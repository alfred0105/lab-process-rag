"""Topic-scoped API for durable scientific DAG workflows."""
from datetime import datetime, timezone
import os
import tempfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Experiment, MaterialAnalysisRun, SimulationRun, WorkflowNode, WorkflowRun
from app.schemas.core import WorkflowCreateRequest, WorkflowNodeIn, WorkflowPlanRequest
from app.services.workflow_planner import plan_workflow

router=APIRouter()
WORKFLOW_TOOLS={"experiment.data_quality.v1","xrd.local_peaks.v1","afm.plane_level_roughness.v1",
    "microscopy.otsu_components.v1","phreeqc.aqueous_equilibrium.v1","phreeqc.aqueous_sweep.v1"}

def _isolated_synthetic_test_mode() -> bool:
    """Permit synthetic workflow fixtures only with an explicit flag and temp DB."""
    db_path=os.getenv("LAB_PROCESS_DB_PATH")
    if os.getenv("LAB_PROCESS_TESTING") != "1" or not db_path:
        return False
    try:
        Path(db_path).expanduser().resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except ValueError:
        return False

def _plan_context(db, experiment):
    analysis_runs=db.query(MaterialAnalysisRun).filter_by(topic_id=experiment.topic_id,experiment_id=experiment.id).order_by(MaterialAnalysisRun.id).all()
    record={"id":experiment.id,"topic_id":experiment.topic_id,"demo":experiment.demo,"status":experiment.status,
        "method_version_id":experiment.method_version_id,
        "steps":[{"id":step.id,"name":step.name,"order_index":step.order_index,
            "variables":[{"name":variable.name,"value":variable.value,"unit":variable.unit,"material":variable.material} for variable in step.variables]}
            for step in experiment.steps],
        "materials":[{"name":material.name,"amount":material.amount,"unit":material.unit,"role":material.role} for material in experiment.materials],
        "results":[{"key":result.key,"value":result.value,"unit":result.unit} for result in experiment.results]}
    runs=[]
    for run in analysis_runs:
        result=run.result_json or {}
        review=run.review_events[-1].review_status if run.review_events else ("COMPUTED" if run.analysis_status=="completed" else "PENDING")
        runs.append({"id":run.id,"topic_id":run.topic_id,"experiment_id":run.experiment_id,"modality":run.modality,
            "analysis_status":run.analysis_status,"review_status":review,"sha256":run.sha256,"result":result,
            "demo":bool(result.get("demo_data")) and not _isolated_synthetic_test_mode(),"filename":run.filename})
    simulation_runs=db.query(SimulationRun).filter_by(experiment_id=experiment.id).order_by(SimulationRun.id.desc()).all()
    simulations=[{"id":item.id,"status":item.status,"model_id":item.model_id,
        "idempotency_key":item.idempotency_key} for item in simulation_runs]
    return record,runs,simulations

def _payload(db, flow):
    nodes=db.query(WorkflowNode).filter_by(workflow_id=flow.id).order_by(WorkflowNode.id).all()
    return {"id":flow.id,"topic_id":flow.topic_id,"experiment_id":flow.experiment_id,"goal":flow.goal,"status":flow.status,
        "cancel_requested":flow.cancel_requested,"created_at":flow.created_at.isoformat()+"Z",
        "started_at":flow.started_at.isoformat()+"Z" if flow.started_at else None,
        "finished_at":flow.finished_at.isoformat()+"Z" if flow.finished_at else None,"result":flow.result_json,"error":flow.error_text,
        "nodes":[{"id":n.id,"key":n.node_key,"tool_id":n.tool_id,"depends_on":n.dependency_keys,"inputs":n.input_json,
            "output":n.output_json,"result_type":n.result_type,"result_id":n.result_id,"status":n.status,
            "attempt":n.attempt,"max_attempts":n.max_attempts,"error_code":n.error_code,"error":n.error_text,
            "started_at":n.started_at.isoformat()+"Z" if n.started_at else None,"finished_at":n.finished_at.isoformat()+"Z" if n.finished_at else None} for n in nodes]}

def _check_references(node, by_key):
    def walk(value):
        if isinstance(value,dict):
            if "$ref" in value:
                ref=value["$ref"]
                if not isinstance(ref,dict) or ref.get("node") not in node.depends_on or not ref.get("path") or not ref.get("unit") or not ref.get("meaning"):
                    raise HTTPException(422,"Typed result references must name a direct dependency and declare path, unit, and meaning.")
            for item in value.values(): walk(item)
        elif isinstance(value,list):
            for item in value: walk(item)
    walk(node.inputs)

@router.post("/workflows",status_code=202)
def create_workflow(payload:WorkflowCreateRequest,db:Session=Depends(get_db)):
    experiment=db.query(Experiment).filter_by(id=payload.experiment_id,topic_id=payload.topic_id).first()
    if not experiment: raise HTTPException(404,"Experiment not found in this topic")
    if experiment.demo: raise HTTPException(422,"Scientific workflow execution is disabled for demo experiments")
    by_key={n.key:n for n in payload.nodes}
    for node in payload.nodes:
        if node.tool_id not in WORKFLOW_TOOLS: raise HTTPException(422,{"reason":"tool_not_registered","tool_id":node.tool_id})
        if any(key.startswith("_") for key in node.inputs):
            raise HTTPException(422,"Workflow inputs cannot set internal Worker metadata.")
        _check_references(node,by_key)
        if node.tool_id.startswith("openfoam."): raise HTTPException(422,"OpenFOAM runs must use the explicit geometry and approval API.")
        if node.tool_id.startswith("phreeqc.") and not node.approval_confirmed: raise HTTPException(409,{"reason":"explicit_calculation_approval_required"})
        if node.tool_id.startswith(("xrd.","afm.","microscopy.")):
            run_id=node.inputs.get("analysis_run_id")
            run=db.query(MaterialAnalysisRun).filter_by(id=run_id,topic_id=payload.topic_id,experiment_id=payload.experiment_id).first() if isinstance(run_id,int) else None
            if not run: raise HTTPException(422,{"reason":"analysis_run_required_for_tool","node":node.key})
            if bool((run.result_json or {}).get("demo_data")) and not _isolated_synthetic_test_mode(): raise HTTPException(422,"Demo measurement files cannot be used in scientific workflows")
            expected="xrd" if node.tool_id.startswith("xrd.") else ("afm" if node.tool_id.startswith("afm.") else "microscopy")
            if expected=="xrd" and run.modality.lower()!="xrd": raise HTTPException(422,"XRD tool requires an XRD upload")
            if expected=="afm" and run.modality.lower()!="afm": raise HTTPException(422,"AFM tool requires an AFM upload")
            if expected=="microscopy" and run.modality.lower() not in {"sem","tem"}: raise HTTPException(422,"Microscopy tool requires SEM/TEM data")
            settings=node.inputs.get("settings") or {}
            if expected=="xrd" and settings.get("xrd_x_unit") not in {"2theta_deg","d_angstrom","q_angstrom^-1"}:
                raise HTTPException(422,{"reason":"xrd_axis_unit_required","message":"Declare the original XRD axis unit before scheduling analysis."})
            if expected=="afm" and settings.get("afm_height_unit") not in {"nm","um","angstrom","m"}:
                raise HTTPException(422,{"reason":"afm_height_calibration_required","message":"Declare the AFM height calibration unit before scheduling analysis."})
            if expected=="microscopy":
                pixel_size=settings.get("pixel_size_nm")
                if isinstance(pixel_size,bool) or not isinstance(pixel_size,(int,float)) or not 0<float(pixel_size)<=100000:
                    raise HTTPException(422,{"reason":"pixel_calibration_required","message":"Declare a finite calibrated pixel size in nm/px before scheduling microscopy analysis."})
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    flow=WorkflowRun(topic_id=payload.topic_id,experiment_id=payload.experiment_id,goal=payload.goal,status="QUEUED",
        graph_json={"nodes":[n.model_dump() for n in payload.nodes]},created_at=now)
    db.add(flow);db.flush()
    for node in payload.nodes:
        db.add(WorkflowNode(workflow_id=flow.id,node_key=node.key,tool_id=node.tool_id,dependency_keys=node.depends_on,
            input_json=node.inputs,approval_confirmed=node.approval_confirmed,timeout_seconds=node.timeout_seconds,
            created_at=now,max_attempts=2))
    db.commit();db.refresh(flow)
    return _payload(db,flow)

@router.post("/workflows/plan",status_code=202)
def plan_or_enqueue_workflow(payload:WorkflowPlanRequest,db:Session=Depends(get_db)):
    experiment=db.query(Experiment).filter_by(id=payload.experiment_id,topic_id=payload.topic_id).first()
    if not experiment: raise HTTPException(404,"Experiment not found in this topic")
    if experiment.demo: raise HTTPException(422,"Scientific workflow planning is disabled for demo experiments")
    record,runs,simulation_runs=_plan_context(db,experiment)
    if payload.process_step_id is not None:
        step_ids={step["id"] for step in record["steps"]}
        if payload.process_step_id not in step_ids:
            raise HTTPException(422,{"reason":"process_step_out_of_scope"})
    plan=plan_workflow(goal=payload.goal,record=record,analysis_runs=runs,
        simulation_inputs=payload.simulation_inputs,
        simulation_runs=simulation_runs,
        database_identifier=payload.database_identifier,process_step_id=payload.process_step_id,
        approval_confirmed=payload.approval_confirmed)
    plan["approval_confirmed"]=bool(payload.approval_confirmed)
    if not payload.enqueue:
        return plan
    if not plan["executable"] or not plan["nodes"]:
        raise HTTPException(409,{"reason":"workflow_plan_not_executable","plan":plan})
    if plan["approval_required"] and not payload.approval_confirmed:
        raise HTTPException(409,{"reason":"explicit_calculation_approval_required","plan":plan})
    nodes=[WorkflowNodeIn(**{**node,"approval_confirmed":payload.approval_confirmed}) for node in plan["nodes"]]
    queued=create_workflow(WorkflowCreateRequest(topic_id=payload.topic_id,experiment_id=payload.experiment_id,
        goal=payload.goal,nodes=nodes),db)
    return {"plan":plan,"workflow":queued}

@router.get("/workflows")
def list_workflows(topic_id:int=Query(...,gt=0),db:Session=Depends(get_db)):
    return [_payload(db,item) for item in db.query(WorkflowRun).filter_by(topic_id=topic_id).order_by(WorkflowRun.created_at.desc()).limit(100).all()]

@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id:int,topic_id:int=Query(...,gt=0),db:Session=Depends(get_db)):
    flow=db.query(WorkflowRun).filter_by(id=workflow_id,topic_id=topic_id).first()
    if not flow: raise HTTPException(404,"Workflow not found")
    return _payload(db,flow)

@router.post("/workflows/{workflow_id}/cancel")
def cancel_workflow(workflow_id:int,topic_id:int=Query(...,gt=0),db:Session=Depends(get_db)):
    flow=db.query(WorkflowRun).filter_by(id=workflow_id,topic_id=topic_id).first()
    if not flow: raise HTTPException(404,"Workflow not found")
    flow.cancel_requested=True
    for node in db.query(WorkflowNode).filter_by(workflow_id=flow.id).all():
        if node.status=="QUEUED": node.status="CANCELLED";node.error_code="CANCELLED_BEFORE_START";node.finished_at=datetime.now(timezone.utc).replace(tzinfo=None)
        elif node.status=="RUNNING": node.cancel_requested=True
        elif node.status=="WAITING_FOR_CACHE": node.status="CANCELLED";node.error_code="CANCELLED_WHILE_WAITING_FOR_CACHE";node.finished_at=datetime.now(timezone.utc).replace(tzinfo=None)
    active=db.query(WorkflowNode).filter_by(workflow_id=flow.id,status="RUNNING").count()
    if not active: flow.status="CANCELLED";flow.finished_at=datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit();return _payload(db,flow)

@router.post("/workflows/{workflow_id}/retry")
def retry_workflow(workflow_id:int,topic_id:int=Query(...,gt=0),node_key:str|None=None,db:Session=Depends(get_db)):
    flow=db.query(WorkflowRun).filter_by(id=workflow_id,topic_id=topic_id).first()
    if not flow: raise HTTPException(404,"Workflow not found")
    nodes=db.query(WorkflowNode).filter_by(workflow_id=flow.id).all(); by_key={n.node_key:n for n in nodes}
    failed=[n for n in nodes if n.status in {"FAILED","TIMED_OUT","BLOCKED","REQUIRES_REVIEW"} and (node_key is None or n.node_key==node_key)]
    if not failed: raise HTTPException(409,"No failed node is eligible for explicit retry")
    reset={n.node_key for n in failed}
    expanded=True
    while expanded:
        expanded=False
        for n in nodes:
            if n.status=="BLOCKED" and any(dep in reset for dep in (n.dependency_keys or [])) and n.node_key not in reset: reset.add(n.node_key);expanded=True
    for key in reset:
        node=by_key[key]
        if node.attempt>=node.max_attempts: raise HTTPException(409,{"reason":"maximum_attempts_reached","node":key})
        if node.tool_id.startswith("phreeqc."):
            inputs=dict(node.input_json or {}); inputs["_retry_failed_calculation"]=True; node.input_json=inputs
        node.status="QUEUED";node.error_code="";node.error_text="";node.finished_at=None;node.cancel_requested=False
    flow.status="QUEUED";flow.cancel_requested=False;flow.error_text="";flow.finished_at=None;db.commit()
    return _payload(db,flow)

@router.post("/simulations/{run_id}/cancel")
def cancel_simulation(run_id:int,topic_id:int=Query(...,gt=0),db:Session=Depends(get_db)):
    run=db.query(SimulationRun).join(Experiment).filter(SimulationRun.id==run_id,Experiment.topic_id==topic_id).first()
    if not run: raise HTTPException(404,"Simulation run not found")
    if run.status=="queued": run.status="cancelled";run.finished_at=datetime.now(timezone.utc).replace(tzinfo=None)
    elif run.status=="running": run.cancel_requested=True
    db.commit();return {"id":run.id,"status":run.status,"cancel_requested":run.cancel_requested}
