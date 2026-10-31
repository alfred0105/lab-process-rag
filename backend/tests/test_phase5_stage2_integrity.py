"""Final integrity regressions for immutable decision and Research source contracts."""
from datetime import datetime
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import (
    DecisionCase,
    DecisionDatasetVersion,
    DecisionModelRun,
    DecisionSnapshot,
    Experiment,
    ResearchTopic,
)
from app.main import app
from app.services.decision_head import (
    ACTIONS,
    DATASET_VERSION,
    FEATURE_SCHEMA_VERSION,
    LearnedDecisionHead,
    dataset_digest,
    encode_state,
    synthetic_cases,
)


def _client_db(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'phase5-integrity.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    Base.metadata.create_all(bind=engine)
    def test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=test_db
    return engine,sessions,TestClient(app)


def _topic_and_experiment(sessions, *, demo=False, name="Integrity experiment"):
    db=sessions()
    topic=ResearchTopic(name=f"Integrity topic {name}",description="")
    db.add(topic);db.flush()
    experiment=Experiment(code=f"INT-{topic.id}-{name[:8]}",name=name,target="decision integrity",
        status="running",demo=demo,topic_id=topic.id)
    db.add(experiment);db.commit();ids=(topic.id,experiment.id);db.close()
    return ids


def _experiment_in_topic(sessions, topic_id, *, name):
    db=sessions()
    count=db.query(Experiment).filter_by(topic_id=topic_id).count()
    row=Experiment(code=f"INT-{topic_id}-{count}-{name[:8]}",name=name,target="decision integrity",
        status="running",demo=False,topic_id=topic_id)
    db.add(row);db.commit();experiment_id=row.id;db.close()
    return experiment_id


def _bias_model(sessions, topic_id, *, action="OPTIMIZE", uniform=False):
    examples=synthetic_cases(seed=71,per_action=24)
    x=np.vstack([encode_state(item["state"]) for item in examples])
    model,_=LearnedDecisionHead.fit(x,[item["action"] for item in examples],seed=71)
    payload=model.to_dict()
    payload["output_weight"]=(np.zeros_like(model.output_weight)).tolist()
    payload["output_bias"]=(np.zeros_like(model.output_bias) if uniform else
        np.asarray([12.0 if label==action else 0.0 for label in ACTIONS])).tolist()
    db=sessions()
    row=DecisionModelRun(topic_id=topic_id,mode="SANDBOX",status="COMPLETED",dataset_hash="a"*64,
        model_version="integrity-test-v1",feature_schema_version=FEATURE_SCHEMA_VERSION,
        dataset_version=DATASET_VERSION,model_json=payload,metrics_json={},
        provenance_json={"dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE"})
    db.add(row);db.commit();model_id=row.id;db.close()
    return model_id


def _sandbox_case(sessions, topic_id, state, action="OPTIMIZE", group="integrity-case"):
    db=sessions()
    row=DecisionCase(topic_id=topic_id,case_group_id=group,state_json=state,
        features_json={"vector":encode_state(state).tolist(),"feature_names":[]},
        feature_schema_version=FEATURE_SCHEMA_VERSION,candidate_actions_json=list(ACTIONS),
        selected_action=action,label_source="SYNTHETIC_SANDBOX",review_status="SYNTHETIC_ONLY",
        provenance_json={"dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE"},dataset_version=DATASET_VERSION)
    db.add(row);db.commit();case_id=row.id;db.close()
    return case_id


def test_final_safety_recommendation_is_the_action_snapshotted_and_accepted(tmp_path):
    engine,sessions,client=_client_db(tmp_path)
    try:
        topic_id,_=_topic_and_experiment(sessions)
        model_id=_bias_model(sessions,topic_id)
        seed=client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=72")
        assert seed.status_code==200
        source=synthetic_cases(seed=71,per_action=24)[0]["state"]

        scenarios=[
            ({"accepted_observation_count":123456789},"ABSTAIN","OPTIMIZE"),
            ({**source,"missing_required_information_count":1},"REQUEST_INFORMATION","OPTIMIZE"),
            ({**source,"missing_required_information_count":0,"pending_review_count":1},"REQUEST_REVIEW","OPTIMIZE"),
        ]
        for number,(state,expected_final,expected_raw) in enumerate(scenarios):
            case_id=_sandbox_case(sessions,topic_id,state,group=f"integrity-scenario-{number}")
            response=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"model_id":model_id,"case_id":case_id})
            assert response.status_code==200,response.text
            result=response.json();snapshot=result["decision_snapshot"]
            assert result["learned"]["action"]==expected_final
            assert result["learned"]["raw_predicted_action"]==expected_raw
            assert snapshot["suggested_action"]==snapshot["final_suggested_action"]==expected_final
            assert snapshot["raw_predicted_action"]==expected_raw
            assert snapshot["safety_override"] is True
            assert snapshot["snapshot_hash"]

            if number==0:
                accepted=client.post("/api/decisions/learned/feedback",json={
                    "snapshot_id":snapshot["snapshot_id"],"model_id":model_id,
                    "feedback_type":"ACCEPT","reviewer":"Researcher A"})
                assert accepted.status_code==200,accepted.text
                assert accepted.json()["suggested_action"]=="ABSTAIN"
                assert accepted.json()["final_reviewed_action"]=="ABSTAIN"
                db=sessions()
                learned_case=db.query(DecisionCase).filter_by(feedback_id=accepted.json()["feedback_id"]).one()
                assert learned_case.selected_action=="ABSTAIN"
                stored=db.get(DecisionSnapshot,snapshot["snapshot_id"])
                assert stored.raw_predicted_action=="OPTIMIZE" and stored.suggested_action=="ABSTAIN"
                assert stored.confidence is not None and stored.calibration_status=="UNCALIBRATED"
                assert stored.ood_status=="UNSUPPORTED_STATE" and stored.ood_reasons_json
                assert stored.safety_override_reason
                db.close()
            elif number==1:
                correction=client.post("/api/decisions/learned/feedback",json={
                    "snapshot_id":snapshot["snapshot_id"],"model_id":model_id,
                    "feedback_type":"CORRECT","final_reviewed_action":"ANALYZE",
                    "reviewer":"Researcher A","review_reason":"Reviewed final request"})
                assert correction.status_code==200,correction.text
                assert correction.json()["suggested_action"]=="REQUEST_INFORMATION"
                assert correction.json()["final_reviewed_action"]=="ANALYZE"
                db=sessions();corrected=db.query(DecisionCase).filter_by(feedback_id=correction.json()["feedback_id"]).one()
                assert corrected.selected_action=="ANALYZE";db.close()
            elif number==2:
                rejected=client.post("/api/decisions/learned/feedback",json={
                    "snapshot_id":snapshot["snapshot_id"],"model_id":model_id,
                    "feedback_type":"REJECT","reviewer":"Researcher A"})
                assert rejected.status_code==200 and rejected.json()["label_eligible"] is False
                assert rejected.json()["final_reviewed_action"] is None

        low_conf_model=_bias_model(sessions,topic_id,uniform=True)
        low_conf_state={**source,"missing_required_information_count":0,"pending_review_count":0}
        case_id=_sandbox_case(sessions,topic_id,low_conf_state,group="integrity-low-confidence")
        response=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"model_id":low_conf_model,"case_id":case_id})
        assert response.status_code==200,response.text
        snapshot=response.json()["decision_snapshot"]
        assert response.json()["learned"]["raw_predicted_action"]=="REQUEST_INFORMATION"
        assert response.json()["learned"]["action"]==snapshot["suggested_action"]=="ABSTAIN"
        assert snapshot["abstention_reason"] and snapshot["safety_override"] is True
        unsure=client.post("/api/decisions/learned/feedback",json={
            "snapshot_id":snapshot["snapshot_id"],"model_id":low_conf_model,
            "feedback_type":"UNSURE","reviewer":"Researcher A"})
        assert unsure.status_code==200 and unsure.json()["label_eligible"] is False
        assert unsure.json()["final_reviewed_action"] is None
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_research_cases_require_verified_non_demo_experiment_and_expert_source_contract(tmp_path):
    engine,sessions,client=_client_db(tmp_path)
    try:
        topic_id,experiment_id=_topic_and_experiment(sessions,name="valid-source")
        other_topic_id,other_experiment_id=_topic_and_experiment(sessions,name="other-source")
        _,demo_id=_topic_and_experiment(sessions,demo=True,name="demo-source")
        base={"topic_id":topic_id,"selected_action":"REQUEST_REVIEW","label_source":"HUMAN_REVIEWED_DECISION","reviewer":"Researcher A"}
        missing=client.post("/api/decisions/learned/cases",json=base)
        assert missing.status_code==422 and missing.json()["detail"]["code"]=="RESEARCH_EXPERIMENT_REQUIRED"
        nonexistent=client.post("/api/decisions/learned/cases",json={**base,"experiment_id":999999})
        assert nonexistent.status_code==422 and nonexistent.json()["detail"]["code"]=="RESEARCH_EXPERIMENT_REQUIRED"
        cross_topic=client.post("/api/decisions/learned/cases",json={**base,"experiment_id":other_experiment_id})
        assert cross_topic.status_code==422 and cross_topic.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        demo=client.post("/api/decisions/learned/cases",json={**base,"experiment_id":demo_id})
        assert demo.status_code==422 and demo.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        expert=client.post("/api/decisions/learned/cases",json={**base,"experiment_id":experiment_id,"label_source":"EXPERT_ANNOTATION"})
        assert expert.status_code==422 and expert.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        saved=client.post("/api/decisions/learned/cases",json={**base,"experiment_id":experiment_id})
        assert saved.status_code==200,saved.text
        snapshot=client.get(f"/api/decisions/learned/snapshots/{saved.json()['snapshot_id']}?topic_id={topic_id}").json()
        assert snapshot["decision_contract_version"]=="decision-snapshot-v2"
        assert snapshot["raw_predicted_action"] is None
        assert snapshot["suggested_action"]=="REQUEST_REVIEW"
        db=sessions();case=db.get(DecisionCase,saved.json()["case_id"])
        assert case.provenance_json["research_source_policy"]=="verified-experiment-snapshot-v2"
        snapshot_row=db.get(DecisionSnapshot,snapshot["snapshot_id"])
        snapshot_row.confidence=0.123  # Simulate a changed immutable field without updating its stored hash.
        db.commit();db.close()
        blocked_dataset=client.post("/api/decisions/learned/datasets/build",json={"topic_id":topic_id,"mode":"research"})
        assert blocked_dataset.status_code==409
        assert blocked_dataset.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        assert other_topic_id!=topic_id
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_research_dataset_train_retrain_and_activation_enforce_one_source_policy(tmp_path):
    engine,sessions,client=_client_db(tmp_path)
    try:
        db=sessions();topic=ResearchTopic(name="Research source lifecycle",description="");db.add(topic);db.commit();topic_id=topic.id;db.close()
        for action in ACTIONS:
            for replicate in range(5):
                experiment_id=_experiment_in_topic(sessions,topic_id,name=f"{action[:4]}-{replicate}")
                saved=client.post("/api/decisions/learned/cases",json={
                    "topic_id":topic_id,"experiment_id":experiment_id,"selected_action":action,
                    "label_source":"HUMAN_REVIEWED_DECISION","reviewer":"Researcher A"})
                assert saved.status_code==200,saved.text
        dataset_response=client.post("/api/decisions/learned/datasets/build",json={"topic_id":topic_id,"mode":"research"})
        assert dataset_response.status_code==200,dataset_response.text
        dataset=dataset_response.json();assert dataset["case_count"]==30
        retrained=client.post("/api/decisions/learned/retrain",json={"dataset_version_id":dataset["dataset_version_id"],"seed":17})
        assert retrained.status_code==200,retrained.text
        assert retrained.json()["provenance"]["research_source_policy"]=="verified-experiment-snapshot-v2"
        activated=client.post("/api/decisions/learned/activate",json={"topic_id":topic_id,
            "model_id":retrained.json()["model_id"],"reviewer":"Reviewer A","reason":"Verified source contract"})
        assert activated.status_code==200,activated.text
        assert activated.json()["active_model_id"]==retrained.json()["model_id"]

        db=sessions()
        broken=db.get(DecisionDatasetVersion,dataset["dataset_version_id"])
        tampered_manifest=dict(broken.manifest_json);tampered_manifest.pop("research_source_policy")
        broken.manifest_json=tampered_manifest;db.commit();db.close()
        blocked_retrain=client.post("/api/decisions/learned/retrain",json={"dataset_version_id":dataset["dataset_version_id"],"seed":18})
        assert blocked_retrain.status_code==409 and blocked_retrain.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_legacy_research_case_dataset_and_model_are_not_reinterpreted(tmp_path):
    engine,sessions,client=_client_db(tmp_path)
    try:
        topic_id,experiment_id=_topic_and_experiment(sessions,name="legacy-source")
        db=sessions()
        exp=db.get(Experiment,experiment_id)
        legacy_snapshot=DecisionSnapshot(id="legacy-integrity-snapshot",topic_id=topic_id,experiment_id=experiment_id,
            method_version_id=None,model_run_id=None,mode="RESEARCH",decision_timestamp=datetime(2026,1,1),
            snapshot_timestamp=datetime(2026,1,1),data_availability_timestamp=datetime(2026,1,1),state_json={"topic_id":topic_id,"experiment_id":experiment_id},
            feature_vector_json=encode_state({}).tolist(),suggested_action="OPTIMIZE",probabilities_json={},ood_status="UNKNOWN",
            feature_schema_version=FEATURE_SCHEMA_VERSION,source_observation_ids_json=[],source_analysis_ids_json=[],
            source_simulation_ids_json=[],source_optimization_model_ids_json=[],provenance_json={},snapshot_hash="b"*64)
        db.add(legacy_snapshot);db.flush();legacy_snapshot_id=legacy_snapshot.id
        legacy_case=DecisionCase(topic_id=topic_id,experiment_id=experiment_id,snapshot_id=legacy_snapshot.id,
            case_group_id=f"experiment-{experiment_id}",state_json=legacy_snapshot.state_json,
            features_json={"vector":legacy_snapshot.feature_vector_json},feature_schema_version=FEATURE_SCHEMA_VERSION,
            candidate_actions_json=list(ACTIONS),selected_action="OPTIMIZE",label_source="HUMAN_REVIEWED_DECISION",
            reviewer="Old reviewer",review_status="ACCEPTED",provenance_json={"snapshot_id":legacy_snapshot.id},dataset_version=DATASET_VERSION)
        db.add(legacy_case);db.flush()
        manifest={"records":[{"case_id":legacy_case.id,"snapshot_id":legacy_snapshot.id,"case_group_id":f"experiment-{experiment_id}","action":"OPTIMIZE"}],
            "evaluation_case_ids":[legacy_case.id],"evaluation_group_ids":[f"experiment-{experiment_id}"],"evaluation_hash":"c"*64}
        legacy_dataset=DecisionDatasetVersion(topic_id=topic_id,mode="RESEARCH",dataset_version="research-legacy",
            dataset_hash="d"*64,feature_schema_version=FEATURE_SCHEMA_VERSION,label_mapping_version="decision-actions-v1",
            case_count=1,group_count=1,action_distribution_json={},missingness_json={},source_summary_json={},manifest_json=manifest)
        db.add(legacy_dataset)
        model_json=LearnedDecisionHead.from_dict(_bias_model_payload()).to_dict()
        legacy_model=DecisionModelRun(topic_id=topic_id,mode="RESEARCH",status="EVALUATED",dataset_hash="e"*64,
            model_version="legacy-research-model",feature_schema_version=FEATURE_SCHEMA_VERSION,dataset_version="legacy",
            model_json=model_json,metrics_json={},provenance_json={"evaluation_hash":"f"*64})
        db.add(legacy_model);db.commit();legacy_dataset_id=legacy_dataset.id;legacy_model_id=legacy_model.id;db.close()

        built=client.post("/api/decisions/learned/datasets/build",json={"topic_id":topic_id,"mode":"research"})
        assert built.status_code==409 and built.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        trained=client.post("/api/decisions/learned/train",json={"topic_id":topic_id,"mode":"research"})
        assert trained.status_code==409 and trained.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        retrained=client.post("/api/decisions/learned/retrain",json={"dataset_version_id":legacy_dataset_id})
        assert retrained.status_code==409 and retrained.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        activation=client.post("/api/decisions/learned/activate",json={"topic_id":topic_id,"model_id":legacy_model_id,"reviewer":"Reviewer A"})
        assert activation.status_code==409 and activation.json()["detail"]["code"]=="UNVERIFIED_RESEARCH_PROVENANCE"
        db=sessions();preserved=db.get(DecisionSnapshot,legacy_snapshot_id)
        assert preserved.snapshot_hash=="b"*64 and preserved.raw_predicted_action is None and preserved.decision_contract_version is None
        db.close()
    finally:
        app.dependency_overrides.clear();engine.dispose()


def _bias_model_payload():
    examples=synthetic_cases(seed=19,per_action=24)
    x=np.vstack([encode_state(item["state"]) for item in examples])
    model,_=LearnedDecisionHead.fit(x,[item["action"] for item in examples],seed=19)
    return model.to_dict()
