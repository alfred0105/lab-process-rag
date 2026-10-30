"""Repeatable local microbenchmark for the real PHREEQC adapter.

This measures runtime only; it is not a scientific accuracy or reference-case test.
Run from backend with ``python scripts/benchmark_phase3.py --repeats 10``.
"""
import argparse
import json
import math
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.services.tool_adapters import PHREEQCAdapter


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--repeats",type=int,default=10);args=parser.parse_args()
    if not 3<=args.repeats<=100: parser.error("--repeats must be 3..100")
    adapter=PHREEQCAdapter()
    inputs=adapter.prepare(adapter.validate_inputs({"temperature_c":25,"pH":8.3,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"]}))
    timings=[];validation=[]
    for _ in range(args.repeats):
        started=time.perf_counter();output=adapter.execute(inputs);timings.append(time.perf_counter()-started)
        validation.append(adapter.validate_outputs(output)["valid"])
    ordered=sorted(timings)
    p95=ordered[min(len(ordered)-1,math.ceil(0.95*len(ordered))-1)]
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    rss_mb=rss/(1024*1024) if platform.system()=="Darwin" else rss/1024
    print(json.dumps({"benchmark":"PHREEQC aqueous equilibrium adapter runtime microbenchmark","scientific_accuracy_test":False,
        "device":platform.platform(),"python":platform.python_version(),"repeats":args.repeats,"input":{"temperature_c":25,"pH":8.3,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"]},
        "all_outputs_passed_schema_validation":all(validation),"runtime_seconds":{"p50":statistics.median(timings),"p95_nearest_rank":p95,"min":min(timings),"max":max(timings)},
        "process_peak_rss_mb":rss_mb,"limitation":"Process peak RSS includes Python imports and PHREEQC; it does not isolate worker/API/VM/model memory."},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
