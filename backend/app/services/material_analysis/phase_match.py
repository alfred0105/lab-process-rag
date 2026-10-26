from __future__ import annotations

import csv
import asyncio
import math

import httpx


COD_SEARCH = "https://www.crystallography.net/cod/result"
COD_ENTRY = "https://www.crystallography.net/cod/{entry}.cif"


class ReferenceDatabaseUnavailable(RuntimeError):
    """The reference database could not be queried or its structures fetched."""


def _reduced_formula(value: str) -> str | None:
    from pymatgen.core import Composition

    try:
        # COD wraps formula strings in hyphens, e.g. "- O Zn -".
        cleaned = " ".join(value.strip().strip("-").split())
        return Composition(cleaned).reduced_formula
    except (ValueError, TypeError):
        return None


def _cod_rows(body: str) -> list[dict[str, str]]:
    lines = [line for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return []
    return list(csv.DictReader(lines))


def _match_peaks(observed: list[dict], calculated: list[tuple[float, float, str]], tolerance: float) -> dict:
    observed_positions = sorted(float(item["x"]) for item in observed)
    predicted = sorted((position, intensity, hkl) for position, intensity, hkl in calculated if intensity >= 3.0)
    possible = sorted(
        (abs(obs - calc), obs_index, calc_index)
        for obs_index, obs in enumerate(observed_positions)
        for calc_index, (calc, _intensity, _hkl) in enumerate(predicted)
        if abs(obs - calc) <= tolerance
    )
    used_observed: set[int] = set()
    used_calculated: set[int] = set()
    pairs: list[dict] = []
    for error, obs_index, calc_index in possible:
        if obs_index in used_observed or calc_index in used_calculated:
            continue
        used_observed.add(obs_index)
        used_calculated.add(calc_index)
        position, intensity, hkl = predicted[calc_index]
        pairs.append({
            "observed_2theta": observed_positions[obs_index],
            "reference_2theta": position,
            "delta_degrees": error,
            "reference_relative_intensity": intensity,
            "reference_hkl": hkl,
        })
    observed_coverage = len(used_observed) / len(observed_positions) if observed_positions else 0.0
    reference_coverage = len(used_calculated) / len(predicted) if predicted else 0.0
    f1 = (2 * observed_coverage * reference_coverage / (observed_coverage + reference_coverage)) if observed_coverage + reference_coverage else 0.0
    return {
        "score_percent": round(f1 * 100, 1),
        "observed_peak_coverage_percent": round(observed_coverage * 100, 1),
        "reference_peak_coverage_percent": round(reference_coverage * 100, 1),
        "matched_peaks": sorted(pairs, key=lambda item: item["observed_2theta"]),
        "unmatched_observed_peaks": [position for index, position in enumerate(observed_positions) if index not in used_observed],
        "reference_peaks_considered": len(predicted),
    }


async def match_xrd_phases(
    data: bytes,
    formulas: list[str],
    wavelength_angstrom: float,
    tolerance_degrees: float = 0.3,
) -> dict:
    """Compare observed peak positions with simulated COD CIF patterns.

    This ranks reference-pattern matches only. It is not phase identification or
    a Rietveld refinement, and intentionally reports the public COD provenance.
    """
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.core import Structure
    from app.services.material_analysis.service import analyze_xrd

    if not math.isfinite(wavelength_angstrom) or not 0.1 <= wavelength_angstrom <= 5:
        raise ValueError("Wavelength must be between 0.1 and 5 Å.")
    if not math.isfinite(tolerance_degrees) or not 0.01 <= tolerance_degrees <= 2:
        raise ValueError("Peak tolerance must be between 0.01 and 2 degrees.")
    if not 1 <= len(formulas) <= 5:
        raise ValueError("Enter between one and five candidate formulas.")

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in formulas:
        formula = raw.strip()
        normalized = _reduced_formula(formula)
        if not normalized:
            raise ValueError(f"'{formula}' is not a valid chemical formula.")
        if normalized not in seen:
            candidates.append((formula, normalized))
            seen.add(normalized)

    analyzed = analyze_xrd(data, "uploaded-pattern.csv")
    observed = analyzed.result["observed_peaks"]
    if not observed:
        return {"matches": [], "notice": "No local maxima were detected to compare.", "wavelength_angstrom": wavelength_angstrom}
    two_theta_range = (min(item["x"] for item in observed), max(item["x"] for item in observed))

    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True, headers={"User-Agent": "LabProcessRAG/0.1 (local research tool)"}) as client:
        async def search_formula(original: str, normalized: str):
            try:
                response = await client.get(COD_SEARCH, params={"text": original, "format": "csv"})
                response.raise_for_status()
                rows = _cod_rows(response.text)
                matching = []
                for row in rows:
                    entry_id = row.get("file", "").strip()
                    cod_formula = row.get("calcformula", "").strip() or row.get("formula", "").strip()
                    if entry_id.isdigit() and _reduced_formula(cod_formula) == normalized:
                        matching.append({"id": entry_id, "formula": cod_formula, "doi": row.get("doi", "").strip(), "title": row.get("title", "").strip()})
                    if len(matching) >= 4:
                        break
                return original, normalized, matching, None
            except (httpx.HTTPError, ValueError):
                return original, normalized, [], "search"

        searches = await asyncio.gather(*(search_formula(*candidate) for candidate in candidates))

        async def fetch_cif(item: dict):
            try:
                response = await client.get(COD_ENTRY.format(entry=item["id"]))
                response.raise_for_status()
                return item, response.text
            except httpx.HTTPError:
                return item, ""

        entries = [(formula, normalized, item) for formula, normalized, rows, _error in searches for item in rows]
        cif_results = await asyncio.gather(*(fetch_cif(item) for _formula, _normalized, item in entries))

    search_failures = sum(error is not None for _formula, _normalized, _rows, error in searches)
    if search_failures == len(searches):
        raise ReferenceDatabaseUnavailable("COD search failed for all candidate formulas")
    if entries and not any(cif_text for _item, cif_text in cif_results):
        raise ReferenceDatabaseUnavailable("COD structures could not be downloaded")

    calc = XRDCalculator(wavelength=wavelength_angstrom)
    results = []
    for (formula, normalized, _item), (item, cif_text) in zip(entries, cif_results, strict=False):
        if not cif_text:
            continue
        try:
            structure = Structure.from_str(cif_text, fmt="cif")
            pattern = calc.get_pattern(structure, two_theta_range=two_theta_range)
            calculated = []
            for index, (position, intensity) in enumerate(zip(pattern.x, pattern.y, strict=False)):
                hkl_items = pattern.hkls[index] if index < len(pattern.hkls) else []
                hkl = ", ".join(
                    "(" + " ".join(str(value) for value in item["hkl"]) + ")"
                    for item in hkl_items[:3]
                )
                calculated.append((float(position), float(intensity), hkl))
            ranked = _match_peaks(observed, calculated, tolerance_degrees)
        except Exception:
            continue
        results.append({
            "formula": normalized,
            "cod_id": item["id"],
            "reference_url": f"https://www.crystallography.net/cod/{item['id']}.html",
            "doi": item["doi"] or None,
            "doi_url": f"https://doi.org/{item['doi']}" if item["doi"] else None,
            **ranked,
        })

    results.sort(key=lambda item: (-item["score_percent"], -item["observed_peak_coverage_percent"], item["cod_id"]))
    return {
        "matches": results[:10],
        "searched_formulas": [normalized for _original, normalized in candidates],
        "observed_peak_count": len(observed),
        "wavelength_angstrom": wavelength_angstrom,
        "tolerance_degrees": tolerance_degrees,
        "data_source": "Crystallography Open Database (COD)",
        "notice": "Reference matches are candidate comparisons, not confirmed phase identification. Results depend on wavelength, sample composition, calibration, texture, mixtures, and completeness of the open structure database. No Rietveld refinement was performed.",
    }
