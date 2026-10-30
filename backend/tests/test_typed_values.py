import pytest

from app.services.typed_values import convert_declared_value


def test_converts_compatible_units_and_uncertainty_delta():
    value, uncertainty = convert_declared_value(25.0, "degC", "kelvin", 0.5)
    assert value == pytest.approx(298.15)
    assert uncertainty == pytest.approx(0.5)


def test_converts_same_dimension_without_offset():
    value, uncertainty = convert_declared_value(1000.0, "microliter", "milliliter", 10.0)
    assert value == pytest.approx(1.0)
    assert uncertainty == pytest.approx(0.01)


@pytest.mark.parametrize("source,target", [("m", "s"), ("pH", "dimensionless"), ("1", "SI")])
def test_rejects_incompatible_or_logarithmic_unit_conversion(source, target):
    with pytest.raises(ValueError):
        convert_declared_value(1.0, source, target)


@pytest.mark.parametrize("value,uncertainty", [(float("nan"), None), (1.0, float("inf")), (1.0, -0.1)])
def test_rejects_nonfinite_value_or_invalid_uncertainty(value, uncertainty):
    with pytest.raises(ValueError):
        convert_declared_value(value, "m", "m", uncertainty)
