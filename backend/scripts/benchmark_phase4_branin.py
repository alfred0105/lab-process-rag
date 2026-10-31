#!/usr/bin/env python3
"""Reproducible multi-seed Phase 4 optimizer comparison on synthetic Branin."""
import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.optimization.gpbo import sandbox_benchmark


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--seed",type=int,default=7)
    parser.add_argument("--budget",type=int,default=20)
    parser.add_argument("--seeds",type=int,default=5)
    parser.add_argument("--output",type=Path,default=Path("reports/phase4_branin_benchmark.json"))
    args=parser.parse_args()
    result=sandbox_benchmark(seed=args.seed,budget=args.budget,seeds=args.seeds)
    try:
        commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
        dirty=bool(subprocess.check_output(["git","status","--porcelain"],text=True).strip())
    except (subprocess.SubprocessError,FileNotFoundError): commit="unknown"; dirty=True
    report={"created_at_utc":datetime.now(timezone.utc).isoformat(),"base_commit":commit,"working_tree_changes_present":dirty,
        "platform":platform.platform(),"python":platform.python_version(),"benchmark":result,
        "methodology":{"same_five_point_initial_design_per_seed":True,"same_additional_evaluation_budget_per_method":True,
            "policies":["random_search","latin_hypercube","gp_ei","gp_ucb"],
            "summary":"Each policy is repeated with deterministic seeds; report median/mean best objective and simple regret. Synthetic objective only."}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(args.output),"commit":commit,"seeds":args.seeds,"budget":args.budget,
        "median_best":{name:row["median_best"] for name,row in result["policies"].items()}},indent=2))


if __name__=="__main__": main()
