import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Paper
from app.main import app
from app.services.ingestion.paper_metadata import extract_paper_metadata, normalize_doi


def make_pdf():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A Practical Study of Solution Processing", fontsize=18)
    page.insert_text((72, 104), "Jane Example and John Researcher", fontsize=10)
    page.insert_text((72, 126), "Journal of Materials, 2024. https://doi.org/10.1234/Example.24", fontsize=9)
    page.insert_text((72, 164), "Abstract", fontsize=11)
    page.insert_textbox((72, 180, 520, 270), "We report a detailed study of solution processing and its effects on material structure. Measurements demonstrate how concentration and temperature alter the resulting film morphology.", fontsize=10)
    page.insert_text((72, 300), "Keywords", fontsize=10)
    page.insert_text((72, 330), "Introduction", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def test_extracts_pdf_metadata_without_external_lookup():
    result = extract_paper_metadata(make_pdf(), "paper.pdf", lookup_crossref=False)
    assert result["title"] == "A Practical Study of Solution Processing"
    assert result["authors"] == "Jane Example and John Researcher"
    assert result["metadata_sources"]["authors"] == "pdf_first_page"
    assert result["doi"] == "10.1234/example.24"
    assert "solution processing" in result["abstract"].lower()
    assert result["metadata_sources"]["abstract"] == "pdf_abstract_section"


def test_doi_normalization_and_filename_fallback():
    assert normalize_doi("https://doi.org/10.5555/ABC.1).") == "10.5555/abc.1"
    doc = pymupdf.open(); doc.new_page().insert_text((72, 72), "Short scan"); payload = doc.tobytes(); doc.close()
    result = extract_paper_metadata(payload, "untitled_scan.pdf", lookup_crossref=False)
    assert result["title"] == "untitled_scan"
    assert result["metadata_sources"]["title"] == "filename_fallback"
    assert result["needs_review"] is True


def test_crossref_doi_match_prefills_external_values_and_reports_conflicts(monkeypatch):
    monkeypatch.setattr("app.services.ingestion.paper_metadata._crossref", lambda doi: {
        "title": "Registered Crossref Title", "authors": ["J. Example"], "year": 2025,
        "doi": doi, "abstract": None, "journal": "Materials Journal",
    })
    result = extract_paper_metadata(make_pdf(), "paper.pdf")
    assert result["title"] == "Registered Crossref Title"
    assert result["metadata_sources"]["title"] == "crossref_doi"
    assert result["conflicts"]["title"]["pdf"] == "A Practical Study of Solution Processing"
    assert result["conflicts"]["year"]["crossref"] == 2025
    assert result["needs_review"] is True


def test_metadata_preview_does_not_create_paper_and_save_persists_reviewed_values(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'papers.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    def get_test_db():
        db = sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setattr("app.services.ingestion.paper_metadata._crossref", lambda doi: None)
    try:
        with TestClient(app) as client:
            topic = client.post("/api/topics", json={"name": "Paper metadata topic", "description": ""}).json()
            pdf = make_pdf()
            preview = client.post("/api/papers/metadata-preview", files={"file": ("study.pdf", pdf, "application/pdf")})
            assert preview.status_code == 200
            assert preview.json()["title"] == "A Practical Study of Solution Processing"
            with sessions() as db:
                assert db.query(Paper).count() == 0
            saved = client.post("/api/papers", data={"topic_id": str(topic["id"]), "title": "Reviewed title", "authors": "Jane Example", "doi": "10.1234/Example.24", "abstract": "Reviewer-confirmed abstract", "metadata_sources": '{"title":"user_edited"}'}, files={"file": ("study.pdf", pdf, "application/pdf")})
            assert saved.status_code == 200, saved.text
            record = client.get(f"/api/papers?topic_id={topic['id']}").json()[0]
            assert record["title"] == "Reviewed title"
            assert record["authors"] == "Jane Example"
            assert record["doi"] == "10.1234/example.24"
            assert record["abstract"] == "Reviewer-confirmed abstract"
            assert record["metadata_sources"]["title"] == "user_edited"
            assert record["summary"] != record["abstract"]
            legacy = client.post("/api/papers", data={"topic_id": str(topic["id"])}, files={"file": ("legacy.pdf", pdf, "application/pdf")})
            assert legacy.status_code == 200, legacy.text
            assert legacy.json()["title"] == "A Practical Study of Solution Processing"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
