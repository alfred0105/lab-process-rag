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
