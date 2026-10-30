from app.services.simulation.readiness import assess_simulation_inputs


def _record(variables):
    return {
        "id": 100,
        "code": "EXP-TEST",
        "steps": [{"name": "Mixing", "variables": variables}],
        "materials": [],
    }


def test_openfoam_readiness_rejects_vague_geometry_and_incompatible_units():
    report = assess_simulation_inputs(_record([
        {"name": "liquid_volume", "value": "250", "unit": "mL"},
        {"name": "vessel_geometry", "value": "cylindrical vessel", "unit": None},
        {"name": "impeller_geometry", "value": "unknown", "unit": None},
        {"name": "stirring_speed", "value": "300", "unit": "kg"},
        {"name": "fluid_density", "value": "1000", "unit": "rpm"},
        {"name": "fluid_viscosity", "value": "1", "unit": "g/cm3"},
    ]))

    checks = {item["key"]: item for item in report["groups"][1]["checks"]}
    assert checks["liquid_volume"]["present"] is True
    assert checks["vessel_geometry"]["present"] is False
    assert checks["vessel_geometry"]["reason"] == "recorded_but_not_usable"
    assert checks["vessel_geometry"]["recorded_value"] == "cylindrical vessel"
    assert checks["impeller_geometry"]["present"] is False
    assert checks["stirring_speed"]["present"] is False
    assert checks["fluid_density"]["present"] is False
    assert checks["fluid_viscosity"]["present"] is False


def test_openfoam_readiness_accepts_measured_dimensions_and_supported_units():
    report = assess_simulation_inputs(_record([
        {"name": "liquid_volume", "value": "250", "unit": "mL"},
        {"name": "vessel_geometry", "value": "inner diameter 80 mm; height 120 mm", "unit": None},
        {"name": "impeller_geometry", "value": "4-blade propeller, diameter 30 mm", "unit": None},
        {"name": "stirring_speed", "value": "300", "unit": "rpm"},
        {"name": "fluid_density", "value": "1.00", "unit": "g/cm³"},
        {"name": "fluid_viscosity", "value": "1.00", "unit": "mPa·s"},
    ]))

    checks = {item["key"]: item for item in report["groups"][1]["checks"]}
    assert all(checks[key]["present"] for key in checks)


def test_openfoam_readiness_accepts_si_inverse_seconds_notation():
    report = assess_simulation_inputs(_record([
        {"name": "stirring_speed", "value": "5", "unit": "s⁻¹"},
    ]))
    checks = {item["key"]: item for item in report["groups"][1]["checks"]}
    assert checks["stirring_speed"]["present"] is True
