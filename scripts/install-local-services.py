#!/usr/bin/env python3
"""Install the local Ollama and Lab Process RAG services for this macOS user."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
USER_ID = os.getuid()
DOMAIN = f"gui/{USER_ID}"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOGS = PROJECT / "data" / "logs"
OLLAMA = Path("/opt/homebrew/bin/ollama")
PYTHON_UVICORN = PROJECT / "backend" / ".venv" / "bin" / "uvicorn"


def install(label: str, program_arguments: list[str], working_directory: Path) -> None:
    plist_path = LAUNCH_AGENTS / f"{label}.plist"
    definition = {
        "Label": label,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(working_directory),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        "StandardOutPath": str(LOGS / f"{label}.log"),
        "StandardErrorPath": str(LOGS / f"{label}.error.log"),
    }
    plist_path.write_bytes(plistlib.dumps(definition))
    subprocess.run(["launchctl", "bootout", DOMAIN, str(plist_path)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", DOMAIN, str(plist_path)], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{DOMAIN}/{label}"], check=True)


def main() -> None:
    if not OLLAMA.exists():
        raise SystemExit(f"Ollama executable was not found at {OLLAMA}")
    if not PYTHON_UVICORN.exists():
        raise SystemExit(f"Project virtual environment was not found at {PYTHON_UVICORN}")
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    install("com.labprocessrag.ollama", [str(OLLAMA), "serve"], PROJECT)
    install(
        "com.labprocessrag.web",
        [str(PYTHON_UVICORN), "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        PROJECT / "backend",
    )
    print("Installed and started local Lab Process RAG and Ollama services.")
    print("Open http://localhost:8000/ in a browser or save it as a bookmark.")


if __name__ == "__main__":
    main()
