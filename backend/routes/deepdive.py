"""/api/synapse/deepdive — topic-first deep dives.

Each dive is a topic you're digging into: a title, free-form `info`, and a list
of sources (structured title+link rows via :DeepDiveSource, plus a free-text
`sources_text` field). Replaces the old monthly-scheduling model (existing dives
are migrated in db.py so nothing is lost).

Dives are module-scoped (`module` property: "synapse", "pulse", …) so each
module can carry its own Deep Dive tab; dives without the property are Synapse's
(they predate the scoping). The URL prefix stays /api/synapse for compatibility.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import DeepDiveCreate, DeepDiveSourceCreate, DeepDiveUpdate
from routes.rows import row_texts

router = APIRouter(prefix="/api/synapse/deepdive", tags=["deepdive"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _with_sources(dive_id: str) -> dict:
    rows = await run_read(
        """
        MATCH (d:DeepDive {id: $id})
        OPTIONAL MATCH (d)-[:HAS_SOURCE]->(s:DeepDiveSource)
        WITH d, s ORDER BY s.created_at
        RETURN d{.*} AS dive, collect(s{.*}) AS sources
        """,
        id=dive_id,
    )
    if not rows:
        raise HTTPException(404, "deep dive not found")
    d = rows[0]["dive"]
    d["sources"] = [s for s in rows[0]["sources"] if s.get("id")]
    d["info_rows"] = (await row_texts([dive_id])).get(dive_id, {}).get("note", [])
    return d


@router.get("")
async def list_dives(module: str = "synapse") -> list[dict]:
    rows = await run_read(
        """
        MATCH (d:DeepDive)
        WHERE coalesce(d.module, 'synapse') = $module
        OPTIONAL MATCH (d)-[:HAS_SOURCE]->(s:DeepDiveSource)
        WITH d, s ORDER BY s.created_at
        RETURN d{.*} AS dive, collect(s{.*}) AS sources
        ORDER BY dive.created_at DESC
        """,
        module=module,
    )
    # `info` is + rows (kind note) on the dive now; the collapsed card's
    # preview reads them from here rather than one GET per card.
    texts = await row_texts([r["dive"].get("id") for r in rows])
    out = []
    for r in rows:
        d = r["dive"]
        d["sources"] = [s for s in r["sources"] if s.get("id")]
        d["info_rows"] = texts.get(d.get("id"), {}).get("note", [])
        out.append(d)
    return out


@router.post("", status_code=201)
async def create_dive(body: DeepDiveCreate) -> dict:
    did = str(uuid.uuid4())
    now = _now()
    await run_write(
        """
        CREATE (d:DeepDive {
            id: $id, topic: $topic, info: $info, sources_text: '',
            module: $module, created_at: $now, updated_at: $now
        })
        """,
        id=did, topic=body.topic.strip(), info=body.info, module=body.module, now=now,
    )
    await record("deepdive", "created", detail=body.topic[:70])
    return await _with_sources(did)


@router.patch("/{dive_id}")
async def update_dive(dive_id: str, patch: DeepDiveUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    fields["updated_at"] = _now()
    sets = ", ".join(f"d.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (d:DeepDive {{id: $id}}) SET {sets} RETURN d", id=dive_id, **fields)
    if not rows:
        raise HTTPException(404, "deep dive not found")
    await record("deepdive", "updated", detail=", ".join(k for k in fields if k != "updated_at"))
    return await _with_sources(dive_id)


@router.delete("/{dive_id}", status_code=204, response_class=Response)
async def delete_dive(dive_id: str) -> Response:
    await run_write(
        "MATCH (d:DeepDive {id: $id}) OPTIONAL MATCH (d)-[:HAS_SOURCE]->(s:DeepDiveSource) DETACH DELETE s, d",
        id=dive_id,
    )
    await record("deepdive", "deleted", detail=dive_id)
    return Response(status_code=204)


@router.post("/{dive_id}/sources", status_code=201)
async def add_source(dive_id: str, body: DeepDiveSourceCreate) -> dict:
    ctx = await run_read("MATCH (d:DeepDive {id: $id}) RETURN d", id=dive_id)
    if not ctx:
        raise HTTPException(404, "deep dive not found")
    sid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (d:DeepDive {id: $did})
        CREATE (d)-[:HAS_SOURCE]->(:DeepDiveSource {id: $id, title: $title, link: $link, created_at: $now})
        """,
        did=dive_id, id=sid, title=body.title.strip(), link=body.link, now=_now(),
    )
    await record("deepdive", "source added", detail=body.title[:70])
    return await _with_sources(dive_id)


@router.delete("/{dive_id}/sources/{source_id}", status_code=204, response_class=Response)
async def delete_source(dive_id: str, source_id: str) -> Response:
    await run_write("MATCH (s:DeepDiveSource {id: $id}) DETACH DELETE s", id=source_id)
    await record("deepdive", "source removed", detail=source_id)
    return Response(status_code=204)
