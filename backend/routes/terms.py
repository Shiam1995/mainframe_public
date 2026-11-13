"""/api/synapse/terms — extracted concepts with 0-10 familiarity scores.

Terms are :Concept nodes linked to a paper via (:Paper)-[:INTRODUCES]->(:Concept).
Familiarity is ALWAYS an integer 0-10 (never categories). Score changes are
logged with old → new values so re-reads leave a trail. An LLM-assisted
"suggest" endpoint proposes candidate concepts for the pre-read assessment.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, HTTPException, Response

import llm
import pdf
from activity import record
from db import run_read, run_write
from models import TermCreate, TermUpdate

router = APIRouter(prefix="/api/synapse/terms", tags=["terms"])


@router.get("")
async def list_terms(paper_id: str) -> list[dict]:
    rows = await run_read(
        """
        MATCH (p:Paper {id: $pid})-[:INTRODUCES]->(c:Concept)
        RETURN c ORDER BY c.familiarity ASC, c.name
        """,
        pid=paper_id,
    )
    return [dict(r["c"]) for r in rows]


@router.post("", status_code=201)
async def create_term(paper_id: str, body: TermCreate) -> dict:
    ctx = await run_read("MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=paper_id)
    if not ctx:
        raise HTTPException(404, "paper not found")
    cid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (p:Paper {id: $pid})
        MERGE (c:Concept {name: $name})
          ON CREATE SET c.id = $id, c.definition = $definition, c.domain = $domain,
                        c.familiarity = $familiarity, c.optional = $optional
          ON MATCH SET  c.familiarity = $familiarity
        MERGE (p)-[:INTRODUCES]->(c)
        RETURN c
        """,
        pid=paper_id, id=cid, name=body.name, definition=body.definition,
        domain=body.domain, familiarity=body.familiarity, optional=body.optional,
    )
    await record("term", "added", detail=f"{body.name} (familiarity={body.familiarity})",
                 paper_id=paper_id, paper_title=ctx[0]["title"])
    return dict(rows[0]["c"])


@router.patch("/{concept_id}")
async def update_term(concept_id: str, patch: TermUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    # Capture old familiarity for the audit trail.
    old = await run_read("MATCH (c:Concept {id: $id}) RETURN c.familiarity AS f, c.name AS name", id=concept_id)
    if not old:
        raise HTTPException(404, "concept not found")
    sets = ", ".join(f"c.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (c:Concept {{id: $id}}) SET {sets} RETURN c", id=concept_id, **fields
    )
    if "familiarity" in fields:
        await record(
            "term", "familiarity changed",
            detail=f"{old[0]['name']}: {old[0]['f']} → {fields['familiarity']}",
        )
    else:
        await record("term", "updated", detail=f"{old[0]['name']}: {', '.join(fields)}")
    return dict(rows[0]["c"])


@router.delete("/{concept_id}", status_code=204, response_class=Response)
async def delete_term(concept_id: str, paper_id: str) -> Response:
    """Unlink a concept from this paper (the Concept node may be shared)."""
    await run_write(
        """
        MATCH (p:Paper {id: $pid})-[r:INTRODUCES]->(c:Concept {id: $cid})
        DELETE r
        """,
        pid=paper_id, cid=concept_id,
    )
    await record("term", "removed", detail=concept_id, paper_id=paper_id)
    return Response(status_code=204)


@router.post("/suggest")
async def suggest_terms(paper_id: str, prompt_override: str | None = Form(None)) -> list[dict]:
    """Use the local LLM to propose concepts from the paper text (not saved)."""
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p.original_path AS op", id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    op = rows[0]["op"]
    text = pdf.extract_head(op, pages=3) if op else ""
    concepts = await llm.extract_concepts(text, prompt_override=prompt_override)
    await record("term", "suggested", detail=f"{len(concepts)} candidates", paper_id=paper_id)
    return concepts
