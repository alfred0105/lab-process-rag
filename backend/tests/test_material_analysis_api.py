import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.db.database import Base, get_db
from app.main import app


def test_analysis_api_persists_original_and_mask_with_provenance(tmp_path, monkeypatch):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'analysis.db'}", connect_args={"check_same_thread": False})
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr(routes, "ANALYSIS_ROOT", tmp_path / "analysis-files")

    def get_test_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_test_db
    pixels = np.zeros((24, 24), dtype=np.uint8)
    pixels[6:18, 6:18] = 240
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="L").save(buffer, format="PNG")
    try:
        with TestClient(app) as client:
            topic_response = client.post("/api/topics", json={"name": "Analysis test", "description": ""})
            assert topic_response.status_code == 200, topic_response.text
            topic_id = topic_response.json()["id"]
            tools = client.get("/api/analysis/tools")
            assert tools.status_code == 200
            assert {item["modality"] for item in tools.json()["pilot_tools"]} == {"xrd", "afm", "sem|tem"}

            response = client.post("/api/analysis/run", data={"modality": "tem", "topic_id": str(topic_id), "pixel_size_nm": "0.5", "foreground": "bright"}, files={"file": ("image.png", buffer.getvalue(), "image/png")})
            assert response.status_code == 200, response.text
            run = response.json()
            assert run["modality"] == "tem"
            assert run["result"]["component_count"] == 1
            assert len(run["sha256"]) == 64
            assert client.get(run["result"]["mask_url"]).content
            assert client.get(f"/api/analysis/runs/{run['id']}/original").content == buffer.getvalue()
            assert client.get(f"/api/analysis/runs?topic_id={topic_id}").json()[0]["id"] == run["id"]

            class FakeGemma:
                def explain_analysis(self, source):
                    assert source["analysis"]["component_count"] == 1
                    assert "filename" not in source
                    return {"summary": "이미지 분할 미리보기 결과입니다.", "review_notes": ["입자 경계를 원본과 대조하세요."]}

            monkeypatch.setattr(routes, "configured_provider", lambda _settings: FakeGemma())
            explanation = client.post(f"/api/analysis/runs/{run['id']}/explain")
            assert explanation.status_code == 200, explanation.text
            assert explanation.json()["analysis_run_id"] == run["id"]
            assert "not a measurement" in explanation.json()["notice"]
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()
