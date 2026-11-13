"""/api/synapse/ideas — the spreadsheet-like idea table.

Ideas are :Idea nodes. Beyond the default columns, users can add arbitrary
custom columns — stored as flexible properties on the node (Pydantic
`extra=allow`). Supports CSV/JSON export. Category is free text (user-extensible),
not a fixed enum.

WHERE AN IDEA GOES, AND WHERE IT CAME FROM. Two edges, and they are the point
of this table rather than decoration on it:

    (:Idea)-[:GIVEN_TO {date}]->(:Project)    you handed it to something
    (:Idea)-[:CAME_FROM {date}]->(:Paper|:Project)   it came out of something

Giving an idea away is the moment worth explaining, so the client writes a why
note against the GIVEN_TO edge at the same time (see routes/notes.py — edge
notes hang off a :Hop). A given idea keeps its row, greyed, naming the project:
an ideas table you delete from stops being a record of what you thought.

ONE PROVENANCE EDGE, NOT TWO. Paper provenance was `i.paper_id`, a scalar
property, and adding a second mechanism for project provenance would have meant
two ways to ask the same question. CAME_FROM is one edge that points at either,
and `_reconcile_provenance()` draws it for every idea that still only has the
old property. The property is kept in step, because instances.py reads it and
the table still shows it as a column.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from activity import record
from config import settings
from db import run_read, run_write
from models import (
    IdeaCameFrom, IdeaCategoryUpsert, IdeaCreate, IdeaGivenTo, IdeaUpdate,
    ReorderRequest,
)
from routes.mind import reorder_nodes

router = APIRouter(prefix="/api/synapse/ideas", tags=["ideas"])

# Reserved so custom columns can't clobber structural props.
# The last four are computed from work sessions on read, never stored.
_RESERVED = {"id", "created_at", "position", "sessions", "total_mins",
             "session_count", "last_worked", "given_to", "came_from"}
# Computed fields — stripped before export so the CSV stays flat.
_COMPUTED = {"sessions", "total_mins", "session_count", "last_worked",
             "given_to", "came_from"}

# The three states an idea can be in. `given` is not typed by hand: it is set
# when the GIVEN_TO edge is drawn, and cleared when it is taken back.
STATUSES = ("raw", "given", "dropped")


# --------------------------------------------------------------------------- #
# Kinds — the colour that marks an idea lives on its kind, not the idea, so
# every idea of a kind reads the same. Kinds are user-extensible.
# --------------------------------------------------------------------------- #
@router.get("/categories")
async def list_categories() -> list[dict]:
    rows = await run_read(
        "MATCH (c:IdeaCategory) RETURN c.name AS name, c.color AS color ORDER BY toLower(c.name)"
    )
    return [{"name": r["name"], "color": r["color"] or "#7FA8C8"} for r in rows if r["name"]]


@router.put("/categories")
async def upsert_category(body: IdeaCategoryUpsert) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    await run_write(
        "MERGE (c:IdeaCategory {name: $name}) SET c.color = $color",
        name=name, color=body.color,
    )
    await record("idea", "kind saved", detail=f"{name} {body.color}")
    return {"name": name, "color": body.color}


@router.delete("/categories/{name}", status_code=204, response_class=Response)
async def delete_category(name: str) -> Response:
    """Removes the kind. Ideas already tagged with it keep the text, they just
    fall back to the neutral colour."""
    await run_write("MATCH (c:IdeaCategory {name: $name}) DELETE c", name=name)
    await record("idea", "kind deleted", detail=name)
    return Response(status_code=204)


def _shape(node: dict, sessions: list[dict], given=None, came=None) -> dict:
    """An idea plus everything logged against it — one card's worth of data."""
    out = dict(node)
    # Both edges are read, never written as columns: the table shows a project
    # name, but the truth is the relationship, so nothing here can drift from it.
    out["given_to"] = dict(given) if given and given.get("id") else None
    out["came_from"] = dict(came) if came and came.get("id") else None
    sessions = [s for s in sessions if s.get("id")]
    sessions.sort(key=lambda s: (s.get("date") or "", s.get("start") or ""), reverse=True)
    out["sessions"] = sessions
    out["total_mins"] = sum(s.get("mins") or 0 for s in sessions)
    out["session_count"] = len(sessions)
    out["last_worked"] = sessions[0]["date"] if sessions else None
    return out


@router.get("")
async def list_ideas() -> list[dict]:
    # Manual row order (position ascending); un-positioned rows fall to the
    # bottom, newest first. Work sessions ride along so the expanded card can
    # show time spent without a second round trip.
    await _reconcile_provenance()
    rows = await run_read(
        """
        MATCH (i:Idea)
        OPTIONAL MATCH (w:WorkSession)-[:ON]->(i)
        WITH i, collect(w{.*}) AS sessions
        OPTIONAL MATCH (i)-[g:GIVEN_TO]->(gp:Project)
        WITH i, sessions, gp{.id, .name, date: g.date} AS given
        OPTIONAL MATCH (i)-[c:CAME_FROM]->(src)
        RETURN i, sessions, given,
               CASE WHEN src IS NULL THEN null ELSE {
                 id: src.id, name: coalesce(src.name, src.title, '(untitled)'),
                 label: head(labels(src)), date: c.date } END AS came
        ORDER BY coalesce(i.position, 1e15) ASC, i.created_at DESC
        """
    )
    return [_shape(r["i"], r["sessions"], r["given"], r["came"]) for r in rows]


async def _reconcile_provenance() -> None:
    """Draw CAME_FROM for ideas that still only carry the old `paper_id`.

    On read rather than as a migration, for the reason `_absorb` in phases.py is:
    it is one MERGE, it is idempotent, and it heals an idea whose paper_id was
    set by some other route that knows nothing about this edge.
    """
    await run_write(
        """
        MATCH (i:Idea) WHERE coalesce(i.paper_id, '') <> ''
          AND NOT (i)-[:CAME_FROM]->()
        MATCH (p:Paper {id: i.paper_id})
        MERGE (i)-[r:CAME_FROM]->(p)
          ON CREATE SET r.date = left(coalesce(i.created_at, ''), 10)
        """)


@router.get("/columns")
async def known_columns() -> dict:
    """Union of all property keys across ideas — lets the grid show custom cols."""
    rows = await run_read("MATCH (i:Idea) RETURN keys(i) AS ks")
    cols: set[str] = set()
    for r in rows:
        cols.update(r["ks"])
    return {"columns": sorted(cols)}


@router.post("", status_code=201)
async def create_idea(body: IdeaCreate) -> dict:
    props = body.model_dump(exclude_none=True)
    props.pop("id", None)
    iid = str(uuid.uuid4())
    props["id"] = iid
    props["created_at"] = datetime.now(timezone.utc).isoformat()
    # An idea is an Inbox row with kind='idea'. Carrying both labels and the
    # kind here means an idea captured from the quick-capture panel or from a
    # paper shows up in the Inbox like any other, rather than becoming a row
    # only this router can see.
    props.setdefault("kind", "idea")
    props.setdefault("status", "raw")
    # A double click on "+ add idea" used to make two rows. See
    # inbox.recent_duplicate.
    for k, v in (("low_h", 0.0), ("high_h", 0.0), ("due", "")):
        props.setdefault(k, v)
    from routes.inbox import capture_lock, recent_duplicate
    async with capture_lock:
        dup = await recent_duplicate((props.get("title") or "").strip(), props["kind"])
        if dup:
            rows = await run_read("MATCH (i:Task {id: $id}) RETURN i", id=dup)
            return dict(rows[0]["i"])
        # New rows land at the top of the manual order.
        rows = await run_write(
            """
            OPTIONAL MATCH (x:Idea)
            WITH coalesce(min(x.position), 0.0) - 1.0 AS pos
            CREATE (i:Idea:Task $props) SET i.position = pos
            RETURN i
            """,
            props=props,
        )
    await record("idea", "created", detail=props.get("title", "")[:80])
    return dict(rows[0]["i"])


@router.post("/reorder")
async def reorder_ideas(body: ReorderRequest) -> dict:
    pairs = await reorder_nodes("Idea", body.ids)
    await record("idea", "reordered", detail=f"{len(pairs)} rows")
    return {"ok": True, "positions": pairs}


@router.patch("/{idea_id}")
async def update_idea(idea_id: str, patch: IdeaUpdate) -> dict:
    fields = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if k not in _RESERVED}
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"i.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (i:Idea {{id: $id}}) SET {sets} RETURN i", id=idea_id, **fields)
    if not rows:
        raise HTTPException(404, "idea not found")
    await record("idea", "updated", detail=", ".join(fields))
    return dict(rows[0]["i"])


@router.delete("/{idea_id}", status_code=204, response_class=Response)
async def delete_idea(idea_id: str) -> Response:
    await run_write("MATCH (i:Idea {id: $id}) DETACH DELETE i", id=idea_id)
    await record("idea", "deleted", detail=idea_id)
    return Response(status_code=204)


@router.get("/export")
async def export_ideas(format: str = "json") -> Response:
    # flat rows only — the session list is a nested structure, and `total_mins`
    # is kept as a plain column so time spent still exports
    rows = await list_ideas()
    ideas = [{k: v for k, v in r.items() if k not in _COMPUTED or k == "total_mins"} for r in rows]
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if format == "csv":
        cols: list[str] = []
        for it in ideas:
            for k in it:
                if k not in cols:
                    cols.append(k)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ideas)
        data = buf.getvalue()
        (settings.exports_dir / f"ideas-{stamp}.csv").write_text(data)
        return Response(data, media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=ideas-{stamp}.csv"})
    (settings.exports_dir / f"ideas-{stamp}.json").write_text(json.dumps(ideas, indent=2))
    return JSONResponse(ideas)


# =========================================================================== #
# WHERE IT WENT, WHERE IT CAME FROM
# =========================================================================== #

@router.post("/{idea_id}/given-to")
async def set_given_to(idea_id: str, body: IdeaGivenTo) -> dict:
    """Hand an idea to a project, or take it back.

    An idea is given to one project at a time. Handing it somewhere else moves
    the edge rather than adding a second: "given to two projects" is not a state
    anyone means, it is a decision that has not been made.

    The row is not removed and the idea is not marked done. It goes grey and
    names the project, because a table you delete from stops being a record of
    what you thought.
    """
    rows = await run_read("MATCH (i:Idea {id: $id}) RETURN i.title AS title", id=idea_id)
    if not rows:
        raise HTTPException(404, "no such idea")
    title = rows[0]["title"] or "(untitled)"

    if not body.project_id:
        await run_write(
            "MATCH (i:Idea {id: $id})-[r:GIVEN_TO]->() DELETE r "
            "SET i.status = 'raw'", id=idea_id)
        await record("idea", "taken back", detail=title[:70], entity_id=idea_id)
        return await _one(idea_id)

    made = await run_write(
        """
        MATCH (i:Idea {id: $id}), (p:Project {id: $pid})
        OPTIONAL MATCH (i)-[old:GIVEN_TO]->() DELETE old
        WITH i, p
        MERGE (i)-[r:GIVEN_TO]->(p)
          ON CREATE SET r.date = $today
        SET i.status = 'given'
        RETURN p.name AS name
        """, id=idea_id, pid=body.project_id,
        today=datetime.now(timezone.utc).date().isoformat())
    if not made:
        raise HTTPException(404, "no such project")
    await record("idea", "given to a project",
                 detail=f"{title[:40]} → {made[0]['name']}"[:70], entity_id=idea_id)
    return await _one(idea_id)


@router.post("/{idea_id}/came-from")
async def set_came_from(idea_id: str, body: IdeaCameFrom) -> dict:
    """Say what an idea came out of: a paper or a project, one edge either way.

    Setting a paper keeps `i.paper_id` in step, because instances.py reads that
    property and the table still shows it as a column. Setting a project clears
    the property, since the idea no longer came from a paper.
    """
    label = "Project" if body.kind == "project" else "Paper"
    if not body.source_id:
        await run_write(
            "MATCH (i:Idea {id: $id})-[r:CAME_FROM]->() DELETE r "
            "SET i.paper_id = ''", id=idea_id)
        await record("idea", "source cleared", detail=idea_id, entity_id=idea_id)
        return await _one(idea_id)

    made = await run_write(
        f"""
        MATCH (i:Idea {{id: $id}}), (src:{label} {{id: $sid}})
        OPTIONAL MATCH (i)-[old:CAME_FROM]->() DELETE old
        WITH i, src
        MERGE (i)-[r:CAME_FROM]->(src)
          ON CREATE SET r.date = $today
        SET i.paper_id = CASE WHEN $is_paper THEN src.id ELSE '' END
        RETURN coalesce(src.name, src.title, '(untitled)') AS name
        """, id=idea_id, sid=body.source_id, is_paper=(label == "Paper"),
        today=datetime.now(timezone.utc).date().isoformat())
    if not made:
        raise HTTPException(404, f"no such idea or {body.kind}")
    await record("idea", "source set",
                 detail=f"from {made[0]['name']}"[:70], entity_id=idea_id)
    return await _one(idea_id)


async def _one(idea_id: str) -> dict:
    """One idea, shaped the same way the list shapes them, so a row the client
    swaps in after a write is identical to one it would get on a reload."""
    rows = await run_read(
        """
        MATCH (i:Idea {id: $id})
        OPTIONAL MATCH (w:WorkSession)-[:ON]->(i)
        WITH i, collect(w{.*}) AS sessions
        OPTIONAL MATCH (i)-[g:GIVEN_TO]->(gp:Project)
        WITH i, sessions, gp{.id, .name, date: g.date} AS given
        OPTIONAL MATCH (i)-[c:CAME_FROM]->(src)
        RETURN i, sessions, given,
               CASE WHEN src IS NULL THEN null ELSE {
                 id: src.id, name: coalesce(src.name, src.title, '(untitled)'),
                 label: head(labels(src)), date: c.date } END AS came
        """, id=idea_id)
    if not rows:
        raise HTTPException(404, "no such idea")
    r = rows[0]
    return _shape(r["i"], r["sessions"], r["given"], r["came"])
