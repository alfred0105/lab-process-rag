"""Reproducible synthetic reliability experiments for Phase 5 Stage 4.

All labels are generated fixtures. This module never consumes final-evaluation
labels during model/threshold selection and never activates a model.
"""
from __future__ import annotations

import json
import pickle
import time
from collections import Counter
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.covariance import LedoitWolf
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import roc_auc_score, average_precision_score

from app.services.decision_head import ACTIONS, LearnedDecisionHead, calibration_metrics, rule_metrics, encode_state
from app.services.phase5_stage3 import SEEDS, generate_scenarios, split_groups
from app.services.scientific_state_v2 import (
    ACTION_NAMES, FEATURE_GROUPS, FEATURE_NAMES, FEATURE_SCHEMA, FEATURE_SCHEMA_VERSION_V2,
    ScientificStateError, StructuredDecisionHeadV2, _softmax, canonical_state, extract_features,
)

STAGE4_VERSION = "phase5-stage4-reliability-v1"
EVALUATION_PROTOCOL = "phase5-stage4-fresh-synthetic-protocol-v2"
RISK_TARGET = 0.20
ID_FPR_TARGET = 0.05


def _metric_report(y: list[str], probabilities: np.ndarray) -> dict[str, Any]:
    if not y:
        return {"status": "INSUFFICIENT_DATA", "sample_count": 0}
    probs=np.asarray(probabilities,dtype=float); actual=np.asarray([ACTION_NAMES.index(a) for a in y]); pred=probs.argmax(axis=1)
    cm=np.zeros((len(ACTION_NAMES),len(ACTION_NAMES)),dtype=int)
    for a,p in zip(actual,pred): cm[a,p]+=1
    per={}
    for i,name in enumerate(ACTION_NAMES):
        tp=int(cm[i,i]);fp=int(cm[:,i].sum()-tp);fn=int(cm[i,:].sum()-tp)
        per[name]={"support":int(cm[i,:].sum()),"predicted_count":int(cm[:,i].sum()),
            "precision":tp/max(1,tp+fp),"recall":tp/max(1,tp+fn),
            "false_positive":fp,"false_negative":fn,
            "high_confidence_wrong_prediction_count":int(np.sum((pred==i)&(probs.max(axis=1)>=.9)&(pred!=actual)))}
    cal=calibration_metrics(y,probs)
    balanced=float(np.mean([per[name]["recall"] for name in ACTION_NAMES if per[name]["support"]]))
    return {"sample_count":len(y),"accuracy":float(np.mean(pred==actual)),"balanced_accuracy":balanced,
        "macro_f1":float(np.mean([2*x["precision"]*x["recall"]/max(1e-12,x["precision"]+x["recall"]) for x in per.values()])),
        "per_class":per,"confusion_matrix":{"labels":list(ACTION_NAMES),"counts":cm.tolist()},
        "negative_log_likelihood":cal["negative_log_likelihood"],"brier_score":cal["brier_score"],
        "expected_calibration_error_10_bins":cal["expected_calibration_error_10_bins"],
        "reliability_bins":cal["reliability_bins"]}


def _align_tree_proba(model, x):
    raw=model.predict_proba(x); output=np.zeros((len(x),len(ACTION_NAMES)))
    for idx,label in enumerate(model.classes_): output[:,ACTION_NAMES.index(str(label))]=raw[:,idx]
    return output


def _hash_feature_records(rows, indexes=None):
    """Hash stable 8-decimal feature vectors to avoid platform float repr drift."""
    import hashlib
    selected=range(len(rows)) if indexes is None else indexes
    payload=[{"group":rows[i]["group_id"],"features":np.round(rows[i]["features_v2"],8).tolist(),"label":rows[i]["action"]} for i in selected]
    encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _temperature_from_calibration(probabilities, labels):
    """Fit a scalar temperature from calibration probabilities only."""
    y=np.asarray([ACTION_NAMES.index(a) for a in labels]);logits=np.log(np.maximum(probabilities,1e-12));best=(1.0,float("inf"))
    for temperature in np.geomspace(.35,4.0,120):
        calibrated=_softmax(logits/temperature);loss=float(-np.log(np.maximum(calibrated[np.arange(len(y)),y],1e-12)).mean())
        if loss<best[1]:best=(float(temperature),loss)
    return best[0]


def _apply_temperature(probabilities,temperature):
    return _softmax(np.log(np.maximum(probabilities,1e-12))/temperature)


def _wilson_upper(errors:int,n:int,z:float=1.96)->float:
    if n<=0: return 1.0
    p=errors/n;den=1+z*z/n
    return float((p+z*z/(2*n)+z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/den)


def _risk_threshold(probabilities:np.ndarray, labels:list[str], *, target:float=RISK_TARGET, min_covered:int=24):
    pred=probabilities.argmax(axis=1);actual=np.asarray([ACTION_NAMES.index(a) for a in labels]);conf=probabilities.max(axis=1)
    candidates=sorted(set(float(x) for x in conf),reverse=True)
    eligible=[]
    for threshold in candidates:
        mask=conf>=threshold;n=int(mask.sum());errors=int(np.sum(pred[mask]!=actual[mask]))
        upper=_wilson_upper(errors,n)
        if n>=min_covered and upper<=target: eligible.append((threshold,n,errors,upper))
    if not eligible:
        return {"status":"INSUFFICIENT_CALIBRATION_EVIDENCE","threshold":None,"target_risk":target,
            "calibration_count":len(labels),"minimum_covered":min_covered,"reason":"No threshold met the prespecified Wilson upper-risk bound."}
    # Lowest feasible threshold yields maximum coverage among thresholds satisfying bound.
    threshold,n,errors,upper=min(eligible,key=lambda item:item[0])
    return {"status":"SELECTED_ON_CALIBRATION_ONLY","threshold":threshold,"target_risk":target,
        "calibration_count":len(labels),"calibration_covered_count":n,"calibration_errors":errors,
        "calibration_risk":errors/n,"calibration_wilson_upper_95":upper,"minimum_covered":min_covered}


def _selective_eval(probabilities,labels,threshold):
    if threshold is None: return {"status":"INSUFFICIENT_CALIBRATION_EVIDENCE","coverage":0.0,"risk":None}
    actual=np.asarray([ACTION_NAMES.index(a) for a in labels]);pred=probabilities.argmax(axis=1);conf=probabilities.max(axis=1)
    mask=conf>=threshold;n=int(mask.sum())
    return {"status":"MEASURED_ON_HELD_OUT_DATA","coverage":float(mask.mean()),"covered_count":n,
        "risk":float(np.mean(pred[mask]!=actual[mask])) if n else None,
        "high_confidence_wrong_count":int(np.sum(mask&(pred!=actual)))}


def _risk_coverage(probabilities,labels):
    if not labels:return {"status":"INSUFFICIENT_DATA","curve":[],"per_predicted_class_at_median_confidence":{}}
    y=np.asarray([ACTION_NAMES.index(a) for a in labels]);pred=probabilities.argmax(axis=1);conf=probabilities.max(axis=1)
    curve=[]
    for threshold in sorted(set(float(v) for v in conf),reverse=True):
        mask=conf>=threshold
        if mask.any(): curve.append({"threshold":threshold,"coverage":float(mask.mean()),"risk":float(np.mean(pred[mask]!=y[mask])),"covered_count":int(mask.sum())})
    per_class={}
    for i,label in enumerate(ACTION_NAMES):
        mask=(conf>=float(np.median(conf)))&(pred==i)
        per_class[label]={"accepted_count":int(mask.sum()),"accepted_error_rate":float(np.mean(pred[mask]!=y[mask])) if mask.any() else None}
    return {"curve":curve,"per_predicted_class_at_median_confidence":per_class}


def _class_weights(y):
    counts=Counter(y);n=len(y);k=max(1,len(counts))
    return {label:n/(k*count) for label,count in counts.items()}


def _feature_diagnostics(records,fit_idx,test_idx,cal_idx=None):
    x=np.vstack([r["features_v2"] for r in records]);y=[r["action"] for r in records]
    fit=np.asarray(fit_idx);test=np.asarray(test_idx);features=[]
    for j,spec in enumerate(FEATURE_SCHEMA["features"]):
        col=x[fit,j]; item={"name":spec["name"],"group":spec["group"],"type":spec["type"],
            "fit_missing_rate":float(np.mean(col==1.0)) if spec["type"]=="missingness_mask" else None,
            "fit_constant":bool(np.ptp(col)<1e-12),"fit_unique_count":int(np.unique(col).size),
            "fit_mean":float(np.mean(col)),"fit_std":float(np.std(col)),
            "fit_to_test_mean_shift":float(abs(np.mean(col)-np.mean(x[test,j])))}
        features.append(item)
    varying=np.flatnonzero(np.std(x[fit],axis=0)>1e-12);corr=np.corrcoef(x[fit][:,varying].T);pairs=[]
    for i in range(len(varying)):
        for j in range(i+1,len(varying)):
            value=float(corr[i,j]) if np.isfinite(corr[i,j]) else 0.0
            if abs(value)>=.98:
                li=int(varying[i]);ri=int(varying[j])
                pairs.append({"left":FEATURE_NAMES[li],"right":FEATURE_NAMES[ri],"correlation":value})
    per_class={label:{"fit_count":sum(y[i]==label for i in fit),"evaluation_count":sum(y[i]==label for i in test)} for label in ACTION_NAMES}
    # Feature subset is predeclared from scientific context, never selected on evaluation metrics.
    core_groups={"experiment","process_conditions","measurements","analysis","provenance"}
    core_idx=[i for i,spec in enumerate(FEATURE_SCHEMA["features"]) if spec["group"] in core_groups]
    mask_idx=[i for i,spec in enumerate(FEATURE_SCHEMA["features"]) if spec["type"]=="missingness_mask" and spec["group"] in core_groups]
    group_features={}
    for group,indexes in FEATURE_GROUPS.items():
        group_features[group]=[FEATURE_NAMES.index(name) for name in FEATURE_NAMES if name.startswith(group+"__")]
    cal=np.asarray(cal_idx if cal_idx is not None else [],dtype=int)
    for label,item in per_class.items(): item["calibration_count"]=sum(y[i]==label for i in cal)
    for item,spec in zip(features,FEATURE_SCHEMA["features"]):
        item["source_path"]=spec["source_path"]
        item["scientific_interpretation"]="Versioned encoding of a declared state or recorded observation; this feature alone does not independently verify a physical measurement."
    return {"feature_count":len(FEATURE_NAMES),"fit_case_count":len(fit),"calibration_case_count":len(cal),"evaluation_case_count":len(test),
        "per_class_counts":per_class,"features":features,"high_correlation_pairs":pairs[:300],
        "high_correlation_pair_count":len(pairs),"predesignated_core_feature_indexes":core_idx,
        "predesignated_core_with_missing_masks_indexes":sorted(set(core_idx)|set(mask_idx)),"feature_group_indexes":group_features}


def _feature_quality_experiments(records,fit,cal,test,seed):
    x=np.vstack([r["features_v2"] for r in records]);y=[r["action"] for r in records]
    result={}
    variants={
        "all_153":None,
        "core_science_predesignated":[i for i,s in enumerate(FEATURE_SCHEMA["features"]) if s["group"] in {"experiment","process_conditions","measurements","analysis","provenance"}],
        "core_science_plus_missing_masks":[i for i,s in enumerate(FEATURE_SCHEMA["features"]) if s["group"] in {"experiment","process_conditions","measurements","analysis","provenance"}],
    }
    masks=[i for i,s in enumerate(FEATURE_SCHEMA["features"]) if s["type"]=="missingness_mask" and s["group"] in {"experiment","process_conditions","measurements","analysis","provenance"}]
    variants["core_science_plus_missing_masks"]=sorted(set(variants["core_science_predesignated"])|set(masks))
    for name,indexes in variants.items():
        xx=x.copy()
        if indexes is not None:
            excluded=sorted(set(range(x.shape[1]))-set(indexes));xx[:,excluded]=0.0
        model,_=StructuredDecisionHeadV2.fit(xx[fit],[y[i] for i in fit],seed=seed,epochs=150)
        model.calibrate(xx[cal],[y[i] for i in cal]);probs=model.predict_proba(xx[test])
        result[name]={"feature_count_active":int(x.shape[1] if indexes is None else len(indexes)),**_metric_report([y[i] for i in test],probs)}
    # Predeclared group ablations: each removes exactly one semantic group from V2.
    groups=("experiment","process_conditions","measurements","analysis","simulation","optimization","tool_readiness","pending_reviews","provenance")
    for group in groups:
        indexes=[i for i,spec in enumerate(FEATURE_SCHEMA["features"]) if spec["group"]!=group]
        xx=x.copy();xx[:,[i for i in range(x.shape[1]) if i not in indexes]]=0.0
        model,_=StructuredDecisionHeadV2.fit(xx[fit],[y[i] for i in fit],seed=seed,epochs=150)
        model.calibrate(xx[cal],[y[i] for i in cal]);probs=model.predict_proba(xx[test])
        result[f"ablate_{group}"]={"removed_group":group,"feature_count_active":len(indexes),**_metric_report([y[i] for i in test],probs)}
    # V1's fixed 18-feature contract is a separate representation comparator.
    from app.services.decision_head import encode_state
    x1=np.vstack([encode_state(r["features_v1_state"]) for r in records])
    v1,_=LearnedDecisionHead.fit(x1[fit],[y[i] for i in fit],seed=seed);v1.calibrate(x1[cal],[y[i] for i in cal])
    result["v1_18_features"]={"feature_count_active":int(x1.shape[1]),**_metric_report([y[i] for i in test],v1.predict_proba(x1[test]))}
    return result


def _ood_variant_matrix(x, feature_schema, seed):
    """Construct labeled shifts independently from the training/calibration rows."""
    rng=np.random.default_rng(seed);types={};base=np.asarray(x,dtype=float)
    numeric=[i for i,s in enumerate(feature_schema["features"]) if s["type"] in {"number","boolean"}]
    mask=[i for i,s in enumerate(feature_schema["features"]) if s["type"]=="missingness_mask"]
    if len(base)<1:return types
    extreme=base.copy();j=numeric[0];mu=float(np.mean(base[:,j]));sd=max(float(np.std(base[:,j])),.1);extreme[:,j]=mu+8*sd;types["extreme_feature_shift"]=extreme
    mild=base.copy();j=numeric[min(2,len(numeric)-1)];mild[:,j]+=1.5*max(float(np.std(base[:,j])),.1);types["mild_feature_shift"]=mild
    # Marginals remain plausible while cross-context pairing changes.
    combo=base.copy();perm=rng.permutation(len(combo));groups=list(FEATURE_GROUPS);mid=len(numeric)//2
    left=numeric[:mid];right=numeric[mid:]
    combo[:,left]=base[perm][:,left]
    combo[:,right]=base[np.roll(perm,1)][:,right]
    types["unseen_cross_context_combination"]=combo
    if mask:
        miss=base.copy();miss[:,mask[:max(1,len(mask)//3)]]=1.0;types["missingness_shift"]=miss
    categorical=[i for i,s in enumerate(feature_schema["features"]) if s["type"] in {"category","categorical","one_hot"}]
    if categorical:
        cat=base.copy();cat[:,categorical[0]]=1.0-cat[:,categorical[0]];types["categorical_shift"] = cat
    # Construction tests for semantic and provenance failures. They are vectors only;
    # enforcement remains the independent scientific validity policy.
    contradictory=base.copy()
    spec_names=[s["name"] for s in feature_schema["features"]]
    for name,value in (("optimization__optimization_ready",1.0),("optimization__gp_model_available",0.0),
                       ("optimization__constraint_validation_status__invalid",1.0)):
        if name in spec_names: contradictory[:,spec_names.index(name)]=value
    types["contradictory_scientific_state"]=contradictory
    unsupported=base.copy()
    for name in ("tool_readiness__optimization_available", "optimization__gp_model_available"):
        if name in spec_names: unsupported[:,spec_names.index(name)]=1.0
    types["unsupported_state_pattern"]=unsupported
    provenance=base.copy()
    for name in ("provenance__validity__INVALID", "provenance__data_quality_gate__BLOCK"):
        if name in spec_names: provenance[:,spec_names.index(name)]=1.0
    types["provenance_failure"]=provenance
    return types


def _score_ood_detectors(x_train,x_cal,x_test,ood_test,embedding_train,embedding_cal,embedding_test,embedding_ood,shift_slices=None):
    # All scalers/thresholds are derived from fit and a separate ID calibration set.
    mean=x_train.mean(axis=0);scale=x_train.std(axis=0);scale[scale<1e-8]=1.0
    ztr=np.clip((x_train-mean)/scale,-8,8);zcal=np.clip((x_cal-mean)/scale,-8,8);zid=np.clip((x_test-mean)/scale,-8,8);zood=np.clip((ood_test-mean)/scale,-8,8)
    numeric=[i for i,s in enumerate(FEATURE_SCHEMA["features"]) if s["type"] in {"number","boolean"}]
    detector_scores={
        "standardized_rms":(lambda a:np.sqrt(np.mean(np.minimum(np.abs(a),20)**2,axis=1)),zcal,zid,zood),
        "max_standardized_deviation":(lambda a:np.max(np.abs(a),axis=1),zcal,zid,zood),
    }
    # Mixed one-hot and missingness columns are excluded from raw KNN; categorical distance is not ordinal.
    knn=NearestNeighbors(n_neighbors=min(5,len(ztr)),algorithm="auto").fit(ztr[:,numeric])
    detector_scores["numeric_knn_distance"]=(lambda a:knn.kneighbors(a[:,numeric],return_distance=True)[0].mean(axis=1),zcal,zid,zood)
    # Low-dimensional, standardized branch embedding with shrinkage covariance.
    emb_mean=embedding_train.mean(axis=0);emb_scale=embedding_train.std(axis=0);emb_scale[emb_scale<1e-6]=1.0
    etr=(embedding_train-emb_mean)/emb_scale;ecal=(embedding_cal-emb_mean)/emb_scale;eID=(embedding_test-emb_mean)/emb_scale;eOOD=(embedding_ood-emb_mean)/emb_scale
    cov=LedoitWolf().fit(etr);inv=np.linalg.pinv(cov.covariance_)
    detector_scores["shrinkage_mahalanobis_embedding"]=(lambda a:np.sqrt(np.maximum(0,np.einsum('ij,jk,ik->i',a-cov.location_,inv,a-cov.location_))),ecal,eID,eOOD)
    ek=NearestNeighbors(n_neighbors=min(5,len(etr))).fit(etr)
    detector_scores["embedding_knn"]=(lambda a:ek.kneighbors(a,return_distance=True)[0].mean(axis=1),ecal,eID,eOOD)
    labels=np.r_[np.zeros(len(x_test),dtype=int),np.ones(len(ood_test),dtype=int)]
    result={}
    for name,(score,cal,idtest,oodtest) in detector_scores.items():
        timer=time.perf_counter()
        cal_score=score(cal);threshold=float(np.quantile(cal_score,1-ID_FPR_TARGET,method="higher"))
        idscore=score(idtest);oodscore=score(oodtest);all_scores=np.r_[idscore,oodscore]
        pred=all_scores>=threshold
        latency=(time.perf_counter()-timer)*1000/max(1,len(idscore)+len(oodscore))
        tpr95_threshold=float(np.quantile(idscore,.05,method="lower"))
        result[name]={"threshold":threshold,"threshold_source":"ID_CALIBRATION_ONLY","calibration_count":len(cal),
            "id_false_positive_rate":float(np.mean(idscore>=threshold)),"shift_detection_rate":float(np.mean(oodscore>=threshold)),
            "auroc":float(roc_auc_score(labels,all_scores)) if len(np.unique(labels))>1 else None,
            "auprc":float(average_precision_score(labels,all_scores)) if len(np.unique(labels))>1 else None,
            "tpr_at_prespecified_id_fpr":float(np.mean(oodscore>=threshold)),
            "fpr_at_95_percent_tpr_threshold":tpr95_threshold,
            "fpr_at_95_percent_tpr":float(np.mean(idscore>=tpr95_threshold)),
            "ood_detection_latency_ms_per_case":latency,"id_score_quantiles":{str(q):float(np.quantile(idscore,q)) for q in (0,.5,.9,.95,.99,1)},
            "ood_score_quantiles":{str(q):float(np.quantile(oodscore,q)) for q in (0,.5,.9,.95,.99,1)},
            "id_count":len(idscore),"ood_count":len(oodscore)}
        result[name]["per_shift_detection_rate"]={shift:float(np.mean(oodscore[start:end]>=threshold)) for shift,start,end in (shift_slices or [])}
        result[name]["counterfactual_ood_abstention_rate_if_detector_were_wired_to_abstain"]=result[name]["shift_detection_rate"]
        result[name]["counterfactual_id_abstention_rate_if_detector_were_wired_to_abstain"]=result[name]["id_false_positive_rate"]
        result[name]["abstention_semantics"]="Counterfactual detector-flag rate only; detector is not connected to or changing the safe-action policy."
    return result


def _make_fresh_final(seed=90421,samples=576):
    """Separate synthetic rule/data recipe reserved for one final evaluation run."""
    from app.services.phase5_stage3 import _blank_context
    rng=np.random.default_rng(seed);records=[]
    for i in range(samples):
        state=_blank_context()
        # New composition rules and ranges; exact recipe is independent of Stage 3's families.
        temp=float(rng.uniform(22,185)); duration=float(rng.uniform(4,480)); concentration=float(rng.uniform(.002,1.2))
        state["experiment"].update({"process_step_count":int(rng.integers(1,12)),"required_condition_completeness":float(rng.uniform(.2,1)),
            "required_conditions_known":bool(rng.random()>.12),"method_version_available":bool(rng.random()>.08)})
        state["process_conditions"]={"items":[{"name":"temperature","dimension":"temperature","value":temp,"unit":"degC"},
            {"name":"duration","dimension":"time","value":duration,"unit":"min"},
            {"name":"concentration","dimension":"concentration","value":concentration,"unit":"mol/L"}]}
        meas=state["measurements"]
        analysis=state["analysis"];sim=state["simulation"];opt=state["optimization"];prov=state["provenance"];tools=state["tool_readiness"]
        case_type=str(rng.choice(("missing","analysis","simulation","optimization","review","ambiguous"),p=(.18,.2,.18,.18,.14,.12)))
        if case_type=="missing":
            prov["missing_required_information_count"]=int(rng.integers(1,5));prov["validity"]="UNKNOWN";meas["measurement_completeness"]=float(rng.uniform(0,.45))
        elif case_type=="analysis":
            analysis.update({"available_analysis_type_count":int(rng.integers(1,4)),"completed_analysis_count":0,"required_input_available":True});tools["analysis_available"]=True
        elif case_type=="simulation":
            approval=bool(rng.random()<.25)
            sim.update({"available_tool_count":1,"input_ready":True,"researcher_approval_required":approval,"approval_status":"PENDING" if approval else "NOT_REQUIRED"});tools["simulation_available"]=True
        elif case_type=="optimization":
            opt.update({"gp_model_available":True,"gp_model_valid":True,"training_data_sufficient":True,"prediction_uncertainty_available":True,
                "optimization_ready":True,"constraint_validation_status":"VALID"});tools["optimization_available"]=True
        elif case_type=="review":
            prov.update({"validity":"INVALID","data_quality_gate":"BLOCK","review_status":"PENDING"});meas["unit_compatibility"]="INCOMPATIBLE"
        elif case_type=="ambiguous":
            state["experiment"]["required_conditions_known"]=False
            opt.update({"optimization_ready":True,"gp_model_available":False})
        # Add realistic nuisance variation, keeping the label rule explicit and deterministic.
        meas["accepted_observation_count"]=int(rng.integers(0,18));meas["pending_observation_count"]=int(rng.integers(0,3))
        meas["measurement_completeness"]=float(np.clip(meas.get("measurement_completeness",rng.uniform(.25,1)),0,1))
        # Derive synthetic labels from state facts, never from the generation branch.
        if meas.get("unit_compatibility")=="INCOMPATIBLE" or prov.get("data_quality_gate")=="BLOCK" or prov.get("validity")=="INVALID": action="REQUEST_REVIEW"
        elif prov.get("missing_required_information_count",0)>0 or not state["experiment"]["required_conditions_known"]: action="REQUEST_INFORMATION"
        elif opt.get("optimization_ready") and opt.get("gp_model_valid") and opt.get("constraint_validation_status")=="VALID" and meas["accepted_observation_count"]>=4: action="OPTIMIZE"
        elif sim.get("input_ready") and not sim.get("researcher_approval_required"): action="SIMULATE"
        elif analysis.get("completed_analysis_count",0)==0 and tools.get("analysis_available"): action="ANALYZE"
        else: action="ABSTAIN"
        if rng.random()<.06: action=str(rng.choice(("REQUEST_REVIEW","ABSTAIN")))
        state["source_provenance"]={"case_group_id":f"stage4-final-{seed}-{i}","recipe_version":"independent-composition-v1"}
        vector,meta=extract_features(state)
        v1={"accepted_observation_count":meas["accepted_observation_count"],"measurement_completeness":meas["measurement_completeness"],
            "available_analysis_count":analysis.get("completed_analysis_count",0),"pending_analysis_count":analysis.get("pending_analysis_count",0),
            "analysis_tool_available":tools.get("analysis_available"),"available_simulation_count":sim.get("completed_run_count",0),
            "simulation_tool_available":tools.get("simulation_available"),"gp_model_ready":opt.get("gp_model_available"),
            "optimization_ready":opt.get("optimization_ready"),"optimization_tool_available":tools.get("optimization_available"),
            "pending_review_count":sum(state["pending_reviews"].values()),"missing_required_information_count":prov.get("missing_required_information_count",0),
            "provenance_valid":prov.get("validity")=="VALID","validation_status":meas["measurement_completeness"],"workflow_state":0.0}
        records.append({"state":state,"features_v2":vector,"features_v1_state":v1,"action":action,
            "group_id":f"stage4-final-{seed}-{i}","scenario_family":"independent_composition"})
    return records


def _fusion_fit(x,y,seed,hidden=32,epochs=180,lr=.02):
    base,_=StructuredDecisionHeadV2.fit(x,y,seed=seed,epochs=180)
    reps=base.representations(x);rng=np.random.default_rng(seed+901);w1=rng.normal(0,.08,(reps.shape[1],hidden));b1=np.zeros(hidden)
    w2=rng.normal(0,.05,(hidden,len(ACTION_NAMES)));b2=np.zeros(len(ACTION_NAMES));yi=np.asarray([ACTION_NAMES.index(v) for v in y]);losses=[]
    for _ in range(epochs):
        h=np.tanh(reps@w1+b1);p=_softmax(h@w2+b2);g=p.copy();g[np.arange(len(yi)),yi]-=1;g/=len(yi)
        losses.append(float(-np.log(np.maximum(p[np.arange(len(yi)),yi],1e-12)).mean()))
        gh=g@w2.T*(1-h*h);w2-=lr*(h.T@g+1e-4*w2);b2-=lr*g.sum(0);w1-=lr*(reps.T@gh+1e-4*w1);b1-=lr*gh.sum(0)
    return {"base":base,"w1":w1,"b1":b1,"w2":w2,"b2":b2,"hidden":hidden,"loss":losses}


def _fusion_proba(model,x):
    h=np.tanh(model["base"].representations(x)@model["w1"]+model["b1"]);return _softmax(h@model["w2"]+model["b2"])


def _timed(predict,x,iterations=150):
    start=time.perf_counter()
    for _ in range(iterations):predict(x)
    return (time.perf_counter()-start)*1000/iterations


def run_stage4_suite(*,seeds=SEEDS,samples_per_seed=576,final_samples=576):
    """Run development comparisons and one untouched, separate-rule final evaluation."""
    if len(seeds)<5:raise ScientificStateError("Stage 4 requires at least five development seeds")
    development=[];feature_samples=[];ood_seed_reports=[];selective_reports=[]
    for seed in seeds:
        rows=generate_scenarios(int(seed),samples_per_seed);groups=np.asarray([r["group_id"] for r in rows]);fit,cal,test=split_groups(groups,seed=int(seed))
        x2=np.vstack([r["features_v2"] for r in rows]);y=[r["action"] for r in rows]
        x1=np.vstack([encode_state(r["features_v1_state"]) for r in rows])
        yfit=[y[i] for i in fit];ycal=[y[i] for i in cal];ytest=[y[i] for i in test]
        xfit2=x2[fit];xcal2=x2[cal];xtest2=x2[test]
        entry={"seed":int(seed),"counts":{"fit":len(fit),"calibration":len(cal),"evaluation":len(test),
            "fit_groups":len(set(groups[fit])),"calibration_groups":len(set(groups[cal])),"evaluation_groups":len(set(groups[test]))},"models":{}}
        from app.services.decision_head import ACTIONS as V1_ACTIONS
        start=time.perf_counter();v1,_=LearnedDecisionHead.fit(x1[fit],yfit,seed=int(seed));v1.calibrate(x1[cal],ycal);v1time=(time.perf_counter()-start)*1000
        p1=v1.predict_proba(x1[test]);entry["models"]["v1"]={**_metric_report(ytest,p1),"fit_runtime_ms":v1time,
            "inference_latency_ms_per_case":_timed(lambda xx:v1.predict_proba(xx),x1[test[:1]]),
            "model_size_bytes":len(json.dumps(v1.to_dict(),separators=(",",":")).encode()),"parameter_count":int(sum(a.size for a in (v1.mean,v1.scale,v1.hidden_weight,v1.hidden_bias,v1.output_weight,v1.output_bias)))}
        start=time.perf_counter();v2,_=StructuredDecisionHeadV2.fit(xfit2,yfit,seed=int(seed));v2.calibrate(xcal2,ycal);v2time=(time.perf_counter()-start)*1000
        p2=v2.predict_proba(xtest2);p2_uncal=v2.predict_proba(xtest2,calibrated=False);entry["models"]["v2"]={**_metric_report(ytest,p2),"uncalibrated_metrics":_metric_report(ytest,p2_uncal),"fit_runtime_ms":v2time,
            "inference_latency_ms_per_case":_timed(lambda xx:v2.predict_proba(xx),xtest2[:1]),
            "model_size_bytes":len(json.dumps(v2.to_dict(),separators=(",",":")).encode()),"parameter_count":v2.parameter_count,
            "temperature":v2.temperature,"legacy_confidence_threshold":v2.confidence_threshold}
        state_test=[rows[i]["features_v1_state"] for i in test];rulepred=rule_metrics(state_test,ytest)["predictions"]
        rule_probs=np.zeros((len(test),len(ACTION_NAMES)))
        for j,label in enumerate(rulepred):rule_probs[j,ACTION_NAMES.index(label)]=1.0
        entry["models"]["rule"]={**_metric_report(ytest,rule_probs),"fit_runtime_ms":0,"inference_latency_ms_per_case":None,"model_size_bytes":None,"parameter_count":None}
        yi=np.asarray([ACTION_NAMES.index(v) for v in y]);tree=HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=15,l2_regularization=1.0,random_state=int(seed))
        start=time.perf_counter();tree.fit(xfit2,yfit);tree_time=(time.perf_counter()-start)*1000
        rawtree=_align_tree_proba(tree,xtest2);treecal=_align_tree_proba(tree,xcal2);tree_temp=_temperature_from_calibration(treecal,ycal);ptree=_apply_temperature(rawtree,tree_temp)
        entry["models"]["hist_gradient_boosting"]={**_metric_report(ytest,ptree),"fit_runtime_ms":tree_time,"calibration_temperature":tree_temp,
            "inference_latency_ms_per_case":_timed(lambda xx:_align_tree_proba(tree,xx),xtest2[:1]),
            "model_size_bytes":len(pickle.dumps(tree,protocol=pickle.HIGHEST_PROTOCOL)),"parameter_count":None}
        # Loss comparison; inverse-frequency weights are computed only from fit labels.
        weights=_class_weights(yfit);sample_w=np.asarray([weights[label] for label in yfit],dtype=float)
        weighted,_=StructuredDecisionHeadV2.fit(xfit2,yfit,seed=int(seed),sample_weights=sample_w)
        pw=weighted.predict_proba(xtest2);entry["models"]["v2_class_weighted"]=_metric_report(ytest,pw)
        # Group-aware balanced sampling: one group per selected row here, preserving the group as the sampling unit.
        by_class={label:[i for i,idx in enumerate(fit) if y[idx]==label] for label in ACTION_NAMES}
        rng=np.random.default_rng(int(seed)+777);target=max(1,min(len(v) for v in by_class.values() if v))
        chosen=np.concatenate([rng.choice(v,size=target,replace=len(v)<target) for v in by_class.values() if v])
        balanced,_=StructuredDecisionHeadV2.fit(xfit2[chosen],[yfit[i] for i in chosen],seed=int(seed),epochs=220)
        pb=balanced.predict_proba(xtest2);entry["models"]["v2_group_balanced_sampling"]=_metric_report(ytest,pb)
        # Context interaction experiment. Branch representation is held fixed and only the small fusion head is trained.
        fusion=_fusion_fit(xfit2,yfit,int(seed),hidden=32);pf=_fusion_proba(fusion,xtest2)
        fusionmetric=_metric_report(ytest,pf);fusion_size=len(json.dumps({k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in fusion.items() if k!="base"},separators=(",",":")).encode())+len(json.dumps(fusion["base"].to_dict(),separators=(",",":")).encode())
        entry["models"]["v2_fusion_32"]={**fusionmetric,"parameter_count":int(fusion["w1"].size+fusion["b1"].size+fusion["w2"].size+fusion["b2"].size+fusion["base"].parameter_count),"model_size_bytes":fusion_size}
        # Feature selection is predeclared, not selected using held-out outcomes.
        entry["feature_subsets"]=_feature_quality_experiments(rows,fit,cal,test,int(seed))
        feature_samples.append(_feature_diagnostics(rows,fit,test,cal))
        # Risk-controlled confidence threshold: choose on calibration only, assess once on evaluation.
        probs_cal=v2.predict_proba(xcal2);threshold_report=_risk_threshold(probs_cal,ycal)
        selective_reports.append({"seed":int(seed),"threshold_selection":threshold_report,"risk_coverage_curve":_risk_coverage(p2,ytest),
            "scenario_family_risk_coverage":{family:_risk_coverage(p2[[j for j,i in enumerate(test) if rows[i]["scenario_family"]==family]],[ytest[j] for j,i in enumerate(test) if rows[i]["scenario_family"]==family]) for family in sorted({rows[i]["scenario_family"] for i in test})},
            "evaluation":_selective_eval(p2,ytest,threshold_report.get("threshold")),
            "legacy_threshold":v2.confidence_threshold,"legacy_selective_evaluation":_selective_eval(p2,ytest,v2.confidence_threshold)})
        # Fresh ID/OOD detector comparison uses separate ID calibration and OOD shifts.
        embed_train=v2.representations(xfit2);embed_cal=v2.representations(xcal2);embed_test=v2.representations(xtest2)
        shifts=_ood_variant_matrix(xtest2,FEATURE_SCHEMA,int(seed));shift_names=list(shifts)
        ood=np.concatenate(list(shifts.values()),axis=0);ood_emb=v2.representations(ood)
        shift_slices=[];offset=0
        for shift_name,shift_rows in shifts.items(): shift_slices.append((shift_name,offset,offset+len(shift_rows)));offset+=len(shift_rows)
        detector=_score_ood_detectors(xfit2,xcal2,xtest2,ood,embed_train,embed_cal,embed_test,ood_emb,shift_slices)
        legacy_distances={"fit":v2.training_distances(xfit2),"calibration":v2.training_distances(xcal2),
            "evaluation":v2.training_distances(xtest2),"constructed_shift":v2.training_distances(ood)}
        legacy_quantiles={partition:{str(q):float(np.quantile(values,q)) for q in (0,.5,.9,.95,.99,1)} for partition,values in legacy_distances.items()}
        ood_seed_reports.append({"seed":int(seed),"shift_types":{k:len(v) for k,v in shifts.items()},"detectors":detector,
            "legacy_v2_shift_probe": {"threshold":v2.trained_distance_threshold,"threshold_formula":"max(6, 1.25 * fit_distance_q99)",
                "distance_quantiles":legacy_quantiles,
                "id_false_positive_count":int(np.sum(legacy_distances["evaluation"]>v2.trained_distance_threshold)),
                "id_false_positive_rate":float(np.mean(legacy_distances["evaluation"]>v2.trained_distance_threshold)),
                "constructed_shift_detection_count":int(np.sum(legacy_distances["constructed_shift"]>v2.trained_distance_threshold)),
                "constructed_shift_detection_rate":float(np.mean(legacy_distances["constructed_shift"]>v2.trained_distance_threshold))}})
        # Raw vs safe action on a sample of held-out states; validity/OOD override is separately counted.
        safe=[v2.predict_safe(rows[i]["state"]) for i in test]
        entry["raw_vs_safe"]={"raw_accuracy":entry["models"]["v2"]["accuracy"],
            "final_action_accuracy":float(np.mean([r["action"]==ytest[j] for j,r in enumerate(safe)])),
            "override_count":sum(bool(r["safety_override"]) for r in safe),
            "override_reasons":dict(Counter(r["safety_override_reason"] for r in safe if r["safety_override_reason"])),
            "final_actions":dict(Counter(r["action"] for r in safe)),"evaluation_labels":dict(Counter(ytest))}
        development.append(entry)
    # Candidate list/protocol is frozen before new final data generation and run once.
    final_records=_make_fresh_final(samples=final_samples);fx2=np.vstack([r["features_v2"] for r in final_records]);fy=[r["action"] for r in final_records]
    fresh_groups=[r["group_id"] for r in final_records];ffit,fcal,ftest=split_groups(fresh_groups,seed=190731)
    # Train a fixed comparison set on the fresh protocol's training/validation rows; never fit on final test.
    # Selection is based on development medians; final evaluation is descriptive and immutable.
    candidates={"rule":None,"v1":None,"v2":None,"hist_gradient_boosting":None,
        "v2_class_weighted":None,"v2_group_balanced_sampling":None,"v2_core_subset":None,"v2_fusion_32":None}
    from app.services.decision_head import ACTIONS as _unused
    fx1=np.vstack([encode_state(r["features_v1_state"]) for r in final_records])
    fyfit=[fy[i] for i in ffit];fycal=[fy[i] for i in fcal];fytest=[fy[i] for i in ftest]
    v1_final,_=LearnedDecisionHead.fit(fx1[ffit],fyfit,seed=190731);v1_final.calibrate(fx1[fcal],fycal);candidates["v1"]=v1_final.predict_proba(fx1[ftest])
    v2_final,_=StructuredDecisionHeadV2.fit(fx2[ffit],fyfit,seed=190731);v2_final.calibrate(fx2[fcal],fycal);candidates["v2"]=v2_final.predict_proba(fx2[ftest])
    final_weights=_class_weights(fyfit);weighted_final,_=StructuredDecisionHeadV2.fit(fx2[ffit],fyfit,seed=190731,sample_weights=np.asarray([final_weights[label] for label in fyfit]));weighted_final.calibrate(fx2[fcal],fycal);candidates["v2_class_weighted"]=weighted_final.predict_proba(fx2[ftest])
    final_by_class={label:[i for i,idx in enumerate(ffit) if fy[idx]==label] for label in ACTION_NAMES};final_target=max(1,min(len(rows) for rows in final_by_class.values() if rows));final_rng=np.random.default_rng(190731+777)
    final_chosen=np.concatenate([final_rng.choice(rows,size=final_target,replace=len(rows)<final_target) for rows in final_by_class.values() if rows])
    balanced_final,_=StructuredDecisionHeadV2.fit(fx2[ffit][final_chosen],[fyfit[i] for i in final_chosen],seed=190731,epochs=220);balanced_final.calibrate(fx2[fcal],fycal);candidates["v2_group_balanced_sampling"]=balanced_final.predict_proba(fx2[ftest])
    core_indexes=[i for i,spec in enumerate(FEATURE_SCHEMA["features"]) if spec["group"] in {"experiment","process_conditions","measurements","analysis","provenance"} or spec["type"]=="missingness_mask" and spec["group"] in {"experiment","process_conditions","measurements","analysis","provenance"}]
    core_x=fx2.copy();core_x[:,sorted(set(range(fx2.shape[1]))-set(core_indexes))]=0.0
    core_final,_=StructuredDecisionHeadV2.fit(core_x[ffit],[fy[i] for i in ffit],seed=190731);core_final.calibrate(core_x[fcal],fycal);candidates["v2_core_subset"]=core_final.predict_proba(core_x[ftest])
    fusion_final=_fusion_fit(fx2[ffit],fyfit,190731,hidden=32);fusion_cal=_fusion_proba(fusion_final,fx2[fcal]);fusion_temp=_temperature_from_calibration(fusion_cal,fycal);candidates["v2_fusion_32"]=_apply_temperature(_fusion_proba(fusion_final,fx2[ftest]),fusion_temp)
    tree_final=HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=15,l2_regularization=1.0,random_state=190731).fit(fx2[ffit],fyfit)
    final_tree_cal=_align_tree_proba(tree_final,fx2[fcal]);final_tree_temp=_temperature_from_calibration(final_tree_cal,fycal)
    candidates["hist_gradient_boosting"]=_apply_temperature(_align_tree_proba(tree_final,fx2[ftest]),final_tree_temp)
    fstates=[final_records[i]["features_v1_state"] for i in ftest];rp=rule_metrics(fstates,fytest)["predictions"]
    rprob=np.zeros((len(ftest),len(ACTION_NAMES)))
    for i,label in enumerate(rp):rprob[i,ACTION_NAMES.index(label)]=1.0
    candidates["rule"]=rprob
    final_metrics={name:_metric_report(fytest,prob) for name,prob in candidates.items()}
    evaluation_hash=_hash_feature_records(final_records,ftest)
    development_summary={}
    names=sorted({name for row in development for name in row["models"]})
    for name in names:
        vals=[r["models"][name]["macro_f1"] for r in development]
        development_summary[name]={"macro_f1_mean":float(np.mean(vals)),"macro_f1_sd":float(np.std(vals,ddof=1)),
            "accuracy_mean":float(np.mean([r["models"][name]["accuracy"] for r in development])),
            "balanced_accuracy_mean":float(np.mean([r["models"][name]["balanced_accuracy"] for r in development]))}
    core_rows=[r["feature_subsets"]["core_science_plus_missing_masks"] for r in development]
    development_summary["v2_core_subset"]={"macro_f1_mean":float(np.mean([r["macro_f1"] for r in core_rows])),
        "macro_f1_sd":float(np.std([r["macro_f1"] for r in core_rows],ddof=1)),
        "accuracy_mean":float(np.mean([r["accuracy"] for r in core_rows])),
        "balanced_accuracy_mean":float(np.mean([r["balanced_accuracy"] for r in core_rows]))}
    # Prespecified conservative selection: prefer the best mean macro-F1 among candidates
    # whose development accuracy is not more than 0.05 below the best; ties prefer compact V1/V2/rule.
    main_candidates=["rule","v1","v2","v2_class_weighted","v2_group_balanced_sampling","v2_core_subset","v2_fusion_32","hist_gradient_boosting"]
    best_f1=max(development_summary[n]["macro_f1_mean"] for n in main_candidates)
    best_accuracy=max(development_summary[n]["accuracy_mean"] for n in main_candidates)
    eligible=[n for n in main_candidates if development_summary[n]["accuracy_mean"]>=best_accuracy-.05]
    selected=max(eligible,key=lambda n:(development_summary[n]["macro_f1_mean"],-main_candidates.index(n)))
    return {
        "diagnostics":{"report_version":STAGE4_VERSION,"data_status":"SYNTHETIC_SOFTWARE_EVALUATION_ONLY",
            "baseline_metrics_by_seed":[{"seed":r["seed"],"models":{k:v for k,v in r["models"].items() if k in {"rule","v1","v2","hist_gradient_boosting"}},"raw_vs_safe":r["raw_vs_safe"]} for r in development],
            "class_distribution_by_seed":[{"seed":r["seed"],"counts":r["counts"]} for r in development],
            "feature_quality_by_seed":feature_samples,
            "feature_ablation_and_subset_by_seed":[{"seed":r["seed"],"subsets":r["feature_subsets"]} for r in development],
            "root_cause_findings":{"class_imbalance":"Measured through per-class support and weighted/group-balanced variants; no causal claim.",
                "feature_redundancy":"Statistics and predictive ablations are descriptive; correlation does not establish harm.",
                "encoder":"Compared against V1, rule and HistGradientBoosting plus a small fusion head.",
                "ood_threshold":"Compared legacy threshold to calibration-quantile multi-detectors; see reliability report.",
                "generalization":"Fresh evaluation uses a separate rule/data recipe; still synthetic and not laboratory evidence."}},
        "comparison":{"report_version":STAGE4_VERSION,"schema_version":FEATURE_SCHEMA_VERSION_V2,"seeds":[int(s) for s in seeds],
            "per_seed":development,"summary":development_summary,"selection_rule":"best development Macro-F1 among rule/V1/V2/tree candidates whose mean accuracy is within 0.05 of best candidate; no final-set tuning."},
        "reliability":{"report_version":STAGE4_VERSION,"risk_target":RISK_TARGET,"id_fpr_target":ID_FPR_TARGET,
            "ood_detectors_by_seed":ood_seed_reports,"selective_prediction_by_seed":selective_reports,
            "safety_reasoning":"Scientific validity gates, distribution shift, and low classification confidence are reported separately.",
            "limitation":"Constructed synthetic shifts do not cover all deployment OOD states."},
        "final_evaluation":{"report_version":STAGE4_VERSION,"protocol_version":EVALUATION_PROTOCOL,
            "dataset_hash":_hash_feature_records(final_records),
            "evaluation_hash":evaluation_hash,
            "sample_count":len(ftest),"fit_count":len(ffit),"calibration_count":len(fcal),"fit_groups":len(set(fresh_groups[i] for i in ffit)),
            "calibration_groups":len(set(fresh_groups[i] for i in fcal)),"evaluation_groups":len(set(fresh_groups[i] for i in ftest)),
            "tree_calibration_temperature_from_calibration_only":final_tree_temp,
            "same_group_overlap":False,"fixed_candidate_models":main_candidates,"metrics":final_metrics,
            "candidate_selected_on_development_only":selected,"development_summary":{n:development_summary[n] for n in main_candidates},
            "selected_baseline_contract":{"model_name":selected,"model_version":{"v1":"learned-decision-mlp-v1","v2":"learned-decision-structured-v2","hist_gradient_boosting":"sklearn-hist-gradient-boosting-stage4","rule":"RuleBasedDecisionPolicy","v2_class_weighted":"learned-decision-structured-v2-weighted","v2_group_balanced_sampling":"learned-decision-structured-v2-balanced","v2_core_subset":"learned-decision-structured-v2-core-subset","v2_fusion_32":"learned-decision-structured-v2-fusion32"}[selected],
                "feature_schema_version":FEATURE_SCHEMA_VERSION_V2 if selected not in {"v1","rule"} else "scientific-decision-features-v1" if selected=="v1" else None,
            "dataset_hash":_hash_feature_records(final_records),
            "evaluation_hash":evaluation_hash,
                "calibration_policy":"Temperature scaling fitted on calibration partition only; evaluated once on fresh synthetic holdout.",
                "ood_policy":"No candidate was activated. OOD detector candidates remain diagnostic; thresholds use ID calibration quantiles only.",
                "selection_reason":"Selected solely by development-seed macro-F1 among candidates within 0.05 of best mean development accuracy.",
                "shadow_only":True,"artifact_promotion":"NONE_SYNTHETIC_EVIDENCE_NOT_FOR_ACTIVATION",
                "known_failure_modes":["Synthetic-only labels and domains","OOD shifts are constructed fixtures","No reviewed lab corpus","Tree model is not a Phase 6 Transformer-compatible head"],
                "serialization_contract":"No production artifact created or activated; candidate version/schema metadata is diagnostic only."},
            "limitations":["All data and labels in this report are synthetic software fixtures.","Final-set metrics are a single run and must not be used to tune candidates.","This does not establish scientific or laboratory decision accuracy."]},
    }
