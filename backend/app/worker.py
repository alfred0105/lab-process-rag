"""Independent SQLite-backed worker for durable scientific workflows.

Run with ``python -m app.worker`` from ``backend``. Claims use conditional
UPDATEs and monotonically increasing lease generations so stale workers cannot
commit after ownership changes.
"""
from __future__ import annotations

import json
import argparse
import logging
import os
import signal
import subprocess
import socket
import threading
import time
import uuid
import math
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.database import DATA_ROOT, ROOT, SessionLocal
from app.db.models import (Experiment, MaterialAnalysisRun, ScientificObservation,
                           SimulationRun, WorkflowNode, WorkflowRun)
from app.services.material_analysis.service import AnalysisInputError
from app.services.artifacts import artifact_manifest, read_contained_file
from app.services.scientific_data import classify_analysis_source, make_observation
from app.services.simulation.openfoam_runner import run_openfoam
from app.services.simulation.cache import phreeqc_cache_identity, typed_phreeqc_outputs
from app.services.tool_adapters import MaterialAnalysisAdapter, PHREEQCAdapter
from app.services.typed_values import convert_declared_value
from app.services.tool_registry import ResultValidator, ToolRegistry, ValidationGate

log=logging.getLogger("lab-process-rag.worker")
LEASE_SECONDS=30
HEARTBEAT_SECONDS=5
POLL_SECONDS=0.5


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Lease:
    def __init__(self, node_id:int, worker_id:str, generation:int):
        self.node_id=node_id; self.worker_id=worker_id; self.generation=generation
        self.cancelled=threading.Event(); self.lost=threading.Event(); self.stop=threading.Event()
        self.thread=threading.Thread(target=self._heartbeat,name=f"job-heartbeat-{node_id}",daemon=True)

    def _heartbeat(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            db=SessionLocal()
            try:
                node=db.get(WorkflowNode,self.node_id)
                if not node or node.status!="RUNNING" or node.worker_id!=self.worker_id or node.lease_generation!=self.generation:
                    self.lost.set(); return
                workflow=db.get(WorkflowRun,node.workflow_id)
                if node.cancel_requested or (workflow and workflow.cancel_requested): self.cancelled.set()
                now=utcnow()
                changed=db.execute(update(WorkflowNode).where(
                    WorkflowNode.id==self.node_id,WorkflowNode.status=="RUNNING",
                    WorkflowNode.worker_id==self.worker_id,WorkflowNode.lease_generation==self.generation,
                ).values(heartbeat_at=now,lease_expires_at=now+timedelta(seconds=LEASE_SECONDS))).rowcount
                cache_key=(node.input_json or {}).get("_phreeqc_cache_key")
                if cache_key:
                    db.execute(update(SimulationRun).where(SimulationRun.idempotency_key==cache_key,
                        SimulationRun.status=="running",SimulationRun.worker_id==self.worker_id,
                        SimulationRun.lease_generation==self.generation).values(
                            heartbeat_at=now,lease_expires_at=now+timedelta(seconds=LEASE_SECONDS)))
                db.commit()
                if changed!=1: self.lost.set(); return
            except Exception:
                db.rollback(); log.exception("Heartbeat failed for node %s",self.node_id)
            finally: db.close()

    def start(self): self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread.is_alive(): self.thread.join(timeout=2)
    def check(self):
        if self.lost.is_set(): raise RuntimeError("LEASE_LOST")
        if self.cancelled.is_set(): raise JobCancelled("Cancellation requested")


class JobCancelled(Exception):
    pass

class JobTimedOut(TimeoutError):
    pass

def _run_with_limits(seconds:int,lease,operation):
    """Enforce wall time and poll worker cancellation in the standalone worker process."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal,"setitimer"):
        started=time.monotonic(); result=operation(); lease.check()
        if time.monotonic()-started>seconds: raise JobTimedOut(f"Execution exceeded {seconds} seconds")
        return result
    previous=signal.getsignal(signal.SIGALRM)
    deadline=time.monotonic()+seconds
    def interrupt(_signum,_frame):
        lease.check()
        if time.monotonic()>=deadline: raise JobTimedOut(f"Execution exceeded {seconds} seconds")
        signal.setitimer(signal.ITIMER_REAL,min(1.0,max(0.01,deadline-time.monotonic())))
    signal.signal(signal.SIGALRM,interrupt);signal.setitimer(signal.ITIMER_REAL,min(1.0,seconds))
    try:return operation()
    finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)


def _workflow_claim(worker_id:str):
    db=SessionLocal()
    try:
        nodes=db.query(WorkflowNode).filter(WorkflowNode.status=="QUEUED").order_by(WorkflowNode.created_at,WorkflowNode.id).limit(100).all()
        for node in nodes:
            flow=db.get(WorkflowRun,node.workflow_id)
            if not flow or flow.cancel_requested: continue
            dependencies=node.dependency_keys or []
            if dependencies:
                prior=db.query(WorkflowNode).filter(WorkflowNode.workflow_id==node.workflow_id,WorkflowNode.node_key.in_(dependencies)).all()
                statuses={item.node_key:item.status for item in prior}
                if any(statuses.get(key) in {"FAILED","BLOCKED","CANCELLED","TIMED_OUT","REQUIRES_REVIEW"} for key in dependencies):
                    node.status="BLOCKED"; node.error_code="DEPENDENCY_FAILED"; node.error_text="A required predecessor did not complete."; node.finished_at=utcnow()
                    _refresh_workflow(db,node.workflow_id);db.commit();continue
                if any(statuses.get(key)!="COMPLETED" for key in dependencies): continue
            generation=node.lease_generation
            now=utcnow()
            changed=db.execute(update(WorkflowNode).where(
                WorkflowNode.id==node.id,WorkflowNode.status=="QUEUED",WorkflowNode.lease_generation==generation,
            ).values(status="RUNNING",worker_id=worker_id,lease_generation=WorkflowNode.lease_generation+1,
                     attempt=WorkflowNode.attempt+1,started_at=now,heartbeat_at=now,
                     lease_expires_at=now+timedelta(seconds=LEASE_SECONDS),cancel_requested=False)).rowcount
            if changed!=1: db.rollback(); continue
            flow.status="RUNNING"; flow.started_at=flow.started_at or now; db.commit()
            return node.id,worker_id,generation+1
        return None
    except OperationalError:
        db.rollback(); return None
    finally: db.close()


def _refresh_workflow(db,workflow_id:int):
    flow=db.get(WorkflowRun,workflow_id)
    if not flow: return
    nodes=db.query(WorkflowNode).filter_by(workflow_id=workflow_id).all()
    states={item.status for item in nodes}
    if flow.cancel_requested and not states.intersection({"RUNNING","QUEUED"}):
        flow.status="CANCELLED"; flow.finished_at=flow.finished_at or utcnow()
    elif states.intersection({"QUEUED","RUNNING","WAITING_FOR_CACHE"}): flow.status="RUNNING" if states.intersection({"RUNNING","WAITING_FOR_CACHE"}) else "QUEUED"
    elif "REQUIRES_REVIEW" in states:
        flow.status="REQUIRES_REVIEW"; flow.finished_at=flow.finished_at or utcnow()
    elif states.issubset({"COMPLETED"}):
        flow.status="COMPLETED"; flow.finished_at=flow.finished_at or utcnow()
        flow.result_json={"nodes":[{"key":item.node_key,"tool_id":item.tool_id,"status":item.status,
            "result_type":item.result_type,"result_id":item.result_id,"output":item.output_json} for item in nodes]}
    elif "COMPLETED" in states: flow.status="PARTIAL"; flow.finished_at=flow.finished_at or utcnow()
    else: flow.status="FAILED"; flow.finished_at=flow.finished_at or utcnow()


def _simulation_validation(simulation: SimulationRun) -> dict:
    return ((simulation.result_json or {}).get("provenance") or {}).get("validation") or {}


def _link_simulation_to_node(db, node: WorkflowNode, simulation: SimulationRun, *, reused: bool) -> None:
    result=simulation.result_json or {}
    node.status="COMPLETED"; node.result_type="simulation_run"; node.result_id=simulation.id
    node.output_json={"simulation_run_id":simulation.id,"result":result,"validation":_simulation_validation(simulation),
        "source_type":"SIMULATION","typed_outputs":typed_phreeqc_outputs(result,simulation.id,review_status="COMPUTED"),
        "cache_reused":reused,"cache_source_workflow_id":(result.get("provenance") or {}).get("workflow_id"),
        "handoff_provenance":[],"completed_at":utcnow().isoformat()+"Z"}
    node.worker_id=None; node.lease_expires_at=None; node.heartbeat_at=utcnow(); node.finished_at=utcnow()


def refresh_cached_workflow_nodes() -> int:
    """Resolve DAG nodes waiting on an identical direct API/Worker calculation."""
    db=SessionLocal(); changed=0
    try:
        waiting=db.query(WorkflowNode).filter_by(status="WAITING_FOR_CACHE").all()
        for node in waiting:
            key=(node.input_json or {}).get("_phreeqc_cache_key")
            simulation=db.query(SimulationRun).filter_by(idempotency_key=key).first() if key else None
            if simulation is None or simulation.status in {"queued","running"}:
                continue
            if simulation.status=="completed":
                _link_simulation_to_node(db,node,simulation,reused=True)
            elif simulation.status in {"failed","timed_out","cancelled","requires_review","invalid_output"}:
                node.status="REQUIRES_REVIEW" if simulation.status=="requires_review" else "FAILED"
                node.error_code="CACHED_CALCULATION_"+simulation.status.upper()
                node.error_text="The matching PHREEQC calculation did not complete; inspect it and explicitly retry if appropriate."
                node.finished_at=utcnow()
            else:
                continue
            changed+=1; _refresh_workflow(db,node.workflow_id)
        if changed: db.commit()
        return changed
    except Exception:
        db.rollback(); log.exception("Could not refresh PHREEQC cache waiters")
        return 0
    finally: db.close()


def _persist_analysis(db,node,output,run,workflow):
    experiment=db.get(Experiment,workflow.experiment_id)
    params=node.input_json.get("settings",{})
    # Test/reference fixture lineage must survive the Worker analysis hop; do
    # not promote a synthetic source file to a measured observation merely
    # because its parent experiment is a non-demo record in an isolated DB.
    source_is_synthetic = bool(output.result.get("demo_data") or (run.result_json or {}).get("demo_data"))
    source=classify_analysis_source(experiment,demo_data=source_is_synthetic)
    definition=ToolRegistry().get(output.tool_id)
    validation=ResultValidator.validate(definition,output.result)
    if not validation.get("valid"): raise ValueError(f"analysis_output_invalid:{validation.get('reason')}")
    finished=utcnow()
    result={**output.result, **({"demo_data": True} if source_is_synthetic else {}), "analysis_provenance":{"experiment_id":experiment.id,"topic_id":workflow.topic_id,
        "method_version_id":experiment.method_version_id,"process_step_id":run.process_step_id,
        "source_type":source,"original_sha256":run.sha256,"parent_data_ids":[f"uploaded-file-sha256:{run.sha256}",f"experiment:{experiment.id}"],
        "tool_id":output.tool_id,"tool_version":definition.version,"algorithm_version":definition.version,
        "parameters":params,"validation":validation,"review_status":"COMPUTED","worker_id":node.worker_id,
        "finished_at":finished.isoformat()+"Z"}}
    artifact_path=None
    original_path=Path(run.original_path)
    original_bytes=read_contained_file(path=original_path,root=DATA_ROOT/"material-analysis")
    if hashlib.sha256(original_bytes).hexdigest()!=run.sha256: raise ValueError("analysis_original_file_integrity_failed")
    provenance=result["analysis_provenance"]
    provenance["original_artifact"]=artifact_manifest(data=original_bytes,path=original_path,root=DATA_ROOT/"material-analysis",
        artifact_id=f"{run.id}:original",artifact_type="measurement_original",source_run_id=run.id,
        parent_data_ids=provenance["parent_data_ids"],tool_id=output.tool_id,tool_version=definition.version,
        parameters=params,source_type=source,validation_status="INPUT_ACCEPTED",review_status="PENDING")
    if output.artifact and output.artifact_extension:
        artifact_dir=DATA_ROOT/"material-analysis"/"artifacts"; artifact_dir.mkdir(parents=True,exist_ok=True)
        artifact_path=artifact_dir/f"{run.id}.{output.artifact_extension}"; artifact_path.write_bytes(output.artifact)
        provenance["derived_artifact"]=artifact_manifest(data=output.artifact,path=artifact_path,root=DATA_ROOT/"material-analysis",
            artifact_id=f"{run.id}:derived",artifact_type="analysis_visualization",source_run_id=run.id,
            parent_data_ids=[f"{run.id}:original"],tool_id=output.tool_id,tool_version=definition.version,
            parameters=params,source_type="ANALYSIS_OUTPUT",validation_status="VALIDATED",review_status="COMPUTED",
            content_type="image/png" if output.artifact_extension.lower()=="png" else None)
        result["mask_url"]=f"/api/analysis/runs/{run.id}/mask?topic_id={workflow.topic_id}"
    run.tool_id=output.tool_id; run.analysis_status="completed"; run.artifact_path=str(artifact_path) if artifact_path else None; run.result_json=result
    for key,value in output.result.items():
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            step=next((item for item in experiment.steps if item.id==run.process_step_id),None)
            db.add(make_observation(topic_id=workflow.topic_id,experiment_id=experiment.id,method_version_id=experiment.method_version_id,
                process_step_id=run.process_step_id,step_name=step.name if step else "measurement analysis",name=key,value=value,
                unit=None,source_type=source,source_id=f"analysis-run:{run.id}:{key}",analysis_run_id=run.id,review_status="COMPUTED"))
    node.result_type="analysis_run"; node.result_id=run.id
    typed_outputs={}
    def declare(key,value,unit,meaning):
        if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(float(value)):
            typed_outputs[key]={"value":value,"unit":unit,"meaning":meaning,"source_type":source,
                "source_id":f"analysis-run:{run.id}:{key}","validation_status":"NUMERICALLY_VALID",
                "review_status":"COMPUTED","tool_id":output.tool_id,"tool_version":definition.version,
                "parent_data_ids":[f"uploaded-file-sha256:{run.sha256}",f"experiment:{experiment.id}"],
                "uncertainty":None}
    if output.tool_id.startswith("afm."):
        unit=str(output.result.get("height_unit") or "")
        for metric in ("Sa","Sq","Sz"):
            declare(metric,output.result.get(metric),unit,f"AFM leveled surface {metric}; calibration and artifact review still required")
    elif output.tool_id.startswith("xrd."):
        axis_unit=str(output.result.get("x_unit") or "")
        for index,peak in enumerate(output.result.get("observed_peaks",[])):
            declare(f"observed_peaks.{index}.x",peak.get("x"),axis_unit,
                "observed local-maximum coordinate on the declared XRD axis; not a phase identification")
    elif output.tool_id.startswith("microscopy."):
        declare("component_count",output.result.get("component_count"),"count",
            "exploratory threshold-segmentation component count; not a validated particle count")
    node.output_json={"analysis_run_id":run.id,"tool_id":output.tool_id,"validation":validation,"source_type":source,
        "original_sha256":run.sha256,"observed_peak_count":len(output.result.get("observed_peaks",[])),
        "typed_outputs":typed_outputs,"review_status":"COMPUTED"}


def _validate_persisted_simulation_source(db, typed, workflow):
    """Fail closed when a simulation typed value has no matching saved run."""
    parts=str(typed.get("source_id", "")).split(":",2)
    if len(parts)!=3 or parts[0]!="simulation-run" or not parts[1].isdigit(): return False
    simulation=db.get(SimulationRun,int(parts[1]))
    if not simulation or simulation.status!="completed" or simulation.experiment_id!=workflow.experiment_id: return False
    experiment=db.get(Experiment,simulation.experiment_id)
    if not experiment or experiment.topic_id!=workflow.topic_id: return False
    result=simulation.result_json or {}; provenance=result.get("provenance") or {}
    if (typed.get("review_status")!="COMPUTED" or provenance.get("review_status")!="COMPUTED"
            or typed.get("tool_id")!=provenance.get("tool_id")
            or typed.get("tool_version")!=provenance.get("tool_version")
            or typed.get("database_sha256")!=result.get("database_sha256")):
        return False
    suffix=parts[2]; value=None
    if suffix in result: value=result[suffix]
    elif suffix.startswith("si:"):
        phase=suffix[3:]
        row=next((item for item in result.get("saturation_indices",[]) if item.get("phase")==phase),None)
        value=row.get("saturation_index") if row else None
    elif suffix.startswith("species:"):
        species=suffix[8:]
        row=next((item for item in result.get("aqueous_species",[]) if item.get("name")==species),None)
        value=row.get("molality") if row else None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(float(value)):
        return False
    return math.isclose(float(value),float(typed.get("value")),rel_tol=1e-12,abs_tol=1e-15)


def _execute_node(node_id:int,worker_id:str,generation:int,lease:Lease):
    db=SessionLocal()
    try:
        node=db.get(WorkflowNode,node_id)
        if not node or node.worker_id!=worker_id or node.lease_generation!=generation: return
        workflow=db.get(WorkflowRun,node.workflow_id)
        if not workflow: raise ValueError("workflow_missing")
        lease.check()
        output=None; result_type=""; handoff=[]; simulation_run_id=None; cached_simulation=None; simulation_reserved=False
        resolved_inputs=dict(node.input_json or {})
        dependencies={item.node_key:item for item in db.query(WorkflowNode).filter(
            WorkflowNode.workflow_id==node.workflow_id,WorkflowNode.node_key.in_(node.dependency_keys or [])).all()}
        def resolve(value):
            if isinstance(value,dict) and "$ref" in value:
                ref=value["$ref"]; parent=dependencies.get(ref.get("node"))
                typed=(parent.output_json or {}).get("typed_outputs",{}).get(ref.get("path")) if parent else None
                value_number=typed.get("value") if isinstance(typed,dict) else None
                if (not isinstance(typed,dict) or isinstance(value_number,bool)
                        or not isinstance(value_number,(int,float)) or not math.isfinite(float(value_number))
                        or not typed.get("unit") or not ref.get("unit") or typed.get("meaning")!=ref.get("meaning")
                        or typed.get("source_type") not in {"SIMULATION","LAB_RESULT","LAB_RECORD","ANALYSIS_OUTPUT","LITERATURE_ANALYSIS_OUTPUT"}
                        or typed.get("review_status") not in {"COMPUTED","ACCEPTED"}
                        or not typed.get("source_id")
                        or typed.get("validation_status") not in {"NUMERICALLY_VALID","VALIDATED"}):
                    raise ValueError("typed_handoff_missing_or_incompatible")
                if typed.get("source_type")=="SIMULATION" and not _validate_persisted_simulation_source(db,typed,workflow):
                    raise ValueError("typed_handoff_missing_or_incompatible")
                try:
                    delivered_value, delivered_uncertainty = convert_declared_value(
                        value_number, str(typed["unit"]), str(ref["unit"]), typed.get("uncertainty"))
                except (TypeError, ValueError) as exc:
                    raise ValueError("typed_handoff_missing_or_incompatible") from exc
                handoff.append({"from_node":parent.node_key,"path":ref["path"],"source_unit":typed["unit"],
                    "unit":ref["unit"],"meaning":typed["meaning"],"source_type":typed.get("source_type"),
                    "source_id":typed.get("source_id"),"validation_status":typed.get("validation_status"),
                    "value":delivered_value,"uncertainty":delivered_uncertainty})
                return delivered_value
            if isinstance(value,dict): return {key:resolve(item) for key,item in value.items()}
            if isinstance(value,list): return [resolve(item) for item in value]
            return value
        resolved_inputs=resolve(resolved_inputs)
        if node.tool_id=="experiment.data_quality.v1":
            experiment=db.get(Experiment,workflow.experiment_id)
            issues=[]
            for step in experiment.steps:
                for variable in step.variables:
                    if not str(variable.value or "").strip(): issues.append({"step":step.name,"field":variable.name,"issue":"missing_value"})
                    elif not variable.unit: issues.append({"step":step.name,"field":variable.name,"issue":"missing_unit"})
            output={"issue_count":len(issues),"issues":issues,"checked_conditions":sum(len(step.variables) for step in experiment.steps),"source_type":"LAB_RECORD"}
            result_type="validation_report"
        elif node.tool_id.startswith(("xrd.","afm.","microscopy.")):
            analysis=db.get(MaterialAnalysisRun,int(resolved_inputs["analysis_run_id"]))
            if not analysis or analysis.topic_id!=workflow.topic_id or analysis.experiment_id!=workflow.experiment_id: raise ValueError("analysis_source_out_of_scope")
            if analysis.analysis_status=="completed":
                output={"analysis_run_id":analysis.id,"status":"ALREADY_ANALYZED","result":analysis.result_json}; result_type="analysis_run"
                node.result_id=analysis.id; node.result_type=result_type
            else:
                original=Path(analysis.original_path)
                try: original_bytes=read_contained_file(path=original,root=DATA_ROOT/"material-analysis")
                except (OSError,ValueError) as exc: raise ValueError("analysis_original_file_missing_or_out_of_scope") from exc
                if hashlib.sha256(original_bytes).hexdigest()!=analysis.sha256: raise ValueError("analysis_original_file_integrity_failed")
                modality=analysis.modality.lower(); settings=resolved_inputs.get("settings",{})
                if modality=="xrd" and settings.get("xrd_x_unit") not in {"2theta_deg","d_angstrom","q_angstrom^-1"}:
                    raise ValueError("xrd_axis_unit_required")
                if modality in {"sem","tem","afm"} and ("pixel_size_nm" not in settings if modality in {"sem","tem"} else "afm_height_unit" not in settings):
                    raise ValueError("calibration_input_required")
                adapter=MaterialAnalysisAdapter()
                checked=adapter.validate_inputs({"data":original_bytes,"modality":modality,"filename":analysis.filename,**settings})
                prepared=adapter.prepare(checked); lease.check(); output=_run_with_limits(node.timeout_seconds,lease,lambda:adapter.execute(prepared))
                result_type="analysis_run"
        elif node.tool_id.startswith("phreeqc."):
            if not node.approval_confirmed: raise ValueError("explicit_calculation_approval_required")
            adapter=PHREEQCAdapter(sweep=node.tool_id=="phreeqc.aqueous_sweep.v1")
            inputs=adapter.validate_inputs(resolved_inputs.get("inputs",{})); adapter.prepare(inputs)
            gate=ValidationGate.validate({"readiness":"REQUIRES_REVIEW","execution_policy":"review_inputs_before_run"},approval_granted=node.approval_confirmed)
            if not gate["allowed"]: raise ValueError("fresh_execution_gate_failed")
            definition=ToolRegistry().get(node.tool_id)
            step_id=resolved_inputs.get("process_step_id",node.input_json.get("process_step_id"))
            cache_key,cache_spec=phreeqc_cache_identity(tool_id=node.tool_id,tool_version=definition.version,
                topic_id=workflow.topic_id,experiment_id=workflow.experiment_id,process_step_id=step_id,parameters=inputs)
            node_inputs=dict(node.input_json or {}); node_inputs["_phreeqc_cache_key"]=cache_key; node.input_json=node_inputs
            lease.check()
            cached_simulation=db.query(SimulationRun).filter_by(idempotency_key=cache_key).first()
            if cached_simulation and cached_simulation.status=="completed":
                output={"result":cached_simulation.result_json or {},"validation":_simulation_validation(cached_simulation)}
                result_type="simulation"; simulation_run_id=cached_simulation.id
            elif cached_simulation and cached_simulation.status in {"queued","running"}:
                db.commit()
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                current=db.query(WorkflowNode).filter_by(id=node_id,status="RUNNING",worker_id=worker_id,lease_generation=generation).first()
                if current:
                    current.status="WAITING_FOR_CACHE"; current.error_code=""; current.error_text=""; current.worker_id=None
                    current.lease_expires_at=None; current.finished_at=None
                    _refresh_workflow(db,current.workflow_id); db.commit()
                else: db.rollback()
                return
            elif cached_simulation and cached_simulation.status not in {"failed","timed_out","cancelled","invalid_output","requires_review"}:
                raise ValueError(f"unsupported_cached_calculation_state:{cached_simulation.status}")
            elif cached_simulation and not node.input_json.get("_retry_failed_calculation"):
                raise ValueError("matching_phreeqc_attempt_failed; explicit workflow retry is required")
            else:
                now=utcnow()
                if cached_simulation:
                    retry_history=list((cached_simulation.input_json or {}).get("retry_history",[]))
                    retry_history.append({"status":cached_simulation.status,"error":cached_simulation.error_text,
                        "finished_at":cached_simulation.finished_at.isoformat()+"Z" if cached_simulation.finished_at else None})
                    cached_simulation.status="running"; cached_simulation.input_json={**inputs,"idempotency_payload":cache_spec,
                        "retry_history":retry_history,"attempt":cached_simulation.attempt+1}
                    cached_simulation.attempt+=1; cached_simulation.result_json=None; cached_simulation.error_code=""; cached_simulation.error_text=""
                    cached_simulation.log_text="Explicit workflow retry claimed after prior failed attempt."
                else:
                    cached_simulation=SimulationRun(experiment_id=workflow.experiment_id,process_step_id=step_id,
                        model_id=node.tool_id,status="running",idempotency_key=cache_key,
                        input_json={**inputs,"idempotency_payload":cache_spec,"attempt":1},
                        worker_id=worker_id,lease_generation=generation,heartbeat_at=now,
                        lease_expires_at=now+timedelta(seconds=LEASE_SECONDS),timeout_seconds=node.timeout_seconds,
                        attempt=1,max_attempts=3,started_at=now,log_text="Reserved atomically by PHREEQC DAG Worker.")
                    db.add(cached_simulation)
                try:
                    db.flush(); simulation_run_id=cached_simulation.id; simulation_reserved=True; db.commit()
                except IntegrityError:
                    db.rollback()
                    winner=db.query(SimulationRun).filter_by(idempotency_key=cache_key).first()
                    if winner and winner.status=="completed":
                        cached_simulation=winner; simulation_run_id=winner.id
                        output={"result":winner.result_json or {},"validation":_simulation_validation(winner)}; result_type="simulation"
                    elif winner and winner.status in {"queued","running"}:
                        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                        current=db.query(WorkflowNode).filter_by(id=node_id,status="RUNNING",worker_id=worker_id,lease_generation=generation).first()
                        if current:
                            inputs_wait=dict(current.input_json or {}); inputs_wait["_phreeqc_cache_key"]=cache_key
                            current.input_json=inputs_wait; current.status="WAITING_FOR_CACHE"; current.worker_id=None
                            current.lease_expires_at=None; current.finished_at=None; _refresh_workflow(db,current.workflow_id); db.commit()
                        else: db.rollback()
                        return
                    else: raise
                if output is None:
                    lease.check(); output=_run_with_limits(node.timeout_seconds,lease,lambda:adapter.execute(inputs))
                    validation=adapter.validate_outputs(output)
                    if not validation.get("valid"): raise ValueError(f"phreeqc_output_invalid:{validation.get('reason')}")
                    output={"result":output,"validation":validation}; result_type="simulation"
        else: raise ValueError(f"tool_not_supported_by_worker:{node.tool_id}")

        lease.check()
        # Lock before persistence: completion, domain result, and fenced owner
        # check are committed atomically so an expired owner cannot overwrite.
        db.commit()
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        current=db.query(WorkflowNode).filter_by(id=node_id,status="RUNNING",worker_id=worker_id,lease_generation=generation).first()
        if not current: db.rollback(); return
        workflow=db.get(WorkflowRun,current.workflow_id)
        if current.tool_id.startswith(("xrd.","afm.","microscopy.")) and isinstance(output,object) and hasattr(output,"tool_id"):
            analysis=db.get(MaterialAnalysisRun,int(current.input_json["analysis_run_id"]))
            _persist_analysis(db,current,output,analysis,workflow)
        elif current.tool_id.startswith("phreeqc."):
            if simulation_reserved:
                simulation=db.query(SimulationRun).filter_by(id=simulation_run_id,status="running",worker_id=worker_id,lease_generation=generation).first()
                if not simulation: raise RuntimeError("PHREEQC_CACHE_RESERVATION_LOST")
                payload=output["result"]; definition=ToolRegistry().get(current.tool_id); finished=utcnow()
                simulation.result_json={**payload,"provenance":{"source_type":"SIMULATION","tool_id":current.tool_id,
                    "tool_version":definition.version,"algorithm_version":"phreeqc-adapter:2","database_sha256":payload.get("database_sha256"),
                    "topic_id":workflow.topic_id,"experiment_id":workflow.experiment_id,"process_step_id":simulation.process_step_id,
                    "worker_id":worker_id,"workflow_id":workflow.id,"idempotency_key":simulation.idempotency_key,
                    "validation":output["validation"],"review_status":"COMPUTED","source_type":"SIMULATION",
                    "parent_data_ids":[f"experiment:{workflow.experiment_id}"]+([f"process-step:{simulation.process_step_id}"] if simulation.process_step_id else [])}}
                simulation.status="completed"; simulation.worker_id=None; simulation.lease_expires_at=None
                simulation.heartbeat_at=finished; simulation.finished_at=finished; simulation.log_text="Completed by durable workflow worker."
                simulation.error_code=""; simulation.error_text=""
                typed_outputs=typed_phreeqc_outputs(simulation.result_json,simulation.id,review_status="COMPUTED")
                current.result_type="simulation_run"; current.result_id=simulation.id
                current.output_json={"simulation_run_id":simulation.id,"result":payload,"validation":output["validation"],
                    "source_type":"SIMULATION","typed_outputs":typed_outputs,"cache_reused":False,"handoff_provenance":handoff}
                experiment=db.get(Experiment,workflow.experiment_id)
                step=next((item for item in experiment.steps if item.id==simulation.process_step_id),None)
                rows=[("input_pH",payload.get("input_pH"),"pH"),("calculated_pH",payload.get("calculated_pH"),"pH")]
                rows.extend((f"SI({row['phase']})",row.get("saturation_index"),"1") for row in payload.get("saturation_indices",[]) if row.get("phase"))
                for name,value,unit in rows:
                    if isinstance(value,(int,float)) and math.isfinite(float(value)):
                        db.add(make_observation(topic_id=workflow.topic_id,experiment_id=experiment.id,method_version_id=experiment.method_version_id,
                            process_step_id=step.id if step else None,step_name=step.name if step else "aqueous chemistry simulation",name=name,value=value,unit=unit,
                            source_type="SIMULATION",source_id=f"simulation-run:{simulation.id}:{name}",review_status="COMPUTED"))
            else:
                simulation=db.get(SimulationRun,simulation_run_id)
                if not simulation or simulation.status!="completed": raise RuntimeError("cached_PHREEQC_result_disappeared")
                _link_simulation_to_node(db,current,simulation,reused=True)
                current.output_json["handoff_provenance"]=handoff
        elif current.tool_id=="experiment.data_quality.v1":
            current.output_json={**output,"typed_outputs":{},"handoff_provenance":handoff}; current.result_type=result_type
        quality_needs_review=current.tool_id=="experiment.data_quality.v1" and (current.output_json or {}).get("issue_count",0)>0
        current.status="REQUIRES_REVIEW" if quality_needs_review else "COMPLETED"
        current.error_code="DATA_QUALITY_REQUIRES_REVIEW" if quality_needs_review else ""
        current.error_text="Resolve or acknowledge recorded data-quality issues before dependent analysis." if quality_needs_review else ""
        current.worker_id=None; current.lease_expires_at=None; current.heartbeat_at=utcnow(); current.finished_at=utcnow()
        db.flush(); _refresh_workflow(db,current.workflow_id); db.commit()
    except JobCancelled:
        db.rollback(); _finish_node(node_id,worker_id,generation,"CANCELLED","CANCEL_REQUESTED","Worker observed cancellation.")
    except Exception as exc:
        db.rollback()
        code="LEASE_LOST" if str(exc)=="LEASE_LOST" else "WORKFLOW_NODE_FAILED"
        terminal="TIMED_OUT" if isinstance(exc,JobTimedOut) else "FAILED"
        _finish_node(node_id,worker_id,generation,terminal,"EXECUTION_TIMEOUT" if terminal=="TIMED_OUT" else code,str(exc)[:4000])
        log.exception("Workflow node %s failed",node_id)
    finally: db.close()


def _finish_node(node_id,worker_id,generation,status,code,message):
    db=SessionLocal()
    try:
        node=db.query(WorkflowNode).filter_by(id=node_id,status="RUNNING",worker_id=worker_id,lease_generation=generation).first()
        if not node: return
        cache_key=(node.input_json or {}).get("_phreeqc_cache_key")
        if cache_key:
            cached=db.query(SimulationRun).filter_by(idempotency_key=cache_key,status="running",worker_id=worker_id,lease_generation=generation).first()
            if cached:
                cached.status={"CANCELLED":"cancelled","TIMED_OUT":"timed_out"}.get(status,"failed")
                cached.error_code=code; cached.error_text=message; cached.worker_id=None
                cached.lease_expires_at=None; cached.finished_at=utcnow(); cached.log_text="PHREEQC workflow attempt did not complete."
        node.status=status; node.error_code=code; node.error_text=message; node.worker_id=None; node.lease_expires_at=None; node.finished_at=utcnow()
        db.flush(); _refresh_workflow(db,node.workflow_id); db.commit()
    finally: db.close()


def _claim_simulation(worker_id):
    db=SessionLocal()
    try:
        items=db.query(SimulationRun).filter_by(status="queued").order_by(SimulationRun.created_at,SimulationRun.id).limit(20).all()
        for item in items:
            if item.model_id.startswith("openfoam.") and not (item.input_json or {}).get("explicit_approval"): continue
            if item.model_id.startswith("openfoam.") and db.query(SimulationRun).filter(SimulationRun.model_id.like("openfoam.%"),SimulationRun.status=="running").count(): continue
            old_generation=item.lease_generation; now=utcnow()
            changed=db.execute(update(SimulationRun).where(SimulationRun.id==item.id,SimulationRun.status=="queued",SimulationRun.lease_generation==old_generation)
                .values(status="running",worker_id=worker_id,lease_generation=SimulationRun.lease_generation+1,attempt=SimulationRun.attempt+1,
                    started_at=now,heartbeat_at=now,lease_expires_at=now+timedelta(seconds=LEASE_SECONDS),cancel_requested=False)).rowcount
            if changed!=1: db.rollback(); continue
            db.commit(); return item.id,worker_id,old_generation+1
        return None
    except OperationalError: db.rollback(); return None
    finally: db.close()


class SimulationLease:
    def __init__(self,run_id,worker_id,generation):
        self.run_id=run_id; self.worker_id=worker_id; self.generation=generation; self.stop=threading.Event(); self.cancelled=threading.Event(); self.lost=threading.Event()
        self.thread=threading.Thread(target=self._pulse,daemon=True,name=f"simulation-heartbeat-{run_id}")
    def _pulse(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            db=SessionLocal()
            try:
                item=db.get(SimulationRun,self.run_id)
                if not item or item.worker_id!=self.worker_id or item.lease_generation!=self.generation or item.status!="running": self.lost.set(); return
                if item.cancel_requested: self.cancelled.set()
                now=utcnow(); n=db.execute(update(SimulationRun).where(SimulationRun.id==self.run_id,SimulationRun.worker_id==self.worker_id,
                    SimulationRun.lease_generation==self.generation,SimulationRun.status=="running").values(heartbeat_at=now,lease_expires_at=now+timedelta(seconds=LEASE_SECONDS))).rowcount
                db.commit()
                if n!=1:self.lost.set();return
            except Exception: db.rollback(); log.exception("simulation heartbeat failed")
            finally:db.close()
    def check(self):
        if self.lost.is_set(): raise RuntimeError("LEASE_LOST")
        if self.cancelled.is_set(): raise JobCancelled("Cancellation requested")
    def start(self):self.thread.start()
    def close(self):self.stop.set();self.thread.join(timeout=2) if self.thread.is_alive() else None


def _execute_simulation(run_id,worker_id,generation):
    db=SessionLocal(); lease=SimulationLease(run_id,worker_id,generation); lease.start()
    try:
        run=db.get(SimulationRun,run_id); config=dict(run.input_json or {})
        if run.model_id.startswith("openfoam."):
            from app.services.simulation.openfoam_runner import run_openfoam
            result,log_text=run_openfoam(config,should_cancel=lease.cancelled.is_set)
            marker=result.get("solver_completed_marker")
            tool=ToolRegistry().get(run.model_id); validation=ResultValidator.validate(tool,result) if tool else {"valid":False,"reason":"tool_not_registered"}
            if not validation["valid"]: raise ValueError(f"openfoam_output_invalid:{validation['reason']}")
            output={**result,"provenance":{"source_type":"SIMULATION","tool_id":run.model_id,"tool_version":"14","input":config,"validation":validation,"worker_id":worker_id,"lease_generation":generation}}
        else:
            tool=ToolRegistry().get(run.model_id)
            if not tool or not run.model_id.startswith("phreeqc."): raise ValueError("worker_tool_not_supported")
            lease.check(); adapter=PHREEQCAdapter(sweep=run.model_id=="phreeqc.aqueous_sweep.v1")
            inputs=adapter.validate_inputs({key:value for key,value in config.items() if key not in {"approval_confirmed","explicit_approval","timeout_seconds"}}); gate=ValidationGate.validate({"readiness":"REQUIRES_REVIEW","execution_policy":"review_inputs_before_run"},approval_granted=bool(config.get("approval_confirmed")))
            if not gate["allowed"]: raise ValueError("explicit_calculation_approval_required")
            output=_run_with_limits(int(run.timeout_seconds or 300),lease,lambda:adapter.execute(inputs)); validation=adapter.validate_outputs(output)
            if not validation["valid"]: raise ValueError(f"phreeqc_output_invalid:{validation['reason']}")
            log_text="PHREEQC worker calculation passed output validation."
            output={**output,"provenance":{"source_type":"SIMULATION","tool_id":run.model_id,"tool_version":tool.version,"input":inputs,"validation":validation,"worker_id":worker_id,"lease_generation":generation}}
        lease.check()
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        current=db.query(SimulationRun).filter_by(id=run_id,status="running",worker_id=worker_id,lease_generation=generation).first()
        if not current: db.rollback(); return
        current.result_json=output; current.status="completed"; current.worker_id=None; current.lease_expires_at=None; current.heartbeat_at=utcnow(); current.finished_at=utcnow(); current.error_code=""; current.error_text=""; current.log_text=log_text
        db.commit()
    except JobCancelled as exc: _finish_simulation(run_id,worker_id,generation,"cancelled","CANCEL_REQUESTED",str(exc))
    except Exception as exc:
        status="timed_out" if isinstance(exc,(subprocess.TimeoutExpired,JobTimedOut)) else "failed"
        _finish_simulation(run_id,worker_id,generation,status,"SIMULATION_WORKER_FAILED",str(exc)[:4000]); log.exception("Simulation %s failed",run_id)
    finally:lease.close();db.close()


def _finish_simulation(run_id,worker_id,generation,status,code,message):
    db=SessionLocal()
    try:
        item=db.query(SimulationRun).filter_by(id=run_id,status="running",worker_id=worker_id,lease_generation=generation).first()
        if not item:return
        item.status=status;item.error_code=code;item.error_text=message;item.worker_id=None;item.lease_expires_at=None;item.finished_at=utcnow();db.commit()
    finally:db.close()


def recover_expired_leases():
    """Never auto-repeat an expired external run; require review before retry."""
    now=utcnow(); db=SessionLocal()
    try:
        nodes=db.query(WorkflowNode).filter(WorkflowNode.status=="RUNNING",WorkflowNode.lease_expires_at<=now).all()
        for node in nodes:
            node.status="REQUIRES_REVIEW";node.error_code="LEASE_EXPIRED";node.error_text="Worker lease expired; inspect external process/result before retry.";node.worker_id=None;node.finished_at=now
            _refresh_workflow(db,node.workflow_id)
        runs=db.query(SimulationRun).filter(SimulationRun.status=="running",SimulationRun.lease_expires_at<=now).all()
        for run in runs:
            run.status="requires_review";run.error_code="LEASE_EXPIRED";run.error_text="Worker lease expired; inspect VM/external process before retry.";run.worker_id=None;run.finished_at=now
        if nodes or runs: db.commit()
    finally:db.close()


def run_once(worker_id:str|None=None) -> bool:
    refresh_cached_workflow_nodes()
    worker_id=worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    claimed=_workflow_claim(worker_id)
    if claimed:
        node_id,owner,generation=claimed; lease=Lease(node_id,owner,generation); lease.start()
        try:_execute_node(node_id,owner,generation,lease)
        finally:lease.close()
        return True
    simulation=_claim_simulation(worker_id)
    if simulation:
        _execute_simulation(*simulation); return True
    return False


def run_forever(stop_event:threading.Event|None=None,poll_seconds:float=POLL_SECONDS):
    stop_event=stop_event or threading.Event()
    last_recovery=0.0
    while not stop_event.is_set():
        if time.monotonic()-last_recovery>=10:
            recover_expired_leases();last_recovery=time.monotonic()
        if not run_once(): stop_event.wait(poll_seconds)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Durable Lab Process RAG scientific worker")
    parser.add_argument("--once",action="store_true",help="claim and execute at most one queued node/job, then exit")
    args=parser.parse_args(argv)
    logging.basicConfig(level=os.getenv("LAB_WORKER_LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.once:
        return 0 if run_once() else 1
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    log.info("Scientific worker started; PID=%s",os.getpid())
    run_forever(stop)
    return 0


if __name__=="__main__": main()
