"""Resolve a parsed reference against Crossref, then OpenAlex.

Order, and what gets recorded as `resolution`:
  1. DOI present in the source text  → GET crossref /works/{doi}   → "doi-exact"
  2. Crossref bibliographic query, scored against the parse        → "crossref-fuzzy"
  3. OpenAlex search, same scoring                                 → "openalex"
  4. nothing fired                                                 → "llm-inferred"
     (the record is exactly as trustworthy as the parse that produced it,
      and `confidence` says how much that is)

The invariant this file serves: a resolved field must be DISTINGUISHABLE from
an inferred one at query time. `resolution` + `confidence` travel with every
result and are written to the node by merge.py; nothing below the threshold
is merged at all (api/references.py routes it to the review queue instead).

Network manners: both APIs get a User-Agent carrying a mailto (Crossref's
polite pool), 3 tries with exponential backoff, and Retry-After is honoured.
A network failure downgrades the result to unresolved — it never raises out
of an ingest.

NOTE: these two endpoints are the only calls in the app that leave localhost.
That is deliberate and spec'd (REFS pipeline); everything else stays local.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
import urllib.parse

import httpx

from config import settings

log = logging.getLogger("synapse.references.resolve")

CROSSREF = "https://api.crossref.org"
OPENALEX = "https://api.openalex.org"
_MAILTO = {"mailto": settings.crossref_mailto} if settings.crossref_mailto else {}
_UA = "mainframe-synapse/0.1" + (f" (mailto:{settings.crossref_mailto})" if settings.crossref_mailto else "")

# Below this score a candidate match is rejected outright.
MATCH_THRESHOLD = 0.85


def _norm(t: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _title_sim(a: str | None, b: str | None) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


async def _get_json(url: str, params: dict | None = None) -> dict | None:
    """GET with retries/backoff. None on any terminal failure — never raises."""
    async with httpx.AsyncClient(
        timeout=settings.ref_resolve_timeout_s, headers={"User-Agent": _UA}
    ) as client:
        for attempt in range(3):
            try:
                r = await client.get(url, params=params)
                if r.status_code == 404:
                    return None
                if r.status_code == 429:
                    wait = float(r.headers.get("Retry-After", 2 ** attempt))
                    await asyncio.sleep(min(wait, 30))
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.HTTPError as exc:
                log.warning("resolve GET %s failed (try %d): %s", url, attempt + 1, exc)
                await asyncio.sleep(2 ** attempt)
    return None


def _from_crossref(work: dict) -> dict:
    """The fields we trust Crossref for, in our shape."""
    authors = [
        {"family": a.get("family") or a.get("name", ""),
         "given": a.get("given"),
         "is_org": "name" in a and "family" not in a}
        for a in work.get("author", []) if a.get("family") or a.get("name")
    ]
    year = None
    for k in ("published-print", "published-online", "issued"):
        parts = (work.get(k) or {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    return {
        "title": (work.get("title") or [None])[0],
        "authors": authors,
        "year": year,
        "venue": (work.get("container-title") or [None])[0],
        "publisher": work.get("publisher"),
        "doi": work.get("DOI"),
        "url": work.get("URL"),
        "issn": (work.get("ISSN") or [None])[0],
        "isbn": ((work.get("ISBN") or [None])[0] or "").split("/")[-1] or None,
        "crossref_type": work.get("type"),
    }


def _score(parsed: dict, cand: dict) -> float:
    """0.6 title similarity + 0.2 year agreement + 0.2 first-author overlap."""
    s = 0.6 * _title_sim(parsed.get("title"), cand.get("title"))
    py, cy = parsed.get("year"), cand.get("year")
    if py and cy and abs(py - cy) <= 1:
        s += 0.2
    pa = {(_norm(a.get("family"))) for a in parsed.get("authors", []) if a.get("family")}
    ca = {(_norm(a.get("family"))) for a in cand.get("authors", []) if a.get("family")}
    if pa and ca and pa & ca:
        s += 0.2
    return s


async def resolve_reference(parsed: dict) -> dict:
    """parsed fields → {resolution, confidence, resolved: {...} | None}."""
    doi = parsed.get("doi")
    if doi:
        body = await _get_json(f"{CROSSREF}/works/{urllib.parse.quote(doi)}")
        if body and body.get("message"):
            cand = _from_crossref(body["message"])
            # the DOI was literal in the source — a title mismatch is worth a
            # flag, not a rejection
            sim = _title_sim(parsed.get("title"), cand.get("title"))
            return {
                "resolution": "doi-exact",
                "confidence": 0.99 if sim >= 0.5 or not parsed.get("title") else 0.90,
                "resolved": cand,
            }

    title = parsed.get("title")
    if title and len(title) >= 15:
        q = title
        first = next((a.get("family") for a in parsed.get("authors", []) if a.get("family")), None)
        if first:
            q += f" {first}"
        if parsed.get("year"):
            q += f" {parsed['year']}"
        body = await _get_json(
            f"{CROSSREF}/works",
            {"query.bibliographic": q, "rows": 4, **_MAILTO},
        )
        items = ((body or {}).get("message") or {}).get("items") or []
        best, best_s = None, 0.0
        for it in items:
            cand = _from_crossref(it)
            s = _score(parsed, cand)
            if s > best_s:
                best, best_s = cand, s
        if best and best_s >= MATCH_THRESHOLD:
            return {"resolution": "crossref-fuzzy", "confidence": round(best_s, 3),
                    "resolved": best}

        body = await _get_json(
            f"{OPENALEX}/works",
            {"search": title, "per-page": 4, **_MAILTO},
        )
        best, best_s = None, 0.0
        for it in (body or {}).get("results") or []:
            cand = {
                "title": it.get("title"),
                "authors": [
                    {"family": (a.get("author") or {}).get("display_name", "").split()[-1],
                     "given": None, "is_org": False}
                    for a in it.get("authorships", [])
                    if (a.get("author") or {}).get("display_name")
                ],
                "year": it.get("publication_year"),
                "venue": ((it.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "publisher": None,
                "doi": (it.get("doi") or "").removeprefix("https://doi.org/") or None,
                "url": it.get("doi") or (it.get("primary_location") or {}).get("landing_page_url"),
                "issn": None, "isbn": None,
                "crossref_type": it.get("type"),
            }
            s = _score(parsed, cand)
            if s > best_s:
                best, best_s = cand, s
        if best and best_s >= MATCH_THRESHOLD:
            return {"resolution": "openalex", "confidence": round(best_s, 3),
                    "resolved": best}

    # Unresolved. Confidence reflects what the literal parse gives us: a real
    # URL or year in the source text is worth something, but never enough to
    # clear the merge threshold on its own — grey literature goes through
    # review once, by design.
    conf = 0.45
    if parsed.get("url"):
        conf += 0.15
    if parsed.get("year"):
        conf += 0.10
    if parsed.get("isbn") or parsed.get("issn"):
        conf += 0.05
    return {"resolution": "llm-inferred", "confidence": round(conf, 3), "resolved": None}
