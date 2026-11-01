"""Measure real full-depth Qwen3 decision-prefix latency and decoder hooks."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.services.phase5_stage3 import generate_scenarios
from app.services.phase6_hybrid import MODEL_REVISION, SharedTransformerBackbone, _training_context


def sync(device):
    if device=="mps" and torch.backends.mps.is_available(): torch.mps.synchronize()
    elif device.startswith("cuda") and torch.cuda.is_available(): torch.cuda.synchronize()


def main():
    model=SharedTransformerBackbone()
    row=generate_scenarios(seed=98271,samples=1)[0]
    enc=model.format_decision_tokens(_training_context(row["state"]))
    layer_calls=[0]*model.layer_count
    handles=[]
    for i,layer in enumerate(model.backbone.layers):
        handles.append(layer.register_forward_hook(lambda _m,_i,_o,idx=i: layer_calls.__setitem__(idx,layer_calls[idx]+1)))
    for _ in range(3):
        with torch.inference_mode(): model.forward_to_exits(enc["input_ids"],enc.get("attention_mask"),capture_layers=(7,14,21,28))
    sync(model.device)
    times=[]; per_run=[]
    for _ in range(30):
        before=layer_calls.copy(); sync(model.device); start=time.perf_counter()
        with torch.inference_mode(): out=model.forward_to_exits(enc["input_ids"],enc.get("attention_mask"),capture_layers=(7,14,21,28))
        sync(model.device); times.append((time.perf_counter()-start)*1000)
        per_run.append({"executed_layers_reported":out["executed_layers"],"decoder_hook_invocations":sum(a-b for a,b in zip(layer_calls,before))})
    for handle in handles: handle.remove()
    result={"status":"MEASURED_FULL_DEPTH_BASELINE_ONLY","model_revision":MODEL_REVISION,"device":model.device,"precision":model.precision,
      "warmup_runs":3,"measured_runs":len(times),"p50_latency_ms":float(np.percentile(times,50)),"p95_latency_ms":float(np.percentile(times,95)),
      "min_latency_ms":float(min(times)),"max_latency_ms":float(max(times)),"input_token_count":int(enc["input_ids"].shape[1]),
      "mean_executed_layers":float(np.mean([x["decoder_hook_invocations"] for x in per_run])),"hook_evidence_all_layers_executed":all(x["decoder_hook_invocations"]==model.layer_count for x in per_run),
      "per_run_evidence":per_run,"early_exit_latency":"NOT_MEASURED; the only statistically passing policy is certified on synthetic sandbox labels and is ineligible under the research safety boundary"}
    path=ROOT/"reports"/"phase6_ee_final_benchmark.json"
    prior=json.loads(path.read_text()) if path.exists() else {}
    prior["runtime_latency"]=result
    prior["actual_runtime_layer_skip"]={"status":"NOT_RUN_SYNTHETIC_ONLY_POLICY_NOT_PRODUCTION_ELIGIBLE","full_depth_hook_evidence":result["hook_evidence_all_layers_executed"],"note":"Sandbox-generated scenario labels cannot authorize research early exit. Existing safety boundary is preserved; only full-depth real Qwen inference was timed."}
    path.write_text(json.dumps(prior,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))

if __name__=="__main__": main()
