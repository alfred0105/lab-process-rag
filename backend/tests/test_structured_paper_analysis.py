from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.database import Base, get_db
from app.db.models import Paper, EvidenceChunk, PaperStructuredAnalysis
from app.main import app
from app.services.paper_analysis.structured import validate_analysis


def test_structured_analysis_rejects_nonexistent_or_foreign_evidence_ids():
    raw = {"research_objectives": [{"description": "Aim", "evidence_ids": [900]}], "materials": [],
           "experimental_methods": [], "process_conditions": [], "characterization_methods": [], "key_findings": [],
           "reported_limitations": [], "analysis_limitations": [], "schema_version": "1"}
    try:
        validate_analysis(raw, {10, 11})
        assert False, "invalid source should be rejected"
    except ValueError as exc:
        assert "outside this paper" in str(exc)


def test_structured_paper_analysis_persists_scopes_and_reuses_result(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'structured.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def get_test_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma:test")

    class FakeProvider:
        calls = 0
        def analyze_paper_structure(self, title, excerpts):
            self.calls += 1
            evidence_id = excerpts[0]["evidence_id"]
            return {"schema_version": "1", "research_objectives": [{"description": "Study process effects", "evidence_ids": [evidence_id]}],
                    "materials": [], "experimental_methods": [], "process_conditions": [], "characterization_methods": [],
                    "key_findings": [], "reported_limitations": [], "analysis_limitations": []}

    provider = FakeProvider()
    monkeypatch.setattr("app.api.routes.configured_provider", lambda settings: provider)
    monkeypatch.setattr("app.api.routes.retrieval.search", lambda db, query, limit=10, topic_id=None: [
        {"evidence_id": chunk.id, "paper_id": chunk.paper_id} for chunk in db.query(EvidenceChunk).filter_by(paper_id=1).all()
    ])
    try:
        with sessions() as db:
            from app.db.models import ResearchTopic
            topic = ResearchTopic(name="structured test", description="")
            db.add(topic); db.flush()
            paper = Paper(title="Evidence paper", filename="evidence.pdf", topic_id=topic.id)
            db.add(paper); db.flush()
            db.add_all([EvidenceChunk(paper_id=paper.id, page=1, section="Abstract", text="Study process effects.", chunk_index=0),
                        EvidenceChunk(paper_id=paper.id, page=4, section="Results", text="Reported result from source.", chunk_index=1)])
            db.commit(); paper_id, topic_id = paper.id, topic.id
        with TestClient(app) as client:
            url = f"/api/papers/{paper_id}/structured-analysis?topic_id={topic_id}"
            assert client.get(url).json()["status"] == "not_generated"
            created = client.post(url, json={})
            assert created.status_code == 200, created.text
            body = created.json()
            assert body["analysis"]["research_objectives"][0]["description"] == "Study process effects"
            assert body["sources"][0]["page"] in {1, 4}
            assert client.get(url).json()["analysis"] == body["analysis"]
            assert client.post(url, json={}).json()["analysis"] == body["analysis"]
            assert provider.calls == 1
            assert client.get(f"/api/papers/{paper_id}/structured-analysis?topic_id=999").status_code == 404
        with sessions() as db:
            assert db.query(PaperStructuredAnalysis).count() == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_structured_analysis_returns_error_when_gemma_is_disabled(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'disabled.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    def get_test_db():
        db = sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setenv("AI_PROVIDER", "disabled")
    try:
        with sessions() as db:
            from app.db.models import ResearchTopic
            topic=ResearchTopic(name="disabled structured test",description=""); db.add(topic); db.flush()
            paper=Paper(title="No model",filename="no-model.pdf",topic_id=topic.id); db.add(paper); db.commit(); paper_id,topic_id=paper.id,topic.id
        with TestClient(app) as client:
            response=client.post(f"/api/papers/{paper_id}/structured-analysis?topic_id={topic_id}",json={})
            assert response.status_code==503
            assert "Gemma is unavailable" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear(); engine.dispose()
