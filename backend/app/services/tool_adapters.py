"""Allowlisted adapters for deterministic scientific tools already in the app."""
from __future__ import annotations

import math
from typing import Any, Callable, Protocol

from app.schemas.core import AqueousEquilibriumRequest, AqueousSweepRequest
from app.services.material_analysis.service import AnalysisInputError, analyze as analyze_material
from app.services.simulation.phreeqc import (calculate_aqueous_equilibrium,
    run_usgs_example_2_gypsum_reference, sweep_aqueous_equilibrium)
from app.services.tool_registry import ResultValidator, ToolRegistry


class ToolAdapter(Protocol):
    tool_id: str
    def validate_inputs(self, inputs: dict) -> Any: ...
    def prepare(self, validated: Any) -> Any: ...
    def execute(self, prepared: Any) -> Any: ...
    def validate_outputs(self, output: Any) -> dict: ...
    def persist(self, output: Any, callback: Callable[[Any], Any]) -> Any: ...


class MaterialAnalysisAdapter:
    """Adapter for the existing XRD, AFM and SEM/TEM deterministic engine."""
    def validate_inputs(self, inputs: dict) -> dict:
        data=inputs.get("data")
        modality=str(inputs.get("modality","")).strip().lower()
        filename=str(inputs.get("filename", "upload"))
        if not isinstance(data,bytes) or not data:
            raise AnalysisInputError("Measurement file is empty or missing.")
        if len(data)>25*1024*1024:
            raise AnalysisInputError("Analysis files are limited to 25 MiB in this pilot.")
        if modality not in {"xrd","afm","sem","tem"}:
            raise AnalysisInputError("Modality must be one of xrd, afm, sem, or tem.")
        x_unit=inputs.get("xrd_x_unit","2theta_deg")
        height_unit=inputs.get("afm_height_unit","nm")
        pixel=inputs.get("pixel_size_nm",1.0)
        foreground=inputs.get("foreground","bright")
        if x_unit not in {"2theta_deg","d_angstrom","q_angstrom^-1"}:
            raise AnalysisInputError("XRD axis must be declared as 2theta_deg, d_angstrom, or q_angstrom^-1.")
        if height_unit not in {"nm","um","angstrom","m"}:
            raise AnalysisInputError("AFM height unit must be nm, um, angstrom, or m.")
        if isinstance(pixel,bool) or not isinstance(pixel,(int,float)) or not math.isfinite(float(pixel)) or not 0<float(pixel)<=100000:
            raise AnalysisInputError("Pixel calibration must be finite, greater than zero, and no more than 100000 nm per pixel.")
        if foreground not in {"bright","dark"}:
            raise AnalysisInputError("Foreground must be bright or dark.")
        return {**inputs,"data":data,"modality":modality,"filename":filename,"xrd_x_unit":x_unit,
            "afm_height_unit":height_unit,"pixel_size_nm":float(pixel),"foreground":foreground}

    def prepare(self, validated: dict) -> dict:
        return validated

    def execute(self, prepared: dict):
        return analyze_material(prepared["modality"],prepared["data"],prepared["filename"],
            xrd_x_unit=prepared["xrd_x_unit"],afm_height_unit=prepared["afm_height_unit"],
            pixel_size_nm=prepared["pixel_size_nm"],foreground=prepared["foreground"])

    def validate_outputs(self, output) -> dict:
        tool=ToolRegistry().get(output.tool_id)
        return ResultValidator.validate(tool,output.result) if tool else {"valid":False,"reason":"tool_not_registered"}

    def persist(self, output, callback: Callable[[Any], Any]):
        return callback(output)


class PHREEQCAdapter:
    def __init__(self, *, sweep: bool=False):
        self.sweep=sweep
        self.tool_id="phreeqc.aqueous_sweep.v1" if sweep else "phreeqc.aqueous_equilibrium.v1"

    def validate_inputs(self, inputs: dict) -> dict:
        model=AqueousSweepRequest.model_validate(inputs) if self.sweep else AqueousEquilibriumRequest.model_validate(inputs)
        values=model.model_dump()
        if any(not math.isfinite(float(value)) for value in values.get("totals_molal",{}).values()):
            raise ValueError("Concentration inputs must all be finite numbers.")
        if self.sweep:
            values.pop("pH",None)
            if values["pH_min"]>=values["pH_max"]:
                raise ValueError("pH sweep minimum must be lower than its maximum.")
        return values

    def prepare(self, validated: dict) -> dict:
        return validated

    def execute(self, prepared: dict) -> dict:
        fn=sweep_aqueous_equilibrium if self.sweep else calculate_aqueous_equilibrium
        return fn(**prepared)

    def execute_official_reference(self, reference_id: str) -> dict:
        """Run an allowlisted official golden case through this PHREEQC adapter."""
        if reference_id != "usgs_example_2_gypsum_anhydrite_25c":
            raise ValueError("Unsupported PHREEQC reference case.")
        if self.sweep:
            raise ValueError("Official batch-reaction reference is not a pH sweep.")
        return run_usgs_example_2_gypsum_reference()

    def validate_outputs(self, output: Any) -> dict:
        tool=ToolRegistry().get(self.tool_id)
        return ResultValidator.validate(tool,output) if tool else {"valid":False,"reason":"tool_not_registered"}

    def persist(self, output: dict, callback: Callable[[dict], Any]):
        return callback(output)
