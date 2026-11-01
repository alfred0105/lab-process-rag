"""Grouped synthetic diagnostics for Phase 6 heads, calibration and layer exits.

This is a research-free software experiment. Synthetic labels are only scenario
contracts and must not be interpreted as laboratory decision accuracy.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, recall_score
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.decision_head import ACTIONS
from app.services.phase5_stage3 import generate_scenarios
from app.services.phase5_stage4 import _risk_threshold, _temperature_from_calibration, _wilson_upper
from app.services.phase6_hybrid import (MODEL_ID, MODEL_REVISION, CONTEXT_ADAPTER_VERSION,
    SharedTransformerBackbone, _training_context, _OodScorer)


def _split_groups(rows, seed=6317):
    groups=sorted({row["group_id"] for row in rows})
    rng=np.random.default_rng(seed);rng.shuffle(groups)
    n=len(groups);a=round(n*.60);b=round(n*.15);c=round(n*.10)
    fit_groups=set(groups[:a]);cal_groups=set(groups[a:a+b]);controller_groups=set(groups[a+b:a+b+c])
    test_groups=set(groups[a+b+c:])
    parts=[np.asarray([i for i,row in enumerate(rows) if row["group_id"] in selected],dtype=int)
           for selected in (fit_groups,cal_groups,controller_groups,test_groups)]
    group_parts=[{rows[i]["group_id"] for i in part} for part in parts]
    if any(group_parts[i]&group_parts[j] for i in range(4) for j in range(i+1,4)):
        raise RuntimeError("Grouped fit/calibration/controller/final split overlap")
    return parts


def _metrics(y, pred):
    return {"count":len(y),"accuracy":float(accuracy_score(y,pred)),
        "balanced_accuracy":float(balanced_accuracy_score(y,pred)),
        "macro_f1":float(f1_score(y,pred,labels=list(range(len(ACTIONS))),average="macro",zero_division=0)),
        "per_class_recall":{name:float(value) for name,value in zip(ACTIONS,
            recall_score(y,pred,labels=list(range(len(ACTIONS))),average=None,zero_division=0))}}


def _route(probabilities_by_layer, ood_by_layer, thresholds, layer_numbers, ood_thresholds):
    n=len(next(iter(probabilities_by_layer.values())))
    predicted=np.empty(n,dtype=int); exits=np.full(n,layer_numbers[-1],dtype=int)
    for row in range(n):
        selected=layer_numbers[-1]
        for layer in layer_numbers[:-1]:
            probs=probabilities_by_layer[layer][row]
            threshold=thresholds[layer]
            if threshold is not None and not ood_by_layer[layer][row] and float(probs.max())>=threshold:
                selected=layer;break
        exits[row]=selected
        predicted[row]=int(probabilities_by_layer[selected][row].argmax())
    return predicted,exits


def _train_head(x_fit,y_fit,architecture,seed=4097,epochs=30):
    torch.manual_seed(seed)
    if architecture=="linear":
        head=nn.Linear(x_fit.shape[1],len(ACTIONS))
        weight_decay=.001;dropout=0.0
    elif architecture=="mlp":
        head=nn.Sequential(nn.Linear(x_fit.shape[1],128),nn.GELU(),nn.Linear(128,len(ACTIONS)))
        weight_decay=0.0;dropout=0.0
    elif architecture=="mlp_regularized":
        head=nn.Sequential(nn.Linear(x_fit.shape[1],128),nn.GELU(),nn.Dropout(.10),nn.Linear(128,len(ACTIONS)))
        weight_decay=.01;dropout=.10
    else: raise ValueError(architecture)
    head.train();opt=torch.optim.AdamW(head.parameters(),lr=.0015,weight_decay=weight_decay)
    loss=nn.CrossEntropyLoss();x=torch.as_tensor(x_fit,dtype=torch.float32);y=torch.as_tensor(y_fit,dtype=torch.long)
    generator=torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        order=torch.randperm(len(y),generator=generator)
        for start in range(0,len(y),32):
            ids=order[start:start+32];opt.zero_grad(set_to_none=True)
            value=loss(head(x[ids]),y[ids]);value.backward();opt.step()
    head.eval()
    return head,{"epochs":epochs,"weight_decay":weight_decay,"dropout":dropout,
        "head_parameters":sum(p.numel() for p in head.parameters())}


def _predict_prob(head, x, temperature=1.0):
    with torch.inference_mode(): logits=head(torch.as_tensor(x,dtype=torch.float32)).numpy()/temperature
    logits=logits-logits.max(axis=1,keepdims=True);p=np.exp(logits);return p/p.sum(axis=1,keepdims=True)


def main():
    rows=generate_scenarios(seed=73191,samples=480)
    for row in rows: row["label_source"]="SYNTHETIC_SANDBOX"
    labels=np.asarray([ACTIONS.index(row["action"]) for row in rows],dtype=int)
    fit,cal,controller,test=_split_groups(rows)
    state_hashes=[hashlib.sha256(_training_context(row["state"]).encode()).hexdigest() for row in rows]
    token_hashes=[]
    start=time.perf_counter()
    model=SharedTransformerBackbone()
    for row in rows:
        enc=model.format_decision_tokens(_training_context(row["state"]))
        token_hashes.append(hashlib.sha256(enc["input_ids"].detach().cpu().numpy().tobytes()).hexdigest())
    input_dataset_hash=hashlib.sha256(json.dumps({"groups":[r["group_id"] for r in rows],"context_hashes":state_hashes},
        sort_keys=True,separators=(",",":")).encode()).hexdigest()
    layer_numbers=(7,10,14,18,21,24,28)
    cache_contract={"backbone_revision":MODEL_REVISION,"tokenizer_revision":MODEL_REVISION,
        "context_adapter_version":CONTEXT_ADAPTER_VERSION,"dataset_hash":input_dataset_hash,
        "layer_ids":list(layer_numbers),"token_hashes":token_hashes,"precision":model.precision}
    cache_key=hashlib.sha256(json.dumps(cache_contract,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    cache_root=Path.home()/".cache"/"lab-process-rag";cache_root.mkdir(parents=True,exist_ok=True)
    cache_path=cache_root/f"phase6-hidden-states-{cache_key}.npz"
    cached=False; hidden={}
    if cache_path.is_file():
        with np.load(cache_path,allow_pickle=False) as saved:
            cached_contract=json.loads(str(saved["contract"].item()))
            if cached_contract==cache_contract:
                hidden={layer:saved[f"layer_{layer}"].copy() for layer in layer_numbers};cached=True
    extraction_start=time.perf_counter()
    if not cached:
        hidden={layer:np.empty((len(rows),model.hidden_size),dtype=np.float32) for layer in layer_numbers}
        for index,row in enumerate(rows):
            enc=model.format_decision_tokens(_training_context(row["state"]))
            with torch.inference_mode():
                out=model.forward_to_exits(enc["input_ids"],enc.get("attention_mask"),capture_layers=layer_numbers)
            for layer in layer_numbers:
                hidden[layer][index]=out["hidden_by_layer"][layer][0].detach().float().cpu().numpy()
            if (index+1)%60==0: print(f"hidden state extraction {index+1}/{len(rows)}",flush=True)
        np.savez_compressed(cache_path,contract=np.asarray(json.dumps(cache_contract,sort_keys=True)),
            **{f"layer_{layer}":values for layer,values in hidden.items()})
    extraction_seconds=time.perf_counter()-extraction_start

    label_distribution={name:int(count) for name,count in zip(ACTIONS,np.bincount(labels,minlength=len(ACTIONS)))}
    split_counts={name:{"count":len(indices),"groups":len({rows[i]["group_id"] for i in indices}),
        "class_distribution":{action:int(sum(labels[i]==j for i in indices)) for j,action in enumerate(ACTIONS)}}
        for name,indices in (("fit",fit),("calibration",cal),("controller_validation",controller),("frozen_evaluation",test))}
    results=[];policy_candidates=[];model_heads={}
    for architecture in ("linear","mlp","mlp_regularized"):
        for layer in layer_numbers:
            head,head_meta=_train_head(hidden[layer][fit],labels[fit],architecture)
            model_heads[(architecture,layer)]=head
            cal_logits=head(torch.as_tensor(hidden[layer][cal],dtype=torch.float32)).detach().numpy()
            exp=np.exp(cal_logits-cal_logits.max(axis=1,keepdims=True));cal_raw=exp/exp.sum(axis=1,keepdims=True)
            temperature=float(_temperature_from_calibration(cal_raw,[ACTIONS[i] for i in labels[cal]]))
            cal_probs=_predict_prob(head,hidden[layer][cal],temperature)
            threshold_result=_risk_threshold(cal_probs,[ACTIONS[i] for i in labels[cal]],target=.20,min_covered=24)
            threshold=threshold_result.get("threshold") if layer<model.layer_count else None
            fit_hidden=hidden[layer][fit];mean=fit_hidden.mean(axis=0);scale=fit_hidden.std(axis=0);scale[scale<1e-5]=1.
            scorer=_OodScorer(mean,scale)
            cal_ood=np.asarray([scorer.score(torch.tensor(value)) for value in hidden[layer][cal]])
            ood_threshold=float(np.quantile(cal_ood,.95,method="higher"))
            controller_probs=_predict_prob(head,hidden[layer][controller],temperature)
            test_probs=_predict_prob(head,hidden[layer][test],temperature)
            cal_pred=cal_probs.argmax(axis=1);test_pred=test_probs.argmax(axis=1)
            layer_result={"architecture":architecture,"layer":layer,"head":head_meta,"temperature":temperature,
                "calibration_threshold_result":threshold_result,"ood_threshold_p95":ood_threshold,
                "calibration_metrics":_metrics(labels[cal],cal_pred),
                "evaluation_metrics":_metrics(labels[test],test_pred),
                "evaluation_high_confidence_wrong_count":int(np.sum((test_pred!=labels[test])&(test_probs.max(axis=1)>=.9))),
                "threshold_selective_evaluation":_metrics(labels[test][test_probs.max(axis=1)>=threshold],
                    test_pred[test_probs.max(axis=1)>=threshold]) if threshold is not None and np.any(test_probs.max(axis=1)>=threshold) else {"status":"NO_CALIBRATED_COVERAGE"}}
            results.append(layer_result)
            if layer<model.layer_count:
                policy_candidates.append({"architecture":architecture,"layer":layer,"head":head,
                    "temperature":temperature,"threshold":threshold,"ood_threshold":ood_threshold,
                    "scorer":scorer,"controller_probs":controller_probs,"test_probs":test_probs})
            del head
        print(f"head diagnostics complete: {architecture}",flush=True)

    policies=[]
    for architecture in ("linear","mlp","mlp_regularized"):
        selected=[item for item in policy_candidates if item["architecture"]==architecture]
        thresholds={item["layer"]:item["threshold"] for item in selected}
        ood_thresholds={item["layer"]:item["ood_threshold"] for item in selected}
        ctrl_probs={item["layer"]:item["controller_probs"] for item in selected}
        ctrl_ood={item["layer"]:np.asarray([item["scorer"].score(torch.tensor(v))>item["ood_threshold"] for v in hidden[item["layer"]][controller]]) for item in selected}
        # The candidate full-depth head uses the same architecture and fit split.
        final_head=model_heads[(architecture,model.layer_count)]
        final_result=next(item for item in results if item["architecture"]==architecture and item["layer"]==model.layer_count)
        final_temp=final_result["temperature"]
        ctrl_probs[model.layer_count]=_predict_prob(final_head,hidden[model.layer_count][controller],final_temp)
        test_probs_by_layer={item["layer"]:item["test_probs"] for item in selected}
        test_probs_by_layer[model.layer_count]=_predict_prob(final_head,hidden[model.layer_count][test],final_temp)
        final_fit=hidden[model.layer_count][fit];final_mean=final_fit.mean(axis=0);final_scale=final_fit.std(axis=0);final_scale[final_scale<1e-5]=1.
        final_scorer=_OodScorer(final_mean,final_scale)
        final_ood_cal=np.asarray([final_scorer.score(torch.tensor(v)) for v in hidden[model.layer_count][cal]])
        final_ood_threshold=float(np.quantile(final_ood_cal,.95,method="higher"))
        ctrl_ood[model.layer_count]=np.asarray([final_scorer.score(torch.tensor(v))>final_ood_threshold for v in hidden[model.layer_count][controller]])
        test_ood={}
        for item in selected:
            test_ood[item["layer"]]=np.asarray([item["scorer"].score(torch.tensor(v))>item["ood_threshold"] for v in hidden[item["layer"]][test]])
        test_ood[model.layer_count]=np.asarray([final_scorer.score(torch.tensor(v))>final_ood_threshold for v in hidden[model.layer_count][test]])
        ctrl_pred,ctrl_exits=_route(ctrl_probs,ctrl_ood,thresholds,layer_numbers,ood_thresholds)
        n=int((ctrl_exits<model.layer_count).sum());errors=int(np.sum((ctrl_pred!=labels[controller])&(ctrl_exits<model.layer_count)))
        upper=_wilson_upper(errors,n)
        allowed=n>=24 and upper<=.20
        final_pred,final_exits=_route(test_probs_by_layer,test_ood,thresholds,layer_numbers,ood_thresholds)
        if not allowed:
            final_exits=np.full(len(test),model.layer_count,dtype=int)
            final_pred=test_probs_by_layer[model.layer_count].argmax(axis=1)
        policies.append({"architecture":architecture,"selected_thresholds":{str(k):v for k,v in thresholds.items()},
            "controller_validation":{"count":len(controller),"early_exit_count":n,"early_exit_errors":errors,
                "wilson_upper_95":upper,"target_risk":.20,"policy_allowed":allowed,"minimum_covered":24},
            "frozen_evaluation":{"count":len(test),"early_exit_count":int((final_exits<model.layer_count).sum()),
                "early_exit_rate":float(np.mean(final_exits<model.layer_count)),
                "mean_executed_layers":float(final_exits.mean()),"layer_fraction_saved_estimate":float(1-final_exits.mean()/model.layer_count),
                "exit_layer_distribution":{str(layer):int(np.sum(final_exits==layer)) for layer in layer_numbers},
                "routed_metrics":_metrics(labels[test],final_pred),
            "full_depth_metrics":_metrics(labels[test],test_probs_by_layer[model.layer_count].argmax(axis=1))}})

    report={"status":"DIAGNOSTIC_SYNTHETIC_ONLY","sample_count":len(rows),"dataset_hash":input_dataset_hash,
        "cache":{"path":str(cache_path),"cache_key":cache_key,"cache_reused":cached,
            "contract_fields":list(cache_contract),"file_bytes":cache_path.stat().st_size,
            "hidden_state_extraction_seconds":extraction_seconds},
        "split_counts":split_counts,"class_distribution":label_distribution,
        "model":{"id":MODEL_ID,"revision":MODEL_REVISION,"device":model.device,"precision":model.precision,
            "model_load_seconds":(time.perf_counter()-start)-extraction_seconds,"layers":model.layer_count,"hidden_size":model.hidden_size},
        "tested_architectures":["linear","mlp","mlp_regularized"],"tested_layers":list(layer_numbers),
        "head_results":results,"sequential_exit_policies":policies,
        "root_cause_observations":["Synthetic scenario label mix is imbalanced; REQUEST_REVIEW is the largest class.",
            "Results are synthetic scenario-contract accuracy only.",
            "Sequential thresholds are enabled only when separate controller-validation Wilson upper risk is at most 0.20 with at least 24 exits."],
        "limitations":["No human-reviewed laboratory decision labels were available.",
            "Final evaluation is synthetic and independent by group, not scientific validation.",
            "Current production artifact remains unchanged; diagnostic heads are not promoted."]}
    path=ROOT/"reports"/"phase6_early_exit_diagnostics.json";path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"cache_reused":cached,"fit_cal_controller_test":[len(fit),len(cal),len(controller),len(test)],
        "labels":label_distribution,"architecture_policy_summary":[{"architecture":p["architecture"],**p["controller_validation"],**p["frozen_evaluation"]} for p in policies],
        "report":str(path)},ensure_ascii=False))


if __name__=="__main__": main()
