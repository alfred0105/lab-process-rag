"""Stage and execute the pinned OpenFOAM 14 simpleRushtonMRF tutorial."""
from __future__ import annotations

import json
import math
import os
import signal
import re
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path


INSTANCE = os.getenv("OPENFOAM_MULTIPASS_INSTANCE", "lab-rag-openfoam").strip()
MULTIPASS = next((path for path in ("/usr/local/bin/multipass", "/opt/homebrew/bin/multipass") if Path(path).exists()), "multipass")
TUTORIAL = "/opt/openfoam14/tutorials/incompressibleFluid/simpleRushtonMRF"


class JobCancelled(RuntimeError): pass


def _run(args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def probe_openfoam_installation(instance: str | None = None) -> dict:
    """Check the same VM, installation, and tutorial template used by the runner."""
    instance_name = (instance or INSTANCE).strip()
    if not instance_name:
        return {"installed": False, "version": None, "template_available": False}
    try:
        install = _run([
            MULTIPASS, "exec", instance_name, "--", "bash", "-lc",
            ". /opt/openfoam14/etc/bashrc >/dev/null 2>&1 && foamRun -help",
        ], timeout=12)
        output = f"{install.stdout}\n{install.stderr}"
        installed = install.returncode == 0 and "Usage" in output
        if not installed:
            return {"installed": False, "version": None, "template_available": False}
        template = _run([
            MULTIPASS, "exec", instance_name, "--", "bash", "-lc",
            f"test -d {TUTORIAL} && test -f {TUTORIAL}/system/blockMeshDict.orig",
        ], timeout=8)
        return {
            "installed": True,
            "version": "14",
            "template_available": template.returncode == 0,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": False, "version": None, "template_available": False}


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


def _terminate_process_group(process, grace_seconds:float=2.0):
    """Stop the isolated solver and its child processes, escalating if needed."""
    if process.poll() is not None:
        return process.communicate()
    try:
        os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()


def _run_solver(args:list[str],*,timeout:int,should_cancel=None,cancel_remote=None):
    process=subprocess.Popen(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    started=__import__("time").monotonic()
    try:
        while process.poll() is None:
            if should_cancel and should_cancel():
                try:
                    if cancel_remote: cancel_remote()
                except Exception:
                    pass
                finally:
                    stdout,stderr=_terminate_process_group(process)
                raise JobCancelled((stdout or "")+(stderr or ""))
            if __import__("time").monotonic()-started>timeout:
                try:
                    if cancel_remote: cancel_remote()
                except Exception:
                    pass
                finally:
                    stdout,stderr=_terminate_process_group(process)
                raise subprocess.TimeoutExpired(args,timeout,output=stdout,stderr=stderr)
            __import__("time").sleep(0.5)
        stdout,stderr=process.communicate()
        return subprocess.CompletedProcess(args,process.returncode,stdout,stderr)
    finally:
        if process.poll() is None: _terminate_process_group(process)


def run_openfoam(config: dict, *, should_cancel=None) -> tuple[dict,str]:
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
    control_dir=f"/tmp/lab-rag-{case_id}-control"
    local_dir = Path(tempfile.mkdtemp(prefix="lab-rag-of-"))
    payload = local_dir / "case.json"
    payload.write_text(json.dumps({**config, "case_dir": guest,"control_dir":control_dir}, allow_nan=False), encoding="utf-8")
    script = Path(__file__).with_name("openfoam_guest_runner.py")
    try:
        transfer = _run([MULTIPASS, "transfer", str(payload), f"{INSTANCE}:/tmp/lab-rag-{case_id}.json"])
        if transfer.returncode:
            raise RuntimeError(transfer.stderr[-4000:] or "Could not transfer validated simulation inputs")
        transfer_script = _run([MULTIPASS, "transfer", str(script), f"{INSTANCE}:/tmp/lab-rag-runner.py"])
        if transfer_script.returncode:
            raise RuntimeError(transfer_script.stderr[-4000:] or "Could not transfer the case runner")
        command = [MULTIPASS, "exec", INSTANCE, "--", "bash", "-lc", f". /opt/openfoam14/etc/bashrc >/dev/null 2>&1 && python3 /tmp/lab-rag-runner.py /tmp/lab-rag-{case_id}.json"]
        cancel_command=[MULTIPASS,"exec",INSTANCE,"--","bash","-lc",
            f"pid_file={shlex.quote(control_dir+'/solver.pgid')}; if [ -s \"$pid_file\" ]; then pgid=$(cat \"$pid_file\"); kill -TERM -- -\"$pgid\" 2>/dev/null || true; fi"]
        result = _run_solver(command, timeout=min(int(config.get("timeout_seconds",1700)),1700),should_cancel=should_cancel,
            cancel_remote=lambda:_run(cancel_command,timeout=12))
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
        cell_match=re.search(r"(?:cells\s*:\s*|\b)(\d+)\s+cells\b",combined,re.I)
        residuals=[float(value) for value in re.findall(r"Final residual\s*=\s*([0-9.eE+-]+)",combined)]
        mesh_cells=int(cell_match.group(1)) if cell_match else None
        solver_converged=bool(residuals) and all(math.isfinite(value) and value<=1e-3 for value in residuals)
        return {"case_id": case_id, "solver": "foamRun (incompressibleFluid)", "mesh_cell_count":mesh_cells,
            "mesh_validation":"CHECKMESH_OK" if re.search(r"Mesh OK\.",combined) else "UNVERIFIED",
            "final_residuals":residuals,"solver_converged":solver_converged,"solver_completed_marker":"End",
            "power_trace": trace, "power_number": power_number, "power_number_method": "OpenFOAM tutorial Allrun post-processing formula", "case_path": guest,
            "limits": ["single-phase Newtonian liquid; steady MRF Rushton case", "power number uses tutorial's dimensionless scaling; confirm applicability for the entered geometry and fluid regime", "not a prediction of concentration mixing time, precipitation, nucleation, particle size, or yield"]}, combined
    finally:
        payload.unlink(missing_ok=True)
        local_dir.rmdir()
        _run([MULTIPASS,"exec",INSTANCE,"--","bash","-lc",f"rm -f {shlex.quote(control_dir+'/solver.pgid')}; rmdir {shlex.quote(control_dir)} 2>/dev/null || true"],timeout=15)
