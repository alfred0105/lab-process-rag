"""Small, deterministic, labeled evaluation set for the RuleBased baseline."""
from __future__ import annotations

from collections import Counter

from app.services.workflow_planner import plan_workflow


def _record():
    return {"id": 70, "topic_id": 30, "demo": False, "status": "planned",
            "steps": [], "materials": [], "results": []}


def _cases():
    cases = []
    cases.extend((goal, "ABSTAIN", None, "unsupported") for goal in [
        "OpenFOAM CFD 유동 해석", "Run CFD with OpenFOAM", "혼합 유동을 CFD로 계산",
        "OpenFOAM flow field for vessel", "지원되지 않는 CFD 계산을 시작"])
    cases.extend((goal, "GENERATE_EXPLANATION", None, "explanation") for goal in [
        "Explain the recorded outcome", "기록 결과를 설명해줘", "해석해줘 저장된 측정 결과",
        "설명 생성: 관측된 값과 출처", "Explain measured peaks without new claims"])
    cases.extend((goal, "RUN_DATA_VALIDATION", "experiment.data_quality.v1", "ready") for goal in [
        "validate process record", "공정 기록 검증", "Check missing units", "조건 누락 확인",
        "실험 기록의 단위 검사"])
    cases.extend((goal, "REQUEST_DATA", None, "missing") for goal in [
        "XRD 회절 분석", "Analyze XRD diffraction", "AFM roughness 거칠기", "SEM image segmentation",
        "TEM particle image", "PHREEQC 수용액 화학종", "aqueous equilibrium speciation",
        "분석할 측정 파일이 없음 XRD", "AFM 표면 분석", "현미경 이미지 분석"])
    cases.extend((goal, "ABSTAIN", None, "unknown") for goal in [
        "새로운 재료 성능을 개선하고 싶음", "Which experiment should I do next?",
        "Predict the exact nanorod length", "Tell me if synthesis will succeed",
        "Optimize everything automatically"])
    return cases


def _pending(modality, settings):
    return [{"id": 100 + len(modality), "modality": modality, "analysis_status": "pending", "demo": False,
             "result": {"provenance": {"parameters": settings}}}]


def test_planner_labeled_evaluation_has_no_false_ready_and_rejects_unsupported_tools():
    cases = _cases()
    assert len(cases) >= 30
    metrics = Counter()
    for goal, expected_action, expected_tool, group in cases:
        plan = plan_workflow(goal=goal, record=_record(), analysis_runs=[])
        metrics["total"] += 1
        metrics["action_correct"] += plan["action"] == expected_action
        metrics["false_ready"] += plan["executable"] and expected_action not in {"RUN_DATA_VALIDATION"}
        if expected_action == "REQUEST_DATA":
            metrics["missing_cases"] += 1
            metrics["missing_detected"] += bool(plan["missing_inputs"])
        if group == "unsupported":
            metrics["unsupported_cases"] += 1
            metrics["unsupported_rejected"] += plan["action"] == "ABSTAIN" and not plan["nodes"] and not plan["executable"]
        if expected_tool:
            metrics["expected_tool_cases"] += 1
            metrics["tool_correct"] += plan["selected_tool_id"] == expected_tool

    assert metrics["action_correct"] == metrics["total"]
    assert metrics["false_ready"] == 0
    assert metrics["missing_detected"] == metrics["missing_cases"]
    assert metrics["unsupported_rejected"] == metrics["unsupported_cases"]
    assert metrics["tool_correct"] == metrics["expected_tool_cases"]


def test_planner_tool_selection_accuracy_for_pending_measurement_modalities():
    evaluations = [
        ("Analyze XRD peaks", "xrd", {"xrd_x_unit": "2theta_deg"}, "xrd.local_peaks.v1"),
        ("XRD 회절 피크 검출", "xrd", {"xrd_x_unit": "q_angstrom^-1"}, "xrd.local_peaks.v1"),
        ("AFM roughness", "afm", {"afm_height_unit": "nm"}, "afm.plane_level_roughness.v1"),
        ("AFM 거칠기 분석", "afm", {"afm_height_unit": "um"}, "afm.plane_level_roughness.v1"),
        ("SEM image segmentation", "sem", {"pixel_size_nm": 2.0}, "microscopy.otsu_components.v1"),
        ("TEM 현미경 객체 분할", "tem", {"pixel_size_nm": 5.0}, "microscopy.otsu_components.v1"),
    ]
    correct = 0
    false_ready = 0
    for goal, modality, settings, expected_tool in evaluations:
        plan = plan_workflow(goal=goal, record=_record(), analysis_runs=_pending(modality, settings))
        correct += plan["selected_tool_id"] == expected_tool and plan["action"] == "RUN_ANALYSIS"
        false_ready += plan["executable"] and not plan["nodes"]
    assert correct == len(evaluations)
    assert false_ready == 0
