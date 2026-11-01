"""Reliability protocol invariants for Phase 5 Stage 4."""
import numpy as np

from app.services.phase5_stage4 import (
    _make_fresh_final,
    _hash_feature_records,
    _fpr_at_target_tpr,
    _metric_report,
    _ood_variant_matrix,
    _risk_coverage,
    _risk_threshold,
    _wilson_upper,
)
from app.services.scientific_state_v2 import ACTION_NAMES, FEATURE_SCHEMA, extract_features


def test_fpr95_uses_ood_positive_roc_and_is_not_the_operating_threshold():
    perfect = _fpr_at_target_tpr([0.1, 0.2, 0.3], [0.7, 0.8, 0.9])
    assert perfect["value"] == 0.0
    assert perfect["achieved_tpr"] == 1.0
    reversed_scores = _fpr_at_target_tpr([0.7, 0.8, 0.9], [0.1, 0.2, 0.3])
    assert reversed_scores["value"] == 1.0
    overlap = _fpr_at_target_tpr([0.1, 0.4, 0.6, 0.9], [0.3, 0.5, 0.7, 0.8])
    assert 0.0 <= overlap["value"] <= 1.0
    assert overlap["achieved_tpr"] >= 0.95
    tied = _fpr_at_target_tpr([0.5] * 4, [0.5] * 4)
    assert tied["value"] == 1.0
    assert tied["threshold"] == 0.5
    invalid = _fpr_at_target_tpr([np.nan], [0.1])
    assert invalid["status"] == "INSUFFICIENT_OR_INVALID_DATA"


def test_fpr95_matches_sklearn_roc_reference_without_using_operating_threshold():
    from sklearn.metrics import roc_curve

    id_scores=np.array([0.1, 0.4, 0.6, 0.9])
    ood_scores=np.array([0.3, 0.5, 0.7, 0.8])
    labels=np.r_[np.zeros(len(id_scores),dtype=int),np.ones(len(ood_scores),dtype=int)]
    fpr,tpr,_=roc_curve(labels,np.r_[id_scores,ood_scores],pos_label=1,drop_intermediate=False)
    expected=float(np.min(fpr[tpr>=.95]))
    got=_fpr_at_target_tpr(id_scores,ood_scores)
    assert got["value"] == expected
    assert got["operational_threshold_selection_uses_evaluation_data"] is False
    assert got["status"] == "MEASURED_ON_EVALUATION_LABELS"


def test_fresh_final_uses_state_derived_labels_and_independent_groups():
    rows = _make_fresh_final(seed=20261031, samples=240)
    assert len({row["group_id"] for row in rows}) == len(rows)
    assert set(row["action"] for row in rows) == set(ACTION_NAMES)
    assert {row["scenario_family"] for row in rows} == {"independent_composition"}
    assert len({tuple(np.round(row["features_v2"], 6)) for row in rows}) > 200


def test_risk_threshold_is_calibration_only_and_reports_insufficient_evidence():
    probs = np.eye(len(ACTION_NAMES))[np.arange(12) % len(ACTION_NAMES)]
    labels = [ACTION_NAMES[i % len(ACTION_NAMES)] for i in range(12)]
    report = _risk_threshold(probs, labels, min_covered=24)
    assert report["status"] == "INSUFFICIENT_CALIBRATION_EVIDENCE"
    assert report["threshold"] is None
    assert _wilson_upper(0, 12) > 0


def test_metrics_and_risk_coverage_cover_all_actions():
    probs = np.eye(len(ACTION_NAMES))[np.arange(30) % len(ACTION_NAMES)]
    labels = [ACTION_NAMES[i % len(ACTION_NAMES)] for i in range(30)]
    metrics = _metric_report(labels, probs)
    curve = _risk_coverage(probs, labels)
    assert metrics["accuracy"] == 1.0
    assert set(metrics["per_class"]) == set(ACTION_NAMES)
    assert curve["curve"] and curve["curve"][-1]["coverage"] == 1.0


def test_ood_probe_matrix_includes_shift_and_invalid_state_families():
    rows = _make_fresh_final(seed=91, samples=36)
    x = np.vstack([row["features_v2"] for row in rows])
    shifts = _ood_variant_matrix(x, FEATURE_SCHEMA, 91)
    assert {
        "extreme_feature_shift",
        "mild_feature_shift",
        "unseen_cross_context_combination",
        "missingness_shift",
        "categorical_shift",
        "contradictory_scientific_state",
        "unsupported_state_pattern",
        "provenance_failure",
    } <= set(shifts)
    assert all(value.shape == x.shape for value in shifts.values())


def test_stage4_fixture_keeps_explicit_observed_state_encoding():
    row = _make_fresh_final(seed=7, samples=1)[0]
    vector, metadata = extract_features(row["state"])
    np.testing.assert_allclose(vector, row["features_v2"])
    assert metadata["schema_version"] == FEATURE_SCHEMA["schema_version"]


def test_dataset_hash_is_stable_after_sub_precision_float_drift():
    rows = _make_fresh_final(seed=51, samples=12)
    first = _hash_feature_records(rows)
    for row in rows:
        row["features_v2"] = row["features_v2"] + 1e-10
    assert _hash_feature_records(rows) == first
