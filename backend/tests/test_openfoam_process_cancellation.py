import os
import sys
import subprocess

import pytest

from app.services.simulation.openfoam_runner import JobCancelled, _run_solver


def _spawn_tree(pid_file):
    child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"
    parent = ("import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); "
              "open(" + repr(str(pid_file)) + ",'w').write(str(child.pid)); time.sleep(30)")
    return [sys.executable, "-c", parent]


def _assert_pid_gone(pid):
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_cancel_terminates_solver_and_its_child_process(tmp_path):
    pid_file = tmp_path / "child.pid"
    with pytest.raises(JobCancelled):
        _run_solver(_spawn_tree(pid_file), timeout=20, should_cancel=lambda: pid_file.exists())
    _assert_pid_gone(int(pid_file.read_text()))


def test_timeout_terminates_solver_and_its_child_process(tmp_path):
    pid_file = tmp_path / "child.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        _run_solver(_spawn_tree(pid_file), timeout=0.01)
    _assert_pid_gone(int(pid_file.read_text()))
