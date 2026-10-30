"""Thin-film drying and thermal-cycle estimators.

Drying adapts the lumped mixed-solvent mass-balance model used by SolVap
(NatLabRockies, Apache-2.0), with numeric Antoine coefficients from NIST.
The implementation deliberately accepts numeric properties only (no eval).
"""
from __future__ import annotations

import math
from typing import Any

from scipy.integrate import solve_ivp

R = 8.314

# Antoine coefficients: log10(p_bar) = A - B / (T_K + C), ranges and source URLs
# are retained with each solvent so the UI can show provenance.
SOLVENTS: dict[str, dict[str, Any]] = {
    "water": {"name": "Water", "rho_kg_m3": 1000.0, "mw_g_mol": 18.015, "A": 4.6543, "B": 1435.264, "C": -64.848, "range_k": [255.9, 373.0], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C7732185&Mask=4"},
    "ethanol": {"name": "Ethanol", "rho_kg_m3": 789.0, "mw_g_mol": 46.07, "A": 5.37229, "B": 1670.409, "C": -40.191, "range_k": [273.0, 351.7], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C64175&Mask=4"},
    "methanol": {"name": "Methanol", "rho_kg_m3": 791.8, "mw_g_mol": 32.04, "A": 5.20409, "B": 1581.341, "C": -33.50, "range_k": [288.1, 356.83], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C67561&Mask=1A8F"},
    "acetone": {"name": "Acetone", "rho_kg_m3": 790.0, "mw_g_mol": 58.08, "A": 4.42448, "B": 1312.253, "C": -32.445, "range_k": [259.16, 507.6], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C67641&Mask=4"},
    "isopropanol": {"name": "Isopropanol", "rho_kg_m3": 786.0, "mw_g_mol": 60.096, "A": 4.8610, "B": 1357.427, "C": -75.814, "range_k": [329.92, 362.41], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C67630&Mask=4"},
    "dmf": {"name": "DMF", "rho_kg_m3": 944.0, "mw_g_mol": 73.09, "A": 3.93068, "B": 1337.716, "C": -82.648, "range_k": [303.0, 363.0], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C68122&Mask=4"},
    "dmso": {"name": "DMSO", "rho_kg_m3": 1100.4, "mw_g_mol": 78.13, "A": 4.49107, "B": 1807.002, "C": -60.995, "range_k": [325.0, 442.09], "source": "NIST Chemistry WebBook", "url": "https://webbook.nist.gov/cgi/cbook.cgi?ID=C67685&Mask=4"},
}


def solvent_catalog() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in SOLVENTS.items()]


def simulate_film_drying(*, wet_thickness_um: float, solids_volume_fraction: float,
                         solvents: list[dict[str, Any]], solid_molar_volume_m3_mol: float,
                         temperature_c: float,
                         mass_transfer_m_s: float, duration_s: float = 3600.0) -> dict[str, Any]:
    if not math.isfinite(wet_thickness_um) or wet_thickness_um <= 0:
        raise ValueError("초기 습윤 막 두께는 0보다 커야 합니다.")
    if not 0 < solids_volume_fraction < 1:
        raise ValueError("고형분 부피분율은 0과 1 사이 값이어야 합니다.")
    if not math.isfinite(solid_molar_volume_m3_mol) or solid_molar_volume_m3_mol <= 0:
        raise ValueError("용질의 몰부피(m³/mol)가 필요합니다. 몰질량과 밀도를 알면 몰부피=몰질량/밀도로 계산하세요.")
    if not 1 <= len(solvents) <= 4:
        raise ValueError("용매는 1~4개를 선택하세요.")
    if not math.isfinite(temperature_c) or not math.isfinite(mass_transfer_m_s) or mass_transfer_m_s <= 0:
        raise ValueError("건조 온도와 양의 물질전달계수가 필요합니다.")
    T = temperature_c + 273.15
    if T <= 0:
        raise ValueError("온도는 절대영도보다 높아야 합니다.")
    parsed: list[tuple[str, float, float, float, str, str]] = []
    for item in solvents:
        key = str(item.get("solvent_id", "")).lower()
        data = SOLVENTS.get(key)
        if not data:
            raise ValueError(f"지원하지 않는 용매입니다: {key or '이름 없음'}")
        fraction = float(item.get("volume_fraction", 0))
        if not math.isfinite(fraction) or fraction <= 0:
            raise ValueError("각 용매의 부피분율은 0보다 커야 합니다.")
        if not data["range_k"][0] <= T <= data["range_k"][1]:
            raise ValueError(f"{data['name']}의 Antoine 자료 적용 온도 범위({data['range_k'][0]-273.15:.1f}–{data['range_k'][1]-273.15:.1f} °C)를 벗어났습니다.")
        p_sat = 10 ** (data["A"] - data["B"] / (T + data["C"])) * 100000
        molar_volume = data["mw_g_mol"] / 1000 / data["rho_kg_m3"]
        alpha = p_sat * molar_volume / (R * T)
        parsed.append((data["name"], fraction, molar_volume, alpha, data["source"], data["url"]))
    total_fraction = sum(x[1] for x in parsed)
    if abs(total_fraction - 1) > 0.03:
        raise ValueError("선택한 용매 부피분율 합은 1.00(100%)에 맞춰야 합니다.")
    fractions = [x[1] / total_fraction for x in parsed]
    n = len(parsed)
    V = [x[2] for x in parsed]
    alpha = [x[3] for x in parsed]
    h0 = wet_thickness_um * 1e-6
    # State vector: solvent volume fractions in the film followed by normalized thickness.
    y0 = [f * (1.0 - solids_volume_fraction) for f in fractions] + [1.0]

    def rhs(_time: float, y: list[float]) -> list[float]:
        phis = y[:n]
        phi_solid = max(1e-9, 1.0 - sum(phis))
        vol_molar = sum(phis[i] / V[i] for i in range(n)) + phi_solid / solid_molar_volume_m3_mol
        x = [(phis[i] / V[i]) / vol_molar for i in range(n)]
        # Solid is nonvolatile. beta is the effective gas-side transfer coefficient.
        h_rate = -mass_transfer_m_s * sum(alpha[i] * x[i] for i in range(n))
        h = max(y[-1] * h0, 1e-12)
        dphis = [(phis[i] / h) * (-h_rate) - mass_transfer_m_s * alpha[i] * x[i] / h for i in range(n)]
        return dphis + [h_rate / h0]

    cutoff = solids_volume_fraction + (1 - solids_volume_fraction) * 0.001
    def done(_time: float, y: list[float]) -> float:
        return y[-1] - cutoff
    done.terminal = True  # type: ignore[attr-defined]
    done.direction = -1  # type: ignore[attr-defined]
    points = 100
    sol = solve_ivp(rhs, (0, duration_s), y0, t_eval=[duration_s * i / (points - 1) for i in range(points)], events=done, rtol=1e-7, atol=1e-10, max_step=max(duration_s / 200, 0.01))
    curve = []
    for i, time in enumerate(sol.t):
        thickness = max(0.0, float(sol.y[-1, i]) * wet_thickness_um)
        liquid_volume_fraction = max(0.0, sum(float(sol.y[j, i]) for j in range(n)))
        curve.append({"time_s": float(time), "film_thickness_um": thickness, "remaining_solvent_fraction_of_initial": liquid_volume_fraction / (1 - solids_volume_fraction)})
    reached = bool(sol.t_events and len(sol.t_events[0]))
    return {
        "model_id": "SolVap-LPMSEM-mixed-solvent-film-drying-adapter-v1",
        "status": "MODEL_ESTIMATE" if sol.success else "SOLVER_WARNING",
        "inputs": {"wet_thickness_um": wet_thickness_um, "solids_volume_fraction": solids_volume_fraction, "solid_molar_volume_m3_mol": solid_molar_volume_m3_mol, "temperature_c": temperature_c, "mass_transfer_m_s": mass_transfer_m_s, "solvents": [{"name": x[0], "volume_fraction": fractions[i]} for i, x in enumerate(parsed)]},
        "results": {"drying_threshold_reached": reached, "estimated_drying_time_s": float(sol.t_events[0][0]) if reached else None, "nominal_nonvolatile_thickness_um": wet_thickness_um * solids_volume_fraction, "end_film_thickness_um": curve[-1]["film_thickness_um"] if curve else wet_thickness_um, "curve": curve},
        "sources": [{"name": x[0], "source": x[4], "url": x[5]} for x in parsed],
        "assumptions": ["Lumped, uniform film; ideal-volume mixture; constant temperature and effective gas-side mass-transfer coefficient.", "The initial film is already spread over the substrate; spin-driven drainage must be modeled separately.", "The solid phase is nonvolatile and does not dissolve, crystallize, react, crack, or change volume."],
        "limitations": ["Drying time is highly sensitive to airflow, solvent activity, substrate temperature, and film formulation; beta is an effective fitted input, not a universal constant.", "Nominal dry thickness assumes volume conservation and is not a densified/annealed thickness.", "Thermal reaction, decomposition, crystallinity, porosity, and shrinkage are not inferred by this evaporation model.", "SolVap is an open research model; this adapter is not independently validated against the user's formulation. Use only within displayed Antoine-data ranges and compare against measured mass/thickness."]
    }


def simulate_thermal_cycle(*, ambient_temperature_c: float, anneal_temperature_c: float,
                           ramp_rate_c_min: float, hold_time_min: float,
                           cooling_rate_c_min: float | None = None, activation_energy_kj_mol: float | None = None,
                           pre_exponential_s_inv: float | None = None, points: int = 80) -> dict[str, Any]:
    vals = [ambient_temperature_c, anneal_temperature_c, ramp_rate_c_min, hold_time_min]
    if not all(math.isfinite(float(x)) for x in vals) or ramp_rate_c_min < 0 or hold_time_min < 0:
        raise ValueError("열처리 온도, 0 이상의 승온 속도(0은 즉시 설정), 0 이상의 유지 시간이 필요합니다.")
    if cooling_rate_c_min is not None and (not math.isfinite(float(cooling_rate_c_min)) or cooling_rate_c_min <= 0):
        raise ValueError("냉각 속도는 생략하거나 0보다 크게 입력하세요.")
    if points < 10 or points > 500:
        raise ValueError("그래프 계산 점은 10~500 범위여야 합니다.")
    ramp_min = abs(anneal_temperature_c - ambient_temperature_c) / ramp_rate_c_min if ramp_rate_c_min > 0 else 0.0
    cool_min = abs(anneal_temperature_c - ambient_temperature_c) / cooling_rate_c_min if cooling_rate_c_min else 0.0
    total_min = ramp_min + hold_time_min + cool_min
    curve = []
    if ramp_min == 0:
        # Preserve an actual setpoint step in the plotted schedule: same time,
        # pre-step and post-step temperatures. Sample thermal lag is not modeled.
        curve.extend([{"time_min": 0.0, "temperature_c": ambient_temperature_c},
                      {"time_min": 0.0, "temperature_c": anneal_temperature_c}])
        first_index = 1
    else:
        first_index = 0
    for i in range(first_index, points + 1):
        t_min = total_min * i / points
        if ramp_min > 0 and t_min <= ramp_min:
            temp = ambient_temperature_c + (anneal_temperature_c - ambient_temperature_c) * t_min / ramp_min
        elif t_min <= ramp_min + hold_time_min:
            temp = anneal_temperature_c
        elif cool_min > 0:
            f = (t_min - ramp_min - hold_time_min) / max(cool_min, 1e-12)
            temp = anneal_temperature_c + (ambient_temperature_c - anneal_temperature_c) * f
        else:
            temp = anneal_temperature_c
        curve.append({"time_min": t_min, "temperature_c": temp})
    kinetic_dose = None
    conversion = None
    if activation_energy_kj_mol is not None or pre_exponential_s_inv is not None:
        if activation_energy_kj_mol is None or pre_exponential_s_inv is None or activation_energy_kj_mol <= 0 or pre_exponential_s_inv <= 0:
            raise ValueError("Arrhenius 추정에는 양의 활성화에너지와 전지수인자가 모두 필요합니다.")
        dose = 0.0
        for a, b in zip(curve, curve[1:]):
            temp_k = (a["temperature_c"] + b["temperature_c"]) / 2 + 273.15
            rate = pre_exponential_s_inv * math.exp(-activation_energy_kj_mol * 1000 / (R * temp_k))
            dose += rate * ((b["time_min"] - a["time_min"]) * 60)
        kinetic_dose = dose
        conversion = 1 - math.exp(-dose)
    return {"model_id": "user-defined-thermal-cycle-arrhenius-v1", "status": "THERMAL_PROFILE_ONLY" if conversion is None else "USER_PARAMETER_ARRHENIUS_ESTIMATE", "inputs": {"ambient_temperature_c": ambient_temperature_c, "anneal_temperature_c": anneal_temperature_c, "ramp_rate_c_min": ramp_rate_c_min, "hold_time_min": hold_time_min, "cooling_rate_c_min": cooling_rate_c_min, "activation_energy_kj_mol": activation_energy_kj_mol, "pre_exponential_s_inv": pre_exponential_s_inv}, "results": {"ramp_time_min": ramp_min, "hold_time_min": hold_time_min, "cool_time_min": cool_min, "total_cycle_min": total_min, "arrhenius_integrated_dose": kinetic_dose, "first_order_conversion_fraction": conversion, "temperature_time_curve": curve}, "limitations": ["Without material-specific kinetics this gives only the requested temperature-time program; it does not predict film densification, phase, decomposition, or thickness shrinkage.", "Optional conversion is a first-order Arrhenius calculation using user-supplied activation energy and pre-exponential factor; it is valid only if those parameters describe the target reaction and atmosphere.", "Sample temperature is assumed to follow the programmed temperature instantly; substrate/sample thermal lag and furnace calibration are not modeled.", "A zero ramp rate means an instantaneous setpoint step in the plotted program, not a prediction that the sample itself instantly reaches the setpoint."]}
