"""/api/framework — the approach I'm taking, and why.

Every other reasoning surface in the Mainframe records what happened: what you
read, what you worked on, what you spent. None of them records *why you chose
this way of working over another one* — which is the thing you can't
reconstruct later from the evidence, and the thing you most want when the
approach stops working and you're deciding whether to change it.

So a :Framework holds four pieces of prose — the approach, the reasoning, what
you ruled out, and a title — plus a simple box diagram for when a picture says
it faster, and any ideas you want kept alongside the reasoning.

The diagram is stored as opaque JSON (`boxes`, `arrows`) rather than as graph
structure, deliberately. It is a *drawing*: it gets redrawn wholesale, and
modelling each box as a node would buy nothing and cost migrations.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import DiagramSave, FrameworkCreate, FrameworkUpdate, ProjectIdeaAttach

router = APIRouter(prefix="/api/framework", tags=["framework"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shape(node: dict) -> dict:
    f = dict(node)
    for key in ("boxes", "arrows"):
        try:
            f[key] = json.loads(f.get(key) or "[]")
        except (TypeError, ValueError):
            f[key] = []
    return f


async def _one(fid: str) -> dict:
    rows = await run_read("MATCH (f:Framework {id: $id}) RETURN f", id=fid)
    if not rows:
        raise HTTPException(404, "framework not found")
    return _shape(rows[0]["f"])


@router.get("")
async def list_frameworks() -> list[dict]:
    """Newest first, but `current` always floats to the top — the point of the
    panel is the approach you're actually running."""
    rows = await run_read(
        """
        MATCH (f:Framework)
        RETURN f
        ORDER BY CASE coalesce(f.status, 'current')
                   WHEN 'current' THEN 0 WHEN 'considering' THEN 1 ELSE 2 END,
                 coalesce(f.updated_at, f.created_at) DESC
        """)
    out = []
    for r in rows:
        f = _shape(r["f"])
        # The list doesn't need the drawing, only whether there is one.
        f["box_count"] = len(f.pop("boxes", []))
        f.pop("arrows", None)
        out.append(f)
    return out


@router.get("/{fid}")
async def get_framework(fid: str) -> dict:
    f = await _one(fid)
    ideas = await run_read(
        """
        MATCH (:Framework {id: $id})-[r:HAS_IDEA]->(i:Idea)
        RETURN i{.id, .title, .category} AS idea, r{.note} AS link
        ORDER BY coalesce(i.title, '')
        """, id=fid)
    f["ideas"] = [{**dict(x["idea"]), "note": (dict(x["link"] or {})).get("note") or ""}
                  for x in ideas]
    return f


@router.post("", status_code=201)
async def create_framework(body: FrameworkCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "give it a title")
    fid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (f:Framework {
            id: $id, title: $title, approach: $approach, why: $why,
            rejected: $rejected, status: $status, boxes: '[]', arrows: '[]',
            created_at: $now, updated_at: $now
        })
        RETURN f
        """,
        id=fid, title=body.title.strip(), approach=body.approach, why=body.why,
        rejected=body.rejected, status=body.status, now=_now())
    await record("framework", "created", detail=body.title[:70], entity_id=fid)
    return _shape(rows[0]["f"])


@router.patch("/{fid}")
async def update_framework(fid: str, patch: FrameworkUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    fields["updated_at"] = _now()
    sets = ", ".join(f"f.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (f:Framework {{id: $id}}) SET {sets} RETURN f", id=fid, **fields)
    if not rows:
        raise HTTPException(404, "framework not found")
    await record("framework", "updated",
                 detail=", ".join(k for k in fields if k != "updated_at"),
                 entity_id=fid)
    return _shape(rows[0]["f"])


@router.put("/{fid}/diagram")
async def save_diagram(fid: str, body: DiagramSave) -> dict:
    """Replace the whole drawing. Saving each box separately would mean a write
    per drag, and a half-saved diagram if one failed."""
    rows = await run_write(
        """
        MATCH (f:Framework {id: $id})
        SET f.boxes = $boxes, f.arrows = $arrows, f.updated_at = $now
        RETURN f
        """,
        id=fid, boxes=json.dumps(body.boxes), arrows=json.dumps(body.arrows),
        now=_now())
    if not rows:
        raise HTTPException(404, "framework not found")
    return _shape(rows[0]["f"])


@router.delete("/{fid}", status_code=204, response_class=Response)
async def delete_framework(fid: str) -> Response:
    await run_write("MATCH (f:Framework {id: $id}) DETACH DELETE f", id=fid)
    await record("framework", "deleted", detail=fid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Ideas kept alongside the reasoning — same shape as a project's
# --------------------------------------------------------------------------- #
@router.post("/{fid}/ideas", status_code=201)
async def attach_idea(fid: str, body: ProjectIdeaAttach) -> dict:
    await _one(fid)
    idea_id = body.idea_id
    if not idea_id:
        title = (body.title or "").strip()
        if not title:
            raise HTTPException(400, "give the idea a title, or attach an existing one")
        idea_id = str(uuid.uuid4())
        await run_write(
            """
            OPTIONAL MATCH (x:Idea)
            WITH coalesce(min(x.position), 0.0) - 1.0 AS pos
            CREATE (i:Idea:Task {id: $id, title: $title, category: $category,
                            kind: 'idea', priority: 'medium', status: 'raw',
                            description: '', low_h: 0.0, high_h: 0.0, due: '',
                            notes: '', created_at: $now, position: pos})
            """, id=idea_id, title=title, category=body.category or "research",
            now=_now())
    sent = body.model_fields_set
    await run_write(
        """
        MATCH (f:Framework {id: $fid}), (i:Idea {id: $iid})
        MERGE (f)-[r:HAS_IDEA]->(i)
          ON CREATE SET r.added_at = $now, r.note = $note
        SET r.note = coalesce($note_set, r.note)
        """,
        fid=fid, iid=idea_id, note=body.note,
        note_set=body.note if "note" in sent else None, now=_now())
    await record("framework", "idea attached", detail=(body.title or idea_id)[:70],
                 entity_id=fid)
    return await get_framework(fid)


@router.delete("/{fid}/ideas/{idea_id}", status_code=204, response_class=Response)
async def detach_idea(fid: str, idea_id: str) -> Response:
    await run_write(
        "MATCH (:Framework {id: $fid})-[r:HAS_IDEA]->(:Idea {id: $iid}) DELETE r",
        fid=fid, iid=idea_id)
    return Response(status_code=204)
