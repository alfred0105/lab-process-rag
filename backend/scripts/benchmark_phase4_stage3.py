"""Run the Stage 3 synthetic multi-objective benchmark suite and save JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.optimization.multiobjective import run_moo_benchmarks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("reports/phase4_stage3_benchmark.json"))
    args = parser.parse_args()
    result = run_moo_benchmarks(seed=args.seed, seeds=5, budget=args.budget, mc_samples=32, candidate_pool_size=48)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "runtime_seconds": result["runtime_seconds"],
        "benchmarks": {name: {policy: summary["mean_hypervolume"] for policy, summary in detail["policies"].items()}
            for name, detail in result["benchmarks"].items()}}, indent=2))


if __name__ == "__main__":
    main()
