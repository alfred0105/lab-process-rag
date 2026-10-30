"""Canonical, versioned identity for reusable PHREEQC calculations."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.simulation.phreeqc import _database_provenance

PHREEQC_ALGORITHM_VERSION = "phreeqc-adapter:2"


def phreeqc_cache_identity(
    *, tool_id: str, tool_version: str, topic_id: int, experiment_id: int,
    process_step_id: int | None, parameters: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Return the same cache key/payload for the direct API and durable Worker.

    Topic, experiment, and step are deliberately part of the scope. This
    prevents cross-topic/result mixing and avoids reusing calculations attached
    to different process stages. The exact bundled database bytes participate
    in cache invalidation.
    """
    stable = {
        "tool_id": tool_id,
        "tool_version": tool_version,
        "algorithm_version": PHREEQC_ALGORITHM_VERSION,
        "topic_id": topic_id,
        "experiment_id": experiment_id,
        "process_step_id": process_step_id,
        "parameters": parameters,
        "model": _database_provenance(),
    }
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), stable


def typed_phreeqc_outputs(result: dict[str, Any], simulation_run_id: int, *, review_status: str = "COMPUTED") -> dict[str, dict[str, Any]]:
    """Expose PHREEQC quantities under the durable typed-artifact contract.

    A completed calculation is COMPUTED, never ACCEPTED. Legacy persisted
    records can be projected only as COMPUTED; scientific acceptance remains
    a separate human review event.
    """
    if review_status not in {"COMPUTED", "REVIEWED", "ACCEPTED", "REJECTED"}:
        raise ValueError("Invalid PHREEQC review status")
    provenance = result.get("provenance") or {}
    tool_id = provenance.get("tool_id")
    tool_version = provenance.get("tool_version")
    database_sha256 = result.get("database_sha256") or provenance.get("database_sha256")
    if not (isinstance(tool_id, str) and tool_id.startswith("phreeqc.") and isinstance(tool_version, str)
            and isinstance(database_sha256, str) and len(database_sha256) == 64):
        raise ValueError("PHREEQC typed output is missing recoverable tool/version/database provenance")
    parent_data_ids = provenance.get("parent_data_ids") or [f"simulation-run:{simulation_run_id}"]
    declarations = {
        "input_pH": ("pH", "fixed input pH"),
        "calculated_pH": ("pH", "calculated equilibrium pH"),
        "temperature_c": ("degC", "calculation temperature"),
    }
    outputs: dict[str, dict[str, Any]] = {}
    for key, (unit, meaning) in declarations.items():
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            outputs[key] = _typed(value, unit, meaning, simulation_run_id, key, tool_id, tool_version, parent_data_ids, review_status, database_sha256)
    for row in result.get("saturation_indices", []):
        phase, value = row.get("phase"), row.get("saturation_index")
        if phase and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            path = f"saturation_indices.{phase}"
            outputs[path] = _typed(value, "1", f"PHREEQC saturation index for {phase}", simulation_run_id, f"si:{phase}", tool_id, tool_version, parent_data_ids, review_status, database_sha256)
    for row in result.get("aqueous_species", []):
        species, value = row.get("name"), row.get("molality")
        if species and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            path = f"aqueous_species.{species}"
            outputs[path] = _typed(value, "mol/kgw", f"aqueous molality of {species}", simulation_run_id, f"species:{species}", tool_id, tool_version, parent_data_ids, review_status, database_sha256)
    return outputs


def _typed(value: int | float, unit: str, meaning: str, run_id: int, suffix: str,
           tool_id: str | None, tool_version: str | None, parent_data_ids: list[str],
           review_status: str, database_sha256: str | None) -> dict[str, Any]:
    return {"value": value, "unit": unit, "meaning": meaning, "source_type": "SIMULATION",
            "source_id": f"simulation-run:{run_id}:{suffix}", "validation_status": "NUMERICALLY_VALID",
            "review_status": review_status, "tool_id": tool_id, "tool_version": tool_version,
            "parent_data_ids": parent_data_ids, "model_id": "PHREEQC-3 / phreeqc.dat",
            "database_sha256": database_sha256, "uncertainty": None}
