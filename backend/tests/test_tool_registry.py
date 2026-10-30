from app.services.tool_registry import ToolRegistry, ValidationGate, recommend_tools


def test_registry_lists_existing_tools_and_marks_unmeasured_resources_unknown():
    result=ToolRegistry().list()
    ids={item["tool_id"] for item in result}
    assert {"xrd.local_peaks.v1","xrd.cod_phase_candidates.v1","afm.plane_level_roughness.v1",
        "microscopy.otsu_components.v1","phreeqc.aqueous_equilibrium.v1","phreeqc.aqueous_sweep.v1",
        "openfoam.simpleRushtonMRF.v1","hydrothermal.water_state.v1","coating.spin_coating.v1",
        "experiment.compare.v1","experiment.data_quality.v1"}.issubset(ids)
    assert all(item["estimated_runtime_seconds"] is None and item["estimated_memory_mb"] is None for item in result)


def test_tool_selection_does_not_claim_phreeqc_predicts_material_growth():
    result=recommend_tools({"id":1,"topic_id":4,"method_version_id":2,"demo":False,"status":"in_progress",
        "steps":[{"name":"Growth","order_index":1,"variables":[{"name":"pH","value":"9","unit":"pH"},{"name":"temperature","value":"90","unit":"°C"}]}],"materials":[],"results":[]},[])
    phreeqc=next(item for item in result["recommendations"] if item["tool_id"]=="phreeqc.aqueous_equilibrium.v1")
    assert phreeqc["readiness"]=="MISSING_INPUT"
    assert "identified dissolved-element totals with concentration units" in phreeqc["missing_inputs"]
    assert result["decision"]["action"] in {"REQUEST_DATA","ABSTAIN"}
    assert "not a learned JEV" in result["notice"]


def test_validation_gate_never_executes_a_review_required_model():
    result=ValidationGate.validate({"readiness":"READY","execution_policy":"human_approval_and_external_vm_required"})
    assert result["allowed"] is False
    assert result["requires_human_approval"] is True

def test_phreeqc_registry_does_not_trust_variable_names_without_values_and_units():
    record={"id":1,"demo":False,"steps":[{"name":"Mix","order_index":0,"variables":[
        {"name":"pH","value":"unknown","unit":"pH"},{"name":"temperature","value":"25","unit":"rpm"},
        {"name":"Zn concentration","value":"0.1","unit":""}]}],"materials":[],"results":[]}
    result=recommend_tools(record,[],goal="aqueous equilibrium")
    phreeqc=next(item for item in result["recommendations"] if item["tool_id"]=="phreeqc.aqueous_equilibrium.v1")
    assert phreeqc["readiness"]=="MISSING_INPUT"
    assert len(phreeqc["missing_inputs"])==3

def test_registry_reports_completed_analysis_and_policy_avoids_duplicate():
    record={"id":1,"demo":False,"steps":[],"materials":[],"results":[]}
    runs=[{"id":4,"modality":"xrd","tool_id":"xrd.local_peaks.v1","analysis_status":"completed","result":{"observed_peaks":[{"x":30,"intensity":1}]}}]
    result=recommend_tools(record,runs,goal="xrd peaks")
    peak=next(item for item in result["recommendations"] if item["tool_id"]=="xrd.local_peaks.v1")
    assert peak["readiness"]=="ALREADY_ANALYZED"
    assert result["decision"]["action"]=="ABSTAIN"

def test_data_quality_requires_explicit_goal_and_uses_distinct_action():
    record={"id":1,"demo":False,"steps":[],"materials":[],"results":[]}
    automatic=recommend_tools(record,[])
    requested=recommend_tools(record,[],goal="단위 검증")
    assert automatic["decision"]["tool_id"] is None
    assert requested["decision"]["action"]=="RUN_DATA_VALIDATION"

def test_result_validator_rejects_non_finite_and_checks_phreeqc_provenance():
    from app.services.tool_registry import ResultValidator
    tool=ToolRegistry().get("phreeqc.aqueous_equilibrium.v1")
    assert not ResultValidator.validate(tool,{"model_id":"PHREEQC-3","input_pH":7,"aqueous_species":[],"saturation_indices":[],"x":float("nan")})["valid"]
    assert not ResultValidator.validate(tool,{"saturation_indices":[]})["valid"]
    assert ResultValidator.validate(tool,{"model_id":"PHREEQC-3 / phreeqc.dat","input_pH":7,"aqueous_species":[],"saturation_indices":[],"limitations":[]})["valid"]
    assert ResultValidator.validate(tool,{"model_id":"PHREEQC-3 / phreeqc.dat","input_pH":7,"calculated_pH":18,"aqueous_species":[],"saturation_indices":[],"limitations":[]})["valid"]
    assert not ResultValidator.validate(tool,{"model_id":"PHREEQC-3 / phreeqc.dat","input_pH":7,"calculated_pH":float("inf"),"aqueous_species":[],"saturation_indices":[],"limitations":[]})["valid"]
    assert not ResultValidator.validate(tool,{"model_id":"PHREEQC-3 / phreeqc.dat","input_pH":7,"aqueous_species":[{"name":"Zn+2","molality":-1}],"saturation_indices":[],"limitations":[]})["valid"]

def test_openfoam_result_requires_normal_solver_end_and_monotone_finite_trace():
    from app.services.tool_registry import ResultValidator
    tool=ToolRegistry().get("openfoam.simpleRushtonMRF.v1")
    row={"time_s":0,"divStressU":0,"divStressDotU":0,"stressDDotGradU":0,"divPU":0,"gradPU":0,"pDivU":0,"divTauU":0,"divTauDotU":0,"tauDDotGradU":0}
    valid={"solver_completed_marker":"End","mesh_cell_count":1000,"mesh_validation":"CHECKMESH_OK",
           "solver_converged":True,"final_residuals":[1e-5,2e-5],"power_trace":[row,{**row,"time_s":1}]}
    assert ResultValidator.validate(tool,valid)["valid"]
    assert not ResultValidator.validate(tool,{**valid,"solver_completed_marker":""})["valid"]
    assert not ResultValidator.validate(tool,{**valid,"power_trace":[row,{**row,"time_s":0}]})["valid"]

def test_tool_executor_runs_fresh_gate_after_prepare_and_before_execute():
    from app.services.tool_registry import ToolExecutor
    events=[]
    class Adapter:
        tool_id="example"
        def validate_inputs(self,inputs): events.append("validate"); return inputs
        def prepare(self,inputs): events.append("prepare"); return inputs
        def execute(self,inputs): events.append("execute"); return {"ok":True}
        def validate_outputs(self,output): events.append("validate_output"); return {"valid":True}
        def persist(self,output,callback): events.append("persist"); return callback(output)
    class Registry:
        def get(self,_tool_id): return object()
    result=ToolExecutor(Registry()).execute_adapter(Adapter(),{},lambda output:"saved",before_execute=lambda *_:events.append("fresh_gate"))
    assert result=="saved"
    assert events==["validate","prepare","fresh_gate","execute","validate_output","persist"]

def test_reference_and_demo_source_classification_is_not_lab_data():
    from types import SimpleNamespace
    from app.main import classify_observation_source
    reference=SimpleNamespace(status="reference",demo=False)
    actual=SimpleNamespace(status="success",demo=False)
    demo=SimpleNamespace(status="success",demo=True)
    literature_variable=SimpleNamespace(source_type="literature")
    assert classify_observation_source(reference,is_result=True)=="LITERATURE"
    assert classify_observation_source(actual,literature_variable)=="LITERATURE"
    assert classify_observation_source(actual,is_result=True)=="LAB_RESULT"
    assert classify_observation_source(demo,is_result=True)=="SYNTHETIC_DEMO"
