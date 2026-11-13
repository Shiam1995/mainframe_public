"""/api/rows — the + rows: notes, things to look into, follow-ups, goals.

    (:Row {id, text, kind, created_at})
    (:Row)-[:ON]->(anything)            what it was written on
    (:Task)-[:CAME_FROM]->(:Row)        its Inbox row

THE SAME SHAPE AS A QUESTION, so the one ListBox serves every box: GET
?parent_id=&kind=, POST {text, kind, parent_id}, PATCH /:id, DELETE /:id.
Questions keep their own store because they are answered; a row is just
written down, and the Questions tab should not fill up with notes.

ONE THOUGHT PER NODE. These used to be textareas, and five notes in one box
were one string that nothing could count, tick or carry forward. A row per
thought is what lets each one turn up in the Inbox on its own.

NOTES STAY IN THEIR OWN AREA (2026-11-08). A row used to file an Inbox note
automatically; it no longer does. Each row carries
    area    the module it was written in — Synapse | Pulse | Vault | Vision,
            or '' on a shared tab. Sent by the page; derived from the parent's
            label when it is not (AREA_OF below).
    intent  log | idea | task. Every row starts as `log`: a record kept where
            it was written.
    done    for to-do boxes ("look into": check reference X, reread §3) — a
            tick on the row itself, shown only where the row lives.
The rare row that needs action is sent with its "→ Inbox" button:
POST /{id}/inbox makes a new Inbox task with (:Task)-[:CAME_FROM]->(:Row) and
the row stays put. `inbox: true` on create still files one, for a caller that
really means it.

`kind` is the box. One node can carry several boxes (a workout has notes; a
medical record has notes and follow-ups), and the box only ever reads its own.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import match_by_id, record
from db import run_read, run_write
from models import RowCreate, RowUpdate
from routes.inbox import create_row

router = APIRouter(prefix="/api/rows", tags=["rows"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ROWS = """
MATCH (r:Row)
WHERE $$WHERE$$
OPTIONAL MATCH (r)-[:ON]->(x)
// the Inbox task this row was sent to, if any — a comprehension, so a row
// with two Inbox rows (an old auto-filed note + a sent task) is still one row
WITH r, x, [(t:Task)-[:CAME_FROM]->(r) | t] AS ts
RETURN r{.*} AS r, x.id AS on_id,
       head([t IN ts WHERE t.kind = 'task' | t.id] + [t IN ts | t.id]) AS task_id
ORDER BY r.created_at, r.id
"""


async def _sync_tools(node_id: str | None) -> None:
    """A pipeline stage's tool rows are also its (:Tool) edges. Tools are
    shared nodes so "what am I using Claude for?" is one query across every
    pipeline (routes/vision.py); the rows are how you type them now, so the
    edges are redrawn from the rows whenever one changes."""
    if not node_id:
        return
    await run_write(
        """
        MATCH (s:PipelineStage {id: $sid})
        OPTIONAL MATCH (s)-[u:USES_TOOL]->(:Tool)
        DELETE u
        WITH DISTINCT s
        MATCH (r:Row {kind: 'tool'})-[:ON]->(s)
        MERGE (t:Tool {name: r.text})
        MERGE (s)-[:USES_TOOL]->(t)
        """, sid=node_id)
    await run_write("MATCH (t:Tool) WHERE NOT (t)<-[:USES_TOOL]-() DETACH DELETE t")


# A row whose page did not say which module it is in gets the module of the
# thing it is written on. Unknown labels get '' (shared / unknown).
AREA_OF = {
    "Instance": "Synapse", "Paper": "Synapse", "Project": "Synapse",
    "DeepDive": "Synapse", "Assumption": "Synapse", "Benchmark": "Synapse",
    "Workout": "Pulse", "Cycle": "Pulse", "StretchSession": "Pulse",
    "Program": "Pulse", "Recipe": "Pulse", "Supplement": "Pulse",
    "Medication": "Pulse", "MedicalRecord": "Pulse", "Intolerance": "Pulse",
    "Investment": "Vault", "Account": "Vault", "Transaction": "Vault",
    "PipelineStage": "Vision", "Storyboard": "Vision", "Blueprint": "Vision",
}
AREAS = ("Synapse", "Pulse", "Vault", "Vision", "")
INTENTS = ("log", "idea", "task")


def _shape(rec: dict) -> dict:
    r = dict(rec["r"])
    r["kind"] = r.get("kind") or "note"
    r["area"] = r.get("area") or ""
    r["intent"] = r.get("intent") or "log"
    r["done"] = bool(r.get("done"))
    r["parent_id"] = rec.get("on_id")
    r["task_id"] = rec.get("task_id")
    return r


@router.get("")
async def list_rows(parent_id: str | None = None, parent_ids: str | None = None,
                    kind: str | None = None) -> list[dict]:
    """One box's rows (`parent_id` + `kind`), or every row on a page of cards
    at once (`parent_ids` comma-separated) so a list of twenty workouts is one
    read rather than twenty."""
    where, params = ["true"], {}
    if parent_id:
        where.append("EXISTS { MATCH (r)-[:ON]->(n) WHERE n.id = $pid }")
        params["pid"] = parent_id
    if parent_ids:
        ids = [p for p in parent_ids.split(",") if p]
        where.append("EXISTS { MATCH (r)-[:ON]->(n) WHERE n.id IN $pids }")
        params["pids"] = ids
    if kind:
        where.append("coalesce(r.kind, 'note') = $kind")
        params["kind"] = kind
    rows = await run_read(_ROWS.replace("$$WHERE$$", " AND ".join(where)), **params)
    return [_shape(r) for r in rows]


@router.get("/todo-counts")
async def todo_counts() -> dict:
    """Open to-do rows per paper, for the "2 to check" on Repository cards.

    A to-do row is a "look into" row that is not done, written on the paper or
    on one of its reading instances."""
    rows = await run_read(
        """
        MATCH (r:Row)-[:ON]->(x)
        WHERE r.kind = 'look into' AND coalesce(r.done, false) = false
          AND (x:Paper OR x:Instance)
        OPTIONAL MATCH (p0:Paper)-[:HAS_INSTANCE]->(x)
        WITH coalesce(p0, CASE WHEN x:Paper THEN x END) AS p, r
        WHERE p IS NOT NULL
        RETURN p.id AS id, count(DISTINCT r) AS n
        """)
    return {r["id"]: r["n"] for r in rows}


@router.post("", status_code=201)
async def add_row(body: RowCreate) -> dict:
    """The row and its edge. No Inbox row unless `inbox` is True — see the
    module docstring."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "a row with no text is not a row")
    kind = (body.kind or "note").strip() or "note"
    intent = body.intent if body.intent in INTENTS else "log"
    rid = str(uuid.uuid4())
    await run_write(
        "CREATE (r:Row {id: $id, text: $text, kind: $kind, created_at: $now, "
        "intent: $intent, done: false})",
        id=rid, text=text, kind=kind, now=_now(), intent=intent)
    if body.parent_id:
        await run_write(
            "MATCH (r:Row {id: $id}) " + match_by_id("pid", "n")
            + " WITH r, n WHERE NOT n:Row MERGE (r)-[:ON]->(n)",
            id=rid, pid=body.parent_id)
    area = body.area if body.area in AREAS else None
    if area is None:
        lab = await run_read(
            "MATCH (:Row {id: $id})-[:ON]->(n) RETURN labels(n) AS l", id=rid)
        labels = lab[0]["l"] if lab else []
        area = next((AREA_OF[l] for l in labels if l in AREA_OF), "")
    await run_write("MATCH (r:Row {id: $id}) SET r.area = $area", id=rid, area=area)
    if body.inbox is True:
        # came_from is the thing it was written on, so the Inbox says "from
        # Leg day" rather than "from a row"; the :Row edge is drawn after.
        tid = await create_row(text, "note", kind, came_from=body.parent_id)
        await run_write(
            "MATCH (t:Task {id: $tid}), (r:Row {id: $rid}) "
            "MERGE (t)-[:CAME_FROM]->(r)", tid=tid, rid=rid)
    await record("inbox", f"{kind} added", detail=text[:70], entity_id=rid)
    rows = await run_read(_ROWS.replace("$$WHERE$$", "r.id = $id"), id=rid)
    out = _shape(rows[0])
    if kind == "tool":
        await _sync_tools(out["parent_id"])
    return out


@router.patch("/{rid}")
async def update_row(rid: str, patch: RowUpdate) -> dict:
    """Editing the words, or ticking a to-do row. An old auto-filed Inbox note
    follows a text edit while it is still open; a task sent with "→ Inbox" does
    not — it is its own row now, worded for doing."""
    if patch.text is None and patch.done is None:
        raise HTTPException(400, "nothing to update")
    if not await run_read("MATCH (r:Row {id: $id}) RETURN r.id AS id", id=rid):
        raise HTTPException(404, "no such row")
    if patch.text is not None:
        text = patch.text.strip()
        if not text:
            raise HTTPException(400, "a row with no text is not a row")
        await run_write("MATCH (r:Row {id: $id}) SET r.text = $text", id=rid, text=text)
        await run_write(
            "MATCH (t:Task {status: 'open', kind: 'note'})-[:CAME_FROM]->(r:Row {id: $id}) "
            "SET t.title = $text", id=rid, text=text)
    if patch.done is not None:
        await run_write(
            "MATCH (r:Row {id: $id}) SET r.done = $d, r.done_at = $at",
            id=rid, d=patch.done, at=_now() if patch.done else "")
    rows = await run_read(_ROWS.replace("$$WHERE$$", "r.id = $id"), id=rid)
    out = _shape(rows[0])
    if out["kind"] == "tool":
        await _sync_tools(out["parent_id"])
    return out


@router.post("/{rid}/inbox", status_code=201)
async def send_to_inbox(rid: str) -> dict:
    """"→ Inbox": the rare note that needs action becomes a real Inbox task.

    A NEW :Task with (:Task)-[:CAME_FROM]->(:Row). The row stays exactly where
    it is; pressing it twice returns the task already made rather than a second.
    """
    rows = await run_read(
        "MATCH (r:Row {id: $id}) "
        "OPTIONAL MATCH (t:Task {kind: 'task'})-[:CAME_FROM]->(r) "
        "RETURN r.text AS text, r.kind AS kind, t.id AS tid", id=rid)
    if not rows:
        raise HTTPException(404, "no such row")
    tid = rows[0]["tid"]
    if not tid:
        tid = await create_row(rows[0]["text"], "task", rows[0]["kind"] or "",
                               came_from=rid)
        await record("inbox", "note sent to Inbox", detail=rows[0]["text"][:70],
                     entity_id=rid)
    rows = await run_read(_ROWS.replace("$$WHERE$$", "r.id = $id"), id=rid)
    out = _shape(rows[0])
    out["task_id"] = tid
    return out


@router.delete("/{rid}", status_code=204, response_class=Response)
async def delete_row(rid: str) -> Response:
    """Deletes the row. Its Inbox row stays, the same rule questions follow:
    it may have been given to a project and worked on by now."""
    rows = await run_read(_ROWS.replace("$$WHERE$$", "r.id = $id"), id=rid)
    await run_write("MATCH (r:Row {id: $id}) DETACH DELETE r", id=rid)
    if rows and rows[0]["r"].get("kind") == "tool":
        await _sync_tools(rows[0]["on_id"])
    await record("inbox", "row deleted", entity_id=rid)
    return Response(status_code=204)


async def row_texts(parent_ids: list[str]) -> dict[str, dict[str, list[str]]]:
    """{parent id: {kind: [text, ...]}} for every row on these nodes, in the
    order written. For the read-only views (a master record, a chip's hover)
    that used to print the old textarea string and now print its rows."""
    ids = [p for p in parent_ids if p]
    if not ids:
        return {}
    rows = await run_read(
        """
        MATCH (r:Row)-[:ON]->(n) WHERE n.id IN $ids
        RETURN n.id AS pid, coalesce(r.kind, 'note') AS kind, r.text AS text
        ORDER BY r.created_at, r.id
        """, ids=ids)
    out: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        out.setdefault(r["pid"], {}).setdefault(r["kind"], []).append(r["text"] or "")
    return out
