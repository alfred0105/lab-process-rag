"""Deterministic checks for whether saved process records contain simulator inputs."""
from __future__ import annotations

import math
import re


SUPPORTED_TOTALS = {
    "Al", "B", "Ba", "Br", "C(4)", "Ca", "Cd", "Cl", "Cu", "F", "Fe(2)",
    "Fe(3)", "K", "Li", "Mg", "Mn", "Na", "N(5)", "P", "Pb", "S(6)", "Si", "Sr", "Zn",
}


def _flatten(record: dict) -> list[dict]:
    return [
        {**variable, "step_name": step.get("name", "")}
        for step in record.get("steps", [])
        for variable in step.get("variables", [])
    ]


def _value_is_numeric(item: dict) -> bool:
    try:
        value = float(str(item.get("value", "")).strip().replace(",", "."))
        return math.isfinite(value)
    except (TypeError, ValueError):
        return False


def _present(items: list[dict], pattern: str, *, numeric: bool = True, unit: bool = False) -> list[dict]:
    regex = re.compile(pattern, re.I)
    matches = [item for item in items if regex.search(str(item.get("name", "")))]
    return [item for item in matches if (not numeric or _value_is_numeric(item)) and (not unit or bool(str(item.get("unit") or "").strip()))]


def _unit_key(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("·", "*").replace("³", "3").replace("²", "2").replace("⁻", "-").replace("¹", "1").replace("−", "-")


def _has_length(text: str) -> bool:
    return bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:mm|cm|m|in|inch|inches)\b", text, re.I))


def _geometry_is_descriptive(item: dict, kind: str) -> bool:
    text = str(item.get("value", "")).strip().lower()
    if not _has_length(text):
        return False
    if kind == "vessel_geometry":
        diameter = bool(re.search(r"diam(?:eter)?|inner\s*dia|지름|직경", text))
        height = bool(re.search(r"height|높이|깊이", text))
        return diameter and height
    diameter = bool(re.search(r"diam(?:eter)?|지름|직경", text))
    impeller_type = bool(re.search(r"impeller|propeller|paddle|turbine|anchor|blade|프로펠러|패들|터빈|앵커|날개", text))
    return diameter and impeller_type


def _has_supported_unit(item: dict, key: str) -> bool:
    unit = _unit_key(item.get("unit"))
    allowed = {
        "liquid_volume": {"l", "liter", "litre", "ml", "milliliter", "millilitre", "cm3", "m3"},
        "stirring_speed": {"rpm", "r/min", "s-1", "1/s", "1/sec", "rad/s"},
        "fluid_density": {"kg/m3", "g/cm3", "g/ml", "kg/l"},
        "fluid_viscosity": {"pa*s", "pas", "mpa*s", "mpas", "cp"},
    }
    return unit in allowed.get(key, set())


def assess_simulation_inputs(record: dict) -> dict:
    """Report saved evidence and gaps without inferring or inserting values.

    OpenFOAM checks are explicitly conditional: a user may not be modelling a
    mechanically stirred vessel at all. PHREEQC checks describe only the
    current aqueous-equilibrium endpoint's minimum supported inputs.
    """
    values = _flatten(record)
    ph = _present(values, r"^(?:pH|solution[_ -]?pH|initial[_ -]?pH)$")
    temperature = _present(values, r"^(?:temperature(?:_c)?|reaction[_ -]?temperature(?:_c)?|growth[_ -]?temperature(?:_c)?|synthesis[_ -]?temperature(?:_c)?|hydrothermal[_ -]?temperature(?:_c)?|annealing[_ -]?temperature(?:_c)?)$")
    total_matches = []
    for item in values:
        name = str(item.get("name", "")).strip()
        match = re.fullmatch(r"(Al|B|Ba|Br|C\(4\)|Ca|Cd|Cl|Cu|F|Fe\(2\)|Fe\(3\)|K|Li|Mg|Mn|Na|N\(5\)|P|Pb|S\(6\)|Si|Sr|Zn)(?:[_ -]?(?:concentration|total))?", name, re.I)
        unit = str(item.get("unit") or "").strip().lower()
        supported_unit = unit in {"mol/kgw", "mol/kg water", "mol/kg", "m", "mol/l", "mol/liter", "mm", "mmol/l", "mmol/kgw", "mmol/kg"}
        if match and _value_is_numeric(item) and supported_unit:
            total_matches.append(item)

    phreeqc_checks = [
        {"key": "pH", "present": bool(ph), "required": True, "value": ph[0].get("value") if ph else None, "unit": ph[0].get("unit") if ph else None},
        {"key": "temperature", "present": bool(temperature), "required": True, "value": temperature[0].get("value") if temperature else None, "unit": temperature[0].get("unit") if temperature else None},
        {"key": "dissolved_total", "present": bool(total_matches), "required": True, "value": ", ".join(str(item.get("name")) for item in total_matches) if total_matches else None, "unit": "mol/kgw or supported molar unit" if total_matches else None},
    ]

    openfoam_definitions = [
        ("liquid_volume", r"(?:liquid|solution|working|batch)[_ -]?(?:volume|amount)|(?:liquid|solution)[_ -]?volume"),
        ("vessel_geometry", r"vessel|tank|reactor[_ -]?(?:diameter|height|geometry)|geometry"),
        ("impeller_geometry", r"impeller|blade|baffle|agitator[_ -]?(?:type|diameter|geometry)"),
        ("stirring_speed", r"rpm|stirring[_ -]?(?:speed|rate)|mixing[_ -]?speed|rotation[_ -]?rate"),
        ("fluid_density", r"(?:fluid|solution|liquid)[_ -]?density|density"),
        ("fluid_viscosity", r"(?:fluid|solution|liquid)[_ -]?viscosity|viscosity"),
    ]
    openfoam_checks = []
    for key, pattern in openfoam_definitions:
        matches = [item for item in values if re.search(pattern, str(item.get("name", "")), re.I)]
        if key in {"vessel_geometry", "impeller_geometry"}:
            found = [item for item in matches if _geometry_is_descriptive(item, key)]
        else:
            found = [item for item in matches if _value_is_numeric(item) and _has_supported_unit(item, key)]
        recorded = found[0] if found else matches[0] if matches else None
        openfoam_checks.append({
            "key": key,
            "present": bool(found),
            "required": True,
            "value": found[0].get("value") if found else None,
            "unit": found[0].get("unit") if found else None,
            "recorded_value": recorded.get("value") if recorded and not found else None,
            "recorded_unit": recorded.get("unit") if recorded and not found else None,
            "reason": "recorded_but_not_usable" if recorded and not found else "missing" if not found else None,
        })

    materials = record.get("materials", [])
    material_checks = [
        {"key": "material_identity", "present": bool(materials), "required": True, "value": ", ".join(str(item.get("name", "")).strip() for item in materials if str(item.get("name", "")).strip()) or None, "unit": None},
        {"key": "material_amounts", "present": bool(materials) and all(str(item.get("amount", "")).strip() and str(item.get("unit", "")).strip() for item in materials), "required": False, "value": None, "unit": None},
        {"key": "lot_and_supplier", "present": bool(materials) and all(str(item.get("lot_number", "")).strip() and str(item.get("supplier", "")).strip() for item in materials), "required": False, "value": None, "unit": None},
    ]
    return {
        "experiment_id": record["id"],
        "record_code": record["code"],
        "groups": [
            {"key": "phreeqc", "conditional": True, "checks": phreeqc_checks},
            {"key": "openfoam_mixer", "conditional": True, "checks": openfoam_checks},
            {"key": "materials", "conditional": False, "checks": material_checks},
        ],
        "limitations": [
            "Missing values are reported from the saved process record only; no values are estimated or inserted.",
            "OpenFOAM mixer checks apply only if the selected process is meant to model a mechanically stirred liquid vessel.",
            "Purity, stock concentration, hydration state, and fluid properties cannot be inferred from a generic chemical identity record.",
        ],
    }
