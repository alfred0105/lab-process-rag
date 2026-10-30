import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.db.database import Base, get_db
from app.main import app
from app.db.models import ScientificObservation


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
            reference_experiment=client.post("/api/experiments",json={"topic_id":topic_id,"name":"Published paper image","target":"microscopy","status":"reference","steps":[{"name":"Published measurement"}]}).json()
            observation = ScientificObservation(topic_id=topic_id, parameter_id="test_temperature", original_value="25", original_unit="degC",
                normalized_value=298.15, normalized_unit="kelvin", value_type="number", source_type="LAB_RECORD", source_id="test:temperature",
                review_status="PENDING")
            test_db = TestSession(); test_db.add(observation); test_db.commit(); test_db.refresh(observation); observation_id=observation.id; test_db.close()
            rejected_early = client.post(f"/api/data/observations/{observation_id}/review", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"checked"})
            assert rejected_early.status_code == 409
            reviewed_observation = client.post(f"/api/data/observations/{observation_id}/review", json={"reviewer":"Researcher","review_status":"REVIEWED","opinion":"Value and unit checked."})
            assert reviewed_observation.status_code == 200, reviewed_observation.text
            accepted_observation = client.post(f"/api/data/observations/{observation_id}/review", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"Traceable to lab notebook."})
            assert accepted_observation.status_code == 200, accepted_observation.text
            assert accepted_observation.json()["review_status"] == "ACCEPTED"
            assert len(accepted_observation.json()["review_history"]) == 2
            tools = client.get("/api/analysis/tools")
            assert tools.status_code == 200
            assert {item["modality"] for item in tools.json()["pilot_tools"]} == {"xrd", "afm", "sem|tem"}

            response = client.post("/api/analysis/run", data={"modality": "tem", "topic_id": str(topic_id), "pixel_size_nm": "0.5", "foreground": "bright"}, files={"file": ("image.png", buffer.getvalue(), "image/png")})
            assert response.status_code == 200, response.text
            run = response.json()
            assert run["modality"] == "tem"
            assert run["review_status"] == "COMPUTED"
            assert run["result"]["component_count"] == 1
            assert len(run["sha256"]) == 64
            assert client.get(run["result"]["mask_url"]).content
            assert client.get(f"/api/analysis/runs/{run['id']}/original").content == buffer.getvalue()
            assert client.get(f"/api/analysis/runs?topic_id={topic_id}").json()[0]["id"] == run["id"]
            reference_analysis=client.post("/api/analysis/run",data={"modality":"sem","topic_id":str(topic_id),"experiment_id":str(reference_experiment["id"]),"pixel_size_nm":"0.5"},files={"file":("paper-image.png",buffer.getvalue(),"image/png")})
            assert reference_analysis.status_code==200,reference_analysis.text
            assert reference_analysis.json()["result"]["analysis_provenance"]["source_type"]=="LITERATURE_ANALYSIS_OUTPUT"
            test_db=TestSession()
            try:
                linked=test_db.query(ScientificObservation).filter_by(analysis_run_id=reference_analysis.json()["id"]).all()
                assert linked and {item.source_type for item in linked}=={"LITERATURE_ANALYSIS_OUTPUT"}
                optimized=client.get(f"/api/optimization/observations/approved?topic_id={topic_id}").json()["observations"]
                assert all(item["source_type"]!="LITERATURE_ANALYSIS_OUTPUT" for item in optimized)
            finally: test_db.close()

            premature = client.post(f"/api/analysis/runs/{run['id']}/review", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"looks good"})
            assert premature.status_code == 409
            reviewed = client.post(f"/api/analysis/runs/{run['id']}/review", json={"reviewer":"Researcher","review_status":"REVIEWED","opinion":"Compared the mask with the source."})
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["review_status"] == "REVIEWED"
            accepted = client.post(f"/api/analysis/runs/{run['id']}/review", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"Scale and segmentation checked."})
            assert accepted.status_code == 200, accepted.text
            assert len(accepted.json()["review_history"]) == 2
            approved = client.get(f"/api/optimization/observations/approved?topic_id={topic_id}")
            assert approved.status_code == 200
            assert approved.json()["status"] == "insufficient_approved_observations"
            assert {item["source_type"] for item in approved.json()["observations"]} <= {"ANALYSIS_OUTPUT", "LAB_RECORD", "LAB_RESULT"}

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
