"""Stage and execute the pinned OpenFOAM 14 simpleRushtonMRF tutorial."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path


INSTANCE = os.getenv("OPENFOAM_MULTIPASS_INSTANCE", "lab-rag-openfoam").strip()
MULTIPASS = next((path for path in ("/usr/local/bin/multipass", "/opt/homebrew/bin/multipass") if Path(path).exists()), "multipass")
TUTORIAL = "/opt/openfoam14/tutorials/incompressibleFluid/simpleRushtonMRF"


def _run(args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


POWER_COLUMNS = ("time_s", "divStressU", "divStressDotU", "stressDDotGradU", "divPU", "gradPU", "pDivU", "divTauU", "divTauDotU", "tauDDotGradU")


def parse_power_trace(text: str) -> list[dict]:
    trace=[]
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            values=[float(value) for value in line.split()]
        except ValueError:
            continue
        if len(values)==len(POWER_COLUMNS) and all(math.isfinite(value) for value in values):
            trace.append(dict(zip(POWER_COLUMNS,values)))
    return trace


def run_openfoam(config: dict) -> dict:
    """Run one explicit, validated case and return its log plus extracted power trace."""
    for key in ("tank_diameter_m", "tank_height_m", "impeller_diameter_m", "rpm", "nu_m2_s"):
        value = float(config[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid validated OpenFOAM input: {key}")
    blades = int(config["blade_count"])
    if blades not in (4, 6):
        raise ValueError("Only 4 or 6 blade Rushton impellers are supported")
    case_id = uuid.uuid4().hex
    guest = f"/home/ubuntu/OpenFOAM/ubuntu-14/run/lab-rag-{case_id}"
    local_dir = Path(tempfile.mkdtemp(prefix="lab-rag-of-"))
    payload = local_dir / "case.json"
    payload.write_text(json.dumps({**config, "case_dir": guest}, allow_nan=False), encoding="utf-8")
    script = Path(__file__).with_name("openfoam_guest_runner.py")
    try:
        transfer = _run([MULTIPASS, "transfer", str(payload), f"{INSTANCE}:/tmp/lab-rag-{case_id}.json"])
        if transfer.returncode:
            raise RuntimeError(transfer.stderr[-4000:] or "Could not transfer validated simulation inputs")
        transfer_script = _run([MULTIPASS, "transfer", str(script), f"{INSTANCE}:/tmp/lab-rag-runner.py"])
        if transfer_script.returncode:
            raise RuntimeError(transfer_script.stderr[-4000:] or "Could not transfer the case runner")
        command = [MULTIPASS, "exec", INSTANCE, "--", "bash", "-lc", f". /opt/openfoam14/etc/bashrc >/dev/null 2>&1 && python3 /tmp/lab-rag-runner.py /tmp/lab-rag-{case_id}.json"]
        result = _run(command, timeout=1800)
        combined = (result.stdout + "\n" + result.stderr)[-40000:]
        if result.returncode:
            raise RuntimeError(combined or f"OpenFOAM exited with status {result.returncode}")
        solver_end = _run([MULTIPASS, "exec", INSTANCE, "--", "bash", "-lc", f"tail -n 1 {guest}/log.foamRun"], timeout=30)
        if solver_end.returncode or solver_end.stdout.strip() != "End":
            raise RuntimeError("OpenFOAM command returned, but the solver log does not end with the normal 'End' marker; this run is not complete.")
        power = _run([MULTIPASS, "exec", INSTANCE, "--", "bash", "-lc", f"cat {guest}/postProcessing/power/0/power.dat 2>/dev/null | tail -n 200"], timeout=30)
        trace=parse_power_trace(power.stdout)
        if len(trace) < 2:
            raise RuntimeError("OpenFOAM ended normally but produced fewer than two power-output points; no result was marked complete.")
        number_match=re.search(r"Power number\s*=\s*([0-9.eE+-]+)",combined)
        power_number=float(number_match.group(1)) if number_match else None
        return {"case_id": case_id, "solver": "foamRun (incompressibleFluid)", "mesh_size": "1 (~68k template cells)", "power_trace": trace, "power_number": power_number, "power_number_method": "OpenFOAM tutorial Allrun post-processing formula", "case_path": guest, "limits": ["single-phase Newtonian liquid; steady MRF Rushton case", "power number uses tutorial's dimensionless scaling; confirm applicability for the entered geometry and fluid regime", "not a prediction of concentration mixing time, precipitation, nucleation, particle size, or yield"]}, combined
    finally:
        payload.unlink(missing_ok=True)
        local_dir.rmdir()
