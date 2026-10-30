"""Conservative research-goal to durable-DAG planning.

Planning never fabricates measurements or authorizes external/chemical runs.
The returned nodes use the existing allowlisted Worker tool IDs.
"""
from __future__ import annotations

from app.services.tool_registry import RuleBasedDecisionPolicy, ScientificStateBuilder


def _action(decision: dict) -> str:
    return decision.get("action") or "ABSTAIN"


def plan_workflow(*, goal: str, record: dict, analysis_runs: list[dict],
                  openfoam_installed: bool = False,
                  openfoam_template_available: bool = False,
                  simulation_inputs: dict | None = None,
                  simulation_runs: list[dict] | None = None,
                  database_identifier: str = "phreeqc.dat",
                  process_step_id: int | None = None,
                  approval_confirmed: bool = False) -> dict:
    state = ScientificStateBuilder.build(record, analysis_runs)
    recommendation_data = __import__("app.services.tool_registry", fromlist=["recommend_tools"]).recommend_tools(
        record, analysis_runs, goal=goal, openfoam_installed=openfoam_installed,
        openfoam_template_available=openfoam_template_available)
    recommendations = recommendation_data["recommendations"]
    decision = RuleBasedDecisionPolicy().choose(state, recommendations, goal)
    selected_id = decision.get("tool_id")
    selected = next((item for item in recommendations if item["tool_id"] == selected_id), None)
    action = _action(decision)
    nodes: list[dict] = []
    missing: list[str] = []
    reasons = [decision.get("reason", "")]
    approval_required = False
    executable = False
    existing_result_id = None

    goal_text = goal.casefold()
    if any(term in goal_text for term in ("explain", "설명해", "설명 생성", "해석해줘")):
        action = "GENERATE_EXPLANATION"
        reasons = ["기록된 결과와 출처만 설명 대상으로 전달합니다. 새 분석·시뮬레이션 수치나 근거는 생성하지 않습니다."]
        nodes = []
        selected_id = None
        selected = None
    requested_modality = ("xrd" if any(term in goal_text for term in ("xrd", "diffraction", "회절", "결정상")) else
                          "afm" if any(term in goal_text for term in ("afm", "roughness", "거칠기")) else
                          "microscopy" if any(term in goal_text for term in ("sem", "tem", "microscopy", "현미경", "입자")) else None)
    # MISSING_INPUT is expected for an uploaded-but-pending source. Resolve its
    # allowlisted tool from the goal so the planner can build a gated DAG.
    if action != "GENERATE_EXPLANATION" and requested_modality and action in {"REQUEST_DATA", "ABSTAIN"}:
        selected_id = {"xrd": "xrd.local_peaks.v1", "afm": "afm.plane_level_roughness.v1",
                       "microscopy": "microscopy.otsu_components.v1"}[requested_modality]
        selected = next((item for item in recommendations if item["tool_id"] == selected_id), None)
    is_phreeqc_goal = any(term in goal_text for term in ("phreeqc", "speciation", "equilibrium", "수용액", "화학종", "포화"))
    if action != "GENERATE_EXPLANATION" and is_phreeqc_goal and not selected_id:
        selected_id = "phreeqc.aqueous_equilibrium.v1"
        selected = next((item for item in recommendations if item["tool_id"] == selected_id), None)
    if action == "RUN_DATA_VALIDATION" and selected_id == "experiment.data_quality.v1":
        nodes = [{"key": "validate_record", "tool_id": "experiment.data_quality.v1", "depends_on": [], "inputs": {}}]
        executable = True
    elif selected_id and selected_id.startswith(("xrd.", "afm.", "microscopy.")):
        modality = "xrd" if selected_id.startswith("xrd.") else "afm" if selected_id.startswith("afm.") else None
        eligible = [item for item in analysis_runs if (not modality or str(item.get("modality", "")).lower() == modality)
                    and (modality is not None or str(item.get("modality", "")).lower() in {"sem", "tem"})
                    and not item.get("demo")]
        pending = [item for item in eligible if item.get("analysis_status") not in {"completed", "COMPLETED"}]
        completed = [item for item in eligible if item.get("analysis_status") in {"completed", "COMPLETED"}]
        if pending:
            run = pending[-1]
            result = run.get("result") or {}
            provenance = result.get("provenance") or {}
            settings = provenance.get("parameters") or {}
            if modality == "xrd" and settings.get("xrd_x_unit") not in {"2theta_deg", "d_angstrom", "q_angstrom^-1"}:
                missing.append("XRD 원본 x축 단위(2θ°, d-spacing Å 또는 q Å⁻¹)")
            if modality in {"sem", "tem"} and not settings.get("pixel_size_nm"):
                missing.append("SEM/TEM 이미지의 교정된 픽셀 크기(nm/px)")
            if modality == "afm" and not settings.get("afm_height_unit"):
                missing.append("AFM 높이 축 단위")
            tool = {"xrd": "xrd.local_peaks.v1", "afm": "afm.plane_level_roughness.v1"}.get(modality, "microscopy.otsu_components.v1")
            nodes = [
                {"key": "validate_record", "tool_id": "experiment.data_quality.v1", "depends_on": [], "inputs": {}},
                {"key": "analyze_measurement", "tool_id": tool, "depends_on": ["validate_record"],
                 "inputs": {"analysis_run_id": run["id"], "settings": settings}},
            ]
            if not missing:
                action = "RUN_ANALYSIS"
                executable = True
                reasons.append("업로드된 원본 분석 파일과 기록된 장비 설정을 연결해 기존 Worker 분석 DAG를 구성했습니다.")
        elif completed:
            action = "REVIEW_RESULT"
            reasons = ["요청한 모달리티의 계산 결과가 이미 있습니다. 기존 결과와 출처를 연구자가 검토하도록 보류합니다."]
            nodes = []
        else:
            action = "REQUEST_DATA"
            missing.append({"xrd": "XRD 원본 회절 파일", "afm": "교정된 AFM 높이맵 원본 파일"}.get(modality, "교정 정보가 포함된 SEM/TEM 원본 이미지"))
            nodes = []
            reasons = ["Topic과 실험 범위에서 사용 가능한 비데모 원본 측정 실행을 찾지 못했습니다. 파일을 먼저 등록해야 합니다."]
    elif action != "GENERATE_EXPLANATION" and (bool(selected_id and selected_id.startswith("phreeqc.")) or is_phreeqc_goal):
        # PHREEQC inputs are supplied explicitly in analytical molality; never
        # derive dissolved totals or charge balance from a recipe.
        approval_required = True
        if database_identifier != "phreeqc.dat":
            action = "ABSTAIN"
            missing = [f"지원하지 않는 PHREEQC 데이터베이스: {database_identifier}"]
            reasons = ["현재 실행 adapter는 phreeqc.dat만 지원합니다. 다른 데이터베이스를 자동 대체하지 않습니다."]
        elif not simulation_inputs:
            action = "REQUEST_DATA"
            missing = ["분석 총량(totals_molal; 원소별 mol/kgw)", "고정 pH", "온도(°C)", "비교할 고체상 목록(선택)"]
            reasons = ["기록된 시약 투입량만으로 용존 원소 총량·용해율·전하 균형을 추정하지 않습니다."]
        else:
            from app.services.tool_adapters import PHREEQCAdapter
            is_sweep = "pH_min" in simulation_inputs or "pH_max" in simulation_inputs
            phreeqc_tool_id = "phreeqc.aqueous_sweep.v1" if is_sweep else "phreeqc.aqueous_equilibrium.v1"
            try:
                checked = PHREEQCAdapter(sweep=is_sweep).validate_inputs(simulation_inputs)
                from app.services.simulation.phreeqc import ELEMENT_TOTALS
                unsupported = sorted(set(checked["totals_molal"]) - ELEMENT_TOTALS)
                if unsupported:
                    raise ValueError(f"지원하지 않는 원소 총량: {', '.join(unsupported)}")
            except Exception as exc:
                action = "ABSTAIN"
                missing = [str(exc)]
                reasons = ["입력이 현재 PHREEQC adapter의 검증 계약을 통과하지 못했습니다."]
            else:
                selected_id = phreeqc_tool_id
                from app.services.simulation.cache import phreeqc_cache_identity
                from app.services.tool_registry import ToolRegistry
                definition=ToolRegistry().get(phreeqc_tool_id)
                expected_key,_=phreeqc_cache_identity(tool_id=phreeqc_tool_id,tool_version=definition.version,
                    topic_id=int(record["topic_id"]),experiment_id=int(record["id"]),process_step_id=process_step_id,parameters=checked)
                cached=next((run for run in (simulation_runs or []) if run.get("idempotency_key")==expected_key and run.get("status")=="completed"),None)
                if cached:
                    action="REVIEW_RESULT"
                    existing_result_id=cached["id"]
                    reasons=["동일한 Topic·실험·단계·입력·도구·데이터베이스의 완료 계산이 있습니다. 새 실행 대신 기존 결과와 계보를 검토하도록 연결합니다."]
                else:
                    nodes = [
                        {"key": "validate_record", "tool_id": "experiment.data_quality.v1", "depends_on": [], "inputs": {}},
                        {"key": "phreeqc_simulation", "tool_id": phreeqc_tool_id, "depends_on": ["validate_record"],
                         "inputs": {"inputs": checked, "process_step_id": process_step_id}},
                    ]
                    if approval_confirmed:
                        action = "RUN_SIMULATION"
                        executable = True
                        reasons = ["사용자가 입력한 분석 총량·온도·pH를 PHREEQC Worker DAG로 전달합니다."]
                    else:
                        action = "REQUIRES_REVIEW"
                        executable = False
                        reasons = ["입력값과 데이터베이스 적합성을 검토하고 명시적으로 승인하면 실행할 수 있습니다."]
    elif any(term in goal_text for term in ("openfoam", "cfd", "유동", "유체", "혼합 유동")):
        action = "ABSTAIN"
        reasons = ["현재 선택된 목표에 실행 가능한 승인된 CFD 계획이 없습니다. 지원 기하학·격자·물성·VM 상태와 별도 승인이 필요합니다."]
        missing = ["지원 형상의 검토된 CFD 케이스", "사용자 명시 실행 승인"]
    elif action == "REVIEW_RESULT":
        executable = False
    elif action == "GENERATE_EXPLANATION":
        executable = False
    elif action == "REQUEST_DATA":
        missing = list(selected.get("missing_inputs", [])) if selected else ["연구 목표에 맞는 입력 자료"]
    else:
        action = "ABSTAIN"
        reasons = ["요청을 기존 allowlist 도구와 안전하게 연결할 수 없어 실행 계획을 만들지 않았습니다."]

    if action != "GENERATE_EXPLANATION" and selected and selected.get("readiness") in {"UNSUPPORTED", "UNAVAILABLE"}:
        action = "ABSTAIN"
        executable = False
        nodes = []
        reasons = [selected.get("reason", "지원되지 않는 도구 또는 입력입니다.")]

    return {
        "action": action,
        "topic_id": record.get("topic_id"),
        "experiment_id": record.get("id"),
        "goal": goal,
        "nodes": nodes,
        "dependencies": [{"node": node["key"], "depends_on": node["depends_on"]} for node in nodes],
        "selected_tool_id": selected_id if action in {"RUN_ANALYSIS", "RUN_SIMULATION", "RUN_DATA_VALIDATION", "REQUIRES_REVIEW"} else None,
        "reasons": [reason for reason in reasons if reason],
        "missing_inputs": missing,
        "estimated_resources": {"execution_mode": "local durable Worker" if executable else "not scheduled",
                                 "timeout_seconds": 300 if executable else None,
                                 "memory_estimate": None},
        "approval_required": approval_required,
        "approval_confirmed": approval_confirmed,
        "existing_result_id": existing_result_id,
        "executable": executable,
        "decision_policy": "RuleBasedDecisionPolicy",
        "scientific_state": state,
        "notice": "계획 생성은 실행 승인이 아닙니다. 수치·시료·출처를 추정하지 않으며 미지원 요청은 보류합니다.",
    }
