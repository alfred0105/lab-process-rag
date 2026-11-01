"""Frozen zero-shot transfer evaluation across independent synthetic recipes.

The report validates software behavior only. Target labels are used only for
evaluation metrics and never for fitting, calibration, thresholds, or selection.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from collections import Counter
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from app.services.decision_head import ACTIONS, LearnedDecisionHead, encode_state, rule_metrics
from app.services.phase5_stage3 import generate_scenarios, split_groups
from app.services.phase5_stage4 import (
    _align_tree_proba,
    _apply_temperature,
    _class_weights,
    _hash_feature_records,
    _metric_report,
    _risk_threshold,
    _selective_eval,
    _temperature_from_calibration,
)
from app.services.scientific_state_v2 import (
    ACTION_NAMES,
    StructuredDecisionHeadV2,
    extract_features,
)
from app.services.phase5_stage4 import _make_fresh_final

PROTOCOL = "phase5-stage4-zero-shot-cross-recipe-v1"
SOURCE_SEED = 61327
TARGET_SEED = 82471
SPLIT_SEED_SOURCE = 190811
SPLIT_SEED_TARGET = 290821


def _state_features(rows):
    x2 = np.vstack([row["features_v2"] for row in rows])
    x1 = np.vstack([encode_state(row["features_v1_state"]) for row in rows])
    y = [row["action"] for row in rows]
    return x1, x2, y


def _weights_digest(model) -> str:
    if hasattr(model, "to_dict"):
        payload = json.dumps(model.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    else:
        payload = pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)
    return hashlib.sha256(payload).hexdigest()


def _probabilities(model_name, model, x1, x2):
    if model_name == "rule":
        raise ValueError("Rule probabilities require source states and are computed by the caller")
    if model_name == "v1":
        return model.predict_proba(x1)
    if model_name in {"v2", "v2_class_weighted"}:
        return model.predict_proba(x2)
    if model_name == "hist_gradient_boosting":
        return _align_tree_proba(model, x2)
    raise ValueError(f"Unsupported transfer comparator: {model_name}")


def _score_ood_rms(x_fit, x_cal, x_id, x_shift):
    """A single prespecified detector: source-fit scaling and ID-calibration q95."""
    mean = np.mean(x_fit, axis=0)
    scale = np.std(x_fit, axis=0)
    scale[scale < 1e-8] = 1.0

    def score(x):
        z = np.clip((x - mean) / scale, -8, 8)
        return np.sqrt(np.mean(z * z, axis=1))

    cal_scores = score(x_cal)
    threshold = float(np.quantile(cal_scores, .95, method="higher"))
    id_scores = score(x_id)
    shift_scores = score(x_shift)
    return {
        "detector": "standardized_rms",
        "threshold": threshold,
        "threshold_source": "training_scaling_plus_id_calibration_q95_only",
        "id_false_positive_rate": float(np.mean(id_scores >= threshold)),
        "shift_detection_rate": float(np.mean(shift_scores >= threshold)),
        "id_count": int(len(id_scores)),
        "shift_count": int(len(shift_scores)),
    }


def _rule_probabilities(rows, labels):
    states = [row["features_v1_state"] for row in rows]
    predictions = rule_metrics(states, labels)["predictions"]
    probs = np.zeros((len(predictions), len(ACTION_NAMES)), dtype=float)
    for index, action in enumerate(predictions):
        probs[index, ACTION_NAMES.index(action)] = 1.0
    return probs


def _fit_candidates(x1, x2, labels, fit_idx, cal_idx, *, seed: int):
    y_fit = [labels[i] for i in fit_idx]
    y_cal = [labels[i] for i in cal_idx]
    candidates = {}

    v1, v1_losses = LearnedDecisionHead.fit(x1[fit_idx], y_fit, seed=seed)
    v1.calibrate(x1[cal_idx], y_cal)
    candidates["v1"] = {"model": v1, "train_loss_first": float(v1_losses[0]), "train_loss_last": float(v1_losses[-1])}

    v2, v2_losses = StructuredDecisionHeadV2.fit(x2[fit_idx], y_fit, seed=seed)
    v2.calibrate(x2[cal_idx], y_cal)
    candidates["v2"] = {"model": v2, "train_loss_first": float(v2_losses[0]), "train_loss_last": float(v2_losses[-1])}

    class_weights = _class_weights(y_fit)
    weights = np.asarray([class_weights[action] for action in y_fit], dtype=float)
    weighted, weighted_losses = StructuredDecisionHeadV2.fit(x2[fit_idx], y_fit, seed=seed, sample_weights=weights)
    weighted.calibrate(x2[cal_idx], y_cal)
    candidates["v2_class_weighted"] = {"model": weighted, "train_loss_first": float(weighted_losses[0]), "train_loss_last": float(weighted_losses[-1])}

    tree = HistGradientBoostingClassifier(max_iter=120, max_leaf_nodes=15, l2_regularization=1.0, random_state=seed)
    tree.fit(x2[fit_idx], y_fit)
    tree_cal = _align_tree_proba(tree, x2[cal_idx])
    tree_temperature = _temperature_from_calibration(tree_cal, y_cal)
    candidates["hist_gradient_boosting"] = {"model": tree, "temperature": tree_temperature}

    for name, candidate in candidates.items():
        candidate["source_model_digest_before_target_inference"] = _weights_digest(candidate["model"])
    return candidates


def _evaluate_candidates(candidates, rows, x1, x2, labels, indexes, *, calibration_probabilities, calibration_labels,
                         transform_tree_temperature=True):
    report = {}
    subset_rows = [rows[i] for i in indexes]
    subset_y = [labels[i] for i in indexes]
    for name, entry in candidates.items():
        model = entry["model"]
        if name == "rule":
            probabilities = _rule_probabilities(subset_rows, subset_y)
        else:
            probabilities = _probabilities(name, model, x1[indexes], x2[indexes])
            if name == "hist_gradient_boosting" and transform_tree_temperature:
                probabilities = _apply_temperature(probabilities, entry["temperature"])
        metrics = _metric_report(subset_y, probabilities)
        cal_prob = calibration_probabilities[name]
        threshold = _risk_threshold(cal_prob, calibration_labels[name])
        report[name] = {
            **metrics,
            "selective_prediction": _selective_eval(probabilities, subset_y, threshold.get("threshold")),
            "calibration_threshold": threshold,
            "source_model_digest_before_target_inference": entry.get("source_model_digest_before_target_inference"),
            "model_digest_after_target_inference": _weights_digest(model) if name != "rule" else None,
        }
        if name != "rule":
            report[name]["weights_unchanged_during_target_evaluation"] = (
                report[name]["source_model_digest_before_target_inference"] == report[name]["model_digest_after_target_inference"]
            )
    return report


def run_cross_recipe_transfer(*, samples_per_recipe: int = 576) -> dict[str, Any]:
    if samples_per_recipe < 120:
        raise ValueError("At least 120 independent groups per recipe are required for the fixed comparison protocol")

    source_rows = generate_scenarios(SOURCE_SEED, samples_per_recipe)
    target_rows = _make_fresh_final(seed=TARGET_SEED, samples=samples_per_recipe)
    for row in source_rows:
        row["group_id"] = f"source:{row['group_id']}"
    for row in target_rows:
        row["group_id"] = f"target:{row['group_id']}"
    source_x1, source_x2, source_y = _state_features(source_rows)
    target_x1, target_x2, target_y = _state_features(target_rows)
    source_groups = [r["group_id"] for r in source_rows]
    target_groups = [r["group_id"] for r in target_rows]
    s_fit, s_cal, s_test = split_groups(source_groups, seed=SPLIT_SEED_SOURCE)
    t_fit, t_cal, t_test = split_groups(target_groups, seed=SPLIT_SEED_TARGET)

    source_models = _fit_candidates(source_x1, source_x2, source_y, s_fit, s_cal, seed=SOURCE_SEED)
    target_models = _fit_candidates(target_x1, target_x2, target_y, t_fit, t_cal, seed=TARGET_SEED)

    def calibration_for(models, rows, x1, x2, labels, cal_idx):
        result = {"rule": _rule_probabilities([rows[i] for i in cal_idx], [labels[i] for i in cal_idx])}
        for name, item in models.items():
            result[name] = _probabilities(name, item["model"], x1[cal_idx], x2[cal_idx])
            if name == "hist_gradient_boosting":
                result[name] = _apply_temperature(result[name], item["temperature"])
        return result

    source_cal = calibration_for(source_models, source_rows, source_x1, source_x2, source_y, s_cal)
    target_cal = calibration_for(target_models, target_rows, target_x1, target_x2, target_y, t_cal)
    source_cal_labels = {name: [source_y[i] for i in s_cal] for name in ["rule", *source_models]}
    target_cal_labels = {name: [target_y[i] for i in t_cal] for name in ["rule", *target_models]}

    source_frozen = {
        name: {**item, "source_model_digest_before_target_inference": _weights_digest(item["model"])}
        for name, item in source_models.items()
    }
    source_zeroshot = _evaluate_candidates(
        source_frozen, target_rows, target_x1, target_x2, target_y, t_test,
        calibration_probabilities=source_cal, calibration_labels=source_cal_labels,
    )
    target_retrained = _evaluate_candidates(
        target_models, target_rows, target_x1, target_x2, target_y, t_test,
        calibration_probabilities=target_cal, calibration_labels=target_cal_labels,
    )
    source_rule = {"rule": {"model": None, "source_model_digest_before_target_inference": None}}
    source_zeroshot["rule"] = _evaluate_candidates(
        source_rule, target_rows, target_x1, target_x2, target_y, t_test,
        calibration_probabilities={"rule": source_cal["rule"]}, calibration_labels={"rule": source_cal_labels["rule"]},
    )["rule"]
    target_retrained["rule"] = _evaluate_candidates(
        source_rule, target_rows, target_x1, target_x2, target_y, t_test,
        calibration_probabilities={"rule": target_cal["rule"]}, calibration_labels={"rule": target_cal_labels["rule"]},
    )["rule"]

    # For source models the target recipe is the shift probe; ID scores use the untouched source test split.
    # For target-trained controls, constructed mutations of the target test inputs are the OOD probes.
    rng = np.random.default_rng(TARGET_SEED + 991)
    shifts = target_x2[t_test].copy()
    numeric = np.flatnonzero(np.std(target_x2[t_fit], axis=0) > 1e-8)
    if len(numeric):
        shifts[:, numeric] += rng.normal(0, 2.5, size=(len(shifts), len(numeric)))
    ood = {}
    for mode, fit_idx, cal_idx, id_idx, ood_x in (
        ("source_trained", s_fit, s_cal, s_test, target_x2[t_test]),
        ("target_retrained", t_fit, t_cal, t_test, shifts),
    ):
        fitted = source_models if mode == "source_trained" else target_models
        x = source_x2 if mode == "source_trained" else target_x2
        for name in fitted:
            ood.setdefault(name, {})[mode] = _score_ood_rms(x[fit_idx], x[cal_idx], x[id_idx], ood_x)

    transfer_gap = {}
    for name in source_zeroshot:
        transfer_gap[name] = {
            "accuracy_target_minus_zero_shot": target_retrained[name]["accuracy"] - source_zeroshot[name]["accuracy"],
            "macro_f1_target_minus_zero_shot": target_retrained[name]["macro_f1"] - source_zeroshot[name]["macro_f1"],
            "balanced_accuracy_target_minus_zero_shot": target_retrained[name]["balanced_accuracy"] - source_zeroshot[name]["balanced_accuracy"],
        }

    source_target_overlap = sorted(set(source_groups) & set(target_groups))
    return {
        "report_version": "phase5-stage4-cross-recipe-transfer-v1",
        "protocol_version": PROTOCOL,
        "data_status": "SYNTHETIC_SOFTWARE_EVALUATION_ONLY",
        "source_recipe_version": "phase5-stage3-correlated-state-recipe-v1",
        "target_recipe_version": "phase5-stage4-transfer-independent-composition-v1",
        "source_generation_seed": SOURCE_SEED,
        "target_generation_seed": TARGET_SEED,
        "source_dataset_hash": _hash_feature_records(source_rows),
        "target_evaluation_hash": _hash_feature_records(target_rows, t_test),
        "source_target_group_overlap": source_target_overlap,
        "source_split": {"fit": len(s_fit), "calibration": len(s_cal), "test": len(s_test), "fit_groups": len(set(np.asarray(source_groups)[s_fit])), "calibration_groups": len(set(np.asarray(source_groups)[s_cal])), "test_groups": len(set(np.asarray(source_groups)[s_test]))},
        "target_split": {"fit": len(t_fit), "calibration": len(t_cal), "test": len(t_test), "fit_groups": len(set(np.asarray(target_groups)[t_fit])), "calibration_groups": len(set(np.asarray(target_groups)[t_cal])), "test_groups": len(set(np.asarray(target_groups)[t_test]))},
        "target_label_use": "Evaluation metrics and class-wise errors only; never used by source model training, source calibration, feature normalization, threshold selection, or candidate selection.",
        "model_freeze_verification": {name: {
            "source_digest_before_target_inference": source_zeroshot[name]["source_model_digest_before_target_inference"],
            "digest_after_target_inference": source_zeroshot[name]["model_digest_after_target_inference"],
            "unchanged": source_zeroshot[name].get("weights_unchanged_during_target_evaluation", True),
        } for name in source_zeroshot},
        "zero_shot_metrics": source_zeroshot,
        "target_retrained_metrics": target_retrained,
        "transfer_gap": transfer_gap,
        "ood_diagnostics": ood,
        "limitations": [
            "Both recipes and all action labels are synthetic software fixtures.",
            "Zero-shot results measure transfer between these programmed recipes only; they do not establish laboratory generalization.",
            "OOD uses standardized RMS only. Source-trained OOD treats target-recipe cases as shift probes; target-trained OOD uses a separate feature-perturbation probe.",
            "Calibration and selective thresholds are derived from each model's own calibration split, never target evaluation labels.",
            "Rule-based actions are deterministic; target-retrained is identical to zero-shot for that comparator by construction.",
        ],
    }
