"""Campaign adapter for the existing Phase 6 learned decision runtime.

This module does not train or promote a model. It reuses the registered local
Phase 6 artifact, records model output separately from the campaign's final
safe action, and fails closed to the established rule policy.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol

from app.services.decision_head import ACTIONS
from app.services.scientific_state_v2 import SCIENTIFIC_STATE_SCHEMA_VERSION, canonical_state

DecisionMode = Literal["RULE_BASED", "JEV_SHADOW", "JEV_SANDBOX"]
_SUPPORTED = set(ACTIONS)


class DecisionRuntime(Protocol):
    def decide(self, scientific_state: dict[str, Any], *, mode: str) -> dict[str, Any]: ...
    def get_available_actions(self) -> list[str]: ...
    def get_decision_metadata(self) -> dict[str, Any]: ...


class Phase6CampaignRuntime:
    """Thin interface around the already implemented Qwen shared-backbone JEV."""

    def decide(self, scientific_state: dict[str, Any], *, mode: str) -> dict[str, Any]:
        from app.services.phase6_hybrid import get_runtime

        result = get_runtime().infer(scientific_state, "Select the next safe campaign action.",
                                     explanation_requested=False, mode=mode)
        return result

    def get_available_actions(self) -> list[str]:
        return list(ACTIONS)

    def get_decision_metadata(self) -> dict[str, Any]:
        from app.services.phase6_hybrid import (ARTIFACT_VERSION, MODEL_ID,
            MODEL_REVISION, _artifact_path, _default_model_path)
        from pathlib import Path

        return {"model_version": f"{MODEL_ID}@{MODEL_REVISION}/artifact-v{ARTIFACT_VERSION}",
                "artifact_available": Path(_artifact_path()).is_file(),
                "backbone_available": Path(_default_model_path()).is_dir()}


def adapt_campaign_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert the campaign's compact counters into the Phase 6 canonical V2 contract.

    Only persisted counts/readiness are represented. Unknown chemistry, evidence,
    measurements, and provenance stay unknown rather than being inferred.
    """
    count = int(state.get("accepted_observation_count", 0))
    pending = int(state.get("pending_review_count", 0))
    quality_done = bool(state.get("quality_result"))
    provenance = "UNKNOWN" if state.get("mode") == "SANDBOX" else "PARTIAL"
    result = {
        "schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION,
        "experiment": {"method_version_available": bool(state.get("method_version_id")),
                       "process_step_count": None, "required_condition_completeness": None,
                       "required_conditions_known": bool(state.get("method_version_id")),
                       "experiment_state": "UNKNOWN", "review_ready": None},
        "process_conditions": {"items": []},
        "measurements": {"accepted_observation_count": count, "pending_observation_count": pending,
                         "rejected_observation_count": None, "measurement_completeness": None,
                         "available_modality_count": None, "uncertainty_available": None,
                         "uncertainty_missing_count": None, "mean_relative_uncertainty": None,
                         "quality_status": "UNKNOWN", "unit_compatibility": "UNKNOWN",
                         "normalization_status": "UNKNOWN"},
        "analysis": {"available_analysis_type_count": 0, "completed_analysis_count": 1 if quality_done else 0,
                     "pending_analysis_count": 0, "failed_analysis_count": 0,
                     "required_input_available": None, "review_status": "UNKNOWN"},
        "simulation": {"available_tool_count": 0, "input_ready": None, "completed_run_count": 0,
                       "pending_run_count": 0, "failed_run_count": 0,
                       "researcher_approval_required": None, "approval_status": "UNKNOWN"},
        "optimization": {"gp_model_available": count >= 3, "gp_model_valid": None,
                          "training_data_sufficient": count >= 3,
                          "prediction_uncertainty_available": count >= 3,
                          "optimization_ready": bool(state.get("optimization_ready")),
                          "pending_recommendation_review_count": pending,
                          "constraint_validation_status": "UNKNOWN"},
        "tool_readiness": {"analysis_available": quality_done,
                           "simulation_available": False,
                           "optimization_available": bool(state.get("optimization_ready")),
                           "data_validation_available": not quality_done},
        "pending_reviews": {"measurement_review_count": pending, "analysis_review_count": 0,
                            "simulation_review_count": 0, "optimization_review_count": pending},
        "provenance": {"validity": provenance, "source_completeness": "UNKNOWN",
                       "approval_status": "UNKNOWN", "data_quality_gate": "UNKNOWN",
                       "missing_required_information_count": None,
                       "unsupported_tool_state": False, "historical_state_insufficient": True},
        "source_provenance": {"adapter": "campaign-state-v1", "campaign_mode": state.get("mode", "UNKNOWN")},
    }
    return canonical_state(result)


def run_learned_decision(state: dict[str, Any], *, mode: DecisionMode,
                         campaign_mode: str, runtime: DecisionRuntime | None = None) -> dict[str, Any]:
    """Return explicit model-vs-policy metadata; never confuse fallback with JEV output."""
    runtime = runtime or Phase6CampaignRuntime()
    metadata = runtime.get_decision_metadata()
    if mode == "RULE_BASED":
        return {"raw_predicted_action": None, "final_safe_action": None,
                "decision_source": "RULE_BASED", "model_version": None,
                "confidence": None, "ood_status": "NOT_RUN", "reason": "Learned runtime is disabled.",
                "requires_review": False, "fallback_reason": None, "runtime_status": "NOT_REQUESTED"}
    if mode == "JEV_SANDBOX" and campaign_mode != "SANDBOX":
        return {"raw_predicted_action": None, "final_safe_action": None,
                "decision_source": "RULE_BASED_FALLBACK", "model_version": metadata.get("model_version"),
                "confidence": None, "ood_status": "NOT_RUN", "reason": "JEV_SANDBOX is restricted to isolated Sandbox campaigns.",
                "requires_review": True, "fallback_reason": "RESEARCH_MODE_REQUIRES_RULE_POLICY", "runtime_status": "BLOCKED"}
    try:
        canonical = adapt_campaign_state(state)
        infer_mode = "sandbox" if campaign_mode == "SANDBOX" else "research"
        prediction = runtime.decide(canonical, mode=infer_mode)
        raw = prediction.get("raw_predicted_action")
        final = prediction.get("final_safe_action")
        ood = str(prediction.get("ood_status", "UNKNOWN"))
        confidence = prediction.get("confidence")
        if raw not in _SUPPORTED or final not in _SUPPORTED:
            raise ValueError("JEV returned an unsupported action")
        fallback = None
        source = "JEV"
        safe = final
        if ood not in {"IN_DISTRIBUTION_BY_CALIBRATION_THRESHOLD", "IN_DISTRIBUTION"}:
            # Sandbox predictions from synthetic-only artifacts are never
            # promoted on OOD states; let the established rule policy decide.
            safe = None; fallback = "OOD_OR_UNSUPPORTED_STATE"; source = "RULE_BASED_FALLBACK"
        if mode == "JEV_SHADOW":
            safe = None; source = "JEV_SHADOW"
        return {"raw_predicted_action": raw, "final_safe_action": safe,
                "decision_source": source, "model_version": prediction.get("backbone_version") + "/" + prediction.get("decision_head_version") if prediction.get("backbone_version") else metadata.get("model_version"),
                "confidence": confidence, "ood_status": ood,
                "reason": prediction.get("safety_override") or f"JEV predicted {raw}.",
                "requires_review": safe in {"REQUEST_REVIEW", "ABSTAIN"},
                "fallback_reason": fallback, "runtime_status": "COMPLETED",
                "exit_layer": prediction.get("exit_layer"), "decision_latency_ms": prediction.get("decision_latency_ms"),
                "model_validation_status": prediction.get("model_validation_status")}
    except Exception as exc:
        return {"raw_predicted_action": None, "final_safe_action": None,
                "decision_source": "RULE_BASED_FALLBACK", "model_version": metadata.get("model_version"),
                "confidence": None, "ood_status": "NOT_RUN", "reason": "JEV runtime unavailable or incompatible; using safe rule policy.",
                "requires_review": False, "fallback_reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                "runtime_status": "FALLBACK"}
