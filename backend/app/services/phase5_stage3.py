"""Generalization data and benchmark utilities for Phase 5 Stage 3."""
from __future__ import annotations

import hashlib
import json
import platform
import random
import time
import tracemalloc
from collections import Counter
from typing import Any

import numpy as np

from app.services.decision_head import ACTIONS, LearnedDecisionHead, calibration_metrics, majority_metrics, rule_metrics
from app.services.scientific_state_v2 import (
    FEATURE_SCHEMA_VERSION_V2, FEATURE_NAMES, FEATURE_GROUPS, FEATURE_SCHEMA, MODEL_VERSION_V2,
    ScientificStateError, StructuredDecisionHeadV2, canonical_state, extract_features,
    from_legacy_state, v2_from_v1,
)

BENCHMARK_VERSION = "phase5-stage3-generalization-v1"
SCENARIO_FAMILIES = (
    "measurement_data_scarce", "analysis_needed", "simulation_ready", "optimization_ready",
    "researcher_review", "incomplete_provenance", "unit_mismatch", "high_uncertainty",
    "multiple_tools_available", "contradictory_readiness", "partial_missingness", "unseen_condition_combination",
)
SEEDS = (11, 29, 47, 71, 101)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def split_groups(groups: list[str], *, seed: int, fractions=(.6, .2, .2)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(groups) < 15 or len(set(groups)) < 15 or abs(sum(fractions) - 1) > 1e-8:
        raise ScientificStateError("At least 15 independent groups are required for fit/calibration/test partitions")
    unique = list(dict.fromkeys(groups))
    rng = np.random.default_rng(seed)
    rng.shuffle(unique)
    n_fit = max(1, int(round(len(unique) * fractions[0])))
    n_cal = max(1, int(round(len(unique) * fractions[1])))
    n_test = len(unique) - n_fit - n_cal
    if n_test < 1:
        raise ScientificStateError("Independent groups cannot populate all requested partitions")
    fit_groups = set(unique[:n_fit]); cal_groups = set(unique[n_fit:n_fit+n_cal]); test_groups = set(unique[n_fit+n_cal:])
    group_array = np.asarray(groups)
    fit = np.where(np.isin(group_array, list(fit_groups)))[0]
    cal = np.where(np.isin(group_array, list(cal_groups)))[0]
    test = np.where(np.isin(group_array, list(test_groups)))[0]
    if (set(group_array[fit]) & set(group_array[cal])) or (set(group_array[fit]) & set(group_array[test])) or (set(group_array[cal]) & set(group_array[test])):
        raise ScientificStateError("Group leakage detected in Stage 3 split")
    return fit, cal, test


def _blank_context() -> dict[str, Any]:
    return {
        "schema_version": "scientific-state-v2",
        "experiment": {"process_step_count": 3, "required_condition_completeness": .8,
                       "method_version_available": True, "required_conditions_known": True,
                       "experiment_state": "IN_PROGRESS", "review_ready": True},
        "process_conditions": {"items": []},
        "measurements": {"accepted_observation_count": 3, "pending_observation_count": 0,
                          "rejected_observation_count": 0, "measurement_completeness": .8,
                          "available_modality_count": 1, "uncertainty_available": True,
                          "uncertainty_missing_count": 0, "mean_relative_uncertainty": .08, "quality_status": "GOOD",
                          "unit_compatibility": "COMPATIBLE", "normalization_status": "NORMALIZED"},
        "analysis": {"available_analysis_type_count": 1, "completed_analysis_count": 0,
                     "pending_analysis_count": 0, "failed_analysis_count": 0,
                     "required_input_available": True, "review_status": "NOT_REQUIRED"},
        "simulation": {"available_tool_count": 1, "input_ready": False, "completed_run_count": 0,
                       "pending_run_count": 0, "failed_run_count": 0,
                       "researcher_approval_required": False, "approval_status": "NOT_REQUIRED"},
        "optimization": {"gp_model_available": False, "gp_model_valid": None, "training_data_sufficient": False,
                          "prediction_uncertainty_available": False, "optimization_ready": False,
                          "pending_recommendation_review_count": 0, "constraint_validation_status": "UNKNOWN"},
        "tool_readiness": {"analysis_available": True, "simulation_available": True,
                           "optimization_available": False, "data_validation_available": True},
        "pending_reviews": {"measurement_review_count": 0, "analysis_review_count": 0,
                            "simulation_review_count": 0, "optimization_review_count": 0},
        "provenance": {"validity": "VALID", "source_completeness": "COMPLETE", "approval_status": "NOT_REQUIRED",
                       "data_quality_gate": "PASS", "missing_required_information_count": 0,
                       "unsupported_tool_state": False, "historical_state_insufficient": False},
        "source_provenance": {"dataset_type": "SYNTHETIC_SCENARIO_CONTRACT", "not_research_data": True},
    }


def _scenario(rng: np.random.Generator, index: int, seed: int) -> tuple[dict[str, Any], str, str]:
    state = _blank_context()
    meas, ana, sim, opt, prov, pending, tools = (state[x] for x in ("measurements", "analysis", "simulation", "optimization", "provenance", "pending_reviews", "tool_readiness"))
    family = SCENARIO_FAMILIES[index % len(SCENARIO_FAMILIES)]
    # Correlated noise and overlapping contexts make labels depend on the combined state, not a family ID.
    accepted = int(rng.integers(0, 10)); completeness = float(np.clip(rng.normal(.68, .22), 0, 1))
    meas.update(accepted_observation_count=accepted, measurement_completeness=completeness,
                available_modality_count=int(rng.integers(0, 4)), uncertainty_available=bool(rng.integers(0, 2)),
                uncertainty_missing_count=int(rng.integers(0, 5)))
    opt_ready = bool(rng.random() < .23); sim_ready = bool(rng.random() < .25)
    analysis_pending = bool(rng.random() < .28); review = bool(rng.random() < .15)
    if family == "measurement_data_scarce": meas["accepted_observation_count"] = int(rng.integers(0, 2)); meas["measurement_completeness"] = float(rng.uniform(0, .35))
    elif family == "analysis_needed": ana.update(pending_analysis_count=1, review_status="PENDING"); analysis_pending = True
    elif family == "simulation_ready": sim.update(input_ready=True, researcher_approval_required=bool(rng.random() < .35), approval_status="PENDING" if rng.random() < .35 else "NOT_REQUIRED"); sim_ready = True
    elif family == "optimization_ready": opt.update(gp_model_available=True, gp_model_valid=True, training_data_sufficient=True,
        prediction_uncertainty_available=True, optimization_ready=True, constraint_validation_status="VALID"); opt_ready = True
    elif family == "researcher_review": review = True; pending["measurement_review_count"] = 1; meas["quality_status"] = "DEGRADED"
    elif family == "incomplete_provenance": prov.update(validity="PARTIAL", source_completeness="PARTIAL"); meas["quality_status"] = "DEGRADED"
    elif family == "unit_mismatch": meas.update(unit_compatibility="INCOMPATIBLE", normalization_status="FAILED", quality_status="BLOCKED"); prov["data_quality_gate"] = "BLOCK"
    elif family == "high_uncertainty": meas.update(uncertainty_available=True, uncertainty_missing_count=0,
        mean_relative_uncertainty=float(rng.uniform(.45, .9)), measurement_completeness=float(rng.uniform(.25, .75)))
    elif family == "multiple_tools_available": tools.update(analysis_available=True, simulation_available=True, optimization_available=True); sim_ready = True; opt_ready = True
    elif family == "contradictory_readiness": opt_ready = True; sim_ready = False; sim["input_ready"] = False; opt["optimization_ready"] = True; opt["constraint_validation_status"] = "INVALID"
    elif family == "partial_missingness": meas["available_modality_count"] = None; sim["input_ready"] = None; prov["source_completeness"] = "UNKNOWN"
    elif family == "unseen_condition_combination":
        state["experiment"]["process_step_count"] = int(rng.integers(7, 13)); meas["available_modality_count"] = 3; sim_ready = True; opt_ready = bool(rng.random() < .5)
    if rng.random() < .18:  # independent, non-class-specific missingness
        field = rng.choice(["available_modality_count", "uncertainty_missing_count", "accepted_observation_count", "pending_run_count"])
        if field in meas: meas[field] = None
        else: sim[field] = None
    ana.update(completed_analysis_count=int(rng.integers(0, 3)), pending_analysis_count=int(analysis_pending),
               failed_analysis_count=0, review_status="PENDING" if analysis_pending else "NOT_REQUIRED")
    sim.update(input_ready=bool(sim.get("input_ready") or sim_ready), completed_run_count=int(rng.integers(0, 2)),
               pending_run_count=0, failed_run_count=0)
    opt.update(gp_model_available=bool(opt.get("gp_model_available") or opt_ready), gp_model_valid=True if opt_ready else None,
               training_data_sufficient=True if opt_ready else False,
               prediction_uncertainty_available=bool(opt.get("prediction_uncertainty_available") or opt_ready),
               optimization_ready=bool(opt.get("optimization_ready") or opt_ready))
    tools.update(analysis_available=True, simulation_available=bool(sim_ready), optimization_available=bool(opt_ready))
    prov["missing_required_information_count"] = int(rng.integers(1, 4)) if accepted < 2 else 0
    pending["analysis_review_count"] = int(analysis_pending); pending["optimization_review_count"] = int(review)
    # Scenario contract derives a conservative action from observed facts. Ambiguous overlaps are intentionally labeled for review/abstention.
    if meas.get("unit_compatibility") == "INCOMPATIBLE" or prov.get("data_quality_gate") == "BLOCK" or review or prov["validity"] in {"INVALID", "PARTIAL"} or (meas.get("mean_relative_uncertainty") or 0) >= .4:
        label = "REQUEST_REVIEW"
    elif prov["missing_required_information_count"] > 0 or accepted < 2 or completeness < .3:
        label = "REQUEST_INFORMATION"
    elif opt.get("optimization_ready") and opt.get("constraint_validation_status") == "VALID" and accepted >= 4:
        label = "OPTIMIZE"
    elif sim.get("input_ready") and not sim.get("researcher_approval_required"):
        label = "SIMULATE"
    elif ana.get("pending_analysis_count") or ana.get("completed_analysis_count", 0) == 0:
        label = "ANALYZE"
    else:
        label = "ABSTAIN"
    if rng.random() < .08:
        label = str(rng.choice(["REQUEST_REVIEW", "ABSTAIN"]))
    state["source_provenance"].update({"scenario_family": family, "seed": seed,
        "case_group_id": f"s3-{seed}-group-{index}", "method_fold": f"method-{index % 3}", "topic_fold": f"topic-{index % 5}"})
    return state, label, f"s3-{seed}-group-{index}"


def generate_scenarios(seed: int, samples: int = 576) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    records = []
    for index in range(samples):
        state, action, group = _scenario(rng, index, seed)
        vector, metadata = extract_features(state)
        # Convert only explicitly available fields into the old contract for a fair V1 comparator.
        old = {
            "accepted_observation_count": state["measurements"].get("accepted_observation_count"),
            "measurement_completeness": state["measurements"].get("measurement_completeness"),
            "available_analysis_count": state["analysis"].get("completed_analysis_count"),
            "pending_analysis_count": state["analysis"].get("pending_analysis_count"),
            "analysis_tool_available": state["tool_readiness"].get("analysis_available"),
            "available_simulation_count": state["simulation"].get("completed_run_count"),
            "simulation_tool_available": state["tool_readiness"].get("simulation_available"),
            "gp_model_ready": state["optimization"].get("gp_model_available"),
            "optimization_ready": state["optimization"].get("optimization_ready"),
            "optimization_tool_available": state["tool_readiness"].get("optimization_available"),
            "pending_review_count": state["pending_reviews"].get("measurement_review_count", 0) + state["pending_reviews"].get("analysis_review_count", 0),
            "missing_required_information_count": state["provenance"].get("missing_required_information_count"),
            "provenance_valid": state["provenance"].get("validity") == "VALID",
            "validation_status": state["measurements"].get("measurement_completeness") or 0.0,
            "workflow_state": 0.0,
        }
        records.append({"state": state, "features_v2": vector, "feature_metadata": metadata,
                        "features_v1_state": old, "group_id": group, "action": action,
                        "scenario_family": state["source_provenance"]["scenario_family"],
                        "method_group": state["source_provenance"]["method_fold"],
                        "topic_group": state["source_provenance"]["topic_fold"]})
    return records


def _macro_metrics(y_true: list[str], predictions: list[str]) -> dict[str, Any]:
    classes = list(ACTIONS)
    per_class = {}
    for action in classes:
        tp = sum(a == action and b == action for a, b in zip(y_true, predictions))
        fp = sum(a != action and b == action for a, b in zip(y_true, predictions))
        fn = sum(a == action and b != action for a, b in zip(y_true, predictions))
        per_class[action] = {"precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn),
                             "support": sum(a == action for a in y_true)}
    accuracy = sum(a == b for a, b in zip(y_true, predictions)) / max(1, len(y_true))
    return {"accuracy": accuracy, "balanced_accuracy": float(np.mean([per_class[a]["recall"] for a in classes if per_class[a]["support"]])) if any(per_class[a]["support"] for a in classes) else 0,
            "macro_f1": float(np.mean([2 * per_class[a]["precision"] * per_class[a]["recall"] / max(1e-12, per_class[a]["precision"] + per_class[a]["recall"]) for a in classes])),
            "per_class": per_class, "confusion_matrix": {"labels": classes, "counts": [[sum(a == actual and b == predicted for a, b in zip(y_true, predictions)) for predicted in classes] for actual in classes]}}


def _v1_predict(model: LearnedDecisionHead, states: list[dict[str, Any]]) -> tuple[list[str], np.ndarray]:
    from app.services.decision_head import encode_state
    vectors = np.vstack([encode_state(state) for state in states])
    probs = model.predict_proba(vectors)
    return [ACTIONS[int(i)] for i in np.argmax(probs, axis=1)], probs


def _v2_metrics(y_true: list[str], probs: np.ndarray, model: StructuredDecisionHeadV2) -> dict[str, Any]:
    basic = _macro_metrics(y_true, [ACTIONS[int(i)] for i in np.argmax(probs, axis=1)])
    cal = calibration_metrics(y_true, probs)
    conf = probs.max(axis=1); pred = np.asarray([ACTIONS[int(i)] for i in np.argmax(probs, axis=1)])
    covered = conf >= model.confidence_threshold
    basic.update({"negative_log_likelihood": cal["negative_log_likelihood"], "brier_score": cal["brier_score"],
                  "expected_calibration_error_10_bins": cal["expected_calibration_error_10_bins"],
                  "reliability_bins": cal["reliability_bins"], "risk_coverage": cal["risk_coverage"],
                  "selective_coverage": float(covered.mean()), "selective_risk": float(np.mean(pred[covered] != np.asarray(y_true)[covered])) if covered.any() else None,
                  "confidence_threshold": model.confidence_threshold, "calibration_status": "CALIBRATED" if model.calibrated else "INSUFFICIENT_CALIBRATION_DATA"})
    return basic


def _ood_probe(model: StructuredDecisionHeadV2, states: list[dict[str, Any]]) -> dict[str, Any]:
    in_states = states[:min(120, len(states))]
    out_states = []
    for source in in_states:
        item = json.loads(json.dumps(source))
        item["experiment"]["process_step_count"] = 100 + int(item["experiment"].get("process_step_count") or 0)
        item["measurements"]["measurement_completeness"] = 1.0
        item["optimization"]["prediction_uncertainty_available"] = not bool(item["optimization"].get("prediction_uncertainty_available"))
        out_states.append(item)
    in_results = [model.predict_safe(item) for item in in_states]
    out_results = [model.predict_safe(item) for item in out_states]
    fp = sum(x["ood_status"] != "IN_DISTRIBUTION" for x in in_results) / max(1, len(in_results))
    tp = sum(x["ood_status"] != "IN_DISTRIBUTION" for x in out_results) / max(1, len(out_results))
    return {"status": "SYNTHETIC_PROBE_ONLY", "in_distribution_count": len(in_results), "shifted_probe_count": len(out_results),
            "in_distribution_false_positive_rate": fp, "shift_detection_rate": tp,
            "ood_abstention_rate": sum(x["action"] == "ABSTAIN" for x in out_results) / max(1, len(out_results)),
            "method": "standardized training distribution distance and missing/context safety gates"}


def _inference_latency_ms(predict, sample, iterations=100):
    start=time.perf_counter()
    for _ in range(iterations): predict(sample)
    return (time.perf_counter()-start)*1000/iterations


def _ablation(model: StructuredDecisionHeadV2, x_test: np.ndarray, y_test: list[str]) -> dict[str, Any]:
    baseline = _v2_metrics(y_test, model.predict_proba(x_test), model)["macro_f1"]
    result = {"baseline_macro_f1": baseline, "groups": {}}
    for group, feature_names in FEATURE_GROUPS.items():
        indexes = np.asarray([i for i, item in enumerate(FEATURE_SCHEMA["features"]) if item["group"] == group], dtype=int)
        changed = x_test.copy(); changed[:, indexes] = model.mean[indexes]
        score = _v2_metrics(y_test, model.predict_proba(changed), model)["macro_f1"]
        result["groups"][group] = {"ablated_feature_count": int(len(indexes)), "macro_f1": score, "delta_from_baseline": score - baseline,
                                    "interpretation": "predictive sensitivity only; not causal importance"}
    return result


def run_robustness_benchmark(*, seeds=SEEDS, samples_per_seed=576) -> dict[str, Any]:
    if len(seeds) < 5:
        raise ScientificStateError("Stage 3 benchmark requires at least five independent seeds")
    seed_results = []
    tracemalloc.start()
    overall_start = time.perf_counter()
    for seed in seeds:
        records = generate_scenarios(int(seed), samples_per_seed)
        groups = np.asarray([x["group_id"] for x in records])
        fit, cal, test = split_groups(groups, seed=int(seed))
        x2 = np.vstack([x["features_v2"] for x in records]); y = [x["action"] for x in records]
        v1_states = [x["features_v1_state"] for x in records]
        from app.services.decision_head import encode_state
        x1 = np.vstack([encode_state(x) for x in v1_states])
        start = time.perf_counter(); v1, v1_loss = LearnedDecisionHead.fit(x1[fit], [y[i] for i in fit], seed=int(seed))
        v1.calibrate(x1[cal], [y[i] for i in cal]); p1 = v1.predict_proba(x1[test]); v1_time = (time.perf_counter() - start) * 1000
        start = time.perf_counter(); v2, v2_loss = StructuredDecisionHeadV2.fit(x2[fit], [y[i] for i in fit], seed=int(seed))
        v2.calibrate(x2[cal], [y[i] for i in cal]); p2 = v2.predict_proba(x2[test]); v2_time = (time.perf_counter() - start) * 1000
        y_test = [y[i] for i in test]
        v1_metric = _macro_metrics(y_test, [ACTIONS[int(i)] for i in p1.argmax(axis=1)])
        v1_cal = calibration_metrics(y_test, p1); v1_metric.update({k: v1_cal[k] for k in ("negative_log_likelihood", "brier_score", "expected_calibration_error_10_bins", "risk_coverage")})
        v2_metric = _v2_metrics(y_test, p2, v2)
        v1_latency=_inference_latency_ms(lambda sample:v1.predict_proba(sample),x1[test[:1]])
        v2_latency=_inference_latency_ms(lambda sample:v2.predict_proba(sample),x2[test[:1]])
        rule = rule_metrics([records[i]["features_v1_state"] for i in test], y_test)
        majority = majority_metrics([y[i] for i in fit], y_test)
        family_indexes = {family: [j for j, idx in enumerate(test) if records[idx]["scenario_family"] == family] for family in SCENARIO_FAMILIES}
        scenario_generalization = {family: {"sample_count": len(indexes), "accuracy": float(np.mean([ACTIONS[int(p2[j].argmax())] == y_test[j] for j in indexes])) if indexes else None}
                                   for family, indexes in family_indexes.items()}
        # A genuinely held-out condition-family check. No examples from the unseen
        # combination family participate in fitting or calibration.
        shift_test = np.asarray([i for i, item in enumerate(records) if item["scenario_family"] == "unseen_condition_combination"], dtype=int)
        shift_pool = np.asarray([i for i, item in enumerate(records) if item["scenario_family"] != "unseen_condition_combination"], dtype=int)
        shift_fit_local, shift_cal_local, shift_extra_local = split_groups([groups[i] for i in shift_pool], seed=int(seed) + 1000)
        shift_fit = shift_pool[np.concatenate([shift_fit_local, shift_extra_local])]
        shift_cal = shift_pool[shift_cal_local]
        shift_v1, _ = LearnedDecisionHead.fit(x1[shift_fit], [y[i] for i in shift_fit], seed=int(seed))
        shift_v1.calibrate(x1[shift_cal], [y[i] for i in shift_cal]); shift_p1 = shift_v1.predict_proba(x1[shift_test])
        shift_v2, _ = StructuredDecisionHeadV2.fit(x2[shift_fit], [y[i] for i in shift_fit], seed=int(seed))
        shift_v2.calibrate(x2[shift_cal], [y[i] for i in shift_cal]); shift_p2 = shift_v2.predict_proba(x2[shift_test])
        shift_y = [y[i] for i in shift_test]
        condition_shift_holdout = {"held_out_family": "unseen_condition_combination", "train_families": list(SCENARIO_FAMILIES[:-1]),
            "train_count": int(len(shift_fit)), "calibration_count": int(len(shift_cal)), "test_count": int(len(shift_test)),
            "group_overlap": bool(set(groups[shift_fit]) & set(groups[shift_cal]) or set(groups[shift_fit]) & set(groups[shift_test]) or set(groups[shift_cal]) & set(groups[shift_test])),
            "v1": _macro_metrics(shift_y, [ACTIONS[int(i)] for i in shift_p1.argmax(axis=1)]),
            "v2": _macro_metrics(shift_y, [ACTIONS[int(i)] for i in shift_p2.argmax(axis=1)])}
        train_groups = {groups[i] for i in fit}; cal_groups = {groups[i] for i in cal}; test_groups = {groups[i] for i in test}
        seed_results.append({"seed": int(seed), "counts": {"total": len(records), "fit": len(fit), "calibration": len(cal), "test": len(test),
            "fit_groups": len(train_groups), "calibration_groups": len(cal_groups), "test_groups": len(test_groups)},
            "group_leakage": bool(train_groups & cal_groups or train_groups & test_groups or cal_groups & test_groups),
            "label_distribution": dict(Counter(y)), "majority_baseline": majority, "rule_baseline": rule,
            "v1": {**v1_metric, "fit_runtime_ms": v1_time,"inference_latency_ms_per_case":v1_latency, "parameter_count": int(sum(x.size for x in (v1.mean, v1.scale, v1.hidden_weight, v1.hidden_bias, v1.output_weight, v1.output_bias))),
                   "model_size_bytes": len(json.dumps(v1.to_dict(), separators=(",", ":")).encode())},
            "v2": {**v2_metric, "fit_runtime_ms": v2_time,"inference_latency_ms_per_case":v2_latency, "parameter_count": v2.parameter_count,
                   "model_size_bytes": len(json.dumps(v2.to_dict(), separators=(",", ":")).encode()),
                   "scenario_family_accuracy": scenario_generalization, "ablation": _ablation(v2, x2[test], y_test),
                   "ood_probe": _ood_probe(v2, [records[i]["state"] for i in test]), "condition_shift_holdout": condition_shift_holdout},
            "training_loss": {"v1_initial": v1_loss[0], "v1_final": v1_loss[-1], "v2_initial": v2_loss[0], "v2_final": v2_loss[-1]}})
    elapsed = time.perf_counter() - overall_start
    _, peak_memory = tracemalloc.get_traced_memory(); tracemalloc.stop()
    metric_fields = ("accuracy", "balanced_accuracy", "macro_f1", "negative_log_likelihood", "brier_score", "expected_calibration_error_10_bins")
    summary = {}
    for model_name in ("majority_baseline", "rule_baseline", "v1", "v2"):
        summary[model_name] = {}
        fields = metric_fields if model_name in {"v1", "v2"} else ("accuracy", "macro_f1")
        for metric in fields:
            vals = [item[model_name].get(metric) for item in seed_results if isinstance(item[model_name].get(metric), (int, float))]
            summary[model_name][metric] = {"mean": float(np.mean(vals)) if vals else None, "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else None,
                                           "seed_count": len(vals), "per_seed": vals}
    all_records = generate_scenarios(9091, samples_per_seed)
    _, _, final_test_ix = split_groups([x["group_id"] for x in all_records], seed=9091)
    holdout_groups = {all_records[int(i)]["group_id"] for i in final_test_ix}
    frozen_hash = stable_hash([{"group_id": x["group_id"], "features": x["features_v2"].tolist(), "action": x["action"]}
                               for x in all_records if x["group_id"] in holdout_groups])
    return {"benchmark_version": BENCHMARK_VERSION, "benchmark_status": "COMPLETED_SYNTHETIC_SOFTWARE_EVALUATION",
        "scientific_state_schema_version": "scientific-state-v2", "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
        "feature_count": len(FEATURE_NAMES), "feature_groups": {k: len(v) for k, v in FEATURE_GROUPS.items()},
        "scenario_families": list(SCENARIO_FAMILIES), "scenario_source": "independent synthetic scenario contract; not expert labels or research data",
        "seeds": [int(x) for x in seeds], "seed_count": len(seeds), "samples_per_seed": samples_per_seed,
        "split": {"strategy": "group-disjoint fit/calibration/test 60/20/20", "same_group_in_multiple_partitions": False,
                  "fit_validation_test_counts_per_seed": seed_results[0]["counts"], "cross_method_holdout": "INSUFFICIENT_DATA: single-topic benchmark generator is not an independent method validation set",
                  "cross_topic_holdout": "INSUFFICIENT_DATA: no independently reviewed multi-topic corpus",
        "condition_shift": "unseen_condition_combination fully withheld from fit/calibration and evaluated separately per seed"},
        "dataset_hash": stable_hash([{ "seed": x["seed"], "counts": x["counts"], "labels": x["label_distribution"]} for x in seed_results]),
        "frozen_evaluation_hash": frozen_hash, "independent_groups_per_seed": seed_results[0]["counts"]["test_groups"],
        "results_by_seed": seed_results, "summary": summary,
        "runtime_seconds": elapsed, "peak_python_memory_bytes": int(peak_memory), "runtime_environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        "limitations": ["All benchmark labels are generated by a declared synthetic scenario contract, not experts.",
                        "Synthetic metrics verify implementation and robustness checks only; they do not measure scientific or laboratory decision accuracy.",
                        "No cross-topic or cross-laboratory generalization claim is possible without independent reviewed data.",
                        "Calibration scores are not probabilities of experiment success.",
                        "Feature ablation is predictive sensitivity, not causal attribution.",
                        "OOD probe measures response to constructed distribution shifts, not deployment OOD performance."]}
