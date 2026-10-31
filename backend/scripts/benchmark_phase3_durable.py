"""End-to-end durable workflow timing on disposable synthetic data.

Run from backend with the project environment:
  python scripts/benchmark_phase3_durable.py --repeats 20

The script creates a temporary SQLite database/data directory, calls the real
FastAPI workflow endpoints through TestClient, and executes nodes through the
real durable Worker run_once loop. It never writes to the research database.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--json", default="backend/reports/phase3_durable_benchmark.json")
    parser.add_argument("--csv", default="backend/reports/phase3_durable_benchmark.csv")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("--repeats must be 1..100")

    with tempfile.TemporaryDirectory(prefix="lab-process-durable-bench-") as temp:
        temp_path = Path(temp)
        os.environ["LAB_PROCESS_DB_PATH"] = str(temp_path / "benchmark.sqlite")
        os.environ["LAB_PROCESS_DATA_DIR"] = str(temp_path / "data")
        os.environ["LAB_PROCESS_TESTING"] = "1"
        backend = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(backend))

        import numpy as np
        from fastapi.testclient import TestClient
        from PIL import Image
        from app.db.database import Base, SessionLocal
        from app.db.models import Experiment, ResearchTopic, WorkflowNode, WorkflowRun
        from app.main import app
        from app import worker

        Base.metadata.create_all(bind=SessionLocal.kw["bind"])
        db = SessionLocal()
        topic = ResearchTopic(name="Disposable durable benchmark", description="Synthetic only")
        db.add(topic); db.commit(); db.refresh(topic)
        topic_id = topic.id
        db.close()

        def experiment(label: str) -> int:
            session = SessionLocal()
            try:
                item = Experiment(code=f"BENCH-{label}-{time.time_ns() % 10**12}", name=f"Synthetic {label}",
                    target="software benchmark", date=date.today(), duration_minutes=1, status="success",
                    demo=False, topic_id=topic_id, notes="Synthetic benchmark fixture")
                session.add(item); session.commit(); session.refresh(item)
                return item.id
            finally:
                session.close()

        def process_rss_mb(pid: int) -> float:
            try:
                sample = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],capture_output=True,text=True,check=False)
                return int(sample.stdout.strip()) / 1024 if sample.stdout.strip() else 0.0
            except (OSError,ValueError):
                return 0.0

        def wait_worker(workflow_id: int) -> dict:
            calls = 0
            while calls < 30 and worker.run_once(f"durable-benchmark-{calls}"):
                calls += 1
            session = SessionLocal()
            try:
                flow = session.get(WorkflowRun, workflow_id)
                nodes = session.query(WorkflowNode).filter_by(workflow_id=workflow_id).order_by(WorkflowNode.id).all()
                assert flow and flow.status == "COMPLETED", (workflow_id, flow.status if flow else None)
                return {"status": flow.status, "calls": calls,
                    "queued_at": flow.created_at.isoformat(),
                    "nodes": [{"tool_id": n.tool_id, "status": n.status, "result_type": n.result_type,
                        "result_id": n.result_id, "output": n.output_json or {},
                        "queued_at": n.created_at.isoformat(), "started_at": n.started_at.isoformat() if n.started_at else None,
                        "finished_at": n.finished_at.isoformat() if n.finished_at else None} for n in nodes]}
            finally:
                session.close()

        results: dict[str, list[dict]] = {}
        with TestClient(app) as client:
            topic_row = client.get("/api/topics").json()
            # TestClient and database share the same temporary store.
            assert any(row["id"] == topic_id for row in topic_row)

            def queued_api(label: str, nodes: list[dict], exp_id: int, *, planner: bool = False,
                           simulation_inputs: dict | None = None, approval_confirmed: bool = False) -> tuple[int, float]:
                started = time.perf_counter()
                if planner:
                    response = client.post("/api/workflows/plan",json={"topic_id":topic_id,"experiment_id":exp_id,
                        "goal":label,"enqueue":True,"approval_confirmed":approval_confirmed,
                        "simulation_inputs":simulation_inputs})
                else:
                    response = client.post("/api/workflows", json={"topic_id": topic_id, "experiment_id": exp_id,
                        "goal": f"durable benchmark {label}", "nodes": nodes})
                if response.status_code != 202:
                    raise RuntimeError(f"workflow enqueue failed ({response.status_code}): {response.text}")
                payload = response.json()
                flow = payload.get("workflow") if planner else payload
                if not flow or not flow.get("id"):
                    raise RuntimeError(f"workflow planner did not return a durable run: {payload}")
                return flow["id"], time.perf_counter() - started

            def measure(label: str, workflow_id: int, enqueue_seconds: float, mode: str = "worker_run_once", fresh_process: bool = False):
                cpu_start = time.process_time(); child_cpu_start = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
                start = time.perf_counter(); worker_peak_rss = None
                if fresh_process:
                    process = subprocess.Popen([sys.executable, "-m", "app.worker", "--once"], cwd=backend,
                        env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    worker_peak_rss = 0.0
                    while process.poll() is None:
                        worker_peak_rss = max(worker_peak_rss,process_rss_mb(process.pid));time.sleep(.01)
                    if process.returncode != 0: raise RuntimeError(f"fresh Worker exited with {process.returncode}")
                done = wait_worker(workflow_id)
                end = time.perf_counter()
                if fresh_process:
                    child_cpu_end = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
                    cpu = child_cpu_end - child_cpu_start
                else:
                    cpu = time.process_time() - cpu_start
                node_times = []
                queue_times = []
                for node in done["nodes"]:
                    if node["started_at"] and node["finished_at"]:
                        from datetime import datetime
                        parse = lambda value: datetime.fromisoformat(value)
                        node_times.append((parse(node["finished_at"]) - parse(node["started_at"])).total_seconds())
                        queue_times.append((parse(node["started_at"]) - parse(node["queued_at"])).total_seconds())
                results.setdefault(label, []).append({"workflow_id": workflow_id, "mode": mode,
                    "status": done["status"], "nodes": len(done["nodes"]), "worker_calls": done["calls"],
                    "enqueue_seconds": enqueue_seconds, "end_to_end_seconds": end - start,
                    "cpu_seconds": cpu, "queue_wait_seconds": max(queue_times, default=0.0),
                    "worker_node_seconds": sum(node_times),
                    "cache_hits": sum(bool(n["output"].get("cache_reused")) for n in done["nodes"]),
                    "worker_peak_rss_mb":worker_peak_rss,
                    "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if platform.system() == "Darwin" else 1024)})
                return done

            for modality in ("xrd", "afm", "sem", "tem"):
                for iteration in range(args.repeats):
                    exp_id = experiment(f"{modality}-{iteration}")
                    if modality == "xrd":
                        content = b"10 1\n11 2\n12 10\n13 2\n14 1\n"
                        filename = "fixture.xy"; tool = "xrd.local_peaks.v1"; settings = {"xrd_x_unit": "2theta_deg"}
                        extra = {"xrd_x_unit": "2theta_deg"}
                    elif modality == "afm":
                        content = "\n".join(",".join(str(x+y) for x in range(8)) for y in range(8)).encode()
                        filename = "fixture.csv"; tool = "afm.plane_level_roughness.v1"; settings = {"afm_height_unit": "nm"}
                        extra = {"afm_height_unit": "nm"}
                    else:
                        pixels = np.zeros((32, 32), dtype=np.uint8); pixels[8:24, 8:24] = 230
                        buffer = io.BytesIO(); Image.fromarray(pixels).save(buffer, format="PNG"); content = buffer.getvalue()
                        filename = "fixture.png"; tool = "microscopy.otsu_components.v1"; settings = {"pixel_size_nm": 1.0, "foreground": "bright"}
                        extra = {"pixel_size_nm": 1.0, "foreground": "bright"}
                    upload = client.post("/api/analysis/pending", data={"modality": modality,"topic_id": topic_id,
                        "experiment_id": exp_id,"tool_id": tool,"result_key": f"{modality}-{iteration}", **extra},
                        files={"file": (filename, content, "application/octet-stream")})
                    if upload.status_code != 200: raise RuntimeError(upload.text)
                    run_id = upload.json()["id"]
                    nodes = [
                        {"key":"validate_record","tool_id":"experiment.data_quality.v1","depends_on":[],"inputs":{}},
                        {"key":"analyze_measurement","tool_id":tool,"depends_on":["validate_record"],
                         "inputs":{"analysis_run_id":run_id,"settings":settings}},
                    ]
                    goal={"xrd":"XRD 회절 피크 분석","afm":"AFM 표면 거칠기 분석",
                        "sem":"SEM 이미지 분석","tem":"TEM 이미지 분석"}[modality]
                    workflow_id, enqueue_time = queued_api(goal, nodes, exp_id, planner=True)
                    measure(f"{modality}_durable_dag", workflow_id, enqueue_time)

            for iteration in range(args.repeats):
                exp_id = experiment(f"phreeqc-{iteration}")
                chemistry = {"temperature_c": 25, "pH": 8.3, "totals_molal": {"Ca": .001, "C(4)": .001}, "phases": ["Calcite"]}
                node = {"key":"equilibrium","tool_id":"phreeqc.aqueous_equilibrium.v1","depends_on":[],
                    "inputs":{"inputs":chemistry},"approval_confirmed":True}
                workflow_id, enqueue_time = queued_api("PHREEQC 수용액 평형 계산", [node], exp_id,
                    planner=True,simulation_inputs=chemistry,approval_confirmed=True)
                measure("phreeqc_cold_worker_process" if iteration == 0 else "phreeqc_warm_run", workflow_id, enqueue_time,
                    "fresh_os_worker_process" if iteration == 0 else "same_controller_process", fresh_process=iteration == 0)

            # A true two-node PHREEQC DAG consumes the first calculation's
            # typed pH output as an explicitly declared input to the next.
            for iteration in range(args.repeats):
                exp_id = experiment(f"phreeqc-multinode-{iteration}")
                first_chemistry = {"temperature_c":25,"pH":8.3,"totals_molal":{"Ca":.001,"C(4)":.001},"phases":["Calcite"]}
                second_chemistry = {"temperature_c":25,"pH":{"$ref":{"node":"first","path":"calculated_pH","unit":"pH","meaning":"calculated equilibrium pH"}},
                    "totals_molal":{"Ca":.0008,"C(4)":.001},"phases":["Calcite"]}
                nodes = [
                    {"key":"first","tool_id":"phreeqc.aqueous_equilibrium.v1","depends_on":[],"inputs":{"inputs":first_chemistry},"approval_confirmed":True},
                    {"key":"second","tool_id":"phreeqc.aqueous_equilibrium.v1","depends_on":["first"],"inputs":{"inputs":second_chemistry},"approval_confirmed":True},
                ]
                workflow_id, enqueue_time = queued_api("PHREEQC two-node typed handoff", nodes, exp_id)
                multi = measure("phreeqc_multinode_typed_dag", workflow_id, enqueue_time)
                assert len(multi["nodes"]) == 2 and multi["nodes"][1]["output"].get("handoff_provenance")

            # Actual same-scope PHREEQC result reuse is exercised with two
            # durable workflows and verified from each persisted node output.
            exp_id = experiment("cached")
            chemistry = {"temperature_c": 25, "pH": 8.3, "totals_molal": {"Ca": .001, "C(4)": .001}, "phases": ["Calcite"]}
            node = {"key":"equilibrium","tool_id":"phreeqc.aqueous_equilibrium.v1","depends_on":[],
                "inputs":{"inputs":chemistry},"approval_confirmed":True}
            first_id, first_enqueue = queued_api("cache fill", [node], exp_id)
            first = measure("phreeqc_cache_fill", first_id, first_enqueue)
            second_id, second_enqueue = queued_api("cache reuse", [node], exp_id)
            second = measure("phreeqc_cached_workflow", second_id, second_enqueue)
            assert first["nodes"][0]["output"].get("cache_reused") is False
            assert second["nodes"][0]["output"].get("cache_reused") is True

            # Two concurrent Worker claims for identical PHREEQC work must
            # converge on one persisted SimulationRun. The worker concurrency
            # contract itself is independently covered by pytest.
            concurrent_exp = experiment("concurrent")
            run_ids = [queued_api("same-key concurrency", [node], concurrent_exp)[0] for _ in range(2)]
            start = time.perf_counter()
            worker_processes=[subprocess.Popen([sys.executable,"-m","app.worker","--once"],cwd=backend,
                env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for _ in range(2)]
            concurrent_peak_rss=0.0
            while any(process.poll() is None for process in worker_processes):
                for process in worker_processes:
                    if process.poll() is None: concurrent_peak_rss=max(concurrent_peak_rss,process_rss_mb(process.pid))
                time.sleep(.01)
            if any(process.returncode != 0 for process in worker_processes):
                raise RuntimeError("one of the concurrent Worker processes did not claim work")
            worker.refresh_cached_workflow_nodes()
            concurrent_elapsed = time.perf_counter() - start
            session = SessionLocal()
            try:
                flows = [session.get(WorkflowRun, run_id) for run_id in run_ids]
                ids = [session.query(WorkflowNode).filter_by(workflow_id=run_id).one().result_id for run_id in run_ids]
                from app.db.models import SimulationRun
                sims = session.query(SimulationRun).filter_by(experiment_id=concurrent_exp).all()
                assert all(flow and flow.status == "COMPLETED" for flow in flows)
                assert len(sims) == 1 and len(set(ids)) == 1
                results["phreeqc_same_key_concurrent"] = [{"workflow_count":2,"successful":len(flows),
                    "unique_simulation_runs":len(sims),"wall_seconds":concurrent_elapsed,
                    "worker_peak_rss_mb_sampled_max":concurrent_peak_rss}]
            finally:
                session.close()

            different_exp = experiment("different-concurrent")
            different_workflows = []
            for p_h in (7.6,8.1):
                different_chemistry={"temperature_c":25,"pH":p_h,"totals_molal":{"Ca":.001,"C(4)":.001},"phases":["Calcite"]}
                different_node={"key":"equilibrium","tool_id":"phreeqc.aqueous_equilibrium.v1","depends_on":[],
                    "inputs":{"inputs":different_chemistry},"approval_confirmed":True}
                different_workflows.append(queued_api("different-key concurrency",[different_node],different_exp)[0])
            different_started=time.perf_counter()
            different_processes=[subprocess.Popen([sys.executable,"-m","app.worker","--once"],cwd=backend,
                env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for _ in range(2)]
            different_peak_rss=0.0
            while any(process.poll() is None for process in different_processes):
                for process in different_processes:
                    if process.poll() is None: different_peak_rss=max(different_peak_rss,process_rss_mb(process.pid))
                time.sleep(.01)
            if any(process.returncode != 0 for process in different_processes): raise RuntimeError("different-key Worker did not claim work")
            different_elapsed=time.perf_counter()-different_started
            session=SessionLocal()
            try:
                flows=[session.get(WorkflowRun,workflow_id) for workflow_id in different_workflows]
                simulation_rows=session.query(SimulationRun).filter_by(experiment_id=different_exp).all()
                assert all(flow and flow.status=="COMPLETED" for flow in flows)
                assert len(simulation_rows)==2
                results["phreeqc_different_key_concurrent"]=[{"workflow_count":2,"successful":len(flows),
                    "unique_simulation_runs":len(simulation_rows),"wall_seconds":different_elapsed,
                    "worker_peak_rss_mb_sampled_max":different_peak_rss}]
            finally: session.close()

        measurements = {}
        for name, rows in results.items():
            if "end_to_end_seconds" not in rows[0]:
                measurements[name] = rows
                continue
            vals = [row["end_to_end_seconds"] for row in rows]
            sorted_vals = sorted(vals)
            measurements[name] = {"n":len(rows),"successes":sum(row["status"] == "COMPLETED" for row in rows),
                "p50_seconds":statistics.median(vals),"p95_nearest_rank_seconds":sorted_vals[max(0, __import__("math").ceil(.95*len(vals))-1)],
                "min_seconds":min(vals),"max_seconds":max(vals),"mean_cpu_seconds":statistics.mean(row["cpu_seconds"] for row in rows),
                "mean_queue_wait_seconds":statistics.mean(row["queue_wait_seconds"] for row in rows),
                "mean_worker_node_seconds":statistics.mean(row["worker_node_seconds"] for row in rows),
                "mean_enqueue_seconds":statistics.mean(row["enqueue_seconds"] for row in rows),
                "cache_hits":sum(row["cache_hits"] for row in rows),
                "worker_peak_rss_mb_max_sampled":max((row["worker_peak_rss_mb"] or 0) for row in rows),
                "controller_peak_rss_mb_max":max(row["peak_rss_mb"] for row in rows),"samples":rows}
        output = {"benchmark":"Phase 3 durable API-queue-worker integration","commit":subprocess.run(["git","rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip(),
            "platform":platform.platform(),"python":platform.python_version(),"repeats_per_modality_and_phreeqc":args.repeats,
            "synthetic_data_only":True,"isolated_temporary_database":True,"measurement_scope":"FastAPI TestClient in benchmark controller; actual durable SQLite queue and app.worker.run_once execution.",
            "limitations":["Worker code is invoked in the controller process; this report does not isolate API and Worker RSS.",
                "Cold process-start timing includes importing and executing one Worker child; worker memory is not sampled separately from the controller.",
                "The same-key concurrency case exercises two concurrent Worker claims but does not provide a broad throughput scaling curve.",
                "No scientific instrument accuracy claim is made; external data and approved CFD remain separate."],"measurements":measurements}
        json_path=Path(args.json);csv_path=Path(args.csv);json_path.parent.mkdir(parents=True,exist_ok=True);csv_path.parent.mkdir(parents=True,exist_ok=True)
        json_path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
        with csv_path.open("w",newline="") as stream:
            writer=csv.writer(stream);writer.writerow(["scenario","n","successes","p50_seconds","p95_nearest_rank_seconds","min_seconds","max_seconds","cache_hits"])
            for name,value in measurements.items():
                if isinstance(value,dict): writer.writerow([name,value["n"],value["successes"],value["p50_seconds"],value["p95_nearest_rank_seconds"],value["min_seconds"],value["max_seconds"],value["cache_hits"]])
        print(json.dumps({"json":str(json_path),"csv":str(csv_path),"measurements":{k:(v if not isinstance(v,dict) else {key:v[key] for key in ("n","successes","p50_seconds","p95_nearest_rank_seconds","cache_hits")}) for k,v in measurements.items()}},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
