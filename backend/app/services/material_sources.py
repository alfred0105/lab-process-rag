"""Small, source-linked chemical identity lookup using the PubChem PUG REST API.

Returned values identify a likely chemical record. They are not lot-specific
reagent specifications and must not be used to infer purity, stock strength,
hydration state, or solution properties.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import quote

import httpx


PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PROPERTIES = "MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,InChIKey"
NIST_CBOOK = "https://webbook.nist.gov/cgi/cbook.cgi"


class _NistPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._anchor: tuple[str, list[str]] | None = None
        self.data_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            self._anchor = (values.get("href") or "", [])

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._anchor is not None:
            self._anchor[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._anchor is not None:
            href, parts = self._anchor
            label = " ".join(" ".join(parts).split())
            if label and ("/cgi/fluid.cgi?ID=" in href or re.search(r"[?&]Mask=", href)):
                self.data_links.append("Reaction data" if label.lower().startswith("reactions ") else label)
            self._anchor = None


class MaterialLookupUnavailable(RuntimeError):
    pass


def lookup_material(query: str) -> dict:
    term = " ".join(query.split())[:120]
    if len(term) < 2:
        raise ValueError("Enter at least two characters to search for a material.")

    headers = {"User-Agent": "LabProcessRAG/0.1 (local research material lookup)"}
    try:
        with httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0), headers=headers) as client:
            cids_response = client.get(f"{PUBCHEM}/compound/name/{quote(term, safe='')}/cids/JSON")
            if cids_response.status_code == 404:
                return _empty_result(term, headers)
            cids_response.raise_for_status()
            cids = cids_response.json().get("IdentifierList", {}).get("CID", [])[:5]
            if not cids:
                return _empty_result(term, headers)
            id_path = ",".join(str(int(cid)) for cid in cids)
            property_response = client.get(f"{PUBCHEM}/compound/cid/{id_path}/property/{PROPERTIES}/JSON")
            property_response.raise_for_status()
            rows = property_response.json().get("PropertyTable", {}).get("Properties", [])
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        raise MaterialLookupUnavailable("PubChem could not return a chemical record right now.") from exc

    candidates = []
    for row in rows:
        cid = row.get("CID")
        if not isinstance(cid, int):
            continue
        candidates.append({
            "cid": cid,
            "name": row.get("IUPACName") or term,
            "formula": row.get("MolecularFormula"),
            "molecular_weight_g_mol": row.get("MolecularWeight"),
            "inchikey": row.get("InChIKey"),
            "canonical_smiles": row.get("ConnectivitySMILES") or row.get("CanonicalSMILES"),
            "source": "PubChem",
            "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        })
    nist = _lookup_nist(term, headers)
    return {
        "query": term,
        "provider": "PubChem PUG REST",
        "candidates": candidates,
        "nist": nist,
        "additional_source_url": "https://webbook.nist.gov/chemistry/",
        "limitations": [
            "PubChem matches are candidate chemical identities; confirm the exact salt, hydrate, and form against the reagent label or certificate of analysis.",
            "Do not infer supplier lot, purity, stock concentration, density, or measured solution properties from this record.",
            "This lookup is reference information only and does not change saved experiment values.",
        ],
    }


def _lookup_nist(term: str, headers: dict[str, str]) -> dict:
    """Return NIST record links and the data sections exposed by the record page.

    This is source discovery, not property extraction: no NIST value is inserted
    into a saved material or simulation input.
    """
    try:
        response = httpx.get(NIST_CBOOK, params={"Name": term, "Units": "SI"}, headers=headers, timeout=httpx.Timeout(12.0, connect=5.0), follow_redirects=True)
        response.raise_for_status()
        parser = _NistPageParser()
        parser.feed(response.text)
    except (httpx.HTTPError, ValueError):
        return {"status": "unavailable", "title": None, "source_url": "https://webbook.nist.gov/chemistry/", "available_data": []}

    title = " ".join(parser.title.split())
    generic = {"", "NIST Chemistry WebBook", "NIST Chemistry WebBook, SRD 69"}
    specific = title not in generic
    return {
        "status": "record_found" if specific else "no_record",
        "title": title if specific else None,
        "source_url": str(response.url) if specific else "https://webbook.nist.gov/chemistry/",
        "available_data": list(dict.fromkeys(parser.data_links))[:16],
    }


def _empty_result(term: str, headers: dict[str, str]) -> dict:
    return {
        "query": term,
        "provider": "PubChem PUG REST",
        "candidates": [],
        "nist": _lookup_nist(term, headers),
        "additional_source_url": "https://webbook.nist.gov/chemistry/",
        "limitations": [
            "No exact PubChem match was returned. Check the name, formula, salt, hydrate, or CAS number; do not guess an identity.",
            "Supplier lot properties and measured solution properties must come from the user, label, certificate, or an applicable primary source.",
        ],
    }
