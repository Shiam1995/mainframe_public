"""/api/focus — the quick overview: where I am right now.

One question, answered from the top bar without navigating anywhere: what
phase am I in, what am I trying to do, and what's actually moving?

Only two things here are *stored* — the phase and the goals. Everything else
is derived from data the rest of the Mainframe already keeps: which projects
have been worked recently, what's being learned, what's due. A quick overview
that needed its own bookkeeping would go stale within a fortnight, and a stale
overview is worse than none.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import FocusUpdate, GoalCreate, GoalUpdate

router = APIRouter(prefix="/api/focus", tags=["focus"])

# How recently a project must have been worked to count as "current".
ACTIVE_DAYS = 21


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _focus_node() -> dict:
    rows = await run_read("MATCH (f:Focus) RETURN f LIMIT 1")
    if rows:
        return dict(rows[0]["f"])
    rows = await run_write(
        "CREATE (f:Focus {id: $id, phase: '', note: '', updated_at: $now}) RETURN f",
        id=str(uuid.uuid4()), now=_now())
    return dict(rows[0]["f"])


async def _goals() -> list[dict]:
    rows = await run_read(
        """
        MATCH (g:Goal) WHERE NOT g:PoolGoal
        RETURN g ORDER BY coalesce(g.position, 1e15) ASC, g.created_at DESC
        """)
    return [dict(r["g"]) for r in rows]


@router.get("")
async def overview() -> dict:
    focus = await _focus_node()
    goals = await _goals()

    cutoff = (datetime.now().date() - timedelta(days=ACTIVE_DAYS)).isoformat()
    projects = await run_read(
        """
        MATCH (p:Project)
        OPTIONAL MATCH (w:WorkSession)-[:ON]->(p)
        WITH p, collect(w) AS ws
        WITH p,
             reduce(s = 0, x IN ws | s + coalesce(x.mins, 0)) AS mins,
             [x IN ws WHERE coalesce(x.date, '') >= $cutoff] AS recent
        WHERE size(recent) > 0
        RETURN p.name AS name, p.id AS id, mins,
               reduce(m = '', x IN recent | CASE WHEN coalesce(x.date,'') > m
                                                 THEN x.date ELSE m END) AS last_worked,
               size(recent) AS recent_sessions
        ORDER BY last_worked DESC LIMIT 8
        """, cutoff=cutoff)

    # What's being learned right now, if the Learning module has anything open.
    learning = await run_read(
        """
        MATCH (l:LearningOpportunity)
        WHERE coalesce(l.status, '') <> 'done'
        RETURN coalesce(l.title, l.name, '') AS title, coalesce(l.status,'') AS status
        ORDER BY coalesce(l.created_at, '') DESC LIMIT 5
        """)

    tasks = await run_read(
        """
        MATCH (t:Task)
        WHERE NOT coalesce(t.done, false) AND coalesce(t.status,'') <> 'hidden'
        RETURN count(t) AS open,
               size([x IN collect(t) WHERE coalesce(x.horizon,'') = 'long']) AS long
        """)

    return {
        "phase": focus.get("phase") or "",
        "note": focus.get("note") or "",
        # Which snapshot sections the panel shows — see FocusUpdate.sections.
        "sections": focus.get("sections") or "",
        "updated_at": focus.get("updated_at"),
        "goals": [g for g in goals if g.get("status") != "done"],
        "done_goals": len([g for g in goals if g.get("status") == "done"]),
        "projects": [dict(p) for p in projects],
        "learning": [dict(l) for l in learning if l["title"]],
        "open_tasks": tasks[0]["open"] if tasks else 0,
        "long_arcs": tasks[0]["long"] if tasks else 0,
    }


@router.put("")
async def set_focus(body: FocusUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "nothing to set")
    await _focus_node()
    fields["updated_at"] = _now()
    sets = ", ".join(f"f.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (f:Focus) SET {sets} RETURN f", **fields)
    # Rearranging the snapshot panel is a preference, not a change of direction —
    # logging it as "phase set" would bury the real phase changes in the activity
    # feed, which is the one place they're worth finding.
    if "phase" in fields or "note" in fields:
        await record("focus", "phase set", detail=(fields.get("phase") or "")[:70])
    return dict(rows[0]["f"])


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #
@router.get("/goals")
async def list_goals() -> list[dict]:
    return await _goals()


@router.post("/goals", status_code=201)
async def create_goal(body: GoalCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "give the goal a title")
    gid = str(uuid.uuid4())
    rows = await run_write(
        """
        OPTIONAL MATCH (x:Goal)
        WITH coalesce(min(x.position), 0.0) - 1.0 AS pos
        CREATE (g:Goal {id: $id, title: $title, note: $note, horizon: $horizon,
                        status: 'active', created_at: $now, position: pos})
        RETURN g
        """,
        id=gid, title=body.title.strip(), note=body.note, horizon=body.horizon,
        now=_now())
    await record("focus", "goal added", detail=body.title[:70], entity_id=gid)
    return dict(rows[0]["g"])


@router.patch("/goals/{gid}")
async def update_goal(gid: str, patch: GoalUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"g.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (g:Goal {{id: $id}}) SET {sets} RETURN g", id=gid, **fields)
    if not rows:
        raise HTTPException(404, "goal not found")
    await record("focus", "goal updated", detail=", ".join(fields), entity_id=gid)
    return dict(rows[0]["g"])


@router.delete("/goals/{gid}", status_code=204, response_class=Response)
async def delete_goal(gid: str) -> Response:
    await run_write("MATCH (g:Goal {id: $id}) DETACH DELETE g", id=gid)
    await record("focus", "goal deleted", detail=gid)
    return Response(status_code=204)
