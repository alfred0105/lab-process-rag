"""Metadata-first registry for existing deterministic analysis/simulation tools."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol
import math
import re

from app.services.simulation.openfoam import plan_simple_rushton_case
from app.services.simulation.readiness import assess_simulation_inputs

Readiness = Literal["READY", "ALREADY_ANALYZED", "REANALYSIS_REQUIRED", "MISSING_INPUT", "UNSUPPORTED", "UNAVAILABLE", "REQUIRES_REVIEW", "ABSTAIN"]


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
        modalities=sorted({str(item.get("modality", "")).lower() for item in analysis_runs or []})
        return {"experiment_id":record.get("id"),"topic_id":record.get("topic_id"),"method_version_id":record.get("method_version_id"),
            "demo":bool(record.get("demo")),"status":record.get("status"),"conditions":conditions,"materials":record.get("materials",[]),
            "result_keys":[item.get("key") for item in record.get("results",[])],"available_modalities":modalities,
            "analysis_runs":[{k:item.get(k) for k in ("id","modality","tool_id","analysis_status","review_status","sha256","result") if k in item} for item in analysis_runs or []]}


class DecisionPolicy(Protocol):
    def choose(self, state: dict, recommendations: list[dict]) -> dict: ...


class ExplanationProvider(Protocol):
    """Language layer contract; it may explain a decision but cannot execute it."""
    def explain(self, state: dict, decision: dict, result: dict | None = None) -> dict: ...


class RuleBasedDecisionPolicy:
    """Safe baseline policy; replaceable by a learned JEV DecisionPolicy later."""
    def choose(self, state: dict, recommendations: list[dict], goal: str = "") -> dict:
        goal_text=goal.casefold()
        if any(x in goal_text for x in ("quality","검증","누락","단위")):
            return {"action":"RUN_DATA_VALIDATION","tool_id":"experiment.data_quality.v1","reason":"The requested goal is record and unit validation.","confidence":"rule_match"}
        targets=("xrd" if any(x in goal_text for x in ("xrd","diffraction","회절","결정상")) else
                 "afm" if any(x in goal_text for x in ("afm","roughness","거칠기","표면")) else
                 "microscopy" if any(x in goal_text for x in ("sem","tem","microscopy","현미경","입자")) else
                 "phreeqc" if any(x in goal_text for x in ("phreeqc","speciation","equilibrium","수용액","화학종","포화")) else
                 "data_quality" if any(x in goal_text for x in ("quality","검증","누락","단위")) else None)
        ready=[item for item in recommendations if item["readiness"]=="READY" and item["category"] != "data_quality"]
        if targets:
            ready=[item for item in ready if item["tool_id"].startswith(targets)]
        relevant=[item for item in recommendations if not targets or item["tool_id"].startswith(targets)]
        if ready:
            selected=ready[0]
            action={"analysis":"RUN_ANALYSIS","simulation":"RUN_SIMULATION"}.get(selected["category"],"ABSTAIN")
            return {"action":action,
                "tool_id":selected["tool_id"],"reason":"A registered tool is compatible with the recorded input; execution still requires the validation gate.","confidence":"rule_match"}
        if targets and any(item["readiness"]=="ALREADY_ANALYZED" for item in recommendations if item["tool_id"].startswith(targets)):
            return {"action":"ABSTAIN","tool_id":None,"reason":"The requested analysis is already present; no duplicate run was selected.","confidence":"rule_match"}
        if any(item["readiness"]=="REQUIRES_REVIEW" for item in relevant):
            return {"action":"REVIEW_RESULT","tool_id":None,"reason":"A candidate requires human or model-scope review before use.","confidence":"rule_match"}
        if any(item["readiness"]=="MISSING_INPUT" for item in relevant):
            return {"action":"REQUEST_DATA","tool_id":None,"reason":"Potentially relevant tools need additional recorded inputs.","confidence":"rule_match"}
        return {"action":"ABSTAIN","tool_id":None,"reason":"No registered tool is currently applicable.","confidence":"rule_match"}


class ValidationGate:
    @staticmethod
    def validate(recommendation: dict, *, approval_granted: bool = False) -> dict:
        readiness=recommendation.get("readiness")
        needs_approval=recommendation.get("execution_policy") not in {"read_only", ""}
        eligible=readiness=="READY" or (readiness=="REQUIRES_REVIEW" and approval_granted)
        allowed=eligible and (not needs_approval or approval_granted)
        status="READY" if allowed else "REQUIRES_REVIEW" if readiness=="REQUIRES_REVIEW" or (eligible and needs_approval) else readiness
        return {"allowed":allowed,"requires_human_approval":needs_approval and not approval_granted,
            "status":status,"reason":"Fresh input validation passed and approval requirements are satisfied." if allowed else "Fresh validation or required human approval is missing."}


class ToolExecutor:
    """Shared execution contract for registered adapters; adapters never run arbitrary text."""
    def __init__(self, registry: ToolRegistry): self.registry=registry
    def prepare(self, tool_id: str, recommendation: dict) -> dict:
        tool=self.registry.get(tool_id)
        if tool is None: return {"status":"UNAVAILABLE","tool_id":tool_id,"invocation":None}
        if recommendation.get("readiness")!="READY": return {"status":recommendation.get("readiness"),"tool_id":tool_id,"invocation":None}
        return {"status":"PREPARED_FOR_REVIEW","tool_id":tool_id,"invocation":None,"execution_policy":tool.execution_policy}

    def execute_adapter(self, adapter, inputs: dict, persist, *, before_execute=None):
        """Run validate → prepare → fresh gate → execute → validate output → persist."""
        checked=adapter.validate_inputs(inputs)
        prepared=adapter.prepare(checked)
        if before_execute is not None:
            before_execute(checked, prepared)
        output=adapter.execute(prepared)
        result_validation=adapter.validate_outputs(output)
        if not result_validation.get("valid"):
            raise ValueError(f"adapter_output_invalid: {result_validation.get('reason','unknown')}")
        return adapter.persist(output,persist)


class ResultValidator:
    @staticmethod
    def validate(tool: ToolDefinition, result: object) -> dict:
        if not isinstance(result, dict): return {"valid":False,"reason":"result_must_be_structured_object"}
        if not result: return {"valid":False,"reason":"result_must_not_be_empty"}
        numbers=[]
        def walk(value):
            if isinstance(value, bool) or value is None: return
            if isinstance(value, (int,float)):
                numbers.append(float(value))
            elif isinstance(value, dict):
                for child in value.values(): walk(child)
            elif isinstance(value, (list,tuple)):
                for child in value: walk(child)
        walk(result)
        if any(not math.isfinite(value) for value in numbers): return {"valid":False,"reason":"non_finite_numeric_output"}
        if tool.tool_id.startswith("phreeqc.") and not result.get("model_id", "").startswith("PHREEQC"):
            return {"valid":False,"reason":"phreeqc_model_provenance_missing"}
        if tool.tool_id=="phreeqc.aqueous_equilibrium.v1" and not all(key in result for key in ("input_pH","aqueous_species","saturation_indices")):
            return {"valid":False,"reason":"phreeqc_equilibrium_outputs_missing"}
        if tool.tool_id.startswith("phreeqc."):
            for key in ("input_pH", "calculated_pH", "temperature_c"):
                if key in result and (not isinstance(result[key], (int, float)) or isinstance(result[key], bool)):
                    return {"valid":False,"reason":f"phreeqc_{key}_must_be_numeric"}
            # Do not impose the conventional aqueous pH 0–14 interval on
            # model output: concentrated/non-ideal solutions and model
            # conventions can produce values outside it. The model input
            # schema and finite-number check remain the applicable guards.
            species=result.get("aqueous_species", [])
            if not isinstance(species, list) or any(not isinstance(item, dict) or not item.get("name") or not isinstance(item.get("molality"), (int,float)) or item["molality"] < 0 for item in species):
                return {"valid":False,"reason":"phreeqc_species_schema_or_molality_invalid"}
            indices=result.get("saturation_indices", [])
            if not isinstance(indices, list) or any(not isinstance(item, dict) or not item.get("phase") or (item.get("saturation_index") is not None and not isinstance(item.get("saturation_index"),(int,float))) for item in indices):
                return {"valid":False,"reason":"phreeqc_saturation_index_schema_invalid"}
        if tool.tool_id=="phreeqc.aqueous_sweep.v1" and not isinstance(result.get("points"),list):
            return {"valid":False,"reason":"phreeqc_sweep_points_missing"}
        if tool.tool_id.startswith("xrd.") and "peaks" not in result and "observed_peaks" not in result:
            return {"valid":False,"reason":"xrd_peak_output_missing"}
        if tool.tool_id.startswith("xrd."):
            peaks=result.get("peaks",result.get("observed_peaks"))
            if not isinstance(peaks,list) or any(not isinstance(item,dict) or not any(isinstance(item.get(key),(int,float)) for key in ("position","x","two_theta","d_spacing_angstrom")) for item in peaks):
                return {"valid":False,"reason":"xrd_peak_schema_invalid"}
        if tool.tool_id.startswith("afm.") and not any(key in result for key in ("Sa_nm","Sq_nm","Sz_nm","Sa","Sq","Sz")):
            return {"valid":False,"reason":"afm_roughness_output_missing"}
        if tool.tool_id.startswith("afm."):
            for key in ("Sa_nm","Sq_nm","Sz_nm","Sa","Sq","Sz"):
                if key in result and (not isinstance(result[key],(int,float)) or result[key] < 0):
                    return {"valid":False,"reason":"afm_roughness_must_be_nonnegative"}
        if tool.tool_id.startswith("microscopy.") and not any(key in result for key in ("component_count","object_count")):
            return {"valid":False,"reason":"microscopy_component_output_missing"}
        if tool.tool_id.startswith("microscopy."):
            count=result.get("component_count",result.get("object_count"))
            if not isinstance(count,int) or isinstance(count,bool) or count < 0:
                return {"valid":False,"reason":"microscopy_component_count_invalid"}
        if tool.tool_id.startswith("openfoam."):
            trace=result.get("power_trace")
            if result.get("solver_completed_marker")!="End":
                return {"valid":False,"reason":"openfoam_solver_normal_completion_unverified"}
            if not isinstance(trace,list) or len(trace)<2:
                return {"valid":False,"reason":"openfoam_power_trace_insufficient"}
            required=("time_s","divStressU","divStressDotU","stressDDotGradU","divPU","gradPU","pDivU","divTauU","divTauDotU","tauDDotGradU")
            if any(not isinstance(row,dict) or any(not isinstance(row.get(key),(int,float)) or isinstance(row.get(key),bool) or not math.isfinite(float(row[key])) for key in required) for row in trace):
                return {"valid":False,"reason":"openfoam_power_trace_schema_invalid"}
            times=[float(row["time_s"]) for row in trace]
            if any(right<=left for left,right in zip(times,times[1:])):
                return {"valid":False,"reason":"openfoam_time_trace_not_increasing"}
        return {"valid":True,"tool_id":tool.tool_id,"numeric_values_checked":len(numbers)}


def _number_with_unit(value: object, unit: object) -> float | None:
    match=re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",str(value or ""))
    if not match: return None
    try:
        parsed=float(match.group())
        return parsed if math.isfinite(parsed) else None
    except ValueError: return None

def recommend_tools(record: dict, analysis_runs: list[dict], *, goal: str = "", openfoam_installed: bool = False, openfoam_template_available: bool = False) -> dict:
    registry=ToolRegistry()
    state=ScientificStateBuilder.build(record,analysis_runs)
    modalities=set(state["available_modalities"])
    conditions=state["conditions"]
    condition_names={str(item.get("name", "")).casefold().replace("_", " ") for item in conditions}
    normalized=" ".join(condition_names)
    output=[]
    for tool in registry.list():
        item={**tool,"readiness":"UNAVAILABLE","missing_inputs":[],"reason":"Tool is not available for this record."}
        if tool["tool_id"]=="experiment.data_quality.v1":
            item.update(readiness="READY",missing_inputs=[],reason="Record fields can be checked without changing data.",action="RUN_DATA_VALIDATION")
        elif tool["tool_id"]=="experiment.compare.v1":
            item.update(readiness="MISSING_INPUT",missing_inputs=["a second eligible experiment"],reason="Select a compatible record pair to compare.")
        elif tool["tool_id"].startswith("xrd."):
            runs=[run for run in analysis_runs if str(run.get("modality","")).lower()=="xrd"]
            completed=any(run.get("analysis_status")=="completed" and (tool["tool_id"]!="xrd.cod_phase_candidates.v1" or (run.get("result") or {}).get("observed_peaks")) for run in runs)
            item.update(readiness="ALREADY_ANALYZED" if completed and tool["tool_id"]=="xrd.local_peaks.v1" else "REQUIRES_REVIEW" if completed else "MISSING_INPUT",missing_inputs=[] if runs else ["XRD measurement"],reason="An XRD analysis is already recorded." if completed else "XRD input requires analysis; upload through the measurement analysis workflow.")
        elif tool["tool_id"].startswith("afm."):
            runs=[run for run in analysis_runs if str(run.get("modality","")).lower()=="afm"]
            done=any(run.get("analysis_status")=="completed" for run in runs)
            item.update(readiness="ALREADY_ANALYZED" if done else "MISSING_INPUT",missing_inputs=[] if runs else ["calibrated AFM height map"],reason="AFM analysis is already recorded." if done else "A calibrated height map is required; upload through measurement analysis.")
        elif tool["tool_id"].startswith("microscopy."):
            found=bool(modalities.intersection({"sem","tem"}))
            runs=[run for run in analysis_runs if str(run.get("modality","")).lower() in {"sem","tem"}]
            done=any(run.get("analysis_status")=="completed" for run in runs)
            item.update(readiness="ALREADY_ANALYZED" if done else "MISSING_INPUT",missing_inputs=[] if found else ["SEM/TEM image and calibrated pixel size"],reason="Microscopy analysis is already recorded." if done else "Image analysis runs when a scale-calibrated measurement is uploaded.")
        elif tool["tool_id"].startswith("phreeqc."):
            base_missing=[]
            pH=[v for v in conditions if "ph"==str(v.get("name","")).casefold().replace("_"," ") and _number_with_unit(v.get("value"),v.get("unit")) is not None and str(v.get("unit") or "pH").casefold() in {"ph",""}]
            temp=[v for v in conditions if "temp" in str(v.get("name","")).casefold() and _number_with_unit(v.get("value"),v.get("unit")) is not None and str(v.get("unit") or "").casefold() in {"°c","c","degc","k","°k"}]
            totals=[v for v in conditions if str(v.get("unit") or "").casefold() in {"mol/kgw","mol/kg","molal","mol/l","mmol/l"} and _number_with_unit(v.get("value"),v.get("unit")) is not None and any(element.casefold() in str(v.get("name","")).casefold() for element in ("zn","ca","mg","na","k","cl","si","al","fe","cu","c","s"))]
            if not pH: base_missing.append("measured pH with pH unit")
            if not temp: base_missing.append("temperature with °C or K unit")
            if not totals: base_missing.append("identified dissolved-element totals with concentration units")
            item.update(readiness="MISSING_INPUT" if base_missing else "REQUIRES_REVIEW",missing_inputs=base_missing,
                reason="Required solution inputs with valid values and units are not all recorded." if base_missing else "Electroneutrality, species mapping, selected phases, and database compatibility require explicit review.")
        elif tool["tool_id"].startswith("openfoam."):
            plan=plan_simple_rushton_case(record)
            if not openfoam_installed: readiness="UNAVAILABLE"; reason="OpenFOAM is not installed or reachable in the configured VM."
            elif not openfoam_template_available: readiness="UNAVAILABLE"; reason="The supported OpenFOAM template is unavailable."
            elif plan["status"]!="ready_for_review": readiness="UNSUPPORTED" if plan["status"]=="unsupported_geometry" else "MISSING_INPUT"; reason="; ".join(plan.get("unsupported_reasons",[])+plan.get("missing",[]))
            else: readiness="REQUIRES_REVIEW"; reason="Compatible inputs exist; inspect the case and approve its external VM run."
            item.update(readiness=readiness,missing_inputs=plan.get("missing",[]),reason=reason)
        else:
            item.update(readiness="MISSING_INPUT",missing_inputs=list(tool["required_inputs"]),
                reason="This tool does not yet have a typed input validator connected; related variable names are not treated as proof of readiness.")
        item["validation_gate"]=ValidationGate.validate(item)
        output.append(item)
    policy=RuleBasedDecisionPolicy()
    decision=policy.choose(state,output,goal)
    selected=next((item for item in output if item["tool_id"]==decision.get("tool_id")),None)
    prepared=ToolExecutor(registry).prepare(selected["tool_id"],selected) if selected else None
    return {"state":state,"recommendations":output,"decision":decision,"prepared_invocation":prepared,
        "notice":"This is a rule-based readiness suggestion, not a learned JEV decision and does not execute tools."}
