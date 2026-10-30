"""Evidence-safe comparisons for recorded failure troubleshooting."""
from __future__ import annotations

import json

from app.db.models import Experiment
from app.services.experiment.compare import compare


def _eligible(target: Experiment, candidate: Experiment, comparison_mode: str) -> tuple[bool, str | None]:
    if target.id == candidate.id or candidate.status != "success":
        return False, "not_a_distinct_successful_record"
    if target.topic_id != candidate.topic_id:
        return False, "different_research_topic"
    if bool(target.demo) != bool(candidate.demo):
        return False, "demo_and_lab_records_must_not_be_mixed"
    if comparison_mode == "same_version":
        if target.method_version_id is None or candidate.method_version_id is None:
            return False, "method_version_unknown"
        if target.method_version_id != candidate.method_version_id:
            return False, "different_method_version"
    else:
        method_a = getattr(getattr(target, "method_version", None), "method_id", None)
        method_b = getattr(getattr(candidate, "method_version", None), "method_id", None)
        if not method_a or method_a != method_b:
            return False, "different_or_unknown_method"
    return True, None


def analyze(target: Experiment, pool: list[Experiment], comparison_mode: str = "same_version") -> dict:
    if comparison_mode not in {"same_version", "cross_version"}:
        raise ValueError("comparison_mode must be same_version or cross_version")

    ranked = []
    excluded = []
    for experiment in pool:
        eligible, reason = _eligible(target, experiment, comparison_mode)
        if not eligible:
            if experiment.status == "success" and experiment.id != target.id:
                excluded.append({"experiment_id": experiment.id, "code": experiment.code, "reason": reason})
            continue
        result = compare(target, experiment, comparison_mode=comparison_mode)
        context = result.get("comparison_context", {})
        if context.get("comparison_status") != "comparable":
            excluded.append({"experiment_id": experiment.id, "code": experiment.code, "reason": context.get("comparison_status", "comparison_unavailable")})
            continue
        shared = len(result["same_variables"])
        differences = len(result["different_variables"]) + len(result["missing_variables"])
        ranked.append((shared - differences, experiment, result))

    ranked.sort(key=lambda item: (-item[0], item[1].code))
    closest = []
    candidates_by_key = {}
    unresolved_by_key = {}
    for _, experiment, result in ranked[:3]:
        closest.append({"experiment_id": experiment.id, "code": experiment.code, "comparison": result})
        for difference in result["different_variables"]:
            key = json.dumps(difference.get("key"), ensure_ascii=False, separators=(",", ":"), default=str)
            candidates_by_key.setdefault(key, {
                "variable_id": key,
                "variable": difference["name"],
                "step_name": difference["step_name"],
                "step_order": difference["step_order"],
                "material": difference.get("material"),
                "method_version_id": target.method_version_id,
                "failure_value": difference["experiment_a"],
                "failure_unit": difference.get("unit_a"),
                "success_value": difference["experiment_b"],
                "success_unit": difference.get("unit_b"),
                "comparison": difference.get("comparison"),
                "evidence_status": "UNKNOWN",
                "evidence_ids": [],
                "label": "Possible variable to investigate; association is not causation",
                "success_experiment": experiment.code,
            })
        for unresolved in result["unresolved_variables"]:
            key = json.dumps(unresolved.get("key"), ensure_ascii=False, separators=(",", ":"), default=str)
            unresolved_by_key.setdefault(key, {
                "variable_id": key,
                "variable": unresolved["name"],
                "step_name": unresolved["step_name"],
                "step_order": unresolved["step_order"],
                "material": unresolved.get("material"),
                "reason": unresolved.get("reason"),
                "label": "Not ranked as a cause candidate because the values cannot be compared",
                "success_experiment": experiment.code,
            })

    observations = [{"category": item.category, "description": item.description, "severity": item.severity} for item in target.observations]
    return {
        "experiment_id": target.id,
        "comparison_mode": comparison_mode,
        "record_kind": "synthetic_demo" if target.demo else "lab_record",
        "failure_observations": observations,
        "closest_successful_experiments": closest,
        "candidate_variables": list(candidates_by_key.values()),
        "unresolved_variables": list(unresolved_by_key.values()),
        "missing_recorded_information": sorted({item["name"] for _, _, result in ranked[:3] for item in result["missing_variables"]}),
        "excluded_successful_experiments": excluded,
        "statement": "Recorded differences are investigation candidates only; causation is UNKNOWN." if closest else "UNKNOWN: no eligible successful record with a compatible, known process version is available.",
    }
