"""Stage 3 explicit two-objective endpoints; single-objective routes stay unchanged."""
from __future__ import annotations

import json
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.optimization import _canonical_observation, _group_holdout_indices, _topic
from app.db.database import get_db
from app.db.models import Experiment, OptimizationModelRun, OptimizationRecommendationRun, ProcessStep, ScientificObservation
from app.services.optimization.constraints import compile_constraints, constraints_feasible, feasible_mask
from app.services.optimization.gpbo import GaussianProcess, OptimizationInputError, dataset_hash, metrics
from app.services.optimization.multiobjective import MODEL_VERSION, greedy_batch, hypervolume_2d, pareto_front, run_moo_benchmarks, zdt1
from app.services.scientific_data import _UNITS

router = APIRouter(prefix="/optimization/multiobjective", tags=["multiobjective-optimization"])


class TrainRequest(BaseModel):
    topic_id: int = Field(gt=0)
    mode: Literal["research", "sandbox"] = "research"
    feature_ids: list[str] = Field(min_length=1, max_length=6)
    objective_ids: list[str] = Field(min_length=2, max_length=2)
    objective_directions: list[Literal["minimize", "maximize"]] = Field(min_length=2, max_length=2)
    method_version_id: int | None = Field(default=None, gt=0)
    process_step_id: int | None = Field(default=None, gt=0)
    objective_process_step_id: int | None = Field(default=None, gt=0)
    pairing_policy: Literal["same_step", "downstream_explicit"] = "same_step"
    downstream_link_confirmed: bool = False
    downstream_relation_label: str | None = Field(default=None, max_length=240)
    kernel: Literal["rbf", "matern"] = "matern"
    noise: float = Field(default=1e-6, ge=0, le=1)
    seed: int = 7
    sandbox_samples: int = Field(default=48, ge=20, le=300)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.feature_ids)) != len(self.feature_ids) or len(set(self.objective_ids)) != 2:
            raise ValueError("Feature IDs and the two objective IDs must be unique")
        if set(self.feature_ids) & set(self.objective_ids):
            raise ValueError("Input features and objectives must be distinct")
        return self


class PredictRequest(BaseModel):
    topic_id: int = Field(gt=0)
    candidates: list[list[float]] = Field(min_length=1, max_length=1000)


class RecommendRequest(BaseModel):
    topic_id: int = Field(gt=0)
    bounds: list[list[float]] = Field(min_length=1, max_length=6)
    bounds_units: list[str] | None = None
    reference_point: list[float] = Field(min_length=2, max_length=2)
    objective_scales: list[float] = Field(default_factory=lambda: [1.0, 1.0], min_length=2, max_length=2)
    batch_size: int = Field(default=1, ge=1, le=4)
    search_budget: int = Field(default=400, ge=32, le=2000)
    monte_carlo_samples: int = Field(default=256, ge=32, le=4096)
    seed: int = 7
    min_candidate_distance: float = Field(default=0.02, ge=0)
    constraints: list[dict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def finite_bounds(self):
        if any(len(pair) != 2 or not np.isfinite(pair).all() or pair[0] >= pair[1] for pair in self.bounds):
            raise ValueError("Every bound must be a finite increasing [minimum, maximum] pair")
        if not np.isfinite(self.reference_point).all() or not np.isfinite(self.objective_scales).all() or any(x <= 0 for x in self.objective_scales):
            raise ValueError("Reference point must be finite and scales must be positive")
        return self


def _research_rows(db, request):
    if not request.method_version_id:
        raise HTTPException(422, detail={"code": "METHOD_VERSION_REQUIRED", "message": "Research mode requires a method version."})
    def resolve_step(step_id):
        if not step_id:
            return None
        row = (db.query(ProcessStep, Experiment).join(Experiment, Experiment.id == ProcessStep.experiment_id)
            .filter(ProcessStep.id == step_id, Experiment.topic_id == request.topic_id,
                    Experiment.method_version_id == request.method_version_id, Experiment.demo.is_(False)).first())
        if not row:
            raise HTTPException(422, detail={"code": "INVALID_PROCESS_STEP_PAIR", "message": "Selected steps must belong to the selected real topic and method version."})
        step, _exp = row
        # A selected ProcessStep is an anchor for its method position/name across
        # all runs; row IDs are per-experiment and must never be exact-joined.
        return (step.order_index, step.name.casefold())
    feature_anchor = resolve_step(request.process_step_id)
    objective_anchor = resolve_step(request.objective_process_step_id)
    if request.pairing_policy == "downstream_explicit":
        if not request.downstream_link_confirmed or not request.downstream_relation_label or not request.process_step_id or not request.objective_process_step_id:
            raise HTTPException(422, detail={"code": "PAIRING_CONFIRMATION_REQUIRED", "message": "Explicit downstream pairing requires both steps and a researcher-confirmed relationship."})
        if feature_anchor[0] >= objective_anchor[0]:
            raise HTTPException(422, detail={"code": "INVALID_PROCESS_STEP_PAIR", "message": "The objective step must follow the input step."})
    else:
        if feature_anchor and objective_anchor and feature_anchor != objective_anchor:
            raise HTTPException(422, detail={"code": "AMBIGUOUS_PROCESS_STEP", "message": "Same-step pairing requires a single shared method step."})
        shared_anchor = feature_anchor or objective_anchor
        feature_anchor = objective_anchor = shared_anchor
    q = (db.query(ScientificObservation, Experiment)
         .join(Experiment, Experiment.id == ScientificObservation.experiment_id)
         .filter(Experiment.topic_id == request.topic_id, Experiment.demo.is_(False),
                 Experiment.method_version_id == request.method_version_id,
                 ScientificObservation.topic_id == request.topic_id,
                 ScientificObservation.method_version_id == request.method_version_id,
                 ScientificObservation.review_status == "ACCEPTED",
                 ScientificObservation.normalization_error.is_(None),
                 ScientificObservation.normalized_value.is_not(None),
                 ScientificObservation.parameter_id.in_(request.feature_ids + request.objective_ids),
                 ScientificObservation.source_type.in_(["LAB_RECORD", "LAB_RESULT", "ANALYSIS_OUTPUT"])))
    observations = q.order_by(ScientificObservation.id).all()
    grouped = {}
    for obs, exp in observations:
        step = db.get(ProcessStep, obs.process_step_id) if obs.process_step_id else None
        if obs.process_step_id and (not step or step.experiment_id != exp.id):
            continue
        expected_step = feature_anchor if obs.parameter_id in request.feature_ids else objective_anchor
        step_identity = (step.order_index, step.name.casefold()) if step else None
        if expected_step and step_identity != expected_step:
            continue
        group = grouped.setdefault(exp.id, {"exp": exp, "features": {}, "objectives": {}})
        target = "features" if obs.parameter_id in request.feature_ids and obs.source_type == "LAB_RECORD" else "objectives" if obs.parameter_id in request.objective_ids and obs.source_type in {"LAB_RESULT", "ANALYSIS_OUTPUT"} else None
        if target:
            group[target].setdefault((obs.parameter_id, obs.replicate_id), []).append(obs)
    rows = []
    incomplete = 0
    for exp_id, group in grouped.items():
        # Pair objective values only within the same experiment and compatible
        # replicate; experiment-level measurements may match a named replicate.
        for replicate in sorted({rep for (_oid, rep) in group["objectives"]}, key=lambda v: v or ""):
            objective_rows = []
            for oid in request.objective_ids:
                exact = group["objectives"].get((oid, replicate), [])
                shared = group["objectives"].get((oid, None), [])
                matches = exact if replicate is not None and exact else shared if replicate is not None else exact
                if len(matches) != 1:
                    objective_rows = []; break
                objective_rows.append(matches[0])
            if not objective_rows:
                incomplete += 1; continue
            selected_features = []
            for fid in request.feature_ids:
                exact = group["features"].get((fid, replicate), [])
                shared = group["features"].get((fid, None), [])
                matches = exact if replicate is not None and exact else shared if replicate is not None else exact
                if len(matches) != 1:
                    selected_features = []; break
                selected_features.append(matches[0])
            if len(selected_features) != len(request.feature_ids):
                incomplete += 1; continue
            if request.pairing_policy == "same_step" and any(
                ((db.get(ProcessStep, feature.process_step_id).order_index, db.get(ProcessStep, feature.process_step_id).name.casefold()) if feature.process_step_id else None)
                != ((db.get(ProcessStep, objective.process_step_id).order_index, db.get(ProcessStep, objective.process_step_id).name.casefold()) if objective.process_step_id else None)
                for feature in selected_features for objective in objective_rows
            ):
                incomplete += 1
                continue
            all_obs = selected_features + objective_rows
            if any(o.material_id for o in all_obs) and len({o.material_id for o in all_obs if o.material_id is not None}) > 1:
                continue
            if any(not o.source_id for o in all_obs):
                raise HTTPException(422, detail={"code": "MISSING_PROVENANCE", "message": "Every paired observation requires a source identifier."})
            canonical = [_canonical_observation(o) for o in all_obs]
            rows.append({"experiment_id": exp_id, "replicate_id": replicate,
                         "x": [v[0] for v in canonical[:len(selected_features)]],
                         "y": [v[0] for v in canonical[len(selected_features):]],
                         "feature_units": [v[1] for v in canonical[:len(selected_features)]],
                         "objective_units": [v[1] for v in canonical[len(selected_features):]],
                         "measurement_uncertainties": [v[2] for v in canonical[len(selected_features):]],
                         "observation_ids": [o.id for o in all_obs], "source_ids": [o.source_id for o in all_obs],
                         "source_types": [o.source_type for o in all_obs], "material_ids": [o.material_id for o in all_obs]})
    material_contexts = {tuple(sorted({material_id for material_id in row["material_ids"] if material_id is not None})) for row in rows}
    if len(material_contexts) > 1:
        raise HTTPException(422, detail={"code": "MATERIAL_IDENTITY_MISMATCH", "message": "The complete-case rows refer to different or inconsistently missing material identities. Select one material identity before training."})
    if len(rows) < 3 or len({r["experiment_id"] for r in rows}) < 3 or len({tuple(r["x"]) for r in rows}) < 2:
        raise HTTPException(422, detail={"code": "INSUFFICIENT_COMPLETE_CASE_DATA", "message": "At least three independent experiments and two distinct input conditions with both objectives are required.", "complete_pair_count": len(rows), "incomplete_pair_count": incomplete})
    for i in range(len(request.feature_ids)):
        if len({r["feature_units"][i] for r in rows}) != 1:
            raise HTTPException(422, detail={"code": "INCOMPATIBLE_UNITS", "message": f"Feature {request.feature_ids[i]} has incompatible units."})
    for i in range(2):
        if len({r["objective_units"][i] for r in rows}) != 1:
            raise HTTPException(422, detail={"code": "INCOMPATIBLE_UNITS", "message": f"Objective {request.objective_ids[i]} has incompatible units."})
    return rows, incomplete


def _load_moo(db, model_id, topic_id):
    item = db.query(OptimizationModelRun).filter_by(id=model_id, topic_id=topic_id).first()
    if not item or item.model_version != MODEL_VERSION or item.model_json.get("model_type") != MODEL_VERSION:
        raise HTTPException(404, "Multi-objective model not found for this topic")
    try:
        models = [GaussianProcess.from_dict(value) for value in item.model_json["models"]]
    except (KeyError, OptimizationInputError) as exc:
        raise HTTPException(409, "Saved multi-objective model is invalid") from exc
    return item, models


@router.post("/models/train")
def train(request: TrainRequest, db: Session = Depends(get_db)):
    _topic(db, request.topic_id)
    if request.mode == "sandbox":
        rng = np.random.default_rng(request.seed)
        x = rng.random((request.sandbox_samples, 2))
        y = zdt1(x)
        rows = [{"x": row.tolist(), "y": target.tolist(), "sandbox": True} for row, target in zip(x, y)]
        units = {"features": [{"id": fid, "unit": "dimensionless"} for fid in request.feature_ids[:2]],
                 "objectives": [{"id": oid, "unit": "dimensionless", "direction": direction} for oid, direction in zip(request.objective_ids, request.objective_directions)]}
        if len(request.feature_ids) != 2:
            raise HTTPException(422, "The ZDT1 sandbox uses exactly two dimensionless inputs.")
        uncertainty = [[0.0, 0.0] for _ in y]
        pairing = {"mode": "sandbox", "source": "synthetic mathematical benchmark", "notice": "Sandbox values are not research observations."}
    else:
        rows, incomplete = _research_rows(db, request)
        x = np.asarray([r["x"] for r in rows], dtype=float); y = np.asarray([r["y"] for r in rows], dtype=float)
        units = {"features": [{"id": fid, "unit": rows[0]["feature_units"][i]} for i, fid in enumerate(request.feature_ids)],
                 "objectives": [{"id": oid, "unit": rows[0]["objective_units"][i], "direction": request.objective_directions[i]} for i, oid in enumerate(request.objective_ids)]}
        uncertainty = [[(v if v is not None else 0.0) for v in r["measurement_uncertainties"]] for r in rows]
        pairing = {"mode": "research", "incomplete_pair_count": incomplete, "pairing_policy": request.pairing_policy,
                   "downstream_relation_label": request.downstream_relation_label if request.pairing_policy == "downstream_explicit" else None,
                   "provenance": [{"experiment_id": r["experiment_id"], "replicate_id": r["replicate_id"], "material_ids": r["material_ids"], "observation_ids": r["observation_ids"], "source_ids": r["source_ids"], "source_types": r["source_types"]} for r in rows]}
    if len(x[0]) != len(request.feature_ids):
        raise HTTPException(422, "Input features are incompatible with selected training data.")
    point_ids = [f"exp:{row.get('experiment_id', index)}|rep:{row.get('replicate_id') or 'unreplicated'}|obs:{','.join(map(str, row.get('observation_ids', [])))}" if request.mode == "research" else f"sandbox:{index}"
        for index, row in enumerate(rows)]
    experiment_ids = [row.get("experiment_id", index) for index, row in enumerate(rows)]
    objective_models = []
    objective_metrics = []
    validation = {"scheme": "experiment-grouped shared split" if request.mode == "research" else "seeded synthetic row holdout",
                  "validation_experiment_ids": [], "training_experiment_ids": []}
    try:
        if request.mode == "research":
            fit_idx, hold_idx, _ = _group_holdout_indices([r["experiment_id"] for r in rows], request.seed)
            validation["validation_experiment_ids"] = sorted({rows[i]["experiment_id"] for i in hold_idx})
            validation["training_experiment_ids"] = sorted({rows[i]["experiment_id"] for i in fit_idx})
        else:
            rng = np.random.default_rng(request.seed); order = rng.permutation(len(y))
            hold_count = max(1, int(round(len(y) * .2))); hold_idx, fit_idx = order[:hold_count], order[hold_count:]
        if len(fit_idx) < 2:
            raise OptimizationInputError("At least two training rows are needed after shared validation split")
        for i in range(2):
            std = np.asarray([row[i] for row in uncertainty], dtype=float) if request.mode == "research" else None
            validation_model = GaussianProcess.fit(x[fit_idx], y[fit_idx, i], kernel=request.kernel, noise=request.noise,
                measurement_std=std[fit_idx] if std is not None else None)
            hold_mean, _hold_epistemic, _hold_aleatoric, hold_total = validation_model.predict_components(x[hold_idx])
            objective_metrics.append(metrics(y[hold_idx, i], hold_mean, hold_total))
            objective_models.append(GaussianProcess.fit(x, y[:, i], kernel=request.kernel, noise=request.noise, measurement_std=std))
    except OptimizationInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    dhash = dataset_hash(rows)
    front = pareto_front(y, request.objective_directions, ids=point_ids)
    config = {"model_type": MODEL_VERSION, "mode": request.mode, "feature_ids": request.feature_ids,
              "objective_ids": request.objective_ids, "objective_directions": request.objective_directions,
              "method_version_id": request.method_version_id, "process_step_id": request.process_step_id,
              "objective_process_step_id": request.objective_process_step_id, "kernel": request.kernel,
              "noise": request.noise, "seed": request.seed, "units": units, "dataset_count": len(rows),
              "independent_experiment_count": len({r.get("experiment_id", i) for i, r in enumerate(rows)}),
              "complete_case_policy": "both objectives from same experiment and compatible replicate; no imputation",
              "independent_objective_gp_assumption": "objective outputs are modeled independently; cross-objective covariance is not learned",
              "data_contract": pairing}
    item = OptimizationModelRun(topic_id=request.topic_id, mode=request.mode.upper(), status="COMPLETED", dataset_hash=dhash,
        model_version=MODEL_VERSION, config_json=config, model_json={"model_type": MODEL_VERSION, "models": [m.to_dict() for m in objective_models], "training_x": x.tolist(), "pareto_values": y.tolist(), "pareto_ids": point_ids, "experiment_ids": experiment_ids, "pareto_observation_ids": [r.get("observation_ids", []) for r in rows], "pareto_source_ids": [r.get("source_ids", []) for r in rows], "feasibility": [True] * len(y)},
        metrics_json={"training_rows": len(rows), "pareto_count": len(front["indices"]), "objective_validation_metrics": objective_metrics,
                      "group_validation": validation,
                      "note": "Independent output GPs; no cross-objective output covariance is modeled."})
    db.add(item); db.commit(); db.refresh(item)
    return {"model_id": item.id, "model_type": MODEL_VERSION, "topic_id": item.topic_id, "mode": request.mode,
            "status": item.status, "dataset_hash": dhash, "config": config, "metrics": item.metrics_json,
              "pareto": {"ids": front["ids"], "values": [y[i].tolist() for i in front["indices"]]}, "created_at": item.created_at.isoformat() + "Z"}


@router.get("/models/{model_id}")
def get_model(model_id: int, topic_id: int, db: Session = Depends(get_db)):
    item, _ = _load_moo(db, model_id, topic_id)
    return {"model_id": item.id, "model_type": item.model_version, "topic_id": topic_id, "status": item.status,
            "dataset_hash": item.dataset_hash, "config": item.config_json, "metrics": item.metrics_json, "created_at": item.created_at.isoformat() + "Z"}


@router.post("/models/{model_id}/predict")
def predict(model_id: int, request: PredictRequest, db: Session = Depends(get_db)):
    item, models = _load_moo(db, model_id, request.topic_id)
    if any(len(row) != len(item.config_json["feature_ids"]) for row in request.candidates):
        raise HTTPException(422, "Candidate dimensions must match the model feature count.")
    result = []
    for i, model in enumerate(models):
        mean, epistemic, aleatoric, total = model.predict_components(request.candidates)
        result.append({"objective": item.config_json["units"]["objectives"][i], "predictions": [{"mean": a, "epistemic_std": b, "aleatoric_std": c, "predictive_std": d} for a, b, c, d in zip(mean, epistemic, aleatoric, total)]})
    return {"model_id": item.id, "dataset_hash": item.dataset_hash, "predictions": [{"candidate": c, "objectives": [result[j]["predictions"][i] | {"definition": result[j]["objective"]} for j in range(2)]} for i, c in enumerate(request.candidates)], "notice": "Predictions are not measured observations or experimental success probabilities."}


@router.get("/pareto")
def get_pareto(model_id: int, topic_id: int, reference_point: str | None = None, objective_scales: str | None = None, db: Session = Depends(get_db)):
    item, _ = _load_moo(db, model_id, topic_id)
    values = np.asarray(item.model_json["pareto_values"], dtype=float)
    ids = item.model_json["pareto_ids"]
    front = pareto_front(values, item.config_json["objective_directions"], ids=ids)
    front_keys = {tuple(np.asarray(values[i]).tolist()) for i in front["indices"]}
    result = {"model_id": item.id, "dataset_hash": item.dataset_hash, "pareto_ids": front["ids"],
              "pareto_values": [values[i].tolist() for i in front["indices"]], "objective_definitions": item.config_json["units"]["objectives"],
              "observed_points": [{"point_id": item.model_json["pareto_ids"][i], "experiment_id": item.model_json.get("experiment_ids", item.model_json["pareto_ids"])[i], "objective_values": values[i].tolist(),
                  "is_pareto": tuple(values[i].tolist()) in front_keys,
                  "source_observation_ids": item.model_json.get("pareto_observation_ids", [[] for _ in values])[i],
                  "source_ids": item.model_json.get("pareto_source_ids", [[] for _ in values])[i],
                  "source_kind": "SYNTHETIC_SANDBOX" if item.mode == "SANDBOX" else "APPROVED_RESEARCH_OBSERVATION"}
                  for i in range(len(values))],
              "pareto_points": [{"point_id": item.model_json["pareto_ids"][i], "experiment_id": item.model_json.get("experiment_ids", item.model_json["pareto_ids"])[i], "objective_values": values[i].tolist(),
                  "source_observation_ids": item.model_json.get("pareto_observation_ids", [[] for _ in values])[i],
                  "source_ids": item.model_json.get("pareto_source_ids", [[] for _ in values])[i],
                  "source_kind": "SYNTHETIC_SANDBOX" if item.mode == "SANDBOX" else "APPROVED_RESEARCH_OBSERVATION"}
                  for i in front["indices"]],
              "reference_point": None, "hypervolume": None}
    if reference_point:
        try:
            reference = json.loads(reference_point); scales = json.loads(objective_scales) if objective_scales else [1, 1]
            result["hypervolume"] = hypervolume_2d(values[front["indices"]], reference, item.config_json["objective_directions"], scale=scales)
            result["reference_point"] = reference; result["objective_scales"] = scales
        except (ValueError, TypeError, OptimizationInputError) as exc:
            raise HTTPException(422, str(exc)) from exc
    return result


@router.post("/models/{model_id}/recommend")
def recommend(model_id: int, request: RecommendRequest, db: Session = Depends(get_db)):
    item, models = _load_moo(db, model_id, request.topic_id)
    nfeatures = len(item.config_json["feature_ids"])
    if len(request.bounds) != nfeatures:
        raise HTTPException(422, "Bounds must match model feature count.")
    bounds = np.asarray(request.bounds, dtype=float)
    feature_units = [feature["unit"] for feature in item.config_json["units"]["features"]]
    if request.bounds_units is not None:
        if len(request.bounds_units) != nfeatures:
            raise HTTPException(422, detail={"code": "INCOMPATIBLE_UNITS", "message": "bounds_units must match the model feature count."})
        try:
            bounds = np.asarray([[float(_UNITS.Quantity(value, source_unit).to(target_unit).magnitude) for value in pair]
                for pair, source_unit, target_unit in zip(request.bounds, request.bounds_units, feature_units)], dtype=float)
        except Exception as exc:
            raise HTTPException(422, detail={"code": "INCOMPATIBLE_UNITS", "message": "Bounds use units incompatible with the selected input features."}) from exc
    if not np.isfinite(bounds).all() or np.any(bounds[:, 0] >= bounds[:, 1]):
        raise HTTPException(422, "Bounds must be finite increasing [minimum, maximum] pairs.")
    try:
        _, inequalities, equalities, projection = compile_constraints(request.constraints, item.config_json["feature_ids"], feature_units)
        if request.constraints and not constraints_feasible(bounds.tolist(), inequalities, equalities):
            raise OptimizationInputError("INFEASIBLE_CONSTRAINT_SET: bounds and physical constraints have no common feasible point")
        rng = np.random.default_rng(request.seed)
        pool = bounds[:, 0] + rng.random((request.search_budget, nfeatures)) * (bounds[:, 1] - bounds[:, 0])
        pool = np.vstack([pool, np.asarray([m.x_mean for m in models[:1]])]) if False else pool
        if projection:
            from app.services.optimization.constraints import project_candidates_to_equalities
            pool = np.vstack([pool, project_candidates_to_equalities(pool, projection)])
        mask, normalized, *_ = feasible_mask(pool, request.constraints, item.config_json["feature_ids"], feature_units, bounds)
        pool = pool[mask]
        existing_x = np.asarray(item.model_json["training_x"], dtype=float)
        feature_scale = np.asarray(models[0].x_scale, dtype=float)
        normalized_distance = np.min(np.linalg.norm((pool[:, None, :] - existing_x[None, :, :]) / feature_scale, axis=2), axis=1)
        pool = pool[normalized_distance > request.min_candidate_distance]
        # Bound the dense candidate posterior covariance on a laptop; the user
        # budget controls proposals, while MC evaluation pre-screens at most 256.
        if len(pool) > 256:
            pool = pool[np.linspace(0, len(pool)-1, 256, dtype=int)]
        if len(pool) < request.batch_size:
            raise OptimizationInputError("NO_FEASIBLE_BATCH: not enough feasible candidates satisfy constraints")
        if len(pool) * request.monte_carlo_samples * request.batch_size > 500_000:
            raise OptimizationInputError("COMPUTE_BUDGET_EXCEEDED: reduce candidate search, batch size, or Monte Carlo samples")
        front = np.asarray(item.model_json["pareto_values"], dtype=float)
        front = front[pareto_front(front, item.config_json["objective_directions"])["indices"]]
        selected = greedy_batch(models, pool, front, request.reference_point, item.config_json["objective_directions"],
            scales=request.objective_scales, samples=request.monte_carlo_samples, seed=request.seed,
            q=request.batch_size, min_distance=request.min_candidate_distance, feature_scales=feature_scale)
        points = pool[selected["indices"]]
        preds = []
        for i, model in enumerate(models):
            mean, epistemic, aleatoric, total = model.predict_components(points)
            preds.append([{"mean": m, "epistemic_std": e, "aleatoric_std": a, "predictive_std": t} for m, e, a, t in zip(mean, epistemic, aleatoric, total)])
        candidates = [{"candidate_id": f"C{rank+1}", "rank": rank+1, "parameters": points[rank].tolist(),
            "predicted_objectives": [{"id": item.config_json["objective_ids"][j], "direction": item.config_json["objective_directions"][j], **preds[j][rank]} for j in range(2)],
            "marginal_expected_hv_improvement": selected["marginal_ehvi"][rank],
            "marginal_ehvi_mc_standard_error": selected["marginal_ehvi_mc_standard_error"][rank], "feasible": True,
            "constraint_results": [{"constraint_id": rule["constraint_id"], "status": "SATISFIED"} for rule in normalized],
            "approval_status": "PENDING_RESEARCHER_REVIEW"} for rank in range(len(points))]
        acquisition_type = "mc_ehvi" if request.batch_size == 1 else "greedy_mc_hvi"
        config = {"batch_size": request.batch_size, "acquisition": acquisition_type, "monte_carlo_samples": request.monte_carlo_samples,
                  "seed": request.seed, "reference_point": request.reference_point, "objective_scales": request.objective_scales,
                  "search_budget": request.search_budget, "candidate_pool_evaluated": len(pool), "constraint_definitions": normalized,
                  "requested_bounds": request.bounds, "requested_bounds_units": request.bounds_units,
                  "normalized_bounds": bounds.tolist(),
                  "total_expected_batch_hv_improvement": selected["total_expected_batch_hvi"],
                  "total_expected_batch_hv_improvement_mc_standard_error": selected["total_expected_batch_hvi_mc_standard_error"],
                  "batch_sampling": "joint posterior covariance within each independent objective GP"}
        saved = OptimizationRecommendationRun(model_run_id=item.id, topic_id=item.topic_id, acquisition=acquisition_type.upper(), config_json=config, candidates_json=candidates, approval_status="PENDING_RESEARCHER_REVIEW")
        db.add(saved); db.commit(); db.refresh(saved)
        return {"recommendation_id": saved.id, "model_id": item.id, "dataset_hash": item.dataset_hash,
                "model_version": item.model_version, "acquisition": acquisition_type, "reference_point": request.reference_point,
                "objective_scales": request.objective_scales, "batch_size": len(candidates), "candidates": candidates,
                "candidate_pool_evaluated": len(pool), "candidate_pool_requested": request.search_budget,
                "total_expected_batch_hv_improvement": selected["total_expected_batch_hvi"],
                "total_expected_batch_hv_improvement_mc_standard_error": selected["total_expected_batch_hvi_mc_standard_error"],
                "approval_status": saved.approval_status,
                "notice": "Predicted candidates only. Hypervolume improvement is not success probability. Researcher review is required; experiments are not executed."}
    except OptimizationInputError as exc:
        raise HTTPException(422, detail={"code": str(exc).split(":", 1)[0], "message": str(exc)}) from exc


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: int, topic_id: int, db: Session = Depends(get_db)):
    saved = db.query(OptimizationRecommendationRun).filter_by(id=recommendation_id, topic_id=topic_id).first()
    if not saved:
        raise HTTPException(404, "Recommendation not found for this topic")
    return {"recommendation_id": saved.id, "model_id": saved.model_run_id, "topic_id": saved.topic_id,
            "acquisition": saved.acquisition.lower(), "config": saved.config_json, "candidates": saved.candidates_json,
            "approval_status": saved.approval_status, "created_at": saved.created_at.isoformat() + "Z"}


@router.post("/sandbox/benchmark")
def sandbox_benchmark(seed: int = 7, samples: int = 48):
    """Simple deterministic ZDT1 truth-front / Pareto / HV software check."""
    if not 20 <= samples <= 5000:
        raise HTTPException(422, "samples must be in [20, 5000]")
    x = np.column_stack([np.linspace(0, 1, samples), np.zeros(samples)])
    y = zdt1(x)
    front = pareto_front(y)
    reference = [1.1, 10.1]
    return {"mode": "sandbox", "benchmark": "ZDT1", "seed": seed, "evaluation_budget": samples,
            "pareto_count": len(front["indices"]), "hypervolume": hypervolume_2d(y[front["indices"]], reference),
            "reference_point": reference, "dataset_hash": dataset_hash([{"x": a.tolist(), "y": b.tolist()} for a, b in zip(x, y)]),
            "notice": "Synthetic software benchmark only; no research observation is created."}


@router.post("/sandbox/benchmark/compare")
def sandbox_benchmark_compare(seed: int = 7, seeds: int = 5, budget: int = 10, mc_samples: int = 32, candidate_pool_size: int = 48):
    try:
        return run_moo_benchmarks(seed=seed, seeds=seeds, budget=budget, mc_samples=mc_samples, candidate_pool_size=candidate_pool_size)
    except OptimizationInputError as exc:
        raise HTTPException(422, str(exc)) from exc
