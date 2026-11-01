"""Generate the frozen Stage 4 zero-shot cross-recipe transfer report."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.phase5_cross_recipe import run_cross_recipe_transfer


REPORT = ROOT / "reports" / "phase5_stage4_cross_recipe_transfer.json"


def main() -> None:
    result = run_cross_recipe_transfer()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({
        "report": str(REPORT),
        "protocol": result["protocol_version"],
        "source_hash": result["source_dataset_hash"],
        "target_evaluation_hash": result["target_evaluation_hash"],
        "target_test_count": result["target_split"]["test"],
    }))


if __name__ == "__main__":
    main()
