#!/usr/bin/env python3
"""Run the reproducible five-seed Phase 5 Stage 3 software benchmark."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.phase5_stage3 import run_robustness_benchmark


def main() -> None:
    report = run_robustness_benchmark()
    target = Path(__file__).resolve().parents[1] / "reports" / "phase5_stage3_generalization.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(target),
        "status": report["benchmark_status"],
        "seeds": report["seeds"],
        "samples_per_seed": report["samples_per_seed"],
        "v1_accuracy": report["summary"]["v1"]["accuracy"],
        "v2_accuracy": report["summary"]["v2"]["accuracy"],
        "runtime_seconds": report["runtime_seconds"],
        "peak_python_memory_bytes": report["peak_python_memory_bytes"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
