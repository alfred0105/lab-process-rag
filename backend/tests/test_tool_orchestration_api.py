from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.db.database import Base, get_db
from app.db.models import ScientificObservation
from app.main import app
from app.services.simulation.phreeqc import calculate_aqueous_equilibrium


def test_tool_recommendation_uses_goal_and_execution_persists_validated_phreeqc_output(tmp_path, monkeypatch):
    engine=create_engine(f"sqlite:///{tmp_path/'tools.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    calls=[]
    def fake_phreeqc(**inputs):
        calls.append(inputs)
        if inputs["pH"]==7.5: raise ValueError("test calculation failure")
        return {"model_id":"PHREEQC-3 / phreeqc.dat","input_pH":inputs["pH"],"calculated_pH":inputs["pH"],
                "input_totals_molal":inputs["totals_molal"],"aqueous_species":[],"saturation_indices":[],"status":"EQUILIBRIUM_ESTIMATE","limitations":["no precipitation prediction"]}
    monkeypatch.setattr(routes,"calculate_aqueous_equilibrium",fake_phreeqc)
    try:
        with TestClient(app) as client:
            topic=client.post('/api/topics',json={"name":"Tool execution test","description":""}).json()
            experiment=client.post('/api/experiments',json={"topic_id":topic['id'],"name":"Chemistry run","target":"solution","steps":[{"name":"Mixing"}]}).json()
            goal=client.get(f"/api/experiments/{experiment['id']}/tools/recommend?goal=data%20quality%20validation")
            assert goal.status_code==200
            assert goal.json()['decision']['action']=='RUN_DATA_VALIDATION'
            quality=client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"experiment.data_quality.v1","inputs":{}})
            assert quality.status_code==200,quality.text
            assert quality.json()['result']['issue_count']==0
            invalid=client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"phreeqc.aqueous_equilibrium.v1","inputs":{"temperature_c":25,"pH":7,"totals_molal":{},"phases":[]}})
            assert invalid.status_code==422
            payload={"temperature_c":25,"pH":7,"totals_molal":{"Zn":0.001},"phases":["Zincite"]}
            executed=client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"phreeqc.aqueous_equilibrium.v1","inputs":payload})
            assert executed.status_code==200,executed.text
            assert executed.json()['status']=='completed'
            assert executed.json()['validation']['valid'] is True
            assert executed.json()['provenance']['model_id']=='PHREEQC-3 / phreeqc.dat'
            reused=client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"phreeqc.aqueous_equilibrium.v1","inputs":payload})
            assert reused.status_code==200,reused.text
            assert reused.json()['status']=='REUSED'
            assert len(calls)==1
            failed=client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"phreeqc.aqueous_equilibrium.v1","inputs":{**payload,"pH":7.5}})
            assert failed.status_code==422
            assert client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"openfoam.simpleRushtonMRF.v1","inputs":{}}).status_code==409
            db=sessions()
            try:
                observations=db.query(ScientificObservation).filter_by(source_type='SIMULATION').all()
                assert observations
                assert all(item.review_status=='COMPUTED' and item.source_id.startswith('simulation-run:') for item in observations)
                from app.db.models import SimulationRun
                assert db.query(SimulationRun).filter_by(status='failed').count()==1
            finally: db.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_real_phreeqc_adapter_returns_species_and_scope_limited_saturation():
    import pytest
    pytest.importorskip("phreeqpython")
    result=calculate_aqueous_equilibrium(temperature_c=25,pH=8.3,totals_molal={"Ca":0.001,"C(4)":0.001},phases=["Calcite"])
    assert result["model_id"]=="PHREEQC-3 / phreeqc.dat"
    assert result["aqueous_species"]
    assert result["saturation_indices"][0]["phase"]=="Calcite"
    assert "does not prove precipitation" in result["limitations"][1]


def test_real_phreeqc_tool_api_executes_and_persists_result(tmp_path):
    import pytest
    pytest.importorskip("phreeqpython")
    engine=create_engine(f"sqlite:///{tmp_path/'real-phreeqc.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        with TestClient(app) as client:
            topic=client.post('/api/topics',json={"name":"Real PHREEQC API test","description":""}).json()
            experiment=client.post('/api/experiments',json={"topic_id":topic['id'],"name":"Calcite equilibrium","target":"solution","steps":[{"name":"Mixing"}]}).json()
            response=client.post('/api/tools/execute',json={"experiment_id":experiment['id'],"tool_id":"phreeqc.aqueous_equilibrium.v1","inputs":{"temperature_c":25,"pH":8.3,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"]}})
            assert response.status_code==200,response.text
            body=response.json()
            assert body['status']=='completed'
            assert body['result']['aqueous_species']
            assert body['result']['saturation_indices'][0]['saturation_index'] is not None
            assert body['provenance']['input']['totals_molal']['Ca']==0.001
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

