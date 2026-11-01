import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase6_ee_research as ee
import phase6_ee_combo_comparison as combos


def test_independent_split_groups_are_disjoint():
    rows = [{"group_id": f"g{i}"} for i in range(100)]
    partitions = ee._splits(rows)
    memberships = [{rows[i]["group_id"] for i in idx} for idx in partitions.values()]
    assert all(not memberships[i] & memberships[j] for i in range(len(memberships)) for j in range(i + 1, len(memberships)))
    assert sum(len(idx) for idx in partitions.values()) == len(rows)


def test_exact_binomial_upper_bound_is_conservative_at_zero_errors():
    assert ee._cp_upper(0, 24) < ee._wilson_upper(0, 24)
    assert ee._cp_upper(0, 24) < ee.TARGET_RISK
    assert ee._cp_upper(1, 24) > ee._cp_upper(0, 24)


def test_router_feature_builder_uses_only_observed_exit_prefix():
    probs = {
        7: np.tile([.7, .2, .1], (2, 1)),
        14: np.tile([.2, .7, .1], (2, 1)),
        21: np.tile([.1, .2, .7], (2, 1)),
        28: np.tile([.5, .3, .2], (2, 1)),
    }
    prefix = ee._features_for_router(probs, (7, 14, 21, 28), 1)
    assert prefix.shape == (2, 16)
    # Mutating future heads cannot affect the feature vector through layer 14.
    probs[21][:] = [1., 0., 0.]
    probs[28][:] = [0., 0., 1.]
    np.testing.assert_allclose(prefix, ee._features_for_router(probs, (7, 14, 21, 28), 1))


def test_exit_router_falls_back_to_final_layer_without_valid_threshold():
    probs = {7: np.array([[.99, .01]]), 14: np.array([[.99, .01]]), 21: np.array([[.99, .01]]), 28: np.array([[.01, .99]])}
    prediction, exits = ee._route(probs, (7, 14, 21, 28), {7: None, 14: None, 21: None})
    assert exits.tolist() == [28]
    assert prediction.tolist() == [1]


def test_combo_router_rejects_ood_exit_and_falls_back_to_full_depth():
    probs = {7: np.array([[.99, .01]]), 14: np.array([[.99, .01]]),
             21: np.array([[.99, .01]]), 28: np.array([[.01, .99]])}
    ood = {layer: {"selection": np.array([True])} for layer in combos.LAYERS}
    prediction, exits = combos._route({layer: {"selection": p} for layer, p in probs.items()},
        "selection", {7: .9, 14: .9, 21: .9}, "max_softmax", np.array([1]), np.array([0]), ood=ood)
    assert exits.tolist() == [28]
    assert prediction.tolist() == [1]


def test_combo_calibration_keeps_minimum_sample_and_fixed_risk_target():
    y = np.array([0, 1] * 30)
    probs = {layer: {"calibration": np.tile([.99, .01], (60, 1))} for layer in combos.LAYERS}
    thresholds = combos._calibrate(probs, y, np.arange(60), "max_softmax")
    assert thresholds[7] is None
    assert combos.TARGET_RISK == .20
    assert combos.MIN_EXITS == 24
