import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import (DecisionActiveShadowModel, DecisionCase, DecisionDatasetVersion,
    DecisionFeedback, DecisionModelActivationEvent, DecisionModelRun, DecisionSnapshot, Experiment, ResearchTopic)
from app.main import app
from app.services.decision_head import (ACTIONS, DecisionInputError, LearnedDecisionHead, calibration_metrics,
    encode_state, majority_metrics, split_by_group, state_from_experiment, synthetic_cases)


def test_trainable_head_metrics_calibration_serialization_and_abstention():
    cases=synthetic_cases(seed=31,per_action=24)
    x=np.vstack([encode_state(row["state"]) for row in cases]); labels=[row["action"] for row in cases]; groups=[row["case_group_id"] for row in cases]
    train,valid=split_by_group(labels,groups,seed=31)
    fit,cal=split_by_group([labels[i] for i in train],[groups[i] for i in train],seed=32)
    fit_ix=train[fit];cal_ix=train[cal]
    model,loss=LearnedDecisionHead.fit(x[fit_ix],[labels[i] for i in fit_ix],seed=31)
    assert loss[-1]<loss[0]
    assert model.calibrate(x[cal_ix],[labels[i] for i in cal_ix])
    restored=LearnedDecisionHead.from_dict(model.to_dict())
    probs=restored.predict_proba(x[valid])
    assert probs.shape==(len(valid),len(ACTIONS)) and np.allclose(probs.sum(axis=1),1)
    report=calibration_metrics([labels[i] for i in valid],probs)
    assert 0<=report["accuracy"]<=1 and report["brier_score"]>=0 and report["expected_calibration_error_10_bins"]>=0
    ood_state=dict(cases[0]["state"]);ood_state["accepted_observation_count"]=10_000_000
    status,reasons=restored.is_ood(encode_state(ood_state))
    assert status=="POTENTIAL_OOD" and reasons
    with np.testing.assert_raises(DecisionInputError): encode_state({"accepted_observation_count":float("nan")})


def test_group_split_keeps_decision_cases_together():
    labels=["ANALYZE"]*8+["SIMULATE"]*8;groups=[f"e-{i}" for i in range(16)]
    train,valid=split_by_group(labels,groups,seed=3)
    assert {groups[i] for i in train}.isdisjoint({groups[i] for i in valid})


def test_group_split_is_deterministic_and_splits_entire_experiment_groups():
    labels=[];groups=[]
    for action in ("ANALYZE","SIMULATE","REQUEST_REVIEW"):
        for group_number in range(8):
            labels.extend([action,action]);groups.extend([f"{action}-{group_number}"]*2)
    fit,evaluation=split_by_group(labels,groups,seed=45)
    fit_again,evaluation_again=split_by_group(labels,groups,seed=45)
    assert fit.tolist()==fit_again.tolist() and evaluation.tolist()==evaluation_again.tolist()
    assert {groups[i] for i in fit}.isdisjoint({groups[i] for i in evaluation})


def test_majority_baseline_selects_class_only_from_training_labels():
    training=["ANALYZE"]*5+["SIMULATE"]*3
    evaluation=["SIMULATE"]*12+["ANALYZE"]
    result=majority_metrics(training,evaluation)
    assert result["predicted_action"]=="ANALYZE"
    assert result["selected_from"]=="TRAINING_LABELS_ONLY"
    assert result["accuracy"]==1/len(evaluation)
    tied=majority_metrics(["SIMULATE","ANALYZE"],["ANALYZE"])
    assert tied["predicted_action"]=="ANALYZE"  # stable ACTIONS-order tie break


def test_feature_extraction_is_deterministic_and_excludes_final_outcome():
    from types import SimpleNamespace
    method=SimpleNamespace(condition_definitions=[])
    def experiment(status):
        return SimpleNamespace(topic_id=3,id=4,method_version_id=5,method_version=method,steps=[],status=status)
    first=state_from_experiment(experiment("success"),[],[],[],[])
    second=state_from_experiment(experiment("failed"),[],[],[],[])
    assert encode_state(first).tolist()==encode_state(second).tolist()
    assert first["workflow_state"]==second["workflow_state"]==0.0
    assert encode_state(first).tolist()==encode_state(first).tolist()
    ready=state_from_experiment(experiment("running"),[],[],[],[],[
        {"category":"simulation","connected":True,"readiness":"REQUIRES_REVIEW"},
        {"category":"analysis","connected":True,"readiness":"MISSING_INPUT"},
    ])
    assert ready["simulation_tool_available"] is True
    assert ready["analysis_tool_available"] is False


def test_sandbox_training_persistence_and_shadow_compare_do_not_execute(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'phase5-decisions.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False);Base.metadata.create_all(bind=engine)
    def test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=test_db
    try:
        db=sessions();topic=ResearchTopic(name="Phase 5 learned decision topic",description="");db.add(topic);db.commit();topic_id=topic.id;db.close()
        with TestClient(app) as client:
            empty=client.post("/api/decisions/learned/train",json={"topic_id":topic_id,"mode":"research"})
            assert empty.status_code==409 and empty.json()["detail"]["code"]=="INSUFFICIENT_REVIEWED_DECISIONS"
            seed=client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=11")
            assert seed.status_code==200 and seed.json()["created"]==144
            ready=client.get(f"/api/decisions/learned/training-readiness?topic_id={topic_id}").json()
            assert ready["research"]["status"]=="INSUFFICIENT_REVIEWED_DECISIONS"
            assert ready["sandbox"]["case_count"]==144
            trained=client.post("/api/decisions/learned/train",json={"topic_id":topic_id,"mode":"sandbox","seed":11})
            assert trained.status_code==200,trained.text
            model=trained.json();assert model["mode"]=="sandbox" and model["metrics"]["training_loss_decreased"]
            got=client.get(f"/api/decisions/learned/models/{model['model_id']}?topic_id={topic_id}")
            assert got.status_code==200 and got.json()["dataset_hash"]==model["dataset_hash"]
            sandbox_case=client.get(f"/api/decisions/learned/cases?topic_id={topic_id}&mode=sandbox").json()[0]
            compared=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"model_id":model["model_id"],"case_id":sandbox_case["case_id"]})
            assert compared.status_code==200,compared.text
            assert compared.json()["mode"]=="SHADOW_ONLY" and compared.json()["workflow_triggered"] is False
            assert compared.json()["model_mode"]=="SANDBOX" and compared.json()["decision_snapshot"]["snapshot_hash"]
            assert compared.json()["learned"]["ood_status"] in {"IN_DISTRIBUTION","POTENTIAL_OOD","UNSUPPORTED_STATE"}
            db=sessions();experiment=Experiment(code="P5-MODE-GUARD",name="real record",target="test",status="running",demo=False,topic_id=topic_id);db.add(experiment);db.commit();experiment_id=experiment.id
            research_row=DecisionModelRun(topic_id=topic_id,mode="research",status="COMPLETED",dataset_hash="a"*64,model_version=model["model_version"],
                feature_schema_version=model["feature_schema_version"],dataset_version="research-test",model_json=db.get(DecisionModelRun,model["model_id"]).model_json,
                metrics_json={},provenance_json={"dataset_type":"HUMAN_REVIEWED_DECISIONS"});db.add(research_row);db.commit();research_id=research_row.id;db.close()
            sandbox_to_research=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"model_id":model["model_id"],"experiment_id":experiment_id})
            assert sandbox_to_research.status_code==409 and sandbox_to_research.json()["detail"]["code"]=="MODEL_DATASET_MODE_MISMATCH"
            research_to_sandbox=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"model_id":research_id,"case_id":sandbox_case["case_id"]})
            assert research_to_sandbox.status_code==409 and research_to_sandbox.json()["detail"]["code"]=="MODEL_DATASET_MODE_MISMATCH"
            other=client.get(f"/api/decisions/learned/models/{model['model_id']}?topic_id={topic_id+100}")
            assert other.status_code==404
        db=sessions();assert db.query(DecisionCase).filter_by(label_source="SYNTHETIC_SANDBOX").count()==144
        assert all(row.candidate_actions_json==list(ACTIONS) for row in db.query(DecisionCase).filter_by(label_source="SYNTHETIC_SANDBOX").all())
        assert db.query(DecisionModelRun).count()==2;db.close()
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_research_case_recording_excludes_demo_and_keeps_human_source(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'phase5-research-case.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False);Base.metadata.create_all(bind=engine)
    def test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=test_db
    try:
        db=sessions();topic=ResearchTopic(name="Reviewed decision provenance",description="");db.add(topic);db.flush()
        exp=Experiment(code="P5-REAL-1",name="non-demo record",target="decision",status="running",demo=False,topic_id=topic.id);demo=Experiment(code="P5-DEMO-1",name="demo",target="decision",status="running",demo=True,topic_id=topic.id);db.add_all([exp,demo]);db.commit();ids=(topic.id,exp.id,demo.id);db.close()
        with TestClient(app) as client:
            body={"topic_id":ids[0],"experiment_id":ids[1],"selected_action":"REQUEST_REVIEW","label_source":"HUMAN_REVIEWED_DECISION","reviewer":"Researcher A","opinion":"Reviewed context."}
            saved=client.post("/api/decisions/learned/cases",json=body)
            assert saved.status_code==200,saved.text
            assert saved.json()["review_status"]=="ACCEPTED"
            mismatch=client.post("/api/decisions/learned/cases",json={**body,"experiment_id":ids[2]})
            assert mismatch.status_code==422
        db=sessions();row=db.query(DecisionCase).one();assert row.label_source=="HUMAN_REVIEWED_DECISION" and row.provenance_json["reviewer"]=="Researcher A";db.close()
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_stage2_feedback_versioned_retraining_comparison_activation_and_rollback(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'phase5-stage2-learning.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False);Base.metadata.create_all(bind=engine)
    def test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=test_db
    try:
        db=sessions();topic=ResearchTopic(name="Phase 5 Stage 2 lifecycle",description="");db.add(topic);db.commit();topic_id=topic.id;db.close()
        with TestClient(app) as client:
            assert client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=27").json()["created"]==144
            v1_response=client.post("/api/decisions/learned/datasets/build",json={"topic_id":topic_id,"mode":"sandbox"})
            assert v1_response.status_code==200,v1_response.text
            v1=v1_response.json();assert v1["case_count"]==144 and v1["evaluation_case_count"]==36
            model1_response=client.post("/api/decisions/learned/retrain",json={"dataset_version_id":v1["dataset_version_id"],"seed":27})
            assert model1_response.status_code==200,model1_response.text
            model1=model1_response.json()
            model2_response=client.post("/api/decisions/learned/retrain",json={"dataset_version_id":v1["dataset_version_id"],"parent_model_id":model1["model_id"],"seed":27})
            assert model2_response.status_code==200,model2_response.text
            model2=model2_response.json()
            assert model2["provenance"]["parent_model_id"]==model1["model_id"]
            eval_ids=set(model2["provenance"]["evaluation_case_ids"])
            assert eval_ids.isdisjoint(model2["provenance"]["training_case_ids"])
            assert eval_ids.isdisjoint(model2["provenance"]["calibration_case_ids"])
            assert set(model2["provenance"]["training_case_ids"]).isdisjoint(model2["provenance"]["calibration_case_ids"])
            comparison_response=client.post("/api/decisions/learned/models/compare",json={"topic_id":topic_id,"champion_model_id":model1["model_id"],"challenger_model_id":model2["model_id"]})
            assert comparison_response.status_code==200,comparison_response.text
            comparison=comparison_response.json();assert comparison["status"]=="COMPARABLE"
            activate1=client.post("/api/decisions/learned/activate",json={"topic_id":topic_id,"model_id":model1["model_id"],"reviewer":"Reviewer A","reason":"Initial shadow selection"})
            assert activate1.status_code==200,activate1.text
            activate2=client.post("/api/decisions/learned/activate",json={"topic_id":topic_id,"model_id":model2["model_id"],"comparison_id":comparison["comparison_id"],"reviewer":"Reviewer A","reason":"Same-set comparison"})
            assert activate2.status_code==200,activate2.text
            assert activate2.json()["previous_model_id"]==model1["model_id"] and activate2.json()["workflow_triggered"] is False
            blocked=client.post("/api/decisions/learned/activate",json={"topic_id":topic_id,"model_id":model1["model_id"],"reviewer":"Reviewer A"})
            assert blocked.status_code==409 and blocked.json()["detail"]["code"]=="MODEL_COMPARISON_REQUIRED"
            rolled=client.post("/api/decisions/learned/rollback",json={"topic_id":topic_id,"mode":"sandbox","reviewer":"Reviewer A","reason":"Restore previous shadow"})
            assert rolled.status_code==200 and rolled.json()["active_model_id"]==model1["model_id"]
            case=client.get(f"/api/decisions/learned/cases?topic_id={topic_id}&mode=sandbox").json()[0]
            result=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"model_id":model2["model_id"],"case_id":case["case_id"]})
            assert result.status_code==200 and result.json()["workflow_triggered"] is False
            snapshot=result.json()["decision_snapshot"]
            assert snapshot["model_id"]==model2["model_id"] and snapshot["snapshot_hash"]
            db=sessions();original_case=db.get(DecisionCase,case["case_id"]);original_case.state_json={"accepted_observation_count":999999};db.commit();db.close()
            saved_snapshot=client.get(f"/api/decisions/learned/snapshots/{snapshot['snapshot_id']}?topic_id={topic_id}").json()
            assert saved_snapshot["snapshot_hash"]==snapshot["snapshot_hash"]
            assert saved_snapshot["state"]["accepted_observation_count"]!=999999
            correction=next(action for action in ACTIONS if action!=snapshot["suggested_action"])
            feedback_response=client.post("/api/decisions/learned/feedback",json={"snapshot_id":snapshot["snapshot_id"],"model_id":model2["model_id"],"feedback_type":"CORRECT","final_reviewed_action":correction,"reviewer":"Researcher A","review_reason":"Corrected after review"})
            assert feedback_response.status_code==200,feedback_response.text
            assert feedback_response.json()["label_eligible"] is True
            v2_response=client.post("/api/decisions/learned/datasets/build",json={"topic_id":topic_id,"mode":"sandbox"})
            assert v2_response.status_code==200,v2_response.text
            v2=v2_response.json();assert v2["dataset_version_id"]!=v1["dataset_version_id"] and v2["dataset_hash"]!=v1["dataset_hash"]
            assert v2["case_count"]==145 and v2["evaluation_hash"]==v1["evaluation_hash"]
            challenger_response=client.post("/api/decisions/learned/retrain",json={"dataset_version_id":v2["dataset_version_id"],"parent_model_id":model2["model_id"],"seed":27})
            assert challenger_response.status_code==200,challenger_response.text
            challenger=challenger_response.json()
            assert challenger["dataset_hash"]==v2["dataset_hash"]
            assert challenger["provenance"]["evaluation_hash"]==v1["evaluation_hash"]
            unsure=client.post("/api/decisions/learned/feedback",json={"snapshot_id":snapshot["snapshot_id"],"model_id":model2["model_id"],"feedback_type":"UNSURE","reviewer":"Researcher A"})
            assert unsure.status_code==200 and unsure.json()["label_eligible"] is False
            assert unsure.json()["revision"]==2 and unsure.json()["supersedes_feedback_id"]==feedback_response.json()["feedback_id"]
            feedback_history=client.get(f"/api/decisions/learned/feedback?topic_id={topic_id}").json()
            assert [item["revision"] for item in feedback_history[:2]]==[2,1]
            # A later UNSURE revision excludes the earlier correction from newly built data,
            # while the already-created V2 manifest remains unchanged.
            rebuilt=client.post("/api/decisions/learned/datasets/build",json={"topic_id":topic_id,"mode":"sandbox"})
            assert rebuilt.status_code==200 and rebuilt.json()["dataset_hash"]==v1["dataset_hash"]
        db=sessions()
        assert db.query(DecisionDatasetVersion).count()==2
        assert db.query(DecisionFeedback).count()==2
        assert db.query(DecisionSnapshot).count()==1
        assert db.query(DecisionActiveShadowModel).one().model_run_id==model1["model_id"]
        assert [event.action for event in db.query(DecisionModelActivationEvent).order_by(DecisionModelActivationEvent.id).all()]==["ACTIVATE","ACTIVATE","ROLLBACK"]
        db.close()
    finally:
        app.dependency_overrides.clear();engine.dispose()
