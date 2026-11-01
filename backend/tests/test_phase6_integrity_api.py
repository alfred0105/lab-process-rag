import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import EvidenceChunk, Experiment, Paper, ResearchTopic
from app.api.hybrid_decisions import HybridInferIn, infer, resolve_topic_evidence


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    topics = [ResearchTopic(name="topic-a"), ResearchTopic(name="topic-b")]
    session.add_all(topics)
    session.flush()
    papers = [Paper(title="Paper A", filename="a.pdf", topic_id=topics[0].id),
              Paper(title="Paper B", filename="b.pdf", topic_id=topics[1].id)]
    session.add_all(papers)
    session.flush()
    chunks = [EvidenceChunk(paper_id=papers[0].id, page=2, section="Results", text="A evidence", chunk_index=0),
              EvidenceChunk(paper_id=papers[1].id, page=3, section="Methods", text="B evidence", chunk_index=0)]
    session.add_all(chunks)
    session.commit()
    yield session, topics, chunks
    session.close()
    Base.metadata.drop_all(engine)


def test_hybrid_request_requires_explicit_mode():
    with pytest.raises(ValueError):
        HybridInferIn(user_request="test")


def test_server_resolves_only_existing_evidence_in_selected_topic(db):
    session, topics, chunks = db
    found = resolve_topic_evidence(session, topics[0].id, [chunks[0].id])
    assert found[0]["_server_verified"] is True
    assert found[0]["evidence_status"] == "RETRIEVED_UNREVIEWED"
    assert "A evidence" == found[0]["text"]
    with pytest.raises(HTTPException) as error:
        resolve_topic_evidence(session, topics[0].id, [chunks[1].id])
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "EVIDENCE_REFERENCE_INVALID"


def test_missing_or_fabricated_citation_is_rejected(db):
    session, topics, _chunks = db
    with pytest.raises(HTTPException):
        resolve_topic_evidence(session, topics[0].id, [999999])


def test_research_mode_rejects_client_state_even_when_experiment_is_also_given(db):
    session, topics, _chunks = db
    experiment = Experiment(code="EXP-X", name="test", target="test", status="COMPLETE",
        demo=False, topic_id=topics[0].id)
    session.add(experiment)
    session.commit()
    payload = HybridInferIn(mode="research", topic_id=topics[0].id, experiment_id=experiment.id,
        scientific_state={"schema_version": "scientific-state-v2", "provenance": {"validity": "VALID"}},
        user_request="run")
    with pytest.raises(HTTPException) as error:
        infer(payload, session)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "CLIENT_STATE_NOT_TRUSTED"


def test_research_mode_requires_quality_verified_server_record(db):
    session, topics, _chunks = db
    experiment = Experiment(code="EXP-Y", name="test", target="test", status="COMPLETE",
        demo=False, topic_id=topics[0].id)
    session.add(experiment)
    session.commit()
    payload = HybridInferIn(mode="research", topic_id=topics[0].id, experiment_id=experiment.id,
        user_request="run")
    with pytest.raises(HTTPException) as error:
        infer(payload, session)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "RESEARCH_STATE_NOT_VERIFIED"
