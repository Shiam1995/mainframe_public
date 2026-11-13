"""/api/synapse/highlights — annotations within a reading instance.

Each highlight is tagged knew | new | rethink | implement, with a section
reference, excerpt, personal note, and optional page. Highlights hang off an
Instance and may link to a Concept.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import HighlightCreate, HighlightUpdate

router = APIRouter(prefix="/api/synapse/highlights", tags=["highlights"])


@router.get("")
async def list_highlights(instance_id: str) -> list[dict]:
    rows = await run_read(
        """
        MATCH (i:Instance {id: $iid})-[:CONTAINS]->(h:Highlight)
        RETURN h ORDER BY coalesce(h.page, 0)
        """,
        iid=instance_id,
    )
    return [dict(r["h"]) for r in rows]


@router.post("", status_code=201)
async def create_highlight(instance_id: str, body: HighlightCreate) -> dict:
    ctx = await run_read(
        """
        MATCH (p:Paper)-[:HAS_INSTANCE]->(i:Instance {id: $iid})
        RETURN p.id AS pid, p.title AS title
        """,
        iid=instance_id,
    )
    if not ctx:
        raise HTTPException(404, "instance not found")
    hid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (i:Instance {id: $iid})
        CREATE (h:Highlight {
            id: $id, section: $section, excerpt: $excerpt, my_note: $my_note,
            tag: $tag, page: $page
        })
        CREATE (i)-[:CONTAINS]->(h)
        RETURN h
        """,
        iid=instance_id, id=hid, section=body.section, excerpt=body.excerpt,
        my_note=body.my_note, tag=body.tag, page=body.page,
    )
    await record("highlight", "created", detail=f"[{body.tag}] {body.excerpt[:60]}",
                 paper_id=ctx[0]["pid"], paper_title=ctx[0]["title"])
    return dict(rows[0]["h"])


@router.patch("/{highlight_id}")
async def update_highlight(highlight_id: str, patch: HighlightUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"h.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (h:Highlight {{id: $id}}) SET {sets} RETURN h", id=highlight_id, **fields
    )
    if not rows:
        raise HTTPException(404, "highlight not found")
    await record("highlight", "updated", detail=", ".join(fields))
    return dict(rows[0]["h"])


@router.delete("/{highlight_id}", status_code=204, response_class=Response)
async def delete_highlight(highlight_id: str) -> Response:
    rows = await run_write(
        "MATCH (h:Highlight {id: $id}) DETACH DELETE h RETURN count(*) AS n", id=highlight_id
    )
    await record("highlight", "deleted", detail=highlight_id)
    return Response(status_code=204)
