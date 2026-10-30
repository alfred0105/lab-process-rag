"""Metadata-first registry for existing deterministic analysis/simulation tools."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from app.services.simulation.openfoam import plan_simple_rushton_case
from app.services.simulation.readiness import assess_simulation_inputs

Readiness = Literal["READY", "MISSING_INPUT", "UNSUPPORTED", "UNAVAILABLE", "REQUIRES_REVIEW", "ABSTAIN"]


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    name: str
    version: str
    category: str
    required_inputs: tuple[str, ...]
    supported_modalities: tuple[str, ...]
    input_units: dict[str, tuple[str, ...]]
    output_schema: str
    applicability_conditions: tuple[str, ...]
    unsupported_conditions: tuple[str, ...]
    estimated_runtime_seconds: float | None
    estimated_memory_mb: int | None
    uncertainty_model: str
    validation_status: str
    execution_policy: str
    connected: bool


_DEFINITIONS = (
    ToolDefinition("xrd.local_peaks.v1", "XRD local peak preview", "1", "analysis", ("xrd_file", "x_axis_unit"), ("xrd",), {"x_axis_unit": ("degree_2theta", "angstrom", "nm")}, "peak_positions_and_intensities", ("numeric XRD pattern with declared x-axis unit",), ("phase identification, Rietveld refinement",), None, None, "No uncertainty estimate; local maxima only", "PILOT", "review_required", True),
    ToolDefinition("xrd.cod_phase_candidates.v1", "XRD COD phase candidates", "1", "analysis", ("xrd_file", "wavelength_angstrom", "target_elements_or_formulas"), ("xrd",), {"wavelength_angstrom": ("angstrom",)}, "ranked_reference_pattern_matches", ("XRD pattern and candidate element/formula scope",), ("quantitative phase fraction or definitive phase identity",), None, None, "Peak-position coverage score is not a probability", "EXPLORATORY_EXTERNAL_REFERENCE", "external_reference_review", True),
    ToolDefinition("afm.plane_level_roughness.v1", "AFM plane leveling and roughness", "1", "analysis", ("calibrated_height_grid", "lateral_scale", "height_unit"), ("afm",), {"lateral_scale": ("nm", "um"), "height_unit": ("nm", "um")}, "surface_roughness_and_height_map", ("rectangular calibrated height map",), ("uncalibrated image without scale metadata",), None, None, "No uncertainty model; scan artifacts require review", "PILOT", "review_required", True),
    ToolDefinition("microscopy.otsu_components.v1", "SEM/TEM threshold preview", "1", "analysis", ("microscopy_image", "pixel_size_nm"), ("sem", "tem"), {"pixel_size_nm": ("nm",)}, "segmentation_preview_and_component_metrics", ("image and scale calibration",), ("trained semantic segmentation or validated rod morphology",), None, None, "Exploratory segmentation; human review required", "PILOT", "review_required", True),
    ToolDefinition("phreeqc.aqueous_equilibrium.v1", "PHREEQC aqueous equilibrium", "1", "simulation", ("pH", "temperature", "dissolved_totals", "database"), (), {"pH": ("pH",), "temperature": ("degC", "K"), "dissolved_totals": ("mol/kgw", "mmol/L", "mol/L")}, "speciation_and_saturation_indices", ("aqueous chemistry with supported species/database",), ("nucleation, precipitation kinetics, particle size, yield",), None, None, "Thermodynamic model uncertainty not quantified", "MODEL_SCOPE_REVIEWED", "review_inputs_before_run", True),
    ToolDefinition("phreeqc.aqueous_sweep.v1", "PHREEQC pH sweep", "1", "simulation", ("temperature", "pH_range", "dissolved_totals", "database"), (), {"temperature": ("degC", "K"), "pH_range": ("pH",), "dissolved_totals": ("mol/kgw", "mmol/L", "mol/L")}, "speciation_and_saturation_curve", ("fixed composition sweep within supported database",), ("actual titration path without feed/charge balance model",), None, None, "Thermodynamic model uncertainty not quantified", "MODEL_SCOPE_REVIEWED", "review_inputs_before_run", True),
    ToolDefinition("openfoam.simpleRushtonMRF.v1", "OpenFOAM Rushton MRF", "14", "simulation", ("supported_closed_vessel_geometry", "Rushton_impeller", "rpm", "density", "viscosity"), (), {"geometry": ("m",), "rpm": ("rpm",), "density": ("kg/m3",), "viscosity": ("m2/s",)}, "flow_field_and_power_trace", ("supported baffled closed fully-filled cylindrical vessel and 4/6 blade Rushton",), ("magnetic stir bars, dosing jets, reactive species transport, nucleation",), None, None, "No validated error model; case review required", "TEMPLATE_ONLY", "human_approval_and_external_vm_required", True),
    ToolDefinition("hydrothermal.water_state.v1", "Hydrothermal water state", "1", "simulation", ("temperature_c", "hold_time_h", "fill_fraction"), (), {"temperature_c": ("degC",), "hold_time_h": ("h",), "fill_fraction": ("fraction",)}, "water_state_reference_values", ("water in supported temperature/pressure range",), ("material-specific growth length or yield",), None, None, "EOS/reference limits reported; no material-growth uncertainty", "REFERENCE_MODEL", "review_inputs_before_run", True),
    ToolDefinition("coating.spin_coating.v1", "Spin coating estimate", "1", "simulation", ("solution_properties", "drop_volume", "rpm_program", "substrate"), (), {"drop_volume": ("uL", "mL"), "rpm_program": ("rpm",)}, "film_estimate", ("known solution and substrate parameters",), ("unknown solvent/material properties silently inferred",), None, None, "Model assumptions reported; calibration required", "ESTIMATE_ONLY", "review_inputs_before_run", True),
    ToolDefinition("experiment.compare.v1", "Experiment condition comparison", "2", "data_quality", ("two_compatible_experiment_records",), (), {}, "same_different_missing_unresolved_variables", ("same known method version or explicit same-method cross-version mode",), ("mixed demo/lab comparison; unknown method mapping",), None, None, "Uses only recorded values and reported uncertainty; does not infer causation", "TESTED", "read_only", True),
    ToolDefinition("experiment.data_quality.v1", "Experiment record data quality", "1", "data_quality", ("experiment_record",), (), {}, "missing_units_and_normalization_errors", ("saved experiment record",), (), None, None, "Rules only; no scientific truth score", "TESTED", "read_only", True),
)


class ToolRegistry:
    def __init__(self, definitions: tuple[ToolDefinition, ...] = _DEFINITIONS):
        self._tools = {item.tool_id: item for item in definitions}

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def list(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self._tools.values()]


class ScientificStateBuilder:
    """Compress a stored run into typed context without changing original values."""
    @staticmethod
    def build(record: dict, analysis_runs: list[dict] | None = None) -> dict:
        conditions=[]
        for step in record.get("steps", []):
            for variable in step.get("variables", []):
                conditions.append({"step_name":step.get("name"),"step_order":step.get("order_index"),
                    "name":variable.get("name"),"value":variable.get("value"),"unit":variable.get("unit"),"material":variable.get("material")})
        modalities=sorted({str(item.get("modality", "")).lower() for item in analysis_runs or [] if item.get("analysis_status")=="completed"})
        return {"experiment_id":record.get("id"),"topic_id":record.get("topic_id"),"method_version_id":record.get("method_version_id"),
            "demo":bool(record.get("demo")),"status":record.get("status"),"conditions":conditions,"materials":record.get("materials",[]),
            "result_keys":[item.get("key") for item in record.get("results",[])],"available_modalities":modalities}


class DecisionPolicy(Protocol):
    def choose(self, state: dict, recommendations: list[dict]) -> dict: ...


class ExplanationProvider(Protocol):
    """Language layer contract; it may explain a decision but cannot execute it."""
    def explain(self, state: dict, decision: dict, result: dict | None = None) -> dict: ...


class RuleBasedDecisionPolicy:
    """Safe baseline policy; replaceable by a learned JEV DecisionPolicy later."""
    def choose(self, state: dict, recommendations: list[dict]) -> dict:
        ready=[item for item in recommendations if item["readiness"]=="READY"]
        if ready:
            selected=ready[0]
            action={"analysis":"RUN_ANALYSIS","simulation":"RUN_SIMULATION","data_quality":"GENERATE_EXPLANATION"}.get(selected["category"],"ABSTAIN")
            return {"action":action,
                "tool_id":selected["tool_id"],"reason":"A registered tool is compatible with the recorded input; execution still requires the validation gate.","confidence":"rule_match"}
        if any(item["readiness"]=="REQUIRES_REVIEW" for item in recommendations):
            return {"action":"REVIEW_RESULT","tool_id":None,"reason":"A candidate requires human or model-scope review before use.","confidence":"rule_match"}
        if any(item["readiness"]=="MISSING_INPUT" for item in recommendations):
            return {"action":"REQUEST_DATA","tool_id":None,"reason":"Potentially relevant tools need additional recorded inputs.","confidence":"rule_match"}
        return {"action":"ABSTAIN","tool_id":None,"reason":"No registered tool is currently applicable.","confidence":"rule_match"}


class ValidationGate:
    @staticmethod
    def validate(recommendation: dict) -> dict:
        allowed=recommendation.get("readiness")=="READY"
        approval=recommendation.get("execution_policy") not in {"read_only"}
        return {"allowed":allowed and not approval,"requires_human_approval":allowed and approval,
            "status":"READY" if allowed and not approval else "REQUIRES_REVIEW" if allowed and approval else recommendation.get("readiness"),
            "reason":"Read-only tool may proceed." if allowed and not approval else "Approval and/or input validation is required before any tool execution."}


class ToolExecutor:
    """Preparation-only interface. Registry recommendations do not execute tools."""
    def __init__(self, registry: ToolRegistry): self.registry=registry
    def prepare(self, tool_id: str, recommendation: dict) -> dict:
        tool=self.registry.get(tool_id)
        if tool is None: return {"status":"UNAVAILABLE","tool_id":tool_id,"invocation":None}
        if recommendation.get("readiness")!="READY": return {"status":recommendation.get("readiness"),"tool_id":tool_id,"invocation":None}
        return {"status":"PREPARED_FOR_REVIEW","tool_id":tool_id,"invocation":None,"execution_policy":tool.execution_policy}


class ResultValidator:
    @staticmethod
    def validate(tool: ToolDefinition, result: object) -> dict:
        if not isinstance(result, dict): return {"valid":False,"reason":"result_must_be_structured_object"}
        return {"valid":True,"tool_id":tool.tool_id,"notice":"Output schema validation is metadata-only until this tool adapter is connected."}


def recommend_tools(record: dict, analysis_runs: list[dict], *, openfoam_installed: bool = False, openfoam_template_available: bool = False) -> dict:
    registry=ToolRegistry()
    state=ScientificStateBuilder.build(record,analysis_runs)
    modalities=set(state["available_modalities"])
    condition_names={str(item.get("name", "")).casefold().replace("_", " ") for item in state["conditions"]}
    normalized=" ".join(condition_names)
    output=[]
    for tool in registry.list():
        item={**tool,"readiness":"UNAVAILABLE","missing_inputs":[],"reason":"Tool is not available for this record."}
        if tool["tool_id"]=="experiment.data_quality.v1":
            item.update(readiness="READY",missing_inputs=[],reason="Record fields can be checked without changing data.")
        elif tool["tool_id"]=="experiment.compare.v1":
            item.update(readiness="MISSING_INPUT",missing_inputs=["a second eligible experiment"],reason="Select a compatible record pair to compare.")
        elif tool["tool_id"].startswith("xrd."):
            if "xrd" in modalities: item.update(readiness="REQUIRES_REVIEW" if "cod" in tool["tool_id"] else "READY",missing_inputs=[],reason="An analyzed XRD measurement is linked to this record.")
            else: item.update(readiness="MISSING_INPUT",missing_inputs=["XRD measurement"],reason="Link an XRD measurement to this record first.")
        elif tool["tool_id"].startswith("afm."):
            item.update(readiness="READY" if "afm" in modalities else "MISSING_INPUT",missing_inputs=[] if "afm" in modalities else ["AFM height map"],reason="AFM measurement is available." if "afm" in modalities else "No AFM measurement is linked.")
        elif tool["tool_id"].startswith("microscopy."):
            found=bool(modalities.intersection({"sem","tem"}))
            item.update(readiness="READY" if found else "MISSING_INPUT",missing_inputs=[] if found else ["SEM/TEM image"],reason="Microscopy measurement is available." if found else "No SEM/TEM image is linked.")
        elif tool["tool_id"].startswith("phreeqc."):
            base_missing=[]
            if "ph" not in normalized: base_missing.append("pH")
            if "temperature" not in normalized: base_missing.append("temperature")
            if not any(token in normalized for token in ("concentration","total","amount","molality")): base_missing.append("dissolved totals")
            item.update(readiness="MISSING_INPUT" if base_missing else "REQUIRES_REVIEW",missing_inputs=base_missing,
                reason="Required solution inputs are not all recorded." if base_missing else "Chemistry database and solution consistency must be reviewed before calculation.")
        elif tool["tool_id"].startswith("openfoam."):
            plan=plan_simple_rushton_case(record)
            if not openfoam_installed: readiness="UNAVAILABLE"; reason="OpenFOAM is not installed or reachable in the configured VM."
            elif not openfoam_template_available: readiness="UNAVAILABLE"; reason="The supported OpenFOAM template is unavailable."
            elif plan["status"]!="ready_for_review": readiness="UNSUPPORTED" if plan["status"]=="unsupported_geometry" else "MISSING_INPUT"; reason="; ".join(plan.get("unsupported_reasons",[])+plan.get("missing",[]))
            else: readiness="REQUIRES_REVIEW"; reason="Compatible inputs exist; inspect the case and approve its external VM run."
            item.update(readiness=readiness,missing_inputs=plan.get("missing",[]),reason=reason)
        else:
            related=[name for name in condition_names if any(token in name for token in ("rpm","spin","coating","temperature","time"))]
            item.update(readiness="MISSING_INPUT" if not related else "REQUIRES_REVIEW",missing_inputs=list(tool["required_inputs"]) if not related else [],reason="Related fields alone do not prove this model's inputs are complete; review its required parameters.")
        item["validation_gate"]=ValidationGate.validate(item)
        output.append(item)
    policy=RuleBasedDecisionPolicy()
    decision=policy.choose(state,output)
    selected=next((item for item in output if item["tool_id"]==decision.get("tool_id")),None)
    prepared=ToolExecutor(registry).prepare(selected["tool_id"],selected) if selected else None
    return {"state":state,"recommendations":output,"decision":decision,"prepared_invocation":prepared,
        "notice":"This is a rule-based readiness suggestion, not a learned JEV decision and does not execute tools."}
