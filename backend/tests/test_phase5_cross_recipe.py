from app.services.phase5_cross_recipe import run_cross_recipe_transfer


def test_cross_recipe_transfer_freezes_source_and_evaluates_common_target_test():
    report = run_cross_recipe_transfer(samples_per_recipe=144)
    assert report["protocol_version"] == "phase5-stage4-zero-shot-cross-recipe-v1"
    assert report["source_target_group_overlap"] == []
    assert report["target_split"]["test"] > 0
    assert set(report["zero_shot_metrics"]) == {
        "rule", "v1", "v2", "v2_class_weighted", "hist_gradient_boosting"
    }
    assert set(report["zero_shot_metrics"]) == set(report["target_retrained_metrics"])
    assert all(item["unchanged"] for item in report["model_freeze_verification"].values())
    assert all(value["accuracy_target_minus_zero_shot"] == 0 for name, value in report["transfer_gap"].items() if name == "rule")
    assert "Evaluation metrics" in report["target_label_use"]
    for name in report["zero_shot_metrics"]:
        assert report["zero_shot_metrics"][name]["sample_count"] == report["target_split"]["test"]
        assert report["target_retrained_metrics"][name]["sample_count"] == report["target_split"]["test"]
