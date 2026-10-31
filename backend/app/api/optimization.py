"""Phase 4 model training, prediction, recommendation, and sandbox routes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Experiment, OptimizationModelRun, OptimizationRecommendationRun, ResearchTopic, ScientificObservation
from app.services.optimization.gpbo import (GaussianProcess, OptimizationInputError, MODEL_VERSION,
    acquisition, branin, dataset_hash, metrics, sandbox_benchmark)

router = APIRouter(prefix="/optimization", tags=["optimization"])


class TrainRequest(BaseModel):
    topic_id: int = Field(gt=0)
    mode: Literal["research", "sandbox"] = "research"
    feature_ids: list[str] = Field(min_length=1, max_length=6)
    target_id: str
    method_version_id: int | None = Field(default=None, gt=0)
    process_step_id: int | None = Field(default=None, gt=0)
    kernel: Literal["rbf", "matern"] = "matern"
    noise: float = Field(default=1e-6, ge=0, le=1)
    seed: int = 7


class PredictRequest(BaseModel):
    topic_id: int = Field(gt=0)
    candidates: list[list[float]] = Field(min_length=1, max_length=1000)


class RecommendRequest(BaseModel):
    topic_id: int = Field(gt=0)
    acquisition: Literal["ei", "pi", "ucb"] = "ei"
    bounds: list[list[float]] = Field(min_length=1, max_length=6)
    maximize: bool = False
    candidate_count: int = Field(default=5, ge=1, le=20)
    search_samples: int = Field(default=3000, ge=200, le=30000)
    seed: int = 7
    constraints: list[dict] = Field(default_factory=list)
    kappa: float = Field(default=2.0, gt=0, le=20)
    xi: float = Field(default=0.01, ge=0, le=10)

    @model_validator(mode="after")
    def validate_bounds(self):
        if any(len(pair) != 2 or not all(np.isfinite(pair)) or pair[0] >= pair[1] for pair in self.bounds):
            raise ValueError("Each bound must be a finite [minimum, maximum] pair")
        return self


def _topic(db, topic_id):
    item = db.get(ResearchTopic, topic_id)
    if not item:
        raise HTTPException(404, "Research topic not found")
    return item


def _research_dataset(db, request):
    if not request.method_version_id:
        raise HTTPException(422, "Research mode requires a Method Version selection")
    if len(set(request.feature_ids)) != len(request.feature_ids) or request.target_id in request.feature_ids:
        raise HTTPException(422, "Feature and target identifiers must be distinct")
    query = (db.query(ScientificObservation, Experiment)
        .join(Experiment, Experiment.id == ScientificObservation.experiment_id)
        .filter(ScientificObservation.topic_id == request.topic_id,
            Experiment.topic_id == request.topic_id, Experiment.demo.is_(False),
            Experiment.method_version_id == request.method_version_id,
            ScientificObservation.method_version_id == request.method_version_id,
            ScientificObservation.review_status == "ACCEPTED",
            ScientificObservation.normalization_error.is_(None),
            ScientificObservation.normalized_value.is_not(None),
            ScientificObservation.source_type.in_(["LAB_RECORD", "LAB_RESULT", "ANALYSIS_OUTPUT"])))
    rows = query.order_by(ScientificObservation.id).all()
    by_experiment = {}
    for obs, exp in rows:
        by_experiment.setdefault(exp.id, {"experiment": exp, "features": {}, "targets": []})
        record = by_experiment[exp.id]
        # Inputs are explicit accepted LAB_RECORDs; outcomes are accepted measured
        # LAB_RESULT / ANALYSIS_OUTPUTs. Literature/simulation/demo sources fail closed.
        if (obs.parameter_id in request.feature_ids and obs.source_type == "LAB_RECORD"
                and (request.process_step_id is None or obs.process_step_id == request.process_step_id)):
            record["features"].setdefault(obs.parameter_id, []).append(obs)
        if obs.parameter_id == request.target_id and obs.source_type in {"LAB_RESULT", "ANALYSIS_OUTPUT"}:
            record["targets"].append(obs)
    samples=[]; provenance=[]
    for experiment_id, group in by_experiment.items():
        if any(identifier not in group["features"] for identifier in request.feature_ids):
            continue
        for target in group["targets"]:
            selected=[]
            for feature_id in request.feature_ids:
                values=group["features"][feature_id]
                compatible=[row for row in values if not target.replicate_id or not row.replicate_id or row.replicate_id == target.replicate_id]
                selected.append((compatible or values)[-1])
            if target.normalized_unit is None or any(row.normalized_value is None for row in selected):
                continue
            samples.append({"x":[float(row.normalized_value) for row in selected],"y":float(target.normalized_value),
                "experiment_id":experiment_id,"replicate_id":target.replicate_id,
                "feature_observation_ids":[row.id for row in selected],"target_observation_id":target.id,
                "feature_units":[row.normalized_unit for row in selected],"target_unit":target.normalized_unit,
                "uncertainty":target.measurement_uncertainty})
            provenance.append({"experiment_id":experiment_id,"features":[row.source_id for row in selected],"target":target.source_id})
    # Do not silently merge incompatible physical dimensions across runs.
    for index, feature_id in enumerate(request.feature_ids):
        units={sample["feature_units"][index] for sample in samples}
        if len(units)>1: raise HTTPException(422, f"Feature {feature_id} has incompatible normalized units")
    target_units={sample["target_unit"] for sample in samples}
    if len(target_units)>1: raise HTTPException(422, "Target has incompatible normalized units")
    if len(samples)<3:
        raise HTTPException(422, detail={"code":"INSUFFICIENT_APPROVED_DATA","message":"At least three paired, accepted, non-demo experiments with compatible units are required.","paired_samples":len(samples)})
    return samples


@router.get("/dataset")
def dataset_preview(topic_id:int,method_version_id:int,feature_ids:str,target_id:str,process_step_id:int|None=None,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    request=TrainRequest(topic_id=topic_id,mode="research",method_version_id=method_version_id,
        feature_ids=[value for value in feature_ids.split(",") if value],target_id=target_id,process_step_id=process_step_id)
    rows=_research_dataset(db,request)
    return {"mode":"research","status":"READY","sample_count":len(rows),"features":[{"id":key,"unit":rows[0]["feature_units"][index]} for index,key in enumerate(request.feature_ids)],
        "target":{"id":target_id,"unit":rows[0]["target_unit"]},"dataset_hash":dataset_hash(rows),
        "provenance":[{"experiment_id":row["experiment_id"],"feature_observation_ids":row["feature_observation_ids"],"target_observation_id":row["target_observation_id"]} for row in rows],
        "source_filter":"ACCEPTED, non-demo LAB_RECORD features paired with ACCEPTED LAB_RESULT/ANALYSIS_OUTPUT outcomes only"}


@router.post("/models/train")
def train_model(request:TrainRequest,db:Session=Depends(get_db)):
    _topic(db,request.topic_id)
    if request.mode == "research":
        rows=_research_dataset(db,request)
        x=[row["x"] for row in rows]; y=[row["y"] for row in rows]
        measurement_std=[float(row["uncertainty"] or 0.0) for row in rows]
        d_hash=dataset_hash(rows)
        units={"features":[{"id":key,"unit":rows[0]["feature_units"][i]} for i,key in enumerate(request.feature_ids)],
               "target":{"id":request.target_id,"unit":rows[0]["target_unit"]}}
        provenance=[{"experiment_id":row["experiment_id"],"feature_observation_ids":row["feature_observation_ids"],"target_observation_id":row["target_observation_id"]} for row in rows]
        sample_count=len(rows)
    else:
        if request.feature_ids != ["x1", "x2"] or request.target_id != "branin":
            raise HTTPException(422,"Sandbox currently supports only the documented 2D Branin objective (x1, x2)")
        rng=np.random.default_rng(request.seed); bounds=np.array([[-5.0,10.0],[0.0,15.0]])
        x=(bounds[:,0]+rng.random((24,2))*(bounds[:,1]-bounds[:,0])).tolist(); y=branin(np.asarray(x)).tolist()
        rows=[{"x":a,"y":b,"sandbox":True} for a,b in zip(x,y)]; d_hash=dataset_hash(rows)
        measurement_std=[0.0]*len(y)
        units={"features":[{"id":"x1","unit":"dimensionless"},{"id":"x2","unit":"dimensionless"}],"target":{"id":"branin","unit":"objective"}}
        provenance=[]; sample_count=len(rows)
    try:
        values_x=np.asarray(x,dtype=float); values_y=np.asarray(y,dtype=float)
        rng=np.random.default_rng(request.seed); order=rng.permutation(len(values_y))
        holdout_count=max(1,int(round(len(values_y)*0.2)))
        holdout=order[:holdout_count]; fitting=order[holdout_count:]
        if len(fitting)<2: raise OptimizationInputError("At least two training rows are required after the deterministic holdout split")
        values_measurement_std=np.asarray(measurement_std,dtype=float)
        validation_model=GaussianProcess.fit(values_x[fitting],values_y[fitting],kernel=request.kernel,noise=request.noise,measurement_std=values_measurement_std[fitting])
        holdout_mean,holdout_std=validation_model.predict(values_x[holdout])
        diagnostic=metrics(values_y[holdout],holdout_mean,holdout_std)
        model=GaussianProcess.fit(values_x,values_y,kernel=request.kernel,noise=request.noise,measurement_std=values_measurement_std)
    except OptimizationInputError as exc: raise HTTPException(422,str(exc)) from exc
    config={"mode":request.mode,"kernel":request.kernel,"noise":request.noise,"seed":request.seed,
        "feature_ids":request.feature_ids,"target_id":request.target_id,"method_version_id":request.method_version_id,
        "process_step_id":request.process_step_id,"units":units,"sample_count":sample_count,"provenance":provenance,
        "observed_targets":[float(value) for value in y],
        "measurement_uncertainty_applied":request.mode=="research" and any(measurement_std),
        "validation_scheme":"deterministic 80/20 holdout; scaler fit only on training fold",
        "validation_rows":int(len(holdout)),"metrics_interpretation":"small-data holdout estimate; not external scientific validation"}
    item=OptimizationModelRun(topic_id=request.topic_id,mode=request.mode.upper(),status="COMPLETED",dataset_hash=d_hash,
        model_version=MODEL_VERSION,config_json=config,model_json=model.to_dict(),metrics_json=diagnostic)
    db.add(item); db.commit(); db.refresh(item)
    return _model_payload(item)


def _model_payload(item):
    return {"model_id":item.id,"topic_id":item.topic_id,"mode":item.mode.lower(),"status":item.status,
        "model_version":item.model_version,"dataset_hash":item.dataset_hash,"config":item.config_json,
        "metrics":item.metrics_json,"created_at":item.created_at.isoformat()+"Z"}


def _load_model(db,model_id,topic_id):
    item=db.query(OptimizationModelRun).filter_by(id=model_id,topic_id=topic_id).first()
    if not item: raise HTTPException(404,"Optimization model not found for this topic")
    try: return item,GaussianProcess.from_dict(item.model_json)
    except OptimizationInputError as exc: raise HTTPException(409,str(exc)) from exc


@router.get("/models/{model_id}")
def get_model(model_id:int,topic_id:int,db:Session=Depends(get_db)):
    item,_=_load_model(db,model_id,topic_id); return _model_payload(item)


@router.post("/models/{model_id}/predict")
def predict(model_id:int,request:PredictRequest,db:Session=Depends(get_db)):
    item,model=_load_model(db,model_id,request.topic_id)
    try: mean,std=model.predict(request.candidates)
    except (OptimizationInputError,ValueError) as exc: raise HTTPException(422,str(exc)) from exc
    return {"model_id":item.id,"dataset_hash":item.dataset_hash,"model_version":item.model_version,
        "features":item.config_json["units"]["features"],"target":item.config_json["units"]["target"],
        "predictions":[{"values":values,"predicted_mean":m,"predictive_std":s} for values,m,s in zip(request.candidates,mean,std)],
        "notice":"Predictive uncertainty is a model estimate, not a probability of experimental success."}


@router.post("/models/{model_id}/recommend")
def recommend(model_id:int,request:RecommendRequest,db:Session=Depends(get_db)):
    item,model=_load_model(db,model_id,request.topic_id)
    if request.constraints:
        raise HTTPException(422,detail={"code":"UNSUPPORTED_CONSTRAINT","message":"This MVP only supports explicit continuous bounds; additional constraint types are not supported."})
    if len(request.bounds)!=len(model.x_mean): raise HTTPException(422,"Bounds must match the model feature count")
    if item.mode=="RESEARCH" and request.maximize and item.config_json.get("target_id")=="": raise HTTPException(422,"A target direction is required")
    rng=np.random.default_rng(request.seed); bounds=np.asarray(request.bounds,dtype=float)
    points=bounds[:,0]+rng.random((request.search_samples,len(bounds)))*(bounds[:,1]-bounds[:,0])
    try: mean,std=model.predict(points)
    except (OptimizationInputError,ValueError) as exc: raise HTTPException(422,str(exc)) from exc
    observed=np.asarray(item.config_json.get("observed_targets") or [],dtype=float)
    if not len(observed): raise HTTPException(409,"The saved model is missing its observed objective values")
    best=float(np.max(observed) if request.maximize else np.min(observed))
    scores=acquisition(mean,std,float(best),request.acquisition,maximize=request.maximize,kappa=request.kappa,xi=request.xi)
    order=np.argsort(scores)[::-1]; chosen=[]
    known=np.asarray(model.x_train)*np.asarray(model.x_scale)+np.asarray(model.x_mean)
    for idx in order:
        point=points[int(idx)]
        if np.min(np.linalg.norm(known-point,axis=1)) < 1e-7: continue
        if any(np.linalg.norm(point-np.asarray(row["values"])) < 1e-8 for row in chosen): continue
        chosen.append({"rank":len(chosen)+1,"values":point.tolist(),"units":[x["unit"] for x in item.config_json["units"]["features"]],
            "predicted_mean":float(mean[int(idx)]),"predictive_std":float(std[int(idx)]),"acquisition_score":float(scores[int(idx)]),
            "feasibility_status":"FEASIBLE_WITHIN_DECLARED_BOUNDS","approval_status":"PENDING_RESEARCHER_REVIEW"})
        if len(chosen)>=request.candidate_count: break
    if not chosen: raise HTTPException(422,"No feasible candidate was generated")
    config={"acquisition":request.acquisition,"bounds":request.bounds,"maximize":request.maximize,"seed":request.seed,
        "search_samples":request.search_samples,"kappa":request.kappa,"xi":request.xi,"constraints":request.constraints,
        "target_id":item.config_json.get("target_id"),"units":item.config_json.get("units"),"reason":"Ranked by acquisition score within declared bounds; not an outcome guarantee."}
    saved=OptimizationRecommendationRun(model_run_id=item.id,topic_id=item.topic_id,acquisition=request.acquisition.upper(),config_json=config,candidates_json=chosen)
    db.add(saved); db.commit(); db.refresh(saved)
    return {"recommendation_id":saved.id,"model_id":item.id,"model_version":item.model_version,"dataset_hash":item.dataset_hash,
        "candidates":chosen,"approval_status":saved.approval_status,"notice":"Candidates require researcher review. Acquisition score is not a predicted outcome or success probability."}


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id:int,topic_id:int,db:Session=Depends(get_db)):
    item=db.query(OptimizationRecommendationRun).filter_by(id=recommendation_id,topic_id=topic_id).first()
    if not item: raise HTTPException(404,"Recommendation not found for this topic")
    return {"recommendation_id":item.id,"model_run_id":item.model_run_id,"topic_id":item.topic_id,"acquisition":item.acquisition,
        "config":item.config_json,"candidates":item.candidates_json,"approval_status":item.approval_status,"created_at":item.created_at.isoformat()+"Z"}


@router.post("/sandbox/benchmark")
def run_sandbox_benchmark(seed:int=7,budget:int=20,seeds:int=5,topic_id:int=1,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    if budget<5 or budget>50: raise HTTPException(422,"budget must be between 5 and 50")
    if seeds<2 or seeds>20: raise HTTPException(422,"seeds must be between 2 and 20")
    return sandbox_benchmark(seed,budget,seeds)
