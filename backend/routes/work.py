"""/api/work — the Mainframe-level work database.

One :WorkSession node per block of work. This is the single table every module
pushes into, and the same rows drive the contribution grid:

  time worked that day  → how dark the square is
  a contributing project worked on → the square gets a border
  a push → the square gets a star

Every session carries the full field set. Anything that doesn't apply to a given
row is masked (0 / "" / "none") rather than omitted, so the table stays one
uniform grid instead of going ragged per row type.

Sessions attached to a project are linked `(:WorkSession)-[:ON]->(:Project)` so
the project's master view can aggregate them; sessions on anything else keep the
reference denormalised in ref_kind/ref_id/ref_title.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from activity import record
from db import run_read, run_write
from workimport import parse_rows
from models import (DEFAULT_WORK_TYPE, WorkKindCreate, WorkSessionCreate,
                    WorkSessionUpdate)

router = APIRouter(prefix="/api/work", tags=["work"])

# every column, in the order the table shows them — also the CSV header order.
# distraction_mins/distraction were dropped from the table (the reading
# workspace records distractions properly, one entry each); the properties are
# still accepted and still on old rows, they're just no longer a column here.
COLUMNS = [
    "date", "start", "end", "mins", "module", "ref_kind", "ref_title",
    "kind", "what", "focus", "notes", "completed",
]

# Seeded on first run; add your own with POST /api/work/kinds.
DEFAULT_KINDS = ["project", "task", "idea", "paper", "document", "habit", "other"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _mins_between(start: str, end: str) -> int:
    """Duration from HH:MM..HH:MM. Crossing midnight wraps to the next day."""
    try:
        sh, sm = (int(x) for x in start.split(":")[:2])
        eh, em = (int(x) for x in end.split(":")[:2])
    except (ValueError, AttributeError):
        return 0
    delta = (eh * 60 + em) - (sh * 60 + sm)
    if delta < 0:
        delta += 24 * 60
    return delta


async def _derive_kind(kind: Optional[str], ref_kind: Optional[str],
                       ref_id: Optional[str]) -> str:
    """What kind of work this was: study | build | admin | body.

    Sent explicitly, that wins — the whole point of the segmented control on a
    push is that an hour of reading logged against a build project is study.
    Otherwise it is inherited from the project, so the common case costs
    nothing. A session on nothing, or on a project that predates the type,
    falls back to the default rather than to null: the column is a filter and
    a total, and a null would drop the row out of both.
    """
    if kind:
        return kind
    if ref_kind == "project" and ref_id:
        rows = await run_read(
            "MATCH (p:Project {id: $id}) RETURN p.kind AS kind", id=ref_id)
        if rows and rows[0]["kind"]:
            return rows[0]["kind"]
    return DEFAULT_WORK_TYPE


def _derive_mins(mins: int, start: str, end: str) -> int:
    """Explicit `mins` wins; otherwise infer it from start/end if both are set."""
    if mins:
        return max(0, mins)
    if start and end:
        return _mins_between(start, end)
    return 0


# --------------------------------------------------------------------------- #
# List — filterable; the table and every aggregate read through this
# --------------------------------------------------------------------------- #
@router.get("")
async def list_sessions(
    start: Optional[str] = None,      # inclusive YYYY-MM-DD
    end: Optional[str] = None,        # inclusive YYYY-MM-DD
    module: Optional[str] = None,
    ref_id: Optional[str] = None,
    ref_kind: Optional[str] = None,
    kind: Optional[str] = None,       # study | build | admin | body
    limit: int = 2000,
) -> list[dict]:
    where = []
    params: dict = {"limit": max(1, min(limit, 10000))}
    if start:
        where.append("w.date >= $start")
        params["start"] = start
    if end:
        where.append("w.date <= $end")
        params["end"] = end
    if module:
        where.append("w.module = $module")
        params["module"] = module
    if ref_id:
        where.append("w.ref_id = $ref_id")
        params["ref_id"] = ref_id
    if ref_kind:
        where.append("w.ref_kind = $ref_kind")
        params["ref_kind"] = ref_kind
    if kind:
        where.append("w.kind = $kind")
        params["kind"] = kind
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await run_read(
        f"""
        MATCH (w:WorkSession)
        {clause}
        RETURN w{{.*}} AS w
        ORDER BY w.date DESC, coalesce(w.start, '') DESC, w.created_at DESC
        LIMIT $limit
        """,
        **params,
    )
    return [r["w"] for r in rows]


# --------------------------------------------------------------------------- #
# Per-day rollup — what the contribution grid draws
# --------------------------------------------------------------------------- #
@router.get("/days")
async def day_summary() -> dict:
    """date → {mins, sessions, pushed, contributed, modules}.

    `contributed` is true when at least one session that day was on a project
    flagged `contributes` (border on the square). `pushed` is true when any
    session that day was a push (star on the square).
    """
    rows = await run_read(
        """
        MATCH (w:WorkSession)
        OPTIONAL MATCH (w)-[:ON]->(p:Project)
        WITH w.date AS day,
             sum(coalesce(w.mins, 0)) AS mins,
             count(w) AS sessions,
             sum(CASE WHEN coalesce(w.completed, w.pushed, false) THEN 1 ELSE 0 END) AS pushes,
             sum(CASE WHEN coalesce(p.contributes, false) THEN 1 ELSE 0 END) AS contribs,
             collect(DISTINCT w.module) AS modules
        WHERE day IS NOT NULL
        RETURN day, mins, sessions, pushes, contribs, modules
        """
    )
    return {
        r["day"]: {
            "mins": r["mins"] or 0,
            "sessions": r["sessions"] or 0,
            "pushed": (r["pushes"] or 0) > 0,
            "contributed": (r["contribs"] or 0) > 0,
            "modules": [m for m in (r["modules"] or []) if m],
        }
        for r in rows
    }


# --------------------------------------------------------------------------- #
# Create / update / delete
# --------------------------------------------------------------------------- #
@router.post("", status_code=201)
async def create_session(body: WorkSessionCreate) -> dict:
    wid = str(uuid.uuid4())
    data = body.model_dump()
    data["id"] = wid
    data["date"] = body.date or _today()
    data["mins"] = _derive_mins(body.mins, body.start, body.end)
    data["kind"] = await _derive_kind(body.kind, body.ref_kind, body.ref_id)
    data["created_at"] = _now()
    # The document lives on a relationship, not on the node — drop it before the
    # CREATE so it isn't also sitting there as a second, driftable copy.
    data.pop("doc_id", None)
    await run_write(
        """
        CREATE (w:WorkSession {
            id: $id, date: $date, start: $start, end: $end, mins: $mins,
            module: $module, ref_kind: $ref_kind, ref_id: $ref_id,
            ref_title: $ref_title, kind: $kind, what: $what, focus: $focus,
            distraction_mins: $distraction_mins, distraction: $distraction,
            notes: $notes, completed: $completed, pushed: $pushed,
            pass_id: $pass_id, instance_id: $instance_id, created_at: $created_at
        })
        """,
        **data,
    )
    await _link_ref(wid, body.ref_kind, body.ref_id)
    await _link_doc(wid, body.doc_id)
    await record(
        # File the event under what the work was ON, when that's a category the
        # activity log knows; everything else reads as ordinary logged work.
        body.ref_kind if body.ref_kind in ("project", "document") else "task",
        "completed" if (body.completed or body.pushed) else "work logged",
        detail=f"{data['mins']}m · {(body.what or body.ref_title)[:60]}",
        module=body.module if body.module != "mainframe" else None,
        entity_id=body.ref_id,
    )
    return await _get_one(wid)


@router.patch("/{session_id}")
async def update_session(session_id: str, patch: WorkSessionUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        return await _get_one(session_id)
    # keep mins consistent when the clock times move
    if ("start" in fields or "end" in fields) and "mins" not in fields:
        cur = await _get_one(session_id)
        s = fields.get("start", cur.get("start") or "")
        e = fields.get("end", cur.get("end") or "")
        if s and e:
            fields["mins"] = _mins_between(s, e)
    sets = ", ".join(f"w.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (w:WorkSession {{id: $id}}) SET {sets} RETURN w",
        id=session_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "work session not found")
    if "ref_id" in fields or "ref_kind" in fields:
        cur = await _get_one(session_id)
        await run_write("MATCH (:WorkSession {id: $id})-[r:ON]->() DELETE r", id=session_id)
        await _link_ref(session_id, cur.get("ref_kind"), cur.get("ref_id"))
    await record("task", "work edited", detail=", ".join(fields))
    return await _get_one(session_id)


# --------------------------------------------------------------------------- #
# The logging gap — work you did that never became a row in this table
#
# Two records already exist and are never otherwise compared: the `:ChangeEvent`
# trail (what you *did*) and `:WorkSession` rows (what you *logged*). Anything
# done after the last session you logged is, by definition, time that isn't in
# the database. Everything below is derived and read-only — nothing is written
# or guessed.
#
# Events reach their subject through `(:Entity)-[:HAS_CHANGE]->(:ChangeEvent)`,
# drawn by activity.record() for every `paper_id`/`entity_id` it's given. The
# `c.paper_id` property is kept as a second route in for events written before
# an entity existed to hang them off.
# --------------------------------------------------------------------------- #

# Only events that represent doing something. "viewed"-style status rows and the
# work log's own entries would otherwise make every item look unlogged.
_REAL_WORK = """
    coalesce(c.category,'') <> 'status'
    AND NOT coalesce(c.action,'') IN ['work logged', 'completed', 'pushed']
"""

# What counts as an "item" in the sweep: the things a session can be logged
# against (TARGET_LABELS, below) — anything else has nowhere for the time to go,
# so calling it unlogged would be noise you can't act on.
_GAP_LABELS = ["Paper", "Project", "Task", "Idea", "Document", "Habit"]
# Label expression for a start pattern — one indexed seek per label.
_GAP_MATCH = "|".join(_GAP_LABELS)
_LABEL_KIND = {
    "Paper": "paper", "Project": "project", "Task": "task",
    "Idea": "idea", "Document": "document", "Habit": "habit",
}
# How many example events each item carries back. The count is exact; this only
# caps what the panel lists underneath it.
_SAMPLE = 12


@router.get("/gap")
async def logging_gap(ref_id: str) -> dict:
    """The logging gap for one thing. See the block comment above."""
    sessions = await run_read(
        """
        MATCH (w:WorkSession {ref_id: $id})
        RETURN w.date AS date, coalesce(w.mins,0) AS mins, w.created_at AS created_at
        ORDER BY coalesce(w.created_at,'') DESC
        """,
        id=ref_id,
    )
    total = sum(int(s["mins"] or 0) for s in sessions)
    last = sessions[0]["created_at"] if sessions else None

    events = await run_read(
        f"""
        MATCH (c:ChangeEvent)
        WHERE {_REAL_WORK}
          AND ($since IS NULL OR coalesce(c.timestamp,'') > $since)
          AND (c.paper_id = $id
               OR EXISTS {{ MATCH (:{_GAP_MATCH} {{id: $id}})-[:HAS_CHANGE]->(c) }})
        RETURN c.timestamp AS ts, c.category AS category, c.action AS action, c.detail AS detail
        ORDER BY ts DESC LIMIT 50
        """,
        id=ref_id, since=last,
    )
    return {
        "ref_id": ref_id,
        "sessions": len(sessions),
        "total_mins": total,
        "last_logged_at": last,
        "unlogged_count": len(events),
        "unlogged": [{"timestamp": e["ts"], "category": e["category"],
                      "action": e["action"], "detail": e["detail"]} for e in events],
    }


@router.get("/gaps")
async def logging_gaps(limit: int = 60) -> dict:
    """The same question asked of everything at once — what the topbar ⏱ reads.

    One item per thing with outstanding work, newest activity first. The per-item
    shape matches /gap so the panel and a single item's own check can't drift.
    """
    rows = await run_read(
        f"""
        MATCH (e)-[:HAS_CHANGE]->(:ChangeEvent)
        WHERE any(l IN labels(e) WHERE l IN $labels) AND e.id IS NOT NULL
        WITH DISTINCT e
        // What's already logged against it — one row even when nothing is.
        CALL (e) {{
          MATCH (w:WorkSession {{ref_id: e.id}})
          RETURN count(w) AS sessions, sum(coalesce(w.mins,0)) AS mins,
                 max(coalesce(w.created_at,'')) AS last
        }}
        WITH e, sessions, mins, coalesce(last, '') AS since
        // …and what's happened since. Counted in full, sampled for display.
        CALL (e, since) {{
          MATCH (e)-[:HAS_CHANGE]->(c:ChangeEvent)
          WHERE {_REAL_WORK}
            AND (since = '' OR coalesce(c.timestamp,'') > since)
          WITH c ORDER BY coalesce(c.timestamp,'') DESC
          RETURN count(c) AS n, collect(c.module)[0] AS module,
                 collect({{timestamp: c.timestamp, category: c.category,
                          action: c.action, detail: c.detail}})[0..$sample] AS sample
        }}
        WITH e, sessions, mins, since, n, module, sample
        WHERE n > 0
        RETURN e.id AS ref_id, labels(e) AS labels, module,
               coalesce(e.title, e.name, e.message, '(untitled)') AS title,
               sessions, mins, since, n, sample
        ORDER BY sample[0].timestamp DESC
        LIMIT $limit
        """,
        labels=_GAP_LABELS, sample=_SAMPLE, limit=max(1, min(limit, 500)),
    )
    items = []
    for r in rows:
        kind = next((_LABEL_KIND[l] for l in r["labels"] if l in _LABEL_KIND), "other")
        items.append({
            "ref_id": r["ref_id"],
            "ref_kind": kind,
            "ref_title": r["title"],
            "module": r["module"] or "mainframe",
            "sessions": r["sessions"],
            "total_mins": r["mins"],
            "last_logged_at": r["since"] or None,
            "unlogged_count": r["n"],
            "unlogged": r["sample"],
        })
    return {
        "items": items,
        "item_count": len(items),
        "total": sum(i["unlogged_count"] for i in items),
    }


# --------------------------------------------------------------------------- #
# Kinds — what a session can be ON. User-extensible.
# --------------------------------------------------------------------------- #
# What a session can point AT, per kind: the label to match and the property
# holding its display name. The timer dock reads this to let you pick the thing
# you're timing instead of retyping its name.
TARGET_LABELS = {
    "project": ("Project", "name"),
    "task": ("Task", "title"),
    "idea": ("Idea", "title"),
    "paper": ("Paper", "title"),
    "document": ("Document", "title"),
    "habit": ("Habit", "name"),
}


@router.get("/targets")
async def work_targets(kind: str) -> list[dict]:
    """Things of `kind` a session (or a running timer) can be logged against.

    An unknown kind isn't an error — plenty of work is "other", which has no
    entity behind it. It just has nothing to offer, and the caller falls back
    to a free-text label.
    """
    if kind not in TARGET_LABELS:
        return []
    label, prop = TARGET_LABELS[kind]
    rows = await run_read(
        f"MATCH (e:{label}) WHERE e.id IS NOT NULL "
        f"RETURN e.id AS id, e.{prop} AS label "
        f"ORDER BY toLower(coalesce(e.{prop}, '')) LIMIT 400"
    )
    return [{"id": r["id"], "label": r["label"] or "(untitled)"} for r in rows]


@router.get("/kinds")
async def list_kinds() -> list[str]:
    """The seeded kinds plus anything you've added, in use-order then name.

    Seeded on read rather than at startup so a fresh database and an existing
    one behave the same.
    """
    # Seeding on every read rather than only into an empty database, so a kind
    # added to DEFAULT_KINDS in a later version reaches graphs that already
    # exist. MERGE is idempotent, and the built-ins can't be deleted anyway.
    await run_write(
        "UNWIND $names AS n MERGE (:WorkKind {name: n})", names=DEFAULT_KINDS
    )
    rows = await run_read("MATCH (k:WorkKind) RETURN k.name AS name")
    names = [r["name"] for r in rows if r["name"]] or list(DEFAULT_KINDS)
    # Keep the seeded ones in their familiar order; custom ones sort after.
    seeded = [n for n in DEFAULT_KINDS if n in names]
    custom = sorted(n for n in names if n not in DEFAULT_KINDS)
    return seeded + custom


@router.post("/kinds", status_code=201)
async def create_kind(body: WorkKindCreate) -> list[str]:
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(400, "a kind needs a name")
    if len(name) > 24:
        raise HTTPException(400, "keep a kind short — it's a column value, not a sentence")
    await run_write("MERGE (:WorkKind {name: $name})", name=name)
    await record("task", "work kind added", detail=name)
    return await list_kinds()


@router.delete("/kinds/{name}", status_code=200)
async def delete_kind(name: str) -> list[str]:
    """Remove a kind. Rows already filed under it keep their value — deleting
    the label shouldn't silently rewrite history — they just can't be re-picked
    from the dropdown."""
    if name in DEFAULT_KINDS:
        raise HTTPException(400, "the built-in kinds can't be removed")
    await run_write("MATCH (k:WorkKind {name: $name}) DELETE k", name=name)
    await record("task", "work kind removed", detail=name)
    return await list_kinds()


@router.delete("/{session_id}", status_code=204, response_class=Response)
async def delete_session(session_id: str) -> Response:
    await run_write("MATCH (w:WorkSession {id: $id}) DETACH DELETE w", id=session_id)
    await record("task", "work deleted", detail=session_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# CSV export — the "excel" half of the ask
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Paste many rows at once — preview first, then commit
# --------------------------------------------------------------------------- #
class ImportPreview(BaseModel):
    text: str
    module: str = ""          # fills rows the paste leaves blank
    ref_kind: str = ""
    date: str = ""


class ImportCommit(BaseModel):
    rows: list[WorkSessionCreate]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _match_target(title: str, targets: list[dict]) -> tuple[Optional[dict], list[dict]]:
    """Title → (the one thing it names, or None; the candidates when several).
    Exact (ignoring case and punctuation) first, then a unique containment
    either way round, so "Garden" finds "Home (Garden)"."""
    n = _norm(title)
    if not n:
        return None, []
    exact = [t for t in targets if _norm(t["label"]) == n]
    if len(exact) == 1:
        return exact[0], []
    part = [t for t in targets
            if n in _norm(t["label"]) or (len(_norm(t["label"])) > 3 and _norm(t["label"]) in n)]
    if len(part) == 1:
        return part[0], []
    return None, (exact or part)[:6]


@router.post("/import/preview")
async def import_preview(body: ImportPreview) -> dict:
    """Parse a paste into rows and say what each would become. Saves nothing:
    the grid shows this, you fix what's wrong, and only then /import writes."""
    today = datetime.now().date()   # local, as the table's dates are
    parsed = parse_rows(body.text, today, {
        "module": body.module, "ref_kind": body.ref_kind, "date": body.date})
    rows = parsed["rows"]

    targets: dict[str, list[dict]] = {}

    async def targets_of(kind: str) -> list[dict]:
        if kind not in targets:
            targets[kind] = await work_targets(kind)
        return targets[kind]

    for r in rows:
        r["ref_id"] = None
        r["candidates"] = []
        if not r["ref_title"]:
            r["ref_kind"] = r["ref_kind"] or "other"
            continue
        # A blank kind means "find it": a project by that name, if there is one.
        kind = r["ref_kind"] or "project"
        if kind in TARGET_LABELS:
            hit, cands = _match_target(r["ref_title"], await targets_of(kind))
            if hit:
                r.update(ref_kind=kind, ref_id=hit["id"], ref_title=hit["label"])
                continue
            r["candidates"] = cands
            if cands:
                r["warnings"].append(
                    f"“{r['ref_title']}” matches {len(cands)} {kind}s — pick one")
            else:
                # Free text still saves, but its hours reach no project and
                # so no phase total — say so rather than let it pass quietly.
                r["warnings"].append(
                    f"no {kind} called “{r['ref_title']}” — logs as free text")
        r["ref_kind"] = r["ref_kind"] or "other"

    # Pasting the same block twice is the easy mistake; flag rows that already exist.
    dates = sorted({r["date"] for r in rows})
    if dates:
        have = await run_read(
            "MATCH (w:WorkSession) WHERE w.date IN $dates "
            "RETURN w.date AS date, w.start AS start, w.mins AS mins, "
            "w.ref_id AS ref_id, w.ref_title AS ref_title, w.what AS what",
            dates=dates)
        seen = {(h["date"], h["start"] or "", h["mins"] or 0,
                 h["ref_id"] or _norm(h["ref_title"]), _norm(h["what"])) for h in have}
        for r in rows:
            mins = r["mins"] or _derive_mins(0, r["start"], r["end"])
            if (r["date"], r["start"], mins, r["ref_id"] or _norm(r["ref_title"]),
                    _norm(r["what"])) in seen:
                r["warnings"].append("already in the database — probably a repeat")
                r["duplicate"] = True
    return parsed


@router.post("/import", status_code=201)
async def import_rows(body: ImportCommit) -> dict:
    """Write the rows the preview produced (after your edits), one
    :WorkSession each, through the same path as + new row."""
    if len(body.rows) > 2000:
        raise HTTPException(400, "2000 rows at a time, at most")
    ids = []
    for row in body.rows:
        ids.append((await create_session(row))["id"])
    return {"created": len(ids), "ids": ids}


@router.get("/export.csv")
async def export_csv(start: Optional[str] = None, end: Optional[str] = None) -> Response:
    rows = await list_sessions(start=start, end=end, limit=10000)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in COLUMNS})
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="work.csv"'},
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _link_ref(session_id: str, ref_kind: Optional[str], ref_id: Optional[str]) -> None:
    """Attach the session to its subject so aggregates can traverse the graph."""
    if not ref_id:
        return
    label = {"project": "Project", "task": "Task", "idea": "Idea", "paper": "Paper",
             "document": "Document"}.get(ref_kind or "")
    if not label:
        return
    await run_write(
        f"""
        MATCH (w:WorkSession {{id: $wid}}), (n:{label} {{id: $rid}})
        MERGE (w)-[:ON]->(n)
        """,
        wid=session_id, rid=ref_id,
    )


async def _link_doc(session_id: str, doc_id: Optional[str]) -> None:
    """Say that this session was worked in a document.

    Separate from :ON, which says what the work was *about*. A session pushed
    from inside a doc that is FOR a project is ON the project and WORKED_ON the
    doc: one session, counted once, reachable from both sides.
    """
    if not doc_id:
        return
    await run_write(
        """
        MATCH (w:WorkSession {id: $wid}), (d:Document {id: $did})
        MERGE (w)-[:WORKED_ON]->(d)
        """,
        wid=session_id, did=doc_id,
    )


async def _get_one(session_id: str) -> dict:
    rows = await run_read("MATCH (w:WorkSession {id: $id}) RETURN w{.*} AS w", id=session_id)
    if not rows:
        raise HTTPException(404, "work session not found")
    return rows[0]["w"]
