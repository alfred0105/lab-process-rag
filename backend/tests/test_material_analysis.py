import io

import numpy as np
from PIL import Image
import pytest

from app.services.material_analysis.service import AnalysisInputError, analyze


def test_xrd_reports_measured_peaks_without_claiming_phase_identity():
    pattern = "2theta,intensity\n" + "\n".join(f"{x},{y}" for x, y in enumerate([0, 1, 2, 8, 2, 1, 0, 1, 2, 5, 2, 1]))
    output = analyze("xrd", pattern.encode(), "sample.csv")
    assert output.tool_id == "xrd.local_peaks.v1"
    assert [peak["x"] for peak in output.result["observed_peaks"]] == [3.0, 9.0]
    assert "No phase identification" in output.result["interpretation_limit"]
    assert output.result["review_required"] is True


def test_xrd_known_gaussian_and_overlapping_peak_coordinates_are_reproducible():
    x = np.arange(10.0, 70.0, 0.05)
    y = (8 + 0.15 * np.sin(x * 4)
         + 100 * np.exp(-0.5 * ((x - 28.35) / 0.18) ** 2)
         + 65 * np.exp(-0.5 * ((x - 44.7) / 0.28) ** 2)
         + 48 * np.exp(-0.5 * ((x - 45.2) / 0.25) ** 2))
    data = "\n".join(f"{a:.3f},{b:.8f}" for a, b in zip(x, y)).encode()
    result = analyze("xrd", data, "synthetic-gaussian.csv", xrd_x_unit="2theta_deg").result
    positions = [peak["x"] for peak in result["observed_peaks"]]
    assert positions[0] == pytest.approx(28.35, abs=0.05)
    # The two close Gaussians are intentionally unresolved by this local-max
    # preview: the merged maximum is reported, never interpreted as two phases.
    assert positions[1] == pytest.approx(44.85, abs=0.1)
    assert result["x_unit"] == "2theta_deg"
    assert "No phase identification" in result["interpretation_limit"]


def test_xrd_d_spacing_axis_is_preserved_without_unstated_wavelength_conversion():
    data = b"0.8 0\n0.9 2\n1.0 10\n1.1 2\n1.2 0\n"
    result = analyze("xrd", data, "d-spacing.dat", xrd_x_unit="d_angstrom").result
    assert result["x_unit"] == "d_angstrom"
    assert result["observed_peaks"][0]["x"] == pytest.approx(1.0)


def test_xrd_constant_background_has_no_false_peak():
    data = "\n".join(f"{x} 100" for x in range(10))
    result = analyze("xrd", data.encode(), "flat.xy").result
    assert result["observed_peaks"] == []
    assert result["point_count"] == 10


def test_xrd_rejects_non_finite_numeric_rows_instead_of_silently_dropping_them():
    with pytest.raises(AnalysisInputError, match="non-finite"):
        analyze("xrd", b"1 1\n2 2\n3 3\n4 nan\n5 1\n", "bad.xy")


def test_afm_plane_leveling_removes_tilt_before_roughness_metrics():
    yy, xx = np.indices((7, 9), dtype=float)
    surface = 4 * xx - 2 * yy + 8
    surface[3, 4] += 10
    data = "\n".join(",".join(str(value) for value in row) for row in surface)
    result = analyze("afm", data.encode(), "height.csv").result
    assert result["leveling"] == "least_squares_plane"
    assert result["height_unit"] == "nm"
    assert result["Sq"] > 0
    assert result["Sq"] < 2
    assert result["review_required"] is True


@pytest.mark.parametrize("kind", ["flat", "periodic", "noisy"])
def test_afm_deterministic_surfaces_have_finite_nonnegative_roughness(kind):
    yy, xx = np.indices((24, 27), dtype=float)
    rng = np.random.default_rng(20261030)
    texture = {"flat": np.zeros_like(xx),
               "periodic": 0.8 * np.sin(xx * np.pi / 4) + 0.4 * np.cos(yy * np.pi / 6),
               "noisy": rng.normal(0, 0.12, size=xx.shape)}[kind]
    grid = 0.3 * xx - 0.17 * yy + 12 + texture
    content = "\n".join(",".join(f"{v:.12f}" for v in row) for row in grid).encode()
    result = analyze("afm", content, f"{kind}.csv", afm_height_unit="nm").result
    assert result["leveling"] == "least_squares_plane"
    assert result["height_unit"] == "nm"
    assert all(np.isfinite(result[key]) and result[key] >= 0 for key in ("Sa", "Sq", "Sz"))
    if kind == "flat":
        assert result["Sa"] < 1e-10 and result["Sq"] < 1e-10 and result["Sz"] < 1e-9


def test_afm_non_finite_and_ragged_height_maps_are_rejected():
    with pytest.raises(AnalysisInputError, match="non-finite"):
        analyze("afm", b"0,1,2\n3,nan,5\n6,7,8", "nan.csv")
    with pytest.raises(AnalysisInputError, match="rectangular"):
        analyze("afm", b"0,1,2\n3,4\n5,6,7", "ragged.csv")


def test_microscopy_creates_retrievable_binary_mask_and_calibrated_area():
    pixels = np.zeros((32, 32), dtype=np.uint8)
    pixels[8:20, 9:22] = 220
    image = Image.fromarray(pixels, mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    output = analyze("sem", buffer.getvalue(), "micro.png", pixel_size_nm=2, foreground="bright")
    assert output.tool_id == "microscopy.otsu_components.v1"
    assert output.result["component_count"] == 1
    assert output.result["component_area_nm2_mean"] == pytest.approx(12 * 13 * 4)
    assert output.artifact_extension == "png"
    assert output.artifact is not None
    assert "not a trained SEM/TEM model" in output.result["interpretation_limit"]


@pytest.mark.parametrize("shape,expected_count", [("edge", 1), ("touching", 1), ("empty", 0), ("low_contrast", 1)])
def test_microscopy_deterministic_edge_overlap_empty_and_low_contrast_cases(shape, expected_count):
    pixels = np.full((40, 48), 20 if shape != "low_contrast" else 100, dtype=np.uint8)
    if shape == "edge":
        pixels[0:12, 0:12] = 230
    elif shape == "touching":
        pixels[10:20, 10:19] = 220
        pixels[10:20, 19:28] = 220
    elif shape == "low_contrast":
        pixels[10:30, 12:36] = 108
    output = io.BytesIO(); Image.fromarray(pixels).save(output, format="PNG")
    result = analyze("sem", output.getvalue(), f"{shape}.png", pixel_size_nm=1.5).result
    assert result["component_count"] == expected_count
    assert result["review_required"] is True
    assert "Overlap" in result["interpretation_limit"]


def test_microscopy_rejects_corrupt_files_and_missing_pixel_calibration():
    with pytest.raises(AnalysisInputError, match="greater than zero"):
        analyze("tem", b"garbage", "bad.png", pixel_size_nm=0)
    with pytest.raises(AnalysisInputError, match="readable"):
        analyze("tem", b"garbage", "bad.png", pixel_size_nm=1)


@pytest.mark.parametrize("modality,filename,data", [
    ("xrd", "bad.png", b"not a pattern"),
    ("afm", "ragged.csv", b"1,2,3\n4,5\n6,7,8"),
    ("unsupported", "sample.dat", b"1 2 3"),
])
def test_invalid_modality_or_input_is_rejected(modality, filename, data):
    with pytest.raises(AnalysisInputError):
        analyze(modality, data, filename)
