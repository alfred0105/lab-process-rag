"""Stage 3 schema, model, benchmark, API and compatibility regressions."""
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import DecisionCase, DecisionDatasetVersion, DecisionModelRun, Experiment, ResearchTopic
from app.main import app
from app.services.decision_head import ACTIONS as V1_ACTIONS, FEATURE_SCHEMA_VERSION as V1_SCHEMA, LearnedDecisionHead, encode_state
from app.services.phase5_stage3 import SEEDS, generate_scenarios, run_robustness_benchmark, split_groups
from app.services.scientific_state_v2 import (
    ACTION_NAMES, FEATURE_NAMES, FEATURE_SCHEMA_VERSION_V2, ScientificStateError,
    StructuredDecisionHeadV2, extract_features, feature_schema, from_legacy_state,
)


def test_v2_feature_contract_is_fixed_and_keeps_v1_contract_distinct():
    assert FEATURE_SCHEMA_VERSION_V2 == "scientific-decision-features-v2"
    assert feature_schema()["feature_count"] == len(FEATURE_NAMES)
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert V1_SCHEMA != FEATURE_SCHEMA_VERSION_V2
    assert len(encode_state({"accepted_observation_count": 1})) > 0
    assert from_legacy_state({"accepted_observation_count": 1})["provenance"]["historical_state_insufficient"] is True


def test_missing_measurement_is_distinct_from_observed_zero():
    missing, _ = extract_features({})
    observed, _ = extract_features({"measurements": {"accepted_observation_count": 0}})
    value_index = FEATURE_NAMES.index("measurements__accepted_observation_count")
    mask_index = FEATURE_NAMES.index("measurements__accepted_observation_count__missing_mask")
    assert missing[value_index] == observed[value_index] == 0
    assert missing[mask_index] == 1 and observed[mask_index] == 0


def test_dimensioned_process_units_are_invariant_and_traceable():
    c, cm = extract_features({"process_conditions": {"items": [{"name": "temperature", "dimension": "temperature", "value": 25, "unit": "degC"}]}})
    k, km = extract_features({"process_conditions": {"items": [{"name": "temperature", "dimension": "temperature", "value": 298.15, "unit": "K"}]}})
    np.testing.assert_allclose(c, k, atol=1e-8)
    assert cm["unit_normalization"]["conversions"][0]["original_unit"] == "degC"
    assert km["unit_normalization"]["conversions"][0]["normalized_unit"] == "degC"


def test_v2_train_roundtrip_and_safe_unsupported_state():
    records = generate_scenarios(31, 180)
    x = np.vstack([r["features_v2"] for r in records[:144]])
    y = [r["action"] for r in records[:144]]
    model, _ = StructuredDecisionHeadV2.fit(x, y, seed=31)
    model.calibrate(x[:72], y[:72])
    restored = StructuredDecisionHeadV2.from_dict(model.to_dict())
    np.testing.assert_allclose(model.predict_proba(x[72:80]), restored.predict_proba(x[72:80]))
    state = records[0]["state"] | {"optimization": {"optimization_ready": True, "gp_model_available": False}}
    result = restored.predict_safe(state)
    assert result["ood_status"] == "UNSUPPORTED_STATE"
    assert result["action"] == "ABSTAIN"
    assert result["workflow_triggered"] is False


def test_group_split_and_five_seed_benchmark_have_no_leakage():
    fit, calibration, test = split_groups([f"g{i}" for i in range(180)], seed=71)
    groups = np.asarray([f"g{i}" for i in range(180)])
    assert not (set(groups[fit]) & set(groups[calibration]))
    assert not (set(groups[fit]) & set(groups[test]))
    assert not (set(groups[calibration]) & set(groups[test]))
    report = run_robustness_benchmark(seeds=SEEDS, samples_per_seed=180)
    assert report["seed_count"] == 5
    assert report["benchmark_status"] == "COMPLETED_SYNTHETIC_SOFTWARE_EVALUATION"
    assert len(report["scenario_families"]) == 12
    for seed in report["results_by_seed"]:
        assert seed["group_leakage"] is False
        assert seed["rule_baseline"]["sample_count"] == seed["counts"]["test"]
        shift = seed["v2"]["condition_shift_holdout"]
        assert shift["group_overlap"] is False
        assert shift["test_count"] > 0
        assert set(seed["v1"]["confusion_matrix"]["labels"]) == set(V1_ACTIONS)


def _api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'stage3.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    def override():
        db = sessions()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override
    return engine, sessions, TestClient(app)


def test_v2_schema_and_features_api(tmp_path):
    engine, sessions, client = _api(tmp_path)
    try:
        db = sessions(); topic = ResearchTopic(name="Stage 3 API", description=""); db.add(topic); db.commit(); topic_id = topic.id; db.close()
        schema = client.get("/api/decisions/learned/stage3/schema")
        assert schema.status_code == 200 and schema.json()["schema_version"] == FEATURE_SCHEMA_VERSION_V2
        state = {"schema_version": "scientific-state-v2", "measurements": {"accepted_observation_count": 2}}
        response = client.post("/api/decisions/learned/stage3/features", json={"topic_id": topic_id, "scientific_state": state})
        assert response.status_code == 200, response.text
        assert response.json()["feature_count"] == len(FEATURE_NAMES)
        seeded = client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=41")
        assert seeded.status_code == 200, seeded.text
        dataset = client.post("/api/decisions/learned/stage3/datasets/build", json={"topic_id": topic_id, "mode": "sandbox", "holdout_strategy": "experiment"})
        assert dataset.status_code == 200, dataset.text
        if dataset.json().get("dataset_version_id"):
            trained = client.post("/api/decisions/learned/stage3/retrain", json={"dataset_version_id": dataset.json()["dataset_version_id"], "seed": 41})
            assert trained.status_code == 200, trained.text
            db = sessions(); version = db.get(DecisionDatasetVersion, dataset.json()["dataset_version_id"])
            candidate_id = version.manifest_json["records"][0]["case_id"]; db.close()
            prediction = client.post(f"/api/decisions/learned/stage3/models/{trained.json()['model_id']}/predict", json={"topic_id": topic_id, "case_id": candidate_id})
            assert prediction.status_code == 200, prediction.text
            assert prediction.json()["mode"] == "SHADOW_ONLY"
            assert prediction.json()["workflow_triggered"] is False
    finally:
        app.dependency_overrides.clear(); engine.dispose()
