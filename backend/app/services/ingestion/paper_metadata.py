"""Conservative metadata extraction for research PDFs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

import httpx
import pymupdf

from app.services.ingestion.pdf import MAX_PDF_PAGES, MAX_PDF_SIZE_BYTES

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:%A-Z0-9]+", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
ABSTRACT_RE = re.compile(r"(?im)^\s*(?:abstract|summary)\s*[:.]?\s*$")
ABSTRACT_INLINE_RE = re.compile(r"(?is)\b(?:abstract|summary)\s*[:.]\s*(.{80,5000}?)(?=\n\s*(?:keywords?|1\.?\s*introduction|introduction)\b|$)")
BAD_TITLES = {"untitled", "microsoft word", "document", "paper", "unknown"}


def _clean(value: str | None) -> str:
    return " ".join((value or "").replace("\x00", " ").split()).strip(" .\n\t")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    candidate = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", value.strip(), flags=re.I)
    candidate = candidate.rstrip(".,;:)]}")
    match = DOI_RE.search(candidate)
    return match.group(0).lower() if match else None


def _primary_doi(pages: list[str]) -> str | None:
    """Choose a DOI from the paper's opening metadata, avoiding later references."""
    if not pages:
        return None
    first_page = pages[0]
    references = re.search(r"(?im)^\s*(?:references|bibliography)\s*$", first_page)
    searchable = first_page[:references.start()] if references else first_page
    candidates: list[tuple[int, int, str]] = []
    for match in DOI_RE.finditer(searchable):
        line_start = searchable.rfind("\n", 0, match.start()) + 1
        line_end = searchable.find("\n", match.end())
        line_end = len(searchable) if line_end < 0 else line_end
        line = searchable[line_start:line_end].casefold()
        prefix = searchable[max(0, match.start() - 24):match.start()].casefold()
        # Favor explicitly labeled DOI lines and publisher DOI URLs, then the earliest header candidate.
        signal = 0 if ("doi" in line or "doi.org/" in prefix) else 1
        doi = normalize_doi(match.group(0))
        if doi:
            candidates.append((signal, match.start(), doi))
    return min(candidates)[2] if candidates else None


def _normalize_title(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def _titles_match(pdf_title: str | None, crossref_title: str | None) -> bool:
    local, external = _normalize_title(pdf_title), _normalize_title(crossref_title)
    if not local or not external:
        return False
    if local == external:
        return True
    ratio = SequenceMatcher(None, local, external).ratio()
    return ratio >= 0.90 or (min(len(local), len(external)) >= 24 and (local in external or external in local))


def _pdf_text(payload: bytes) -> tuple[dict[str, Any], list[str]]:
    if not payload:
        raise ValueError("The uploaded PDF is empty.")
    if len(payload) > MAX_PDF_SIZE_BYTES:
        raise ValueError("PDF exceeds the 50 MB upload limit.")
    with pymupdf.open(stream=payload, filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if doc.page_count > MAX_PDF_PAGES:
            raise ValueError("PDF exceeds the 500-page processing limit.")
        metadata = doc.metadata or {}
        pages = [doc[index].get_text("text") for index in range(min(3, doc.page_count))]
    return metadata, pages


def _candidate_title(metadata: dict[str, Any], first_page: str, filename: str, payload: bytes) -> tuple[str | None, str | None]:
    embedded = _clean(metadata.get("title"))
    fallback = Path(filename).stem
    if embedded and embedded.casefold() not in BAD_TITLES and embedded.casefold() != fallback.casefold() and len(embedded) >= 8:
        return embedded[:500], "pdf_metadata"

    # Candidate lines near the top of page one, scored using layout font size
    # and title-like text features rather than simply choosing the largest span.
    scores: dict[str, float] = {}
    try:
        with pymupdf.open(stream=payload, filetype="pdf") as doc:
            page = doc[0]
            data = page.get_text("dict")
            page_height = page.rect.height
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = _clean(" ".join(span.get("text", "") for span in spans))
                    if not text or not spans:
                        continue
                    size = max(float(span.get("size", 0)) for span in spans)
                    y = min(float(span.get("bbox", [0, 0, 0, page_height])[1]) for span in spans)
                    if y > page_height * 0.48 or len(text) < 14 or len(text) > 280:
                        continue
                    if text.casefold() in BAD_TITLES or "@" in text or DOI_RE.search(text) or YEAR_RE.fullmatch(text):
                        continue
                    if re.search(r"(?i)^(abstract|keywords?|available online|received|accepted|doi|www\.)\b", text):
                        continue
                    score = min(size, 30) * 1.2 + (10 if 25 <= len(text) <= 180 else 0) - y / max(page_height, 1) * 9
                    if text.isupper():
                        score -= 3
                    scores[text] = max(scores.get(text, -1), score)
    except Exception:
        pass
    if scores:
        chosen = max(scores, key=scores.get)
        if chosen.casefold() != fallback.casefold():
            return chosen[:500], "pdf_first_page"

    for line in first_page.splitlines()[:35]:
        text = _clean(line)
        if 18 <= len(text) <= 180 and text.casefold() not in BAD_TITLES and not DOI_RE.search(text) and not YEAR_RE.fullmatch(text):
            if not re.search(r"(?i)^(abstract|keywords?|received|accepted|doi)\b", text):
                return text[:500], "pdf_first_page"
    return None, None


def _first_page_authors(payload: bytes, title: str | None) -> str | None:
    """Pick a nearby author-like line while rejecting common affiliation lines."""
    try:
        with pymupdf.open(stream=payload, filetype="pdf") as doc:
            page = doc[0]
            page_height = page.rect.height
            candidates: list[tuple[float, str]] = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = _clean(" ".join(span.get("text", "") for span in spans))
                    if not text or not spans:
                        continue
                    y = min(float(span.get("bbox", [0, 0, 0, page_height])[1]) for span in spans)
                    if y > page_height * 0.60 or len(text) > 240 or len(text) < 5:
                        continue
                    lowered = text.casefold()
                    if any(term in lowered for term in ("abstract", "keywords", "university", "institute", "department", "corresponding author", "email", "http", "doi", "received", "accepted")):
                        continue
                    if re.search(r"\d|@|[=<>]", text) or YEAR_RE.fullmatch(text):
                        continue
                    if title and (text.casefold() in title.casefold() or title.casefold() in text.casefold()):
                        continue
                    if not re.search(r"[,;]|\band\b|\b[a-z][.]\s*[a-z]", text, re.I):
                        continue
                    size = max(float(span.get("size", 0)) for span in spans)
                    candidates.append((y - min(size, 16) * 0.25, text))
            if candidates:
                return min(candidates, key=lambda item: item[0])[1][:1000]
    except Exception:
        return None
    return None


def _abstract(text: str) -> str | None:
    inline = ABSTRACT_INLINE_RE.search(text)
    if inline:
        return _clean(inline.group(1))[:12000]
    match = ABSTRACT_RE.search(text)
    if not match:
        return None
    remainder = text[match.end():]
    end = re.search(r"(?im)^\s*(?:keywords?|1\.?\s*introduction|introduction)\b", remainder)
    value = _clean(remainder[:end.start()] if end else remainder)
    return value[:12000] if len(value) >= 40 else None


def _crossref(doi: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"https://api.crossref.org/works/{doi}", headers={"User-Agent": "LabProcessRAG/0.1 (paper metadata)"}, timeout=5.0)
        response.raise_for_status()
        item = response.json().get("message", {})
        title = (item.get("title") or [None])[0]
        authors = [" ".join(part for part in (author.get("given"), author.get("family")) if part) for author in item.get("author", [])]
        issued = item.get("published-print") or item.get("published-online") or item.get("issued") or {}
        parts = issued.get("date-parts") or [[None]]
        abstract = _clean(re.sub(r"<[^>]+>", " ", item.get("abstract") or "")) or None
        return {"title": title, "authors": [a for a in authors if a], "year": parts[0][0] if parts and parts[0] else None, "doi": item.get("DOI"), "abstract": abstract, "journal": (item.get("container-title") or [None])[0]}
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return None


def extract_paper_metadata(payload: bytes, filename: str, *, lookup_crossref: bool = True) -> dict[str, Any]:
    embedded, pages = _pdf_text(payload)
    text = "\n".join(pages)
    title, title_source = _candidate_title(embedded, pages[0] if pages else "", filename, payload)
    sources: dict[str, str] = {}
    if title_source:
        sources["title"] = title_source
    authors = _clean(embedded.get("author"))
    if authors and authors.casefold() in BAD_TITLES:
        authors = ""
    if not authors:
        authors = _first_page_authors(payload, title) or ""
    if authors:
        sources["authors"] = "pdf_metadata" if _clean(embedded.get("author")) else "pdf_first_page"
    doi = _primary_doi(pages)
    if doi:
        sources["doi"] = "pdf_first_page"
    year_match = YEAR_RE.search("\n".join(pages[:2]))
    year = int(year_match.group(0)) if year_match else None
    if year:
        sources["year"] = "pdf_first_page"
    abstract = _abstract(text)
    if abstract:
        sources["abstract"] = "pdf_abstract_section"
    warnings: list[str] = []
    crossref = _crossref(doi) if doi and lookup_crossref else None
    conflicts: dict[str, dict[str, Any]] = {}
    if doi and lookup_crossref and crossref is None:
        warnings.append("Crossref DOI lookup was unavailable; local PDF extraction was used.")
    if crossref:
        title_match = _titles_match(title, crossref.get("title"))
        if title and crossref.get("title") and not title_match:
            conflicts["title"] = {"pdf": title, "crossref": crossref["title"]}
            conflicts["authors"] = {"pdf": authors or None, "crossref": crossref.get("authors")}
            conflicts["year"] = {"pdf": year, "crossref": crossref.get("year")}
            conflicts["abstract"] = {"pdf": abstract, "crossref": crossref.get("abstract")}
            warnings.append("The DOI record title does not match the PDF title. Crossref values were not applied.")
        else:
            # Only a title-consistent DOI record can fill or correct bibliographic fields.
            # Field differences remain visible for researcher review.
            local_values = {"title": title, "authors": authors, "year": year, "abstract": abstract}
            for field, local in local_values.items():
                external = crossref.get(field)
                if local and external and (" ".join(local).casefold() if isinstance(local, list) else str(local).casefold()) != (" ".join(external).casefold() if isinstance(external, list) else str(external).casefold()):
                    conflicts[field] = {"pdf": local, "crossref": external}
                if external:
                    if field == "title":
                        title = external
                    elif field == "authors":
                        authors = "; ".join(external)
                    elif field == "year":
                        year = external
                    elif field == "abstract":
                        abstract = external
                    sources[field] = "crossref_doi"
            doi = normalize_doi(crossref.get("doi")) or doi
    metadata_title = title or Path(filename).stem
    if not title:
        sources["title"] = "filename_fallback"
        warnings.append("A reliable title was not found. Review the filename-based title.")
    if not abstract:
        warnings.append("Abstract was not found in the PDF or Crossref metadata.")
    if conflicts:
        warnings.append("PDF and Crossref metadata differ. Review the conflicting fields.")
    return {"title": metadata_title, "authors": authors, "year": year, "doi": doi, "abstract": abstract, "journal": crossref.get("journal") if crossref else None, "metadata_sources": sources, "conflicts": conflicts, "needs_review": bool(warnings or not title), "warnings": warnings, "crossref": crossref}
