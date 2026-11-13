"""Idempotent merge of a classified reference into the graph.

Dedupe order (spec):
  1. DOI exact
  2. normalised title + first author family + year
  3. no match → NEW node, flagged needs_review

One :Reference node per WORK — a second document citing the same work adds a
second incoming :CITES edge, never a second node. In-degree is signal.

Never-downgrade rule: a node whose fields came from a better resolution
(manual > doi-exact > crossref-fuzzy > openalex > llm-inferred) keeps them;
a weaker re-ingest only adds the :CITES edge. So an LLM guess can never
overwrite a resolved record, and re-running an ingest is a no-op.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone

from db import run_read, run_write

log = logging.getLogger("synapse.references.merge")

_RANK = {"manual": 4, "doi-exact": 3, "crossref-fuzzy": 2, "openalex": 1,
         "llm-inferred": 0}

_STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or the to with".split()
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_title(t: str | None) -> str:
    """lowercase, strip diacritics, punctuation and stopwords."""
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    words = re.sub(r"[^a-z0-9]+", " ", t).split()
    return " ".join(w for w in words if w not in _STOPWORDS)


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.lower().removeprefix("https://doi.org/").strip().rstrip(".") or None


def _uid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def _first_family(fields: dict) -> str:
    for a in fields.get("authors", []):
        if a.get("family"):
            return norm_title(a["family"])
    return ""


async def find_existing(fields: dict) -> dict | None:
    """Dedupe lookup → {uid, resolution} of the matching node, or None."""
    doi = _norm_doi(fields.get("doi"))
    if doi:
        rows = await run_read(
            "MATCH (r:Reference {doi: $doi}) RETURN r.uid AS uid, r.resolution AS resolution LIMIT 1",
            doi=doi,
        )
        if rows:
            return rows[0]
    tn, fam, year = norm_title(fields.get("title")), _first_family(fields), fields.get("year")
    if tn and year:
        rows = await run_read(
            """
            MATCH (r:Reference {title_norm: $tn})
            WHERE r.year = $year AND ($fam = '' OR r.first_author_norm = $fam)
            RETURN r.uid AS uid, r.resolution AS resolution LIMIT 1
            """,
            tn=tn, year=year, fam=fam,
        )
        if rows:
            return rows[0]
    return None


async def merge_reference(
    fields: dict,
    cls: dict,
    resolution: str,
    confidence: float,
    document_id: str | None = None,
    ordinal: int | None = None,
    page: int | None = None,
) -> dict:
    """Merge one classified reference; returns {uid, created, updated}.

    `fields` is the parse result, already overlaid with resolved values where
    the resolver fired (api/references.py does the overlay). form/warrant are
    PROPERTIES — never labels — so reclassification is a SET.
    """
    existing = await find_existing(fields)
    doi = _norm_doi(fields.get("doi"))
    if existing:
        uid = existing["uid"]
        created = False
        needs_review = False
        update = _RANK.get(resolution, 0) >= _RANK.get(existing.get("resolution") or "llm-inferred", 0)
    else:
        key = f"doi:{doi}" if doi else (
            f"tay:{norm_title(fields.get('title'))}|{_first_family(fields)}|{fields.get('year')}"
            if fields.get("title") else f"raw:{fields.get('raw_string', '')}"
        )
        uid = _uid(key)
        created = True
        needs_review = not doi and not fields.get("title")
        update = True

    await run_write(
        """
        MERGE (r:Reference {uid: $uid})
        ON CREATE SET r.first_seen = $now, r.raw_string = $raw,
                      r.needs_review = $needs_review
        """,
        uid=uid, now=_now(), raw=fields.get("raw_string", ""), needs_review=needs_review,
    )
    if update:
        await run_write(
            """
            MATCH (r:Reference {uid: $uid})
            SET r.title = $title, r.title_norm = $tn, r.first_author_norm = $fam,
                r.year = $year, r.doi = $doi, r.url = $url,
                r.isbn = $isbn, r.issn = $issn,
                r.form = $form, r.warrant = $warrant,
                r.warrant_source = $warrant_source,
                r.resolution = $resolution, r.confidence = $confidence
            """,
            uid=uid, title=fields.get("title"), tn=norm_title(fields.get("title")),
            fam=_first_family(fields), year=fields.get("year"), doi=doi,
            url=fields.get("url"), isbn=fields.get("isbn"), issn=fields.get("issn"),
            form=cls["form"], warrant=cls["warrant"],
            warrant_source=cls.get("warrant_source", "inferred"),
            resolution=resolution, confidence=confidence,
        )
        for i, a in enumerate(fields.get("authors", [])):
            name = (f"{a['given']} {a['family']}".strip() if a.get("given") else a.get("family", "")).strip()
            if not name:
                continue
            await run_write(
                """
                MERGE (au:Author {name: $name})
                  ON CREATE SET au.uid = $auid, au.family = $family,
                                au.given = $given, au.is_org = $is_org
                WITH au
                MATCH (r:Reference {uid: $uid})
                MERGE (r)-[rel:AUTHORED_BY]->(au)
                SET rel.position = $pos
                """,
                name=name[:200], auid=_uid("author:" + name.lower()),
                family=a.get("family"), given=a.get("given"),
                is_org=bool(a.get("is_org")), uid=uid, pos=i,
            )
        venue = (fields.get("venue") or "").strip()
        if venue:
            await run_write(
                """
                MERGE (v:Venue {name: $name})
                  ON CREATE SET v.uid = $vuid
                SET v.type = coalesce($vtype, v.type),
                    v.publisher = coalesce($publisher, v.publisher)
                WITH v
                MATCH (r:Reference {uid: $uid})
                MERGE (r)-[:PUBLISHED_IN]->(v)
                """,
                name=venue[:300], vuid=_uid("venue:" + venue.lower()),
                vtype=cls["form"], publisher=fields.get("publisher"), uid=uid,
            )

    if document_id:
        await run_write(
            """
            MATCH (p:Paper {id: $doc}), (r:Reference {uid: $uid})
            MERGE (p)-[c:CITES]->(r)
            SET c.ordinal = $ordinal, c.page = $page
            """,
            doc=document_id, uid=uid, ordinal=ordinal, page=page,
        )
    return {"uid": uid, "created": created, "updated": update}


# --------------------------------------------------------------------------- #
# Review queue — below-threshold results live here, NOT in the graph.
# --------------------------------------------------------------------------- #
async def queue_for_review(
    fields: dict, cls: dict, resolution: str, confidence: float,
    document_id: str | None, ordinal: int | None,
) -> dict:
    uid = _uid("review:" + fields.get("raw_string", "") + ":" + (document_id or ""))
    proposal = {**fields, **cls, "resolution": resolution, "confidence": confidence}
    await run_write(
        """
        MERGE (q:RefReviewItem {uid: $uid})
        ON CREATE SET q.created_at = $now
        SET q.raw_string = $raw, q.proposal = $proposal, q.confidence = $confidence,
            q.resolution = $resolution, q.document_id = $doc, q.ordinal = $ordinal,
            q.status = 'pending'
        """,
        uid=uid, now=_now(), raw=fields.get("raw_string", ""),
        proposal=json.dumps(proposal), confidence=confidence,
        resolution=resolution, doc=document_id, ordinal=ordinal,
    )
    return {"uid": uid, "queued": True, "confidence": confidence}
