from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage


class AnalysisInputError(ValueError):
    """Raised when a file cannot safely be interpreted by a pilot analyzer."""


@dataclass(frozen=True)
class AnalysisOutput:
    tool_id: str
    result: dict
    artifact: bytes | None = None
    artifact_extension: str | None = None


def analyze_xrd(data: bytes, filename: str, x_unit: str = "2theta_deg") -> AnalysisOutput:
    """Report measured local maxima only; this does not identify phases."""
    rows: list[tuple[float, float]] = []
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith(("#", "!", ";")):
            continue
        fields = re.split(r"[,;\s]+", cleaned)
        try:
            x, y = float(fields[0]), float(fields[1])
        except (ValueError, IndexError):
            continue  # common column headers are ignored
        if math.isfinite(x) and math.isfinite(y):
            rows.append((x, y))
    if len(rows) < 5:
        raise AnalysisInputError("XRD input needs at least five numeric x/intensity rows.")
    values = np.asarray(rows, dtype=float)
    order = np.argsort(values[:, 0], kind="stable")
    x, y = values[order, 0], values[order, 1]
    if np.any(np.diff(x) <= 0):
        raise AnalysisInputError("XRD x positions must be unique and increasing.")
    dynamic_range = float(np.ptp(y))
    threshold = float(np.min(y) + 0.05 * dynamic_range)
    candidates = [i for i in range(1, len(y) - 1) if y[i] > y[i - 1] and y[i] >= y[i + 1] and y[i] >= threshold]
    # Collapse adjacent local maxima to the stronger observed sample.
    peaks: list[int] = []
    for index in candidates:
        if peaks and index - peaks[-1] < 3:
            if y[index] > y[peaks[-1]]:
                peaks[-1] = index
        else:
            peaks.append(index)
    max_intensity = float(np.max(y))
    # Keep a bounded, deterministic preview of the measured curve for the UI.
    # Always retain detected peak samples even when a long scan is decimated.
    preview_limit = 1200
    stride = max(1, math.ceil(len(x) / preview_limit))
    preview_indices = set(range(0, len(x), stride)) | set(peaks)
    preview_indices.add(len(x) - 1)
    return AnalysisOutput("xrd.local_peaks.v1", {
        "analysis_kind": "observed_pattern_features",
        "filename": filename,
        "point_count": int(len(x)),
        "x_unit": x_unit,
        "intensity_unit": "instrument_reported",
        "baseline_min": float(np.min(y)),
        "intensity_max": max_intensity,
        "pattern_preview": [
            {"x": float(x[i]), "intensity": float(y[i])}
            for i in sorted(preview_indices)
        ],
        "observed_peaks": [
            {"x": float(x[i]), "intensity": float(y[i]), "relative_intensity_percent": float(y[i] / max_intensity * 100) if max_intensity else 0.0}
            for i in peaks[:200]
        ],
        "interpretation_limit": "Observed local maxima only. No phase identification, lattice refinement, or causal conclusion was performed.",
        "review_required": True,
    })


def _parse_numeric_grid(data: bytes) -> np.ndarray:
    rows: list[list[float]] = []
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith(("#", "!", ";")):
            continue
        fields = re.split(r"[,;\s]+", cleaned)
        try:
            row = [float(value) for value in fields if value]
        except ValueError:
            continue
        if row:
            rows.append(row)
    if len(rows) < 3 or len({len(row) for row in rows}) != 1 or len(rows[0]) < 3:
        raise AnalysisInputError("AFM input must contain a rectangular numeric height grid of at least 3×3 values.")
    grid = np.asarray(rows, dtype=float)
    if not np.isfinite(grid).all():
        raise AnalysisInputError("AFM height grid contains non-finite values.")
    return grid


def analyze_afm(data: bytes, filename: str, height_unit: str = "nm") -> AnalysisOutput:
    """Plane-level an AFM height grid, then compute standard descriptive roughness."""
    grid = _parse_numeric_grid(data)
    height, width = grid.shape
    yy, xx = np.indices(grid.shape, dtype=float)
    design = np.column_stack((xx.ravel(), yy.ravel(), np.ones(grid.size)))
    plane, *_ = np.linalg.lstsq(design, grid.ravel(), rcond=None)
    leveled = grid - (plane[0] * xx + plane[1] * yy + plane[2])
    centered = leveled - float(leveled.mean())
    return AnalysisOutput("afm.plane_level_roughness.v1", {
        "analysis_kind": "surface_topography_metrics",
        "filename": filename,
        "grid_shape_px": {"rows": int(height), "columns": int(width)},
        "height_unit": height_unit,
        "leveling": "least_squares_plane",
        "Sa": float(np.mean(np.abs(centered))),
        "Sq": float(np.sqrt(np.mean(centered ** 2))),
        "Sz": float(np.max(leveled) - np.min(leveled)),
        "height_min_leveled": float(np.min(leveled)),
        "height_max_leveled": float(np.max(leveled)),
        "interpretation_limit": "Metrics are computed from the supplied height grid after plane leveling; calibration and scan-line artifact review remain necessary.",
        "review_required": True,
    })


def _otsu_threshold(values: np.ndarray) -> int:
    histogram = np.bincount(values.ravel(), minlength=256).astype(float)
    probability = histogram / histogram.sum()
    centers = np.arange(256, dtype=float)
    weight_background = np.cumsum(probability)
    mean_background = np.cumsum(probability * centers)
    total_mean = mean_background[-1]
    denominator = weight_background * (1.0 - weight_background)
    score = np.zeros(256, dtype=float)
    valid = denominator > 0
    score[valid] = (total_mean * weight_background[valid] - mean_background[valid]) ** 2 / denominator[valid]
    return int(np.argmax(score))


def analyze_microscopy(data: bytes, filename: str, pixel_size_nm: float, foreground: str = "bright") -> AnalysisOutput:
    """Create an Otsu mask and component measurements for review, not a trained scientific model."""
    if not math.isfinite(pixel_size_nm) or pixel_size_nm <= 0:
        raise AnalysisInputError("Pixel size must be a finite number greater than zero.")
    if foreground not in {"bright", "dark"}:
        raise AnalysisInputError("Foreground must be 'bright' or 'dark'.")
    try:
        source_image = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise AnalysisInputError("Microscopy pilot accepts readable PNG, JPEG, or TIFF images.") from exc
    if getattr(source_image, "n_frames", 1) != 1:
        raise AnalysisInputError("This pilot accepts one SEM/TEM image plane per file; multi-frame image stacks need a format-specific adapter.")
    if source_image.width < 8 or source_image.height < 8 or source_image.width * source_image.height > 16_000_000:
        raise AnalysisInputError("Image dimensions must be at least 8×8 and no more than 16 million pixels.")
    image = source_image.convert("L")
    gray = np.asarray(image, dtype=np.uint8)
    threshold = _otsu_threshold(gray)
    mask = gray > threshold if foreground == "bright" else gray <= threshold
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    sizes = np.bincount(labels.ravel())[1:]
    sizes = sizes[sizes >= 3]  # omit tiny isolated sensor/noise specks from the preview summary
    component_count = int(len(sizes))
    mask_image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    output = io.BytesIO()
    mask_image.save(output, format="PNG")
    size_nm2 = sizes.astype(float) * pixel_size_nm ** 2
    return AnalysisOutput("microscopy.otsu_components.v1", {
        "analysis_kind": "exploratory_binary_segmentation",
        "filename": filename,
        "image_size_px": {"width": int(image.width), "height": int(image.height)},
        "pixel_size_nm": float(pixel_size_nm),
        "threshold_method": "Otsu global threshold",
        "threshold_gray_0_255": threshold,
        "foreground": foreground,
        "component_count": component_count,
        "component_area_nm2_mean": float(np.mean(size_nm2)) if component_count else None,
        "component_area_nm2_median": float(np.median(size_nm2)) if component_count else None,
        "component_area_nm2_min": float(np.min(size_nm2)) if component_count else None,
        "component_area_nm2_max": float(np.max(size_nm2)) if component_count else None,
        "mask_url": None,
        "interpretation_limit": "Exploratory global-threshold mask, not a trained SEM/TEM model. Overlap, charging, scale calibration, and domain-specific morphology can invalidate particle counts and areas.",
        "review_required": True,
    }, output.getvalue(), "png")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def analyze(modality: str, data: bytes, filename: str, *, xrd_x_unit: str = "2theta_deg", afm_height_unit: str = "nm", pixel_size_nm: float = 1.0, foreground: str = "bright") -> AnalysisOutput:
    normalized = modality.strip().lower()
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if normalized == "xrd":
        if suffix not in {"xy", "xye", "csv", "txt", "dat"}:
            raise AnalysisInputError("XRD pilot accepts .xy, .xye, .csv, .txt, or .dat numeric patterns.")
        return analyze_xrd(data, filename, xrd_x_unit)
    if normalized == "afm":
        if suffix not in {"csv", "txt", "dat"}:
            raise AnalysisInputError("AFM pilot accepts rectangular .csv, .txt, or .dat numeric height grids.")
        return analyze_afm(data, filename, afm_height_unit)
    if normalized in {"sem", "tem"}:
        if suffix not in {"png", "jpg", "jpeg", "tif", "tiff"}:
            raise AnalysisInputError("SEM/TEM pilot accepts .png, .jpg, .jpeg, .tif, or .tiff raster images.")
        return analyze_microscopy(data, filename, pixel_size_nm, foreground)
    raise AnalysisInputError("Modality must be one of xrd, afm, sem, or tem.")
