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
            second_topic=client.post("/api/topics",json={"name":"Separate analysis topic","description":""}).json()
            reference_experiment=client.post("/api/experiments",json={"topic_id":topic_id,"name":"Published paper image","target":"microscopy","status":"reference","steps":[{"name":"Published measurement"}]}).json()
            observation = ScientificObservation(topic_id=topic_id, parameter_id="test_temperature", original_value="25", original_unit="degC",
                normalized_value=298.15, normalized_unit="kelvin", value_type="number", source_type="LAB_RECORD", source_id="test:temperature",
                review_status="PENDING")
            test_db = TestSession(); test_db.add(observation); test_db.commit(); test_db.refresh(observation); observation_id=observation.id; test_db.close()
            assert client.post(f"/api/data/observations/{observation_id}/review?topic_id={second_topic['id']}",json={"reviewer":"R","review_status":"REVIEWED","opinion":"cross-topic"}).status_code==404
            rejected_early = client.post(f"/api/data/observations/{observation_id}/review?topic_id={topic_id}", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"checked"})
            assert rejected_early.status_code == 409
            reviewed_observation = client.post(f"/api/data/observations/{observation_id}/review?topic_id={topic_id}", json={"reviewer":"Researcher","review_status":"REVIEWED","opinion":"Value and unit checked."})
            assert reviewed_observation.status_code == 200, reviewed_observation.text
            accepted_observation = client.post(f"/api/data/observations/{observation_id}/review?topic_id={topic_id}", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"Traceable to lab notebook."})
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
            provenance=run["result"]["analysis_provenance"]
            for key in ("original_artifact","derived_artifact"):
                manifest=provenance[key]
                assert manifest["sha256"] and manifest["size_bytes"]>0 and manifest["content_type"]
                assert manifest["tool_id"]==run["tool_id"] and manifest["tool_version"]
                assert manifest["source_run_id"]==provenance["analysis_run_key"] and manifest["parent_data_ids"]
                assert manifest["review_status"] in {"PENDING","COMPUTED"}
            assert client.get(run["result"]["mask_url"]).content
            assert client.get(f"/api/analysis/runs/{run['id']}/original?topic_id={topic_id}").content == buffer.getvalue()
            original_path=routes.ANALYSIS_ROOT/provenance["original_artifact"]["path"]
            original_path.write_bytes(b"altered after save")
            assert client.get(f"/api/analysis/runs/{run['id']}/original?topic_id={topic_id}").status_code==409
            original_path.write_bytes(buffer.getvalue())
            assert client.get(f"/api/analysis/runs?topic_id={topic_id}").json()[0]["id"] == run["id"]
            same_topic_repeat=client.post("/api/analysis/run",data={"modality":"tem","topic_id":str(topic_id),"pixel_size_nm":"0.5","foreground":"bright"},files={"file":("repeat.png",buffer.getvalue(),"image/png")})
            assert same_topic_repeat.status_code==200 and same_topic_repeat.json()["id"]==run["id"]
            cross_topic=client.post("/api/analysis/run",data={"modality":"tem","topic_id":str(second_topic["id"]),"pixel_size_nm":"0.5","foreground":"bright"},files={"file":("same.png",buffer.getvalue(),"image/png")})
            assert cross_topic.status_code==200, cross_topic.text
            assert cross_topic.json()["id"]!=run["id"]
            assert cross_topic.json()["topic_id"]==second_topic["id"]
            assert client.get(f"/api/analysis/runs/{run['id']}/original?topic_id={second_topic['id']}").status_code==404
            assert client.get(f"/api/analysis/runs/{run['id']}/mask?topic_id={second_topic['id']}").status_code==404
            assert client.post(f"/api/analysis/runs/{run['id']}/review?topic_id={second_topic['id']}",json={"reviewer":"R","review_status":"REVIEWED"}).status_code==404
            assert client.post(f"/api/analysis/runs/{run['id']}/phase-match?topic_id={second_topic['id']}").status_code==404
            assert client.post(f"/api/analysis/runs/{run['id']}/explain?topic_id={second_topic['id']}").status_code==404
            assert client.get(f"/api/analysis/runs?topic_id={second_topic['id']}").json()[0]["id"]==cross_topic.json()["id"]
            xrd_bytes=b"10,1\n11,2\n12,10\n13,2\n14,1\n"
            xrd_form={"modality":"xrd","topic_id":str(topic_id),"xrd_x_unit":"2theta_deg"}
            xrd_first=client.post("/api/analysis/run",data=xrd_form,files={"file":("scan.xy",xrd_bytes,"text/plain")})
            assert xrd_first.status_code==200,xrd_first.text
            xrd_reused=client.post("/api/analysis/run",data=xrd_form,files={"file":("same-content.xy",xrd_bytes,"text/plain")})
            assert xrd_reused.status_code==200 and xrd_reused.json()["id"]==xrd_first.json()["id"]
            xrd_reanalyzed=client.post("/api/analysis/run",data={**xrd_form,"xrd_x_unit":"d_angstrom"},files={"file":("scan.xy",xrd_bytes,"text/plain")})
            assert xrd_reanalyzed.status_code==200,xrd_reanalyzed.text
            assert xrd_reanalyzed.json()["id"]!=xrd_first.json()["id"]
            assert xrd_reanalyzed.json()["result"]["analysis_provenance"]["parameters"]["xrd_x_unit"]=="d_angstrom"
            assert any(row["id"]==xrd_first.json()["id"] for row in client.get(f"/api/analysis/runs?topic_id={topic_id}").json())
            from app.db.models import MaterialAnalysisRun
            legacy=TestSession();legacy_run=legacy.get(MaterialAnalysisRun,xrd_first.json()["id"])
            import copy
            legacy_payload=copy.deepcopy(legacy_run.result_json);legacy_payload["analysis_provenance"]["algorithm_version"]="old-algorithm"
            legacy_run.result_json=legacy_payload
            legacy.commit();legacy.close()
            xrd_algorithm_changed=client.post("/api/analysis/run",data=xrd_form,files={"file":("scan.xy",xrd_bytes,"text/plain")})
            assert xrd_algorithm_changed.status_code==200 and xrd_algorithm_changed.json()["id"] not in {xrd_first.json()["id"],xrd_reanalyzed.json()["id"]}
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

            premature = client.post(f"/api/analysis/runs/{run['id']}/review?topic_id={topic_id}", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"looks good"})
            assert premature.status_code == 409
            reviewed = client.post(f"/api/analysis/runs/{run['id']}/review?topic_id={topic_id}", json={"reviewer":"Researcher","review_status":"REVIEWED","opinion":"Compared the mask with the source."})
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["review_status"] == "REVIEWED"
            accepted = client.post(f"/api/analysis/runs/{run['id']}/review?topic_id={topic_id}", json={"reviewer":"Researcher","review_status":"ACCEPTED","reason":"Scale and segmentation checked."})
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
            explanation = client.post(f"/api/analysis/runs/{run['id']}/explain?topic_id={topic_id}")
            assert explanation.status_code == 200, explanation.text
            assert explanation.json()["analysis_run_id"] == run["id"]
            assert "not a measurement" in explanation.json()["notice"]
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()
