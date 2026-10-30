"""Input compatibility checks for the installed single-phase Rushton MRF case.

This planner does not run CFD. It refuses to imply that the packaged tutorial
matches arbitrary mixer geometry or an open/free-surface vessel.
"""
from __future__ import annotations

import math
import re


MODEL_ID = "OpenFOAM-14/simpleRushtonMRF"
LIMITATIONS = [
    "The selected template models steady single-phase Newtonian flow in a baffled cylindrical tank with a Rushton turbine.",
    "The tank is represented as completely liquid-filled with a closed rigid top; open free surfaces, gas entrainment, dosing jets, and reactive scalar transport are not modeled.",
    "The flow and impeller power are estimates for the stated geometry and constant properties. They do not predict concentration homogenization time, precipitation, nucleation, particle size, or yield.",
    "Only 4- or 6-blade Rushton turbines are supported by this template. Other impeller types are not approximated as Rushton turbines.",
]


def _normal_unit(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("³", "3").replace("²", "2").replace("⁻", "-").replace("¹", "1").replace("·", "*").replace("−", "-")


def _positive_number(value: object) -> float | None:
    try:
        number = float(str(value).strip().replace(",", "."))
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def _length_m(value: object, unit: object) -> float | None:
    number = _positive_number(value)
    key = _normal_unit(unit)
    factor = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "inch": 0.0254, "inches": 0.0254}.get(key)
    return number * factor if number is not None and factor is not None else None


def _numeric_variable(variables: list[dict], pattern: str) -> float | None:
    for item in variables:
        if re.search(pattern, str(item.get("name", "")), re.I):
            result = _positive_number(item.get("value"))
            if result is not None:
                return result
    return None


def _length_variable(variables: list[dict], pattern: str) -> float | None:
    for item in variables:
        if re.search(pattern, str(item.get("name", "")), re.I):
            result = _length_m(item.get("value"), item.get("unit"))
            if result is not None:
                return result
    return None


def _geometry_length(text: str, dimension: str) -> float | None:
    if dimension == "diameter":
        label = r"(?:inner\s*)?(?:diameter|dia\.?|지름|직경)"
    else:
        label = r"(?:liquid\s*)?(?:height|높이|깊이)"
    match = re.search(rf"{label}\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m|in(?:ches?)?)\b", text, re.I)
    return _length_m(match.group(1), match.group(2)) if match else None


def _volume_m3(variables: list[dict]) -> float | None:
    for item in variables:
        if not re.search(r"(?:liquid|solution|working|batch)[_ -]?(?:volume|amount)", str(item.get("name", "")), re.I):
            continue
        value = _positive_number(item.get("value"))
        unit = _normal_unit(item.get("unit"))
        factor = {"m3": 1.0, "l": 0.001, "liter": 0.001, "litre": 0.001, "ml": 1e-6, "milliliter": 1e-6, "millilitre": 1e-6, "cm3": 1e-6}.get(unit)
        if value is not None and factor is not None:
            return value * factor
    return None


def _density_kg_m3(variables: list[dict]) -> float | None:
    for item in variables:
        if not re.search(r"(?:fluid|solution|liquid)?[_ -]?density", str(item.get("name", "")), re.I):
            continue
        value = _positive_number(item.get("value")); unit = _normal_unit(item.get("unit"))
        factor = {"kg/m3": 1.0, "g/cm3": 1000.0, "g/ml": 1000.0, "kg/l": 1000.0}.get(unit)
        if value is not None and factor is not None:
            return value * factor
    return None


def _dynamic_viscosity_pa_s(variables: list[dict]) -> float | None:
    for item in variables:
        if not re.search(r"(?:fluid|solution|liquid)?[_ -]?viscosity", str(item.get("name", "")), re.I):
            continue
        value = _positive_number(item.get("value")); unit = _normal_unit(item.get("unit"))
        factor = {"pa*s": 1.0, "pas": 1.0, "mpa*s": 0.001, "mpas": 0.001, "cp": 0.001}.get(unit)
        if value is not None and factor is not None:
            return value * factor
    return None


def plan_simple_rushton_case(record: dict) -> dict:
    variables = [variable for step in record.get("steps", []) for variable in step.get("variables", [])]
    vessel_text = " ".join(str(item.get("value", "")) for item in variables if re.search(r"vessel|tank|geometry", str(item.get("name", "")), re.I))
    impeller_text = " ".join(str(item.get("value", "")) for item in variables if re.search(r"impeller|agitator|blade|stirrer|stir[_ -]?bar|magnetic", str(item.get("name", "")), re.I))
    vessel_diameter = _length_variable(variables, r"(?:vessel|tank)[_ -]?(?:inner[_ -]?)?diameter") or _geometry_length(vessel_text, "diameter")
    vessel_height = _length_variable(variables, r"(?:vessel|tank)[_ -]?(?:liquid[_ -]?)?height") or _geometry_length(vessel_text, "height")
    impeller_diameter = _length_variable(variables, r"(?:rushton[_ -]?)?impeller[_ -]?diameter") or _geometry_length(impeller_text, "diameter")
    states_open_surface = bool(re.search(r"open\s*(?:tank|vessel|surface)|free\s*surface|open\s*surface|개방\s*(?:용기|액면)", vessel_text, re.I))

    stirring_speed = None
    for item in variables:
        if not re.search(r"rpm|stirring[_ -]?(?:speed|rate)|mixing[_ -]?speed|rotation[_ -]?rate", str(item.get("name", "")), re.I):
            continue
        raw = _positive_number(item.get("value")); unit = _normal_unit(item.get("unit"))
        if raw is None:
            continue
        if unit in {"rpm", "r/min"}:
            stirring_speed = raw
        elif unit in {"s-1", "1/s", "1/sec"}:
            stirring_speed = raw * 60.0
        elif unit == "rad/s":
            stirring_speed = raw * 60.0 / (2.0 * math.pi)
        if stirring_speed is not None:
            break

    density = _density_kg_m3(variables)
    dynamic_viscosity = _dynamic_viscosity_pa_s(variables)
    nu = dynamic_viscosity / density if dynamic_viscosity and density else None
    blade_match = re.search(r"\b(4|6)\s*[- ]?blade\b|\bblade\s*[:=]?\s*(4|6)\b|([46])\s*날", impeller_text, re.I)
    blades = int(next(group for group in blade_match.groups() if group)) if blade_match else None
    rushton = bool(re.search(r"rushton|러시턴", impeller_text, re.I))
    magnetic_bar = bool(re.search(r"magnetic[ _-]?(?:stir(?:ring)?[ _-]?)?bar|stir[ _-]?bar|magnetic[ _-]?stirrer|magnetic[ _-]?stirring|마그네틱[ _-]?바|자석[ _-]?교반봉|교반[ _-]?자석", impeller_text, re.I))
    baffled = bool(re.search(r"baffl|배플", vessel_text, re.I)) and not bool(re.search(r"unbaffl|without\s+baffl|배플\s*없", vessel_text, re.I))
    closed_full = bool(re.search(r"closed\s*(?:and\s*)?(?:fully\s*)?filled|fully\s*filled|sealed\s*and\s*filled|완전\s*충전|밀폐\s*충전", vessel_text, re.I))

    checks = [
        {"key": "cylindrical_tank_diameter", "present": vessel_diameter is not None, "value_si": vessel_diameter, "unit_si": "m"},
        {"key": "cylindrical_tank_height", "present": vessel_height is not None, "value_si": vessel_height, "unit_si": "m"},
        {"key": "rushton_impeller", "present": rushton, "value_si": "Rushton" if rushton else None, "unit_si": None},
        {"key": "impeller_diameter", "present": impeller_diameter is not None, "value_si": impeller_diameter, "unit_si": "m"},
        {"key": "blade_count", "present": blades in {4, 6}, "value_si": blades, "unit_si": "blades"},
        {"key": "baffles", "present": baffled, "value_si": "baffled" if baffled else None, "unit_si": None},
        {"key": "closed_fully_filled_vessel", "present": closed_full, "value_si": "closed and fully filled" if closed_full else None, "unit_si": None},
        {"key": "stirring_speed", "present": stirring_speed is not None, "value_si": stirring_speed, "unit_si": "rpm"},
        {"key": "fluid_density", "present": density is not None, "value_si": density, "unit_si": "kg/m3"},
        {"key": "kinematic_viscosity", "present": nu is not None and math.isfinite(nu), "value_si": nu, "unit_si": "m2/s"},
    ]
    volume = _volume_m3(variables)
    geometry_volume = math.pi * (vessel_diameter / 2) ** 2 * vessel_height if vessel_diameter and vessel_height else None
    volume_matches = bool(volume and geometry_volume and abs(volume - geometry_volume) / geometry_volume <= 0.05)
    checks.append({"key": "liquid_volume_matches_closed_tank", "present": volume_matches, "value_si": volume, "expected_si": geometry_volume, "unit_si": "m3"})
    ratio = impeller_diameter / vessel_diameter if impeller_diameter and vessel_diameter else None
    checks.append({"key": "impeller_to_tank_ratio", "present": ratio is not None and 0.2 <= ratio <= 0.4, "value_si": ratio, "expected_range": [0.2, 0.4], "unit_si": None})
    missing = [item["key"] for item in checks if not item["present"]]
    supported = rushton and (blades in {4, 6}) and baffled and closed_full
    explicitly_other_impeller = bool(re.search(r"pitched\s*blade|propeller|paddle|anchor|hydrofoil|marine\s*impeller|프로펠러|패들|앵커|하이드로포일", impeller_text, re.I))
    explicitly_unbaffled = bool(re.search(r"unbaffl|without\s+baffl|배플\s*없", vessel_text, re.I))
    explicitly_unsupported = magnetic_bar or (explicitly_other_impeller and not rushton) or explicitly_unbaffled or states_open_surface
    unsupported_reasons = ["This case does not model a magnetic stir bar in an open beaker; use a dedicated bar-stirring case."] if magnetic_bar else []
    return {
        "experiment_id": record.get("id"),
        "record_code": record.get("code"),
        "model_id": MODEL_ID,
        "engine_installed": None,
        "status": "unsupported_geometry" if explicitly_unsupported else "ready_for_review" if not missing and supported else "needs_input",
        "compatible": supported,
        "checks": checks,
        "missing": missing,
        "unsupported_reasons": unsupported_reasons,
        "limitations": LIMITATIONS + (["This case models a Rushton turbine, not a magnetic stir bar in a beaker."] if magnetic_bar else []),
    }
