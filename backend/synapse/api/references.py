"""/api/synapse/references — typed reference ingestion (REFS pipeline).

POST /ingest        run extract→segment→parse→resolve→classify→dedupe→merge
                    on a paper's PDF or on pasted text. Anything under the
                    confidence threshold lands in the review queue, not the
                    graph.
GET  /review-queue  pending items with their full proposal.
POST /review/{uid}/confirm   human confirms (optionally edits) → merged with
                             resolution="manual", confidence 1.0.
POST /review/{uid}/reject    drop the item.

No frontend view yet — by design.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

import pdf
from activity import record
from config import settings
from db import run_read, run_write
from synapse.references import classify, merge, parse, resolve

router = APIRouter(prefix="/api/synapse/references", tags=["references"])


class IngestBody(BaseModel):
    paper_id: str | None = None    # ingest this paper's PDF bibliography…
    text: str | None = None        # …or pasted bibliography text
    commit: bool = True            # False → dry run, returns the pipeline output


class ConfirmBody(BaseModel):
    edits: dict | None = None      # field overrides applied over the proposal


def _overlay(fields: dict, res: dict) -> dict:
    """Resolved values win over parsed ones — but only where the resolver
    actually returned something, so a null can't erase a literal field."""
    resolved = res.get("resolved") or {}
    out = dict(fields)
    for k in ("title", "authors", "year", "venue", "publisher", "doi", "url",
              "isbn", "issn"):
        if resolved.get(k):
            out[k] = resolved[k]
    return out


@router.post("/ingest")
async def ingest(body: IngestBody) -> dict:
    if not body.text and not body.paper_id:
        raise HTTPException(400, "provide paper_id or text")

    text = body.text or ""
    if body.paper_id:
        rows = await run_read(
            "MATCH (p:Paper {id: $id}) RETURN p.original_path AS op, p.title AS title",
            id=body.paper_id,
        )
        if not rows:
            raise HTTPException(404, "paper not found")
        if not text:
            text = pdf.extract_references_section(rows[0]["op"]) if rows[0]["op"] else ""
    if not text.strip():
        raise HTTPException(422, "no bibliography text found")

    segments = parse.segment(text)
    merged, queued, results = [], [], []
    for seg in segments:
        fields = await parse.parse_entry(seg["raw"])
        res = await resolve.resolve_reference(fields)
        cls = classify.classify(fields, res)
        fields = _overlay(fields, res)
        item = {
            "ordinal": seg["ordinal"],
            "title": fields.get("title"),
            "form": cls["form"], "warrant": cls["warrant"],
            "resolution": res["resolution"], "confidence": res["confidence"],
        }
        if not body.commit:
            results.append({**item, "fields": fields})
            continue
        if res["confidence"] >= settings.ref_confidence_threshold:
            out = await merge.merge_reference(
                fields, cls, res["resolution"], res["confidence"],
                document_id=body.paper_id, ordinal=seg["ordinal"],
            )
            merged.append({**item, **out})
        else:
            out = await merge.queue_for_review(
                fields, cls, res["resolution"], res["confidence"],
                document_id=body.paper_id, ordinal=seg["ordinal"],
            )
            queued.append({**item, **out})

    if body.commit:
        await record(
            "ref", "ingested",
            detail=f"{len(segments)} segments → {len(merged)} merged, {len(queued)} queued",
            paper_id=body.paper_id,
        )
    return {
        "segments": len(segments),
        "merged": merged, "queued": queued,
        "dry_run": None if body.commit else results,
        "threshold": settings.ref_confidence_threshold,
    }


@router.get("/review-queue")
async def review_queue() -> list[dict]:
    rows = await run_read(
        "MATCH (q:RefReviewItem {status: 'pending'}) RETURN q ORDER BY q.created_at"
    )
    out = []
    for row in rows:
        q = dict(row["q"])
        try:
            q["proposal"] = json.loads(q.get("proposal") or "{}")
        except json.JSONDecodeError:
            q["proposal"] = {}
        out.append(q)
    return out


@router.post("/review/{uid}/confirm")
async def confirm_review(uid: str, body: ConfirmBody) -> dict:
    rows = await run_read("MATCH (q:RefReviewItem {uid: $uid}) RETURN q", uid=uid)
    if not rows:
        raise HTTPException(404, "review item not found")
    q = dict(rows[0]["q"])
    proposal = json.loads(q.get("proposal") or "{}")
    if body.edits:
        proposal.update(body.edits)
    cls = {
        "form": proposal.get("form", "webpage"),
        "warrant": proposal.get("warrant", "unwarranted"),
        # a human said so — the one path where warrant stops being inferred
        "warrant_source": "manual",
    }
    if cls["form"] not in classify.FORMS or cls["warrant"] not in classify.WARRANTS:
        raise HTTPException(422, f"form must be one of {sorted(classify.FORMS)}, "
                                 f"warrant one of {sorted(classify.WARRANTS)}")
    out = await merge.merge_reference(
        proposal, cls, resolution="manual", confidence=1.0,
        document_id=q.get("document_id"), ordinal=q.get("ordinal"),
    )
    await run_write("MATCH (q:RefReviewItem {uid: $uid}) DETACH DELETE q", uid=uid)
    await record("ref", "review confirmed", detail=(proposal.get("title") or q.get("raw_string", ""))[:70])
    return {**out, "resolution": "manual", "confidence": 1.0}


@router.post("/review/{uid}/reject", status_code=204, response_class=Response)
async def reject_review(uid: str) -> Response:
    await run_write("MATCH (q:RefReviewItem {uid: $uid}) DETACH DELETE q", uid=uid)
    await record("ref", "review rejected", detail=uid)
    return Response(status_code=204)
