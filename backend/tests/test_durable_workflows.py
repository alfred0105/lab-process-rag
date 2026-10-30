from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
import os
import subprocess
import sys
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Experiment, ProcessStep, ProcessVariable, ResearchTopic, WorkflowNode, WorkflowRun
from app.schemas.core import WorkflowCreateRequest
from app import worker


def _db(tmp_path, monkeypatch):
    engine=create_engine(f"sqlite:///{tmp_path/'worker.db'}",connect_args={"check_same_thread":False,"timeout":20})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(worker,"SessionLocal",sessions)
    db=sessions();topic=ResearchTopic(name="workflow",description="")
    db.add(topic);db.flush()
    experiment=Experiment(code="WF-001",name="workflow test",target="validation",status="planned",topic_id=topic.id,demo=False)
    db.add(experiment);db.flush()
    db.commit()
    return engine,sessions,db,topic,experiment


def test_workflow_request_rejects_cycles_and_untyped_handoffs():
    with pytest.raises(ValidationError):
        WorkflowCreateRequest(topic_id=1,experiment_id=1,goal="cycle graph",nodes=[
            {"key":"a","tool_id":"experiment.data_quality.v1","depends_on":["b"]},
            {"key":"b","tool_id":"experiment.data_quality.v1","depends_on":["a"]}])


def test_two_workers_cannot_claim_same_workflow_node(tmp_path,monkeypatch):
    engine,sessions,db,topic,experiment=_db(tmp_path,monkeypatch)
    flow=WorkflowRun(topic_id=topic.id,experiment_id=experiment.id,goal="claim contention",status="QUEUED",graph_json={},created_at=datetime.utcnow())
    db.add(flow);db.flush();db.add(WorkflowNode(workflow_id=flow.id,node_key="quality",tool_id="experiment.data_quality.v1",dependency_keys=[],input_json={},created_at=datetime.utcnow()))
    db.commit();db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda name:worker._workflow_claim(name),("worker-a","worker-b")))
    claimed=[item for item in claims if item]
    assert len(claimed)==1
    assert claimed[0][2]==1
    engine.dispose()


def test_separate_worker_processes_share_one_atomic_durable_queue(tmp_path,monkeypatch):
    engine,sessions,db,topic,experiment=_db(tmp_path,monkeypatch)
    flow=WorkflowRun(topic_id=topic.id,experiment_id=experiment.id,goal="multi process claim",status="QUEUED",graph_json={},created_at=datetime.utcnow())
    db.add(flow);db.flush();db.add(WorkflowNode(workflow_id=flow.id,node_key="quality",tool_id="experiment.data_quality.v1",dependency_keys=[],input_json={},created_at=datetime.utcnow()))
    db.commit();db.close();engine.dispose()
    db_path=tmp_path/"worker.db";env={**os.environ,"LAB_PROCESS_DB_PATH":str(db_path)}
    backend_dir=os.path.dirname(os.path.dirname(__file__))
    processes=[subprocess.Popen([sys.executable,"-m","app.worker","--once"],cwd=backend_dir,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results=[process.communicate(timeout=20)+(process.returncode,) for process in processes]
    assert all(result[2] in {0,1} for result in results),results
    engine2=create_engine(f"sqlite:///{db_path}");session2=sessionmaker(bind=engine2)();node=session2.query(WorkflowNode).one()
    assert node.status=="COMPLETED"
    assert node.attempt==1
    assert node.lease_generation==1
    session2.close();engine2.dispose()


def test_durable_worker_executes_dag_and_persists_terminal_state(tmp_path,monkeypatch):
    engine,sessions,db,topic,experiment=_db(tmp_path,monkeypatch)
    flow=WorkflowRun(topic_id=topic.id,experiment_id=experiment.id,goal="quality check",status="QUEUED",graph_json={},created_at=datetime.utcnow())
    db.add(flow);db.flush()
    db.add_all([
        WorkflowNode(workflow_id=flow.id,node_key="quality",tool_id="experiment.data_quality.v1",dependency_keys=[],input_json={},created_at=datetime.utcnow()),
        WorkflowNode(workflow_id=flow.id,node_key="child",tool_id="experiment.data_quality.v1",dependency_keys=["quality"],input_json={},created_at=datetime.utcnow())])
    db.commit();db.close()
    assert worker.run_once("test-worker") is True
    assert worker.run_once("test-worker") is True
    db=sessions();saved=db.query(WorkflowRun).one();nodes=db.query(WorkflowNode).order_by(WorkflowNode.id).all()
    assert saved.status=="COMPLETED"
    assert [item.status for item in nodes]==["COMPLETED","COMPLETED"]
    assert [item.lease_generation for item in nodes]==[1,1]
    assert all(item.output_json is not None for item in nodes)
    db.close();engine.dispose()


def test_failed_dependency_blocks_child_without_claiming_it(tmp_path,monkeypatch):
    engine,sessions,db,topic,experiment=_db(tmp_path,monkeypatch)
    flow=WorkflowRun(topic_id=topic.id,experiment_id=experiment.id,goal="failure propagation",status="QUEUED",graph_json={},created_at=datetime.utcnow())
    db.add(flow);db.flush()
    db.add_all([
        WorkflowNode(workflow_id=flow.id,node_key="broken",tool_id="experiment.data_quality.v1",dependency_keys=[],input_json={},status="FAILED",created_at=datetime.utcnow()),
        WorkflowNode(workflow_id=flow.id,node_key="downstream",tool_id="experiment.data_quality.v1",dependency_keys=["broken"],input_json={},created_at=datetime.utcnow())])
    db.commit();db.close()
    assert worker._workflow_claim("test-worker") is None
    db=sessions();node=db.query(WorkflowNode).filter_by(node_key="downstream").one()
    assert node.status=="BLOCKED" and node.error_code=="DEPENDENCY_FAILED"
    db.close();engine.dispose()


def test_data_quality_gate_requires_review_before_dependent_tool(tmp_path,monkeypatch):
    engine,sessions,db,topic,experiment=_db(tmp_path,monkeypatch)
    step=ProcessStep(experiment_id=experiment.id,name="mix",step_type="process",order_index=0,description="")
    db.add(step);db.flush();db.add(ProcessVariable(process_step_id=step.id,name="temperature",value="25",unit=None))
    flow=WorkflowRun(topic_id=topic.id,experiment_id=experiment.id,goal="require valid inputs before analysis",status="QUEUED",graph_json={},created_at=datetime.utcnow())
    db.add(flow);db.flush();db.add_all([
        WorkflowNode(workflow_id=flow.id,node_key="quality",tool_id="experiment.data_quality.v1",dependency_keys=[],input_json={},created_at=datetime.utcnow()),
        WorkflowNode(workflow_id=flow.id,node_key="analysis",tool_id="experiment.data_quality.v1",dependency_keys=["quality"],input_json={},created_at=datetime.utcnow())])
    db.commit();db.close()
    assert worker.run_once("test-worker") is True
    assert worker._workflow_claim("test-worker") is None
    db=sessions();saved=db.query(WorkflowRun).one();nodes=db.query(WorkflowNode).order_by(WorkflowNode.id).all()
    assert saved.status=="REQUIRES_REVIEW"
    assert nodes[0].status=="REQUIRES_REVIEW" and nodes[0].output_json["issue_count"]==1
    assert nodes[1].status=="BLOCKED"
    db.close();engine.dispose()


def test_worker_execution_timeout_is_enforced():
    class LeaseStub:
        lost=type("Flag",(),{"is_set":lambda self:False})()
        cancelled=type("Flag",(),{"is_set":lambda self:False})()
        def check(self):
            if self.cancelled.is_set(): raise worker.JobCancelled("cancel")
    with pytest.raises(worker.JobTimedOut):
        worker._run_with_limits(1,LeaseStub(),lambda:__import__("time").sleep(3))

def test_worker_cancellation_interrupts_active_operation():
    import threading,time
    class LeaseStub:
        lost=threading.Event();cancelled=threading.Event()
        def check(self):
            if self.cancelled.is_set(): raise worker.JobCancelled("cancel")
    lease=LeaseStub();threading.Timer(.1,lease.cancelled.set).start()
    with pytest.raises(worker.JobCancelled):
        worker._run_with_limits(5,lease,lambda:time.sleep(3))


def test_real_phreeqc_workflow_persists_simulation_provenance_and_observations(tmp_path,monkeypatch):
    pytest.importorskip("phreeqpython")
    from fastapi.testclient import TestClient
    from app.db.database import get_db
    from app.db.models import ScientificObservation,SimulationRun
    from app.main import app
    engine,sessions,db,topic,experiment=_db(tmp_path,monkeypatch);topic_id=topic.id;experiment_id=experiment.id;db.close()
    def get_test_db():
        session=sessions()
        try:yield session
        finally:session.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        with TestClient(app) as client:
            response=client.post("/api/workflows",json={"topic_id":topic_id,"experiment_id":experiment_id,"goal":"Check carbonate equilibrium and retain the model provenance","nodes":[
                {"key":"quality","tool_id":"experiment.data_quality.v1","inputs":{}},
                {"key":"equilibrium","tool_id":"phreeqc.aqueous_equilibrium.v1","depends_on":["quality"],"approval_confirmed":True,
                 "inputs":{"inputs":{"temperature_c":25,"pH":8.3,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"]}}}]})
            assert response.status_code==202,response.text
            workflow_id=response.json()["id"]
            assert worker.run_once("phase3-test") is True
            assert worker.run_once("phase3-test") is True
            state=client.get(f"/api/workflows/{workflow_id}?topic_id={topic_id}").json()
            assert state["status"]=="COMPLETED"
            assert [node["status"] for node in state["nodes"]]==["COMPLETED","COMPLETED"]
            stored=sessions();simulation=stored.query(SimulationRun).one()
            assert simulation.status=="completed"
            assert simulation.result_json["provenance"]["tool_id"]=="phreeqc.aqueous_equilibrium.v1"
            assert simulation.result_json["saturation_indices"][0]["phase"]=="Calcite"
            assert stored.query(ScientificObservation).filter_by(source_type="SIMULATION",review_status="COMPUTED").count()>=3
            stored.close()
    finally:
        app.dependency_overrides.clear();engine.dispose()
