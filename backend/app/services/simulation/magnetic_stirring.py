"""Transparent magnetic stir-bar descriptors; these are not CFD predictions."""
from __future__ import annotations
import math


def characterize_magnetic_stirring(*, bar_length_mm: float, bar_diameter_mm: float,
                                   rpm: float, liquid_density_kg_m3: float,
                                   dynamic_viscosity_pa_s: float,
                                   liquid_volume_ml: float | None = None,
                                   beaker_inner_diameter_mm: float | None = None,
                                   bottom_clearance_mm: float | None = None) -> dict:
    vals = [bar_length_mm, bar_diameter_mm, rpm, liquid_density_kg_m3, dynamic_viscosity_pa_s]
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("바 길이·지름, 실제 회전수, 액체 밀도·점도는 0보다 큰 유한값이어야 합니다.")
    if bar_diameter_mm >= bar_length_mm:
        raise ValueError("교반바 길이는 지름보다 커야 합니다.")
    if liquid_volume_ml is not None and (not math.isfinite(liquid_volume_ml) or liquid_volume_ml <= 0):
        raise ValueError("용액 부피는 0보다 커야 합니다.")
    if beaker_inner_diameter_mm is not None and (not math.isfinite(beaker_inner_diameter_mm) or beaker_inner_diameter_mm <= 0):
        raise ValueError("비커 안지름은 0보다 커야 합니다.")
    if bottom_clearance_mm is not None and (not math.isfinite(bottom_clearance_mm) or bottom_clearance_mm < 0):
        raise ValueError("바닥 간극은 0 이상이어야 합니다.")
    omega = 2 * math.pi * rpm / 60
    length_m = bar_length_mm / 1000
    tip_speed = omega * length_m / 2
    reynolds = liquid_density_kg_m3 * tip_speed * length_m / dynamic_viscosity_pa_s
    froude = omega**2 * length_m / 9.80665
    return {
        "model_id": "magnetic-stir-bar-characterization-v1",
        "status": "DIMENSIONLESS_ESTIMATE",
        "inputs": {"bar_length_mm":bar_length_mm,"bar_diameter_mm":bar_diameter_mm,"rpm":rpm,
                   "liquid_density_kg_m3":liquid_density_kg_m3,"dynamic_viscosity_pa_s":dynamic_viscosity_pa_s,
                   "liquid_volume_ml":liquid_volume_ml,"beaker_inner_diameter_mm":beaker_inner_diameter_mm,
                   "bottom_clearance_mm":bottom_clearance_mm},
        "results": {"angular_speed_rad_s":omega,"bar_tip_speed_m_s":tip_speed,
                    "bar_length_reynolds_number":reynolds,"bar_length_froude_number":froude,
                    "bar_to_beaker_diameter_ratio":bar_length_mm/beaker_inner_diameter_mm if beaker_inner_diameter_mm else None,
                    "clearance_to_bar_diameter_ratio":bottom_clearance_mm/bar_diameter_mm if bottom_clearance_mm is not None else None},
        "interpretation": "Dimensionless and kinematic descriptors for the entered actual bar RPM; not a spatial flow or mixing-time solution.",
        "limitations": ["Does not solve the magnetic coupling/slip between hotplate and bar.",
                        "Does not calculate the 3-D velocity field, free-surface vortex, local shear, scalar mixing time, or reaction transport.",
                        "A CFD case must use the actual capsule/bar geometry and be validated against tracer or velocity measurements before treating its mixing results as predictive."]
    }
