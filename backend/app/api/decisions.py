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
from app.db.models import (DecisionCase, DecisionModelRun, Experiment, MaterialAnalysisRun,
    OptimizationModelRun, ResearchTopic, ScientificObservation, SimulationRun)
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
    experiment_id:int|None=Field(default=None,gt=0)
    scientific_state:dict[str,Any]|None=None


class CompareIn(PredictIn):
    pass


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


def _model_out(row):
    return {"model_id":row.id,"topic_id":row.topic_id,"mode":row.mode,"status":row.status,"model_version":row.model_version,
        "feature_schema_version":row.feature_schema_version,"dataset_version":row.dataset_version,"dataset_hash":row.dataset_hash,
        "metrics":row.metrics_json,"provenance":row.provenance_json,"created_at":row.created_at.isoformat()+"Z"}


@router.get("/training-readiness")
def training_readiness(topic_id:int,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    rows=db.query(DecisionCase).filter(DecisionCase.topic_id==topic_id).all()
    human=[row for row in rows if row.label_source in {"HUMAN_REVIEWED_DECISION","EXPERT_ANNOTATION"} and row.review_status=="ACCEPTED"]
    groups=len({row.case_group_id for row in human}); classes=sorted({row.selected_action for row in human})
    action_groups={action:len({row.case_group_id for row in human if row.selected_action==action}) for action in classes}
    ready=groups>=20 and len(classes)>=2 and all(count>=2 for count in action_groups.values())
    return {"topic_id":topic_id,"research":{"status":"READY" if ready else "INSUFFICIENT_REVIEWED_DECISIONS","reviewed_case_count":len(human),"independent_group_count":groups,"action_classes":classes,"action_group_counts":action_groups,"minimum_groups":20},
        "sandbox":{"status":"READY" if any(row.label_source=="SYNTHETIC_SANDBOX" for row in rows) else "NOT_SEEDED","case_count":sum(row.label_source=="SYNTHETIC_SANDBOX" for row in rows)},
        "dataset_version":DATASET_VERSION,"feature_schema_version":FEATURE_SCHEMA_VERSION}


@router.post("/cases")
def create_case(payload:CaseIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id)
    state=_state(db,payload.topic_id,payload.experiment_id,payload.scientific_state)
    try: features=encode_state(state).tolist()
    except DecisionInputError as exc: raise HTTPException(422,str(exc)) from exc
    group=f"experiment-{payload.experiment_id}" if payload.experiment_id else payload.case_group_id or f"case-{uuid.uuid4()}"
    row=DecisionCase(topic_id=payload.topic_id,experiment_id=payload.experiment_id,case_group_id=group,state_json=state,
        features_json={"vector":features,"feature_names":list(FEATURES)},feature_schema_version=FEATURE_SCHEMA_VERSION,
        candidate_actions_json=list(ACTIONS),selected_action=payload.selected_action,label_source=payload.label_source,reviewer=payload.reviewer.strip(),review_status="ACCEPTED",
        provenance_json={"label_source":payload.label_source,"reviewer":payload.reviewer.strip(),"opinion":payload.opinion.strip(),"decision_timestamp":datetime.now(timezone.utc).isoformat(),"feature_extraction_timestamp":datetime.now(timezone.utc).isoformat()},dataset_version=DATASET_VERSION,created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row);db.commit();db.refresh(row)
    return {"case_id":row.id,"topic_id":row.topic_id,"label_source":row.label_source,"review_status":row.review_status,"case_group_id":row.case_group_id,"feature_schema_version":row.feature_schema_version}


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
        eval_metrics["majority_baseline"]=majority_metrics([labels[i] for i in valid_ix])
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
    state=_state(db,payload.topic_id,payload.experiment_id,payload.scientific_state)
    try:
        model=LearnedDecisionHead.from_dict(row.model_json);result=infer_safe(model,state);result.update({"model_id":row.id,"scientific_state_id":state.get("experiment_id"),"rule_based":_rule_result(state),"tool_eligibility":state.get("tool_availability",{}),"safety_gate_status":"NOT_EXECUTED_SHADOW_RECOMMENDATION_ONLY","review_required":True})
        result["agreement"]=(result["action"]==result["rule_based"]["action"])
        return result
    except DecisionInputError as exc: raise HTTPException(422,str(exc)) from exc


@router.post("/compare")
def compare(payload:CompareIn,db:Session=Depends(get_db)):
    _topic(db,payload.topic_id);row=_latest(db,payload.topic_id)
    if not row: raise HTTPException(409,detail={"code":"LEARNED_HEAD_NOT_TRAINED","message":"Train a sandbox or research decision head first."})
    state=_state(db,payload.topic_id,payload.experiment_id,payload.scientific_state)
    try:
        learned=infer_safe(LearnedDecisionHead.from_dict(row.model_json),state);rule=_rule_result(state)
        return {"topic_id":payload.topic_id,"model_id":row.id,"state":state,"learned":learned,"rule_based":rule,
            "agreement":learned["action"]==rule["action"],"mode":"SHADOW_ONLY","workflow_triggered":False,
            "tool_eligibility":state.get("tool_availability",{}),"safety_gate_status":"NOT_EXECUTED_SHADOW_RECOMMENDATION_ONLY","review_required":True}
    except DecisionInputError as exc: raise HTTPException(422,str(exc)) from exc
