import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import CampaignObservation, Experiment, ProcessStep, ProcessVariable, ResearchTopic, ScientificObservation
from app.main import app
from app.services.optimization.gpbo import branin
from app import worker


def test_phase7_sandbox_campaign_completes_reviewed_loop_and_executes_worker(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'phase7.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def get_test_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(worker, "SessionLocal", sessions)
    app.dependency_overrides[get_db] = get_test_db
    try:
        db = sessions()
        topic = ResearchTopic(name="Phase 7 Sandbox", description="")
        db.add(topic); db.flush()
        experiment = Experiment(code="P7-001", name="Worker fixture", target="record validation", status="planned",
            demo=False, topic_id=topic.id)
        db.add(experiment); db.flush()
        step = ProcessStep(experiment_id=experiment.id, name="Mixing", order_index=0)
        db.add(step); db.flush()
        db.add(ProcessVariable(process_step_id=step.id, name="stir_speed", value="500", unit="rpm"))
        db.commit(); topic_id, experiment_id = topic.id, experiment.id; db.close()

        client = TestClient(app)
        created = client.post("/api/campaigns", json={
            "topic_id": topic_id, "experiment_id": experiment_id, "mode": "sandbox",
            "goal": "Minimize the benchmark objective after validating recorded conditions",
            "target_property": "branin", "direction": "minimize",
            "variables": [{"id": "x1", "name": "x1", "unit": "dimensionless", "minimum": -5, "maximum": 10},
                          {"id": "x2", "name": "x2", "unit": "dimensionless", "minimum": 0, "maximum": 15}],
            "fixed_conditions": {"benchmark": "Branin"}, "max_iterations": 3, "idempotency_key": "phase7-create-1"})
        assert created.status_code == 201, created.text
        campaign = created.json(); campaign_id = campaign["id"]
        assert campaign["mode"] == "SANDBOX" and len(campaign["observations"]) == 6

        queued = client.post(f"/api/campaigns/{campaign_id}/advance?topic_id={topic_id}", json={"idempotency_key": "phase7-advance-1"})
        assert queued.status_code == 200 and queued.json()["state"] == "RUNNING_ANALYSIS"
        assert worker.run_once("phase7-test-worker") is True
        optimized = client.post(f"/api/campaigns/{campaign_id}/advance?topic_id={topic_id}", json={"idempotency_key": "phase7-advance-2"})
        assert optimized.status_code == 200, optimized.text
        campaign = optimized.json()
        assert campaign["state"] == "WAITING_FOR_REVIEW", campaign
        assert campaign["decision"]["workflow_status"] == "COMPLETED"
        assert campaign["decision"]["validation"]["valid"] is True
        assert campaign["selected_action"] == "OPTIMIZE"
        assert campaign["candidate"]["approval_status"] == "PENDING_RESEARCHER_REVIEW"
        assert campaign["candidate"]["prediction_is_not_measurement"] is True

        approved = client.post(f"/api/campaigns/{campaign_id}/review?topic_id={topic_id}", json={"decision": "APPROVE", "reviewer": "researcher", "idempotency_key": "phase7-review-1"})
        assert approved.status_code == 200 and approved.json()["state"] == "WAITING_FOR_RESULT"
        candidate = approved.json()["candidate"]["values"]
        measured = float(branin(np.asarray([candidate]))[0])
        submitted = client.post(f"/api/campaigns/{campaign_id}/observations?topic_id={topic_id}", json={
            "conditions": candidate, "target_value": measured, "target_unit": "objective",
            "source_type": "SANDBOX_SYNTHETIC", "idempotency_key": "phase7-observation-1"})
        assert submitted.status_code == 200, submitted.text
        obs = submitted.json()["observation"]
        assert obs["review_status"] == "PENDING"
        db = sessions()
        assert db.query(CampaignObservation).filter_by(campaign_id=campaign_id, review_status="ACCEPTED").count() == 6
        assert db.query(ScientificObservation).count() == 0
        db.close()
        reviewed = client.post(f"/api/campaigns/{campaign_id}/observations/{obs['id']}/review?topic_id={topic_id}", json={
            "review_status": "ACCEPTED", "reviewer": "researcher", "idempotency_key": "phase7-observation-review-1"})
        assert reviewed.status_code == 200 and reviewed.json()["state"] == "OPTIMIZING"
        next_candidate = client.post(f"/api/campaigns/{campaign_id}/advance?topic_id={topic_id}", json={"idempotency_key": "phase7-advance-3"})
        assert next_candidate.status_code == 200, next_candidate.text
        assert next_candidate.json()["state"] == "WAITING_FOR_REVIEW"
        assert next_candidate.json()["iteration_count"] == 2
        assert len(next_candidate.json()["observations"]) == 7
        repeated = client.post(f"/api/campaigns/{campaign_id}/advance?topic_id={topic_id}", json={"idempotency_key": "phase7-advance-3"})
        assert repeated.json()["iteration_count"] == 2
        assert client.get(f"/api/campaigns?topic_id={topic_id}").status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
