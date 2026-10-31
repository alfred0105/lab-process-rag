#!/usr/bin/env python3
"""Run and persist the Phase 5 Stage 4 reliability reports."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.services.phase5_stage4 import run_stage4_suite


def main():
    result=run_stage4_suite()
    paths={"diagnostics":"phase5_stage4_diagnostics.json","comparison":"phase5_stage4_model_comparison.json",
           "reliability":"phase5_stage4_reliability.json","final_evaluation":"phase5_stage4_final_evaluation.json"}
    for key,name in paths.items():
        target=ROOT/"reports"/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result[key],ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        print(f"{key}: {target}")
    print(json.dumps({"protocol":result["final_evaluation"]["protocol_version"],
        "dataset_hash":result["final_evaluation"]["dataset_hash"],
        "selected_candidate_on_development":result["final_evaluation"]["candidate_selected_on_development_only"],
        "final_test_count":result["final_evaluation"]["sample_count"]},ensure_ascii=False))

if __name__=="__main__":main()
