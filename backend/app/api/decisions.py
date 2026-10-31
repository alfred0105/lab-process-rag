"""Learned decision head APIs. All outputs are shadow recommendations only."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (DecisionActiveShadowModel, DecisionCase, DecisionDatasetVersion,
    DecisionFeedback, DecisionModelActivationEvent, DecisionModelComparison, DecisionModelRun,
    DecisionSnapshot, Experiment, MaterialAnalysisRun, OptimizationModelRun, ResearchTopic,
    ScientificObservation, SimulationRun)
from app.services.decision_head import (ACTIONS, DATASET_VERSION, FEATURES, FEATURE_SCHEMA_VERSION,
    MODEL_VERSION, DecisionInputError, LearnedDecisionHead, calibration_metrics, dataset_digest,
    encode_state, infer_safe, majority_metrics, rule_metrics, split_by_group, state_from_experiment,
    synthetic_cases)
from app.services.tool_registry import RuleBasedDecisionPolicy, recommend_tools

router=APIRouter(prefix="/decisions/learned",tags=["learned-decision"])


class CaseIn(BaseModel):
    topic_id:int=Field(gt=0)
    experiment_id:int|None=Field(default=None,gt=0)
    case_group_id:str|None=Field(default=None,max_length=200)
    scientific_state:dict[str,Any]|None=None
    selected_action:Literal["REQUEST_INFORMATION","ANALYZE","SIMULATE","OPTIMIZE","REQUEST_REVIEW","ABSTAIN"]
    label_source:Literal["HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"]
    reviewer:str=Field(min_length=2,max_length=200)
    opinion:str=Field(default="",max_length=2000)


class TrainIn(BaseModel):
    topic_id:int=Field(gt=0)
    mode:Literal["research","sandbox"]="sandbox"
    seed:int=7


class PredictIn(BaseModel):
    topic_id:int=Field(gt=0)
    case_id:int|None=Field(default=None,gt=0)
    snapshot_id:str|None=None
    experiment_id:int|None=Field(default=None,gt=0)
    scientific_state:dict[str,Any]|None=None


class CompareIn(PredictIn):
    model_id:int=Field(gt=0)


class FeedbackIn(BaseModel):
    snapshot_id:str
    model_id:int=Field(gt=0)
    feedback_type:Literal["ACCEPT","CORRECT","REJECT","UNSURE"]
    final_reviewed_action:Literal["REQUEST_INFORMATION","ANALYZE","SIMULATE","OPTIMIZE","REQUEST_REVIEW","ABSTAIN"]|None=None
    reviewer:str=Field(min_length=2,max_length=200)
    review_reason:str=Field(default="",max_length=3000)


class DatasetBuildIn(BaseModel):
    topic_id:int=Field(gt=0)
    mode:Literal["research","sandbox"]


class RetrainIn(BaseModel):
    dataset_version_id:int=Field(gt=0)
    parent_model_id:int|None=Field(default=None,gt=0)
    seed:int=7


class ModelCompareIn(BaseModel):
    topic_id:int=Field(gt=0)
    champion_model_id:int=Field(gt=0)
    challenger_model_id:int=Field(gt=0)


class ActivationIn(BaseModel):
    topic_id:int=Field(gt=0)
    model_id:int=Field(gt=0)
    comparison_id:int|None=Field(default=None,gt=0)
    reviewer:str=Field(min_length=2,max_length=200)
    reason:str=Field(default="",max_length=3000)


class RollbackIn(BaseModel):
    topic_id:int=Field(gt=0)
    mode:Literal["research","sandbox"]
    reviewer:str=Field(min_length=2,max_length=200)
    reason:str=Field(default="",max_length=3000)


def _topic(db,topic_id):
    if not db.get(ResearchTopic,topic_id): raise HTTPException(404,"Research topic not found")


def _state(db,topic_id,experiment_id,state):
    if experiment_id is not None:
        experiment=db.get(Experiment,experiment_id)
        if not experiment or experiment.topic_id!=topic_id or experiment.demo:
            raise HTTPException(422,detail={"code":"EXPERIMENT_TOPIC_MISMATCH","message":"Select a non-demo experiment from this research topic."})
        observations=db.query(ScientificObservation).filter(ScientificObservation.experiment_id==experiment_id).all()
        analysis=db.query(MaterialAnalysisRun).filter(MaterialAnalysisRun.experiment_id==experiment_id).all()
        simulation=db.query(SimulationRun).filter(SimulationRun.experiment_id==experiment_id).all()
        optimization=db.query(OptimizationModelRun).filter(OptimizationModelRun.topic_id==topic_id).order_by(OptimizationModelRun.created_at).all()
        record={"id":experiment.id,"topic_id":experiment.topic_id,"method_version_id":experiment.method_version_id,
            "demo":experiment.demo,"status":experiment.status,"materials":[],
            "steps":[{"name":step.name,"order_index":step.order_index,"variables":[{"name":variable.name,"value":variable.value,
                "unit":variable.unit,"material":variable.material} for variable in step.variables]} for step in experiment.steps],
            "results":[{"key":result.key,"value":result.value,"unit":result.unit} for result in experiment.results]}
        analysis_context=[{"id":row.id,"modality":row.modality,"tool_id":row.tool_id,"analysis_status":row.analysis_status,
            "sha256":row.sha256,"result":row.result_json or {}} for row in analysis]
        registered=recommend_tools(record,analysis_context)["recommendations"]
        return state_from_experiment(experiment,observations,analysis,simulation,optimization,registered)
    if state is None: raise HTTPException(422,detail={"code":"SCIENTIFIC_STATE_REQUIRED","message":"Provide an experiment or ScientificState snapshot."})
    if state.get("topic_id") not in (None,topic_id): raise HTTPException(422,"ScientificState belongs to another topic")
    return dict(state,topic_id=topic_id)


def _model_mode(row):
    return str(row.mode).upper()


def _snapshot_sources(db,experiment_id,topic_id):
    if not experiment_id: return {"observation_ids":[],"analysis_ids":[],"simulation_ids":[],"optimization_model_ids":[]}
    return {
        "observation_ids":[x.id for x in db.query(ScientificObservation).filter_by(experiment_id=experiment_id).order_by(ScientificObservation.id).all()],
        "analysis_ids":[x.id for x in db.query(MaterialAnalysisRun).filter_by(experiment_id=experiment_id).order_by(MaterialAnalysisRun.id).all()],
        "simulation_ids":[x.id for x in db.query(SimulationRun).filter_by(experiment_id=experiment_id).order_by(SimulationRun.id).all()],
        "optimization_model_ids":[x.id for x in db.query(OptimizationModelRun).filter_by(topic_id=topic_id).order_by(OptimizationModelRun.id).all()],
    }


def _save_snapshot(db,topic_id,mode,state,model,result,*,experiment_id=None,source_case=None,existing=None):
    if existing:
        if existing.topic_id!=topic_id or existing.mode!=mode:
            raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Snapshot and model dataset modes must match."})
        if model and existing.model_run_id not in (None,model.id):
            raise HTTPException(409,detail={"code":"SNAPSHOT_MODEL_MISMATCH","message":"This snapshot belongs to a different model recommendation."})
        return existing
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    sources=_snapshot_sources(db,experiment_id,topic_id)
    if source_case:
        sources.update(source_case_id=source_case.id,case_group_id=source_case.case_group_id)
    feature_vector=encode_state(state).tolist()
    provenance={"dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE" if mode=="SANDBOX" else "RESEARCH_STATE_SNAPSHOT",
        "source_case_id":source_case.id if source_case else state.get("decision_source_case_id"),
        "case_group_id":source_case.case_group_id if source_case else state.get("decision_case_group_id"),
        "historical_time_reconstruction":"NOT_AVAILABLE","future_state_reconstructed":False}
    body={"topic_id":topic_id,"experiment_id":experiment_id,"mode":mode,"decision_timestamp":now.isoformat(),
        "state":state,"features":feature_vector,"feature_schema_version":FEATURE_SCHEMA_VERSION,"sources":sources,
        "model_id":model.id if model else None,"action":result["raw_predicted_action"],"probabilities":result.get("action_probabilities",{}),"ood_status":result.get("ood_status","UNKNOWN")}
    row=DecisionSnapshot(id=str(uuid.uuid4()),topic_id=topic_id,experiment_id=experiment_id,
        method_version_id=state.get("method_version_id"),model_run_id=model.id if model else None,mode=mode,
        decision_timestamp=now,snapshot_timestamp=now,data_availability_timestamp=now,state_json=state,
        feature_vector_json=feature_vector,suggested_action=result["raw_predicted_action"],
        probabilities_json=result.get("action_probabilities",{}),ood_status=result.get("ood_status","UNKNOWN"),
        feature_schema_version=FEATURE_SCHEMA_VERSION,source_observation_ids_json=sources["observation_ids"],
        source_analysis_ids_json=sources["analysis_ids"],source_simulation_ids_json=sources["simulation_ids"],
        source_optimization_model_ids_json=sources["optimization_model_ids"],provenance_json=provenance,
        snapshot_hash=dataset_digest(body),created_at=now)
    db.add(row);db.flush()
    return row


def _resolve_model_state(db,payload,row):
    mode=_model_mode(row)
    if payload.snapshot_id:
        snapshot=db.get(DecisionSnapshot,payload.snapshot_id)
        if not snapshot or snapshot.topic_id!=payload.topic_id:
            raise HTTPException(404,detail={"code":"DECISION_SNAPSHOT_NOT_FOUND","message":"Decision snapshot not found for this topic."})
        if snapshot.mode!=mode:
            raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Model and snapshot dataset modes differ."})
        if snapshot.model_run_id not in (None,row.id):
            raise HTTPException(409,detail={"code":"SNAPSHOT_MODEL_MISMATCH","message":"Snapshot was created for another model recommendation."})
        return snapshot.state_json,snapshot.experiment_id,snapshot if snapshot.model_run_id==row.id else None
    if payload.case_id is not None:
        case=db.get(DecisionCase,payload.case_id)
        if not case or case.topic_id!=payload.topic_id:
            raise HTTPException(404,detail={"code":"DECISION_CASE_NOT_FOUND","message":"Decision case not found for this topic."})
        expected="SYNTHETIC_SANDBOX" if mode=="SANDBOX" else None
        if mode=="SANDBOX" and (case.label_source!=expected or case.review_status!="SYNTHETIC_ONLY"):
            raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Sandbox models accept only stored synthetic cases."})
        if mode=="RESEARCH" and (case.label_source not in {"HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"} or case.review_status!="ACCEPTED" or not case.snapshot_id):
            raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Research models require a reviewed research case with a decision-time snapshot."})
        snapshot=db.get(DecisionSnapshot,case.snapshot_id) if case.snapshot_id else None
        if mode=="RESEARCH" and (not snapshot or snapshot.mode!="RESEARCH"):
            raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Research case is missing a compatible snapshot."})
        if snapshot:
            state=dict(snapshot.state_json)
            state["decision_source_case_id"]=case.id
            state["decision_case_group_id"]=case.case_group_id
            return state,case.experiment_id,snapshot if snapshot.model_run_id==row.id else None
        state=dict(case.state_json)
        state["decision_source_case_id"]=case.id
        state["decision_case_group_id"]=case.case_group_id
        return state,None,None
    if mode=="SANDBOX":
        raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Sandbox models require a stored synthetic case or sandbox snapshot; experiment records are not accepted."})
    if payload.experiment_id is not None:
        return _state(db,payload.topic_id,payload.experiment_id,None),payload.experiment_id,None
    raise HTTPException(409,detail={"code":"RESEARCH_DECISION_MODEL_UNAVAILABLE","message":"Research decisions require a non-demo experiment or a research snapshot."})


def _snapshot_out(row):
    return {"snapshot_id":row.id,"topic_id":row.topic_id,"experiment_id":row.experiment_id,"method_version_id":row.method_version_id,
        "model_id":row.model_run_id,"mode":row.mode,"decision_timestamp":row.decision_timestamp.isoformat()+"Z",
        "snapshot_timestamp":row.snapshot_timestamp.isoformat()+"Z","data_availability_timestamp":row.data_availability_timestamp.isoformat()+"Z",
        "feature_schema_version":row.feature_schema_version,"feature_vector":row.feature_vector_json,"snapshot_hash":row.snapshot_hash,
        "source_observation_ids":row.source_observation_ids_json,"source_analysis_ids":row.source_analysis_ids_json,
        "source_simulation_ids":row.source_simulation_ids_json,"source_optimization_model_ids":row.source_optimization_model_ids_json,
        "provenance":row.provenance_json,"suggested_action":row.suggested_action,"action_probabilities":row.probabilities_json,"ood_status":row.ood_status}


def _model_out(row):
    return {"model_id":row.id,"topic_id":row.topic_id,"mode":row.mode,"status":row.status,"model_version":row.model_version,
        "feature_schema_version":row.feature_schema_version,"dataset_version":row.dataset_version,"dataset_hash":row.dataset_hash,
        "dataset_type":row.provenance_json.get("dataset_type","UNKNOWN"),
        "metrics":row.metrics_json,"provenance":row.provenance_json,"created_at":row.created_at.isoformat()+"Z"}


@router.get("/training-readiness")
def training_readiness(topic_id:int,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    rows=db.query(DecisionCase).filter(DecisionCase.topic_id==topic_id).all()
    feedback_rows=db.query(DecisionFeedback).filter_by(topic_id=topic_id).order_by(DecisionFeedback.snapshot_id,DecisionFeedback.model_run_id,DecisionFeedback.revision.desc()).all()
    latest={}
    for feedback in feedback_rows:latest.setdefault((feedback.snapshot_id,feedback.model_run_id),feedback)
    latest_eligible={row.id for row in latest.values() if row.feedback_type in {"ACCEPT","CORRECT","REJECT"} and row.final_reviewed_action}
    human=[row for row in rows if row.label_source in {"HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"} and row.review_status=="ACCEPTED" and (row.feedback_id is None or row.feedback_id in latest_eligible) and row.snapshot_id]
    groups=len({row.case_group_id for row in human}); classes=sorted({row.selected_action for row in human})
    action_groups={action:len({row.case_group_id for row in human if row.selected_action==action}) for action in classes}
    ready=groups>=20 and len(classes)>=2 and all(count>=2 for count in action_groups.values())
    return {"topic_id":topic_id,"decision_case_count":len(rows),"feedback_revision_count":len(feedback_rows),
        "latest_feedback_count":len(latest),"eligible_feedback_count":sum(item.id in latest_eligible for item in latest.values()),
        "research":{"status":"READY" if ready else "INSUFFICIENT_REVIEWED_DECISIONS","reviewed_case_count":len(human),"independent_group_count":groups,"action_classes":classes,"action_group_counts":action_groups,"minimum_groups":20},
        "sandbox":{"status":"READY" if any(row.label_source=="SYNTHETIC_SANDBOX" for row in rows) else "NOT_SEEDED","case_count":sum(row.label_source=="SYNTHETIC_SANDBOX" for row in rows)},
        "dataset_version":DATASET_VERSION,"feature_schema_version":FEATURE_SCHEMA_VERSION}


@router.post("/cases")
def create_case(payload:CaseIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id)
    state=_state(db,payload.topic_id,payload.experiment_id,payload.scientific_state)
    try: features=encode_state(state).tolist()
    except DecisionInputError as exc: raise HTTPException(422,str(exc)) from exc
    snapshot=_save_snapshot(db,payload.topic_id,"RESEARCH",state,None,{"raw_predicted_action":payload.selected_action},experiment_id=payload.experiment_id)
    group=f"experiment-{payload.experiment_id}" if payload.experiment_id else payload.case_group_id or f"case-{uuid.uuid4()}"
    row=DecisionCase(topic_id=payload.topic_id,experiment_id=payload.experiment_id,snapshot_id=snapshot.id,case_group_id=group,state_json=state,
        features_json={"vector":features,"feature_names":list(FEATURES)},feature_schema_version=FEATURE_SCHEMA_VERSION,
        candidate_actions_json=list(ACTIONS),selected_action=payload.selected_action,label_source=payload.label_source,reviewer=payload.reviewer.strip(),review_status="ACCEPTED",
        provenance_json={"label_source":payload.label_source,"reviewer":payload.reviewer.strip(),"reviewer_identity_status":"SELF_REPORTED_NOT_AUTHENTICATED","opinion":payload.opinion.strip(),"decision_timestamp":snapshot.decision_timestamp.isoformat(),"feature_extraction_timestamp":snapshot.snapshot_timestamp.isoformat(),"snapshot_id":snapshot.id},dataset_version=DATASET_VERSION,created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row);db.commit();db.refresh(row)
    return {"case_id":row.id,"snapshot_id":snapshot.id,"snapshot_hash":snapshot.snapshot_hash,"topic_id":row.topic_id,"label_source":row.label_source,"review_status":row.review_status,"case_group_id":row.case_group_id,"feature_schema_version":row.feature_schema_version}


@router.post("/sandbox/seed")
def seed_sandbox(topic_id:int,seed:int=7,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    made=0
    for item in synthetic_cases(seed=seed,per_action=24):
        if db.query(DecisionCase).filter_by(topic_id=topic_id,case_group_id=item["case_group_id"]).first(): continue
        state=dict(item["state"],topic_id=topic_id)
        db.add(DecisionCase(topic_id=topic_id,case_group_id=item["case_group_id"],state_json=state,
            features_json={"vector":encode_state(state).tolist(),"feature_names":list(FEATURES)},feature_schema_version=FEATURE_SCHEMA_VERSION,candidate_actions_json=list(ACTIONS),
            selected_action=item["action"],label_source="SYNTHETIC_SANDBOX",reviewer=None,review_status="SYNTHETIC_ONLY",
            provenance_json={"dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE","seed":seed,"scenario_group":item["case_group_id"],"not_expert_truth":True},dataset_version=DATASET_VERSION,created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        made+=1
    db.commit()
    return {"topic_id":topic_id,"created":made,"total_synthetic_cases":db.query(DecisionCase).filter_by(topic_id=topic_id,label_source="SYNTHETIC_SANDBOX").count(),
        "dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE","notice":"Synthetic labels test software behavior only; they are not expert or research decisions."}


@router.post("/train")
def train(payload:TrainIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id)
    rows=db.query(DecisionCase).filter(DecisionCase.topic_id==payload.topic_id).all()
    if payload.mode=="sandbox": rows=[row for row in rows if row.label_source=="SYNTHETIC_SANDBOX" and row.review_status=="SYNTHETIC_ONLY"]
    else: rows=[row for row in rows if row.label_source in {"HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"} and row.review_status=="ACCEPTED"]
    groups={row.case_group_id for row in rows}; labels=[row.selected_action for row in rows]
    min_groups=24 if payload.mode=="sandbox" else 20
    action_groups={action:len({row.case_group_id for row in rows if row.selected_action==action}) for action in set(labels)}
    if len(groups)<min_groups or len(set(labels))<2 or any(count<2 for count in action_groups.values()):
        code="INSUFFICIENT_REVIEWED_DECISIONS" if payload.mode=="research" else "INSUFFICIENT_SANDBOX_CASES"
        raise HTTPException(409,detail={"code":code,"message":f"At least {min_groups} independent {payload.mode} cases and two action classes are required."})
    states=[row.state_json for row in rows]
    try:
        x=np.vstack([encode_state(state) for state in states]); train_ix,valid_ix=split_by_group(labels,[row.case_group_id for row in rows],seed=payload.seed,fraction=.25)
        fit_sub,cal_sub=split_by_group([labels[i] for i in train_ix],[rows[i].case_group_id for i in train_ix],seed=payload.seed+1,fraction=.2)
        fit_ix=train_ix[fit_sub];cal_ix=train_ix[cal_sub]
        model,losses=LearnedDecisionHead.fit(x[fit_ix], [labels[i] for i in fit_ix],seed=payload.seed)
        calibrated=model.calibrate(x[cal_ix],[labels[i] for i in cal_ix])
        test_prob=model.predict_proba(x[valid_ix]); eval_metrics=calibration_metrics([labels[i] for i in valid_ix],test_prob)
        predictions=[ACTIONS[index] for index in test_prob.argmax(axis=1)]
        eval_metrics["model_size_bytes"]=len(json.dumps(model.to_dict(),separators=(",",":" )).encode())
        eval_metrics["training_loss_start"]=losses[0];eval_metrics["training_loss_end"]=losses[-1];eval_metrics["training_loss_decreased"]=losses[-1]<losses[0]
        eval_metrics["calibration_status"]="TEMPERATURE_SCALED_ON_HELD_OUT_CALIBRATION_GROUPS" if calibrated else "INSUFFICIENT_CALIBRATION_DATA"
        eval_metrics["calibration_groups"]=len({rows[i].case_group_id for i in cal_ix})
        eval_metrics["validation_group_count"]=len({rows[i].case_group_id for i in valid_ix})
        eval_metrics["majority_baseline"]=majority_metrics([labels[i] for i in fit_ix],[labels[i] for i in valid_ix])
        eval_metrics["rule_baseline"]=rule_metrics([states[i] for i in valid_ix],[labels[i] for i in valid_ix])
        eval_metrics["inference_latency_ms"]=_measure_latency(model,x[valid_ix])
        eval_metrics["action_probabilities_are_success_probabilities"]=False
        cm=np.asarray(eval_metrics["confusion_matrix"]["counts"])
        eval_metrics["action_count"]={action:int(np.sum(cm[ACTIONS.index(action)])) for action in ACTIONS}
        digest=dataset_digest([{"case_group_id":row.case_group_id,"features":row.features_json,"action":row.selected_action,"source":row.label_source,"review_status":row.review_status} for row in rows])
        provenance={"dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE" if payload.mode=="sandbox" else "HUMAN_REVIEWED_DECISIONS",
            "case_ids":[row.id for row in rows],"label_sources":sorted({row.label_source for row in rows}),"review_statuses":sorted({row.review_status for row in rows}),
            "group_split":"stratified_by_case_group","training_case_ids":[rows[i].id for i in fit_ix],"calibration_case_ids":[rows[i].id for i in cal_ix],"validation_case_ids":[rows[i].id for i in valid_ix],
            "no_pseudo_labels":True,"shadow_mode_only":True}
        run=DecisionModelRun(topic_id=payload.topic_id,mode=payload.mode,status="COMPLETED",dataset_hash=digest,model_version=MODEL_VERSION,
            feature_schema_version=FEATURE_SCHEMA_VERSION,dataset_version=DATASET_VERSION,model_json=model.to_dict(),metrics_json=eval_metrics,provenance_json=provenance,created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(run);db.commit();db.refresh(run)
        return _model_out(run)
    except (DecisionInputError,ValueError,np.linalg.LinAlgError) as exc:
        db.rollback();raise HTTPException(422,detail={"code":"DECISION_TRAINING_INVALID","message":str(exc)}) from exc


def _measure_latency(model,x):
    if not len(x): return 0.0
    sample=x[:1]; start=time.perf_counter()
    for _ in range(100): model.predict_proba(sample)
    return (time.perf_counter()-start)*10.0


@router.get("/models/{model_id}")
def get_model(model_id:int,topic_id:int,db:Session=Depends(get_db)):
    row=db.get(DecisionModelRun,model_id)
    if not row or row.topic_id!=topic_id: raise HTTPException(404,"Decision model not found")
    return _model_out(row)


def _latest(db,topic_id,mode=None):
    query=db.query(DecisionModelRun).filter_by(topic_id=topic_id,status="COMPLETED")
    if mode:query=query.filter_by(mode=mode)
    return query.order_by(DecisionModelRun.created_at.desc(),DecisionModelRun.id.desc()).first()


def _rule_result(state):
    recs=[]
    if state.get("optimization_ready"):
        goal="optimize experiment conditions"
    elif state.get("pending_review_count",0)>0:
        recs.append({"tool_id":"xrd.local_peaks.v1","category":"analysis","readiness":"REQUIRES_REVIEW"});goal="xrd peaks"
    elif state.get("simulation_tool_available"):
        recs.append({"tool_id":"phreeqc.aqueous_equilibrium.v1","category":"simulation","readiness":"READY"});goal="aqueous equilibrium"
    elif state.get("analysis_tool_available"):
        recs.append({"tool_id":"xrd.local_peaks.v1","category":"analysis","readiness":"READY"});goal="xrd peaks"
    elif state.get("missing_required_information_count",0)>0:
        recs.append({"tool_id":"xrd.local_peaks.v1","category":"analysis","readiness":"MISSING_INPUT"});goal="xrd peaks"
    else: goal="unsupported goal"
    raw=RuleBasedDecisionPolicy().choose(state,recs,goal)
    action={"RUN_ANALYSIS":"ANALYZE","RUN_SIMULATION":"SIMULATE","RUN_OPTIMIZATION":"OPTIMIZE","REQUEST_DATA":"REQUEST_INFORMATION","REVIEW_RESULT":"REQUEST_REVIEW","ABSTAIN":"ABSTAIN"}.get(raw.get("action"),"ABSTAIN")
    return {"action":action,"reason":raw.get("reason"),"tool_id":raw.get("tool_id"),"workflow_triggered":False,"policy":"RuleBasedDecisionPolicy"}


@router.post("/models/{model_id}/predict")
def predict(model_id:int,payload:PredictIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id);row=db.get(DecisionModelRun,model_id)
    if not row or row.topic_id!=payload.topic_id: raise HTTPException(404,"Decision model not found")
    try:
        state,experiment_id,snapshot=_resolve_model_state(db,payload,row)
        model=LearnedDecisionHead.from_dict(row.model_json);result=infer_safe(model,state)
        snapshot=_save_snapshot(db,payload.topic_id,_model_mode(row),state,row,result,experiment_id=experiment_id,existing=snapshot)
        db.commit()
        result.update({"model_id":row.id,"model_mode":_model_mode(row),"dataset_type":row.provenance_json.get("dataset_type"),
            "model_version":row.model_version,"feature_schema_version":row.feature_schema_version,"dataset_hash":row.dataset_hash,
            "decision_snapshot":_snapshot_out(snapshot),"scientific_state_id":state.get("experiment_id"),"rule_based":_rule_result(state),
            "tool_eligibility":state.get("tool_availability",{}),"safety_gate_status":"NOT_EXECUTED_SHADOW_RECOMMENDATION_ONLY","review_required":True})
        result["agreement"]=(result["action"]==result["rule_based"]["action"])
        return result
    except DecisionInputError as exc: raise HTTPException(422,str(exc)) from exc


@router.post("/compare")
def compare(payload:CompareIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id);row=db.get(DecisionModelRun,payload.model_id)
    if not row or row.topic_id!=payload.topic_id: raise HTTPException(404,detail={"code":"DECISION_MODEL_NOT_FOUND","message":"Decision model not found for this topic."})
    try:
        state,experiment_id,snapshot=_resolve_model_state(db,payload,row)
        learned=infer_safe(LearnedDecisionHead.from_dict(row.model_json),state);rule=_rule_result(state)
        snapshot=_save_snapshot(db,payload.topic_id,_model_mode(row),state,row,learned,experiment_id=experiment_id,existing=snapshot)
        db.commit()
        return {"topic_id":payload.topic_id,"model_id":row.id,"model_mode":_model_mode(row),
            "dataset_type":row.provenance_json.get("dataset_type"),"model_version":row.model_version,
            "feature_schema_version":row.feature_schema_version,"dataset_hash":row.dataset_hash,
            "decision_snapshot":_snapshot_out(snapshot),"state":state,"learned":learned,"rule_based":rule,
            "agreement":learned["action"]==rule["action"],"mode":"SHADOW_ONLY","workflow_triggered":False,
            "tool_eligibility":state.get("tool_availability",{}),"safety_gate_status":"NOT_EXECUTED_SHADOW_RECOMMENDATION_ONLY","review_required":True}
    except DecisionInputError as exc: raise HTTPException(422,str(exc)) from exc


@router.get("/cases")
def list_cases(topic_id:int,mode:Literal["research","sandbox"]|None=None,limit:int=100,db:Session=Depends(get_db)):
    _topic(db,topic_id);query=db.query(DecisionCase).filter_by(topic_id=topic_id)
    if mode=="sandbox": query=query.filter_by(label_source="SYNTHETIC_SANDBOX",review_status="SYNTHETIC_ONLY")
    elif mode=="research": query=query.filter(DecisionCase.snapshot_id.is_not(None),DecisionCase.label_source.in_(["HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"]))
    return [{"case_id":row.id,"snapshot_id":row.snapshot_id,"group_id":row.case_group_id,"label":row.selected_action,
        "label_source":row.label_source,"review_status":row.review_status,"created_at":row.created_at.isoformat()+"Z"} for row in query.order_by(DecisionCase.id.desc()).limit(min(max(limit,1),500)).all()]


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id:str,topic_id:int,db:Session=Depends(get_db)):
    row=db.get(DecisionSnapshot,snapshot_id)
    if not row or row.topic_id!=topic_id: raise HTTPException(404,"Decision snapshot not found")
    return {**_snapshot_out(row),"state":row.state_json,"provenance":row.provenance_json}


def _dataset_out(row):
    return {"dataset_version_id":row.id,"topic_id":row.topic_id,"mode":row.mode,"dataset_version":row.dataset_version,
        "dataset_hash":row.dataset_hash,"feature_schema_version":row.feature_schema_version,"label_mapping_version":row.label_mapping_version,
        "case_count":row.case_count,"group_count":row.group_count,"action_distribution":row.action_distribution_json,
        "missingness":row.missingness_json,"source_summary":row.source_summary_json,
        "evaluation_hash":row.manifest_json.get("evaluation_hash"),"evaluation_case_count":len(row.manifest_json.get("evaluation_case_ids",[])),
        "created_at":row.created_at.isoformat()+"Z"}


@router.get("/datasets")
def list_datasets(topic_id:int,mode:Literal["research","sandbox"]|None=None,db:Session=Depends(get_db)):
    _topic(db,topic_id);query=db.query(DecisionDatasetVersion).filter_by(topic_id=topic_id)
    if mode:query=query.filter_by(mode=mode.upper())
    return [_dataset_out(row) for row in query.order_by(DecisionDatasetVersion.id.desc()).all()]


@router.post("/datasets/build")
def build_dataset(payload:DatasetBuildIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id);mode=payload.mode.upper()
    rows=db.query(DecisionCase).filter_by(topic_id=payload.topic_id).order_by(DecisionCase.id).all()
    feedbacks=db.query(DecisionFeedback).filter_by(topic_id=payload.topic_id).order_by(DecisionFeedback.snapshot_id,DecisionFeedback.model_run_id,DecisionFeedback.revision.desc()).all()
    latest={}
    for feedback in feedbacks: latest.setdefault((feedback.snapshot_id,feedback.model_run_id),feedback)
    latest_feedback_ids={item.id for item in latest.values() if item.feedback_type in {"ACCEPT","CORRECT","REJECT"} and item.final_reviewed_action}
    if mode=="SANDBOX":
        rows=[row for row in rows if row.label_source=="SYNTHETIC_SANDBOX" and row.review_status=="SYNTHETIC_ONLY"]
        rows=[case for case in rows if case.feedback_id is None or case.feedback_id in latest_feedback_ids]
    else:
        rows=[row for row in rows if row.label_source in {"HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"} and row.review_status=="ACCEPTED" and row.snapshot_id]
        # Eligibility is explicit from the final action and feedback type.
        rows=[case for case in rows if case.feedback_id is None or case.feedback_id in latest_feedback_ids]
        snapshots={item.id:item for item in db.query(DecisionSnapshot).filter(DecisionSnapshot.id.in_([row.snapshot_id for row in rows if row.snapshot_id])).all()}
        rows=[row for row in rows if row.snapshot_id in snapshots and snapshots[row.snapshot_id].mode=="RESEARCH"]
        experiments={item.id:item for item in db.query(Experiment).filter(Experiment.id.in_([row.experiment_id for row in rows if row.experiment_id])).all()}
        rows=[row for row in rows if row.experiment_id is None or (row.experiment_id in experiments and experiments[row.experiment_id].topic_id==payload.topic_id and not experiments[row.experiment_id].demo)]
    if not rows: raise HTTPException(409,detail={"code":"INSUFFICIENT_REVIEWED_DECISIONS" if mode=="RESEARCH" else "INSUFFICIENT_SANDBOX_CASES","message":"No eligible, snapshot-backed decision cases are available."})
    snapshots={item.id:item for item in db.query(DecisionSnapshot).filter(DecisionSnapshot.id.in_([row.snapshot_id for row in rows if row.snapshot_id])).all()}
    records=[]
    for row in rows:
        snapshot=snapshots.get(row.snapshot_id)
        if mode=="RESEARCH" and not snapshot: continue
        state=snapshot.state_json if snapshot else row.state_json
        vector=snapshot.feature_vector_json if snapshot else row.features_json.get("vector",[])
        group=(f"experiment-{row.experiment_id}" if row.experiment_id else row.case_group_id)
        records.append({"case_id":row.id,"snapshot_id":row.snapshot_id,"feedback_id":row.feedback_id,
            "case_group_id":group,"features":vector,"state":state,"action":row.selected_action,
            "label_source":row.label_source,"review_status":row.review_status,
            "reviewer_identity_status":(row.provenance_json or {}).get("reviewer_identity_status","NOT_AUTHENTICATED"),
            "provenance":row.provenance_json or {}})
    if len(records)<2: raise HTTPException(409,detail={"code":"INSUFFICIENT_REVIEWED_DECISIONS" if mode=="RESEARCH" else "INSUFFICIENT_SANDBOX_CASES","message":"At least two eligible decision cases are required."})
    record_ids={item["case_id"] for item in records}
    previous=db.query(DecisionDatasetVersion).filter_by(topic_id=payload.topic_id,mode=mode).order_by(DecisionDatasetVersion.id.desc()).first()
    frozen_eval_ids=[];frozen_group_ids=[]
    if previous:
        frozen_eval_ids=list(previous.manifest_json.get("evaluation_case_ids",[]));frozen_group_ids=list(previous.manifest_json.get("evaluation_group_ids",[]))
        if not set(frozen_eval_ids)<=record_ids:
            raise HTTPException(409,detail={"code":"EVALUATION_SET_LEAKAGE","message":"The frozen evaluation cases are missing from the new dataset."})
        # Reuse the original immutable holdout records, never a current mutable row
        # that could silently rewrite the evaluation target after V1 was frozen.
        frozen_records={item["case_id"]:item for item in previous.manifest_json.get("records",[]) if item["case_id"] in set(frozen_eval_ids)}
        if set(frozen_records)!=set(frozen_eval_ids):
            raise HTTPException(409,detail={"code":"EVALUATION_SET_LEAKAGE","message":"The frozen evaluation manifest is incomplete."})
        records=[frozen_records.get(item["case_id"],item) for item in records]
    else:
        try:
            _,eval_ix=split_by_group([x["action"] for x in records],[x["case_group_id"] for x in records],seed=1729,fraction=.25)
        except DecisionInputError as exc:
            raise HTTPException(409,detail={"code":"INSUFFICIENT_REVIEWED_DECISIONS" if mode=="RESEARCH" else "INSUFFICIENT_SANDBOX_CASES","message":str(exc)}) from exc
        frozen_eval_ids=[records[i]["case_id"] for i in eval_ix]
        frozen_group_ids=sorted({records[i]["case_group_id"] for i in eval_ix})
    eval_hash=dataset_digest([item for item in records if item["case_id"] in set(frozen_eval_ids)])
    records=sorted(records,key=lambda x:(x["case_group_id"],x["case_id"]))
    action_distribution={action:sum(item["action"]==action for item in records) for action in ACTIONS}
    missingness={"missing_feature_count_cases":sum(bool(item["state"].get("state_field_missing_count",0)) for item in records),
        "without_authenticated_reviewer":sum(item["reviewer_identity_status"]!="AUTHENTICATED" for item in records if mode=="RESEARCH")}
    source_summary={"label_sources":sorted({item["label_source"] for item in records}),
        "review_statuses":sorted({item["review_status"] for item in records}),"synthetic_only":mode=="SANDBOX",
        "no_pseudo_labels":True,"reviewer_identity_is_self_reported":mode=="RESEARCH"}
    manifest={"records":records,"evaluation_case_ids":frozen_eval_ids,"evaluation_group_ids":frozen_group_ids,"evaluation_hash":eval_hash,
        "excluded_training_group_ids":frozen_group_ids,"split_policy":"immutable_group_holdout_v1"}
    digest=dataset_digest({"topic_id":payload.topic_id,"mode":mode,"feature_schema_version":FEATURE_SCHEMA_VERSION,
        "label_mapping_version":"decision-actions-v1","manifest":manifest})
    existing=db.query(DecisionDatasetVersion).filter_by(topic_id=payload.topic_id,mode=mode,dataset_hash=digest).first()
    if existing:return _dataset_out(existing)
    version=f"{mode.lower()}-v{db.query(DecisionDatasetVersion).filter_by(topic_id=payload.topic_id,mode=mode).count()+1}"
    row=DecisionDatasetVersion(topic_id=payload.topic_id,mode=mode,dataset_version=version,dataset_hash=digest,
        feature_schema_version=FEATURE_SCHEMA_VERSION,label_mapping_version="decision-actions-v1",case_count=len(records),
        group_count=len({x["case_group_id"] for x in records}),action_distribution_json=action_distribution,
        missingness_json=missingness,source_summary_json=source_summary,manifest_json=manifest,created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row);db.commit();db.refresh(row)
    return _dataset_out(row)


@router.get("/feedback")
def list_feedback(topic_id:int,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    return [{"feedback_id":row.id,"snapshot_id":row.snapshot_id,"model_id":row.model_run_id,"revision":row.revision,
        "feedback_type":row.feedback_type,"suggested_action":row.suggested_action,"final_reviewed_action":row.final_reviewed_action,
        "reviewer":row.reviewer,"reviewer_identity_status":row.reviewer_identity_status,"review_status":row.review_status,
        "label_source":row.label_source,"created_at":row.created_at.isoformat()+"Z"}
        for row in db.query(DecisionFeedback).filter_by(topic_id=topic_id).order_by(DecisionFeedback.created_at.desc(),DecisionFeedback.id.desc()).all()]


@router.post("/feedback")
def create_feedback(payload:FeedbackIn,db:Session=Depends(get_db)):
    snapshot=db.get(DecisionSnapshot,payload.snapshot_id);model=db.get(DecisionModelRun,payload.model_id)
    if not snapshot: raise HTTPException(404,detail={"code":"DECISION_SNAPSHOT_NOT_FOUND","message":"Decision snapshot not found."})
    _topic(db,snapshot.topic_id)
    if not model or model.topic_id!=snapshot.topic_id: raise HTTPException(404,detail={"code":"DECISION_MODEL_NOT_FOUND","message":"Model not found for this snapshot topic."})
    if snapshot.model_run_id!=model.id or snapshot.mode!=_model_mode(model):
        raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Feedback must refer to the exact model and mode that produced the snapshot."})
    final_action=payload.final_reviewed_action
    if payload.feedback_type=="ACCEPT":
        if final_action not in (None,snapshot.suggested_action): raise HTTPException(422,"Accept feedback must keep the suggested action.")
        final_action=snapshot.suggested_action
    elif payload.feedback_type=="CORRECT":
        if not final_action or final_action==snapshot.suggested_action: raise HTTPException(422,"Correct feedback requires a different final action.")
    elif payload.feedback_type=="UNSURE" and final_action:
        raise HTTPException(422,"Unsure feedback cannot contain a training label.")
    previous=db.query(DecisionFeedback).filter_by(snapshot_id=snapshot.id,model_run_id=model.id).order_by(DecisionFeedback.revision.desc()).first()
    revision=(previous.revision+1) if previous else 1
    eligible=payload.feedback_type in {"ACCEPT","CORRECT","REJECT"} and bool(final_action)
    mode=_model_mode(model)
    label_source="SYNTHETIC_SANDBOX" if mode=="SANDBOX" else "HUMAN_REVIEWED_DECISION"
    feedback=DecisionFeedback(topic_id=snapshot.topic_id,snapshot_id=snapshot.id,model_run_id=model.id,revision=revision,
        feedback_type=payload.feedback_type,suggested_action=snapshot.suggested_action,final_reviewed_action=final_action,
        reviewer=payload.reviewer.strip(),reviewer_identity_status="SELF_REPORTED_NOT_AUTHENTICATED",
        review_reason=payload.review_reason.strip(),review_status="RESEARCHER_REVIEWED" if eligible else "NO_TRAINING_LABEL",
        label_source=label_source,model_version=model.model_version,original_probabilities_json=snapshot.probabilities_json,
        ood_status=snapshot.ood_status,dataset_version=None,supersedes_feedback_id=previous.id if previous else None,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(feedback);db.flush()
    if eligible:
        state=snapshot.state_json
        case_group=(f"experiment-{snapshot.experiment_id}" if snapshot.experiment_id else
            (snapshot.provenance_json.get("case_group_id") or f"decision-snapshot-{snapshot.id}"))
        synthetic=mode=="SANDBOX"
        case=DecisionCase(topic_id=snapshot.topic_id,experiment_id=snapshot.experiment_id,snapshot_id=snapshot.id,feedback_id=feedback.id,
            case_group_id=case_group,state_json=state,features_json={"vector":snapshot.feature_vector_json,"feature_names":list(FEATURES)},
            feature_schema_version=snapshot.feature_schema_version,candidate_actions_json=list(ACTIONS),selected_action=final_action,
            label_source=label_source,reviewer=payload.reviewer.strip(),review_status="SYNTHETIC_ONLY" if synthetic else "ACCEPTED",
            provenance_json={"label_source":label_source,"reviewer_identity_status":"SELF_REPORTED_NOT_AUTHENTICATED",
                "reviewed_feedback_id":feedback.id,"feedback_type":payload.feedback_type,"model_id":model.id,
                "model_version":model.model_version,"snapshot_id":snapshot.id,"snapshot_hash":snapshot.snapshot_hash,
                "not_authenticated_expert_truth":True,"decision_time_snapshot":True},
            dataset_version=DATASET_VERSION,created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(case)
    db.commit();db.refresh(feedback)
    return {"feedback_id":feedback.id,"revision":feedback.revision,"snapshot_id":snapshot.id,"model_id":model.id,
        "feedback_type":feedback.feedback_type,"suggested_action":feedback.suggested_action,
        "final_reviewed_action":feedback.final_reviewed_action,"label_eligible":eligible,
        "review_status":feedback.review_status,"reviewer_identity_status":feedback.reviewer_identity_status,
        "supersedes_feedback_id":feedback.supersedes_feedback_id,"workflow_triggered":False}


@router.post("/retrain")
def retrain(payload:RetrainIn,db:Session=Depends(get_db)):
    dataset=db.get(DecisionDatasetVersion,payload.dataset_version_id)
    if not dataset: raise HTTPException(404,detail={"code":"DECISION_DATASET_NOT_FOUND","message":"Decision dataset version not found."})
    records=dataset.manifest_json.get("records",[]);eval_ids=list(dataset.manifest_json.get("evaluation_case_ids",[]))
    eval_set=set(eval_ids);eval_records=[item for item in records if item["case_id"] in eval_set]
    if len(eval_records)!=len(eval_ids) or not eval_records:
        raise HTTPException(409,detail={"code":"EVALUATION_SET_LEAKAGE","message":"Frozen evaluation records are missing or duplicated."})
    eval_groups=set(dataset.manifest_json.get("evaluation_group_ids",[]))
    train_records=[item for item in records if item["case_id"] not in eval_set and item["case_group_id"] not in eval_groups]
    labels=[item["action"] for item in train_records];groups=[item["case_group_id"] for item in train_records]
    if len(set(groups))<4 or len(set(labels))<2:
        code="INSUFFICIENT_REVIEWED_DECISIONS" if dataset.mode=="RESEARCH" else "INSUFFICIENT_SANDBOX_CASES"
        raise HTTPException(409,detail={"code":code,"message":"Not enough independent non-evaluation groups for fitting and calibration."})
    parent=db.get(DecisionModelRun,payload.parent_model_id) if payload.parent_model_id else None
    if payload.parent_model_id and (not parent or parent.topic_id!=dataset.topic_id or parent.mode.upper()!=dataset.mode):
        raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Parent model must have the same topic and dataset mode."})
    if parent:
        parent_eval=parent.provenance_json.get("evaluation_case_ids") or parent.provenance_json.get("validation_case_ids") or []
        parent_hash=parent.provenance_json.get("evaluation_hash")
        if parent_eval!=eval_ids or (parent_hash and parent_hash!=dataset.manifest_json.get("evaluation_hash")):
            raise HTTPException(409,detail={"code":"MODELS_NOT_COMPARABLE","message":"Frozen evaluation set differs from the parent model."})
    try:
        fit_sub,cal_sub=split_by_group(labels,groups,seed=payload.seed,fraction=.2)
        fit_records=[train_records[i] for i in fit_sub];cal_records=[train_records[i] for i in cal_sub]
        x_fit=np.vstack([np.asarray(item["features"],dtype=float) for item in fit_records])
        x_cal=np.vstack([np.asarray(item["features"],dtype=float) for item in cal_records])
        x_eval=np.vstack([np.asarray(item["features"],dtype=float) for item in eval_records])
        y_fit=[item["action"] for item in fit_records];y_cal=[item["action"] for item in cal_records];y_eval=[item["action"] for item in eval_records]
        model,losses=LearnedDecisionHead.fit(x_fit,y_fit,seed=payload.seed)
        calibrated=model.calibrate(x_cal,y_cal)
        probabilities=model.predict_proba(x_eval)
        metrics=calibration_metrics(y_eval,probabilities)
        predictions=[ACTIONS[int(index)] for index in np.argmax(probabilities,axis=1)]
        metrics["per_class"]={action:{"precision":float(np.sum((np.asarray(predictions)==action)&(np.asarray(y_eval)==action))/max(1,np.sum(np.asarray(predictions)==action))),
            "recall":float(np.sum((np.asarray(predictions)==action)&(np.asarray(y_eval)==action))/max(1,np.sum(np.asarray(y_eval)==action)))} for action in ACTIONS}
        metrics["majority_baseline"]=majority_metrics(y_fit,y_eval)
        metrics["rule_baseline"]=rule_metrics([item["state"] for item in eval_records],y_eval)
        metrics["training_loss_start"]=losses[0];metrics["training_loss_end"]=losses[-1];metrics["training_loss_decreased"]=losses[-1]<losses[0]
        metrics["calibration_status"]="TEMPERATURE_SCALED_ON_SEPARATE_GROUP_HOLDOUT" if calibrated else "INSUFFICIENT_CALIBRATION_DATA"
        metrics["calibration_group_count"]=len({item["case_group_id"] for item in cal_records})
        metrics["model_size_bytes"]=len(json.dumps(model.to_dict(),separators=(",",":" )).encode())
        safe_outputs=[infer_safe(model,item["state"]) for item in eval_records]
        metrics["abstention_rate"]=float(np.mean([result["action"]=="ABSTAIN" for result in safe_outputs]))
        metrics["ood_summary"]={status:sum(result["ood_status"]==status for result in safe_outputs) for status in ("IN_DISTRIBUTION","POTENTIAL_OOD","UNSUPPORTED_STATE")}
        metrics["inference_latency_ms"]=_measure_latency(model,x_eval)
        metrics["action_probabilities_are_success_probabilities"]=False
        eval_hash=dataset.manifest_json.get("evaluation_hash")
        training_ids=[item["case_id"] for item in fit_records];calibration_ids=[item["case_id"] for item in cal_records]
        if (set(training_ids)|set(calibration_ids)) & eval_set:
            raise DecisionInputError("Evaluation data leaked into training or calibration.")
        run_number=db.query(DecisionModelRun).filter_by(topic_id=dataset.topic_id,mode=dataset.mode).count()+1
        trained_at=datetime.now(timezone.utc).replace(tzinfo=None)
        artifact_hash=dataset_digest(model.to_dict())
        provenance={"dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE" if dataset.mode=="SANDBOX" else "RESEARCHER_REVIEWED_DECISIONS",
            "dataset_version_id":dataset.id,"dataset_version":dataset.dataset_version,"dataset_hash":dataset.dataset_hash,
            "feature_schema_version":dataset.feature_schema_version,"label_mapping_version":dataset.label_mapping_version,
            "training_seed":payload.seed,"training_config":{"architecture":"tanh_mlp_softmax","hidden_size":12,"epochs":550,"learning_rate":0.035,"calibration":"temperature_scaling_on_group_holdout"},
            "model_artifact_hash":artifact_hash,"trained_at":trained_at.isoformat()+"Z",
            "parent_model_id":parent.id if parent else None,"training_case_ids":training_ids,"calibration_case_ids":calibration_ids,
            "evaluation_case_ids":eval_ids,"validation_case_ids":eval_ids,"evaluation_group_ids":sorted(eval_groups),"evaluation_hash":eval_hash,
            "group_split":"frozen_group_holdout_v1","evaluation_case_count":len(eval_ids),"no_pseudo_labels":True,"shadow_mode_only":True,
            "reviewer_identity_note":"Self-reported identity; not authenticated." if dataset.mode=="RESEARCH" else "Synthetic fixture only."}
        row=DecisionModelRun(topic_id=dataset.topic_id,mode=dataset.mode,status="EVALUATED",dataset_hash=dataset.dataset_hash,
            model_version=f"{MODEL_VERSION}+run-{run_number}",feature_schema_version=dataset.feature_schema_version,
            dataset_version=dataset.dataset_version,model_json=model.to_dict(),metrics_json=metrics,provenance_json=provenance,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(row);db.commit();db.refresh(row)
        return _model_out(row)
    except (DecisionInputError,ValueError,np.linalg.LinAlgError) as exc:
        db.rollback();raise HTTPException(422,detail={"code":"DECISION_TRAINING_INVALID","message":str(exc)}) from exc


@router.post("/models/compare")
def compare_models(payload:ModelCompareIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id)
    champion=db.get(DecisionModelRun,payload.champion_model_id);challenger=db.get(DecisionModelRun,payload.challenger_model_id)
    if not champion or not challenger or champion.topic_id!=payload.topic_id or challenger.topic_id!=payload.topic_id:
        raise HTTPException(404,detail={"code":"DECISION_MODEL_NOT_FOUND","message":"Both models must belong to the selected topic."})
    if champion.id==challenger.id or champion.mode.upper()!=challenger.mode.upper():
        raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Champion and challenger must be different models from the same dataset mode."})
    cp=champion.provenance_json or {};npv=challenger.provenance_json or {}
    champion_eval=cp.get("evaluation_case_ids") or cp.get("validation_case_ids") or []
    challenger_eval=npv.get("evaluation_case_ids") or npv.get("validation_case_ids") or []
    evaluation_hash=cp.get("evaluation_hash")
    status="NOT_COMPARABLE";reason="Models do not share a verified frozen evaluation set."
    report={"champion_model_id":champion.id,"challenger_model_id":challenger.id,
        "champion_dataset_hash":champion.dataset_hash,"challenger_dataset_hash":challenger.dataset_hash,
        "champion_metrics":champion.metrics_json,"challenger_metrics":challenger.metrics_json,
        "evaluation_hash":evaluation_hash,"evaluation_case_ids":champion_eval}
    if evaluation_hash and evaluation_hash==npv.get("evaluation_hash") and champion_eval==challenger_eval and champion_eval:
        ctrain=set(cp.get("training_case_ids",[]));ccal=set(cp.get("calibration_case_ids",[]))
        ntrain=set(npv.get("training_case_ids",[]));ncal=set(npv.get("calibration_case_ids",[]));evalset=set(champion_eval)
        if ((ctrain|ccal|ntrain|ncal)&evalset):
            status="NOT_COMPARABLE";reason="The frozen evaluation set overlaps at least one model's training or calibration data."
            code="EVALUATION_SET_LEAKAGE"
        else:
            groups=len(set(cp.get("evaluation_group_ids",[])))
            cmetrics=champion.metrics_json or {};nmetrics=challenger.metrics_json or {}
            delta_f1=float(nmetrics.get("macro_f1",0))-float(cmetrics.get("macro_f1",0))
            delta_brier=float(nmetrics.get("brier_score",1))-float(cmetrics.get("brier_score",1))
            delta_ece=float(nmetrics.get("expected_calibration_error_10_bins",1))-float(cmetrics.get("expected_calibration_error_10_bins",1))
            conservative_actions=("REQUEST_REVIEW","ABSTAIN")
            c_per_class=cmetrics.get("per_class",{});n_per_class=nmetrics.get("per_class",{})
            protected_recall_deltas={action:float(n_per_class.get(action,{}).get("recall",0))-float(c_per_class.get(action,{}).get("recall",0)) for action in conservative_actions}
            safety_degraded=(delta_brier>.05 or delta_ece>.10 or float(nmetrics.get("abstention_rate",0))+0.15<float(cmetrics.get("abstention_rate",0))
                or any(delta<-.10 for delta in protected_recall_deltas.values()))
            if len(champion_eval)<30 or groups<10:
                status="INSUFFICIENT_EVIDENCE";reason="The shared holdout has too few independent cases or groups for a promotion comparison."
            elif safety_degraded or delta_f1<-.02:
                status="REGRESSED";reason="The challenger reduced macro F1 or materially worsened a calibration/safety measure."
            elif delta_f1>.02 and not safety_degraded and delta_brier<=.02:
                status="IMPROVED";reason="The challenger improved macro F1 on the same frozen evaluation set without the configured calibration regressions."
            else:
                status="COMPARABLE";reason="The evidence does not establish a material improvement or regression."
            code=None
            report.update({"independent_evaluation_group_count":groups,"delta_macro_f1":delta_f1,"delta_brier_score":delta_brier,
                "delta_ece":delta_ece,"safety_degraded":safety_degraded,"protected_action_recall_delta":protected_recall_deltas,"per_class_champion":cmetrics.get("per_class",{}),
                "per_class_challenger":nmetrics.get("per_class",{}),"champion_ood":cmetrics.get("ood_summary"),
                "challenger_ood":nmetrics.get("ood_summary"),"champion_abstention_rate":cmetrics.get("abstention_rate"),
                "challenger_abstention_rate":nmetrics.get("abstention_rate"),"champion_model_size_bytes":cmetrics.get("model_size_bytes"),
                "challenger_model_size_bytes":nmetrics.get("model_size_bytes"),"champion_latency_ms":cmetrics.get("inference_latency_ms"),
                "challenger_latency_ms":nmetrics.get("inference_latency_ms"),"reason":reason})
    else:
        code=None;report["reason"]=reason
    row=DecisionModelComparison(topic_id=payload.topic_id,mode=champion.mode.upper(),champion_model_id=champion.id,
        challenger_model_id=challenger.id,evaluation_hash=evaluation_hash or "",comparison_status=status,
        report_json=report,created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row);db.commit();db.refresh(row)
    return {"comparison_id":row.id,"topic_id":row.topic_id,"mode":row.mode,"champion_model_id":row.champion_model_id,
        "challenger_model_id":row.challenger_model_id,"evaluation_hash":row.evaluation_hash,"status":status,"reason":reason,
        "error_code":code if status=="NOT_COMPARABLE" else None,"report":report,"workflow_triggered":False}


def _active_out(db,topic_id,mode):
    active=db.query(DecisionActiveShadowModel).filter_by(topic_id=topic_id,mode=mode).first()
    if not active:return {"topic_id":topic_id,"mode":mode,"model":None,"activation_history":[]}
    return {"topic_id":topic_id,"mode":mode,"model":_model_out(db.get(DecisionModelRun,active.model_run_id)),
        "activation_history":[{"event_id":event.id,"previous_model_id":event.previous_model_id,"new_model_id":event.new_model_id,
            "comparison_id":event.comparison_id,"reviewer":event.reviewer,"reviewer_identity_status":event.reviewer_identity_status,
            "action":event.action,"reason":event.reason,"created_at":event.created_at.isoformat()+"Z"}
            for event in db.query(DecisionModelActivationEvent).filter_by(topic_id=topic_id,mode=mode).order_by(DecisionModelActivationEvent.id.desc()).limit(25).all()]}


@router.get("/active")
def get_active_shadow(topic_id:int,mode:Literal["research","sandbox"],db:Session=Depends(get_db)):
    _topic(db,topic_id);return _active_out(db,topic_id,mode.upper())


def _set_active_shadow(db,topic_id,mode,model,comparison,reviewer,reason,action):
    mode=mode.upper()
    active=db.query(DecisionActiveShadowModel).filter_by(topic_id=topic_id,mode=mode).first()
    previous_id=active.model_run_id if active else None
    if previous_id==model.id: raise HTTPException(409,detail={"code":"MODEL_ALREADY_ACTIVE","message":"This model is already the active shadow model."})
    if action=="ACTIVATE" and active and not comparison:
        raise HTTPException(409,detail={"code":"MODEL_COMPARISON_REQUIRED","message":"Replacing the active model requires an acceptable Champion–Challenger comparison."})
    if comparison:
        if comparison.topic_id!=topic_id or comparison.challenger_model_id!=model.id or comparison.mode.upper()!=mode:
            raise HTTPException(409,detail={"code":"MODEL_NOT_EVALUATED_FOR_PROMOTION","message":"Comparison does not evaluate this challenger for this topic/mode."})
        if comparison.comparison_status not in {"IMPROVED","COMPARABLE"}:
            raise HTTPException(409,detail={"code":"MODEL_PROMOTION_GATE_FAILED","message":f"Cannot activate a model with comparison status {comparison.comparison_status}."})
        if action=="ACTIVATE" and active and comparison.champion_model_id!=active.model_run_id:
            raise HTTPException(409,detail={"code":"MODEL_COMPARISON_REQUIRED","message":"The comparison must use the currently active Shadow model as Champion."})
    elif not (model.provenance_json or {}).get("evaluation_hash"):
        raise HTTPException(409,detail={"code":"MODEL_NOT_EVALUATED_FOR_PROMOTION","message":"A frozen evaluation result is required before activation."})
    if model.topic_id!=topic_id or model.mode.upper()!=mode or not (model.provenance_json or {}).get("evaluation_hash"):
        raise HTTPException(409,detail={"code":"MODEL_DATASET_MODE_MISMATCH","message":"Only evaluated models with the same topic and dataset mode can be activated."})
    if active: active.model_run_id=model.id;active.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        active=DecisionActiveShadowModel(topic_id=topic_id,mode=mode,model_run_id=model.id,updated_at=datetime.now(timezone.utc).replace(tzinfo=None));db.add(active)
    if previous_id:
        previous=db.get(DecisionModelRun,previous_id)
        if previous: previous.status="SHADOW_INACTIVE"
    model.status="SHADOW_ACTIVE"
    event=DecisionModelActivationEvent(topic_id=topic_id,mode=mode,previous_model_id=previous_id,new_model_id=model.id,
        comparison_id=comparison.id if comparison else None,reviewer=reviewer.strip(),
        reviewer_identity_status="SELF_REPORTED_NOT_AUTHENTICATED",action=action,reason=reason.strip(),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(event);db.commit();db.refresh(event)
    return {"topic_id":topic_id,"mode":mode,"active_model_id":model.id,"previous_model_id":previous_id,
        "event_id":event.id,"action":action,"reviewer_identity_status":event.reviewer_identity_status,"workflow_triggered":False}


@router.post("/activate")
def activate_shadow(payload:ActivationIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id);model=db.get(DecisionModelRun,payload.model_id)
    if not model: raise HTTPException(404,"Decision model not found")
    comparison=db.get(DecisionModelComparison,payload.comparison_id) if payload.comparison_id else None
    if payload.comparison_id and not comparison: raise HTTPException(404,"Model comparison not found")
    return _set_active_shadow(db,payload.topic_id,model.mode.upper(),model,comparison,payload.reviewer,payload.reason,"ACTIVATE")


@router.post("/rollback")
def rollback_shadow(payload:RollbackIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id)
    topic_id=payload.topic_id;normalized=payload.mode.upper();active=db.query(DecisionActiveShadowModel).filter_by(topic_id=topic_id,mode=normalized).first()
    if not active: raise HTTPException(409,detail={"code":"NO_ACTIVE_SHADOW_MODEL","message":"No active shadow model can be rolled back."})
    previous=db.query(DecisionModelActivationEvent).filter_by(topic_id=topic_id,mode=normalized).order_by(DecisionModelActivationEvent.id.desc()).first()
    if not previous or not previous.previous_model_id: raise HTTPException(409,detail={"code":"NO_SHADOW_ROLLBACK_TARGET","message":"There is no previous model in the activation history."})
    target=db.get(DecisionModelRun,previous.previous_model_id)
    if not target: raise HTTPException(409,detail={"code":"NO_SHADOW_ROLLBACK_TARGET","message":"Previous shadow model is no longer available."})
    return _set_active_shadow(db,topic_id,normalized,target,None,payload.reviewer,payload.reason,"ROLLBACK")
