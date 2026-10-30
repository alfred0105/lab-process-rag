"""Launch isolated API, worker, and Vite processes for Playwright."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
BACKEND = FRONTEND.parent / "backend"
ROOT = FRONTEND.parent
VENV_PYTHON = BACKEND / ".venv" / "bin" / "python"
PYTHON = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
temp = tempfile.TemporaryDirectory(prefix="lab-process-e2e-")
env = os.environ.copy()
env.update({
    "LAB_PROCESS_DB_PATH": str(Path(temp.name) / "e2e.sqlite"),
    "LAB_PROCESS_DATA_DIR": str(Path(temp.name) / "data"),
    "LAB_PROCESS_TESTING": "1",
    "LAB_PROCESS_PYTHON": str(PYTHON),
    "LAB_PROCESS_BACKEND": str(BACKEND),
    "LAB_PROCESS_API_TARGET": "http://127.0.0.1:8001",
    "PYTHONPATH": str(BACKEND),
})
processes: list[subprocess.Popen] = []

def stop(*_):
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: process.kill()
    temp.cleanup()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

try:
    processes.append(subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=2): break
        except Exception: time.sleep(.5)
    else: raise RuntimeError("isolated API did not become ready")

    seed = r'''
from pathlib import Path
import hashlib
from datetime import date
from app.db.database import SessionLocal, DATA_ROOT
from app.db.models import ResearchTopic, Experiment, MaterialAnalysisRun
db=SessionLocal()
topic=ResearchTopic(name="Playwright isolated synthetic topic",description="Disposable browser test data")
db.add(topic);db.flush()
exp=Experiment(code="E2E-XRD-001",name="Synthetic XRD browser flow",target="XRD workflow",date=date(2026,1,1),duration_minutes=1,status="success",demo=False,topic_id=topic.id,notes="SYNTHETIC TEST ONLY")
db.add(exp);db.flush()
content="10 1\n20 2\n30 15\n40 2\n50 1\n60 14\n70 1\n"
path=DATA_ROOT/"material-analysis"/"originals"/"e2e-xrd.xy";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
run=MaterialAnalysisRun(experiment_id=exp.id,topic_id=topic.id,modality="xrd",tool_id="xrd.peak_preview.v1",filename="synthetic-e2e.xy",sha256=hashlib.sha256(content.encode()).hexdigest(),original_path=str(path),artifact_path=None,result_json={"analysis_status":"pending","demo_data":True,"provenance":{"parameters":{"xrd_x_unit":"2theta_deg"}}},analysis_status="pending",result_key="synthetic_e2e_xrd")
db.add(run);db.flush()
bad=Experiment(code="E2E-XRD-FAIL",name="Synthetic invalid XRD retry",target="XRD workflow",date=date(2026,1,2),duration_minutes=1,status="success",demo=False,topic_id=topic.id,notes="SYNTHETIC TEST ONLY")
db.add(bad);db.flush()
bad_content="this is intentionally malformed synthetic XRD data\n"
bad_path=DATA_ROOT/"material-analysis"/"originals"/"e2e-xrd-invalid.xy";bad_path.write_text(bad_content)
db.add(MaterialAnalysisRun(experiment_id=bad.id,topic_id=topic.id,modality="xrd",tool_id="xrd.peak_preview.v1",filename="synthetic-invalid-e2e.xy",sha256=hashlib.sha256(bad_content.encode()).hexdigest(),original_path=str(bad_path),artifact_path=None,result_json={"analysis_status":"pending","demo_data":True,"provenance":{"parameters":{"xrd_x_unit":"2theta_deg"}}},analysis_status="pending",result_key="synthetic_e2e_invalid_xrd"))
db.commit();print(topic.id,exp.id,bad.id);db.close()
'''
    subprocess.run([str(PYTHON), "-c", seed], cwd=BACKEND, env=env, check=True, stdout=subprocess.DEVNULL)
    processes.append(subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5174", "--strictPort"], cwd=FRONTEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    while True:
        if any(process.poll() is not None for process in processes): raise RuntimeError("an isolated E2E server exited unexpectedly")
        try:
            with urllib.request.urlopen("http://127.0.0.1:5174", timeout=2): time.sleep(.25); break
        except Exception: time.sleep(.25)
    while True: time.sleep(1)
except BaseException:
    stop()
