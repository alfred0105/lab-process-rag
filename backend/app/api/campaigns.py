"""Persistent, approval-gated experiment optimization campaigns (Phase 7 core)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (CampaignEvent, CampaignObservation, Experiment, ExperimentCampaign,
    MaterialAnalysisRun, OptimizationModelRun, OptimizationRecommendationRun, ResearchTopic, ScientificObservation,
    WorkflowNode, WorkflowRun)
from app.services.decision_head import FeatureExtractor
from app.services.campaign_decision_runtime import run_learned_decision
from app.services.optimization.gpbo import GaussianProcess, acquisition, branin, dataset_hash
from app.services.scientific_data import _UNITS
from app.services.tool_registry import ResultValidator, RuleBasedDecisionPolicy, ToolRegistry, ValidationGate

router = APIRouter(prefix="/campaigns", tags=["phase7-campaigns"])
ALLOWED_STATES = {"CREATED", "PLANNING", "RUNNING_ANALYSIS", "RUNNING_SIMULATION", "OPTIMIZING",
    "WAITING_FOR_REVIEW", "WAITING_FOR_RESULT", "COMPLETED", "FAILED", "CANCELLED", "PAUSED"}


class VariableIn(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(default="dimensionless", max_length=80)
    minimum: float
    maximum: float

    @model_validator(mode="after")
    def finite_bounds(self):
        if not math.isfinite(self.minimum) or not math.isfinite(self.maximum) or self.minimum >= self.maximum:
            raise ValueError("Variable bounds must be finite and increasing.")
        return self


class CampaignCreate(BaseModel):
    topic_id: int = Field(gt=0)
    experiment_id: int | None = Field(default=None, gt=0)
    method_version_id: int | None = Field(default=None, gt=0)
    mode: Literal["sandbox", "research"] = "sandbox"
    decision_mode: Literal["RULE_BASED", "JEV_SHADOW", "JEV_SANDBOX"] | None = None
    goal: str = Field(min_length=3, max_length=1000)
    target_property: str = Field(min_length=1, max_length=200)
    direction: Literal["maximize", "minimize"]
    variables: list[VariableIn] = Field(min_length=1, max_length=6)
    fixed_conditions: dict = Field(default_factory=dict)
    max_iterations: int = Field(default=5, ge=1, le=50)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def unique_variables(self):
        ids = [item.id for item in self.variables]
        if len(set(ids)) != len(ids):
            raise ValueError("Variable identifiers must be unique.")
        return self


class IdempotentAction(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ReviewIn(IdempotentAction):
    decision: Literal["APPROVE", "REJECT", "REQUEST_REVISION"]
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2000)


class ObservationIn(IdempotentAction):
    conditions: list[float] = Field(min_length=1, max_length=6)
    target_value: float
    target_unit: str = Field(default="dimensionless", max_length=80)
    source_type: Literal["SANDBOX_SYNTHETIC", "LAB_RESULT"] = "SANDBOX_SYNTHETIC"

    @model_validator(mode="after")
    def finite_result(self):
        if not math.isfinite(self.target_value) or any(not math.isfinite(value) for value in self.conditions):
            raise ValueError("Observation values must be finite.")
        return self


class ObservationReviewIn(IdempotentAction):
    review_status: Literal["ACCEPTED", "REJECTED"]
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2000)


def _event(db: Session, campaign_id: int, event_type: str, status: str, key: str, payload: dict):
    existing = db.query(CampaignEvent).filter_by(campaign_id=campaign_id, idempotency_key=key).first()
    if existing:
        return existing
    item = CampaignEvent(campaign_id=campaign_id, event_type=event_type, status=status,
        idempotency_key=key, payload_json=payload, created_at=datetime.utcnow())
    db.add(item)
    db.flush()
    return item


def _observable(item: CampaignObservation):
    return {"id": item.id, "conditions": item.conditions_json, "target_value": item.target_value,
        "target_unit": item.target_unit, "source_type": item.source_type, "review_status": item.review_status,
        "reviewer": item.reviewer, "review_reason": item.review_reason, "created_at": item.created_at.isoformat() + "Z"}


def _payload(db: Session, item: ExperimentCampaign):
    events = db.query(CampaignEvent).filter_by(campaign_id=item.id).order_by(CampaignEvent.id).all()
    observations = db.query(CampaignObservation).filter_by(campaign_id=item.id).order_by(CampaignObservation.id).all()
    workflow = db.get(WorkflowRun, item.current_workflow_id) if item.current_workflow_id else None
    return {"id": item.id, "topic_id": item.topic_id, "experiment_id": item.experiment_id,
        "method_version_id": item.method_version_id, "mode": item.mode, "goal": item.goal,
        "target_property": item.target_property, "direction": item.direction,
        "variables": item.variables_json, "fixed_conditions": item.fixed_conditions_json,
        "max_iterations": item.max_iterations, "iteration_count": item.iteration_count,
        "state": item.state, "selected_action": item.selected_action, "decision": item.decision_json,
        "workflow": {"id": workflow.id, "status": workflow.status, "result": workflow.result_json,
            "error": workflow.error_text} if workflow else None,
        "model_run_id": item.current_model_run_id, "recommendation_id": item.current_recommendation_id,
        "candidate": item.candidate_json, "review_status": item.review_status,
        "observations": [_observable(row) for row in observations],
        "history": [{"id": row.id, "type": row.event_type, "status": row.status,
            "details": row.payload_json, "created_at": row.created_at.isoformat() + "Z"} for row in events],
        "created_at": item.created_at.isoformat() + "Z", "updated_at": item.updated_at.isoformat() + "Z"}


def _get_campaign(db: Session, campaign_id: int, topic_id: int):
    item = db.query(ExperimentCampaign).filter_by(id=campaign_id, topic_id=topic_id).first()
    if not item:
        raise HTTPException(404, "Campaign not found in this research topic.")
    return item


def _decision(db: Session, item: ExperimentCampaign, *, pending_reviews: int = 0):
    """Use the shared decision policy contract for safe action routing."""
    scientific_state = {
        "campaign_id": item.id,
        "topic_id": item.topic_id,
        "experiment_id": item.experiment_id,
        "mode": item.mode,
        "goal": item.goal,
        "target_property": item.target_property,
        "accepted_observation_count": len(_campaign_observations(db, item)),
        "pending_review_count": pending_reviews,
        "optimization_ready": True,
        "provenance_valid": 1.0 if item.mode == "SANDBOX" or item.experiment_id else 0.0,
        "workflow_state": 1 if item.current_workflow_id else 0,
        "validation_status": 1 if (item.decision_json or {}).get("quality_result") else 0,
    }
    feature_vector = FeatureExtractor.extract(scientific_state).tolist()
    registry = ToolRegistry()
    if not item.goal.strip() or not item.target_property.strip():
        return {"action": "REQUEST_INFORMATION", "policy": "RuleBasedDecisionPolicy",
            "scientific_state": scientific_state, "decision_features": feature_vector,
            "reason": "A research goal and target property are required.", "workflow_triggered": False}
    if pending_reviews:
        return {"action": "REQUEST_REVIEW", "policy": "RuleBasedDecisionPolicy",
            "scientific_state": scientific_state, "decision_features": feature_vector,
            "reason": "A submitted observation is awaiting researcher review.", "workflow_triggered": False}
    if not (item.decision_json or {}).get("quality_result"):
        quality_tool = registry.get("experiment.data_quality.v1")
        gate = ValidationGate.validate({"readiness": "READY", "execution_policy": quality_tool.execution_policy if quality_tool else ""})
        policy_decision = RuleBasedDecisionPolicy().choose(scientific_state,
            [{"tool_id": "experiment.data_quality.v1", "category": "data_quality", "readiness": "READY"}],
            goal="validate experiment record")
        return {"action": "ANALYZE" if gate["allowed"] and policy_decision.get("action") == "RUN_DATA_VALIDATION" else "ABSTAIN",
            "policy": "RuleBasedDecisionPolicy",
            "tool_id": "experiment.data_quality.v1", "scientific_state": scientific_state,
            "decision_features": feature_vector, "validation_gate": gate,
            "reason": policy_decision.get("reason", "Validate the recorded process data before optimization."), "workflow_triggered": False}
    rule_decision = {"action": "OPTIMIZE", "policy": "campaign_optimizer_ready_v1",
        "scientific_state": scientific_state, "decision_features": feature_vector,
        "reason": "Required campaign fields and objective bounds are present.", "workflow_triggered": False}
    decision_mode = (item.decision_json or {}).get("decision_mode", "RULE_BASED")
    learned = run_learned_decision({**scientific_state,
        "quality_result": (item.decision_json or {}).get("quality_result"),
        "method_version_id": item.method_version_id,
        "optimization_ready": item.mode == "SANDBOX" or len(_campaign_observations(db, item)) >= 3},
        mode=decision_mode, campaign_mode=item.mode)
    if decision_mode == "JEV_SHADOW":
        return {**rule_decision, "decision_source": "RULE_BASED_WITH_JEV_SHADOW",
            "decision_mode": decision_mode, "jev": learned,
            "raw_predicted_action": learned.get("raw_predicted_action"),
            "final_safe_action": rule_decision["action"],
            "fallback_reason": learned.get("fallback_reason")}
    if decision_mode == "JEV_SANDBOX" and learned.get("decision_source") == "JEV":
        action = learned.get("final_safe_action")
        if pending_reviews:
            action = "REQUEST_REVIEW"
        elif action == "ANALYZE":
            completed = set((item.decision_json or {}).get("completed_tool_ids", []))
            goal = f"{item.goal} {item.target_property}".casefold()
            aliases = {"xrd": ("xrd", "diffraction", "회절"), "afm": ("afm", "roughness", "거칠기"),
                "sem": ("sem", "tem", "microscopy", "현미경", "입자")}
            runs = (db.query(MaterialAnalysisRun).filter_by(topic_id=item.topic_id,
                experiment_id=item.experiment_id, analysis_status="completed").order_by(MaterialAnalysisRun.id.desc()).all()
                if item.experiment_id else [])
            def rank(run):
                matches = aliases.get(run.modality.casefold(), ())
                return (0 if any(term in goal for term in matches) else 1, -run.id)
            selected = next((run for run in sorted(runs, key=rank)
                if run.tool_id not in completed and (tool := registry.get(run.tool_id)) is not None
                and tool.category == "analysis" and tool.connected
                and ResultValidator.validate(tool, run.result_json or {}).get("valid")), None)
            if selected:
                learned["selected_tool_id"] = selected.tool_id
                learned["tool_readiness"] = "READY"
                learned["analysis_run_id"] = selected.id
            else:
                action = "REQUEST_INFORMATION"
                learned["fallback_reason"] = "NO_COMPATIBLE_REGISTERED_ANALYSIS"
                learned["missing_inputs"] = ["저장된 XRD, AFM 또는 SEM/TEM 분석 결과"]
        elif action == "SIMULATE":
            action = "REQUEST_INFORMATION"
            learned["fallback_reason"] = "NO_COMPATIBLE_CAMPAIGN_SIMULATION_INPUTS"
            learned["missing_inputs"] = ["시뮬레이터가 요구하는 명시적 입력과 연구자 승인"]
        elif action not in {"OPTIMIZE", "REQUEST_INFORMATION", "REQUEST_REVIEW", "ABSTAIN"}:
            action = "ABSTAIN"
            learned["fallback_reason"] = "UNSUPPORTED_CAMPAIGN_ACTION"
        return {**rule_decision, "action": action, "policy": "Phase6HybridRuntime",
            "reason": learned.get("reason") or ("A compatible registered measurement analysis is available." if action == "ANALYZE" else None), "decision_mode": decision_mode,
            "decision_source": learned.get("decision_source"), "jev": learned,
            "tool_id": learned.get("selected_tool_id"),
            "raw_predicted_action": learned.get("raw_predicted_action"),
            "final_safe_action": action, "model_version": learned.get("model_version"),
            "confidence": learned.get("confidence"), "ood_status": learned.get("ood_status"),
            "requires_review": learned.get("requires_review"),
            "fallback_reason": learned.get("fallback_reason")}
    return {**rule_decision, "reason": learned.get("reason") if learned.get("fallback_reason") else rule_decision["reason"],
        "decision_mode": decision_mode,
        "decision_source": learned.get("decision_source", "RULE_BASED"), "jev": learned,
        "raw_predicted_action": None, "final_safe_action": rule_decision["action"]}


def _campaign_observations(db: Session, item: ExperimentCampaign):
    return db.query(CampaignObservation).filter_by(campaign_id=item.id, review_status="ACCEPTED").order_by(CampaignObservation.id).all()


def _research_rows(db: Session, item: ExperimentCampaign):
    from app.api.optimization import TrainRequest, _research_dataset
    req = TrainRequest(topic_id=item.topic_id, mode="research", feature_ids=[x["id"] for x in item.variables_json],
        target_id=item.target_property, method_version_id=item.method_version_id)
    try:
        return _research_dataset(db, req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, detail={"code": "INSUFFICIENT_APPROVED_DATA", "message": str(exc)}) from exc


def _fit_and_recommend(db: Session, item: ExperimentCampaign):
    variables = item.variables_json
    bounds = np.asarray([[float(x["minimum"]), float(x["maximum"])] for x in variables], dtype=float)
    if item.mode == "SANDBOX":
        if item.target_property.casefold() != "branin" or [x["id"] for x in variables] != ["x1", "x2"]:
            raise HTTPException(422, detail={"code": "SANDBOX_OBJECTIVE_UNSUPPORTED", "message": "The first sandbox campaign supports the documented Branin objective with x1 and x2 only."})
        expected = np.asarray([[-5., 10.], [0., 15.]])
        if not np.allclose(bounds, expected):
            raise HTTPException(422, detail={"code": "SANDBOX_BOUNDS_FIXED", "message": "Branin sandbox bounds are fixed to x1 [-5, 10] and x2 [0, 15]."})
        rows = _campaign_observations(db, item)
        x = np.asarray([row.conditions_json for row in rows], dtype=float)
        y = np.asarray([row.target_value for row in rows], dtype=float)
        uncertainty = None
        source_ids = [f"campaign-observation:{row.id}" for row in rows]
        source_type = "SANDBOX_SYNTHETIC"
    else:
        canonical_units = []
        for index, variable in enumerate(variables):
            try:
                low = _UNITS.Quantity(float(variable["minimum"]), variable["unit"]).to_base_units()
                high = _UNITS.Quantity(float(variable["maximum"]), variable["unit"]).to_base_units()
            except Exception as exc:
                raise HTTPException(422, detail={"code": "INVALID_VARIABLE_UNIT", "message": f"Variable '{variable['id']}' has an invalid unit."}) from exc
            bounds[index] = [float(low.magnitude), float(high.magnitude)]
            canonical_units.append(str(low.units))
        rows = _research_rows(db, item)
        x = np.asarray([row["x"] for row in rows], dtype=float)
        y = np.asarray([row["y"] for row in rows], dtype=float)
        uncertainty = np.asarray([float(row.get("uncertainty") or 0.) for row in rows])
        source_ids = [str(row.get("target_observation_id") or "") for row in rows]
        source_type = "APPROVED_LAB_OBSERVATION"
    if len(y) < 3 or len({tuple(np.round(row, 10)) for row in x}) < 3:
        raise HTTPException(409, detail={"code": "INSUFFICIENT_APPROVED_DATA", "message": "At least three distinct eligible observations are required."})
    try:
        model = GaussianProcess.fit(x, y, kernel="matern", noise=1e-6,
            measurement_std=uncertainty)
    except Exception as exc:
        raise HTTPException(422, detail={"code": "GP_FIT_FAILED", "message": str(exc)}) from exc
    rng = np.random.default_rng(1701 + item.iteration_count)
    points = bounds[:, 0] + rng.random((2500, len(bounds))) * (bounds[:, 1] - bounds[:, 0])
    mean, std = model.predict(points, prediction_type="latent")
    incumbent = float(np.max(y) if item.direction == "maximize" else np.min(y))
    score = acquisition(mean, std, incumbent, "ei", maximize=item.direction == "maximize")
    # Exclude exact repeats and select the best-scoring bounded point.
    order = np.argsort(score)[::-1]
    scale = np.maximum(bounds[:, 1] - bounds[:, 0], 1e-12)
    chosen = None
    for index in order:
        candidate = points[int(index)]
        distance = np.min(np.linalg.norm((x - candidate) / scale, axis=1))
        if distance > 1e-4:
            chosen = int(index)
            break
    if chosen is None:
        raise HTTPException(409, "No non-duplicate feasible candidate is available.")
    pred_mean, epistemic, aleatoric, total = model.predict_components(points[chosen:chosen+1])
    candidate = {"rank": 1, "values": points[chosen].tolist(), "variables": [v["id"] for v in variables],
        "units": canonical_units if item.mode == "RESEARCH" else [v["unit"] for v in variables], "predicted_mean": pred_mean[0],
        "epistemic_std": epistemic[0], "aleatoric_std": aleatoric[0], "total_predictive_std": total[0],
        "acquisition": "EI", "acquisition_score": float(score[chosen]), "feasibility_status": "FEASIBLE",
        "approval_status": "PENDING_RESEARCHER_REVIEW", "source_type": source_type,
        "source_ids": source_ids, "prediction_is_not_measurement": True}
    rows_for_hash = [{"x": a.tolist(), "y": float(b)} for a, b in zip(x, y)]
    data_hash = dataset_hash(rows_for_hash)
    model_run = OptimizationModelRun(topic_id=item.topic_id, mode=item.mode.upper(), status="COMPLETED",
        dataset_hash=data_hash, model_version=model.model_version,
        config_json={"campaign_id": item.id, "feature_ids": [v["id"] for v in variables], "target_id": item.target_property,
            "direction": item.direction, "bounds": bounds.tolist(), "source_type": source_type,
            "source_ids": source_ids, "model_version": model.model_version},
        model_json=model.to_dict(), metrics_json={"sample_count": int(len(y)), "unique_conditions": int(len({tuple(a) for a in x}))},
        created_at=datetime.utcnow())
    db.add(model_run); db.flush()
    recommendation = OptimizationRecommendationRun(model_run_id=model_run.id, topic_id=item.topic_id,
        acquisition="EI", config_json={"campaign_id": item.id, "bounds": bounds.tolist(),
            "objective_direction": item.direction, "source_type": source_type,
            "approval_status": "PENDING_RESEARCHER_REVIEW"}, candidates_json=[candidate],
        approval_status="PENDING_RESEARCHER_REVIEW", created_at=datetime.utcnow())
    db.add(recommendation); db.flush()
    item.current_model_run_id = model_run.id
    item.current_recommendation_id = recommendation.id
    item.candidate_json = candidate
    item.iteration_count += 1
    item.state = "WAITING_FOR_REVIEW"
    item.review_status = "PENDING_RESEARCHER_REVIEW"
    item.selected_action = "OPTIMIZE"
    item.updated_at = datetime.utcnow()
    return candidate, model_run, recommendation, data_hash


def _run_campaign_quality(db: Session, item: ExperimentCampaign, key: str):
    tool = ToolRegistry().get("experiment.data_quality.v1")
    if not tool:
        raise HTTPException(503, "Campaign data quality tool is not registered.")
    gate = ValidationGate.validate({"readiness": "READY", "execution_policy": "read_only"})
    if not gate["allowed"]:
        raise HTTPException(409, "Data quality tool failed its execution gate.")
    if item.experiment_id is not None:
        experiment = db.query(Experiment).filter_by(id=item.experiment_id, topic_id=item.topic_id).first()
        if not experiment:
            raise HTTPException(404, "Selected experiment is outside this research topic.")
        if experiment.demo:
            # Demo experiment content remains visibly separate from synthetic campaign objective data.
            record = {"steps": [{"name": step.name, "variables": [{"name": v.name, "value": v.value, "unit": v.unit}
                for v in step.variables]} for step in experiment.steps], "source_type": "DEMO_RECORD"}
        else:
            record = {"steps": [{"name": step.name, "variables": [{"name": v.name, "value": v.value, "unit": v.unit}
                for v in step.variables]} for step in experiment.steps], "source_type": "LAB_RECORD"}
        workflow = None
        if not experiment.demo:
            workflow = WorkflowRun(topic_id=item.topic_id, experiment_id=experiment.id, goal=item.goal,
                status="QUEUED", graph_json={"nodes": [{"key": "validate_record", "tool_id": tool.tool_id,
                    "depends_on": [], "inputs": {}}]}, created_at=datetime.utcnow())
            db.add(workflow); db.flush()
            node = WorkflowNode(workflow_id=workflow.id, node_key="validate_record", tool_id=tool.tool_id,
                dependency_keys=[], input_json={}, created_at=datetime.utcnow(), max_attempts=2)
            db.add(node); db.flush()
            item.current_workflow_id = workflow.id
            item.state = "RUNNING_ANALYSIS"
            item.selected_action = "ANALYZE"
            item.decision_json = {**(item.decision_json or {}), "action": "ANALYZE", "policy": "RuleBasedDecisionPolicy",
                "tool_id": tool.tool_id, "source_type": "LAB_RECORD", "workflow_id": workflow.id,
                "reason": "Campaign routed a read-only record quality check to the existing durable worker.",
                "workflow_triggered": True}
            _event(db, item.id, "TOOL_QUEUED", "QUEUED", key, {"tool_id": tool.tool_id,
                "workflow_id": workflow.id, "source_type": "LAB_RECORD"})
            return None
    else:
        record = {"steps": [{"name": "campaign_inputs", "variables": [
            {"name": v["id"], "value": f"[{v['minimum']}, {v['maximum']}]", "unit": v["unit"]}
            for v in item.variables_json]}], "source_type": "SANDBOX_CAMPAIGN_CONFIG"}
    issues = []
    for step in record["steps"]:
        for variable in step["variables"]:
            if not str(variable.get("value") or "").strip():
                issues.append({"step": step["name"], "field": variable["name"], "issue": "missing_value"})
            elif not variable.get("unit"):
                issues.append({"step": step["name"], "field": variable["name"], "issue": "missing_unit"})
    result = {"issue_count": len(issues), "issues": issues,
        "checked_conditions": sum(len(step["variables"]) for step in record["steps"]),
        "source_type": record["source_type"], "tool_id": tool.tool_id}
    validation = ResultValidator.validate(tool, result)
    if not validation["valid"]:
        raise HTTPException(422, {"reason": "campaign_quality_result_invalid", "validation": validation})
    item.decision_json = {**(item.decision_json or {}), "action": "ANALYZE", "policy": "RuleBasedDecisionPolicy", "tool_id": tool.tool_id,
        "result": result, "quality_result": result, "validation": validation, "workflow_triggered": False,
        "scientific_state": {"campaign_id": item.id, "topic_id": item.topic_id,
            "experiment_id": item.experiment_id, "mode": item.mode, "conditions": record["steps"]}}
    item.selected_action = "ANALYZE"
    item.state = "OPTIMIZING"
    _event(db, item.id, "TOOL_COMPLETED", "COMPLETED", key, {"tool_id": tool.tool_id,
        "result": result, "validation": validation})
    return result


def _queue_campaign_analysis(db: Session, item: ExperimentCampaign, tool_id: str, key: str):
    """Queue a compatible, already uploaded instrument result via the durable Worker."""
    tool = ToolRegistry().get(tool_id)
    if not tool or tool.category != "analysis" or not tool.connected:
        raise HTTPException(422, detail={"code": "CAMPAIGN_TOOL_UNAVAILABLE", "message": "The selected analysis tool is not connected."})
    completed_ids = set((item.decision_json or {}).get("completed_tool_ids", []))
    run = (db.query(MaterialAnalysisRun).filter_by(topic_id=item.topic_id, experiment_id=item.experiment_id,
        tool_id=tool_id, analysis_status="completed").order_by(MaterialAnalysisRun.id.desc()).first())
    if not run:
        item.state = "WAITING_FOR_REVIEW"; item.selected_action = "REQUEST_INFORMATION"
        item.decision_json = {**(item.decision_json or {}), "action": "REQUEST_INFORMATION",
            "final_safe_action": "REQUEST_INFORMATION", "missing_inputs": list(tool.required_inputs),
            "reason": f"{tool.name}가 필요하지만 호환되는 저장 측정 결과가 없습니다."}
        _event(db, item.id, "TOOL_INPUT_REQUIRED", item.state, key,
            {"tool_id": tool_id, "missing_inputs": list(tool.required_inputs)})
        return False
    if tool_id in completed_ids:
        item.state = "WAITING_FOR_REVIEW"; item.selected_action = "REQUEST_REVIEW"
        item.decision_json = {**(item.decision_json or {}), "action": "REQUEST_REVIEW",
            "final_safe_action": "REQUEST_REVIEW", "reason": "이 분석 도구는 이번 캠페인에서 이미 검토했습니다. 추가 입력이나 연구자 검토가 필요합니다."}
        _event(db, item.id, "TOOL_REVIEW_REQUIRED", item.state, key, {"tool_id": tool_id, "reason": "already_executed"})
        return False
    validation = ResultValidator.validate(tool, run.result_json or {})
    if not validation.get("valid"):
        item.state = "WAITING_FOR_REVIEW"; item.selected_action = "REQUEST_REVIEW"
        item.decision_json = {**(item.decision_json or {}), "action": "REQUEST_REVIEW",
            "final_safe_action": "REQUEST_REVIEW", "reason": "저장된 측정 분석 결과가 도구 출력 검증을 통과하지 못했습니다.",
            "validation": validation}
        _event(db, item.id, "TOOL_RESULT_REJECTED", item.state, key, {"tool_id": tool_id, "analysis_run_id": run.id, "validation": validation})
        return False
    gate = ValidationGate.validate({"readiness": "READY", "execution_policy": "read_only"})
    if not gate["allowed"]:
        item.state = "FAILED"; item.selected_action = "ABSTAIN"
        _event(db, item.id, "TOOL_GATE_BLOCKED", item.state, key, {"tool_id": tool_id, "gate": gate})
        return False
    flow = WorkflowRun(topic_id=item.topic_id, experiment_id=item.experiment_id, goal=item.goal,
        status="QUEUED", graph_json={"nodes": [{"key": "campaign_analysis", "tool_id": tool_id,
            "depends_on": [], "inputs": {"analysis_run_id": run.id}}]}, created_at=datetime.utcnow())
    db.add(flow); db.flush()
    node = WorkflowNode(workflow_id=flow.id, node_key="campaign_analysis", tool_id=tool_id,
        dependency_keys=[], input_json={"analysis_run_id": run.id}, created_at=datetime.utcnow(), max_attempts=2)
    db.add(node); db.flush()
    item.current_workflow_id = flow.id; item.state = "RUNNING_ANALYSIS"; item.selected_action = "ANALYZE"
    item.decision_json = {**(item.decision_json or {}), "action": "ANALYZE", "tool_id": tool_id,
        "analysis_run_id": run.id, "workflow_id": flow.id, "workflow_status": "QUEUED",
        "tool_readiness": "READY", "workflow_triggered": True}
    _event(db, item.id, "TOOL_QUEUED", "QUEUED", key,
        {"tool_id": tool_id, "analysis_run_id": run.id, "workflow_id": flow.id,
         "source_sha256": run.sha256, "source_type": "ANALYSIS_OUTPUT"})
    return True


def advance_campaign_from_worker(db: Session, workflow_id: int) -> bool:
    """Consume a completed Campaign Worker exactly once and continue safe steps.

    This runs only after the existing durable Worker commits its result. It can
    validate and optimize automatically, but always stops at researcher review.
    """
    item = db.query(ExperimentCampaign).filter_by(current_workflow_id=workflow_id).first()
    if not item or item.state != "RUNNING_ANALYSIS":
        return False
    event_key = f"campaign-worker-complete:{workflow_id}"
    if db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=event_key).first():
        return False
    flow = db.get(WorkflowRun, workflow_id)
    if not flow:
        return False
    if flow.status in {"FAILED", "TIMED_OUT", "CANCELLED", "BLOCKED", "REQUIRES_REVIEW"}:
        if flow.status == "REQUIRES_REVIEW":
            item.state = "WAITING_FOR_REVIEW"; item.selected_action = "REQUEST_REVIEW"
        else:
            item.state = "FAILED"
        item.decision_json = {**(item.decision_json or {}), "workflow_status": flow.status,
            "final_safe_action": "REQUEST_REVIEW" if item.state == "WAITING_FOR_REVIEW" else "ABSTAIN",
            "reason": flow.error_text or "Campaign Worker stopped; inspect the recorded workflow result."}
        _event(db, item.id, "WORKER_STOPPED", item.state, event_key,
            {"workflow_id": workflow_id, "workflow_status": flow.status, "error": flow.error_text})
        item.updated_at = datetime.utcnow(); db.commit()
        return True
    if flow.status != "COMPLETED":
        return False
    node_result = next((node for node in (flow.result_json or {}).get("nodes", [])
        if node.get("key") in {"validate_record", "campaign_analysis"}), {})
    result = node_result.get("output") or {}
    completed_tool_id = node_result.get("tool_id") or "experiment.data_quality.v1"
    tool = ToolRegistry().get(completed_tool_id)
    output_payload = result.get("result") if completed_tool_id != "experiment.data_quality.v1" else result
    validation = ResultValidator.validate(tool, output_payload or {}) if tool else {"valid": False, "reason": "tool_missing"}
    if not validation.get("valid"):
        item.state = "FAILED"
        item.decision_json = {**(item.decision_json or {}), "result": result, "validation": validation,
            "workflow_status": flow.status, "final_safe_action": "ABSTAIN"}
        _event(db, item.id, "TOOL_RESULT_REJECTED", "FAILED", event_key,
            {"workflow_id": workflow_id, "validation": validation})
        item.updated_at = datetime.utcnow(); db.commit()
        return True
    existing_decision = item.decision_json or {}
    completed_ids = list(existing_decision.get("completed_tool_ids", []))
    if completed_tool_id not in completed_ids:
        completed_ids.append(completed_tool_id)
    item.decision_json = {**existing_decision, "result": result,
        "tool_result": output_payload, "quality_result": result if completed_tool_id == "experiment.data_quality.v1" else existing_decision.get("quality_result"),
        "completed_tool_ids": completed_ids, "validation": validation, "workflow_status": flow.status}
    if completed_tool_id == "experiment.data_quality.v1" and int(result.get("issue_count", 0)) > 0:
        item.state = "WAITING_FOR_REVIEW"; item.selected_action = "REQUEST_REVIEW"
        item.decision_json = {**item.decision_json, "action": "REQUEST_REVIEW",
            "final_safe_action": "REQUEST_REVIEW",
            "reason": "Record validation found missing or incomplete process entries; correct or review them before optimization."}
        _event(db, item.id, "TOOL_REQUIRES_REVIEW", item.state, event_key,
            {"workflow_id": workflow_id, "result": result, "validation": validation})
        item.updated_at = datetime.utcnow(); db.commit()
        return True
    item.state = "OPTIMIZING"
    pending = db.query(CampaignObservation).filter_by(campaign_id=item.id, review_status="PENDING").count()
    decision = _decision(db, item, pending_reviews=pending)
    item.selected_action = decision["action"]
    item.decision_json = {**item.decision_json, **decision, "result": result,
        "quality_result": item.decision_json.get("quality_result"), "validation": validation, "workflow_id": workflow_id,
        "workflow_status": flow.status, "synthetic_data_isolated": item.mode == "SANDBOX"}
    if decision["action"] == "ANALYZE":
        _queue_campaign_analysis(db, item, decision.get("tool_id", ""), event_key)
    elif decision["action"] == "OPTIMIZE":
        try:
            candidate, model_run, recommendation, d_hash = _fit_and_recommend(db, item)
        except HTTPException as exc:
            item.state = "FAILED" if exc.status_code >= 500 else "WAITING_FOR_REVIEW"
            item.selected_action = "REQUEST_INFORMATION"
            item.decision_json = {**item.decision_json, "action": "REQUEST_INFORMATION",
                "final_safe_action": "REQUEST_INFORMATION", "reason": str(exc.detail),
                "missing_inputs": [str(exc.detail)]}
            _event(db, item.id, "OPTIMIZATION_BLOCKED", item.state, event_key, {"detail": exc.detail})
            item.updated_at = datetime.utcnow(); db.commit()
            return True
        item.current_model_run_id = model_run.id; item.current_recommendation_id = recommendation.id
        item.candidate_json = candidate
        item.review_status = "PENDING_RESEARCHER_REVIEW"; item.state = "WAITING_FOR_REVIEW"
        _event(db, item.id, "CANDIDATE_PROPOSED", item.state, event_key,
            {"candidate": candidate, "model_run_id": model_run.id,
             "recommendation_id": recommendation.id, "dataset_hash": d_hash,
             "source_type": candidate["source_type"], "approval_required": True,
             "worker_auto_advance": True})
    elif decision["action"] != "ANALYZE":
        item.state = "WAITING_FOR_REVIEW" if decision["action"] in {"REQUEST_REVIEW", "REQUEST_INFORMATION"} else "FAILED"
        _event(db, item.id, "DECISION_STOPPED", item.state, event_key, decision)
    item.updated_at = datetime.utcnow(); db.commit()
    return True


@router.post("", status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    topic = db.get(ResearchTopic, payload.topic_id)
    if not topic:
        raise HTTPException(404, "Research topic not found.")
    existing_event = db.query(CampaignEvent).filter_by(idempotency_key=payload.idempotency_key).first()
    if existing_event:
        existing = db.get(ExperimentCampaign, existing_event.campaign_id)
        if existing and existing.topic_id == payload.topic_id:
            return _payload(db, existing)
        raise HTTPException(409, "Idempotency key is already used by another campaign.")
    if payload.mode == "research":
        if not payload.experiment_id or not payload.method_version_id:
            raise HTTPException(422, detail={"code": "RESEARCH_RECORD_REQUIRED", "message": "Research campaigns require a non-demo experiment and its Method Version."})
        experiment = db.query(Experiment).filter_by(id=payload.experiment_id, topic_id=payload.topic_id).first()
        if not experiment or experiment.demo or experiment.method_version_id != payload.method_version_id:
            raise HTTPException(422, detail={"code": "UNVERIFIED_RESEARCH_PROVENANCE", "message": "Research campaign must reference a non-demo experiment in this topic and the matching Method Version."})
        if len(payload.variables) < 1:
            raise HTTPException(422, "At least one controllable variable is required.")
        if payload.decision_mode == "JEV_SANDBOX":
            raise HTTPException(422, detail={"code": "JEV_SANDBOX_RESEARCH_FORBIDDEN", "message": "JEV Sandbox routing is limited to isolated synthetic campaigns."})
    elif payload.target_property.casefold() != "branin" or [x.id for x in payload.variables] != ["x1", "x2"]:
        raise HTTPException(422, detail={"code": "SANDBOX_OBJECTIVE_UNSUPPORTED", "message": "The first sandbox campaign uses the labeled Branin benchmark with x1 and x2."})
    decision_mode = payload.decision_mode or ("JEV_SANDBOX" if payload.mode == "sandbox" else "RULE_BASED")
    item = ExperimentCampaign(topic_id=payload.topic_id, experiment_id=payload.experiment_id,
        method_version_id=payload.method_version_id, mode=payload.mode.upper(), goal=payload.goal.strip(),
        target_property=payload.target_property.strip(), direction=payload.direction,
        variables_json=[x.model_dump() for x in payload.variables], fixed_conditions_json=payload.fixed_conditions,
        max_iterations=payload.max_iterations, state="CREATED", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    item.decision_json = {"decision_mode": decision_mode}
    db.add(item); db.flush()
    _event(db, item.id, "CAMPAIGN_CREATED", "CREATED", payload.idempotency_key,
        {"mode": item.mode, "goal": item.goal, "target_property": item.target_property,
            "synthetic_data_separate": item.mode == "SANDBOX"})
    if item.mode == "SANDBOX":
        design = [[-4., 2.], [0., 10.], [5., 5.], [10., 15.], [-2., 13.], [7., 1.]]
        for index, values in enumerate(design):
            row = CampaignObservation(campaign_id=item.id, conditions_json=values, target_value=float(branin(np.asarray([values]))[0]),
                target_unit="objective", source_type="SANDBOX_SYNTHETIC", review_status="ACCEPTED",
                idempotency_key=f"initial-synthetic-{index+1}", reviewer="benchmark-fixture", review_reason="Deterministic Branin sandbox fixture only.",
                created_at=datetime.utcnow(), reviewed_at=datetime.utcnow())
            db.add(row)
        _event(db, item.id, "SANDBOX_FIXTURE_CREATED", "SYNTHETIC_ONLY", f"{payload.idempotency_key}:seed",
            {"benchmark": "Branin", "count": len(design), "source_type": "SANDBOX_SYNTHETIC", "not_lab_measurements": True})
    db.commit(); db.refresh(item)
    return _payload(db, item)


@router.get("")
def list_campaigns(topic_id: int, db: Session = Depends(get_db)):
    if not db.get(ResearchTopic, topic_id):
        raise HTTPException(404, "Research topic not found.")
    return [_payload(db, item) for item in db.query(ExperimentCampaign).filter_by(topic_id=topic_id).order_by(ExperimentCampaign.updated_at.desc()).limit(100).all()]


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, topic_id: int, db: Session = Depends(get_db)):
    return _payload(db, _get_campaign(db, campaign_id, topic_id))


@router.post("/{campaign_id}/advance")
def advance_campaign(campaign_id: int, topic_id: int, payload: IdempotentAction, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    previous = db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first()
    if previous:
        return _payload(db, item)
    if item.state in {"CANCELLED", "COMPLETED", "FAILED", "PAUSED"}:
        raise HTTPException(409, f"Campaign cannot advance from {item.state}.")
    if item.iteration_count >= item.max_iterations:
        item.state = "COMPLETED"; _event(db, item.id, "CAMPAIGN_COMPLETED", "COMPLETED", payload.idempotency_key, {"reason": "max_iterations_reached"})
        db.commit(); return _payload(db, item)
    if item.state in {"WAITING_FOR_REVIEW", "WAITING_FOR_RESULT", "RUNNING_ANALYSIS", "RUNNING_SIMULATION"}:
        if item.state == "RUNNING_ANALYSIS" and item.current_workflow_id:
            flow = db.get(WorkflowRun, item.current_workflow_id)
            if flow and flow.status in {"FAILED", "TIMED_OUT", "CANCELLED", "BLOCKED"}:
                item.state = "FAILED"; _event(db, item.id, "TOOL_FAILED", "FAILED", payload.idempotency_key, {"workflow_id": flow.id, "error": flow.error_text})
                db.commit(); return _payload(db, item)
            if flow and flow.status == "REQUIRES_REVIEW":
                node_result = next((node for node in (flow.result_json or {}).get("nodes", [])
                    if node.get("key") == "validate_record"), {})
                item.state = "FAILED"
                item.selected_action = "REQUEST_REVIEW"
                item.decision_json = {**(item.decision_json or {}), "action": "REQUEST_REVIEW",
                    "workflow_status": flow.status, "result": node_result.get("output") or {},
                    "reason": "The existing record-quality gate found missing or incomplete recorded conditions. Correct the source record before starting a new campaign."}
                _event(db, item.id, "TOOL_REQUIRES_REVIEW", "FAILED", payload.idempotency_key,
                    {"workflow_id": flow.id, "result": item.decision_json["result"]})
                db.commit(); db.refresh(item); return _payload(db, item)
            if flow and flow.status not in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "BLOCKED"}:
                return _payload(db, item)
            if flow and flow.status != "COMPLETED":
                item.state = "FAILED"; _event(db, item.id, "TOOL_FAILED", "FAILED", payload.idempotency_key,
                    {"workflow_id": flow.id, "status": flow.status, "error": flow.error_text})
                db.commit(); db.refresh(item); return _payload(db, item)
            if flow and flow.status == "COMPLETED":
                node_result = next((node for node in (flow.result_json or {}).get("nodes", [])
                    if node.get("key") == "validate_record"), {})
                result = node_result.get("output") or {}
                tool = ToolRegistry().get("experiment.data_quality.v1")
                validation = ResultValidator.validate(tool, result) if tool else {"valid": False, "reason": "tool_missing"}
                if not validation.get("valid"):
                    item.state = "FAILED"
                    item.decision_json = {**(item.decision_json or {}), "result": result,
                        "validation": validation, "workflow_status": flow.status}
                    _event(db, item.id, "TOOL_RESULT_REJECTED", "FAILED", payload.idempotency_key,
                        {"workflow_id": flow.id, "validation": validation})
                    db.commit(); db.refresh(item); return _payload(db, item)
                item.decision_json = {**(item.decision_json or {}), "result": result,
                    "quality_result": result, "validation": validation, "workflow_status": flow.status}
                item.state = "OPTIMIZING"
        else:
            raise HTTPException(409, f"Campaign is waiting at {item.state}; complete its review or result step first.")
    if item.state == "CREATED" and not (item.decision_json or {}).get("quality_result"):
        if item.experiment_id is not None:
            _run_campaign_quality(db, item, payload.idempotency_key)
            if item.state == "RUNNING_ANALYSIS":
                db.commit(); db.refresh(item); return _payload(db, item)
        else:
            _run_campaign_quality(db, item, payload.idempotency_key)
    pending = db.query(CampaignObservation).filter_by(campaign_id=item.id, review_status="PENDING").count()
    decision = _decision(db, item, pending_reviews=pending)
    prior_decision = item.decision_json or {}
    item.selected_action = decision["action"]
    item.decision_json = {**prior_decision, **decision,
        "quality_result": prior_decision.get("quality_result", prior_decision.get("result")),
        "result": prior_decision.get("result"), "validation": prior_decision.get("validation"),
        "workflow_id": prior_decision.get("workflow_id"), "workflow_status": prior_decision.get("workflow_status"),
        "synthetic_data_isolated": item.mode == "SANDBOX"}
    if decision["action"] == "REQUEST_INFORMATION":
        item.state = "WAITING_FOR_REVIEW"
        _event(db, item.id, "INFORMATION_REQUIRED", item.state, payload.idempotency_key, decision)
    elif decision["action"] == "REQUEST_REVIEW":
        item.state = "WAITING_FOR_REVIEW"
        _event(db, item.id, "REVIEW_REQUIRED", item.state, payload.idempotency_key, decision)
    elif decision["action"] in {"ABSTAIN", "REQUEST_DATA"}:
        item.state = "FAILED"
        _event(db, item.id, "DECISION_STOPPED", item.state, payload.idempotency_key, decision)
    elif decision["action"] == "ANALYZE":
        _queue_campaign_analysis(db, item, decision.get("tool_id", ""), payload.idempotency_key)
    elif decision["action"] == "OPTIMIZE":
        try:
            candidate, model_run, recommendation, d_hash = _fit_and_recommend(db, item)
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict) and exc.detail.get("code") == "INSUFFICIENT_APPROVED_DATA":
                item.state = "FAILED"
                item.selected_action = "REQUEST_INFORMATION"
                item.decision_json = {**(item.decision_json or {}), "action": "REQUEST_INFORMATION",
                    "reason": exc.detail.get("message", "Insufficient approved observations."),
                    "missing_information": ["At least three distinct eligible accepted observations"]}
                _event(db, item.id, "OPTIMIZATION_BLOCKED", "INSUFFICIENT_APPROVED_DATA", payload.idempotency_key,
                    {"detail": exc.detail})
                db.commit()
            raise
        _event(db, item.id, "CANDIDATE_PROPOSED", item.state, payload.idempotency_key,
            {"candidate": candidate, "model_run_id": model_run.id, "recommendation_id": recommendation.id,
                "dataset_hash": d_hash, "source_type": candidate["source_type"], "approval_required": True})
    item.updated_at = datetime.utcnow()
    db.commit(); db.refresh(item)
    return _payload(db, item)


@router.post("/{campaign_id}/review")
def review_candidate(campaign_id: int, topic_id: int, payload: ReviewIn, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    if db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first():
        return _payload(db, item)
    if item.state != "WAITING_FOR_REVIEW" or not item.candidate_json or item.review_status != "PENDING_RESEARCHER_REVIEW":
        raise HTTPException(409, "There is no pending candidate to review.")
    if payload.decision == "APPROVE":
        item.review_status = "APPROVED"; item.state = "WAITING_FOR_RESULT"
        if item.current_recommendation_id:
            rec = db.get(OptimizationRecommendationRun, item.current_recommendation_id); rec.approval_status = "APPROVED"
    elif payload.decision == "REJECT":
        item.review_status = "REJECTED"; item.state = "OPTIMIZING"
        if item.current_recommendation_id:
            rec = db.get(OptimizationRecommendationRun, item.current_recommendation_id); rec.approval_status = "REJECTED"
    else:
        item.review_status = "REVISION_REQUESTED"; item.state = "OPTIMIZING"
    _event(db, item.id, "CANDIDATE_REVIEWED", payload.decision, payload.idempotency_key,
        {"reviewer": payload.reviewer, "reason": payload.reason, "candidate": item.candidate_json})
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item)
    return _payload(db, item)


@router.post("/{campaign_id}/observations")
def submit_campaign_observation(campaign_id: int, topic_id: int, payload: ObservationIn, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    previous = db.query(CampaignObservation).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first()
    if previous:
        return {"campaign": _payload(db, item), "observation": _observable(previous)}
    if item.state != "WAITING_FOR_RESULT" or not item.candidate_json:
        raise HTTPException(409, "An approved candidate is required before recording a result.")
    if item.mode == "RESEARCH":
        raise HTTPException(422, detail={"code": "RESEARCH_OBSERVATION_LINK_REQUIRED", "message": "Research observations must be linked from an existing reviewed ScientificObservation; synthetic feedback is disabled."})
    if payload.source_type != "SANDBOX_SYNTHETIC" or payload.target_unit != "objective":
        raise HTTPException(422, "Sandbox feedback must stay labeled SANDBOX_SYNTHETIC with objective units.")
    if len(payload.conditions) != len(item.variables_json) or not np.allclose(payload.conditions, item.candidate_json["values"], rtol=0, atol=1e-9):
        raise HTTPException(422, detail={"code": "RESULT_CONDITIONS_MISMATCH", "message": "Submitted result conditions must match the researcher-approved candidate."})
    observation = CampaignObservation(campaign_id=item.id, conditions_json=payload.conditions,
        target_value=payload.target_value, target_unit=payload.target_unit, source_type="SANDBOX_SYNTHETIC",
        review_status="PENDING", idempotency_key=payload.idempotency_key, created_at=datetime.utcnow())
    db.add(observation); db.flush()
    item.state = "WAITING_FOR_REVIEW"; item.review_status = "OBSERVATION_REVIEW_PENDING"
    _event(db, item.id, "OBSERVATION_SUBMITTED", "PENDING", f"{payload.idempotency_key}:event",
        {"observation_id": observation.id, "source_type": "SANDBOX_SYNTHETIC", "not_lab_measurement": True})
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item)
    return {"campaign": _payload(db, item), "observation": _observable(observation)}


@router.post("/{campaign_id}/observations/{observation_id}/review")
def review_observation(campaign_id: int, observation_id: int, topic_id: int, payload: ObservationReviewIn, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    observation = db.query(CampaignObservation).filter_by(id=observation_id, campaign_id=item.id).first()
    if not observation:
        raise HTTPException(404, "Campaign observation not found.")
    if db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first():
        return _payload(db, item)
    if observation.review_status != "PENDING":
        raise HTTPException(409, "Observation has already been reviewed.")
    observation.review_status = payload.review_status; observation.reviewer = payload.reviewer
    observation.review_reason = payload.reason; observation.reviewed_at = datetime.utcnow()
    item.state = "OPTIMIZING" if payload.review_status == "ACCEPTED" else "WAITING_FOR_RESULT"
    item.review_status = payload.review_status
    _event(db, item.id, "OBSERVATION_REVIEWED", payload.review_status, payload.idempotency_key,
        {"observation_id": observation.id, "reviewer": payload.reviewer, "reason": payload.reason,
            "source_type": observation.source_type})
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item)
    return _payload(db, item)


class LinkObservationIn(IdempotentAction):
    observation_id: int = Field(gt=0)


@router.post("/{campaign_id}/observations/link")
def link_research_observation(campaign_id: int, topic_id: int, payload: LinkObservationIn, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    if item.mode != "RESEARCH" or item.state != "WAITING_FOR_RESULT" or item.review_status != "APPROVED":
        raise HTTPException(409, "An approved Research candidate is required before linking a measured result.")
    previous = db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first()
    if previous:
        return _payload(db, item)
    observation = db.get(ScientificObservation, payload.observation_id)
    if (not observation or observation.topic_id != item.topic_id
            or observation.method_version_id != item.method_version_id or observation.review_status != "ACCEPTED"
            or observation.normalization_error or observation.normalized_value is None
            or observation.source_type not in {"LAB_RESULT", "ANALYSIS_OUTPUT"}):
        raise HTTPException(422, detail={"code": "INELIGIBLE_RESEARCH_OBSERVATION",
            "message": "Only accepted, normalized lab or analysis observations from a non-demo experiment in this topic and Method Version can be linked."})
    if observation.parameter_id != item.target_property:
        raise HTTPException(422, detail={"code": "CAMPAIGN_TARGET_MISMATCH",
            "message": "The observation must measure this Campaign's target property."})
    result_experiment = db.get(Experiment, observation.experiment_id) if observation.experiment_id else None
    if not result_experiment or result_experiment.demo or result_experiment.method_version_id != item.method_version_id:
        raise HTTPException(422, detail={"code": "UNVERIFIED_RESEARCH_PROVENANCE",
            "message": "Linked result must belong to a non-demo experiment using this Method Version."})
    feature_rows = db.query(ScientificObservation).filter(
        ScientificObservation.experiment_id == result_experiment.id,
        ScientificObservation.topic_id == item.topic_id,
        ScientificObservation.method_version_id == item.method_version_id,
        ScientificObservation.review_status == "ACCEPTED",
        ScientificObservation.source_type == "LAB_RECORD",
        ScientificObservation.normalization_error.is_(None),
        ScientificObservation.normalized_value.is_not(None),
    ).all()
    for index, variable in enumerate(item.variables_json):
        rows = [row for row in feature_rows if row.parameter_id == variable["id"]]
        if len(rows) != 1:
            raise HTTPException(422, detail={"code": "CAMPAIGN_CONDITION_PAIRING_REQUIRED",
                "message": f"The result experiment must have exactly one accepted recorded value for condition '{variable['id']}'."})
        row = rows[0]
        try:
            candidate_unit = (item.candidate_json.get("units") or [variable["unit"]] * len(item.variables_json))[index]
            observed_value = _UNITS.Quantity(float(row.normalized_value), row.normalized_unit).to_base_units().magnitude
            proposed_value = float(_UNITS.Quantity(float(item.candidate_json["values"][index]), candidate_unit).to_base_units().magnitude)
        except Exception as exc:
            raise HTTPException(422, detail={"code": "CAMPAIGN_CONDITION_UNIT_MISMATCH",
                "message": f"Condition '{variable['id']}' has incompatible or missing units."}) from exc
        if not math.isclose(float(observed_value), proposed_value, rel_tol=1e-7, abs_tol=1e-9):
            raise HTTPException(422, detail={"code": "RESULT_CONDITIONS_MISMATCH",
                "message": f"The measured run's '{variable['id']}' value does not match the approved candidate."})
    _event(db, item.id, "RESEARCH_OBSERVATION_LINKED", "ACCEPTED", payload.idempotency_key,
        {"observation_id": observation.id, "experiment_id": result_experiment.id, "parameter_id": observation.parameter_id,
            "value": observation.normalized_value, "unit": observation.normalized_unit,
            "source_type": observation.source_type, "review_status": observation.review_status})
    item.state = "OPTIMIZING"; item.review_status = "RESULT_LINKED"; item.updated_at = datetime.utcnow()
    db.commit(); db.refresh(item)
    return _payload(db, item)


@router.post("/{campaign_id}/pause")
def pause_campaign(campaign_id: int, topic_id: int, payload: IdempotentAction, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    if db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first():
        return _payload(db, item)
    if item.state in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise HTTPException(409, f"Campaign cannot pause from {item.state}.")
    prior_state = item.state
    item.state = "PAUSED"; _event(db, item.id, "PAUSED", item.state, payload.idempotency_key, {"previous_state": prior_state})
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item); return _payload(db, item)


@router.post("/{campaign_id}/resume")
def resume_campaign(campaign_id: int, topic_id: int, payload: IdempotentAction, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    if db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first():
        return _payload(db, item)
    if item.state != "PAUSED": raise HTTPException(409, "Only a paused campaign can resume.")
    last_pause = db.query(CampaignEvent).filter_by(campaign_id=item.id, event_type="PAUSED").order_by(CampaignEvent.id.desc()).first()
    prior_state = (last_pause.payload_json or {}).get("previous_state") if last_pause else None
    if prior_state == "RUNNING_ANALYSIS" and item.current_workflow_id:
        workflow = db.get(WorkflowRun, item.current_workflow_id)
        prior_state = "FAILED" if workflow and workflow.status == "CANCELLED" else "RUNNING_ANALYSIS"
    item.state = prior_state if prior_state in ALLOWED_STATES - {"PAUSED"} else (
        "WAITING_FOR_REVIEW" if item.review_status == "PENDING_RESEARCHER_REVIEW" else
        "WAITING_FOR_RESULT" if item.review_status == "APPROVED" else "OPTIMIZING" if item.candidate_json else "CREATED")
    _event(db, item.id, "RESUMED", item.state, payload.idempotency_key, {"previous_state": item.state})
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item); return _payload(db, item)


@router.post("/{campaign_id}/cancel")
def cancel_campaign(campaign_id: int, topic_id: int, payload: IdempotentAction, db: Session = Depends(get_db)):
    item = _get_campaign(db, campaign_id, topic_id)
    if db.query(CampaignEvent).filter_by(campaign_id=item.id, idempotency_key=payload.idempotency_key).first():
        return _payload(db, item)
    if item.state == "COMPLETED": raise HTTPException(409, "Completed campaign cannot be cancelled.")
    if item.current_workflow_id:
        workflow = db.get(WorkflowRun, item.current_workflow_id)
        if workflow and workflow.status in {"QUEUED", "RUNNING"}:
            workflow.cancel_requested = True
            for node in db.query(WorkflowNode).filter_by(workflow_id=workflow.id).all():
                if node.status in {"QUEUED", "WAITING_FOR_CACHE"}:
                    node.status = "CANCELLED"; node.error_code = "CAMPAIGN_CANCELLED"; node.finished_at = datetime.utcnow()
                elif node.status == "RUNNING":
                    node.cancel_requested = True
            if not db.query(WorkflowNode).filter_by(workflow_id=workflow.id, status="RUNNING").count():
                workflow.status = "CANCELLED"; workflow.finished_at = datetime.utcnow()
    item.state = "CANCELLED"; _event(db, item.id, "CANCELLED", item.state, payload.idempotency_key, {})
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item); return _payload(db, item)
