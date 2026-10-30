from app.services.workflow_planner import plan_workflow


def _record():
    return {"id": 7, "topic_id": 3, "demo": False, "status": "planned", "steps": [], "materials": [], "results": []}


def test_goal_without_measurement_requests_original_data_without_fake_execution():
    plan = plan_workflow(goal="XRD 회절 피크 분석", record=_record(), analysis_runs=[])
    assert plan["action"] == "REQUEST_DATA"
    assert not plan["executable"]
    assert "XRD 원본 회절 파일" in plan["missing_inputs"]
    assert plan["nodes"] == []


def test_pending_xrd_file_generates_existing_worker_dag():
    run = {"id": 11, "modality": "xrd", "analysis_status": "pending", "demo": False,
           "result": {"provenance": {"parameters": {"xrd_x_unit": "2theta_deg"}}}}
    plan = plan_workflow(goal="XRD 피크 분석", record=_record(), analysis_runs=[run])
    assert plan["action"] == "RUN_ANALYSIS"
    assert plan["executable"]
    assert [node["tool_id"] for node in plan["nodes"]] == ["experiment.data_quality.v1", "xrd.local_peaks.v1"]
    assert plan["nodes"][1]["depends_on"] == ["validate_record"]
    assert plan["nodes"][1]["inputs"]["analysis_run_id"] == 11


def test_afm_plan_requests_missing_calibration_instead_of_guessing():
    run = {"id": 12, "modality": "afm", "analysis_status": "pending", "demo": False, "result": {}}
    plan = plan_workflow(goal="AFM roughness 거칠기", record=_record(), analysis_runs=[run])
    assert plan["action"] == "REQUEST_DATA"
    assert not plan["executable"]
    assert "AFM 높이 축 단위" in plan["missing_inputs"]


def test_phreeqc_plan_requests_chemical_totals_not_recipe_guess():
    plan = plan_workflow(goal="PHREEQC 수용액 화학종 평형 계산", record=_record(), analysis_runs=[])
    assert plan["action"] == "REQUEST_DATA"
    assert plan["approval_required"]
    assert not plan["executable"]
    assert any("원소별" in value for value in plan["missing_inputs"])


def test_phreeqc_plan_requires_review_then_builds_approved_dag():
    inputs={"temperature_c":25,"pH":8.3,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"]}
    pending=plan_workflow(goal="PHREEQC 수용액 평형 계산",record=_record(),analysis_runs=[],simulation_inputs=inputs)
    assert pending["action"]=="REQUIRES_REVIEW"
    assert not pending["executable"]
    assert pending["nodes"][1]["tool_id"]=="phreeqc.aqueous_equilibrium.v1"
    approved=plan_workflow(goal="PHREEQC 수용액 평형 계산",record=_record(),analysis_runs=[],simulation_inputs=inputs,approval_confirmed=True)
    assert approved["action"]=="RUN_SIMULATION"
    assert approved["executable"]
    assert approved["nodes"][1]["inputs"]["inputs"]==inputs


def test_phreeqc_planner_abstains_on_unavailable_database_or_unsupported_species():
    inputs={"temperature_c":25,"pH":8,"totals_molal":{"Ca":0.001},"phases":[]}
    unsupported_db=plan_workflow(goal="PHREEQC equilibrium",record=_record(),analysis_runs=[],simulation_inputs=inputs,database_identifier="unsupported.dat")
    unsupported_species=plan_workflow(goal="PHREEQC equilibrium",record=_record(),analysis_runs=[],simulation_inputs={**inputs,"totals_molal":{"Xx":1}})
    assert unsupported_db["action"]=="ABSTAIN"
    assert unsupported_species["action"]=="ABSTAIN"


def test_phreeqc_planner_builds_explicit_pH_sweep_tool():
    inputs={"temperature_c":25,"totals_molal":{"Ca":0.001,"C(4)":0.001},"phases":["Calcite"],
        "pH_min":6,"pH_max":10,"points":5}
    plan=plan_workflow(goal="PHREEQC pH sweep 수용액",record=_record(),analysis_runs=[],simulation_inputs=inputs,approval_confirmed=True)
    assert plan["action"]=="RUN_SIMULATION"
    assert plan["nodes"][1]["tool_id"]=="phreeqc.aqueous_sweep.v1"


def test_phreeqc_planner_surfaces_matching_completed_result_without_reexecution():
    from app.services.simulation.cache import phreeqc_cache_identity
    from app.services.tool_adapters import PHREEQCAdapter
    from app.services.tool_registry import ToolRegistry
    inputs=PHREEQCAdapter().validate_inputs({"temperature_c":25,"pH":8,"totals_molal":{"Ca":0.001},"phases":[]})
    tool=ToolRegistry().get("phreeqc.aqueous_equilibrium.v1")
    key,_=phreeqc_cache_identity(tool_id=tool.tool_id,tool_version=tool.version,topic_id=3,experiment_id=7,process_step_id=None,parameters=inputs)
    plan=plan_workflow(goal="PHREEQC aqueous speciation",record=_record(),analysis_runs=[],simulation_inputs=inputs,
        simulation_runs=[{"id":42,"status":"completed","idempotency_key":key}])
    assert plan["action"]=="REVIEW_RESULT"
    assert plan["existing_result_id"]==42
    assert plan["nodes"]==[] and not plan["executable"]


def test_unapproved_cfd_goal_abstains():
    plan = plan_workflow(goal="OpenFOAM CFD 유동 해석", record=_record(), analysis_runs=[])
    assert plan["action"] == "ABSTAIN"
    assert not plan["executable"]
    assert plan["nodes"] == []


def test_validation_goal_builds_read_only_data_quality_dag():
    plan = plan_workflow(goal="검증하고 누락 단위 확인", record=_record(), analysis_runs=[])
    assert plan["action"] == "RUN_DATA_VALIDATION"
    assert plan["executable"]
    assert plan["nodes"][0]["tool_id"] == "experiment.data_quality.v1"


def test_explanation_goal_does_not_schedule_analysis_or_simulation():
    plan = plan_workflow(goal="기록된 결과 설명해줘", record=_record(), analysis_runs=[])
    assert plan["action"] == "GENERATE_EXPLANATION"
    assert not plan["executable"]
    assert plan["nodes"] == []
