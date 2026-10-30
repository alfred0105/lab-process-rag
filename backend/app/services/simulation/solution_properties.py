"""Low-cost solvent-matrix property estimate for supported liquid ingredients.

Uses the open-source ``thermo`` package's pure-component correlations and
default liquid-mixture rules. Undissolved/ionic precursor solids are excluded;
the result is therefore a screening proxy, never a measured solution property.
"""
from __future__ import annotations

import math
import re
from typing import Any

from thermo import Chemical, Mixture

_AMOUNT = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_MW = {"ethanol": 46.06844, "monoethanolamine": 61.08308, "water": 18.01528, "zinc_acetate_dihydrate": 219.50}


def _number(value: object) -> float | None:
    match = _AMOUNT.search(str(value or ""))
    if not match:
        return None
    result = float(match.group())
    return result if math.isfinite(result) and result > 0 else None


def estimate_solvent_matrix_properties(materials: list[dict[str, Any]], temperature_c: float = 25.0) -> dict[str, Any] | None:
    """Estimate density and viscosity of ethanol/MEA/hydration-water matrix.

    Zinc acetate is deliberately excluded from the liquid mixture rule because
    the selected generic package does not model its ionic contribution in this
    nonaqueous precursor. Hydration water is included in the solvent matrix.
    """
    if not math.isfinite(temperature_c) or temperature_c <= -273.15:
        return None
    temp_k = temperature_c + 273.15
    amount_mol: dict[str, float] = {"ethanol": 0.0, "monoethanolamine": 0.0, "water": 0.0}
    zinc_mol = 0.0
    sources: list[str] = []
    omitted = []
    for item in materials:
        name = str(item.get("name", "")).lower().replace("₂", "2").replace("·", " ")
        amount = _number(item.get("amount"))
        unit = str(item.get("unit") or "").strip().lower().replace("μ", "u").replace("µ", "u")
        if amount is None:
            continue
        if "zinc acetate" in name and ("dihydrate" in name or "2h2o" in name or "2 h2o" in name):
            mass_g = amount / 1000 if unit == "mg" else amount if unit == "g" else None
            if mass_g is not None:
                zinc_mol = mass_g / _MW["zinc_acetate_dihydrate"]
                amount_mol["water"] += 2 * zinc_mol
                omitted.append({"material": item.get("name"), "reason": "아세테이트 염의 용액 내 이온·착물 효과는 이 혼합 규칙에 포함되지 않음"})
            continue
        key = "ethanol" if "ethanol" in name and "amine" not in name else "monoethanolamine" if name.strip() in {"mea", "monoethanolamine", "mono ethanolamine", "2-aminoethanol", "2-aminoethan-1-ol"} else "water" if name.strip() in {"water", "h2o", "distilled water", "deionized water", "deionised water"} else None
        if key is None:
            omitted.append({"material": item.get("name"), "reason": "혼합 물성 입력에 포함하지 않은 성분"})
            continue
        if unit in {"ml", "milliliter", "milliliters", "millilitre", "millilitres"}:
            volume_ml = amount
        elif unit in {"ul", "microliter", "microliters", "microlitre", "microlitres"}:
            volume_ml = amount / 1000
        elif unit in {"l", "liter", "litre", "liters", "litres"}:
            volume_ml = amount * 1000
        elif unit in {"g", "gram", "grams", "mg"}:
            mass_g = amount / 1000 if unit == "mg" else amount
            amount_mol[key] += mass_g / _MW[key]
            sources.append(str(item.get("name")))
            continue
        else:
            continue
        if key == "water":
            density_g_ml = 0.99705
        else:
            pure = Chemical(key, T=temp_k, P=101325)
            density_g_ml = float(pure.rhol) / 1000 if pure.rhol else 0
        if density_g_ml > 0:
            amount_mol[key] += volume_ml * density_g_ml / _MW[key]
            sources.append(str(item.get("name")))

    components = [(key, value) for key, value in amount_mol.items() if value > 0]
    if not components or amount_mol["ethanol"] <= 0:
        return None
    ids = [key for key, _ in components]
    total = sum(value for _, value in components)
    fractions = [value / total for _, value in components]
    mixture = Mixture(ids, T=temp_k, P=101325, zs=fractions)
    density = float(mixture.rhol) if mixture.rhol is not None else None
    viscosity = float(mixture.mul) if mixture.mul is not None else None
    if not density or not viscosity or not math.isfinite(density) or not math.isfinite(viscosity):
        return None
    return {
        "model_id": "thermo-solvent-matrix-mixture-v1",
        "status": "SCREENING_ESTIMATE_SOLUTE_EXCLUDED",
        "temperature_c": temperature_c,
        "density_kg_m3": density,
        "dynamic_viscosity_pa_s": viscosity,
        "components": [{"id": key, "mole_fraction": amount / total} for key, amount in components],
        "mixing_methods": {"density": mixture.VolumeLiquidMixture.method, "viscosity": mixture.ViscosityLiquidMixture.method},
        "included_materials": sources,
        "omitted_materials": omitted,
        "zinc_acetate_amount_mol": zinc_mol,
        "source": "thermo (ChEDL) pure-component correlations and default liquid-mixture rules; model is generic and not fitted to this zinc-acetate precursor.",
        "limitations": [
            "The estimate represents the ethanol/MEA/water solvent matrix; zinc acetate ions, complexation, dissolution-induced volume change, and sol-gel aging are not modeled.",
            "Default liquid mixture rules are screening estimates and have not been calibrated against a measured sample of this formulation.",
            "Use measured final-solution density and viscosity when available; retain this result as a model estimate, not a measurement.",
        ],
    }
