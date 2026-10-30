"""Safe numeric unit conversion for declared workflow handoffs."""
from __future__ import annotations

import math

import pint


_UNITS = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
_LOGARITHMIC_OR_MODEL_UNITS = {"ph", "si", "saturation_index", "dimensionless_ratio"}


def convert_declared_value(value: float, source_unit: str, target_unit: str,
                           uncertainty: float | None = None) -> tuple[float, float | None]:
    """Convert compatible units, keeping uncertainty as a delta quantity.

    Exact-unit values pass through untouched. pH and saturation indices are
    model/log quantities and are intentionally not converted as linear units.
    """
    if not math.isfinite(float(value)):
        raise ValueError("typed handoff value must be finite")
    if uncertainty is not None and (not math.isfinite(float(uncertainty)) or uncertainty < 0):
        raise ValueError("typed handoff uncertainty must be finite and nonnegative")
    if source_unit == target_unit:
        return float(value), float(uncertainty) if uncertainty is not None else None
    if source_unit.strip().casefold() in _LOGARITHMIC_OR_MODEL_UNITS or target_unit.strip().casefold() in _LOGARITHMIC_OR_MODEL_UNITS:
        raise ValueError("logarithmic/model units require an exact unit match")
    try:
        source = _UNITS.Unit(source_unit)
        target = _UNITS.Unit(target_unit)
        if source.dimensionality != target.dimensionality:
            raise ValueError("typed handoff units have incompatible dimensions")
        converted = float(_UNITS.Quantity(float(value), source).to(target).magnitude)
        # Conversion for an uncertainty is the magnitude scale only; do not
        # apply affine offsets such as Celsius -> Kelvin to a delta.
        delta_scale = abs(float((_UNITS.Quantity(1, source).to(target).magnitude)
                                - (_UNITS.Quantity(0, source).to(target).magnitude)))
        converted_uncertainty = float(uncertainty) * delta_scale if uncertainty is not None else None
    except pint.errors.PintError as exc:
        raise ValueError("typed handoff units cannot be converted") from exc
    if not math.isfinite(converted) or (converted_uncertainty is not None and not math.isfinite(converted_uncertainty)):
        raise ValueError("unit conversion produced a non-finite value")
    return converted, converted_uncertainty
