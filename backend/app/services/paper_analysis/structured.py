"""Bounded, paper-scoped evidence selection and validation for structured extraction."""
from __future__ import annotations

import re

from app.db.models import EvidenceChunk, Paper

GROUPS = {
    "objective": "abstract introduction objective aim purpose conclusion",
    "materials": "materials reagents precursor substrate solvent sample chemicals",
    "methods": "experimental method synthesis fabrication procedure",
    "characterization": "characterization measurement instrument analysis XRD SEM TEM AFM",
    "findings": "results discussion conclusion result properties performance",
    "limitations": "limitations limitation however challenge future work",
}
ARRAY_FIELDS = {
    "research_objectives": ("description",),
    "materials": ("name",),
    "experimental_methods": ("name",),
    "process_conditions": ("method", "parameter"),
    "characterization_methods": ("name",),
    "key_findings": ("finding",),
    "reported_limitations": ("description",),
}


def select_evidence(db, paper: Paper, retrieval, maximum: int = 24) -> list[EvidenceChunk]:
    chunks = db.query(EvidenceChunk).filter_by(paper_id=paper.id).order_by(EvidenceChunk.page, EvidenceChunk.chunk_index).all()
    if not chunks:
        return []
    by_id = {chunk.id: chunk for chunk in chunks}
    selected: list[int] = []
    for query in GROUPS.values():
        try:
            hits = retrieval.search(db, query, limit=12, topic_id=paper.topic_id)
        except Exception:
            hits = []
        selected.extend(hit["evidence_id"] for hit in hits if hit.get("paper_id") == paper.id and hit.get("evidence_id") in by_id)
    # Add strong section/page-spread candidates where FTS did not cover the paper.
    section_terms = re.compile(r"abstract|introduction|material|experimental|method|fabricat|synth|character|measurement|result|discussion|conclusion|limitation", re.I)
    selected.extend(chunk.id for chunk in chunks if chunk.section and section_terms.search(chunk.section))
    pages = sorted({chunk.page for chunk in chunks})
    if pages:
        quartiles = [pages[min(len(pages)-1, round((len(pages)-1)*fraction))] for fraction in (0, .33, .66, 1)]
        for page in quartiles:
            candidate = next((chunk.id for chunk in chunks if chunk.page == page), None)
            if candidate is not None:
                selected.append(candidate)
    unique = list(dict.fromkeys(selected))
    # Guarantee page coverage first, then fill in retrieval order; cap duplicate chunks per page.
    ordered: list[int] = []
    for page in quartiles if pages else []:
        page_ids = [chunk.id for chunk in chunks if chunk.page == page and chunk.id in unique]
        if page_ids and page_ids[0] not in ordered:
            ordered.append(page_ids[0])
    ordered.extend(item for item in unique if item not in ordered)
    result, per_page = [], {}
    for evidence_id in ordered:
        chunk = by_id[evidence_id]
        if per_page.get(chunk.page, 0) >= 2:
            continue
        result.append(chunk)
        per_page[chunk.page] = per_page.get(chunk.page, 0) + 1
        if len(result) >= maximum:
            break
    return result


def validate_analysis(raw: dict, allowed_ids: set[int]) -> dict:
    required = set(ARRAY_FIELDS) | {"analysis_limitations", "schema_version"}
    if not isinstance(raw, dict) or not required.issubset(raw):
        raise ValueError("Structured analysis is missing required fields.")
    cleaned = {"schema_version": "1"}
    for field, text_keys in ARRAY_FIELDS.items():
        items = raw.get(field)
        if not isinstance(items, list):
            raise ValueError(f"{field} must be an array.")
        cleaned_items = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{field} contains an invalid item.")
            ids = item.get("evidence_ids")
            if not isinstance(ids, list):
                raise ValueError(f"Every {field} item needs evidence IDs.")
            if any(type(value) is int and value not in allowed_ids for value in ids):
                raise ValueError(f"{field} cites evidence outside this paper's selected excerpts.")
            normalized_ids = []
            for value in ids:
                if type(value) is int:
                    normalized_ids.append(value)
                elif isinstance(value, str) and value.isdigit():
                    normalized_ids.append(int(value))
                else:
                    raise ValueError(f"{field} contains a malformed evidence ID.")
            # A model may emit a blank placeholder instead of an empty array; never persist it.
            if not normalized_ids or any(not isinstance(item.get(key), str) or not item[key].strip() for key in text_keys):
                continue
            if not set(normalized_ids).issubset(allowed_ids):
                raise ValueError(f"{field} cites evidence outside this paper's selected excerpts.")
            cleaned_item = {key: (str(value).strip() if isinstance(value, str) else value) for key, value in item.items() if key != "evidence_ids"}
            cleaned_item["evidence_ids"] = list(dict.fromkeys(normalized_ids))
            cleaned_items.append(cleaned_item)
        cleaned[field] = cleaned_items
    limitations = raw.get("analysis_limitations")
    if not isinstance(limitations, list) or any(not isinstance(value, str) and not (isinstance(value, dict) and isinstance(value.get("description"), str)) for value in limitations):
        raise ValueError("analysis_limitations must be an array of strings.")
    cleaned["analysis_limitations"] = [value.strip() if isinstance(value, str) else value["description"].strip() for value in limitations if (value.strip() if isinstance(value, str) else value["description"].strip())][:20]
    return cleaned
