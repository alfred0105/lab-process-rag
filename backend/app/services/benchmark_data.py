"""Read-only, provenance-preserving access to cross-domain literature run data."""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from app.db.database import ROOT

DATA_FILE = ROOT / "docs" / "research-data" / "cross-domain-process-outcomes.csv"


class BenchmarkDataError(ValueError):
    pass


def load_records() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open(encoding="utf-8-sig", newline="") as handle:
        records = []
        for row in csv.DictReader(handle):
            row["factors"] = json.loads(row.pop("factors_json"))
            row["outcomes"] = json.loads(row.pop("outcomes_json"))
            records.append(row)
        return records


def _outcome_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, dict) and isinstance(value.get("mean"), (int, float)):
        number = float(value["mean"])
    else:
        return None
    return number if math.isfinite(number) else None


def catalog() -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load_records():
        grouped[record["dataset_id"]].append(record)
    result = []
    for dataset_id, records in grouped.items():
        first = records[0]
        factor_names = sorted({key for row in records for key in row["factors"]})
        outcome_names = sorted({key for row in records for key in row["outcomes"]})
        result.append({
            "dataset_id": dataset_id,
            "run_count": len(records),
            "domain": first["domain"],
            "process_family": first["process_family"],
            "material_or_system": first["material_or_system"],
            "factor_names": factor_names,
            "outcome_names": outcome_names,
            "source_url": first["source_url"],
        })
    return sorted(result, key=lambda item: (item["domain"], item["dataset_id"]))


def dataset_records(dataset_id: str) -> list[dict[str, Any]]:
    records = [row for row in load_records() if row["dataset_id"] == dataset_id]
    if not records:
        raise BenchmarkDataError(f"Unknown literature dataset: {dataset_id}")
    return records


def summarize(dataset_id: str, outcome_key: str | None = None, objective: str = "maximize") -> dict[str, Any]:
    if objective not in {"maximize", "minimize"}:
        raise BenchmarkDataError("objective must be maximize or minimize")
    records = dataset_records(dataset_id)
    output_names = sorted({key for record in records for key in record["outcomes"]})
    if outcome_key is not None and outcome_key not in output_names:
        raise BenchmarkDataError(f"Unknown outcome for dataset: {outcome_key}")
    outcomes = {}
    for name in output_names:
        values = [(record, _outcome_number(record["outcomes"].get(name))) for record in records]
        values = [(record, value) for record, value in values if value is not None]
        if not values:
            continue
        observed_values = [value for _, value in values]
        stats = {
            "n": len(observed_values),
            "mean": mean(observed_values),
            "median": median(observed_values),
            "min": min(observed_values),
            "max": max(observed_values),
        }
        # A maximize/minimize choice is meaningful only for the one explicitly
        # selected outcome; different measurements can have opposite goals.
        if outcome_key == name:
            best = (max if objective == "maximize" else min)(observed_values)
            stats["objective"] = objective
            stats["best_observed_runs"] = [
                {"run_id": record["run_id"], "value": value, "factors": record["factors"], "source_location": record["source_location"]}
                for record, value in values if value == best
            ]
        outcomes[name] = stats
    first = records[0]
    return {
        "dataset_id": dataset_id,
        "run_count": len(records),
        "domain": first["domain"],
        "process_family": first["process_family"],
        "material_or_system": first["material_or_system"],
        "selected_outcome": outcome_key,
        "objective": objective,
        "outcomes": outcomes,
        "source_url": first["source_url"],
        "notice": "Descriptive summary of reported runs only. Best observed conditions are not a success probability, causal claim, or validated recommendation.",
    }
