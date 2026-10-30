import pytest

from app.services.simulation.ph import estimate_solution_ph


def test_phreeqc_matches_usgs_example_2_pure_water_gypsum_anhydrite_case():
    """Match the published first 25 C reaction step in USGS PHREEQC Example 2."""
    from phreeqpython import PhreeqPython

    engine = PhreeqPython(database="phreeqc.dat")
    engine.ip.run_string(
        """SOLUTION 1 Pure water
            pH 7.0
            temp 25.0
        EQUILIBRIUM_PHASES 1
            Gypsum 0.0 1.0
            Anhydrite 0.0 1.0
        SELECTED_OUTPUT 1
            -reset false
            -si anhydrite gypsum
        END
        """
    )
    rows = engine.ip.get_selected_output_array()
    # The final row is the batch-reaction result; the USGS table reports
    # anhydrite SI=-0.30 and gypsum SI=0.00 at 25 C (rounded to 0.01).
    assert rows[-1][0] == pytest.approx(-0.30, abs=0.01)
    assert rows[-1][1] == pytest.approx(0.00, abs=0.01)


def test_strong_acid_stock_dose_includes_dilution_volume():
    result = estimate_solution_ph(100, [{"species": "HCl", "concentration_mol_l": 0.1, "volume_ml": 1}])
    assert result["estimated_ph"] == pytest.approx(3.0043, abs=0.001)
    assert result["total_volume_ml"] == pytest.approx(101)
    assert result["status"] == "ESTIMATE_ONLY"


def test_neutralized_strong_acid_and_base_returns_neutral_water():
    result = estimate_solution_ph(100, [
        {"species": "HCl", "amount_mmol": 1},
        {"species": "NaOH", "amount_mmol": 1},
    ])
    assert result["estimated_ph"] == pytest.approx(7, abs=0.001)


def test_weak_acid_and_weak_base_have_expected_direction():
    acid = estimate_solution_ph(100, [{"species": "CH3COOH", "concentration_mol_l": 0.1, "volume_ml": 10}])
    base = estimate_solution_ph(100, [{"species": "NH3", "concentration_mol_l": 0.1, "volume_ml": 10}])
    assert acid["estimated_ph"] < 7
    assert base["estimated_ph"] > 7


def test_phreeqc_calculation_records_exact_database_fingerprint():
    from app.services.simulation.phreeqc import calculate_aqueous_equilibrium

    result = calculate_aqueous_equilibrium(
        temperature_c=25, pH=7, totals_molal={"Ca": 0.001, "C(4)": 0.001}, phases=["Calcite"]
    )
    assert result["engine"] == "PHREEQC-3"
    assert result["adapter_version"]
    assert result["database"] == "phreeqc.dat"
    assert len(result["database_sha256"]) == 64


def test_bicarbonate_uses_counterion_and_carbonate_equilibria():
    result = estimate_solution_ph(100, [{"species": "NaHCO3", "concentration_mol_l": 0.1, "volume_ml": 10}])
    assert 8.0 < result["estimated_ph"] < 8.6


def test_unsupported_reagent_is_rejected_instead_of_guessed():
    with pytest.raises(ValueError, match="not in the supported list"):
        estimate_solution_ph(100, [{"species": "Zn(NO3)2", "amount_mmol": 1}])


def test_missing_stock_volume_is_rejected():
    with pytest.raises(ValueError, match="requires both concentration and added volume"):
        estimate_solution_ph(100, [{"species": "HCl", "concentration_mol_l": 0.1}])


def test_pure_sodium_hydroxide_mass_is_converted_to_amount():
    result = estimate_solution_ph(100, [{"species": "NaOH", "mass_g": 0.004}])
    assert result["reagents"][0]["amount_mmol"] == pytest.approx(0.1, abs=0.001)
    assert result["estimated_ph"] == pytest.approx(11.0, abs=0.03)
