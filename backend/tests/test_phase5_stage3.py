"""Stage 3 schema, model, benchmark, API and compatibility regressions."""
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import DecisionCase, DecisionDatasetVersion, DecisionModelRun, Experiment, ResearchTopic
from app.main import app
from app.services.decision_head import ACTIONS as V1_ACTIONS, FEATURE_SCHEMA_VERSION as V1_SCHEMA, LearnedDecisionHead, dataset_digest, encode_state
from app.services.phase5_stage3 import SEEDS, generate_scenarios, run_robustness_benchmark, split_groups
from app.api.decisions import _stage3_condition_holdout_groups, _stage3_groups, _stage3_method_holdout_groups
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


def test_method_and_condition_holdouts_assign_whole_experiment_groups():
    rows=[]
    for group,method,signatures in (("exp-a","v1",["common"]),("exp-b","v1",["common","rare"]),
                                     ("exp-c","v2",["common"]),("exp-d","v2",["common"])):
        rows.extend({"case_id":f"{group}-{index}","case_group_id":group,"method_version_id":method,
                     "condition_group":signature} for index,signature in enumerate(signatures))
    grouped=_stage3_groups(rows)
    _,method_eval_groups,error=_stage3_method_holdout_groups(grouped)
    assert error is None and method_eval_groups=={"exp-c","exp-d"}
    method_eval=[x for x in rows if x["case_group_id"] in method_eval_groups]
    method_fit=[x for x in rows if x["case_group_id"] not in method_eval_groups]
    assert {x["case_group_id"] for x in method_eval}.isdisjoint({x["case_group_id"] for x in method_fit})
    condition_eval_groups,_=_stage3_condition_holdout_groups(grouped)
    condition_eval=[x for x in rows if x["case_group_id"] in condition_eval_groups]
    condition_fit=[x for x in rows if x["case_group_id"] not in condition_eval_groups]
    assert {x["case_group_id"] for x in condition_eval}.isdisjoint({x["case_group_id"] for x in condition_fit})
    assert {x["case_group_id"] for x in condition_eval if x["condition_group"]=="rare"}=={"exp-b"}
    mixed={"experiment-x":[{"method_version_id":"v1"},{"method_version_id":"v2"}]}
    _,_,error=_stage3_method_holdout_groups(mixed)
    assert "conflicting method versions" in error


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


def test_frozen_evaluation_group_excludes_new_cases_and_preserves_hash(tmp_path):
    engine, sessions, client = _api(tmp_path)
    try:
        db=sessions(); topic=ResearchTopic(name="Frozen group API",description="");db.add(topic);db.commit();topic_id=topic.id;db.close()
        assert client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=45").status_code==200
        path="/api/decisions/learned/stage3/datasets/build"
        first=client.post(path,json={"topic_id":topic_id,"mode":"sandbox","holdout_strategy":"experiment"})
        assert first.status_code==200,first.text
        db=sessions();v1=db.get(DecisionDatasetVersion,first.json()["dataset_version_id"]);old_manifest=v1.manifest_json
        frozen_ids=list(old_manifest["evaluation_case_ids"]);frozen_hash=old_manifest["evaluation_hash"]
        frozen_group=old_manifest["evaluation_group_ids"][0]
        source=next(row for row in db.query(DecisionCase).filter_by(topic_id=topic_id).all()
                    if row.id==old_manifest["records"][[x["case_id"] for x in old_manifest["records"]].index(frozen_ids[0])]["case_id"])
        for _ in range(3):
            db.add(DecisionCase(topic_id=topic_id,experiment_id=None,snapshot_id=None,feedback_id=None,
                case_group_id=frozen_group,state_json=dict(source.state_json),features_json=dict(source.features_json),
                feature_schema_version=source.feature_schema_version,candidate_actions_json=list(source.candidate_actions_json or []),
                selected_action=source.selected_action,label_source="SYNTHETIC_SANDBOX",review_status="SYNTHETIC_ONLY",
                dataset_version=source.dataset_version))
        # An unrelated group remains eligible for training after the version advances.
        db.commit();v1_id=v1.id;db.close()
        second=client.post(path,json={"topic_id":topic_id,"mode":"sandbox","holdout_strategy":"experiment"})
        assert second.status_code==200,second.text
        db=sessions();v2=db.get(DecisionDatasetVersion,second.json()["dataset_version_id"]);manifest=v2.manifest_json
        new_ids=set(manifest["excluded_case_ids"])
        assert len(new_ids)>=3
        assert set(manifest["excluded_case_reasons"].values())=={"EXCLUDED_FROZEN_EVALUATION_GROUP"}
        assert set(manifest["evaluation_case_ids"])==set(frozen_ids)
        assert manifest["evaluation_hash"]==frozen_hash
        assert set(manifest["fit_group_ids"]).isdisjoint(manifest["evaluation_group_ids"])
        assert set(manifest["calibration_group_ids"]).isdisjoint(manifest["evaluation_group_ids"])
        assert set(manifest["fit_group_ids"]).isdisjoint(manifest["calibration_group_ids"])
        assert not new_ids.intersection(manifest["fit_case_ids"]+manifest["calibration_case_ids"]+manifest["evaluation_case_ids"])
        old_again=db.get(DecisionDatasetVersion,v1_id).manifest_json
        assert old_again==old_manifest
        assert any(x["case_group_id"] not in manifest["evaluation_group_ids"] for x in manifest["records"] if x["case_id"] in manifest["fit_case_ids"])
        db.close()
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_retrain_rejects_tampered_group_partition_before_artifact_creation(tmp_path):
    engine,sessions,client=_api(tmp_path)
    try:
        db=sessions();topic=ResearchTopic(name="Tampered partition",description="");db.add(topic);db.commit();topic_id=topic.id;db.close()
        assert client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=46").status_code==200
        built=client.post("/api/decisions/learned/stage3/datasets/build",json={"topic_id":topic_id,"mode":"sandbox","holdout_strategy":"experiment"})
        assert built.status_code==200,built.text
        db=sessions();version=db.get(DecisionDatasetVersion,built.json()["dataset_version_id"]);manifest=dict(version.manifest_json)
        eval_case=manifest["evaluation_case_ids"][0]
        manifest["fit_case_ids"]=manifest["fit_case_ids"]+[eval_case]
        manifest["fit_group_ids"]=manifest["fit_group_ids"]+[manifest["evaluation_group_ids"][0]]
        version.manifest_json=manifest
        version.dataset_hash=dataset_digest({"topic_id":version.topic_id,"mode":version.mode,
            "feature_schema_version":version.feature_schema_version,"label_mapping_version":version.label_mapping_version,"manifest":manifest})
        db.commit();version_id=version.id;before=db.query(DecisionModelRun).filter_by(topic_id=topic_id).count();db.close()
        response=client.post("/api/decisions/learned/stage3/retrain",json={"dataset_version_id":version_id,"seed":46})
        assert response.status_code==409,response.text
        assert response.json()["detail"]["code"]=="EVALUATION_GROUP_LEAKAGE"
        db=sessions();after=db.query(DecisionModelRun).filter_by(topic_id=topic_id).count();db.close()
        assert after==before
    finally:
        app.dependency_overrides.clear();engine.dispose()
