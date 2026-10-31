"""Phase 4 model training, prediction, recommendation, and sandbox routes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Experiment, OptimizationModelRun, OptimizationRecommendationRun, ProcessStep, ResearchTopic, ScientificObservation
from app.services.optimization.gpbo import (GaussianProcess, OptimizationInputError, MODEL_VERSION,
    acquisition, branin, dataset_hash, metrics, noisy_expected_improvement, sandbox_benchmark, stage2_sandbox_benchmark)
from app.services.optimization.constraints import compile_constraints, constraints_feasible, feasible_mask, project_candidates_to_equalities
from app.services.scientific_data import _UNITS

router = APIRouter(prefix="/optimization", tags=["optimization"])


class TrainRequest(BaseModel):
    topic_id: int = Field(gt=0)
    mode: Literal["research", "sandbox"] = "research"
    feature_ids: list[str] = Field(min_length=1, max_length=6)
    target_id: str
    method_version_id: int | None = Field(default=None, gt=0)
    process_step_id: int | None = Field(default=None, gt=0)
    target_process_step_id: int | None = Field(default=None, gt=0)
    pairing_policy: Literal["same_step", "downstream_explicit"] = "same_step"
    downstream_link_confirmed: bool = False
    downstream_relation_label: str | None = Field(default=None, max_length=240)
    replicate_policy: Literal["preserve", "inverse_variance_mean"] = "preserve"
    kernel: Literal["rbf", "matern"] = "matern"
    noise: float = Field(default=1e-6, ge=0, le=1)
    seed: int = 7


class PredictRequest(BaseModel):
    topic_id: int = Field(gt=0)
    candidates: list[list[float]] = Field(min_length=1, max_length=1000)
    prediction_type: Literal["latent", "observation"] = "observation"


class ConstraintSpec(BaseModel):
    constraint_id: str | None = Field(default=None, max_length=100)
    type: Literal["linear_inequality", "linear_equality", "variable_relation"]
    parameter_ids: list[str] = Field(default_factory=list, max_length=6)
    coefficients: list[float] = Field(default_factory=list, max_length=6)
    coefficient_units: list[str] | None = None
    threshold: float | None = None
    unit: str | None = None
    tolerance: float = Field(default=0.0, ge=0)
    sense: Literal["le", "ge"] = "le"
    left_parameter_id: str | None = None
    right_parameter_id: str | None = None
    relation: Literal["le", "ge"] = "ge"


class RecommendRequest(BaseModel):
    topic_id: int = Field(gt=0)
    acquisition: Literal["ei", "pi", "ucb", "noisy_ei"] = "ei"
    bounds: list[list[float]] = Field(min_length=1, max_length=6)
    bounds_units: list[str] | None = None
    maximize: bool = False
    candidate_count: int = Field(default=5, ge=1, le=20)
    search_samples: int = Field(default=3000, ge=200, le=30000)
    seed: int = 7
    constraints: list[ConstraintSpec] = Field(default_factory=list, max_length=20)
    candidate_diversity: float = Field(default=1e-6, ge=0, le=1)
    prediction_type: Literal["latent", "observation"] = "latent"
    noisy_ei_samples: int = Field(default=256, ge=32, le=8192)
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


def _step_anchor(db, step_id, request, label):
    if step_id is None:
        return None
    row = (db.query(ProcessStep, Experiment).join(Experiment, Experiment.id == ProcessStep.experiment_id)
        .filter(ProcessStep.id == step_id, Experiment.topic_id == request.topic_id,
            Experiment.method_version_id == request.method_version_id, Experiment.demo.is_(False)).first())
    if not row:
        raise HTTPException(422, detail={"code":"AMBIGUOUS_PROCESS_STEP","message":f"{label} step does not belong to the selected topic and Method Version."})
    step, _experiment = row
    return {"order_index":step.order_index,"name":step.name.casefold()}


def _canonical_observation(obs):
    if obs.normalization_error:
        raise HTTPException(422,detail={"code":"INVALID_UNIT","message":"An observation with a normalization error cannot train a GP."})
    try:
        value=float(obs.normalized_value)
        if not np.isfinite(value): raise ValueError
        unit=obs.normalized_unit
        if unit is None:
            if obs.original_unit:
                raise HTTPException(422,detail={"code":"INCOMPATIBLE_UNITS","message":"A unit-bearing value has no normalized unit."})
            canonical_unit="dimensionless"; canonical_value=value
        elif str(unit).casefold()=="ph":
            # Preserve logarithmic quantities without linear unit conversion.
            canonical_unit="pH"; canonical_value=value
        else:
            quantity=_UNITS.Quantity(value,unit).to_base_units()
            canonical_unit=str(quantity.units); canonical_value=float(quantity.magnitude)
        uncertainty=obs.measurement_uncertainty
        if uncertainty is not None:
            uncertainty=float(uncertainty)
            if not np.isfinite(uncertainty) or uncertainty<0:
                raise HTTPException(422,detail={"code":"INVALID_UNCERTAINTY","message":"Observation uncertainty must be finite and non-negative."})
            if unit and str(unit).casefold()!="ph":
                delta_unit={"degc":"delta_degC","degf":"delta_degF"}.get(str(unit).casefold(),str(unit))
                uncertainty=float(_UNITS.Quantity(uncertainty,delta_unit).to_base_units().magnitude)
        return canonical_value,canonical_unit,uncertainty
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422,detail={"code":"INVALID_UNIT","message":"Observation value or unit cannot be normalized."}) from exc


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
    feature_anchor = _step_anchor(db, request.process_step_id, request, "Feature")
    target_anchor = _step_anchor(db, request.target_process_step_id, request, "Target")
    if request.pairing_policy == "downstream_explicit":
        if (feature_anchor is None or target_anchor is None or target_anchor["order_index"] <= feature_anchor["order_index"]
                or not request.downstream_link_confirmed or not request.downstream_relation_label):
            raise HTTPException(422, detail={"code":"AMBIGUOUS_PROCESS_STEP","message":"Downstream pairing requires explicit feature and later target steps plus a researcher-confirmed relationship label."})
    elif feature_anchor and target_anchor and feature_anchor["order_index"] != target_anchor["order_index"]:
        raise HTTPException(422, detail={"code":"AMBIGUOUS_PROCESS_STEP","message":"Same Step pairing cannot select different feature and target steps."})
    process_steps = {step.id:(step.experiment_id,step.order_index,step.name.casefold()) for step in db.query(ProcessStep).join(Experiment, Experiment.id==ProcessStep.experiment_id)
        .filter(Experiment.topic_id==request.topic_id,Experiment.method_version_id==request.method_version_id,Experiment.demo.is_(False)).all()}
    by_experiment = {}
    for obs, exp in rows:
        by_experiment.setdefault(exp.id, {"experiment": exp, "features": {}, "targets": []})
        record = by_experiment[exp.id]
        # Inputs are explicit accepted LAB_RECORDs; outcomes are accepted measured
        # LAB_RESULT / ANALYSIS_OUTPUTs. Literature/simulation/demo sources fail closed.
        obs_step = process_steps.get(obs.process_step_id) if obs.process_step_id is not None else None
        if obs.process_step_id is not None and (obs_step is None or obs_step[0] != exp.id):
            continue
        feature_step_matches = True
        target_step_matches = True
        if feature_anchor:
            feature_step_matches = bool(obs_step and obs_step[1] == feature_anchor["order_index"] and obs_step[2] == feature_anchor["name"])
        if target_anchor:
            target_step_matches = bool(obs_step and obs_step[1] == target_anchor["order_index"] and obs_step[2] == target_anchor["name"])
        if (obs.parameter_id in request.feature_ids and obs.source_type == "LAB_RECORD" and feature_step_matches):
            record["features"].setdefault(obs.parameter_id, []).append(obs)
        if obs.parameter_id == request.target_id and obs.source_type in {"LAB_RESULT", "ANALYSIS_OUTPUT"} and target_step_matches:
            record["targets"].append(obs)
    samples=[]
    for experiment_id, group in by_experiment.items():
        for target in group["targets"]:
            target_order=process_steps[target.process_step_id][1] if target.process_step_id in process_steps else None
            selected=[]
            unmatched=False
            for feature_id in request.feature_ids:
                values=group["features"].get(feature_id, [])
                if request.pairing_policy=="same_step":
                    expected_order=feature_anchor["order_index"] if feature_anchor else target_order
                    values=[row for row in values if (process_steps[row.process_step_id][1] if row.process_step_id in process_steps else None)==expected_order]
                exact=[row for row in values if target.replicate_id and row.replicate_id==target.replicate_id]
                shared=[row for row in values if row.replicate_id is None]
                if target.replicate_id:
                    matches=exact if exact else shared
                else:
                    matches=shared
                    if not matches and values:
                        raise HTTPException(422, detail={"code":"AMBIGUOUS_OBSERVATION_PAIRING","message":"An unreplicated outcome cannot be arbitrarily paired to replicate-specific feature observations."})
                if not values:
                    unmatched=True
                    break
                if len(matches)>1:
                    raise HTTPException(422, detail={"code":"AMBIGUOUS_OBSERVATION_PAIRING","message":f"Multiple observations match feature '{feature_id}' and the selected replicate."})
                if not matches:
                    raise HTTPException(422, detail={"code":"AMBIGUOUS_OBSERVATION_PAIRING","message":f"No same-replicate or experiment-level feature observation matches '{feature_id}'."})
                selected.append(matches[0])
            if unmatched:
                continue
            if any(row.material_id and target.material_id and row.material_id != target.material_id for row in selected):
                raise HTTPException(422, detail={"code":"AMBIGUOUS_OBSERVATION_PAIRING","message":"Feature and outcome refer to different materials."})
            # Step matching is exact by default. The alternative requires explicit
            # method-order anchors and reports association, never causal proof.
            feature_orders=[process_steps[row.process_step_id][1] if row.process_step_id in process_steps else None for row in selected]
            if request.pairing_policy == "same_step":
                if any(order != target_order for order in feature_orders):
                    continue
            elif any(order is None or target_order is None or order >= target_order for order in feature_orders):
                continue
            if any(row.normalized_value is None for row in selected) or target.normalized_value is None:
                continue
            if not target.source_id or any(not row.source_id for row in selected):
                raise HTTPException(422, detail={"code":"MISSING_PROVENANCE","message":"Every paired observation must retain a source identifier."})
            canonical_features=[_canonical_observation(row) for row in selected]
            canonical_target=_canonical_observation(target)
            samples.append({"x":[row[0] for row in canonical_features],"y":canonical_target[0],
                "experiment_id":experiment_id,"replicate_id":target.replicate_id,
                "feature_observation_ids":[row.id for row in selected],"target_observation_id":target.id,
                "feature_units":[row[1] for row in canonical_features],"target_unit":canonical_target[1],
                "uncertainty":canonical_target[2],
                "feature_uncertainties":[row[2] for row in canonical_features],
                "process_step_ids":[row.process_step_id for row in selected],"target_process_step_id":target.process_step_id,
                "source_ids":[row.source_id for row in selected]+[target.source_id],
                "source_types":[row.source_type for row in selected]+[target.source_type],
                "review_statuses":[row.review_status for row in selected]+[target.review_status]})
    # Duplicate database rows referencing the same source are not extra evidence.
    unique=[]; seen={}
    for sample in samples:
        key=(sample["experiment_id"],sample["target_observation_id"])
        source_key=(sample["experiment_id"],tuple(sample["source_ids"]))
        prior=seen.get(source_key)
        if prior:
            if prior["x"]!=sample["x"] or prior["y"]!=sample["y"]:
                raise HTTPException(422, detail={"code":"MISSING_PROVENANCE","message":"Duplicate source identifiers contain conflicting values."})
            continue
        seen[source_key]=sample; unique.append(sample)
    samples=unique
    # Optional aggregation is explicit and only valid for independent replicate
    # measurements with known positive standard uncertainties at identical X.
    raw_samples=list(samples)
    if request.replicate_policy == "inverse_variance_mean":
        grouped={}
        for sample in samples:
            grouped.setdefault((sample["experiment_id"],tuple(sample["x"])),[]).append(sample)
        aggregated=[]
        for group_samples in grouped.values():
            if len(group_samples)<2:
                aggregated.extend(group_samples); continue
            sigmas=[row["uncertainty"] for row in group_samples]
            if any(value is None or float(value)<=0 for value in sigmas) or any(row["replicate_id"] is None for row in group_samples):
                raise HTTPException(422, detail={"code":"INVALID_UNCERTAINTY","message":"Inverse-variance aggregation requires distinct replicate IDs and positive known standard uncertainties."})
            weights=1.0/np.square(np.asarray(sigmas,dtype=float))
            aggregate=dict(group_samples[0])
            aggregate["y"]=float(np.sum(weights*np.asarray([row["y"] for row in group_samples]))/np.sum(weights))
            aggregate["uncertainty"]=float(np.sqrt(1.0/np.sum(weights)))
            aggregate["replicate_id"]="AGGREGATED:"+",".join(str(row["replicate_id"]) for row in group_samples)
            aggregate["source_replicate_ids"]=[row["replicate_id"] for row in group_samples]
            aggregate["paired_observation_count"]=len(group_samples)
            aggregate["feature_observation_ids"]=[value for row in group_samples for value in row["feature_observation_ids"]]
            aggregate["target_observation_ids"]=[row["target_observation_id"] for row in group_samples]
            aggregate["source_ids"]=[value for row in group_samples for value in row["source_ids"]]
            aggregate["aggregated_replicate_count"]=len(group_samples)
            aggregate["aggregation_assumption"]="Independent Gaussian measurement errors with stated standard uncertainties"
            aggregated.append(aggregate)
        samples=aggregated
    # Do not silently merge incompatible physical dimensions across runs.
    for index, feature_id in enumerate(request.feature_ids):
        units={sample["feature_units"][index] for sample in samples}
        if len(units)>1: raise HTTPException(422, f"Feature {feature_id} has incompatible normalized units")
    target_units={sample["target_unit"] for sample in samples}
    if len(target_units)>1: raise HTTPException(422, "Target has incompatible normalized units")
    independent_experiments={sample["experiment_id"] for sample in samples}
    unique_conditions={tuple(round(value,12) for value in sample["x"]) for sample in samples}
    if len(samples)<3 or len(independent_experiments)<3 or len(unique_conditions)<2:
        code="INSUFFICIENT_INDEPENDENT_EXPERIMENTS" if len(independent_experiments)<3 else "INSUFFICIENT_APPROVED_DATA"
        raise HTTPException(422, detail={"code":code,"message":"Research GP requires at least 3 independent experiments, 3 paired observations, and 2 distinct input conditions.","paired_observation_count":len(samples),"independent_experiment_count":len(independent_experiments),"unique_input_condition_count":len(unique_conditions)})
    samples.sort(key=lambda row:(row["experiment_id"],row["replicate_id"] or "",row["target_observation_id"]))
    for sample in samples:
        sample["effective_training_sample_count"] = len(samples)
        sample["pairing_policy"] = request.pairing_policy
        sample["replicate_policy"] = request.replicate_policy
    return samples


def _dataset_counts(samples, *, raw_samples=None):
    rows=raw_samples if raw_samples is not None else samples
    return {
        "independent_experiment_count":len({row.get("experiment_id") for row in rows if row.get("experiment_id") is not None}),
        "unique_replicate_count":len({(row.get("experiment_id"),replicate_id) for row in rows
            for replicate_id in (row.get("source_replicate_ids") or [row.get("replicate_id")]) if replicate_id}),
        "paired_observation_count":sum(int(row.get("paired_observation_count",1)) for row in rows),
        "effective_training_sample_count":len(samples),
        "unique_input_condition_count":len({tuple(round(float(value),12) for value in row["x"]) for row in samples}),
    }


def _group_holdout_indices(experiment_ids, seed):
    """Deterministic split by independent Experiment; all replicates stay together."""
    groups=np.asarray(sorted(set(int(value) for value in experiment_ids)),dtype=int)
    if len(groups)<3:
        raise OptimizationInputError("INSUFFICIENT_INDEPENDENT_EXPERIMENTS: at least 3 independent Experiments are required for grouped validation")
    rng=np.random.default_rng(seed); shuffled=rng.permutation(groups)
    validation_group_count=max(1,int(round(len(groups)*0.2)))
    if len(groups)-validation_group_count<2:
        validation_group_count=len(groups)-2
    validation_groups=set(int(value) for value in shuffled[:validation_group_count])
    holdout=np.asarray([index for index,value in enumerate(experiment_ids) if int(value) in validation_groups],dtype=int)
    fitting=np.asarray([index for index,value in enumerate(experiment_ids) if int(value) not in validation_groups],dtype=int)
    if not len(holdout) or len({int(experiment_ids[index]) for index in fitting})<2:
        raise OptimizationInputError("INSUFFICIENT_INDEPENDENT_EXPERIMENTS: grouped validation cannot form train and validation groups")
    return fitting,holdout,validation_group_count


@router.get("/dataset")
def dataset_preview(topic_id:int,method_version_id:int,feature_ids:str,target_id:str,process_step_id:int|None=None,
    target_process_step_id:int|None=None,pairing_policy:Literal["same_step","downstream_explicit"]="same_step",
    downstream_link_confirmed:bool=False,downstream_relation_label:str|None=None,
    replicate_policy:Literal["preserve","inverse_variance_mean"]="preserve",db:Session=Depends(get_db)):
    _topic(db,topic_id)
    request=TrainRequest(topic_id=topic_id,mode="research",method_version_id=method_version_id,
        feature_ids=[value for value in feature_ids.split(",") if value],target_id=target_id,process_step_id=process_step_id,
        target_process_step_id=target_process_step_id,pairing_policy=pairing_policy,
        downstream_link_confirmed=downstream_link_confirmed,downstream_relation_label=downstream_relation_label,
        replicate_policy=replicate_policy)
    rows=_research_dataset(db,request)
    counts=_dataset_counts(rows)
    return {"mode":"research","status":"READY","sample_count":len(rows),**counts,
        "pairing_policy":request.pairing_policy,"replicate_policy":request.replicate_policy,
        "downstream_relation_label":request.downstream_relation_label,
        "features":[{"id":key,"unit":rows[0]["feature_units"][index]} for index,key in enumerate(request.feature_ids)],
        "target":{"id":target_id,"unit":rows[0]["target_unit"]},"dataset_hash":dataset_hash(rows),
        "provenance":[{"experiment_id":row["experiment_id"],"replicate_id":row["replicate_id"],"feature_observation_ids":row["feature_observation_ids"],"target_observation_id":row.get("target_observation_id"),"target_observation_ids":row.get("target_observation_ids"),"source_ids":row["source_ids"],"process_step_ids":row["process_step_ids"],"target_process_step_id":row["target_process_step_id"]} for row in rows],
        "causality_notice":"Step order documents an explicit association path; it does not establish causality.",
        "source_filter":"ACCEPTED, non-demo LAB_RECORD features paired with ACCEPTED LAB_RESULT/ANALYSIS_OUTPUT outcomes only"}


@router.get("/dataset/options")
def dataset_options(topic_id:int,method_version_id:int,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    rows=(db.query(ScientificObservation,Experiment)
        .join(Experiment,Experiment.id==ScientificObservation.experiment_id)
        .filter(ScientificObservation.topic_id==topic_id,Experiment.topic_id==topic_id,
            Experiment.method_version_id==method_version_id,Experiment.demo.is_(False),
            ScientificObservation.method_version_id==method_version_id,ScientificObservation.review_status=="ACCEPTED",
            ScientificObservation.normalization_error.is_(None),ScientificObservation.normalized_value.is_not(None),
            ScientificObservation.source_type.in_(["LAB_RECORD","LAB_RESULT","ANALYSIS_OUTPUT"])).all())
    options={}
    experiments=set(); observations=set(); replicates=set(); step_meta={}
    for obs,exp in rows:
        if not obs.source_id: continue
        role="feature" if obs.source_type=="LAB_RECORD" else "outcome"
        unit=obs.normalized_unit or "dimensionless"
        options.setdefault((obs.parameter_id,unit,role),set()).add(exp.id)
        observations.add(obs.id); experiments.add(exp.id)
        if obs.replicate_id: replicates.add((exp.id,obs.replicate_id))
        if obs.process_step_id:
            step=db.get(ProcessStep,obs.process_step_id)
            if step and step.experiment_id==exp.id:
                entry=step_meta.setdefault((step.order_index,step.name),{"id":step.id,"experiments":set()})
                entry["experiments"].add(exp.id)
    return {"topic_id":topic_id,"method_version_id":method_version_id,
        "features":[{"parameter_id":key[0],"unit":key[1],"experiment_count":len(value)} for key,value in sorted(options.items()) if key[2]=="feature"],
        "outcomes":[{"parameter_id":key[0],"unit":key[1],"experiment_count":len(value)} for key,value in sorted(options.items()) if key[2]=="outcome"],
        "process_steps":[{"id":value["id"],"order_index":key[0],"name":key[1],"experiment_count":len(value["experiments"])} for key,value in sorted(step_meta.items())],
        "counts":{"independent_experiment_count":len(experiments),"observation_count":len(observations),"replicate_count":len(replicates)}}


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
        provenance=[{"experiment_id":row["experiment_id"],"replicate_id":row["replicate_id"],
            "feature_observation_ids":row["feature_observation_ids"],"target_observation_id":row.get("target_observation_id"),
            "target_observation_ids":row.get("target_observation_ids"),"source_ids":row["source_ids"],
            "process_step_ids":row["process_step_ids"],"target_process_step_id":row["target_process_step_id"]} for row in rows]
        sample_count=len(rows)
        counts=_dataset_counts(rows)
        validation_scheme="experiment-grouped deterministic holdout; scaler fit only on training groups"
    else:
        if request.feature_ids != ["x1", "x2"] or request.target_id != "branin":
            raise HTTPException(422,"Sandbox currently supports only the documented 2D Branin objective (x1, x2)")
        rng=np.random.default_rng(request.seed); bounds=np.array([[-5.0,10.0],[0.0,15.0]])
        x=(bounds[:,0]+rng.random((24,2))*(bounds[:,1]-bounds[:,0])).tolist(); y=branin(np.asarray(x)).tolist()
        rows=[{"x":a,"y":b,"sandbox":True} for a,b in zip(x,y)]; d_hash=dataset_hash(rows)
        measurement_std=[0.0]*len(y)
        units={"features":[{"id":"x1","unit":"dimensionless"},{"id":"x2","unit":"dimensionless"}],"target":{"id":"branin","unit":"objective"}}
        provenance=[]; sample_count=len(rows); counts=_dataset_counts(rows)
        validation_scheme="deterministic 80/20 row holdout; scaler fit only on training rows"
    try:
        values_x=np.asarray(x,dtype=float); values_y=np.asarray(y,dtype=float)
        if request.mode=="research":
            fitting,holdout,validation_group_count=_group_holdout_indices([row["experiment_id"] for row in rows],request.seed)
        else:
            rng=np.random.default_rng(request.seed); order=rng.permutation(len(values_y))
            holdout_count=max(1,int(round(len(values_y)*0.2)))
            holdout=order[:holdout_count]; fitting=order[holdout_count:]; validation_group_count=len(holdout)
        if len(fitting)<2: raise OptimizationInputError("At least two training rows are required after the deterministic holdout split")
        values_measurement_std=np.asarray(measurement_std,dtype=float)
        validation_model=GaussianProcess.fit(values_x[fitting],values_y[fitting],kernel=request.kernel,noise=request.noise,measurement_std=values_measurement_std[fitting])
        holdout_mean,holdout_std=validation_model.predict(values_x[holdout])
        diagnostic=metrics(values_y[holdout],holdout_mean,holdout_std)
        model=GaussianProcess.fit(values_x,values_y,kernel=request.kernel,noise=request.noise,measurement_std=values_measurement_std)
    except OptimizationInputError as exc: raise HTTPException(422,str(exc)) from exc
    config={"mode":request.mode,"kernel":request.kernel,"noise":request.noise,"seed":request.seed,
        "feature_ids":request.feature_ids,"target_id":request.target_id,"method_version_id":request.method_version_id,
        "process_step_id":request.process_step_id,"target_process_step_id":request.target_process_step_id,
        "pairing_policy":request.pairing_policy,"replicate_policy":request.replicate_policy,
        "downstream_link_confirmed":request.downstream_link_confirmed,"downstream_relation_label":request.downstream_relation_label,
        "units":units,"sample_count":sample_count,"provenance":provenance,"dataset_counts":counts,
        "observed_targets":[float(value) for value in y],
        "measurement_uncertainty_applied":request.mode=="research" and any(measurement_std),
        "validation_scheme":validation_scheme,"validation_rows":int(len(holdout)),"validation_group_count":int(validation_group_count),
        "metrics_interpretation":"small-data held-out estimate; not external scientific validation",
        "uncertainty_interpretation":"Known observation standard uncertainties are heteroscedastic training noise; learned nugget estimates residual observation noise; future-location aleatoric noise uses the homoscedastic nugget assumption.",
        "replicate_independence_assumption":"Preserved replicate observations are modeled with independent stated Gaussian measurement errors unless explicitly aggregated by inverse variance.",
        "aggregation_assumption":"Independent Gaussian measurement errors with stated standard uncertainties" if request.replicate_policy=="inverse_variance_mean" else None}
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
    try: mean,epistemic,aleatoric,total=model.predict_components(request.candidates)
    except (OptimizationInputError,ValueError) as exc: raise HTTPException(422,str(exc)) from exc
    return {"model_id":item.id,"dataset_hash":item.dataset_hash,"model_version":item.model_version,
        "features":item.config_json["units"]["features"],"target":item.config_json["units"]["target"],
        "prediction_type":request.prediction_type,
        "predictions":[{"values":values,"predicted_mean":m,"epistemic_std":e,"aleatoric_std":a,"total_predictive_std":t,
            "predictive_std":t if request.prediction_type=="observation" else e} for values,m,e,a,t in zip(request.candidates,mean,epistemic,aleatoric,total)],
        "uncertainty_model":{"known_observation_noise":"heteroscedastic per training row","future_aleatoric":"learned homoscedastic residual nugget assumption","epistemic":"latent GP posterior"},
        "notice":"Uncertainty components are model assumptions and estimates, not experimental success probabilities."}


@router.post("/models/{model_id}/recommend")
def recommend(model_id:int,request:RecommendRequest,db:Session=Depends(get_db)):
    item,model=_load_model(db,model_id,request.topic_id)
    if len(request.bounds)!=len(model.x_mean): raise HTTPException(422,"Bounds must match the model feature count")
    if len(request.bounds)!=len(item.config_json.get("feature_ids",[])):
        raise HTTPException(422,"Bounds must match the model's declared features")
    if item.mode=="RESEARCH" and request.maximize and item.config_json.get("target_id")=="": raise HTTPException(422,"A target direction is required")
    bounds=np.asarray(request.bounds,dtype=float)
    if not np.isfinite(bounds).all() or (bounds[:,0]>=bounds[:,1]).any():
        raise HTTPException(422,"Bounds must be finite increasing [minimum, maximum] pairs")
    feature_units=[feature["unit"] for feature in item.config_json["units"]["features"]]
    if request.bounds_units is not None:
        if len(request.bounds_units)!=len(feature_units):
            raise HTTPException(422,detail={"code":"INCOMPATIBLE_UNITS","message":"bounds_units must match the model feature count."})
        converted=[]
        for pair,source_unit,target_unit in zip(request.bounds,request.bounds_units,feature_units):
            try:
                converted.append([float(_UNITS.Quantity(value,source_unit).to(target_unit).magnitude) for value in pair])
            except Exception as exc:
                raise HTTPException(422,detail={"code":"INCOMPATIBLE_UNITS","message":"Bounds use units incompatible with the selected features."}) from exc
        bounds=np.asarray(converted,dtype=float)
        if not np.isfinite(bounds).all() or (bounds[:,0]>=bounds[:,1]).any():
            raise HTTPException(422,"Bounds must be finite increasing [minimum, maximum] pairs")
    constraint_dicts=[constraint.model_dump(exclude_none=True) for constraint in request.constraints]
    try:
        _normalized,inequalities,equalities,projection_equalities=compile_constraints(constraint_dicts,item.config_json["feature_ids"],feature_units)
        if constraint_dicts and not constraints_feasible(bounds.tolist(),inequalities,equalities):
            raise HTTPException(422,detail={"code":"INFEASIBLE_CONSTRAINT_SET","message":"The declared bounds and physical constraints have no common feasible point."})
    except OptimizationInputError as exc:
        message=str(exc); code=message.split(":",1)[0] if ":" in message else "UNSUPPORTED_CONSTRAINT"
        raise HTTPException(422,detail={"code":code,"message":message}) from exc
    rng=np.random.default_rng(request.seed)
    proposal_budget=min(request.search_samples*12,300000)
    raw_points=bounds[:,0]+rng.random((proposal_budget,len(bounds)))*(bounds[:,1]-bounds[:,0])
    try:
        projected=project_candidates_to_equalities(raw_points,projection_equalities)
        proposals=np.vstack([raw_points,projected]) if projection_equalities else raw_points
        mask,normalized_constraints,inequalities,equalities,projection_equalities=feasible_mask(proposals,constraint_dicts,item.config_json["feature_ids"],feature_units,bounds)
    except OptimizationInputError as exc:
        message=str(exc); code=message.split(":",1)[0] if ":" in message else "UNSUPPORTED_CONSTRAINT"
        raise HTTPException(422,detail={"code":code,"message":message}) from exc
    points=proposals[mask]
    if not len(points):
        raise HTTPException(422,detail={"code":"NO_FEASIBLE_CANDIDATES","message":"No feasible candidate was found within the bounded search budget."})
    if len(points)>request.search_samples:
        points=points[:request.search_samples]
    try:
        mean,epistemic,aleatoric,total=model.predict_components(points)
        std=epistemic if request.prediction_type=="latent" else total
    except (OptimizationInputError,ValueError) as exc: raise HTTPException(422,str(exc)) from exc
    observed=np.asarray(item.config_json.get("observed_targets") or [],dtype=float)
    if not len(observed): raise HTTPException(409,"The saved model is missing its observed objective values")
    best=float(np.max(observed) if request.maximize else np.min(observed))
    if request.acquisition=="noisy_ei":
        try: scores=noisy_expected_improvement(model,points,samples=request.noisy_ei_samples,seed=request.seed,maximize=request.maximize)
        except OptimizationInputError as exc: raise HTTPException(422,str(exc)) from exc
    else:
        scores=acquisition(mean,std,float(best),request.acquisition,maximize=request.maximize,kappa=request.kappa,xi=request.xi)
    order=np.argsort(scores)[::-1]; chosen=[]
    known=np.asarray(model.x_train)*np.asarray(model.x_scale)+np.asarray(model.x_mean)
    scale=np.maximum(bounds[:,1]-bounds[:,0],1e-12)
    for idx in order:
        point=points[int(idx)]
        if np.min(np.linalg.norm((known-point)/scale,axis=1)) <= request.candidate_diversity: continue
        if any(np.linalg.norm((point-np.asarray(row["values"]))/scale) <= request.candidate_diversity for row in chosen): continue
        chosen.append({"rank":len(chosen)+1,"values":point.tolist(),"units":[x["unit"] for x in item.config_json["units"]["features"]],
            "predicted_mean":float(mean[int(idx)]),"epistemic_std":float(epistemic[int(idx)]),"aleatoric_std":float(aleatoric[int(idx)]),
            "total_predictive_std":float(total[int(idx)]),"predictive_std":float(std[int(idx)]),"acquisition_score":float(scores[int(idx)]),
            "prediction_type":request.prediction_type,"constraint_evaluation":[{"constraint_id":constraint.get("constraint_id") or f"constraint-{i+1}","status":"SATISFIED"} for i,constraint in enumerate(normalized_constraints)],
            "feasibility_status":"FEASIBLE","model_id":item.id,"dataset_hash":item.dataset_hash,"approval_status":"PENDING_RESEARCHER_REVIEW"})
        if len(chosen)>=request.candidate_count: break
    if not chosen: raise HTTPException(422,detail={"code":"NO_FEASIBLE_CANDIDATES","message":"No sufficiently diverse feasible candidate was generated."})
    config={"acquisition":request.acquisition,"bounds":bounds.tolist(),"bounds_units":feature_units,"maximize":request.maximize,"seed":request.seed,
        "search_samples":request.search_samples,"kappa":request.kappa,"xi":request.xi,"constraints":constraint_dicts,
        "candidate_diversity":request.candidate_diversity,"noisy_ei_samples":request.noisy_ei_samples,
        "prediction_type":request.prediction_type,"feasible_candidate_count":int(len(points)),"proposal_count":int(len(proposals)),"rejected_candidate_count":int(len(proposals)-len(points)),
        "target_id":item.config_json.get("target_id"),"units":item.config_json.get("units"),
        "constraint_evaluation":"All persisted recommendations satisfy the compiled deterministic constraints.",
        "reason":"Candidates are ranked by the selected acquisition within declared bounds and deterministic constraints; score is not an outcome guarantee."}
    saved=OptimizationRecommendationRun(model_run_id=item.id,topic_id=item.topic_id,acquisition=request.acquisition.upper(),config_json=config,candidates_json=chosen)
    db.add(saved); db.commit(); db.refresh(saved)
    return {"recommendation_id":saved.id,"model_id":item.id,"model_version":item.model_version,"dataset_hash":item.dataset_hash,
        "candidates":chosen,"feasible_candidate_count":len(points),"rejected_candidate_count":len(proposals)-len(points),
        "approval_status":saved.approval_status,"notice":"Candidates require researcher review. Acquisition score is not a predicted outcome or success probability."}


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


@router.post("/sandbox/benchmark/stage2")
def run_stage2_benchmark(kind:Literal["noisy","constrained","all"]="all",seed:int=7,budget:int=12,seeds:int=5,
    noise_level:float=0.08,topic_id:int=1,db:Session=Depends(get_db)):
    _topic(db,topic_id)
    try:
        return stage2_sandbox_benchmark(kind,seed,budget,seeds,noise_level)
    except OptimizationInputError as exc:
        raise HTTPException(422,str(exc)) from exc
