import pytest

from app.services.scientific_data import normalize_scalar


def test_scalar_normalization_preserves_original_and_converts_units():
    normalized=normalize_scalar("Growth", "growth time", "60", "min")
    assert normalized["original_value"]=="60"
    assert normalized["original_unit"]=="min"
    assert normalized["normalized_value"]==pytest.approx(3600)
    assert normalized["normalized_unit"]=="second"
    assert normalized["value_type"]=="number"


def test_scalar_normalization_does_not_guess_unknown_or_ambiguous_unit():
    normalized=normalize_scalar("Growth", "rate", "2", "widgets")
    assert normalized["normalized_value"] is None
    assert "unit_conversion_failed" in normalized["normalization_error"]
    assert normalized["original_unit"]=="widgets"


def test_scalar_normalization_keeps_zero_missing_boolean_and_categories_distinct():
    zero=normalize_scalar("Step", "count", "0", "cycles")
    missing=normalize_scalar("Step", "count", "", "cycles")
    boolean=normalize_scalar("Step", "formed", "false")
    category=normalize_scalar("Step", "appearance", "white")
    assert zero["normalized_value"]==0
    assert missing["value_type"]=="missing"
    assert boolean["value_type"]=="boolean"
    assert category["value_type"]=="categorical"


def test_p_h_is_preserved_as_logarithmic_not_treated_as_linear_unit():
    normalized=normalize_scalar("Solution", "pH", "8.5", "pH")
    assert normalized["normalized_value"]==8.5
    assert normalized["normalized_unit"]=="pH"
    assert normalized["normalization_error"] is None


def test_uncertainty_must_be_nonnegative_and_finite():
    with pytest.raises(ValueError): normalize_scalar("Step", "temperature", "25", "degC", uncertainty=-0.1)


def test_temperature_uncertainty_uses_temperature_difference_scale():
    normalized=normalize_scalar("Step", "temperature", "25", "degC", uncertainty=0.5)
    assert normalized["measurement_uncertainty"]==pytest.approx(0.5)
