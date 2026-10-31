"""Reliability protocol invariants for Phase 5 Stage 4."""
import numpy as np

from app.services.phase5_stage4 import (
    _make_fresh_final,
    _hash_feature_records,
    _metric_report,
    _ood_variant_matrix,
    _risk_coverage,
    _risk_threshold,
    _wilson_upper,
)
from app.services.scientific_state_v2 import ACTION_NAMES, FEATURE_SCHEMA, extract_features


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
