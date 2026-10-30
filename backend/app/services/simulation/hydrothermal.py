"""General hydrothermal water-state calculations plus literature model registry."""
from __future__ import annotations
import math


def calculate_hydrothermal_water_state(*, temperature_c: float, hold_time_h: float,
                                       fill_fraction: float | None = None,
                                       substrate_context: dict | None = None) -> dict:
    if not math.isfinite(temperature_c) or not 0 <= temperature_c <= 350:
        raise ValueError("이 계산기는 물의 포화증기압 참고값을 0–350°C 범위에서 계산합니다.")
    if not math.isfinite(hold_time_h) or not 0 < hold_time_h <= 1000:
        raise ValueError("유지 시간은 0보다 크고 1000시간 이하여야 합니다.")
    if fill_fraction is not None and (not math.isfinite(fill_fraction) or not 0 < fill_fraction < 1):
        raise ValueError("충전율은 0과 1 사이의 비율로 입력하세요.")
    from iapws import IAPWS97
    saturation = IAPWS97(T=temperature_c + 273.15, x=0)
    pressure_mpa = float(saturation.P)
    return {
        "model_id":"IAPWS-IF97-water-saturation-reference",
        "status":"WATER_THERMODYNAMIC_REFERENCE",
        "inputs":{"temperature_c":temperature_c,"hold_time_h":hold_time_h,"fill_fraction":fill_fraction,
                  "substrate_context":substrate_context},
        "results":{"pure_water_saturation_pressure_mpa_abs":pressure_mpa,
                   "pure_water_saturation_pressure_bar_abs":pressure_mpa*10,
                   "hold_time_h":hold_time_h},
        "limitations":["Pressure is the saturation pressure of pure water at the stated temperature, not a rated-autoclave pressure calculation.",
                       "Solutes, headspace gas, vessel fill/thermal expansion, non-equilibrium heating, and sealed-vessel mechanics are not included.",
                       "This general hydrothermal state calculation does not predict reaction conversion, nucleation, crystal phase, morphology, nanorod dimensions, or yield.",
                       "Never use this estimate to select vessel, set a safety limit, or replace the manufacturer's pressure/temperature rating.",
                       "Attached substrate/coating information is carried as process context only; it does not alter this water-state calculation or predict nucleation, alignment, or crystal growth."]
    }


def zno_literature_growth_reference(*, time_h: float) -> dict:
    """A fixed, non-extrapolating reproduction of a reported ZnO array benchmark."""
    if not math.isfinite(time_h) or not 0 <= time_h <= 8:
        raise ValueError("문헌 성장 참고 곡선은 보고된 첫 8시간 범위에서만 표시합니다.")
    # Guo et al. report ~5.5 nm/min and up to 2.4 um array thickness in first 8 h.
    length_um = min(5.5 * time_h * 60 / 1000, 2.4)
    return {"model_id":"literature-reference-zno-nanorod-array-guo-2007",
            "status":"PUBLISHED_REFERENCE_ONLY",
            "inputs":{"time_h":time_h},
            "results":{"reported_array_layer_length_um_reference":length_um,
                       "reported_growth_rate_nm_min_reference":5.5,
                       "reported_upper_length_um_reference":2.4},
            "source":{"citation":"Guo et al., Chinese Journal of Engineering 29(7), 735–738, 2007",
                      "doi":"10.13374/j.issn1001-053x.2007.07.019",
                      "url":"https://cje.ustb.edu.cn/en/article/doi/10.13374/j.issn1001-053x.2007.07.019?viewType=citedby-info"},
            "limitations":["This is a fixed literature reference curve, not a prediction for the user's process or individual rod length.",
                           "The paper describes array layer length/thickness and reports a two-stage width evolution; this endpoint does not reconstruct individual rod morphology.",
                           "Do not transfer this ZnO-specific result to other materials, seed layers, recipes, or reactor conditions.",
                           "A material-specific predictive model needs the full matching recipe, time-resolved measurements, and independent validation."]}
