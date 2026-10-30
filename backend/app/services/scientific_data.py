"""Create traceable, normalized scalar observations without changing originals."""
from __future__ import annotations

import math
import re

import pint

from app.db.models import ScientificObservation

_UNITS = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_BOOLS = {"true": True, "false": False, "yes": True, "no": False, "성공": True, "실패": False, "예": True, "아니오": False}
_ALIASES = {"µ": "u", "μ": "u", "°C": "degC", "℃": "degC", "°F": "degF", "·": "*", "⁻": "-", "²": "2", "³": "3"}


def _unit(raw: str | None) -> str:
    value = (raw or "").strip()
    if value.casefold() in {"min", "mins"}:
        return "minute"
    if value.casefold() in {"h", "hr", "hrs"}:
        return "hour"
    for source, target in _ALIASES.items():
        value = value.replace(source, target)
    return value


def _parameter_id(step_name: str, name: str, material: str | None = None) -> str:
    raw = "/".join(part.strip().casefold() for part in (step_name, name, material or "") if part.strip())
    return re.sub(r"[^\w]+", "_", raw, flags=re.UNICODE).strip("_")[:300]


def normalize_scalar(step_name: str, name: str, value: object, unit: str | None = None, *, material: str | None = None, uncertainty: float | None = None) -> dict:
    """Return typed value, base-unit scalar, stable scoped ID, or a visible error."""
    original = "" if value is None else str(value).strip()
    if not original:
        return {"parameter_id": _parameter_id(step_name, name, material), "original_value": original, "original_unit": unit, "normalized_value": None, "normalized_unit": None, "value_type": "missing", "measurement_uncertainty": uncertainty, "normalization_error": "value_missing"}
    if uncertainty is not None and (not math.isfinite(uncertainty) or uncertainty < 0):
        raise ValueError("measurement uncertainty must be finite and nonnegative")
    token = original.casefold()
    if token in _BOOLS:
        return {"parameter_id": _parameter_id(step_name, name, material), "original_value": original, "original_unit": unit, "normalized_value": None, "normalized_unit": None, "value_type": "boolean", "measurement_uncertainty": uncertainty, "normalization_error": "units_not_applicable" if unit else None}
    normalized = original.replace(",", ".") if original.count(",") == 1 and "." not in original else original
    if not _NUMBER.fullmatch(normalized):
        return {"parameter_id": _parameter_id(step_name, name, material), "original_value": original, "original_unit": unit, "normalized_value": None, "normalized_unit": None, "value_type": "categorical" if not unit else "text", "measurement_uncertainty": uncertainty, "normalization_error": "unit_attached_to_non_numeric_value" if unit else None}
    number = float(normalized)
    if not math.isfinite(number):
        raise ValueError("numeric values must be finite")
    clean_unit = _unit(unit)
    if not clean_unit:
        base_value, base_unit, error = number, None, None
    elif clean_unit.casefold() == "ph":
        # pH is logarithmic and is deliberately preserved without linear conversion.
        base_value, base_unit, error = number, "pH", None
    else:
        try:
            quantity = _UNITS.Quantity(number, clean_unit).to_base_units()
            base_value, base_unit, error = float(quantity.magnitude), str(quantity.units), None
            if not math.isfinite(base_value):
                raise ValueError("unit conversion returned a non-finite value")
        except (pint.errors.PintError, ValueError, TypeError) as exc:
            base_value, base_unit, error = None, None, f"unit_conversion_failed: {str(exc)[:240]}"
    if uncertainty is not None and error is None and unit and clean_unit.casefold() != "ph":
        try:
            delta_unit={"degc":"delta_degC","degf":"delta_degF"}.get(clean_unit.casefold(),clean_unit)
            uncertainty = abs(float(_UNITS.Quantity(uncertainty, delta_unit).to_base_units().magnitude))
        except pint.errors.PintError as exc:
            error = f"uncertainty_conversion_failed: {str(exc)[:240]}"
            base_value, base_unit = None, None
    return {"parameter_id": _parameter_id(step_name, name, material), "original_value": original, "original_unit": unit, "normalized_value": base_value, "normalized_unit": base_unit, "value_type": "number", "measurement_uncertainty": uncertainty, "normalization_error": error}


def make_observation(*, experiment_id: int | None, method_version_id: int | None, process_step_id: int | None, step_name: str, name: str, value: object, unit: str | None, source_type: str, source_id: str, topic_id: int | None = None, material: str | None = None, material_id: int | None = None, analysis_run_id: int | None = None, review_status: str = "PENDING", uncertainty: float | None = None) -> ScientificObservation:
    if source_type not in {"LAB_RECORD", "LAB_RESULT", "SYNTHETIC_DEMO", "LITERATURE", "SIMULATION", "ANALYSIS_OUTPUT"}:
        raise ValueError(f"unsupported scientific observation source type: {source_type}")
    data = normalize_scalar(step_name, name, value, unit, material=material, uncertainty=uncertainty)
    return ScientificObservation(
        topic_id=topic_id, experiment_id=experiment_id, method_version_id=method_version_id,
        process_step_id=process_step_id, material_id=material_id,
        source_type=source_type, source_id=str(source_id), analysis_run_id=analysis_run_id,
        review_status=review_status, **data,
    )
