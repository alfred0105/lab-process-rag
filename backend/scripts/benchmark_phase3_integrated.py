"""Isolated synthetic integration benchmark for Phase 3 software paths.

This measures deterministic local software only. It does not estimate Gemma,
VM/OpenFOAM, instrument, or scientific accuracy performance.
Run from backend: python scripts/benchmark_phase3_integrated.py --repeats 5
"""
from __future__ import annotations

import argparse, csv, io, json, os, platform, resource, statistics, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

_tmp = tempfile.TemporaryDirectory(prefix="lab-process-phase3-bench-")
os.environ["LAB_PROCESS_DB_PATH"] = str(Path(_tmp.name) / "bench.sqlite")
os.environ["LAB_PROCESS_DATA_DIR"] = str(Path(_tmp.name) / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from app.db.database import Base, SessionLocal
from app.db.models import Experiment, ResearchTopic, WorkflowNode, WorkflowRun
from app.services.material_analysis.service import analyze
from app.services.simulation.cache import phreeqc_cache_identity
from app.services.tool_adapters import PHREEQCAdapter
from app.services.tool_registry import ResultValidator, RuleBasedDecisionPolicy, ScientificStateBuilder, ToolRegistry, ValidationGate, recommend_tools
from app.services.typed_values import convert_declared_value
from app.services.workflow_planner import plan_workflow
from app import worker


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--repeats",type=int,default=5);parser.add_argument("--json",default="reports/phase3_integrated_benchmark.json");parser.add_argument("--csv",default="reports/phase3_integrated_benchmark.csv")
    args=parser.parse_args()
    if not 3<=args.repeats<=100: parser.error("--repeats must be 3..100")
    Base.metadata.create_all(bind=SessionLocal.kw["bind"])
    db=SessionLocal();topic=ResearchTopic(name="Disposable Phase 3 benchmark",description="Synthetic benchmark only");db.add(topic);db.flush()
    experiment=Experiment(code="BENCH-001",name="Synthetic benchmark record",target="software timing",status="success",topic_id=topic.id,demo=True)
    db.add(experiment);db.commit();topic_id=topic.id;experiment_id=experiment.id;db.close()

    x=np.linspace(10,80,1000);y=10+100*np.exp(-((x-35)/0.35)**2)+70*np.exp(-((x-62)/0.5)**2)
    xrd="\n".join(f"{a:.6f},{b:.6f}" for a,b in zip(x,y)).encode()
    grid=np.random.default_rng(3).normal(0,1,(128,128));afm="\n".join(",".join(f"{v:.4f}" for v in row) for row in grid).encode()
    pixels=np.zeros((256,256),dtype=np.uint8);pixels[30:90,40:100]=240;bio=io.BytesIO();Image.fromarray(pixels).save(bio,format="PNG");image=bio.getvalue()
    record={"id":experiment_id,"topic_id":topic_id,"demo":True,"status":"success","steps":[],"materials":[],"results":[]}
    adapter=PHREEQCAdapter();ph_input=adapter.prepare(adapter.validate_inputs({"temperature_c":25,"pH":8,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"]}))
    ph_result=adapter.execute(ph_input)
    tool=ToolRegistry().get("phreeqc.aqueous_equilibrium.v1")
    operations={
        "state_builder":lambda:ScientificStateBuilder.build(record,[]),
        "decision_policy":lambda:RuleBasedDecisionPolicy().choose(ScientificStateBuilder.build(record,[]),recommend_tools(record,[])["recommendations"],"XRD"),
        "workflow_planner":lambda:plan_workflow(goal="PHREEQC equilibrium",record=record,analysis_runs=[],simulation_inputs=ph_input,approval_confirmed=True),
        "validation_gate":lambda:ValidationGate.validate({"readiness":"READY","execution_policy":"review_inputs_before_run"},approval_granted=True),
        "tool_result_validator":lambda:ResultValidator.validate(tool,ph_result),
        "typed_handoff_conversion":lambda:convert_declared_value(1.5,"mmol/L","mol/L",None),
        "cache_identity":lambda:phreeqc_cache_identity(tool_id=tool.tool_id,tool_version=tool.version,topic_id=topic_id,experiment_id=experiment_id,process_step_id=None,parameters=ph_input),
        "XRD_analysis":lambda:analyze("xrd",xrd,"bench.xy"),
        "AFM_analysis":lambda:analyze("afm",afm,"bench.csv"),
        "SEM_analysis":lambda:analyze("sem",image,"bench.png",pixel_size_nm=2.0),
        "TEM_analysis":lambda:analyze("tem",image,"bench.png",pixel_size_nm=2.0),
        "PHREEQC_execution":lambda:adapter.execute(ph_input),
    }
    samples={}
    for name,operation in operations.items():
        timings=[];cpu=[];errors=0
        for _ in range(args.repeats):
            p0=time.process_time();t0=time.perf_counter()
            try:
                result=operation()
                if isinstance(result,dict) and result.get("valid") is False: errors+=1
            except Exception: errors+=1
            timings.append(time.perf_counter()-t0);cpu.append(time.process_time()-p0)
        samples[name]={"n":args.repeats,"errors":errors,"wall_seconds":{"p50":statistics.median(timings),"p95_nearest_rank":sorted(timings)[max(0,int(np.ceil(.95*len(timings)))-1)],"min":min(timings),"max":max(timings)},"cpu_seconds_p50":statistics.median(cpu)}

    queue_samples=[];claim_samples=[];sqlite_samples=[];claim_errors=0
    for i in range(args.repeats):
        db=SessionLocal();now=datetime.now(timezone.utc).replace(tzinfo=None);t0=time.perf_counter()
        flow=WorkflowRun(topic_id=topic_id,experiment_id=experiment_id,goal="synthetic queue benchmark",status="QUEUED",graph_json={"nodes":[]},created_at=now);db.add(flow);db.flush()
        node=WorkflowNode(workflow_id=flow.id,node_key=f"quality-{i}",tool_id="experiment.data_quality.v1",dependency_keys=[],input_json={},created_at=now);db.add(node);db.commit();queue_samples.append(time.perf_counter()-t0);node_id=node.id;db.close()
        t0=time.perf_counter();claim=worker._workflow_claim(f"bench-{i}");claim_samples.append(time.perf_counter()-t0)
        if not claim or claim[0]!=node_id: claim_errors+=1
        t0=time.perf_counter();db=SessionLocal();claimed=db.get(WorkflowNode,node_id);claimed.output_json={"benchmark_roundtrip":i};db.commit();db.close();sqlite_samples.append(time.perf_counter()-t0)
    for label,timings in (("workflow_enqueue_sqlite",queue_samples),("worker_claim",claim_samples),("sqlite_read_write_roundtrip",sqlite_samples)):
        samples[label]={"n":args.repeats,"errors":claim_errors if label=="worker_claim" else 0,"wall_seconds":{"p50":statistics.median(timings),"p95_nearest_rank":sorted(timings)[max(0,int(np.ceil(.95*len(timings)))-1)],"min":min(timings),"max":max(timings)},"cpu_seconds_p50":None}
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb=rss/(1024*1024) if platform.system()=="Darwin" else rss/1024
    report={"benchmark":"Phase 3 integrated deterministic software smoke benchmark","device":platform.platform(),"python":platform.python_version(),"repeats":args.repeats,"synthetic_data_only":True,"process_peak_rss_mb":rss_mb,"measurements":samples,"limitations":["No scientific accuracy claim; PHREEQC is also tested separately against an equivalent input deck.","Single-process Python peak RSS includes imports and native libraries; it does not isolate API, worker, VM, or LLM memory.","Concurrency, true cache-hit execution, and OpenFOAM CFD are intentionally not inferred by this local smoke benchmark.","Synthetic XRD/AFM/SEM/TEM data measure code path timing only, not instrument validity."]}
    json_path=Path(args.json);csv_path=Path(args.csv);json_path.parent.mkdir(parents=True,exist_ok=True);csv_path.parent.mkdir(parents=True,exist_ok=True)
    json_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with csv_path.open("w",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(["operation","n","errors","p50_seconds","p95_seconds","min_seconds","max_seconds","cpu_p50_seconds"])
        for name,item in samples.items():
            w=item["wall_seconds"];writer.writerow([name,item["n"],item["errors"],w["p50"],w["p95_nearest_rank"],w["min"],w["max"],item["cpu_seconds_p50"]])
    print(json.dumps({"json":str(json_path),"csv":str(csv_path),"process_peak_rss_mb":rss_mb,"measurements":samples},ensure_ascii=False,indent=2))
    _tmp.cleanup()

if __name__=="__main__":main()
