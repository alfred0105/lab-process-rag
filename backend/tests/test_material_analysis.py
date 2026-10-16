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


@pytest.mark.parametrize("modality,filename,data", [
    ("xrd", "bad.png", b"not a pattern"),
    ("afm", "ragged.csv", b"1,2,3\n4,5\n6,7,8"),
    ("unsupported", "sample.dat", b"1 2 3"),
])
def test_invalid_modality_or_input_is_rejected(modality, filename, data):
    with pytest.raises(AnalysisInputError):
        analyze(modality, data, filename)
