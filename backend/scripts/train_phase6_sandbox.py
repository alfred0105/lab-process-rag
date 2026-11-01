"""Train and benchmark actual pretrained Qwen decision heads on synthetic fixtures only."""
from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.phase5_stage3 import generate_scenarios, split_groups, stable_hash
from app.services.decision_head import ACTIONS as ACTION_ORDER, LearnedDecisionHead, encode_state
from app.services.phase5_stage4 import _apply_temperature, _temperature_from_calibration
from app.services.scientific_state_v2 import ACTION_NAMES, StructuredDecisionHeadV2
from sklearn.ensemble import HistGradientBoostingClassifier
from app.services.phase6_hybrid import (
    ACTIONS, MODEL_ID, MODEL_REVISION, Phase6HybridRuntime, SharedTransformerBackbone,
    _artifact_path, train_sandbox_heads,
)


def main():
    root = ROOT
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    rows = generate_scenarios(seed=73191, samples=120)
    for row in rows:
        row["label_source"] = "SYNTHETIC_SANDBOX"
    fit, cal, test = split_groups([row["group_id"] for row in rows], seed=2391)
    groups=np.asarray([row["group_id"] for row in rows])
    split_group_overlap={"fit_cal":sorted(set(groups[fit])&set(groups[cal])),"fit_test":sorted(set(groups[fit])&set(groups[test])),"cal_test":sorted(set(groups[cal])&set(groups[test]))}
    if any(split_group_overlap.values()): raise RuntimeError("Phase 6 benchmark group leakage detected")
    checkpoint = Path.home()/".cache"/"huggingface"/"hub"/"models--Qwen--Qwen3-0.6B"/"snapshots"/MODEL_REVISION
    started = time.perf_counter()
    model = SharedTransformerBackbone(checkpoint)
    load_ms = (time.perf_counter()-started)*1000
    device = model.device
    if device == "cuda": torch.cuda.reset_peak_memory_stats()
    if _artifact_path().is_file():
        trained = torch.load(_artifact_path(), map_location="cpu", weights_only=True)
        trained["artifact_path"] = str(_artifact_path())
    else:
        trained = train_sandbox_heads(model=model, rows=rows, fit_indexes=fit, calibration_indexes=cal,
                                      eval_indexes=test, epochs=18, batch_size=12, seed=4097)
    runtime = Phase6HybridRuntime(checkpoint, _artifact_path(), device=device)
    test_rows = [rows[i] for i in test]
    valid_test_rows = [row for row in test_rows if row["state"].get("provenance", {}).get("validity") == "VALID"
                       and row["state"].get("provenance", {}).get("data_quality_gate") == "PASS"]
    truth = [row["action"] for row in valid_test_rows[:24]]
    # Compare actual prefix execution with forced full-depth execution on identical examples.
    early_runs=[]; full_runs=[]; early_actions=[]; full_actions=[]; early_results=[]
    request = "Select the appropriate next action for this recorded laboratory state."
    runtime_rows = valid_test_rows[:24]
    for row in runtime_rows:
        state=row["state"]
        start=time.perf_counter(); result=runtime.infer(state,request)
        early_runs.append((time.perf_counter()-start)*1000); early_actions.append(result["raw_predicted_action"]); early_results.append(result)
        start=time.perf_counter(); result_full=runtime.infer(state,request,force_full_depth=True)
        full_runs.append((time.perf_counter()-start)*1000); full_actions.append(result_full["raw_predicted_action"])
    def metrics(actual, predicted):
        classes=list(ACTIONS)
        f1=[]
        for label in classes:
            tp=sum(a==label and p==label for a,p in zip(actual,predicted)); fp=sum(a!=label and p==label for a,p in zip(actual,predicted)); fn=sum(a==label and p!=label for a,p in zip(actual,predicted))
            f1.append(2*tp/max(1,2*tp+fp+fn))
        return {"count":len(actual),"accuracy":sum(a==p for a,p in zip(actual,predicted))/max(1,len(actual)),"macro_f1":sum(f1)/len(f1)}
    # Fit Phase 5 baselines on the same source recipe groups and frozen partitions.
    labels=[row["action"] for row in rows]
    v1_x=np.vstack([encode_state(row["features_v1_state"]) for row in rows])
    v1_model,_=LearnedDecisionHead.fit(v1_x[fit],[labels[i] for i in fit],seed=4097)
    v1_model.calibrate(v1_x[cal],[labels[i] for i in cal])
    v1_probs=v1_model.predict_proba(v1_x[test])
    v2_x=np.vstack([row["features_v2"] for row in rows])
    v2_model,_=StructuredDecisionHeadV2.fit(v2_x[fit],[labels[i] for i in fit],seed=4097)
    v2_model.calibrate(v2_x[cal],[labels[i] for i in cal])
    v2_probs=v2_model.predict_proba(v2_x[test])
    v2_weights={label:len(fit)/(len(set(labels[i] for i in fit))*sum(labels[i]==label for i in fit)) for label in set(labels[i] for i in fit)}
    v2_weighted,_=StructuredDecisionHeadV2.fit(v2_x[fit],[labels[i] for i in fit],seed=4097,
        sample_weights=np.asarray([v2_weights[labels[i]] for i in fit]))
    v2_weighted.calibrate(v2_x[cal],[labels[i] for i in cal]); v2_weighted_probs=v2_weighted.predict_proba(v2_x[test])
    tree=HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=15,l2_regularization=1.0,random_state=4097).fit(v2_x[fit],[labels[i] for i in fit])
    def align_tree(probabilities,classes):
        aligned=np.zeros((len(probabilities),len(ACTION_NAMES)))
        for idx,label in enumerate(classes): aligned[:,ACTION_NAMES.index(str(label))]=probabilities[:,idx]
        return aligned
    tree_cal=align_tree(tree.predict_proba(v2_x[cal]),tree.classes_)
    tree_temp=_temperature_from_calibration(tree_cal,[labels[i] for i in cal])
    tree_probs=_apply_temperature(align_tree(tree.predict_proba(v2_x[test]),tree.classes_),tree_temp)
    def prob_metrics(probs):
        pred=[ACTION_ORDER[int(i)] for i in probs.argmax(axis=1)]
        return metrics([labels[i] for i in test],pred)
    phase5_baselines={"phase5_v1":{"metrics":prob_metrics(v1_probs),"calibration":"temperature_fit_on_calibration_partition"},
        "phase5_v2":{"metrics":prob_metrics(v2_probs),"calibration":"temperature_fit_on_calibration_partition"},
        "phase5_v2_class_weighted":{"metrics":prob_metrics(v2_weighted_probs),"calibration":"temperature_fit_on_calibration_partition"},
        "phase5_hist_gradient_boosting":{"metrics":prob_metrics(tree_probs),"calibration":{"temperature":tree_temp,"fit_partition":"calibration_only"}}}
    early_layers=[x["executed_layers"] for x in early_results]
    decision_report={
        "status":"PARTIAL_SYNTHETIC_SOFTWARE_BENCHMARK",
        "model_id":MODEL_ID,"model_revision":MODEL_REVISION,"license":"Apache-2.0",
        "dataset_label":"SYNTHETIC_SANDBOX_NOT_SCIENTIFIC_VALIDATION",
        "dataset_hash":stable_hash([{k:row[k] for k in ("group_id","action","scenario_family")} for row in rows]),
        "counts":{"total":len(rows),"fit":len(fit),"calibration":len(cal),"evaluation":len(test),"measured_runtime_cases":len(early_runs)},
        "group_leakage":False,"group_overlap":split_group_overlap,"backbone_frozen_digest":trained["backbone_frozen_digest"],
        "backbone_parameters":model.total_parameters,"decision_head_parameters":trained["parameter_count"],
        "shared_lm_embedding_weights":model.shared_weights,"hidden_dimension":model.hidden_size,"layer_count":model.layer_count,"device":model.device,"precision":model.precision,
        "trainable_parameters_percent":100*trained["parameter_count"]/model.total_parameters,
        "evaluation_by_exit_layer":trained["evaluation_metrics"],
        "phase5_baselines_same_source_group_split":phase5_baselines,
        "architecture":"six independently trained linear heads over frozen Qwen3 hidden states at layers 7/14/21/28",
        "limitations":["Synthetic labels validate software execution only.","No reviewed laboratory labels were available.","Runtime latency sample is small and local-load includes shared system conditions."]}
    final_phase6 = trained["evaluation_metrics"][str(model.layer_count)]
    decision_report["same_split_phase6_vs_phase5"]={name:{"accuracy_delta_vs_phase6_final":final_phase6["accuracy"]-baseline["metrics"]["accuracy"],
        "macro_f1_delta_vs_phase6_final":final_phase6["macro_f1"]-baseline["metrics"]["macro_f1"]}
        for name,baseline in phase5_baselines.items()}
    (reports/"phase6_decision_benchmark.json").write_text(json.dumps(decision_report,indent=2,ensure_ascii=False)+"\n")
    exit_report={"status":"MEASURED_LOCAL_SYNTHETIC_SOFTWARE_ONLY","device":device,"precision":model.precision,
        "eligible_valid_cases":len(runtime_rows),"blocked_invalid_input_count":len(test_rows)-len(valid_test_rows),
        "early_exit_cases":len(early_runs),"early_executed_layers":early_layers,
        "early_exit_rate":sum(x in model.exit_layers[:-1] for x in [r["exit_layer"] for r in early_results])/max(1,len(early_results)),
        "mean_layers_early":statistics.mean(early_layers),"mean_layers_full":model.layer_count,
        "layer_fraction_saved_estimate":1-statistics.mean(early_layers)/model.layer_count,
        "early_raw_action_metrics":metrics(truth[:len(early_actions)],early_actions),
        "full_depth_raw_action_metrics":metrics(truth[:len(full_actions)],full_actions),
        "early_latency_ms":{"p50":statistics.median(early_runs),"p95":float(np.percentile(early_runs,95))},
        "full_depth_latency_ms":{"p50":statistics.median(full_runs),"p95":float(np.percentile(full_runs,95))},
        "actual_layer_skipping":any(x in model.exit_layers[:-1] for x in [r["exit_layer"] for r in early_results]),"early_full_decision_equivalent":early_actions==full_actions,
        "limitations":["One warm local process; at most 24 cases.","Layer fraction is a proxy, not measured FLOPs."]}
    (reports/"phase6_early_exit_benchmark.json").write_text(json.dumps(exit_report,indent=2,ensure_ascii=False)+"\n")
    # Compare decision-only (zero tokens) against a requested explanation on one case.
    example=valid_test_rows[0]["state"]
    decision=runtime.infer(example,"Select the appropriate next action for this recorded laboratory state.")
    explain=runtime.infer(example,"Select the appropriate next action for this recorded laboratory state. Explain evidence and limitations briefly.",explanation_requested=True,max_new_tokens=48)
    raw_encoded=model.format_tokens("Reply with the single word OK.",user_request="Short generation-path smoke check.")
    raw_text,raw_tokens,raw_generation_ms,raw_cache_bytes=model.generate_from_full_cache(raw_encoded,max_new_tokens=4)
    generation_report={"status":"MEASURED_LOCAL_SMOKE","decision_only":{"generated_tokens":decision["generated_token_count"],"generation_called":decision["generation_required"],"decision_latency_ms":decision["decision_latency_ms"]},
        "conditional_explanation":{"generated_tokens":explain["generated_token_count"],"generation_latency_ms":explain["generation_latency_ms"],"cache_reuse_status":explain["cache_reuse_status"],"kv_cache_bytes":explain["kv_cache_bytes"],"text":explain["generated_text"]},
        "raw_lm_runtime_smoke_non_scientific":{"generated_tokens":raw_tokens,"latency_ms":raw_generation_ms,"kv_cache_bytes":raw_cache_bytes,"text":raw_text},
        "cache_policy":"Decision early-exit state is not a complete KV cache. When no validated evidence exists, explanation generation is skipped. If supported evidence exists, the implementation uses full-depth prefill fallback followed by per-token KV reuse.","workflow_triggered":False}
    (reports/"phase6_generation_benchmark.json").write_text(json.dumps(generation_report,indent=2,ensure_ascii=False)+"\n")
    memory={"status":"MEASURED_LOCAL","device":device,"precision":model.precision,"model_load_ms":load_ms,
        "parameter_count":model.total_parameters,"model_revision":MODEL_REVISION,"python":platform.python_version(),
        "torch":torch.__version__,"mps_available":bool(torch.backends.mps.is_available()),"cuda_available":bool(torch.cuda.is_available()),
        "device_memory_allocated_after_run_bytes":int(torch.mps.driver_allocated_memory()) if device=="mps" else (int(torch.cuda.max_memory_allocated()) if device=="cuda" else None),
        "device_memory_measurement":"MPS_DRIVER_ALLOCATED_AFTER_RUN_NOT_PEAK" if device=="mps" else "CUDA_PEAK_ALLOCATED" if device=="cuda" else "NOT_MEASURED",
        "host_peak_rss_bytes":None,"host_peak_rss_measurement":"NOT_MEASURED","quantization":{"int8":"NOT_SUPPORTED_IN_THIS_MPS_BACKEND_SETUP","int4":"NOT_SUPPORTED_IN_THIS_MPS_BACKEND_SETUP"},
        "limitations":["macOS process peak RSS was not collected reliably from Python in this run.","No supported quantized runtime was installed; FP16 MPS is measured.","RTX 4060 Ti system is not attached and was not measured."]}
    (reports/"phase6_memory_latency.json").write_text(json.dumps(memory,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"status":decision_report["status"],"model":MODEL_ID,"device":device,"load_ms":load_ms,
        "decision":decision_report["evaluation_by_exit_layer"],"early_exit":exit_report,"generation":generation_report,"memory":memory},ensure_ascii=False))


if __name__=="__main__":main()
