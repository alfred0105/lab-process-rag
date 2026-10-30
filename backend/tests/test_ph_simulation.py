import pytest

from app.services.simulation.ph import estimate_solution_ph


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
