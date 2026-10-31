import math
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Experiment, ExperimentMethod, MethodVersion, ResearchTopic, ScientificObservation
from app.main import app
from app.services.optimization.gpbo import GaussianProcess, OptimizationInputError, acquisition, branin, sandbox_benchmark


def test_gp_fit_predict_kernels_serialization_and_acquisitions():
    x=np.linspace(-2,2,18)[:,None]; y=np.sin(x[:,0])
    for kernel in ("rbf","matern"):
        model=GaussianProcess.fit(x,y,kernel=kernel,noise=1e-5)
        mean,std=model.predict([[0.2],[1.1]])
        assert np.all(np.isfinite(mean)) and np.all(np.isfinite(std)) and min(std)>=0
        restored=GaussianProcess.from_dict(model.to_dict())
        assert restored.predict([[0.2]])==model.predict([[0.2]])
    assert acquisition([1],[0],0,"ei")[0] == pytest.approx(0.99)
    assert acquisition([-1],[0],0,"ei",maximize=False)[0] == pytest.approx(0.99)
    assert acquisition([2],[0],1,"pi")[0] == 1
    assert acquisition([1],[0],0,"ucb",maximize=False)[0] == -1
    with pytest.raises(OptimizationInputError): GaussianProcess.fit([[1],[1]],[float("nan"),2])
    with pytest.raises(OptimizationInputError): model.predict([[1,2]])


def test_gp_consumes_measurement_uncertainty_and_rejects_invalid_values():
    x=np.array([[0.],[1.],[2.],[3.]])
    y=np.array([0.1,1.2,1.8,3.1])
    model=GaussianProcess.fit(x,y,measurement_std=[0.01,0.02,0.03,0.04])
    assert any(value>0 for value in model.observation_noise_variance)
    restored=GaussianProcess.from_dict(model.to_dict())
    assert restored.observation_noise_variance==model.observation_noise_variance
    with pytest.raises(OptimizationInputError): GaussianProcess.fit(x,y,measurement_std=[0.1])
    with pytest.raises(OptimizationInputError): GaussianProcess.fit(x,y,measurement_std=[0.0,0.1,-0.1,0.0])


def test_synthetic_branin_bo_benchmark_is_reproducible_and_not_labeled_research():
    first=sandbox_benchmark(seed=23,budget=8); second=sandbox_benchmark(seed=23,budget=8)
    assert {key:value for key,value in first.items() if key!="wall_clock_seconds"}=={key:value for key,value in second.items() if key!="wall_clock_seconds"}
    assert first["wall_clock_seconds"]>0
    assert first["function"].startswith("Branin")
    assert "do not establish" in first["notice"]
    assert first["seeds"]==5
    assert set(first["policies"])=={"random_search","latin_hypercube","gp_ei","gp_ucb"}
    assert first["policies"]["gp_ei"]["runs"]==5
    assert len(first["policies"]["gp_ei"]["mean_best_trace"])==8
    assert np.isfinite(branin(np.array([[math.pi,2.275]]))).all()


def test_gpbo_api_sandbox_persistence_and_research_data_isolation(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'gpbo.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False); Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        with TestClient(app) as client:
            db=sessions(); topic=ResearchTopic(name="GP test",description=""); db.add(topic); db.flush()
            other=ResearchTopic(name="GP other",description=""); db.add(other); db.flush()
            method=ExperimentMethod(topic_id=topic.id,name="test process"); db.add(method); db.flush()
            version=MethodVersion(method_id=method.id,version_number=1,version_label="1",process_map=[],condition_definitions=[],material_definitions=[]); db.add(version); db.flush()
            for i,(x,y) in enumerate([(0,0.2),(1,0.8),(2,0.5),(3,1.1),(4,0.7)]):
                exp=Experiment(code=f"GP-{i}",name=f"run {i}",target="test",status="success",demo=False,topic_id=topic.id,method_version_id=version.id)
                db.add(exp); db.flush()
                for param,value,source in (("temperature",x,"LAB_RECORD"),("yield",y,"LAB_RESULT")):
                    db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,
                        parameter_id=param,original_value=str(value),original_unit="unit",normalized_value=float(value),normalized_unit="unit",
                        value_type="number",source_type=source,source_id=f"{exp.id}:{param}",review_status="ACCEPTED"))
                # This simulation-only row must never join the measured target.
                db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,
                    parameter_id="yield",original_value="99",original_unit="unit",normalized_value=99.,normalized_unit="unit",
                    value_type="number",source_type="SIMULATION",source_id=f"{exp.id}:sim",review_status="ACCEPTED"))
            db.commit(); topic_id=topic.id; other_id=other.id; version_id=version.id; db.close()
            preview=client.get(f"/api/optimization/dataset?topic_id={topic_id}&method_version_id={version_id}&feature_ids=temperature&target_id=yield")
            assert preview.status_code==200 and preview.json()["sample_count"]==5
            assert preview.json()["features"][0]["unit"]=="unit"
            assert len(preview.json()["dataset_hash"])==64
            train=client.post("/api/optimization/models/train",json={"topic_id":topic_id,"mode":"research","method_version_id":version_id,"feature_ids":["temperature"],"target_id":"yield","kernel":"matern"})
            assert train.status_code==200,train.text
            model=train.json(); assert model["mode"]=="research" and model["config"]["sample_count"]==5
            assert model["config"]["validation_scheme"].startswith("deterministic 80/20")
            assert len(model["config"]["provenance"])==5
            assert len(model["dataset_hash"])==64
            prediction=client.post(f"/api/optimization/models/{model['model_id']}/predict",json={"topic_id":topic_id,"candidates":[[2.5]]})
            assert prediction.status_code==200 and np.isfinite(prediction.json()["predictions"][0]["predicted_mean"])
            rec=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"maximize":True,"candidate_count":3,"search_samples":500})
            assert rec.status_code==200 and len(rec.json()["candidates"])==3
            assert rec.json()["candidates"][0]["approval_status"]=="PENDING_RESEARCHER_REVIEW"
            assert "not a predicted outcome" in rec.json()["notice"]
            for acquisition in ("pi","ucb"):
                alternate=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"maximize":False,"acquisition":acquisition,"candidate_count":2,"search_samples":500,"seed":11})
                assert alternate.status_code==200 and len(alternate.json()["candidates"])==2
                assert alternate.json()["candidates"][0]["acquisition_score"]>=alternate.json()["candidates"][1]["acquisition_score"]
            assert client.get(f"/api/optimization/models/{model['model_id']}?topic_id={other_id}").status_code==404
            approved=client.get(f"/api/optimization/observations/approved?topic_id={topic_id}").json()
            assert all(row["source_type"]!="SIMULATION" for row in approved["observations"])
            assert client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"constraints":[{"type":"unknown"}]}).status_code==422
            sandbox=client.post("/api/optimization/models/train",json={"topic_id":topic_id,"mode":"sandbox","feature_ids":["x1","x2"],"target_id":"branin","seed":31})
            assert sandbox.status_code==200 and sandbox.json()["mode"]=="sandbox"
            assert sandbox.json()["config"]["sample_count"]==24
            assert client.get("/api/optimization/recommendations/1?topic_id="+str(topic_id)).status_code==200
            insufficient=client.post("/api/optimization/models/train",json={"topic_id":other_id,"mode":"research","method_version_id":version_id,"feature_ids":["temperature"],"target_id":"yield"})
            assert insufficient.status_code==422 and insufficient.json()["detail"]["code"]=="INSUFFICIENT_APPROVED_DATA"
            bench=client.post(f"/api/optimization/sandbox/benchmark?topic_id={topic_id}&budget=5&seed=9")
            assert bench.status_code==200 and bench.json()["policies"]["gp_ei"]["runs"]==5
    finally:
        app.dependency_overrides.clear(); engine.dispose()
