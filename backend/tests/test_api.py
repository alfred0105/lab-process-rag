from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base, get_db
from app.main import app

def test_health():
    with TestClient(app) as c:
        assert c.get('/api/health').json()['status']=='ok'

def test_simulation_status_reports_phreeqc_without_running_demo_inputs():
    with TestClient(app) as c:
        response=c.get('/api/simulations/status')
        assert response.status_code==200
        assert response.json()['phreeqc_installed'] is True
        assert response.json()['aqueous_equilibrium'] is True

def test_saved_materials_are_reusable_and_scoped_to_topic(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path / 'materials.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        with TestClient(app) as client:
            topic=client.post('/api/topics',json={"name":"Materials test","description":""}).json()
            saved=client.post(f"/api/topics/{topic['id']}/materials",json={"name":"Zinc nitrate","role":"precursor","unit":"mmol","supplier":"Lab supplier","catalog_number":"ZN-01"})
            assert saved.status_code==200
            assert saved.json()["name"]=="Zinc nitrate"
            duplicate=client.post(f"/api/topics/{topic['id']}/materials",json={"name":" zinc nitrate ","role":"different"})
            assert duplicate.json()["id"]==saved.json()["id"]
            assert [item["name"] for item in client.get(f"/api/topics/{topic['id']}/materials").json()]==["Zinc nitrate"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

def test_environment_measurements_are_recorded_per_process_step(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path / 'environment.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        with TestClient(app) as client:
            topic=client.post('/api/topics',json={"name":"Environment test","description":""}).json()
            response=client.post('/api/experiments',json={
                "topic_id":topic['id'],"name":"Checkpoint run","target":"sample",
                "steps":[{"name":"Drying"},{"name":"Annealing"}],
                "materials":[{"name":"Powder","amount":"500","unit":"mg"}],
                "environment_records":[{"step_index":1,"phase":"before","temperature_c":21.5,"relative_humidity_percent":42,"pressure_kpa":101.3,"notes":"Room logger"}],
            })
            assert response.status_code==200
            record=response.json()['environment_records'][0]
            assert record['step_name']=='Annealing'
            assert record['phase']=='before'
            assert record['relative_humidity_percent']==42
            assert response.json()['materials'][0]['unit']=='mg'
            invalid=client.post('/api/experiments',json={"name":"Invalid humidity","target":"sample","environment_records":[{"step_index":0,"phase":"during","relative_humidity_percent":120}]})
            assert invalid.status_code==422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
