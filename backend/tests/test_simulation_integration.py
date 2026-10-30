from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.db.database import Base, get_db
from app.db.models import Experiment, ResearchTopic, SimulationRun
from app.main import app


def _client_for(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'simulation-integration.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def get_test_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_test_db
    return TestClient(app), sessions


def _seed_simulation(sessions, *, demo=False, status="completed"):
    db = sessions()
    topic = ResearchTopic(name="Simulation integration test", description="Isolated API test")
    db.add(topic)
    db.flush()
    experiment = Experiment(code="EXP-SIM-TEST", name="CFD source run", target="Stirred liquid", status="reference", demo=demo, topic_id=topic.id)
    db.add(experiment)
    db.flush()
    run = SimulationRun(experiment_id=experiment.id, model_id="test-model", status=status,
                        input_json={"rpm": 100}, result_json={"power_number": 2.1}, log_text="End")
    db.add(run)
    db.commit()
    output = (topic.id, experiment.id, run.id)
    db.close()
    return output


def test_integrated_analysis_includes_completed_simulation_as_separate_output(tmp_path, monkeypatch):
    client, sessions = _client_for(tmp_path)
    topic_id, experiment_id, simulation_id = _seed_simulation(sessions)

    class FakeProvider:
        def explain_integrated(self, task, evidence, allow_general_knowledge, record_text):
            assert "Integrated numerical simulations" in task
            assert f'"simulation_run_id": {simulation_id}' in task
            return {
                "claims": [{"claim": "The model output reports a power number.", "status": "SIMULATION_OUTPUT",
                            "simulation_run_refs": [simulation_id], "evidence_ids": [], "experiment_refs": [], "analysis_run_refs": []}],
                "evidence_gaps": [],
                "decision_brief": {"summary": "Simulation context only.", "options": [], "decision_note": "No measured validation was supplied."},
            }

    monkeypatch.setattr(routes, "configured_provider", lambda settings: FakeProvider())
    monkeypatch.setattr(routes.retrieval, "search", lambda *args, **kwargs: [])
    try:
        with client:
            response = client.post("/api/analysis/integrated", json={
                "simulation_run_ids": [simulation_id], "experiment_ids": [experiment_id],
                "goal": "Explain the simulated flow output and keep it separate from measurements.",
            })
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["simulation_run_ids"] == [simulation_id]
        assert report["research_trace"]["simulation_runs_integrated"] == 1
        assert report["simulations"][0]["computed_outputs"]["power_number"] == 2.1
        assert report["claims"][0]["status"] == "SIMULATION_OUTPUT"
        assert report["claims"][0]["simulation_run_refs"] == [simulation_id]
    finally:
        app.dependency_overrides.clear()


def test_integrated_analysis_rejects_simulation_from_demo_experiment(tmp_path):
    client, sessions = _client_for(tmp_path)
    _, _, simulation_id = _seed_simulation(sessions, demo=True)
    try:
        with client:
            response = client.post("/api/analysis/integrated", json={
                "simulation_run_ids": [simulation_id], "goal": "Try to integrate a demo simulation output."
            })
        assert response.status_code == 422
        assert "non-demo" in response.text
    finally:
        app.dependency_overrides.clear()


def test_integrated_analysis_rejects_unfinished_simulation(tmp_path):
    client, sessions = _client_for(tmp_path)
    _, experiment_id, simulation_id = _seed_simulation(sessions, status="running")
    try:
        with client:
            response = client.post("/api/analysis/integrated", json={
                "simulation_run_ids": [simulation_id], "experiment_ids": [experiment_id],
                "goal": "Explain only completed model results."
            })
        assert response.status_code == 422
        assert "completed" in response.text
    finally:
        app.dependency_overrides.clear()
