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
    assert "dissolved totals" in phreeqc["missing_inputs"]
    assert result["decision"]["action"]=="GENERATE_EXPLANATION"
    assert "not a learned JEV" in result["notice"]


def test_validation_gate_never_executes_a_review_required_model():
    result=ValidationGate.validate({"readiness":"READY","execution_policy":"human_approval_and_external_vm_required"})
    assert result["allowed"] is False
    assert result["requires_human_approval"] is True
