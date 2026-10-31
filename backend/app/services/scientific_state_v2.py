"""Versioned, structured scientific context for the Phase 5 Stage 3 head.

This module is deliberately independent of the Stage 1/2 feature contract.
It encodes only observed/declared status. Unknown data stays explicitly missing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

SCIENTIFIC_STATE_SCHEMA_VERSION = "scientific-state-v2"
FEATURE_SCHEMA_VERSION_V2 = "scientific-decision-features-v2"
MODEL_VERSION_V2 = "learned-decision-structured-v2"
DATASET_VERSION_V2 = "decision-dataset-v2"
ACTION_MAPPING_VERSION = "decision-actions-v1"
ACTION_NAMES = ("REQUEST_INFORMATION", "ANALYZE", "SIMULATE", "OPTIMIZE", "REQUEST_REVIEW", "ABSTAIN")


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    path: str
    kind: str = "number"  # number, boolean, category
    unit: str = "1"
    categories: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


_SPECS: list[FeatureSpec] = []


def _num(group: str, name: str, unit: str = "1", minimum: float | None = 0, maximum: float | None = None):
    _SPECS.append(FeatureSpec(name, group, f"{group}.{name}", "number", unit, (), minimum, maximum))


def _bool(group: str, name: str):
    _SPECS.append(FeatureSpec(name, group, f"{group}.{name}", "boolean", "1", (), 0, 1))


def _cat(group: str, name: str, categories: tuple[str, ...]):
    _SPECS.append(FeatureSpec(name, group, f"{group}.{name}", "category", "category", categories=categories))


_num("experiment", "process_step_count", "count")
_num("experiment", "required_condition_completeness", "fraction", 0, 1)
_bool("experiment", "method_version_available")
_bool("experiment", "required_conditions_known")
_cat("experiment", "experiment_state", ("PLANNED", "IN_PROGRESS", "REVIEW_PENDING", "COMPLETE", "UNKNOWN"))
_bool("experiment", "review_ready")
_num("process_conditions", "temperature_mean_c", "degC", None)
_num("process_conditions", "pressure_mean_kpa", "kPa", 0)
_num("process_conditions", "duration_mean_min", "min", 0)
_num("process_conditions", "volume_mean_ml", "mL", 0)
_num("process_conditions", "concentration_mean_mol_l", "mol/L", 0)
_num("process_conditions", "known_quantity_count", "count")
_num("process_conditions", "unit_conversion_count", "count")
_num("measurements", "accepted_observation_count", "count")
_num("measurements", "pending_observation_count", "count")
_num("measurements", "rejected_observation_count", "count")
_num("measurements", "measurement_completeness", "fraction", 0, 1)
_num("measurements", "available_modality_count", "count")
_bool("measurements", "uncertainty_available")
_num("measurements", "uncertainty_missing_count", "count")
_num("measurements", "mean_relative_uncertainty", "fraction", 0)
_cat("measurements", "quality_status", ("GOOD", "DEGRADED", "BLOCKED", "UNKNOWN"))
_cat("measurements", "unit_compatibility", ("COMPATIBLE", "INCOMPATIBLE", "PARTIAL", "UNKNOWN"))
_cat("measurements", "normalization_status", ("NORMALIZED", "PARTIAL", "FAILED", "UNKNOWN"))
_num("analysis", "available_analysis_type_count", "count")
_num("analysis", "completed_analysis_count", "count")
_num("analysis", "pending_analysis_count", "count")
_num("analysis", "failed_analysis_count", "count")
_bool("analysis", "required_input_available")
_cat("analysis", "review_status", ("APPROVED", "PENDING", "REJECTED", "NOT_REQUIRED", "UNKNOWN"))
_num("simulation", "available_tool_count", "count")
_bool("simulation", "input_ready")
_num("simulation", "completed_run_count", "count")
_num("simulation", "pending_run_count", "count")
_num("simulation", "failed_run_count", "count")
_bool("simulation", "researcher_approval_required")
_cat("simulation", "approval_status", ("APPROVED", "PENDING", "NOT_REQUIRED", "UNKNOWN"))
_bool("optimization", "gp_model_available")
_bool("optimization", "gp_model_valid")
_bool("optimization", "training_data_sufficient")
_bool("optimization", "prediction_uncertainty_available")
_bool("optimization", "optimization_ready")
_num("optimization", "pending_recommendation_review_count", "count")
_cat("optimization", "constraint_validation_status", ("VALID", "INVALID", "PENDING", "UNKNOWN"))
_bool("tool_readiness", "analysis_available")
_bool("tool_readiness", "simulation_available")
_bool("tool_readiness", "optimization_available")
_bool("tool_readiness", "data_validation_available")
_num("pending_reviews", "measurement_review_count", "count")
_num("pending_reviews", "analysis_review_count", "count")
_num("pending_reviews", "simulation_review_count", "count")
_num("pending_reviews", "optimization_review_count", "count")
_cat("provenance", "validity", ("VALID", "PARTIAL", "INVALID", "UNKNOWN"))
_cat("provenance", "source_completeness", ("COMPLETE", "PARTIAL", "MISSING", "UNKNOWN"))
_cat("provenance", "approval_status", ("APPROVED", "PENDING", "NOT_REQUIRED", "UNKNOWN"))
_cat("provenance", "data_quality_gate", ("PASS", "REVIEW", "BLOCK", "UNKNOWN"))
_num("provenance", "missing_required_information_count", "count")
_bool("provenance", "unsupported_tool_state")
_bool("provenance", "historical_state_insufficient")

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {}
for _group in dict.fromkeys(spec.group for spec in _SPECS):
    FEATURE_GROUPS[_group] = tuple(spec.name for spec in _SPECS if spec.group == _group)


def feature_schema() -> dict[str, Any]:
    """Return the immutable schema definition, including typed missing masks."""
    features: list[dict[str, Any]] = []
    for spec in _SPECS:
        feature_name = f"{spec.group}__{spec.name}"
        if spec.kind == "category":
            for category in spec.categories:
                features.append({"name": f"{feature_name}__{category.lower()}", "group": spec.group,
                                 "type": "one_hot", "unit": "1", "source_path": spec.path})
        else:
            features.append({"name": feature_name, "group": spec.group, "type": spec.kind,
                             "unit": spec.unit, "source_path": spec.path,
                             "normalization": "training-set mean/std" if spec.kind == "number" else "identity"})
        features.append({"name": f"{feature_name}__missing_mask", "group": spec.group,
                         "type": "missingness_mask", "unit": "1", "source_path": spec.path})
    return {"schema_version": FEATURE_SCHEMA_VERSION_V2, "scientific_state_schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION,
            "action_mapping_version": ACTION_MAPPING_VERSION, "feature_count": len(features), "features": features,
            "groups": {name: list(values) for name, values in FEATURE_GROUPS.items()},
            "missingness": "Unknown values are represented by zero plus an explicit missingness indicator; zero is not treated as unknown."}


FEATURE_SCHEMA = feature_schema()
FEATURE_NAMES = tuple(item["name"] for item in FEATURE_SCHEMA["features"])


class ScientificStateError(ValueError):
    pass


def _get_path(state: dict[str, Any], path: str):
    value: Any = state
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


@lru_cache(maxsize=1)
def _unit_registry():
    import pint
    return pint.UnitRegistry(autoconvert_offset_to_baseunit=True)


def _unit_normalized_conditions(state: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    """Normalize explicitly dimensioned conditions with Pint; unknown units stay missing."""
    conditions=state.get("process_conditions", {})
    items=conditions.get("items", []) if isinstance(conditions, dict) else []
    if not items:
        return {}, {"status": "NO_DIMENSIONED_CONDITIONS", "conversions": [], "unsupported_unit_count": 0}
    try:
        ureg=_unit_registry()
    except ImportError:  # The project installs Pint, but never silently guesses if absent.
        return {}, {"status": "UNIT_LIBRARY_UNAVAILABLE", "conversions": []}
    targets = {"temperature": "degC", "pressure": "kPa", "duration": "minute", "volume": "milliliter", "concentration": "mole / liter"}
    aliases = {"temperature": ("temperature", "temp"), "pressure": ("pressure",), "duration": ("time", "duration", "hold"),
               "volume": ("volume",), "concentration": ("concentration", "molarity")}
    grouped: dict[str, list[float]] = {key: [] for key in targets}
    provenance: list[dict[str, Any]] = []
    unknown_units = 0
    for item in items:
        if not isinstance(item, dict) or item.get("value") is None or not item.get("unit"):
            continue
        label = str(item.get("dimension") or item.get("name") or "").casefold()
        dimension = next((key for key, names in aliases.items() if any(name in label for name in names)), None)
        if not dimension:
            continue
        try:
            quantity = float(item["value"]) * ureg(str(item["unit"]))
            normalized = float(quantity.to(targets[dimension]).magnitude)
            if not np.isfinite(normalized):
                raise ValueError("non-finite converted value")
            grouped[dimension].append(normalized)
            provenance.append({"name": item.get("name"), "dimension": dimension, "original_value": item["value"],
                               "original_unit": item["unit"], "normalized_value": normalized,
                               "normalized_unit": targets[dimension], "normalizer": "Pint"})
        except Exception:
            unknown_units += 1
            provenance.append({"name": item.get("name"), "dimension": dimension, "original_value": item.get("value"),
                               "original_unit": item.get("unit"), "status": "UNSUPPORTED_OR_INCOMPATIBLE_UNIT"})
    values = {f"{key}_mean_{'c' if key == 'temperature' else 'kpa' if key == 'pressure' else 'min' if key == 'duration' else 'ml' if key == 'volume' else 'mol_l'}": float(np.mean(items))
              for key, items in grouped.items() if items}
    return values, {"status": "PARTIAL" if unknown_units else "NORMALIZED" if provenance else "NO_DIMENSIONED_CONDITIONS",
                    "conversions": provenance, "unsupported_unit_count": unknown_units}


def canonical_state(state: dict[str, Any]) -> dict[str, Any]:
    """Validate and stabilize the V2 nested state without inventing absent evidence."""
    if not isinstance(state, dict):
        raise ScientificStateError("ScientificState V2 must be an object")
    if state.get("schema_version") not in (None, SCIENTIFIC_STATE_SCHEMA_VERSION):
        raise ScientificStateError("Unsupported ScientificState schema version")
    data = json.loads(json.dumps(state, sort_keys=True, allow_nan=False, default=str))
    data["schema_version"] = SCIENTIFIC_STATE_SCHEMA_VERSION
    contexts = ("experiment", "process_conditions", "measurements", "analysis", "simulation", "optimization",
                "tool_readiness", "pending_reviews", "provenance")
    for context in contexts:
        value = data.setdefault(context, {})
        if not isinstance(value, dict):
            raise ScientificStateError(f"ScientificState context '{context}' must be an object")
    data.setdefault("source_provenance", {})
    if not isinstance(data["source_provenance"], dict):
        raise ScientificStateError("source_provenance must be an object")
    conditions, unit_trace = _unit_normalized_conditions(data)
    for key, value in conditions.items():
        data["process_conditions"].setdefault(key, value)
    data["process_conditions"].setdefault("unit_normalization", unit_trace)
    return data


def extract_features(state: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    normalized = canonical_state(state)
    values: list[float] = []
    missing_names: list[str] = []
    for spec in _SPECS:
        value = _get_path(normalized, spec.path)
        missing = value is None
        if spec.kind == "category":
            if not missing:
                category = str(value).upper()
                if category not in spec.categories:
                    raise ScientificStateError(f"Unsupported category {category!r} for {spec.name}")
            else:
                category = "UNKNOWN" if "UNKNOWN" in spec.categories else spec.categories[-1]
                missing_names.append(spec.name)
            values.extend(float(category == item) for item in spec.categories)
        else:
            if missing:
                numeric = 0.0
                missing_names.append(spec.name)
            elif spec.kind == "boolean":
                if not isinstance(value, bool):
                    raise ScientificStateError(f"Feature '{spec.name}' must be boolean")
                numeric = float(value)
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ScientificStateError(f"Feature '{spec.name}' must be numeric")
            else:
                numeric = float(value)
            if not np.isfinite(numeric):
                raise ScientificStateError(f"Feature '{spec.name}' must be finite")
            if spec.minimum is not None and numeric < spec.minimum:
                raise ScientificStateError(f"Feature '{spec.name}' is below its valid range")
            if spec.maximum is not None and numeric > spec.maximum:
                raise ScientificStateError(f"Feature '{spec.name}' is above its valid range")
            values.append(numeric)
        values.append(float(missing))
    vector = np.asarray(values, dtype=np.float64)
    if vector.shape != (len(FEATURE_NAMES),):
        raise ScientificStateError("Feature schema and encoded vector dimensions differ")
    return vector, {"schema_version": FEATURE_SCHEMA_VERSION_V2, "feature_names": list(FEATURE_NAMES),
                    "feature_groups": {name: list(names) for name, names in FEATURE_GROUPS.items()},
                    "missing_feature_names": missing_names, "missing_feature_count": len(missing_names),
                    "source_provenance": normalized["source_provenance"],
                    "unit_normalization": normalized["process_conditions"].get("unit_normalization", {})}


def from_legacy_state(state: dict[str, Any]) -> dict[str, Any]:
    """Loss-aware adapter for historical V1 snapshots; unavailable context remains marked unknown."""
    old = state if isinstance(state, dict) else {}
    values = lambda key: old.get(key) if old.get(key) is not None else None
    accepted = values("accepted_observation_count")
    completeness = values("measurement_completeness")
    analysis_done = values("available_analysis_count")
    analysis_pending = values("pending_analysis_count")
    simulation_done = values("available_simulation_count")
    pending_review = values("pending_review_count")
    provenance_valid = values("provenance_valid")
    missing_info = values("missing_required_information_count")
    legacy_missing = True
    return {"schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION,
        "experiment": {"method_version_available": old.get("method_version_id") is not None,
                       "process_step_count": None, "required_condition_completeness": None,
                       "required_conditions_known": False, "experiment_state": "UNKNOWN", "review_ready": None},
        "process_conditions": {"items": []},
        "measurements": {"accepted_observation_count": accepted, "pending_observation_count": pending_review,
                         "rejected_observation_count": None, "measurement_completeness": completeness,
                         "available_modality_count": None, "uncertainty_available": None,
                         "uncertainty_missing_count": None, "mean_relative_uncertainty": None, "quality_status": "UNKNOWN",
                         "mean_relative_uncertainty": None,
                         "unit_compatibility": "UNKNOWN", "normalization_status": "UNKNOWN"},
        "analysis": {"available_analysis_type_count": None, "completed_analysis_count": analysis_done,
                     "pending_analysis_count": analysis_pending, "failed_analysis_count": None,
                     "required_input_available": None, "review_status": "UNKNOWN"},
        "simulation": {"available_tool_count": None, "input_ready": None, "completed_run_count": simulation_done,
                       "pending_run_count": None, "failed_run_count": None,
                       "researcher_approval_required": None, "approval_status": "UNKNOWN"},
        "optimization": {"gp_model_available": old.get("gp_model_ready"), "gp_model_valid": None,
                          "training_data_sufficient": old.get("optimization_ready"),
                          "prediction_uncertainty_available": old.get("gp_mean_uncertainty") is not None,
                          "optimization_ready": old.get("optimization_ready"),
                          "pending_recommendation_review_count": None, "constraint_validation_status": "UNKNOWN"},
        "tool_readiness": {"analysis_available": old.get("analysis_tool_available"),
                           "simulation_available": old.get("simulation_tool_available"),
                           "optimization_available": old.get("optimization_tool_available"),
                           "data_validation_available": None},
        "pending_reviews": {"measurement_review_count": pending_review, "analysis_review_count": analysis_pending,
                            "simulation_review_count": None, "optimization_review_count": None},
        "provenance": {"validity": "VALID" if provenance_valid is True else "INVALID" if provenance_valid is False else "UNKNOWN",
                       "source_completeness": "UNKNOWN", "approval_status": "UNKNOWN", "data_quality_gate": "UNKNOWN",
                       "missing_required_information_count": missing_info, "unsupported_tool_state": False,
                       "historical_state_insufficient": legacy_missing},
        "source_provenance": {"adapter": "v1-to-v2-loss-aware", "historical_state": "INSUFFICIENT_HISTORICAL_STATE"}}


def scientific_state_from_experiment(experiment: Any, observations: list[Any], analysis_runs: list[Any],
                                     simulation_runs: list[Any], optimization_models: list[Any],
                                     optimization_recommendations: list[Any], tool_recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [x for x in observations if x.review_status == "ACCEPTED"]
    pending = [x for x in observations if x.review_status in {"PENDING", "NEEDS_REVIEW"}]
    rejected = [x for x in observations if x.review_status == "REJECTED"]
    normalized = [x for x in accepted if x.normalization_error is None and x.normalized_value is not None]
    uncertainty = [x for x in accepted if x.measurement_uncertainty is not None]
    relative_uncertainties=[abs(float(x.measurement_uncertainty)/float(x.normalized_value)) for x in accepted
        if x.measurement_uncertainty is not None and x.normalized_value not in (None,0)]
    analysis_done = [x for x in analysis_runs if str(x.analysis_status).casefold() in {"completed", "succeeded"}]
    analysis_pending = [x for x in analysis_runs if str(x.analysis_status).casefold() in {"pending", "queued", "running", "needs_review"}]
    analysis_failed = [x for x in analysis_runs if str(x.analysis_status).casefold() in {"failed", "rejected"}]
    sim_done = [x for x in simulation_runs if str(x.status).casefold() in {"completed", "succeeded"}]
    sim_pending = [x for x in simulation_runs if str(x.status).casefold() in {"queued", "running", "pending"}]
    sim_failed = [x for x in simulation_runs if str(x.status).casefold() == "failed"]
    approved_analysis = [x for x in analysis_done if x.review_events and x.review_events[-1].review_status == "ACCEPTED"]
    method_version = getattr(experiment, "method_version", None)
    required = [x for x in (method_version.condition_definitions or []) if x.get("required")] if method_version else []
    actual_names = {v.name.casefold() for step in experiment.steps for v in step.variables}
    required_present = sum(str(x.get("name", "")).casefold() in actual_names for x in required)
    condition_completeness = required_present / len(required) if required else (1.0 if method_version else None)
    valid_sources = [bool(x.source_id) and bool(x.source_type) for x in accepted]
    provenance = ("UNKNOWN" if not accepted else "VALID" if all(valid_sources) and len(normalized) == len(accepted)
                  else "PARTIAL" if any(valid_sources) else "INVALID")
    tool_ids = {item.get("tool_id") for item in tool_recommendations if item.get("readiness") in {"READY", "REQUIRES_REVIEW"}}
    analysis_tools = {item.get("tool_id") for item in tool_recommendations if item.get("category") == "analysis" and item.get("connected")}
    simulation_tools = {item.get("tool_id") for item in tool_recommendations if item.get("category") == "simulation" and item.get("connected")}
    gp_models = [x for x in optimization_models if str(x.status).upper() in {"COMPLETED", "EVALUATED"}]
    approved_recs = [x for x in optimization_recommendations if str(x.approval_status).upper() == "APPROVED"]
    pending_recs = [x for x in optimization_recommendations if str(x.approval_status).upper() in {"PENDING_RESEARCHER_REVIEW", "PENDING"}]
    normalized_count = len(normalized)
    unit_state = "UNKNOWN" if not accepted else "COMPATIBLE" if len(normalized) == len(accepted) else "PARTIAL" if normalized else "INCOMPATIBLE"
    quality = "UNKNOWN" if not observations else "BLOCKED" if rejected or any(x.normalization_error for x in observations) else "DEGRADED" if pending else "GOOD"
    sim_review_required = any(item.get("category") == "simulation" and item.get("readiness") == "REQUIRES_REVIEW" for item in tool_recommendations)
    missing_info = max(0, len(required) - required_present) if required else None
    return {"schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION,
        "experiment_id": experiment.id, "topic_id": experiment.topic_id,
        "experiment": {"method_version_available": method_version is not None, "process_step_count": len(experiment.steps),
                       "required_condition_completeness": condition_completeness, "required_conditions_known": bool(method_version),
                       "experiment_state": "IN_PROGRESS" if str(experiment.status).upper() in {"IN_PROGRESS", "RUNNING"} else "PLANNED" if str(experiment.status).upper() in {"PLANNED", "DRAFT"} else "COMPLETE" if str(experiment.status).upper() in {"COMPLETED", "COMPLETE"} else "UNKNOWN",
                       "review_ready": bool(accepted) and not pending and not rejected},
        "process_conditions": {"items": [{"name": v.name, "value": v.value, "unit": v.unit, "dimension": v.name}
            for step in experiment.steps for v in step.variables if v.value is not None and v.unit]},
        "measurements": {"accepted_observation_count": len(accepted), "pending_observation_count": len(pending), "rejected_observation_count": len(rejected),
                         "measurement_completeness": len(normalized) / max(1, len(observations)) if observations else None,
                         "available_modality_count": len({str(x.parameter_id).split(":", 1)[0].casefold() for x in normalized}),
                         "uncertainty_available": bool(uncertainty) if accepted else None,
                         "uncertainty_missing_count": len(accepted) - len(uncertainty) if accepted else None,
                         "mean_relative_uncertainty": float(np.mean(relative_uncertainties)) if relative_uncertainties else None,
                         "quality_status": quality, "unit_compatibility": unit_state,
                         "normalization_status": "UNKNOWN" if not observations else "NORMALIZED" if normalized_count == len(observations) else "PARTIAL" if normalized else "FAILED"},
        "analysis": {"available_analysis_type_count": len(analysis_tools), "completed_analysis_count": len(analysis_done),
                     "pending_analysis_count": len(analysis_pending), "failed_analysis_count": len(analysis_failed),
                     "required_input_available": bool(analysis_done or analysis_pending),
                     "review_status": "UNKNOWN" if not analysis_runs else "APPROVED" if len(approved_analysis) == len(analysis_done) and analysis_done else "PENDING" if analysis_pending or analysis_done else "REJECTED" if analysis_failed else "UNKNOWN"},
        "simulation": {"available_tool_count": len(simulation_tools), "input_ready": any(item.get("readiness") == "READY" for item in tool_recommendations if item.get("category") == "simulation"),
                       "completed_run_count": len(sim_done), "pending_run_count": len(sim_pending), "failed_run_count": len(sim_failed),
                       "researcher_approval_required": bool(sim_review_required),
                       "approval_status": "PENDING" if sim_review_required else "NOT_REQUIRED" if simulation_tools else "UNKNOWN"},
        "optimization": {"gp_model_available": bool(gp_models), "gp_model_valid": bool(gp_models) if gp_models else None,
                          "training_data_sufficient": len(accepted) >= 3 if accepted else None,
                          "prediction_uncertainty_available": any(bool((x.metrics_json or {}).get("holdout", {}).get("mean_normalized_std") is not None) for x in gp_models) if gp_models else None,
                          "optimization_ready": bool(gp_models) and len(accepted) >= 3,
                          "pending_recommendation_review_count": len(pending_recs),
                          "constraint_validation_status": "VALID" if approved_recs else "PENDING" if pending_recs else "UNKNOWN"},
        "tool_readiness": {"analysis_available": bool(analysis_tools), "simulation_available": bool(simulation_tools),
                           "optimization_available": bool(gp_models) and len(accepted) >= 3,
                           "data_validation_available": "experiment.data_quality.v1" in tool_ids},
        "pending_reviews": {"measurement_review_count": len(pending), "analysis_review_count": len(analysis_pending),
                            "simulation_review_count": len(sim_pending), "optimization_review_count": len(pending_recs)},
        "provenance": {"validity": provenance, "source_completeness": "UNKNOWN" if not accepted else "COMPLETE" if all(valid_sources) else "PARTIAL",
                       "approval_status": "PENDING" if pending or pending_recs else "APPROVED" if accepted and not pending else "UNKNOWN",
                       "data_quality_gate": "BLOCK" if rejected or (observations and not normalized_count) else "REVIEW" if pending or missing_info else "PASS" if accepted else "UNKNOWN",
                       "missing_required_information_count": missing_info, "unsupported_tool_state": any(item.get("readiness") == "UNSUPPORTED" for item in tool_recommendations),
                       "historical_state_insufficient": False},
        "source_provenance": {"experiment_id": experiment.id, "topic_id": experiment.topic_id,
            "method_version_id": experiment.method_version_id, "observation_ids": [x.id for x in observations],
            "analysis_run_ids": [x.id for x in analysis_runs], "simulation_run_ids": [x.id for x in simulation_runs],
            "optimization_model_ids": [x.id for x in gp_models], "derived_from_current_records": True}}


def v2_from_v1(state: dict[str, Any]) -> dict[str, Any]:
    """Convert the named V1 fields loss-aware; never backfill historical details."""
    return from_legacy_state(state)


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    e = np.exp(np.clip(shifted, -60, 60))
    return e / e.sum(axis=1, keepdims=True)


@dataclass
class StructuredDecisionHeadV2:
    mean: np.ndarray
    scale: np.ndarray
    group_weights: list[np.ndarray]
    group_biases: list[np.ndarray]
    output_weight: np.ndarray
    output_bias: np.ndarray
    temperature: float = 1.0
    confidence_threshold: float = 0.55
    trained_distance_threshold: float = 6.0
    calibrated: bool = False

    @property
    def parameter_count(self) -> int:
        return int(sum(x.size for x in self.group_weights) + sum(x.size for x in self.group_biases) + self.output_weight.size + self.output_bias.size + self.mean.size * 2)

    @classmethod
    def fit(cls, x: np.ndarray, labels: list[str], *, seed: int = 7, epochs: int = 220, learning_rate: float = .025,
            sample_weights: np.ndarray | None = None) -> tuple["StructuredDecisionHeadV2", list[float]]:
        if x.ndim != 2 or x.shape[1] != len(FEATURE_NAMES) or len(labels) != len(x) or len(labels) < 18:
            raise ScientificStateError("V2 training requires at least 18 aligned vectors using the V2 feature schema")
        if set(labels) - set(ACTION_NAMES):
            raise ScientificStateError("Unknown V2 action label")
        row_weights=np.ones(len(labels),dtype=float) if sample_weights is None else np.asarray(sample_weights,dtype=float)
        if row_weights.shape!=(len(labels),) or not np.all(np.isfinite(row_weights)) or np.any(row_weights<=0):
            raise ScientificStateError("V2 sample weights must be finite, positive and aligned to training rows")
        row_weights=row_weights/row_weights.sum()
        groups = [np.asarray([i for i, spec in enumerate(FEATURE_SCHEMA["features"]) if spec["group"] == group], dtype=int)
                  for group in FEATURE_GROUPS]
        mean = x.mean(axis=0); scale = x.std(axis=0); scale[scale < 1e-8] = 1.0
        z = np.clip((x - mean) / scale, -8, 8)
        rng = np.random.default_rng(seed)
        hidden = 5
        w = [rng.normal(0, .08, (len(indexes), hidden)) for indexes in groups]
        b = [np.zeros(hidden) for _ in groups]
        output = rng.normal(0, .06, (len(groups) * hidden, len(ACTION_NAMES)))
        output_bias = np.zeros(len(ACTION_NAMES))
        y = np.asarray([ACTION_NAMES.index(label) for label in labels])
        losses: list[float] = []
        for _ in range(epochs):
            branch = [np.tanh(z[:, indexes] @ weight + bias) for indexes, weight, bias in zip(groups, w, b)]
            joined = np.concatenate(branch, axis=1)
            probabilities = _softmax(joined @ output + output_bias)
            losses.append(float(np.sum(-np.log(np.maximum(probabilities[np.arange(len(y)), y], 1e-12))*row_weights)))
            grad = probabilities
            grad[np.arange(len(y)), y] -= 1
            grad *= row_weights[:,None]
            out_grad = joined.T @ grad + 1e-4 * output
            out_bias_grad = grad.sum(axis=0)
            branch_grad = (grad @ output.T).reshape(len(x), len(groups), hidden)
            new_w = []; new_b = []
            for i, (indexes, weights, activations) in enumerate(zip(groups, w, branch)):
                derivative = branch_grad[:, i, :] * (1 - activations * activations)
                new_w.append(weights - learning_rate * (z[:, indexes].T @ derivative + 1e-4 * weights))
                new_b.append(b[i] - learning_rate * derivative.sum(axis=0))
            w = new_w; b = new_b
            output -= learning_rate * out_grad
            output_bias -= learning_rate * out_bias_grad
        model = cls(mean, scale, w, b, output, output_bias)
        distances = model.training_distances(x)
        model.trained_distance_threshold = float(max(6.0, np.quantile(distances, .99) * 1.25))
        return model, losses

    def representations(self, x: np.ndarray) -> np.ndarray:
        if x.ndim != 2 or x.shape[1] != len(self.mean):
            raise ScientificStateError("V2 representation input schema/dimension mismatch")
        z = np.clip((x - self.mean) / self.scale, -8, 8)
        groups = [np.asarray([i for i, spec in enumerate(FEATURE_SCHEMA["features"]) if spec["group"] == group], dtype=int)
                  for group in FEATURE_GROUPS]
        return np.concatenate([np.tanh(z[:, idx] @ weight + bias) for idx, weight, bias in zip(groups, self.group_weights, self.group_biases)], axis=1)

    def encode(self, state: dict[str, Any]) -> dict[str, Any]:
        vector, metadata = extract_features(state)
        embedding = self.representations(vector.reshape(1, -1))[0]
        return {"representation_version": "scientific-state-embedding-v2", "values": embedding.tolist(), "metadata": metadata}

    def logits(self, x: np.ndarray) -> np.ndarray:
        return self.representations(x) @ self.output_weight + self.output_bias

    def predict_proba(self, x: np.ndarray, *, calibrated: bool = True) -> np.ndarray:
        temperature = self.temperature if calibrated else 1.0
        return _softmax(self.logits(x) / temperature)

    def calibrate(self, x: np.ndarray, labels: list[str]) -> bool:
        if len(labels) < 24 or len(set(labels)) < 3:
            self.calibrated = False; self.temperature = 1.0; self.confidence_threshold = 0.55
            return False
        y = np.asarray([ACTION_NAMES.index(label) for label in labels])
        logits = self.logits(x)
        candidates = np.geomspace(.35, 3.0, 100)
        losses = [-np.log(np.maximum(_softmax(logits / t)[np.arange(len(y)), y], 1e-12)).mean() for t in candidates]
        self.temperature = float(candidates[int(np.argmin(losses))])
        self.calibrated = True
        calibrated = _softmax(logits / self.temperature)
        correct = calibrated.argmax(axis=1) == y
        # Threshold selected on calibration data only; prefer >=80% precision when feasible,
        # otherwise use a conservative quantile and document it as a score threshold.
        candidates_conf = np.unique(np.round(calibrated.max(axis=1), 4))
        eligible = [float(t) for t in candidates_conf if int(np.sum(calibrated.max(axis=1) >= t)) >= max(5, int(.15 * len(y)))
                    and float(correct[calibrated.max(axis=1) >= t].mean()) >= .8]
        self.confidence_threshold = max(eligible) if eligible else float(max(.55, np.quantile(calibrated.max(axis=1), .6)))
        return True

    def training_distances(self, x: np.ndarray) -> np.ndarray:
        z = np.abs((x - self.mean) / self.scale)
        return np.sqrt(np.mean(np.minimum(z, 20) ** 2, axis=1))

    def predict_safe(self, state: dict[str, Any]) -> dict[str, Any]:
        vector, meta = extract_features(state)
        probs = self.predict_proba(vector.reshape(1, -1))[0]
        raw = ACTION_NAMES[int(np.argmax(probs))]
        distance = float(self.training_distances(vector.reshape(1, -1))[0])
        reasons = []
        status = "IN_DISTRIBUTION"
        state_v = canonical_state(state)
        experiment=state_v["experiment"];measurement=state_v["measurements"];analysis=state_v["analysis"]
        simulation=state_v["simulation"];optimization=state_v["optimization"];provenance=state_v["provenance"]
        contradictions=[]
        if optimization.get("optimization_ready") is True and optimization.get("gp_model_available") is False:
            contradictions.append("OPTIMIZATION_READY_WITHOUT_MODEL")
        if simulation.get("input_ready") is True and (simulation.get("available_tool_count") or 0)==0:
            contradictions.append("SIMULATION_INPUT_READY_WITHOUT_TOOL")
        if measurement.get("unit_compatibility")=="INCOMPATIBLE" and measurement.get("quality_status")=="GOOD":
            contradictions.append("GOOD_QUALITY_WITH_INCOMPATIBLE_UNITS")
        if provenance.get("validity")=="INVALID" and provenance.get("data_quality_gate")=="PASS":
            contradictions.append("PROVENANCE_INVALID_WITH_PASS_GATE")
        if experiment.get("required_conditions_known") is False and (experiment.get("required_condition_completeness") or 0)>0:
            contradictions.append("CONDITION_COMPLETENESS_WITH_UNKNOWN_REQUIREMENTS")
        if contradictions:
            status="UNSUPPORTED_STATE";reasons.extend(contradictions)
        if meta["missing_feature_count"] > 14:
            status = "UNSUPPORTED_STATE"; reasons.append("HIGH_REQUIRED_CONTEXT_MISSINGNESS")
        elif status != "UNSUPPORTED_STATE" and distance > self.trained_distance_threshold:
            status = "POTENTIAL_OOD"; reasons.append("STANDARDIZED_TRAINING_DISTRIBUTION_DISTANCE")
        if provenance.get("validity") in {"INVALID", "UNKNOWN"} and not provenance.get("historical_state_insufficient"):
            reasons.append("SOURCE_PROVENANCE_NOT_VERIFIED")
        if measurement.get("unit_compatibility") == "INCOMPATIBLE":
            reasons.append("MEASUREMENT_UNITS_INCOMPATIBLE")
        if provenance.get("data_quality_gate") == "BLOCK":
            reasons.append("DATA_QUALITY_GATE_BLOCKED")
        confidence = float(np.max(probs))
        override_reason = None
        if status != "IN_DISTRIBUTION":
            final = "ABSTAIN"; override_reason = "OOD_OR_UNSUPPORTED_STATE"
        elif "MEASUREMENT_UNITS_INCOMPATIBLE" in reasons or "DATA_QUALITY_GATE_BLOCKED" in reasons or "SOURCE_PROVENANCE_NOT_VERIFIED" in reasons:
            final = "REQUEST_REVIEW"; override_reason = "SCIENTIFIC_DATA_QUALITY_GATE"
        elif confidence < self.confidence_threshold:
            final = "ABSTAIN"; override_reason = "BELOW_CALIBRATED_CONFIDENCE_THRESHOLD"
        else:
            final = raw
        return {"raw_predicted_action": raw, "action": final,
                "action_probabilities": {name: float(probs[i]) for i, name in enumerate(ACTION_NAMES)},
                "confidence": confidence, "confidence_semantics": "calibrated_class_score_not_success_probability" if self.calibrated else "uncalibrated_class_score",
                "calibration_status": "CALIBRATED_ON_SEPARATE_GROUP_HOLDOUT" if self.calibrated else "UNCALIBRATED_OR_INSUFFICIENT_DATA",
                "ood_status": status, "ood_reasons": reasons, "training_distribution_distance": distance,
                "abstention_reason": override_reason if final in {"ABSTAIN", "REQUEST_REVIEW"} else None,
                "safety_override": final != raw, "safety_override_reason": override_reason,
                "threshold_source": "CALIBRATION_GROUPS_ONLY" if self.calibrated else "FIXED_CONSERVATIVE_FALLBACK",
                "scientific_explanation": None, "workflow_triggered": False, "shadow_only": True}

    def to_dict(self) -> dict[str, Any]:
        return {"model_version": MODEL_VERSION_V2, "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
                "scientific_state_schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION, "action_mapping_version": ACTION_MAPPING_VERSION,
                "actions": list(ACTION_NAMES), "mean": self.mean.tolist(), "scale": self.scale.tolist(),
                "group_names": list(FEATURE_GROUPS), "group_weights": [x.tolist() for x in self.group_weights],
                "group_biases": [x.tolist() for x in self.group_biases], "output_weight": self.output_weight.tolist(),
                "output_bias": self.output_bias.tolist(), "temperature": self.temperature, "calibrated": self.calibrated,
                "confidence_threshold": self.confidence_threshold, "trained_distance_threshold": self.trained_distance_threshold,
                "architecture": {"type": "grouped_tanh_feature_encoder", "input_size": len(FEATURE_NAMES),
                                 "group_embedding_size": 5, "output_size": len(ACTION_NAMES), "parameter_count": self.parameter_count}}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StructuredDecisionHeadV2":
        if (payload.get("model_version") != MODEL_VERSION_V2 or payload.get("feature_schema_version") != FEATURE_SCHEMA_VERSION_V2
            or payload.get("scientific_state_schema_version") != SCIENTIFIC_STATE_SCHEMA_VERSION
            or payload.get("action_mapping_version") != ACTION_MAPPING_VERSION or payload.get("actions") != list(ACTION_NAMES)
            or payload.get("group_names") != list(FEATURE_GROUPS)):
            raise ScientificStateError("Stored model version/action/schema is incompatible with Scientific Decision V2")
        model = cls(np.asarray(payload["mean"], dtype=float), np.asarray(payload["scale"], dtype=float),
                    [np.asarray(x, dtype=float) for x in payload["group_weights"]],
                    [np.asarray(x, dtype=float) for x in payload["group_biases"]],
                    np.asarray(payload["output_weight"], dtype=float), np.asarray(payload["output_bias"], dtype=float),
                    float(payload.get("temperature", 1)), float(payload.get("confidence_threshold", .55)),
                    float(payload.get("trained_distance_threshold", 6)), bool(payload.get("calibrated", False)))
        if len(model.mean) != len(FEATURE_NAMES) or model.scale.shape != model.mean.shape or len(model.group_weights) != len(FEATURE_GROUPS):
            raise ScientificStateError("Stored V2 model tensor dimensions are invalid")
        return model
