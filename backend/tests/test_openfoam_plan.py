from app.services.simulation.openfoam import plan_simple_rushton_case
from app.services.simulation.openfoam_runner import parse_power_trace, parse_solver_log, probe_openfoam_installation
from app.schemas.core import IntegratedAnalysisClaim, IntegratedAnalysisRequest
from pydantic import ValidationError
import pytest


def _record(variables):
    return {"id": 71, "code": "EXP-071", "steps": [{"name": "Mixing", "variables": variables}]}


def test_openfoam_plan_maps_a_compatible_record_to_si_without_claiming_it_ran():
    plan = plan_simple_rushton_case(_record([
        {"name": "vessel_geometry", "value": "closed fully filled baffled cylindrical vessel, diameter 100 mm, height 120 mm"},
        {"name": "impeller_geometry", "value": "6-blade Rushton turbine, diameter 30 mm"},
        {"name": "stirring_speed", "value": "300", "unit": "rpm"},
        {"name": "liquid_volume", "value": "942", "unit": "mL"},
        {"name": "fluid_density", "value": "1", "unit": "g/cm3"},
        {"name": "fluid_viscosity", "value": "1", "unit": "mPa·s"},
    ]))

    assert plan["status"] == "ready_for_review"
    assert plan["compatible"] is True
    assert plan["missing"] == []
    checks = {item["key"]: item for item in plan["checks"]}
    assert checks["cylindrical_tank_diameter"]["value_si"] == 0.1
    assert checks["cylindrical_tank_height"]["value_si"] == 0.12
    assert checks["stirring_speed"]["value_si"] == 300
    assert checks["fluid_density"]["value_si"] == 1000
    assert checks["kinematic_viscosity"]["value_si"] == 1e-6
    assert "do not predict concentration homogenization time" in " ".join(plan["limitations"])


def test_openfoam_plan_rejects_an_impeller_the_template_does_not_support():
    plan = plan_simple_rushton_case(_record([
        {"name": "vessel_geometry", "value": "open baffled tank, diameter 100 mm, height 120 mm"},
        {"name": "impeller_geometry", "value": "4-blade pitched paddle, diameter 30 mm"},
    ]))

    assert plan["status"] == "unsupported_geometry"
    assert plan["compatible"] is False
    assert "closed_fully_filled_vessel" in plan["missing"]


def test_openfoam_plan_identifies_magnetic_stir_bar_as_a_separate_unsupported_case():
    plan = plan_simple_rushton_case(_record([
        {"name": "vessel_geometry", "value": "100 mm diameter glass beaker"},
        {"name": "magnetic_stir_bar", "value": "PTFE magnetic stir bar, 30 mm long"},
        {"name": "stirring_speed", "value": "400", "unit": "rpm"},
    ]))

    assert plan["status"] == "unsupported_geometry"
    assert any("magnetic stir bar" in reason for reason in plan["unsupported_reasons"])
    assert any("not a magnetic stir bar" in limitation for limitation in plan["limitations"])


def test_openfoam_power_trace_parser_keeps_named_finite_solver_values():
    trace = parse_power_trace("""# Domain-integrated power [x 1e-09]
# Time divStressU divStressDotU stressDDotGradU divPU gradPU pDivU divTauU divTauDotU tauDDotGradU
0 0 0 0 0 0 0 0 0 0
10 3233.09286528 899.85509017 2333.23777511 3210.69244947 2543.2279744 667.46447507 22.40041581 -1643.37288423 1665.77330004
bad row
""")

    assert len(trace) == 2
    assert trace[1]["time_s"] == 10
    assert trace[1]["divStressU"] == 3233.09286528
    assert trace[1]["divTauDotU"] == -1643.37288423


def test_openfoam_log_fixture_matrix_distinguishes_solver_evidence():
    good = "cells: 1200 cells\nMesh OK.\nFinal residual = 2e-5\nFinal residual = 8e-5\n"
    assert parse_solver_log(good, returncode=0, solver_end="End")["valid"] is True
    unconverged = parse_solver_log("cells: 1200 cells\nMesh OK.\nFinal residual = 0.2\n", returncode=0, solver_end="End")
    assert unconverged["solver_converged"] is False and unconverged["valid"] is False
    bad_mesh = parse_solver_log("cells: 1200 cells\nFailed 2 mesh checks\nFinal residual = 2e-5\n", returncode=0, solver_end="End")
    assert bad_mesh["mesh_validation"] == "UNVERIFIED" and not bad_mesh["valid"]
    crashed = parse_solver_log(good, returncode=9, solver_end="FOAM FATAL ERROR")
    assert crashed["solver_completed_marker"] is None and not crashed["valid"]
    truncated = parse_solver_log("cells: 1200 cells\nMesh OK.\n", returncode=0, solver_end="")
    assert truncated["solver_completed_marker"] is None and not truncated["valid"]
    missing_evidence = parse_solver_log("", returncode=0, solver_end="End")
    assert missing_evidence["mesh_cell_count"] is None and not missing_evidence["valid"]


def test_integrated_analysis_claims_keep_simulation_outputs_distinct_from_measurements():
    claim = IntegratedAnalysisClaim(claim="The model output shows a higher integrated power term.", status="SIMULATION_OUTPUT", simulation_run_refs=[9])
    assert claim.simulation_run_refs == [9]
    with pytest.raises(ValidationError):
        IntegratedAnalysisClaim(claim="A measurement increased.", status="SIMULATION_OUTPUT")
    with pytest.raises(ValidationError):
        IntegratedAnalysisClaim(claim="Measurement output.", status="ANALYSIS_OUTPUT", analysis_run_refs=[3], simulation_run_refs=[9])


def test_integrated_analysis_request_accepts_simulation_run_ids():
    request = IntegratedAnalysisRequest(simulation_run_ids=[9], goal="Explain the model result alongside the records.")
    assert request.simulation_run_ids == [9]


def test_openfoam_probe_checks_actual_runner_template(monkeypatch):
    import subprocess
    calls=[]
    def fake_run(args, timeout=40):
        calls.append(args)
        if "foamRun -help" in args[-1]:
            return subprocess.CompletedProcess(args,0,"Usage: foamRun","")
        return subprocess.CompletedProcess(args,0,"","")
    monkeypatch.setattr("app.services.simulation.openfoam_runner._run",fake_run)
    result=probe_openfoam_installation("test-vm")
    assert result == {"installed":True,"version":"14","template_available":True}
    assert "simpleRushtonMRF" in calls[1][-1]
    assert "mixerVessel2DMRF" not in calls[1][-1]


def test_openfoam_probe_does_not_report_template_when_missing(monkeypatch):
    import subprocess
    def fake_run(args, timeout=40):
        if "foamRun -help" in args[-1]:
            return subprocess.CompletedProcess(args,0,"Usage: foamRun","")
        return subprocess.CompletedProcess(args,1,"","")
    monkeypatch.setattr("app.services.simulation.openfoam_runner._run",fake_run)
    result=probe_openfoam_installation("test-vm")
    assert result["installed"] is True
    assert result["template_available"] is False
