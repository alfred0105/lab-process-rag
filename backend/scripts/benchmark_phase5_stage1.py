"""Reproducible synthetic software benchmark for Learned JEV Decision Head."""
from __future__ import annotations

import json
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import numpy as np

from app.services.decision_head import (ACTIONS, DATASET_VERSION, FEATURES, FEATURE_SCHEMA_VERSION,
    MODEL_VERSION, LearnedDecisionHead, calibration_metrics, encode_state, majority_metrics,
    rule_metrics, split_by_group, synthetic_cases)


def run(seed: int = 7) -> dict:
    cases=synthetic_cases(seed=seed,per_action=30)
    states=[row["state"] for row in cases]; labels=[row["action"] for row in cases]; groups=[row["case_group_id"] for row in cases]
    x=np.vstack([encode_state(state) for state in states])
    outer_train,test=split_by_group(labels,groups,seed=seed,fraction=.25)
    fit_rel,cal_rel=split_by_group([labels[i] for i in outer_train],[groups[i] for i in outer_train],seed=seed+1,fraction=.2)
    fit=outer_train[fit_rel];cal=outer_train[cal_rel]
    train_started=time.perf_counter();model,loss=LearnedDecisionHead.fit(x[fit],[labels[i] for i in fit],seed=seed);train_ms=(time.perf_counter()-train_started)*1000
    calibrated=model.calibrate(x[cal],[labels[i] for i in cal])
    probs=model.predict_proba(x[test]); metrics=calibration_metrics([labels[i] for i in test],probs)
    model_size=len(json.dumps(model.to_dict(),separators=(",",":" )).encode())
    sample=x[test[:1]];latencies=[]
    for _ in range(500):
        started=time.perf_counter();model.predict_proba(sample);latencies.append((time.perf_counter()-started)*1000)
    ood_state=dict(states[0],accepted_observation_count=1000000)
    ood_state_status=model.is_ood(encode_state(ood_state))[0]
    unsupported_state=model.is_ood(encode_state({"accepted_observation_count":1}))[0]
    metrics.update({"majority_baseline":majority_metrics([labels[i] for i in fit],[labels[i] for i in test]),
        "rule_baseline":rule_metrics([states[i] for i in test],[labels[i] for i in test]),
        "training_loss_start":loss[0],"training_loss_end":loss[-1],"training_loss_decreased":loss[-1]<loss[0],
        "calibration_status":"TEMPERATURE_SCALED_ON_SEPARATE_GROUP_HOLDOUT" if calibrated else "INSUFFICIENT_CALIBRATION_DATA",
        "model_size_bytes":model_size,"inference_latency_ms":{"p50":float(np.percentile(latencies,50)),"p95":float(np.percentile(latencies,95))},
        "training_latency_ms":train_ms,"ood_tests":{"far_numeric_value":ood_state_status,"mostly_missing_state":unsupported_state},
        "inference_memory_process_max_rss_bytes":int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)*(1 if sys.platform=="darwin" else 1024),
        "action_probabilities_are_success_probabilities":False})
    return {"report_version":"phase5-stage1-synthetic-v1","dataset_type":"SYNTHETIC_SOFTWARE_FIXTURE_NOT_EXPERT_TRUTH",
        "dataset_version":DATASET_VERSION,"seed":seed,"feature_schema_version":FEATURE_SCHEMA_VERSION,"features":list(FEATURES),
        "action_labels":list(ACTIONS),"groups_are_independent_scenario_ids":True,"sample_counts":{"total":len(cases),"training":len(fit),"calibration":len(cal),"validation":len(test)},
        "model_architecture":model.to_dict()["architecture"],"model_version":MODEL_VERSION,"metrics":metrics,
        "environment":{"python":platform.python_version(),"platform":platform.platform(),"numpy":np.__version__},
        "limitations":["Synthetic scenarios and labels test software behavior only; they are not expert decisions or real lab accuracy.",
            "Current MLP is a small numeric-feature head and does not use Transformer hidden states.",
            "Temperature scaling uses a separate scenario-group calibration split; small datasets remain uncalibrated.",
            "OOD is a simple standardized feature-range check; detection sensitivity has not been externally validated.",
            "The RuleBasedDecisionPolicy comparison is an engineering baseline, not human ground truth."]}


if __name__=="__main__":
    report=run()
    out=Path(__file__).resolve().parents[1]/"reports"/"phase5_stage1_decision_benchmark.json"
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(out)
    print(json.dumps({"accuracy":report["metrics"]["accuracy"],"macro_f1":report["metrics"]["macro_f1"],"brier":report["metrics"]["brier_score"],"ece":report["metrics"]["expected_calibration_error_10_bins"],"samples":report["sample_counts"]},ensure_ascii=False))
