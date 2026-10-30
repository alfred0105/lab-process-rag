"""Ideal dilute-solution pH estimate for a documented set of acid/base stocks."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class AcidBaseSystem:
    kind: str
    pka: tuple[float, ...] = ()
    strong_charge: float = 0.0
    countercharge: float = 0.0


SYSTEMS: dict[str, AcidBaseSystem] = {
    "HCl": AcidBaseSystem("strong_acid", strong_charge=-1.0),
    "HNO3": AcidBaseSystem("strong_acid", strong_charge=-1.0),
    "H2SO4": AcidBaseSystem("sulfuric_acid", pka=(1.99,), strong_charge=-1.0),
    "NaOH": AcidBaseSystem("strong_base", strong_charge=1.0),
    "KOH": AcidBaseSystem("strong_base", strong_charge=1.0),
    "CH3COOH": AcidBaseSystem("polyprotic_acid", pka=(4.76,)),
    "H3PO4": AcidBaseSystem("polyprotic_acid", pka=(2.15, 7.20, 12.35)),
    "NH3": AcidBaseSystem("weak_base", pka=(9.25,)),
    "NaHCO3": AcidBaseSystem("salt_acid_family", pka=(6.35, 10.33), countercharge=1.0),
    "Na2CO3": AcidBaseSystem("salt_acid_family", pka=(6.35, 10.33), countercharge=2.0),
}
MOLAR_MASS_G_MOL = {
    "HCl": 36.4609, "HNO3": 63.0128, "H2SO4": 98.079,
    "NaOH": 39.997, "KOH": 56.1056, "CH3COOH": 60.052,
    "H3PO4": 97.994, "NH3": 17.031, "NaHCO3": 84.0066, "Na2CO3": 105.9888,
}


def _mean_negative_charge(pH: float, pka: tuple[float, ...]) -> float:
    hydrogen = 10.0 ** (-pH)
    weights = [1.0]
    product = 1.0
    for value in pka:
        product *= 10.0 ** (-value) / hydrogen
        weights.append(product)
    total = sum(weights)
    return sum(index * weight for index, weight in enumerate(weights)) / total


def _net_charge(pH: float, species: list[tuple[AcidBaseSystem, float]]) -> float:
    hydrogen = 10.0 ** (-pH)
    hydroxide = 1e-14 / hydrogen
    charge = hydrogen - hydroxide
    for system, concentration in species:
        if system.kind in {"strong_acid", "strong_base"}:
            charge += system.strong_charge * concentration
        elif system.kind == "sulfuric_acid":
            charge += system.strong_charge * concentration
            charge -= concentration * _mean_negative_charge(pH, system.pka)
        elif system.kind == "polyprotic_acid":
            charge -= concentration * _mean_negative_charge(pH, system.pka)
        elif system.kind == "weak_base":
            # B + H+ <-> BH+; pKa is for the conjugate acid.
            charge += concentration / (1.0 + 10.0 ** (pH - system.pka[0]))
        elif system.kind == "salt_acid_family":
            charge += concentration * (system.countercharge - _mean_negative_charge(pH, system.pka))
    return charge


def estimate_solution_ph(water_volume_ml: float, reagents: list[dict]) -> dict:
    """Estimate pH for ideal dilute mixtures at 25 C from known stock solutions.

    Each reagent has a supported ``species`` and exactly one dosing form:
    stock concentration (mol/L) + volume (mL), or amount (mmol).
    """
    if not math.isfinite(water_volume_ml) or water_volume_ml <= 0:
        raise ValueError("Initial water volume must be greater than zero.")
    if not reagents:
        raise ValueError("Add at least one supported acid/base reagent.")

    total_volume_ml = float(water_volume_ml)
    prepared: list[tuple[AcidBaseSystem, float, dict]] = []
    for index, reagent in enumerate(reagents, start=1):
        species_name = str(reagent.get("species", "")).strip()
        system = SYSTEMS.get(species_name)
        if system is None:
            raise ValueError(f"Reagent {index}: {species_name or 'unknown'} is not in the supported list.")
        has_amount = reagent.get("amount_mmol") is not None
        has_mass = reagent.get("mass_g") is not None
        stock_values_present = reagent.get("concentration_mol_l") is not None or reagent.get("volume_ml") is not None
        has_stock = reagent.get("concentration_mol_l") is not None and reagent.get("volume_ml") is not None
        if stock_values_present and not has_stock:
            raise ValueError(f"Reagent {index}: stock dosing requires both concentration and added volume.")
        if sum((has_amount, has_mass, has_stock)) != 1:
            raise ValueError(f"Reagent {index}: enter exactly one dose form: amount in mmol, pure reagent mass in g, or stock concentration and added volume.")
        if has_mass:
            mass_g = float(reagent["mass_g"])
            if not math.isfinite(mass_g) or mass_g < 0:
                raise ValueError(f"Reagent {index}: mass must be a non-negative finite value.")
            mmol = mass_g / MOLAR_MASS_G_MOL[species_name] * 1000.0
            dose_volume_ml = 0.0
        elif has_amount:
            mmol = float(reagent["amount_mmol"])
            if not math.isfinite(mmol) or mmol < 0:
                raise ValueError(f"Reagent {index}: amount must be a non-negative finite value.")
            dose_volume_ml = 0.0
        else:
            concentration = float(reagent["concentration_mol_l"])
            dose_volume_ml = float(reagent["volume_ml"])
            if not math.isfinite(concentration) or concentration < 0 or not math.isfinite(dose_volume_ml) or dose_volume_ml < 0:
                raise ValueError(f"Reagent {index}: stock concentration and added volume must be non-negative finite values.")
            mmol = concentration * dose_volume_ml
        total_volume_ml += dose_volume_ml
        prepared.append((system, mmol, {"species": species_name, "amount_mmol": mmol, "added_volume_ml": dose_volume_ml, **({"mass_g": float(reagent["mass_g"])} if has_mass else {})}))

    if total_volume_ml <= 0:
        raise ValueError("Total solution volume must be greater than zero.")
    species = [(system, mmol / total_volume_ml) for system, mmol, _ in prepared]
    low, high = -2.0, 16.0
    low_charge, high_charge = _net_charge(low, species), _net_charge(high, species)
    if low_charge * high_charge > 0:
        raise ValueError("The estimated pH is outside the supported calculation range (-2 to 16).")
    for _ in range(120):
        middle = (low + high) / 2.0
        if _net_charge(middle, species) > 0:
            low = middle
        else:
            high = middle
    pH = (low + high) / 2.0
    return {
        "estimated_ph": round(pH, 4),
        "model_id": "ideal_dilute_acid_base_v1",
        "status": "ESTIMATE_ONLY",
        "temperature_c": 25.0,
        "total_volume_ml": round(total_volume_ml, 6),
        "reagents": [entry for _, _, entry in prepared],
        "assumptions": [
            "Ideal dilute solution at 25 °C; activity-coefficient corrections are omitted.",
            "Only the listed acid/base species and their stated dissociation constants are modeled.",
            "Precipitation, metal-ion hydrolysis, complex formation, gas exchange, and reaction kinetics are not modeled.",
            "This is a calculated estimate, not an electrode measurement or an in-reactor hydrothermal pH.",
        ],
        "supported_species": sorted(SYSTEMS),
    }
