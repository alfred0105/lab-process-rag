"""Local PHREEQC aqueous speciation and mineral saturation calculations.

This adapter reports equilibrium/speciation calculations only. It does not
predict nucleation, particle size, synthesis yield, or reaction kinetics.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

ELEMENT_TOTALS = {
    "Al", "B", "Ba", "Br", "C(4)", "Ca", "Cd", "Cl", "Cu", "F",
    "Fe(2)", "Fe(3)", "K", "Li", "Mg", "Mn", "Na", "N(5)", "P",
    "Pb", "S(6)", "Si", "Sr", "Zn",
}
PHASES = {
    "Calcite", "Aragonite", "Dolomite", "Smithsonite", "Zincite",
    "Witherite", "Strontianite", "Gypsum", "Anhydrite", "Quartz",
    "Chalcedony", "Gibbsite", "Goethite", "Hematite", "Fluorite", "Zn(OH)2(e)", "Willemite",
}
PHASE_ELEMENTS = {
    "Calcite": {"Ca", "C(4)"}, "Aragonite": {"Ca", "C(4)"}, "Dolomite": {"Ca", "Mg", "C(4)"},
    "Smithsonite": {"Zn", "C(4)"}, "Zn(OH)2(e)": {"Zn"}, "Zincite": {"Zn"},
    "Witherite": {"Ba", "C(4)"}, "Strontianite": {"Sr", "C(4)"},
    "Gypsum": {"Ca", "S(6)"}, "Anhydrite": {"Ca", "S(6)"},
    "Quartz": {"Si"}, "Chalcedony": {"Si"}, "Gibbsite": {"Al"},
    "Goethite": {"Fe(2)", "Fe(3)"}, "Hematite": {"Fe(2)", "Fe(3)"},
    "Fluorite": {"Ca", "F"}, "Willemite": {"Zn", "Si"},
}


def calculate_aqueous_equilibrium(
    *, temperature_c: float, pH: float, totals_molal: dict[str, float], phases: list[str]
) -> dict[str, Any]:
    """Run PHREEQC on this process and return species and saturation indices."""
    if not -2 <= pH <= 16:
        raise ValueError("pH must be between -2 and 16.")
    if not -20 <= temperature_c <= 150:
        raise ValueError("Temperature must be between -20 and 150 °C.")
    if not totals_molal:
        raise ValueError("Enter at least one dissolved element total.")
    unknown = sorted(set(totals_molal) - ELEMENT_TOTALS)
    if unknown:
        raise ValueError(f"Unsupported element total: {', '.join(unknown)}")
    for name, value in totals_molal.items():
        if not isfinite(value) or value < 0 or value > 100:
            raise ValueError(f"{name} must be a finite concentration from 0 to 100 mol/kg water.")
    if not any(value > 0 for value in totals_molal.values()):
        raise ValueError("At least one dissolved analytical total must be greater than zero.")
    if len(phases) > 15:
        raise ValueError("Select no more than 15 mineral phases.")
    invalid_phases = sorted(set(phases) - PHASES)
    if invalid_phases:
        raise ValueError(f"Unsupported mineral phase: {', '.join(invalid_phases)}")

    try:
        from phreeqpython import PhreeqPython
    except ImportError as exc:  # pragma: no cover - installation-specific
        raise RuntimeError("PHREEQC is not installed in this backend environment.") from exc

    model = PhreeqPython(database="phreeqc.dat")
    solution_input: dict[str, Any] = {
        "units": "mol/kgw",
        "pH": pH,
        "temp": temperature_c,
        **{key: value for key, value in totals_molal.items() if value > 0},
    }
    solution = model.add_solution(solution_input)
    aqueous_species = [
        {"name": name, "molality": value}
        for name, value in sorted(solution.species.items(), key=lambda item: item[1], reverse=True)
        if name not in {"H2O", "H+", "OH-"} and value > 1e-12
    ][:30]
    saturation = []
    for phase in phases:
        index = float(solution.si(phase))
        saturation.append({
            "phase": phase,
            "saturation_index": index if isfinite(index) and index > -900 else None,
            "interpretation": (
                "supersaturated" if index > 0 else "undersaturated" if index < 0 else "near_equilibrium"
            ) if isfinite(index) and index > -900 else "not_available_in_database",
        })
    return {
        "model_id": "PHREEQC-3 / phreeqc.dat",
        "engine": "phreeqpython 1.6.2",
        "temperature_c": temperature_c,
        "input_pH": pH,
        "calculated_pH": float(solution.pH),
        "input_totals_molal": totals_molal,
        "aqueous_species": aqueous_species,
        "saturation_indices": saturation,
        "status": "EQUILIBRIUM_ESTIMATE",
        "limitations": [
            "This is a thermodynamic aqueous-equilibrium/speciation calculation using the PHREEQC phreeqc.dat database.",
            "Positive saturation index indicates thermodynamic supersaturation only; it does not prove precipitation or predict nucleation, particle size, morphology, yield, or reaction rate.",
            "The entered pH is held fixed and charge balance is not imposed. Enter analytically consistent, approximately electroneutral solution totals.",
            "Activities, redox conditions, complexation, solid phases, and database coverage affect the result. Verify input totals, units, and database suitability for the chemistry.",
        ],
    }


def sweep_aqueous_equilibrium(
    *, temperature_c: float, pH_min: float, pH_max: float, points: int,
    totals_molal: dict[str, float], phases: list[str]
) -> dict[str, Any]:
    """Evaluate selected mineral saturation indices over a pH range."""
    if not -2 <= pH_min < pH_max <= 16:
        raise ValueError("pH sweep must increase within -2 to 16.")
    if not 3 <= points <= 31:
        raise ValueError("pH sweep must use between 3 and 31 points.")
    rows = []
    for index in range(points):
        current_pH = pH_min + (pH_max - pH_min) * index / (points - 1)
        result = calculate_aqueous_equilibrium(
            temperature_c=temperature_c, pH=current_pH,
            totals_molal=totals_molal, phases=phases,
        )
        rows.append({"pH": current_pH, "saturation_indices": result["saturation_indices"]})
    return {
        "model_id": "PHREEQC-3 / phreeqc.dat",
        "temperature_c": temperature_c,
        "pH_min": pH_min,
        "pH_max": pH_max,
        "points": rows,
        "status": "EQUILIBRIUM_SWEEP_ESTIMATE",
        "limitations": [
            "This is an equilibrium pH sweep at fixed analytical totals, not an experimental titration curve; adding acid/base would also change solution totals and counterions.",
            "Saturation index is a thermodynamic indicator, not proof of precipitation, nucleation, particle growth, or yield.",
            "The entered pH is varied at fixed analytical totals; no acid/base titrant or counterion is added and charge balance is not imposed.",
        ],
    }


def simulate_stirred_reaction_path(
    *, temperature_c: float, pH: float, totals_molal: dict[str, float],
    titrant: str, total_titrant_mmol: float, duration_min: float,
    points: int, tracked_element: str, equilibrium_phase: str | None,
) -> dict[str, Any]:
    """Model a staged titrant addition as ideal mixing plus equilibrium at each step."""
    from phreeqpython import PhreeqPython

    if titrant not in {"HCl", "NaOH"}:
        raise ValueError("Only HCl or NaOH stoichiometric additions are supported.")
    if not -2 <= pH <= 16 or not -20 <= temperature_c <= 150:
        raise ValueError("Starting pH or temperature is outside the supported model range.")
    if not 3 <= points <= 31:
        raise ValueError("Use between 3 and 31 time points.")
    if not isfinite(total_titrant_mmol) or not 0 < total_titrant_mmol <= 10000:
        raise ValueError("Total titrant must be greater than 0 and no more than 10000 mmol per kg water.")
    if not isfinite(duration_min) or not 0 < duration_min <= 10000:
        raise ValueError("Addition duration must be greater than 0 and no more than 10000 minutes.")
    if tracked_element not in ELEMENT_TOTALS or totals_molal.get(tracked_element, 0) <= 0:
        raise ValueError("Choose a tracked element with a positive initial analytical total.")
    invalid = sorted(set(totals_molal) - ELEMENT_TOTALS)
    if invalid:
        raise ValueError(f"Unsupported element total: {', '.join(invalid)}")
    if not any(isfinite(value) and 0 < value <= 100 for value in totals_molal.values()):
        raise ValueError("Enter at least one positive analytical total up to 100 mol/kg water.")
    if equilibrium_phase is not None and equilibrium_phase not in PHASES:
        raise ValueError("Selected equilibrium phase is not supported.")
    if equilibrium_phase and tracked_element not in PHASE_ELEMENTS.get(equilibrium_phase, set()):
        raise ValueError(f"{equilibrium_phase} does not contain tracked element {tracked_element}.")

    engine = PhreeqPython(database="phreeqc.dat")
    initial_tracked_mmol = totals_molal[tracked_element] * 1000.0
    rows = []
    for index in range(points):
        fraction = index / (points - 1)
        added = total_titrant_mmol * fraction
        solution = engine.add_solution({
            "units": "mol/kgw", "pH": pH, "temp": temperature_c,
            **{key: value for key, value in totals_molal.items() if value > 0},
        })
        if added > 0:
            solution.add(titrant, added, "mmol")
        saturation_before = float(solution.si(equilibrium_phase)) if equilibrium_phase else None
        dissolved_before = float(solution.total_element(tracked_element, "mmol"))
        phase_available = saturation_before is not None and isfinite(saturation_before) and saturation_before > -900
        if equilibrium_phase and not phase_available:
            raise ValueError(f"{equilibrium_phase} is not present in the selected PHREEQC database.")
        if equilibrium_phase and saturation_before is not None and saturation_before > 0:
            # Zero starting moles allows precipitation but not dissolution in this
            # independently equilibrated dose step; this is a maximum-equilibrium scenario.
            solution.equalize([equilibrium_phase], [0], [0])
        dissolved_after = float(solution.total_element(tracked_element, "mmol"))
        saturation_after = float(solution.si(equilibrium_phase)) if equilibrium_phase else None
        precipitated = max(0.0, initial_tracked_mmol - dissolved_after) if equilibrium_phase else 0.0
        rows.append({
            "time_min": duration_min * fraction,
            "added_titrant_mmol": added,
            "pH": float(solution.pH),
            "dissolved_element_mmol_per_kgw": dissolved_after,
            "precipitated_element_mmol_per_kgw_equilibrium": precipitated,
            "saturation_index_before_precipitation": saturation_before if phase_available else None,
            "saturation_index_after_equilibrium": saturation_after if saturation_after is not None and saturation_after > -900 else None,
        })
    return {
        "model_id": "PHREEQC-3 / phreeqc.dat",
        "titrant": titrant, "tracked_element": tracked_element,
        "equilibrium_phase": equilibrium_phase, "temperature_c": temperature_c,
        "starting_pH": pH, "total_titrant_mmol": total_titrant_mmol,
        "duration_min": duration_min, "mixing_assumption": "instantaneous homogeneous bulk mixing at each dose step",
        "points": rows, "status": "STIRRED_BATCH_EQUILIBRIUM_ESTIMATE",
        "limitations": [
            "Stirring is represented as ideal homogeneous bulk mixing; RPM, impeller geometry, shear, mass transfer, and local concentration gradients are not solved.",
            "Titrant is added as stoichiometric pure HCl or NaOH in mmol/kg water; carrier-water volume and dilution are ignored.",
            "Each point is an equilibrium calculation at cumulative dose, not a time-resolved kinetic model. Reaction rates, induction time, nucleation, particle size, morphology, and yield are not predicted.",
            "When an equilibrium phase is selected, precipitated amount is a maximum-equilibrium element balance for that database phase; real experiments may remain supersaturated or form other solids.",
            "Input pH is fixed only for the starting solution; charge balance is not imposed. Verify initial solution totals and database suitability.",
        ],
    }
