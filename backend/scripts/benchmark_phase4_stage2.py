"""Run the bounded synthetic Phase 4 Stage 2 software benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.optimization.gpbo import stage2_sandbox_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--budget", type=int, default=12)
    parser.add_argument("--noise-level", type=float, default=0.08)
    parser.add_argument("--output", type=Path, default=Path("reports/phase4_stage2_benchmark.json"))
    args = parser.parse_args()
    report = stage2_sandbox_benchmark("all", args.seed, args.budget, args.seeds, args.noise_level)
    report["benchmark_kind"] = "synthetic software validation"
    report["runtime_environment"] = "Python / NumPy / SciPy; CPU"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "wall_clock_seconds": report["wall_clock_seconds"],
                      "seed_count": report["seeds"], "evaluation_budget": report["additional_evaluations"]}, indent=2))


if __name__ == "__main__":
    main()
