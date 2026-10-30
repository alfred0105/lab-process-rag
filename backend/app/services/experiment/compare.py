"""Context-aware comparison of experiment process variables.

Variable row IDs are local to a run, so comparisons use a stable semantic key:
step order/type/name, variable name, material, and duplicate occurrence. Numeric
values are converted with Pint only when their units are dimensionally compatible.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

import pint

from app.db.models import Experiment


_UNIT_REGISTRY = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_UNIT_ALIASES = {
    "µ": "u",
    "μ": "u",
    "°C": "degC",
    "℃": "degC",
    "°F": "degF",
    "°": "degree",
    "·": "*",
    "⁻": "-",
    "¹": "1",
    "²": "2",
    "³": "3",
}


def _label(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _number(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    if not _NUMERIC.fullmatch(text):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _unit_text(value: Any) -> str:
    unit = str(value or "").strip()
    # Pint's short forms ``min`` and ``h`` can resolve to angular units in
    # contexts where they are ambiguous; prefer the common lab time units.
    if unit.casefold() in {"min", "mins"}:
        return "minute"
    if unit.casefold() in {"h", "hr", "hrs"}:
        return "hour"
    for source, replacement in _UNIT_ALIASES.items():
        unit = unit.replace(source, replacement)
    return unit


def _condition_definition(exp: Experiment, step: Any, variable: Any) -> dict | None:
    version = getattr(exp, "method_version", None)
    definitions = getattr(version, "condition_definitions", None) or []
    candidates = [
        item for item in definitions
        if _label(item.get("step_name")) == _label(step.name)
        and _label(item.get("name")) == _label(variable.name)
    ]
    if not candidates:
        return None
    variable_unit = _unit_text(variable.unit)
    return next((item for item in candidates if _unit_text(item.get("unit")) == variable_unit), candidates[0])


def _value_type(exp: Experiment, step: Any, variable: Any) -> str:
    definition = _condition_definition(exp, step, variable)
    declared = str(definition.get("value_type", "")) if definition else ""
    if declared in {"boolean", "text", "number"}:
        return declared
    raw = str(variable.value or "").strip().casefold()
    if raw in {"true", "false", "yes", "no", "예", "아니오", "성공", "실패"}:
        return "boolean"
    return "number" if _number(variable.value) is not None else "text"


def _semantic_key(exp: Experiment, step: Any, variable: Any, occurrence: int, value_type: str) -> tuple:
    return (
        int(step.order_index),
        _label(step.step_type),
        _label(step.name),
        _label(variable.name),
        _label(variable.material),
        occurrence,
    )


def _variables(exp: Experiment) -> dict[tuple, dict]:
    output: dict[tuple, dict] = {}
    occurrences: dict[tuple, int] = defaultdict(int)
    steps = sorted(exp.steps or [], key=lambda item: (item.order_index, item.id or 0))
    for step in steps:
        for variable in step.variables or []:
            value_type = _value_type(exp, step, variable)
            identity = (
                int(step.order_index), _label(step.step_type), _label(step.name),
                _label(variable.name), _label(variable.material),
            )
            occurrence = occurrences[identity]
            occurrences[identity] += 1
            key = _semantic_key(exp, step, variable, occurrence, value_type)
            output[key] = {
                "key": key,
                "name": variable.name,
                "step_name": step.name,
                "step_order": step.order_index,
                "step_type": step.step_type,
                "material": variable.material,
                "value": variable.value,
                "unit": variable.unit,
                # Legacy ProcessVariable has no uncertainty column. Keep this
                # optional hook for richer imported/adapter-backed records.
                "measurement_uncertainty": getattr(variable, "measurement_uncertainty", None),
                "value_type": value_type,
                "definition": _condition_definition(exp, step, variable),
            }
    return output


def variable_map(exp: Experiment) -> dict[str, tuple]:
    """Backward-compatible flattened view, with step context in every key."""
    return {
        f"{item['step_order']}:{item['step_name']}:{item['name']}:{key[-1]}":
            (item["value"], item["unit"], item["material"])
        for key, item in _variables(exp).items()
    }


def _numeric_comparison(a: dict, b: dict) -> dict:
    value_a = _number(a["value"])
    value_b = _number(b["value"])
    unit_a = _unit_text(a.get("unit"))
    unit_b = _unit_text(b.get("unit"))
    if value_a is None or value_b is None:
        return {"comparable": False, "same": False, "reason": "non_numeric_value"}
    if bool(unit_a) != bool(unit_b):
        return {"comparable": False, "same": False, "reason": "unit_missing_on_one_record"}
    try:
        if unit_a:
            quantity_a = _UNIT_REGISTRY.Quantity(value_a, unit_a).to_base_units()
            quantity_b = _UNIT_REGISTRY.Quantity(value_b, unit_b).to(quantity_a.units)
            normalized_a = float(quantity_a.magnitude)
            normalized_b = float(quantity_b.magnitude)
            normalized_unit = str(quantity_a.units)
        else:
            normalized_a, normalized_b, normalized_unit = value_a, value_b, None
    except (pint.errors.PintError, ValueError, TypeError) as exc:
        return {"comparable": False, "same": False, "reason": "incompatible_or_unknown_units", "detail": str(exc)[:160]}
    # Only use reported measurement uncertainties when both records provide
    # them. Otherwise this is a near-exact numeric equality check with a
    # floating-point conversion tolerance, not an assumed measurement precision.
    uncertainty_a = a.get("measurement_uncertainty")
    uncertainty_b = b.get("measurement_uncertainty")
    if uncertainty_a is not None and uncertainty_b is not None:
        try:
            uncertainty_a = float(uncertainty_a)
            uncertainty_b = float(uncertainty_b)
            if unit_a:
                delta_a = {"degC": "delta_degC", "degF": "delta_degF"}.get(unit_a, unit_a)
                delta_b = {"degC": "delta_degC", "degF": "delta_degF"}.get(unit_b, unit_b)
                target_delta = {"degC": "delta_degC", "degF": "delta_degF"}.get(str(quantity_a.units), str(quantity_a.units))
                uncertainty_a = float(_UNIT_REGISTRY.Quantity(uncertainty_a, delta_a).to(target_delta).magnitude)
                uncertainty_b = float(_UNIT_REGISTRY.Quantity(uncertainty_b, delta_b).to(target_delta).magnitude)
            if not (math.isfinite(uncertainty_a) and math.isfinite(uncertainty_b) and uncertainty_a >= 0 and uncertainty_b >= 0):
                raise ValueError("measurement uncertainty must be finite and nonnegative")
            tolerance = math.hypot(uncertainty_a, uncertainty_b)
            basis = "combined_reported_standard_uncertainty"
        except (pint.errors.PintError, ValueError, TypeError) as exc:
            return {"comparable": False, "same": False, "reason": "invalid_measurement_uncertainty", "detail": str(exc)[:160]}
    else:
        tolerance = max(1e-15, max(abs(normalized_a), abs(normalized_b)) * 1e-12)
        basis = "floating_point_conversion_only_no_measurement_precision_assumed"
    same = abs(normalized_a - normalized_b) <= tolerance
    return {
        "comparable": True,
        "same": same,
        "normalized_a": normalized_a,
        "normalized_b": normalized_b,
        "normalized_unit": normalized_unit,
        "comparison_tolerance": tolerance,
        "tolerance_basis": basis,
        "reason": "unit_normalized_numeric_comparison",
    }


def _compare_value(a: dict, b: dict) -> dict:
    if a["value"] is None or b["value"] is None or not str(a["value"]).strip() or not str(b["value"]).strip():
        return {"comparable": False, "same": False, "reason": "value_missing"}
    if a["value_type"] != b["value_type"]:
        return {"comparable": False, "same": False, "reason": "value_type_changed"}
    if a["value_type"] == "number":
        return _numeric_comparison(a, b)
    same = str(a["value"] or "").strip().casefold() == str(b["value"] or "").strip().casefold()
    return {"comparable": True, "same": same, "reason": "casefolded_categorical_comparison"}


def _context(exp: Experiment) -> dict:
    version = getattr(exp, "method_version", None)
    return {
        "method_version_id": exp.method_version_id,
        "method_version_label": getattr(version, "version_label", None) if version else None,
    }


def compare(a: Experiment, b: Experiment, comparison_mode: str = "same_version") -> dict:
    if comparison_mode not in {"same_version", "cross_version"}:
        raise ValueError("comparison_mode must be same_version or cross_version")
    version_a = _context(a)
    version_b = _context(b)
    same_known_version = (
        a.method_version_id is not None
        and b.method_version_id is not None
        and a.method_version_id == b.method_version_id
    )
    if comparison_mode == "same_version" and not same_known_version:
        return {
            "same_variables": [], "different_variables": [], "missing_variables": [],
            "unresolved_variables": [], "comparison_context": {
                "experiment_a": version_a, "experiment_b": version_b,
                "same_method_version": False, "comparison_mode": comparison_mode,
                "comparison_status": "blocked_version_mismatch_or_unknown",
                "uncertainty_available": False,
            },
        }
    if comparison_mode == "cross_version":
        method_a = getattr(getattr(a, "method_version", None), "method_id", None)
        method_b = getattr(getattr(b, "method_version", None), "method_id", None)
        if not (method_a and method_b and method_a == method_b):
            return {
                "same_variables": [], "different_variables": [], "missing_variables": [],
                "unresolved_variables": [], "comparison_context": {
                    "experiment_a": version_a, "experiment_b": version_b,
                    "same_method_version": False, "comparison_mode": comparison_mode,
                    "comparison_status": "blocked_unrelated_or_unknown_methods",
                    "uncertainty_available": False,
                },
            }
    variables_a, variables_b = _variables(a), _variables(b)
    same: list[dict] = []
    different: list[dict] = []
    missing: list[dict] = []
    unresolved: list[dict] = []

    for key in sorted(variables_a.keys() | variables_b.keys()):
        left, right = variables_a.get(key), variables_b.get(key)
        if left is None or right is None:
            item = left or right
            missing.append({
                "key": key,
                "name": item["name"],
                "step_name": item["step_name"],
                "step_order": item["step_order"],
                "experiment_a": (left["value"], left["unit"], left["material"]) if left else None,
                "experiment_b": (right["value"], right["unit"], right["material"]) if right else None,
            })
            continue
        comparison = _compare_value(left, right)
        detail = {
            "key": key,
            "name": left["name"],
            "step_name": left["step_name"],
            "step_order": left["step_order"],
            "material": left["material"],
            "experiment_a": left["value"],
            "unit_a": left["unit"],
            "experiment_b": right["value"],
            "unit_b": right["unit"],
            "comparison": comparison,
            "measurement_uncertainty": "not_recorded",
        }
        if not comparison["comparable"]:
            unresolved.append({**detail, "reason": comparison["reason"]})
        elif comparison["same"]:
            same.append({
                **detail,
                "value": left["value"],
                "unit": left["unit"],
                "normalized_value": comparison.get("normalized_a"),
                "normalized_unit": comparison.get("normalized_unit"),
            })
        else:
            different.append(detail)

    return {
        "same_variables": same,
        "different_variables": different,
        "missing_variables": missing,
        "unresolved_variables": unresolved,
        "comparison_context": {
            "experiment_a": version_a,
            "experiment_b": version_b,
            "same_method_version": version_a["method_version_id"] == version_b["method_version_id"],
            "comparison_mode": comparison_mode,
            "comparison_status": "comparable",
            "uncertainty_available": False,
        },
    }
