"""First-order spin-coating liquid-film thinning model (Emslie–Bonner–Peck)."""
from __future__ import annotations
import math


def estimate_spin_coated_film(*, substrate_length_mm: float, substrate_width_mm: float,
                              dispensed_volume_ml: float, density_kg_m3: float,
                              dynamic_viscosity_pa_s: float, nonvolatile_volume_fraction: float | None = None,
                              rpm: float | None = None, spin_time_s: float | None = None, coating_cycles: int = 1,
                              substrate_material: str | None = None,
                              coating_material: str | None = None,
                              source_experiment_id: int | None = None,
                              spin_program: list[dict] | None = None) -> dict:
    program = []
    if spin_program:
        if len(spin_program) > 12:
            raise ValueError("회전 단계는 최대 12개까지 입력할 수 있습니다.")
        for step in spin_program:
            step_rpm = float(step.get("rpm", 0)); step_time = float(step.get("duration_s", 0))
            if not math.isfinite(step_rpm) or not math.isfinite(step_time) or step_rpm <= 0 or step_time <= 0:
                raise ValueError("각 회전 단계의 RPM과 지속 시간은 0보다 커야 합니다.")
            program.append({"rpm": step_rpm, "duration_s": step_time})
        spin_time_s = sum(step["duration_s"] for step in program)
        rpm = math.sqrt(sum(step["rpm"] ** 2 * step["duration_s"] for step in program) / spin_time_s)
    if rpm is None or spin_time_s is None:
        raise ValueError("RPM·시간 또는 세부 회전 프로그램을 입력하세요.")
    values = [substrate_length_mm, substrate_width_mm, dispensed_volume_ml, density_kg_m3,
              dynamic_viscosity_pa_s, rpm, spin_time_s]
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError("기판 크기, 도포량, 액체 밀도·점도, 회전수, 회전 시간은 모두 0보다 커야 합니다.")
    if nonvolatile_volume_fraction is not None and (not math.isfinite(nonvolatile_volume_fraction) or not 0 < nonvolatile_volume_fraction <= 1):
        raise ValueError("비휘발 성분의 부피분율은 0 초과 1 이하여야 합니다.")
    if not 1 <= int(coating_cycles) <= 30:
        raise ValueError("코팅 횟수는 1–30회 범위여야 합니다.")
    area_m2 = substrate_length_mm * 1e-3 * substrate_width_mm * 1e-3
    initial_wet_m = dispensed_volume_ml * 1e-6 / area_m2
    omega = 2 * math.pi * rpm / 60
    def omega_squared_time(time_s: float) -> float:
        if not program:
            return omega**2 * time_s
        remaining = max(0.0, min(time_s, spin_time_s)); exposure = 0.0
        for step in program:
            duration = min(remaining, step["duration_s"])
            exposure += (2 * math.pi * step["rpm"] / 60) ** 2 * duration
            remaining -= duration
            if remaining <= 0: break
        return exposure
    thinning = 1 + (4 * density_kg_m3 * initial_wet_m**2 * omega_squared_time(spin_time_s)) / (3 * dynamic_viscosity_pa_s)
    final_wet_m = initial_wet_m / math.sqrt(thinning)
    dry_m = final_wet_m * nonvolatile_volume_fraction if nonvolatile_volume_fraction is not None else None
    return {
        "model_id": "Emslie-Bonner-Peck-spin-coating-v1",
        "status": "FIRST_ORDER_PROCESS_ESTIMATE" if nonvolatile_volume_fraction is not None else "WET_FILM_ESTIMATE_ONLY",
        "inputs": {"substrate_length_mm": substrate_length_mm, "substrate_width_mm": substrate_width_mm,
                   "dispensed_volume_ml": dispensed_volume_ml, "density_kg_m3": density_kg_m3,
                   "dynamic_viscosity_pa_s": dynamic_viscosity_pa_s, "rpm": rpm,
                    "spin_time_s": spin_time_s, "nonvolatile_volume_fraction": nonvolatile_volume_fraction,
                   "coating_cycles": int(coating_cycles), "substrate_material": substrate_material,
                    "coating_material": coating_material, "source_experiment_id": source_experiment_id,
                    "spin_program": program or [{"rpm": rpm, "duration_s": spin_time_s}]},
        "results": {"substrate_area_mm2": substrate_length_mm * substrate_width_mm,
                    "initial_uniform_wet_thickness_um": initial_wet_m * 1e6,
                    "end_of_spin_wet_thickness_um": final_wet_m * 1e6,
                    "single_cycle_nominal_dry_thickness_um": dry_m * 1e6 if dry_m is not None else None,
                    "cycles_nominal_dry_thickness_um": dry_m * int(coating_cycles) * 1e6 if dry_m is not None else None,
                    "thickness_time_curve": [{"time_s": spin_time_s * n / 20,
                        "wet_thickness_um": initial_wet_m / math.sqrt(1 + 4 * density_kg_m3 * initial_wet_m**2 * omega_squared_time(spin_time_s * n / 20) / (3 * dynamic_viscosity_pa_s)) * 1e6}
                        for n in range(21)]},
        "assumptions": ["Emslie–Bonner–Peck viscous-flow model: Newtonian liquid, uniform initial film on an ideal rotating flat disk, no solvent evaporation."],
        "limitations": ["Dispensed liquid is treated as a uniform starting layer over the entire substrate; edge bead, incomplete wetting, splashing, and spin-off details are not resolved.",
                        "Evaporation, surface tension, non-Newtonian rheology, sol-gel reactions, drying, annealing shrinkage, porosity, and roughness are not modeled.",
                        "Dry thickness uses the supplied nonvolatile volume fraction as a simple volume-conservation estimate; it is not a measured or calibrated film thickness.",
                        "Multiple-cycle thickness is a linear nominal sum and does not model interlayer redissolution, densification, or cracking.",
                        "A seed layer's crystallinity, texture, grain size, and surface roughness must be measured; this calculation does not predict subsequent crystal alignment or growth."] + (["Dry thickness is withheld because nonvolatile volume fraction was not supplied; a theoretical oxide yield is not substituted for this formulation property."] if nonvolatile_volume_fraction is None else [])
    }
