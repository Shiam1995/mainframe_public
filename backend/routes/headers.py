"""/api/synapse/headers — user-defined custom sections.

Lets the system grow without code changes: create a named section (e.g.
"Literature Review", "Conference Notes") that shows up as its own tab. Content
is freeform markdown/text. A header can be global or scoped to one paper via
(:CustomHeader)-[:SCOPED_TO]->(:Paper).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import HeaderCreate, HeaderUpdate

router = APIRouter(prefix="/api/synapse/headers", tags=["headers"])


async def _one(header_id: str) -> dict | None:
    rows = await run_read(
        """
        MATCH (h:CustomHeader {id: $id})
        OPTIONAL MATCH (h)-[:SCOPED_TO]->(p:Paper)
        RETURN h, p.id AS paper_id
        """,
        id=header_id,
    )
    if not rows:
        return None
    h = dict(rows[0]["h"])
    h["paper_id"] = rows[0]["paper_id"]
    return h


@router.get("")
async def list_headers(paper_id: str | None = None) -> list[dict]:
    """Global headers, plus any scoped to `paper_id` when provided."""
    rows = await run_read(
        """
        MATCH (h:CustomHeader)
        OPTIONAL MATCH (h)-[:SCOPED_TO]->(p:Paper)
        RETURN h, p.id AS paper_id
        ORDER BY h.order, h.created_at
        """
    )
    out = []
    for r in rows:
        h = dict(r["h"])
        h["paper_id"] = r["paper_id"]
        if h["paper_id"] is None or h["paper_id"] == paper_id:
            out.append(h)
    return out


@router.post("", status_code=201)
async def create_header(body: HeaderCreate) -> dict:
    hid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (h:CustomHeader {
            id: $id, name: $name, description: $description, order: $order,
            content: $content, created_at: $created_at
        })
        """,
        id=hid, name=body.name, description=body.description, order=body.order,
        content=body.content, created_at=datetime.now(timezone.utc).isoformat(),
    )
    if body.paper_id:
        await run_write(
            "MATCH (h:CustomHeader {id: $hid}),(p:Paper {id: $pid}) MERGE (h)-[:SCOPED_TO]->(p)",
            hid=hid, pid=body.paper_id,
        )
    await record("header", "created", detail=body.name, paper_id=body.paper_id)
    return await _one(hid)


@router.patch("/{header_id}")
async def update_header(header_id: str, patch: HeaderUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"h.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (h:CustomHeader {{id: $id}}) SET {sets} RETURN h", id=header_id, **fields)
    if not rows:
        raise HTTPException(404, "header not found")
    await record("header", "updated", detail=", ".join(fields))
    return await _one(header_id)


@router.delete("/{header_id}", status_code=204, response_class=Response)
async def delete_header(header_id: str) -> Response:
    await run_write("MATCH (h:CustomHeader {id: $id}) DETACH DELETE h", id=header_id)
    await record("header", "deleted", detail=header_id)
    return Response(status_code=204)
