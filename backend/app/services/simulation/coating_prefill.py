"""Validate Gemma's semantic bindings and calculate safe coating prefill values."""
from __future__ import annotations

import math
import re
from typing import Any

from app.services.simulation.film_postprocess import SOLVENTS
from app.services.simulation.solution_properties import estimate_solvent_matrix_properties

_ALLOWED = {
    "substrate_length_mm", "substrate_width_mm", "dispensed_volume_ml", "density_kg_m3",
    "dynamic_viscosity_pa_s", "nonvolatile_volume_fraction", "coating_cycles", "spin_rpm",
    "spin_duration_s", "drying_temperature_c", "drying_duration_s", "drying_mass_transfer_m_s",
    "solid_molar_volume_m3_mol",
}
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_MATERIAL = re.compile(r"^materials\[(\d+)\]\.(amount|unit)$")
_PATH_RESULT = re.compile(r"^results\[(\d+)\]\.(value|unit)$")
_PATH_VARIABLE = re.compile(r"^steps\[(\d+)\]\.variables\[(\d+)\]\.(value|unit)$")

# Field-level routing: only values with a defensible producer are eligible for
# automatic handoff. A theoretical estimate is never silently treated as a
# measured property.
_INPUT_DEPENDENCIES = {
    "substrate_length_mm": ("measurement_required", None, "기판 길이를 직접 측정해야 합니다. 현재 기판 치수를 예측하는 모델은 없습니다."),
    "substrate_width_mm": ("measurement_required", None, "기판 폭을 직접 측정해야 합니다. 현재 기판 치수를 예측하는 모델은 없습니다."),
    "density_kg_m3": ("measurement_required", None, "혼합 용액 밀도 측정값이 필요합니다. 성분별 정보만으로 실제 전구체 용액 밀도를 확정하는 모델은 연결되지 않았습니다."),
    "dynamic_viscosity_pa_s": ("measurement_required", None, "혼합 용액 점도 측정값이 필요합니다. 실제 조성의 점도를 신뢰성 있게 예측하는 모델은 연결되지 않았습니다."),
    "nonvolatile_volume_fraction": ("model_candidate_not_substitutable", "stoichiometric_material_balance", "조성으로 이론적 산화물 수율은 계산할 수 있지만 실제 비휘발 부피분율과 같다고 볼 수 없어 자동 대체하지 않습니다."),
    "spin_program": ("process_record_required", "gemma_record_mapper", "저장된 공정 기록에서 RPM과 시간을 찾지 못했습니다. 단계별 회전수와 시간을 기록해야 합니다."),
    "drying_temperature_c": ("process_record_required", "gemma_record_mapper", "건조 온도를 공정 기록에서 찾지 못했습니다."),
    "drying_duration_s": ("process_record_required", "gemma_record_mapper", "건조 시간을 공정 기록에서 찾지 못했습니다."),
    "drying_mass_transfer_m_s": ("measurement_required", None, "건조기 기류·습도·기판 조건에 맞는 물질전달계수가 필요합니다. 자동 추정 모델은 아직 연결되지 않았습니다."),
    "solid_molar_volume_m3_mol": ("material_property_required", "material_property_lookup", "건조 후 고체상과 밀도가 확인되어야 몰부피를 계산할 수 있습니다."),
    "solvent_id": ("process_record_required", "gemma_record_mapper", "용매 종류와 양을 공정 기록에서 확인할 수 없습니다."),
}


def _dependency_plan(missing: list[dict]) -> list[dict]:
    plan = []
    for item in missing:
        field = item.get("field", "")
        status, model_id, action = _INPUT_DEPENDENCIES.get(
            field,
            ("measurement_required", None, "현재 기록에서 값을 찾지 못했고 이를 계산할 수 있는 연결 모델도 없습니다."),
        )
        plan.append({"field": field, "status": status, "model_id": model_id,
                     "auto_run": False, "action": action})
    return plan


def _number(value: Any) -> float | None:
    match = _NUMBER.search(str(value or ""))
    if not match:
        return None
    parsed = float(match.group())
    return parsed if math.isfinite(parsed) else None


def _source(record: dict, path: str) -> tuple[float, str, int | None] | None:
    if found := _PATH_MATERIAL.fullmatch(path):
        item = record.get("materials", [])[int(found.group(1))]
        raw = item.get("amount") if found.group(2) == "amount" else item.get("unit")
        unit = item.get("unit") or ""
        value = _number(raw)
        return (value, unit, None) if value is not None else None
    if found := _PATH_RESULT.fullmatch(path):
        item = record.get("results", [])[int(found.group(1))]
        raw = item.get("value") if found.group(2) == "value" else item.get("unit")
        value = _number(raw)
        return (value, item.get("unit") or "", None) if value is not None else None
    if found := _PATH_VARIABLE.fullmatch(path):
        si, vi, field = int(found.group(1)), int(found.group(2)), found.group(3)
        step = record.get("steps", [])[si]
        variable = step.get("variables", [])[vi]
        raw = variable.get("value") if field == "value" else variable.get("unit")
        value = _number(raw)
        return (value, variable.get("unit") or "", si) if value is not None else None
    return None


def _normalize(target: str, value: float, unit: str) -> float | None:
    u = unit.lower().replace("μ", "u").replace("µ", "u").replace("°", "")
    u = re.sub(r"[\s·*_]+", "", u)
    if target in {"substrate_length_mm", "substrate_width_mm"}:
        return value * 25.4 if u in {"in", "inch", "inches"} else value * 10 if u in {"cm", "centimeter", "centimeters"} else value if u in {"mm", "millimeter", "millimeters"} else None
    if target == "dispensed_volume_ml":
        return value / 1000 if u in {"ul", "microliter", "microliters"} else value if u in {"ml", "milliliter", "milliliters"} else value * 1000 if u in {"l", "liter", "liters"} else None
    if target == "density_kg_m3":
        return value * 1000 if u in {"g/cm3", "gcm-3", "g/ml"} else value if u in {"kg/m3", "kgm-3"} else None
    if target == "dynamic_viscosity_pa_s":
        return value / 1000 if u in {"mpas", "cp", "millipascalsecond"} else value if u in {"pas", "pascalsecond"} else None
    if target == "nonvolatile_volume_fraction":
        return value / 100 if u in {"%", "percent", "vol%", "volpercent"} else value if u in {"", "fraction", "volfraction", "0-1"} else None
    if target in {"spin_rpm", "coating_cycles"}:
        return value if u in {"", "rpm", "cycle", "cycles", "times", "x"} else None
    if target in {"spin_duration_s", "drying_duration_s"}:
        return value * 60 if u in {"min", "minute", "minutes"} else value if u in {"s", "sec", "second", "seconds"} else None
    if target == "drying_temperature_c":
        return value - 273.15 if u in {"k", "kelvin"} else value if u in {"c", "celsius", "degc", ""} else None
    if target == "drying_mass_transfer_m_s":
        return value if u in {"m/s", "ms-1"} else None
    if target == "solid_molar_volume_m3_mol":
        return value if u in {"m3/mol", "m3mol-1"} else None
    return None


def _known_zno_chemistry(record: dict) -> dict | None:
    zinc = ethanol_ml = mea_ml = None
    zinc_source = ethanol_source = mea_source = None
    for index, item in enumerate(record.get("materials", [])):
        name = str(item.get("name", "")).lower().replace("₂", "2").replace("·", " ")
        amount = _number(item.get("amount")); unit = (item.get("unit") or "").lower().replace("μ", "u").replace("µ", "u").strip()
        if amount is None: continue
        if "zinc acetate" in name and ("dihydrate" in name or "2h2o" in name or "2 h2o" in name):
            zinc = amount / 1000 if unit == "mg" else amount if unit == "g" else None
            zinc_source = f"materials[{index}]"
        elif "ethanol" in name:
            ethanol_ml = amount / 1000 if unit in {"ul", "uL".lower()} else amount if unit == "ml" else amount * 1000 if unit == "l" else None
            ethanol_source = f"materials[{index}]"
        elif name.strip() in {"mea", "monoethanolamine", "mono ethanolamine", "2-aminoethanol"}:
            mea_ml = amount / 1000 if unit == "ul" else amount if unit == "ml" else None
            mea_source = f"materials[{index}]"
    if zinc is None or ethanol_ml is None or mea_ml is None or ethanol_ml <= 0:
        return None
    zinc_mmol = zinc / 219.50 * 1000
    mea_mmol = mea_ml * 1.012 / 61.083 * 1000
    zno_g = zinc_mmol / 1000 * 81.38
    nominal_volume_l = (ethanol_ml + mea_ml) / 1000
    return {
        "status": "DETERMINISTIC_STOICHIOMETRY_ESTIMATE",
        "zinc_amount_mmol": zinc_mmol,
        "nominal_zinc_concentration_mol_l": zinc_mmol / 1000 / nominal_volume_l,
        "mea_amount_mmol": mea_mmol,
        "mea_to_zinc_molar_ratio": mea_mmol / zinc_mmol,
        "theoretical_zno_mass_g_full_batch": zno_g,
        "theoretical_zno_mass_mg_per_50ul_aliquot": zno_g * (0.05 / (ethanol_ml + mea_ml)) * 1000,
        "sources": [zinc_source, ethanol_source, mea_source],
        "assumptions": ["Treats the zinc reagent as zinc acetate dihydrate (219.50 g/mol), MEA density as 1.012 g/mL and molar mass as 61.083 g/mol, and assumes one mole of zinc can yield one mole of ZnO (81.38 g/mol).", "Nominal concentration uses ethanol plus MEA volumes as additive; it is not a measured final solution volume or film yield."],
    }


def make_gemma_mapping_record(record: dict) -> dict:
    return {
        "experiment": {"id": record.get("id"), "code": record.get("code"), "name": record.get("name"), "target": record.get("target")},
        "materials": [{"index": i, "name": x.get("name"), "amount": x.get("amount"), "unit": x.get("unit"), "role": x.get("role")} for i, x in enumerate(record.get("materials", []))],
        "steps": [{"index": si, "name": step.get("name"), "variables": [{"index": vi, "name": v.get("name"), "value": v.get("value"), "unit": v.get("unit")} for vi, v in enumerate(step.get("variables", []))]} for si, step in enumerate(record.get("steps", []))],
        "results": [{"index": i, "key": x.get("key"), "value": x.get("value"), "unit": x.get("unit")} for i, x in enumerate(record.get("results", []))],
    }


def apply_gemma_coating_map(record: dict, mapping: dict, coating_cycles: int = 5) -> dict:
    inputs: dict[str, Any] = {key: None for key in _ALLOWED if key not in {"spin_rpm", "spin_duration_s"}}
    inputs["coating_cycles"] = int(coating_cycles)
    provenance = {"coating_cycles": {"source": "user_request", "value": int(coating_cycles)}}
    spin_steps: dict[tuple[int, int], dict[str, Any]] = {}
    mapped_paths: set[str] = set()
    rejected = []
    for binding in mapping.get("bindings", [])[:60]:
        target = binding.get("target")
        path = binding.get("source_path")
        if isinstance(path, str) and path.startswith("$."):
            path = path[2:]
        if target not in _ALLOWED or target in {"coating_cycles"} or not isinstance(path, str):
            rejected.append({"target": target, "reason": "unsupported_target_or_source"}); continue
        try:
            source = _source(record, path)
        except (IndexError, TypeError, KeyError):
            source = None
        if source is None:
            rejected.append({"target": target, "reason": "source_not_found"}); continue
        value, unit, step_index = source
        mapped_paths.add(path)
        normalized = _normalize(target, value, unit)
        if normalized is None or not math.isfinite(normalized):
            rejected.append({"target": target, "source_path": path, "reason": "unit_not_supported"}); continue
        if target in {"spin_rpm", "spin_duration_s"}:
            if step_index is None:
                rejected.append({"target": target, "source_path": path, "reason": "spin_stage_requires_step"}); continue
            variable_match = _PATH_VARIABLE.fullmatch(path)
            variable_index = int(variable_match.group(2)) if variable_match else 0
            variable = record["steps"][step_index].get("variables", [])[variable_index]
            stage_match = re.search(r"stage\s*(\d+)|(?:^|\s)(\d+)(?:st|nd|rd|th)?(?:\s|$)", str(variable.get("name", "")), re.I)
            if stage_match:
                stage_index = int(stage_match.group(1) or stage_match.group(2)) - 1
            else:
                name_pattern = r"rpm|spin.*speed|rotation.*speed|\brpm\b" if target == "spin_rpm" else r"spin.*(time|duration)|coat.*(time|duration)|stage.*(time|duration)|duration|\btime\b"
                candidates = [i for i, v in enumerate(record["steps"][step_index].get("variables", [])) if re.search(name_pattern, str(v.get("name", "")), re.I)]
                stage_index = candidates.index(variable_index) if variable_index in candidates else 0
            slot = (step_index, stage_index)
            spin_steps.setdefault(slot, {})[target] = normalized
            spin_steps[slot][target + "_source"] = path
        else:
            inputs[target] = normalized
            provenance[target] = {"source": path, "original_value": value, "unit": unit, "gemma_reason": str(binding.get("reason", ""))[:240]}
    # When saved variable labels clearly describe a spin program, recover any
    # omitted bindings by reading those exact source fields; no values are guessed.
    for si, step in enumerate(record.get("steps", [])):
        if not re.search(r"spin|coat|회전|코팅", str(step.get("name", "")), re.I):
            continue
        variables = step.get("variables", [])
        speeds = [vi for vi, var in enumerate(variables) if re.search(r"rpm|spin.*speed|rotation.*speed|회전.*속도", str(var.get("name", "")), re.I)]
        durations = [vi for vi, var in enumerate(variables) if re.search(r"spin.*(time|duration)|coat.*(time|duration)|stage.*(time|duration)|duration|\btime\b|회전.*시간|코팅.*시간", str(var.get("name", "")), re.I)]
        for stage_index, (speed_vi, duration_vi) in enumerate(zip(speeds, durations)):
            slot = (si, stage_index)
            stage = spin_steps.setdefault(slot, {})
            for target, vi in (("spin_rpm", speed_vi), ("spin_duration_s", duration_vi)):
                if target in stage: continue
                variable = variables[vi]
                value = _number(variable.get("value"))
                normalized = _normalize(target, value, variable.get("unit") or "") if value is not None else None
                if normalized is not None:
                    stage[target] = normalized
                    stage[target + "_source"] = f"steps[{si}].variables[{vi}].value"
                    mapped_paths.add(stage[target + "_source"])
    inputs["spin_program"] = []
    for (step_index, stage_index), stage in sorted(spin_steps.items()):
        if "spin_rpm" in stage and "spin_duration_s" in stage:
            inputs["spin_program"].append({"rpm": stage["spin_rpm"], "duration_s": stage["spin_duration_s"], "source_step_index": step_index, "stage_index": stage_index})
    # Accept solvent identities only when Gemma labels a saved material as a
    # solvent and its name maps to the local vetted solvent catalog.
    roles_by_index = {}
    for entry in mapping.get("material_roles", [])[:len(record.get("materials", []))]:
        try:
            idx = int(entry.get("material_index"))
            if 0 <= idx < len(record.get("materials", [])) and entry.get("role") in {"precursor", "solvent", "complexing_agent", "substrate", "other"}:
                roles_by_index[idx] = entry["role"]
        except (TypeError, ValueError, KeyError):
            continue
    solvent_amounts = []
    for idx, material in enumerate(record.get("materials", [])):
        name = str(material.get("name", "")).lower().replace(" ", "")
        role = roles_by_index.get(idx, str(material.get("role", "")).lower())
        solvent_key = next((key for key, spec in SOLVENTS.items() if key in name or spec["name"].lower().replace(" ", "") in name), None)
        if role != "solvent" or solvent_key is None:
            continue
        amount = _number(material.get("amount")); unit = (material.get("unit") or "").lower().replace("μ", "u").replace("µ", "u").strip()
        if amount is None: continue
        volume_ml = amount / 1000 if unit == "ul" else amount if unit == "ml" else amount * 1000 if unit == "l" else None
        if volume_ml is not None and volume_ml > 0:
            solvent_amounts.append((solvent_key, volume_ml, idx))
    solvent_total = sum(item[1] for item in solvent_amounts)
    inputs["solvents"] = [{"solvent_id": key, "volume_fraction": volume / solvent_total} for key, volume, _ in solvent_amounts] if solvent_total else []
    if len(inputs["solvents"]) == 1:
        inputs["solvent_id"] = inputs["solvents"][0]["solvent_id"]
        inputs["solvent_fraction"] = 1.0
    elif len(inputs["solvents"]) >= 2:
        inputs["solvent_id"] = inputs["solvents"][0]["solvent_id"]
        inputs["solvent_fraction"] = inputs["solvents"][0]["volume_fraction"]
        inputs["second_solvent_id"] = inputs["solvents"][1]["solvent_id"]
    property_estimate = None
    if inputs.get("density_kg_m3") is None or inputs.get("dynamic_viscosity_pa_s") is None:
        property_estimate = estimate_solvent_matrix_properties(record.get("materials", []))
        if property_estimate:
            for key in ("density_kg_m3", "dynamic_viscosity_pa_s"):
                if inputs.get(key) is None:
                    inputs[key] = property_estimate[key]
                    provenance[key] = {"source": "model_estimate", "model_id": property_estimate["model_id"], "status": property_estimate["status"], "temperature_c": property_estimate["temperature_c"]}
    missing = [item for item in list(mapping.get("missing_inputs", []))[:30]
               if not (item.get("field") in {"density_kg_m3", "dynamic_viscosity_pa_s"} and inputs.get(item.get("field")) is not None)]
    for target in ["substrate_length_mm", "substrate_width_mm", "dispensed_volume_ml", "density_kg_m3", "dynamic_viscosity_pa_s", "nonvolatile_volume_fraction", "drying_temperature_c", "drying_duration_s", "drying_mass_transfer_m_s", "solid_molar_volume_m3_mol"]:
        if inputs.get(target) is None and not any(item.get("field") == target for item in missing):
            missing.append({"field": target, "why_needed": "실험 기록에서 해당 값과 단위를 찾지 못했습니다."})
    if not inputs["spin_program"]:
        missing.append({"field": "spin_program", "why_needed": "RPM과 시간을 같은 단계에서 함께 확인할 수 있어야 회전막 계산을 실행할 수 있습니다."})
    else:
        for si, step in enumerate(record.get("steps", [])):
            if not re.search(r"spin|coat|회전|코팅", str(step.get("name", "")), re.I):
                continue
            variables = step.get("variables", [])
            speed_indices = [vi for vi, var in enumerate(variables) if re.search(r"rpm|spin.*speed|rotation.*speed|회전.*속도", str(var.get("name", "")), re.I)]
            duration_indices = [vi for vi, var in enumerate(variables) if re.search(r"spin.*(time|duration)|coat.*(time|duration)|stage.*(time|duration)|회전.*시간|코팅.*시간", str(var.get("name", "")), re.I)]
            mapped_speed = sum(f"steps[{si}].variables[{vi}].value" in mapped_paths for vi in speed_indices)
            mapped_duration = sum(f"steps[{si}].variables[{vi}].value" in mapped_paths for vi in duration_indices)
            if mapped_speed < len(speed_indices) or mapped_duration < len(duration_indices):
                missing.append({"field": "spin_program", "why_needed": f"{step.get('name')}에 기록된 모든 회전 속도·시간 구간을 연결하지 못했습니다."})
    if not inputs["solvents"]:
        missing.append({"field": "solvent_id", "why_needed": "저장 재료 중 용매 역할과 용매량을 확인할 수 없어 건조 모델의 용매 조성을 정하지 않았습니다."})
    spin_fields = {"substrate_length_mm", "substrate_width_mm", "dispensed_volume_ml", "density_kg_m3", "dynamic_viscosity_pa_s", "spin_program"}
    drying_fields = {"nonvolatile_volume_fraction", "solid_molar_volume_m3_mol", "drying_temperature_c", "drying_duration_s", "drying_mass_transfer_m_s", "solvent_id"}
    spin_missing = [item for item in missing if item.get("field") in spin_fields]
    drying_missing = [item for item in missing if item.get("field") in drying_fields]
    return {
        "model": "Gemma semantic mapping + deterministic unit conversion",
        "simulation_inputs": inputs,
        "provenance": provenance,
        "material_roles": mapping.get("material_roles", [])[:30],
        "missing_inputs": missing,
        "dependency_plan": _dependency_plan(missing),
        "property_estimate": property_estimate,
        "spin_missing_inputs": spin_missing,
        "drying_missing_inputs": drying_missing,
        "will_run_spin_simulation": not spin_missing,
        "will_run_drying_simulation": not drying_missing,
        "rejected_mappings": rejected[:30],
        "chemistry_estimate": _known_zno_chemistry(record),
        "notes": [str(x)[:300] for x in mapping.get("notes", [])[:10]],
        "will_run_simulation": not missing,
    }
