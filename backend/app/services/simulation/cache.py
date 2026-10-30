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


def typed_phreeqc_outputs(result: dict[str, Any], simulation_run_id: int) -> dict[str, dict[str, Any]]:
    """Expose only declared PHREEQC quantities with explicit units/meanings."""
    declarations = {
        "input_pH": ("pH", "fixed input pH"),
        "calculated_pH": ("pH", "calculated equilibrium pH"),
        "temperature_c": ("degC", "calculation temperature"),
    }
    outputs: dict[str, dict[str, Any]] = {}
    for key, (unit, meaning) in declarations.items():
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            outputs[key] = _typed(value, unit, meaning, simulation_run_id, key)
    for row in result.get("saturation_indices", []):
        phase, value = row.get("phase"), row.get("saturation_index")
        if phase and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            path = f"saturation_indices.{phase}"
            outputs[path] = _typed(value, "1", f"PHREEQC saturation index for {phase}", simulation_run_id, f"si:{phase}")
    for row in result.get("aqueous_species", []):
        species, value = row.get("name"), row.get("molality")
        if species and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            path = f"aqueous_species.{species}"
            outputs[path] = _typed(value, "mol/kgw", f"aqueous molality of {species}", simulation_run_id, f"species:{species}")
    return outputs


def _typed(value: int | float, unit: str, meaning: str, run_id: int, suffix: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "meaning": meaning, "source_type": "SIMULATION",
            "source_id": f"simulation-run:{run_id}:{suffix}", "validation_status": "NUMERICALLY_VALID",
            "uncertainty": None}
