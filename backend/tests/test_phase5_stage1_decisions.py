import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import DecisionCase, DecisionModelRun, Experiment, ResearchTopic
from app.main import app
from app.services.decision_head import (ACTIONS, DecisionInputError, LearnedDecisionHead, calibration_metrics,
    encode_state, split_by_group, state_from_experiment, synthetic_cases)


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
            state={"topic_id":topic_id,"accepted_observation_count":5,"measurement_completeness":1.0,"available_analysis_count":1,
                "available_simulation_count":0,"gp_model_ready":False,"gp_mean_uncertainty":0.0,"optimization_ready":False,
                "pending_review_count":0,"available_tool_count":1,"missing_required_information_count":0,"provenance_valid":True,
                "validation_status":1.0,"workflow_state":0.0}
            compared=client.post("/api/decisions/learned/compare",json={"topic_id":topic_id,"scientific_state":state})
            assert compared.status_code==200,compared.text
            assert compared.json()["mode"]=="SHADOW_ONLY" and compared.json()["workflow_triggered"] is False
            assert compared.json()["learned"]["ood_status"] in {"IN_DISTRIBUTION","POTENTIAL_OOD","UNSUPPORTED_STATE"}
            other=client.get(f"/api/decisions/learned/models/{model['model_id']}?topic_id={topic_id+100}")
            assert other.status_code==404
        db=sessions();assert db.query(DecisionCase).filter_by(label_source="SYNTHETIC_SANDBOX").count()==144
        assert all(row.candidate_actions_json==list(ACTIONS) for row in db.query(DecisionCase).filter_by(label_source="SYNTHETIC_SANDBOX").all())
        assert db.query(DecisionModelRun).count()==1;db.close()
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
