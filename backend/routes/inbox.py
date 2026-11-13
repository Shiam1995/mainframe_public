"""/api/synapse/inbox and /api/synapse/tree — one leaf node type, one tree.

THE MODEL, in four sentences.

    (:Project {name, done_when, low_h, high_h, due})  nests to any depth:
        (:Project)-[:CHILD_OF]->(:Project)
    (:Task {title, kind, status, low_h, high_h, due}) is the leaf. One node
        serves both the Inbox row and the tree task; a tree task is simply a
        Task carrying (:Task)-[:GIVEN_TO]->(:Project).
    (:Task)-[:CAME_FROM]->(:Project)  an offshoot: the project made you think
        of it.
    (:Task)-[:BECAME]->(:Project)     promote (idea) and grow (task).

`kind` is idea | task and flips in place, which is the whole reason the two
tables became one: an idea that turns out to be a piece of work should not have
to be retyped as a different kind of row, losing its notes and its provenance
on the way.

TWO LABELS, ONE NODE. A row with kind='idea' also carries :Idea. That is not a
second copy and not a leftover: :Idea is how the reading workspace, the
knowledge graph, Framework and the per-project idea board find ideas, and those
features have nothing to do with the Inbox and no reason to be rewritten
because it exists. The label is an index on `kind`, maintained by every write
in this file — flipping to task drops it, flipping back adds it.

STATUS follows kind:
    idea   raw | given | done | became | dropped | cached
    task   open | done | became | dropped | cached

DONE IS FOR IDEAS TOO. An idea you have followed through on is closed, not
dropped and not a project. Closing (done or drop) takes an optional one-line
why, kept on the row as done_why/dropped_why beside done_at/dropped_at, so the
Archive can say when and why without reading the move log. Reopen undoes
either: an idea goes back to raw, or given if it still has a GIVEN_TO edge.

TO DO AND ARCHIVE. The client splits rows by status: raw ideas and open
tasks/notes are "to do"; given, became, done and dropped are the Archive,
dated by when they were closed (see _shape's `closed`).

STARRED IS A MARKER, NOT A STATUS. `starred` is a flag you set on the way past
— "this one matters" — and it is deliberately NOT part of the status machine
and NOT the same thing as `priority`. Priority is a considered three-way
judgement you set while thinking about a row; a star is one click while
scanning. Starring works on any row including a settled one, because flagging
something you already decided is still useful, and it never changes what a row
IS — only where it sits on the screen.

CACHE2 IS A SHELF, NOT A BIN. `cached` is the one status that means "not now"
rather than "settled". Dropping says you decided against it; caching says you
decided nothing and would rather be asked again later, so the row leaves the
Inbox's working view without leaving the record. Uncaching puts it back exactly
where it was — raw, open, or given again if it had already been handed to a
project — because a shelf you cannot take things down from is a bin.

THE JOURNAL. A row carries a chain of (:TaskEntry) nodes — what happened, what
you learned, what is next, and the minutes it took — reached through
(:Task)-[:HAS_ENTRY]->(:TaskEntry). Those nodes and their write endpoints belong
to routes/tasks.py, which every other tab (Activity, Planner, Phases, Calendar)
already reads; the Inbox surfaces them on the row rather than owning a second
copy. This is what the Progress tab used to show, and the reason that tab is
gone: it was a second table over these same :Task nodes, reading a `done`/
`horizon` schema the rows no longer have.

NOTHING IS DELETED. Every move rewrites `status` and draws an edge; the row
stays in the Inbox naming where it went. A table you delete from stops being a
record of what you thought, and "what did I decide about this" is the question
the Inbox exists to answer.

WHY LIVES ON THE EDGE, NOT THE NODE. Each move writes its edge with a {date}
and, when you typed one, a why :Note against the :Hop standing in for that edge
(see routes/notes.py). The why belongs to the hop because it explains the move,
not the thing moved: "why is this under Research" is a fact about the edge.

THE LOG. Moves also append one :Move node, which is what the "What changed"
table reads. The edges alone cannot answer it — dropping a row, marking a task
done and flipping a kind are all moves that draw no edge, and a log missing
three of its verbs is not a log. The edge remains the truth; the :Move is the
sentence about it.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from activity import match_by_id, record
from db import run_read, run_write
from hours import hours_index
from models import (
    DEFAULT_WORK_TYPE, WORK_TYPES,
    InboxCreate, InboxUpdate, MoveCache, MoveDrop, MoveGive, MoveGrow,
    MovePromote, MoveStar,
    ProjectDone, ProjectMove, ProjectNest, ProjectOffshoot, ProjectReorder,
    ProjectSplit, TreeProjectUpdate, TreeTaskCreate, TreeTaskUpdate, WhyIn,
)

router = APIRouter(prefix="/api/synapse", tags=["inbox"])

IDEA_STATUSES = ("raw", "given", "done", "became", "dropped", "cached")
TASK_STATUSES = ("open", "done", "became", "dropped", "cached")


def _now() -> str:
    # Microseconds, not seconds. Several moves land inside the same second —
    # promote writes a project and a BECAME back to back — and at second
    # resolution the log came back in an order that was not the order the moves
    # happened in.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _is_hhmm(v: str) -> bool:
    parts = (v or "").split(":")
    return (len(parts) == 2 and all(p.isdigit() for p in parts)
            and int(parts[0]) < 24 and int(parts[1]) < 60)


def _today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# The log
# --------------------------------------------------------------------------- #
async def _write_move(frm: str, edge: str, to: str, why: str = "") -> None:
    """One row of "What changed".

    `when` is stored as a full timestamp and rendered as HH:MM by the client,
    so a log read tomorrow still knows which day a move happened on.
    """
    await run_write(
        """
        CREATE (m:Move {id: $id, at: $at, frm: $frm, edge: $edge, to: $to,
                        why: $why})
        """, id=str(uuid.uuid4()), at=_now(), frm=frm, edge=edge, to=to,
        why=why or "")


async def _hop_why(from_id: str, rel: str, to_id: str, why: str) -> None:
    """Hang a why note off the :Hop standing in for an edge.

    Same shape routes/notes.py writes, so a why written here shows up in the
    Reasoning tab beside every other why without that tab knowing this file
    exists.
    """
    why = (why or "").strip()
    if not why:
        return
    rows = await run_read(
        "MATCH (h:Hop {from_id: $f, rel: $r, to_id: $t}) RETURN h.id AS id",
        f=from_id, r=rel, t=to_id)
    hid = rows[0]["id"] if rows else str(uuid.uuid4())
    if not rows:
        await run_write(
            "CREATE (h:Hop {id: $id, from_id: $f, rel: $r, to_id: $t, "
            "created_at: $now})", id=hid, f=from_id, r=rel, t=to_id, now=_now())
    await run_write(
        """
        MATCH (h:Hop {id: $hid})
        CREATE (n:Note {id: $nid, date: $date, text: $text, kind: 'why',
                        created_at: $now})
        CREATE (n)-[:NOTE_ON]->(h)
        """, hid=hid, nid=str(uuid.uuid4()), date=_today(), text=why,
        now=_now())


@router.get("/inbox/log")
async def move_log(limit: int = 200) -> list[dict]:
    """The moves, newest first."""
    rows = await run_read(
        "MATCH (m:Move) RETURN m{.*} AS m ORDER BY m.at DESC LIMIT $limit",
        limit=limit)
    return [dict(r["m"]) for r in rows]


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
_PATH = """
    OPTIONAL MATCH path = (p)-[:CHILD_OF*0..]->(root:Project)
    WHERE NOT (root)-[:CHILD_OF]->(:Project)
    WITH p, nodes(path) AS chain
    ORDER BY size(chain) DESC
    WITH p, head(collect(chain)) AS chain
    RETURN [n IN reverse(chain) | n.name] AS parts
"""


async def _path_of(project_id: str) -> str:
    """A project's full path, 'Research › Sample project', the way the demo prints
    it. Built from the CHILD_OF chain rather than stored, so renaming a parent
    renames every path under it at once."""
    rows = await run_read(
        "MATCH (p:Project {id: $id}) " + _PATH, id=project_id)
    if not rows or not rows[0]["parts"]:
        return ""
    return " › ".join(rows[0]["parts"])


# --------------------------------------------------------------------------- #
# Inbox rows
# --------------------------------------------------------------------------- #
_ROW = """
    OPTIONAL MATCH (t)-[g:GIVEN_TO]->(gp:Project)
    OPTIONAL MATCH (t)-[bb:BECAME]->(bp:Project)
    OPTIONAL MATCH (n:Note)-[:NOTE_ON]->(t)
    RETURN t{.*} AS t,
           CASE WHEN gp IS NULL THEN null
                ELSE {id: gp.id, name: gp.name, date: g.date} END AS given,
           CASE WHEN bp IS NULL THEN null
                ELSE {id: bp.id, name: bp.name, date: bb.date} END AS became,
           // ONE origin per row. This was an OPTIONAL MATCH, and a row with two
           // CAME_FROM edges (a question asked during a reading pass points at
           // both the :Question and the :Instance) came back as two rows, so the
           // Inbox listed it twice. The question is already in `questions`
           // below, so the non-question origin wins and the question is the
           // fallback.
           // A :Row is skipped the same way: a note's Inbox row points at the
           // row and at what the row was written on, and the latter is the
           // useful "came from".
           head([(t)-[:CAME_FROM]->(src) WHERE NOT src:Question AND NOT src:Row |
                   {id: src.id,
                    // a journal entry has `text` rather than a name or title
                    name: coalesce(src.name, src.title, src.text),
                    label: head(labels(src))}]
                + [(t)-[:CAME_FROM]->(src:Question) |
                   {id: src.id, name: coalesce(src.name, src.title, src.text),
                    label: 'Question'}]) AS came,
           count(n) AS notes,
           // + notes written on the row itself (:Row)-[:ON]->(t) — a pattern
           // comprehension, so it cannot multiply count(n) above.
           size([(nr:Row)-[:ON]->(t) | nr]) AS row_notes,
           // A pattern comprehension, not another OPTIONAL MATCH: a second
           // match on CAME_FROM would multiply this row and inflate count(n)
           // above, which is the same trap _entries_of documents.
           [(t)-[:CAME_FROM]->(q:Question) |
              {id: q.id, text: q.text,
               answered: coalesce(q.answered, false)}] AS questions
"""


async def _entries_of(task_ids: list[str] | None = None) -> dict[str, list[dict]]:
    """The journal for each row, keyed by row id.

    Its own query rather than another OPTIONAL MATCH inside _ROW: that block
    already aggregates with count(n) for the notes, and a collect() of entries
    beside it multiplies the two out — the notes count silently inflates by the
    number of journal entries. Two reads merged in Python is the same fix the
    project-why read uses.
    """
    where = "WHERE t.id IN $ids" if task_ids is not None else ""
    rows = await run_read(
        f"""
        MATCH (t:Task)-[:HAS_ENTRY]->(e:TaskEntry)
        {where}
        RETURN t.id AS tid, e{{.*}} AS e
        ORDER BY coalesce(e.date, e.created_at, '')
        """, **({"ids": task_ids} if task_ids is not None else {}))
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["tid"], []).append(dict(r["e"]))
    return out


async def _shape(rec, entries: dict[str, list[dict]] | None = None) -> dict:
    t = dict(rec["t"])
    given = rec["given"]
    out = {
        "id": t.get("id"),
        "kind": t.get("kind") or "idea",
        "title": t.get("title") or "",
        "description": t.get("description") or "",
        "status": t.get("status") or "raw",
        "category": t.get("category") or "",
        "priority": t.get("priority") or "",
        "starred": bool(t.get("starred")),
        # two stars: yellow = priority, teal = sooner rather than later.
        # Stars set before there were two are priority.
        "star_tone": ((t.get("star_tone") or "priority") if t.get("starred") else ""),
        "paper_id": t.get("paper_id") or "",
        "low_h": t.get("low_h") or 0,
        "high_h": t.get("high_h") or 0,
        "due": t.get("due") or "",
        "do_on": t.get("do_on") or "",
        "do_at": t.get("do_at") or "",
        "takes_min": t.get("takes_min") or 0,
        "started_on": t.get("started_on") or "",
        "created_at": t.get("created_at") or "",
        "done_at": t.get("done_at") or "",
        "dropped_at": t.get("dropped_at") or "",
        # the optional line typed when the row was closed
        "why": (t.get("done_why") if t.get("status") == "done"
                else t.get("dropped_why") if t.get("status") == "dropped"
                else "") or "",
        "notes": (rec["notes"] or 0) + (rec.get("row_notes") or 0),
        # The journal, and the minutes it adds up to. Both come from
        # :TaskEntry — see _entries_of.
        "entries": [],
        "total_mins": 0,
        "given": None,
        "became": rec["became"],
        "came": rec["came"],
        # one question per row: a row IS a question or it is not
        "question": None,
    }
    qs = rec["questions"] or []
    if qs:
        out["question"] = dict(qs[0])
    if entries is not None:
        out["entries"] = entries.get(out["id"]) or []
        out["total_mins"] = sum(
            int(e.get("time_spent_mins") or 0) for e in out["entries"])
    if given:
        out["given"] = {**given, "path": await _path_of(given["id"])}
    if out["became"]:
        out["became"] = {**out["became"],
                         "path": await _path_of(out["became"]["id"])}
    # When the row left "to do" — the Archive's date column.
    st = out["status"]
    out["closed"] = (
        out["done_at"] if st == "done"
        else out["dropped_at"] if st == "dropped"
        else (out["became"] or {}).get("date") or "" if st == "became"
        else (out["given"] or {}).get("date") or "" if st == "given"
        else "")
    return out


# THIS PHASE. (:Task)-[:FOR_PHASE]->(:Phase) is a row you have said you mean to
# do inside that phase — a commitment, set by hand. It is NOT the IN_PHASE edge
# phasehook.py files automatically on everything created while a phase runs:
# that one says when a row was born, this one says when you want it done. The
# row stays in the Inbox (its universal home); the Phases tab reads the same
# edge back, so the two views are one fact, never a copy.
async def _phase_marks(ids: list[str] | None = None) -> dict:
    rows = await run_read(
        "MATCH (t:Task)-[r:FOR_PHASE]->(p:Phase) "
        + ("WHERE t.id IN $ids " if ids is not None else "")
        + "RETURN t.id AS tid, p.id AS id, p.name AS name, "
          "coalesce(p.status,'active') = 'active' AS active, r.at AS at "
          "ORDER BY r.at", ids=ids or [])
    out: dict = {}
    for r in rows:
        # if a row was ever carried into a second phase, the active one wins
        if r["tid"] not in out or r["active"]:
            out[r["tid"]] = {"id": r["id"], "name": r["name"], "active": r["active"]}
    return out


async def _one(task_id: str) -> dict:
    rows = await run_read("MATCH (t:Task {id: $id}) " + _ROW, id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    row = await _shape(rows[0], await _entries_of([task_id]))
    row["for_phase"] = (await _phase_marks([task_id])).get(task_id)
    return row


@router.get("/inbox")
async def list_inbox() -> list[dict]:
    """Every row, newest first. Dropped and became rows come back too: they are
    the record of a decision, and the client greys them rather than hiding
    them."""
    rows = await run_read(
        "MATCH (t:Task) " + _ROW + " ORDER BY t.created_at DESC")
    entries = await _entries_of()
    marks = await _phase_marks()
    out = [await _shape(r, entries) for r in rows]
    for r in out:
        r["for_phase"] = marks.get(r["id"])
    return out


class PhaseMark(BaseModel):
    on: bool = True


@router.post("/inbox/{task_id}/phase")
async def set_phase(task_id: str, body: PhaseMark) -> dict:
    """Put a row in the active phase ("do this phase"), or take it out.

    Like the star, a marker — no :Move, and it works on any status. Marking
    with no phase running is refused rather than silently doing nothing."""
    if not await run_read("MATCH (t:Task {id: $id}) RETURN t.id AS id", id=task_id):
        raise HTTPException(404, "no such row")
    ph = await run_read(
        "MATCH (p:Phase) WHERE coalesce(p.status,'active') = 'active' "
        "RETURN p.id AS id ORDER BY p.start DESC LIMIT 1")
    if body.on:
        if not ph:
            raise HTTPException(409, "no phase is running — start one in the Phases tab")
        await run_write(
            "MATCH (t:Task {id: $id}), (p:Phase {id: $pid}) "
            "MERGE (t)-[r:FOR_PHASE]->(p) ON CREATE SET r.at = $now",
            id=task_id, pid=ph[0]["id"], now=datetime.now(timezone.utc).isoformat())
    elif ph:
        await run_write(
            "MATCH (t:Task {id: $id})-[r:FOR_PHASE]->(:Phase {id: $pid}) DELETE r",
            id=task_id, pid=ph[0]["id"])
    return await _one(task_id)


# Held around "is there a duplicate?" + the CREATE, so two requests arriving
# together can't both see no duplicate and both write. One uvicorn process, so
# an in-process lock is enough.
capture_lock = asyncio.Lock()


async def recent_duplicate(title: str, kind: str, seconds: int = 10) -> str | None:
    """The id of an identical row made in the last few seconds, if there is one.

    WHY. The same capture was landing twice, 30–60 ms apart: a double click on
    "+ add idea", or Enter arriving twice through the input method. Nobody types
    the same title twice inside ten seconds on purpose, so the second write is
    treated as the first one arriving again and returns that row instead.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
        timespec="microseconds")
    rows = await run_read(
        "MATCH (t:Task) WHERE t.title = $title AND t.kind = $kind "
        "AND t.created_at >= $cutoff RETURN t.id AS id LIMIT 1",
        title=title, kind=kind, cutoff=cutoff)
    return rows[0]["id"] if rows else None


async def create_row(title: str, kind: str, category: str = "",
                     came_from: str | None = None) -> str:
    """Make a row and return its id. THE one place a :Task is created.

    Everything that captures into the Inbox goes through here — the add box,
    and the Journal when a spoken point is sent over. The reason it is one
    function is the :Idea label: a row with kind='idea' must also carry :Idea
    or the knowledge graph, Framework and the per-project idea board stop
    seeing it, and a second CREATE somewhere else is exactly how that gets
    forgotten. See the module docstring.

    `came_from` is any node this row came out of — a project (an offshoot), a
    paper, or a journal entry you spoke. It is provenance, not placement: the
    row still has to be given somewhere.
    """
    title = (title or "").strip()
    if not title:
        raise HTTPException(400, "a row with no title is not a row")
    if kind not in ("idea", "task", "note"):
        raise HTTPException(400, "kind must be idea, task or note")
    async with capture_lock:
        dup = await recent_duplicate(title, kind)
        if dup:
            return dup
        tid = str(uuid.uuid4())
        await run_write(
            """
            CREATE (t:Task {id: $id, kind: $kind, title: $title, description: '',
                            status: $status, category: $category, priority: '',
                            paper_id: '', low_h: 0.0, high_h: 0.0, due: '',
                            notes: '', created_at: $now, position: 0.0})
            """, id=tid, kind=kind, title=title,
            status="raw" if kind == "idea" else "open",
            category=category or "", now=_now())
    if kind == "idea":
        await run_write("MATCH (t:Task {id: $id}) SET t:Idea", id=tid)
    if came_from:
        await run_write(
            "MATCH (t:Task {id: $id}) " + match_by_id("src", "s") + " "
            "MERGE (t)-[:CAME_FROM]->(s)", id=tid, src=came_from)
    await record("inbox", f"{kind} added", detail=title[:70], entity_id=tid)
    return tid


@router.post("/inbox", status_code=201)
async def add_row(body: InboxCreate) -> dict:
    """A new row. Kind decides the opening status and nothing else."""
    return await _one(await create_row(body.title, body.kind, body.category or ""))


class InboxBulk(BaseModel):
    titles: list[str]
    kind: str = "idea"
    category: str = ""


@router.post("/inbox/bulk", status_code=201)
async def add_rows(body: InboxBulk) -> dict:
    """Many rows at once — a column pasted out of a spreadsheet. Each goes
    through create_row, so the :Idea label rule holds exactly as for the add
    box. Deduping is the caller's preview; blanks are skipped here too."""
    titles = [t.strip() for t in body.titles if t and t.strip()]
    if len(titles) > 2000:
        raise HTTPException(400, "2000 rows at a time, at most")
    ids = [await create_row(t, body.kind, body.category) for t in titles]
    return {"created": len(ids), "ids": ids}


@router.patch("/inbox/{task_id}")
async def edit_row(task_id: str, body: InboxUpdate) -> dict:
    """Edit a row, including flipping its kind.

    FLIPPING IS THE INTERESTING CASE. A given idea that becomes a task has to
    appear in the tree, because a task given to a project IS a tree task; a
    task that becomes an idea has to leave it. The GIVEN_TO edge is what makes
    it a tree leaf, so the flip adds or removes exactly that edge and nothing
    else moves.
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.kind AS kind, t.title AS title, "
        "t.status AS status", id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    old_kind, title, status = rows[0]["kind"], rows[0]["title"], rows[0]["status"]

    if status == "became":
        raise HTTPException(400, "this row already became a project")

    sets, params = [], {"id": task_id}
    for field in ("title", "description", "category", "priority", "due"):
        val = getattr(body, field, None)
        if val is not None:
            sets.append(f"t.{field} = ${field}")
            params[field] = val
    for field in ("low_h", "high_h"):
        val = getattr(body, field, None)
        if val is not None:
            sets.append(f"t.{field} = ${field}")
            params[field] = float(val)
    if body.do_on is not None:
        if body.do_on:
            try:
                date.fromisoformat(body.do_on)
            except ValueError:
                raise HTTPException(400, "do on must be a date, YYYY-MM-DD")
        sets.append("t.do_on = $do_on"); params["do_on"] = body.do_on
    if body.started_on is not None:
        if body.started_on:
            try:
                date.fromisoformat(body.started_on)
            except ValueError:
                raise HTTPException(400, "started must be a date, YYYY-MM-DD")
        sets.append("t.started_on = $started_on"); params["started_on"] = body.started_on
    if body.do_at is not None:
        if body.do_at and not _is_hhmm(body.do_at):
            raise HTTPException(400, "time must be HH:MM")
        sets.append("t.do_at = $do_at"); params["do_at"] = body.do_at
    if body.takes_min is not None:
        sets.append("t.takes_min = $takes_min"); params["takes_min"] = max(0, int(body.takes_min))

    if body.kind is not None and body.kind != old_kind:
        if body.kind not in ("idea", "task", "note"):
            raise HTTPException(400, "kind must be idea, task or note")
        # A flip resets status to the opening state of the new kind. Carrying
        # `dropped` across would be right, but carrying `open` onto an idea
        # would put a status on it that ideas do not have. `cached` carries the
        # same way `dropped` does: deciding a shelved row is really a task is
        # not the same as taking it off the shelf.
        new_status = status if status in ("dropped", "cached") else (
            "raw" if body.kind == "idea" else "open")
        sets.append("t.kind = $kind")
        sets.append("t.status = $status")
        params["kind"] = body.kind
        params["status"] = new_status

    if sets:
        await run_write(
            "MATCH (t:Task {id: $id}) SET " + ", ".join(sets), **params)

    if body.kind is not None and body.kind != old_kind:
        # Keep the :Idea label in step with `kind` — see the module docstring.
        if body.kind == "idea":
            await run_write("MATCH (t:Task {id: $id}) SET t:Idea", id=task_id)
        else:
            await run_write("MATCH (t:Task {id: $id}) REMOVE t:Idea", id=task_id)
        given = await run_read(
            "MATCH (t:Task {id: $id})-[:GIVEN_TO]->(p:Project) "
            "RETURN p.id AS pid", id=task_id)
        if body.kind == "idea" and given and status not in ("dropped", "cached"):
            # Out of the tree, but still given: the row keeps naming the
            # project it was handed to. A dropped or cached row keeps the
            # status it carried in — the flip decided its kind, not its fate.
            await run_write(
                "MATCH (t:Task {id: $id}) SET t.status = 'given'", id=task_id)
        await _write_move(f'{old_kind} "{title}"', "flipped to", body.kind, "")
        await record("inbox", "kind flipped",
                     detail=f"{title[:50]} → {body.kind}", entity_id=task_id)

    return await _one(task_id)


@router.post("/inbox/{task_id}/star")
async def set_star(task_id: str, body: MoveStar) -> dict:
    """Flag a row, or unflag it.

    Its own endpoint rather than a field on PATCH because PATCH refuses a row
    that became a project — that refusal protects the row's WORDING, which is
    the record of what you thought. A star is not wording.
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title", id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    # priority = yellow, soon = teal ("possible priority"), later = grey
    # ("could be important in a later phase")
    tone = body.tone if body.tone in ("priority", "soon", "later") else "priority"
    await run_write("MATCH (t:Task {id: $id}) SET t.starred = $on, t.star_tone = $tone",
                    id=task_id, on=bool(body.starred),
                    tone=tone if body.starred else None)
    # No :Move row. The log is the record of decisions about where work goes,
    # and starring is not one — a log full of stars and unstars would bury the
    # moves that matter.
    return await _one(task_id)


class DoneIn(BaseModel):
    why: str = ""


@router.post("/inbox/{task_id}/done")
async def mark_done(task_id: str, body: DoneIn | None = None) -> dict:
    """✓ — completes a task, a note or an idea. Done rows sit in the
    Completed box."""
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind, "
        "t.status AS status", id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    if rows[0]["kind"] not in ("task", "note", "idea"):
        raise HTTPException(400, "only a task, a note or an idea can be done")
    if rows[0]["status"] == "became":
        raise HTTPException(400, "this row already became a project")
    why = ((body.why if body else "") or "").strip()
    await run_write(
        "MATCH (t:Task {id: $id}) SET t.status = 'done', t.done_at = $now, "
        "t.done_why = $why", id=task_id, now=_now(), why=why)
    await _write_move(f'{rows[0]["kind"]} "{rows[0]["title"]}"', "DONE", "", why)
    await record("inbox", f'{rows[0]["kind"]} done', detail=rows[0]["title"][:70],
                 entity_id=task_id)
    return await _one(task_id)


@router.post("/inbox/{task_id}/drop")
async def drop_row(task_id: str, body: MoveDrop) -> dict:
    """Dropped, not deleted. The row stays and says so."""
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind",
        id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    await run_write(
        "MATCH (t:Task {id: $id}) SET t.status = 'dropped', "
        "t.dropped_at = $now, t.dropped_why = $why",
        id=task_id, now=_now(), why=(body.why or "").strip())
    await _write_move(f'{rows[0]["kind"]} "{rows[0]["title"]}"', "DROPPED", "",
                      body.why or "")
    await record("inbox", "dropped", detail=rows[0]["title"][:70],
                 entity_id=task_id)
    return await _one(task_id)


@router.post("/inbox/{task_id}/reopen")
async def reopen_row(task_id: str) -> dict:
    """Untick or un-drop: a done or dropped task or note goes back to open, an
    idea back to raw (or given, if it still has a GIVEN_TO edge). The note's tick box needs
    both directions; a tick you can't take back is a tick you hesitate over."""
    rows = await run_read(
        """
        MATCH (t:Task {id: $id})
        OPTIONAL MATCH (t)-[:GIVEN_TO]->(p:Project)
        RETURN t.title AS title, t.kind AS kind, t.status AS status,
               p IS NOT NULL AS given
        """, id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    if rows[0]["status"] not in ("done", "dropped"):
        raise HTTPException(400, "only a done or dropped row can be reopened")
    back = ("open" if rows[0]["kind"] != "idea"
            else "given" if rows[0]["given"] else "raw")
    await run_write(
        "MATCH (t:Task {id: $id}) SET t.status = $back "
        "REMOVE t.done_at, t.done_why, t.dropped_at, t.dropped_why",
        id=task_id, back=back)
    await _write_move(f'{rows[0]["kind"]} "{rows[0]["title"]}"', "REOPENED", "", "")
    await record("inbox", "reopened", detail=rows[0]["title"][:70], entity_id=task_id)
    return await _one(task_id)


@router.delete("/inbox/{task_id}")
async def delete_row(task_id: str) -> dict:
    """Delete the Inbox row — and only the Inbox row. The red × beside the star.

    Drop is still the move for "decided against"; this is for rows that should
    never have been written (a typo, a duplicate, a test).

    WHAT GOES: the :Task and its own edges (DETACH DELETE), CAME_FROM included.
    WHAT STAYS:
      * the node it CAME_FROM — journal entry, paper, instance, question, + row.
        Those are records in their own areas; the Inbox row was only a pointer
        to them. Nothing here matches past the edge, so nothing there can go.
      * its :TaskEntry journal. Detached, not deleted: each is stamped
        orphaned_from (the row's title) and orphaned_at, so nothing written is
        lost (2026-11-08, user request — it used to be deleted with the row).
      * logged hours — a :WorkSession keeps its ref_title and only loses the edge.
    One DELETED line goes into "What changed" so the log still says it existed.
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind",
        id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    await run_write(
        """
        MATCH (t:Task {id: $id})-[h:HAS_ENTRY]->(e:TaskEntry)
        SET e.orphaned_from = $title, e.orphaned_at = $now, e.orphaned_task_id = $id
        DELETE h
        """, id=task_id, title=rows[0]["title"] or "",
        now=datetime.now(timezone.utc).isoformat())
    await run_write("MATCH (t:Task {id: $id}) DETACH DELETE t", id=task_id)
    await _write_move(f'{rows[0]["kind"]} "{rows[0]["title"]}"', "DELETED", "", "")
    await record("inbox", "deleted", detail=rows[0]["title"][:70])
    return {"deleted": task_id}


@router.post("/inbox/{task_id}/cache")
async def cache_row(task_id: str, body: MoveCache) -> dict:
    """Cache2 — put it on the shelf.

    The move for a row you have not decided against and are not doing: it comes
    out of the working view and waits. Nothing else about the row changes, so a
    given row still names its project and a row with notes keeps them; only the
    status says "not now".
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind, "
        "t.status AS status", id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    kind, title, status = rows[0]["kind"], rows[0]["title"], rows[0]["status"]
    if status == "became":
        raise HTTPException(400, "this row already became a project")
    if status == "cached":
        return await _one(task_id)
    await run_write(
        # `cached_from` is how uncache knows where to put the row back without
        # guessing: a given idea that comes back off the shelf is given again,
        # not raw.
        "MATCH (t:Task {id: $id}) SET t.status = 'cached', "
        "t.cached_from = $was, t.cached_at = $now",
        id=task_id, was=status or "", now=_now())
    await _write_move(f'{kind} "{title}"', "CACHED", "cache2", body.why or "")
    await record("inbox", "cached", detail=title[:70], entity_id=task_id)
    return await _one(task_id)


@router.post("/inbox/{task_id}/uncache")
async def uncache_row(task_id: str, body: MoveCache) -> dict:
    """Off the shelf and back into the Inbox.

    Back to the status it was cached from. That status is re-derived rather
    than trusted blindly, because the row's edges may have moved while it sat
    there and the GIVEN_TO edge, not the stored string, is what "given" means.
    """
    rows = await run_read(
        """
        MATCH (t:Task {id: $id})
        OPTIONAL MATCH (t)-[:GIVEN_TO]->(p:Project)
        RETURN t.title AS title, t.kind AS kind, t.status AS status,
               coalesce(t.cached_from, '') AS was, p IS NOT NULL AS given
        """, id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    r = rows[0]
    if r["status"] != "cached":
        raise HTTPException(400, "this row is not in cache2")

    kind, given, was = r["kind"], r["given"], r["was"]
    if was == "dropped":
        back = "dropped"          # shelved after being dropped: still dropped
    elif kind in ("task", "note"):
        back = "open"
    elif given:
        back = "given"
    else:
        back = "raw"

    await run_write(
        "MATCH (t:Task {id: $id}) SET t.status = $back "
        "REMOVE t.cached_from, t.cached_at", id=task_id, back=back)
    await _write_move("cache2", "BACK TO", f'{kind} "{r["title"]}"',
                      body.why or "")
    await record("inbox", "back from cache2", detail=r["title"][:70],
                 entity_id=task_id)
    return await _one(task_id)


@router.post("/inbox/{task_id}/give")
async def give_to(task_id: str, body: MoveGive) -> dict:
    """Hand a row to a project.

    One project at a time: handing it somewhere else moves the edge rather than
    adding a second, because "given to two projects" is not a state anyone
    means, it is a decision that has not been made yet.
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind",
        id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    kind, title = rows[0]["kind"], rows[0]["title"]

    made = await run_write(
        """
        MATCH (t:Task {id: $id}), (p:Project {id: $pid})
        OPTIONAL MATCH (t)-[old:GIVEN_TO]->() DELETE old
        WITH t, p
        MERGE (t)-[r:GIVEN_TO]->(p)
          ON CREATE SET r.date = $today
        SET t.status = CASE WHEN t.kind = 'task' THEN 'open' ELSE 'given' END
        RETURN p.name AS name
        """, id=task_id, pid=body.project_id, today=_today())
    if not made:
        raise HTTPException(404, "no such project")

    path = await _path_of(body.project_id)
    await _hop_why(task_id, "GIVEN_TO", body.project_id, body.why)
    await _write_move(f'{kind} "{title}"', "GIVEN_TO", path, body.why or "")
    await record("inbox", "given to a project",
                 detail=f"{title[:40]} → {made[0]['name']}"[:70],
                 entity_id=task_id)
    return await _one(task_id)


async def _new_project(name: str, parent_id: str | None) -> str:
    pid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (p:Project {id: $id, name: $name, done_when: '', low_h: 0.0,
                           high_h: 0.0, due: '', created_at: $now,
                           kind: $kind})
        """, id=pid, name=name, now=_now(), kind=DEFAULT_WORK_TYPE)
    if parent_id:
        ok = await run_write(
            "MATCH (c:Project {id: $cid}), (p:Project {id: $pid}) "
            "MERGE (c)-[r:CHILD_OF]->(p) ON CREATE SET r.date = $today "
            "RETURN p.id AS id", cid=pid, pid=parent_id, today=_today())
        if not ok:
            raise HTTPException(404, "no such parent project")
    return pid


@router.post("/inbox/{task_id}/promote")
async def promote(task_id: str, body: MovePromote) -> dict:
    """An idea becomes a project.

    The idea's text becomes the project's first why, because that sentence is
    the only record of what the project was FOR before any work went into it.
    A why typed into the modal wins; the idea text is the fallback, which is
    what the demo does.
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind",
        id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    if rows[0]["kind"] != "idea":
        raise HTTPException(400, "a task grows, an idea promotes")
    title = rows[0]["title"]

    pid = await _new_project(title, body.parent_id)
    await run_write(
        """
        MATCH (t:Task {id: $id}), (p:Project {id: $pid})
        MERGE (t)-[r:BECAME]->(p) ON CREATE SET r.date = $today
        SET t.status = 'became'
        """, id=task_id, pid=pid, today=_today())

    why = (body.why or "").strip() or title
    await _hop_why(task_id, "BECAME", pid, why)
    path = await _path_of(pid)
    await _write_move(f'idea "{title}"', "BECAME", f"project {path}", why)
    await record("inbox", "idea promoted", detail=title[:70], entity_id=task_id)
    return await _one(task_id)


@router.post("/inbox/{task_id}/grow")
async def grow(task_id: str, body: MoveGrow) -> dict:
    """A task grows into a project and becomes its own first child.

    The task keeps its sessions. That is the point of growing rather than
    making a new project and retyping the task: the hours already logged
    against it are what tell you the estimate was wrong, and they must end up
    inside the project they were really spent on.
    """
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind",
        id=task_id)
    if not rows:
        raise HTTPException(404, "no such row")
    if rows[0]["kind"] != "task":
        raise HTTPException(400, "an idea promotes, a task grows")
    title = rows[0]["title"]

    pid = await _new_project(title, body.parent_id)
    # The row itself stays a task and is re-given to the new project, so its
    # sessions travel with it. A second Task is never created: one node, one
    # history.
    await run_write(
        """
        MATCH (t:Task {id: $id}), (p:Project {id: $pid})
        OPTIONAL MATCH (t)-[old:GIVEN_TO]->() DELETE old
        WITH t, p
        MERGE (t)-[g:GIVEN_TO]->(p) ON CREATE SET g.date = $today
        MERGE (t)-[b:BECAME]->(p)   ON CREATE SET b.date = $today
        SET t.status = 'open'
        """, id=task_id, pid=pid, today=_today())

    await _hop_why(task_id, "BECAME", pid, body.why)
    path = await _path_of(pid)
    await _write_move(f'task "{title}"', "BECAME", f"project {path}",
                      body.why or "")
    await record("inbox", "task grown into a project", detail=title[:70],
                 entity_id=task_id)
    return await _one(task_id)


# --------------------------------------------------------------------------- #
# Projects: the list, the page, and the tree underneath both
#
# ROLL-UPS ARE COMPUTED HERE, not in the client. A project's estimate, its
# logged hours and its done-counts all depend on its whole subtree, and two
# clients working that out independently is two chances to disagree about what
# a number means. The tree comes back with the arithmetic already done.
#
# An estimate typed onto a parent is an OVERRIDE and is flagged as one, because
# a guess and a sum that happen to be equal are not the same claim.
# --------------------------------------------------------------------------- #
PRIORITIES = (1, 2, 3)
# Named, not free hex. You pick a project out of a wall of cards by its colour,
# which only works while the colours stay far apart; a colour wheel is how you
# end up with two projects a shade apart and no way to tell them at a glance.
# "" means no choice made, and the card falls back to its priority colour.
PROJECT_COLORS = ("", "yellow", "purple", "blue", "green", "red", "pink", "teal")
PRIORITY_WORD = {1: "now", 2: "soon", 3: "later"}
PROJECT_STATUSES = ("active", "paused", "not started", "holding", "done")


async def _all_projects() -> list[dict]:
    rows = await run_read(
        """
        MATCH (p:Project)
        OPTIONAL MATCH (p)-[c:CHILD_OF]->(parent:Project)
        RETURN p{.*} AS p, parent.id AS parent_id,
               coalesce(c.order, 0.0) AS ord
        """)
    out = []
    for r in rows:
        d = dict(r["p"])
        d["parent_id"] = r["parent_id"]
        d["order"] = r["ord"]
        d.setdefault("priority", 2)
        d.setdefault("priority_order", 0.0)
        d.setdefault("status", "active")
        d.setdefault("color", "")
        d.setdefault("done_at", "")
        out.append(d)
    return out


async def _all_tree_tasks() -> list[dict]:
    rows = await run_read(
        """
        MATCH (t:Task)-[g:GIVEN_TO]->(p:Project)
        WHERE t.kind = 'task'
        RETURN t{.*} AS t, p.id AS project_id, coalesce(g.order, 0.0) AS ord
        """)
    out = []
    for r in rows:
        d = dict(r["t"])
        d["project_id"] = r["project_id"]
        d["order"] = r["ord"]
        out.append(d)
    return out


async def _logged_by_task() -> dict:
    rows = await run_read(
        """
        MATCH (w:WorkSession)-[:ON]->(t:Task)
        RETURN t.id AS id, sum(coalesce(w.mins, 0)) AS mins, count(w) AS n,
               max(coalesce(w.date, '')) AS last
        """)
    return {r["id"]: {"mins": r["mins"], "sessions": r["n"], "last": r["last"]}
            for r in rows}


def _index(projects: list[dict], tasks: list[dict]):
    kids, own = {}, {}
    for p in projects:
        kids.setdefault(p["parent_id"], []).append(p)
    for t in tasks:
        own.setdefault(t["project_id"], []).append(t)
    for v in kids.values():
        v.sort(key=lambda p: (p.get("order") or 0.0, p.get("created_at") or ""))
    for v in own.values():
        v.sort(key=lambda t: (t.get("order") or 0.0, t.get("created_at") or ""))
    return kids, own


def _rollup(p: dict, kids: dict, own: dict, logged: dict) -> dict:
    """Estimate, hours and done-counts for one project and everything under it.

    Depth-first and memo-free: the tree is small, and a project that somehow
    ended up its own ancestor would loop, so `seen` cuts that rather than
    trusting the data to be acyclic.
    """
    def walk(node, seen):
        if node["id"] in seen:
            return {"low": 0.0, "high": 0.0, "mins": 0, "sessions": 0,
                    "tasks": 0, "tasks_done": 0, "kids": 0, "kids_done": 0}
        seen = seen | {node["id"]}
        my_tasks = own.get(node["id"], [])
        my_kids = kids.get(node["id"], [])
        low = high = 0.0
        mins = sessions = 0
        tasks = tasks_done = 0
        for t in my_tasks:
            low += t.get("low_h") or 0.0
            high += t.get("high_h") or 0.0
            lg = logged.get(t["id"]) or {}
            mins += lg.get("mins", 0)
            sessions += lg.get("sessions", 0)
            tasks += 1
            if t.get("status") == "done":
                tasks_done += 1
        for k in my_kids:
            sub = walk(k, seen)
            low += sub["low"]; high += sub["high"]
            mins += sub["mins"]; sessions += sub["sessions"]
            tasks += sub["tasks"]; tasks_done += sub["tasks_done"]
        return {"low": low, "high": high, "mins": mins, "sessions": sessions,
                "tasks": tasks, "tasks_done": tasks_done,
                "kids": len(my_kids),
                "kids_done": sum(1 for k in my_kids if k.get("status") == "done")}

    agg = walk(p, frozenset())
    has_children = bool(kids.get(p["id"]) or own.get(p["id"]))
    override = bool(p.get("est_override")) or not has_children
    return {
        "low": (p.get("low_h") or 0.0) if override else agg["low"],
        "high": (p.get("high_h") or 0.0) if override else agg["high"],
        "rolled_low": agg["low"], "rolled_high": agg["high"],
        "override": bool(p.get("est_override")) and has_children,
        "logged_mins": agg["mins"], "sessions": agg["sessions"],
        "tasks": agg["tasks"], "tasks_done": agg["tasks_done"],
        "child_projects": agg["kids"], "child_projects_done": agg["kids_done"],
    }


async def _claims() -> dict:
    rows = await run_read(
        """
        MATCH (pr:Project)-[r:CLAIMED_BY]->(ph:Phase)
        RETURN pr.id AS id, ph.id AS phase_id, ph.name AS phase,
               coalesce(r.hours, 0.0) AS planned
        """)
    out = {}
    for r in rows:
        out.setdefault(r["id"], []).append(
            {"phase_id": r["phase_id"], "phase": r["phase"],
             "planned_h": r["planned"]})
    return out


async def _latest_whys() -> dict:
    """One why per project: the newest one that is about THE PROJECT ITSELF.

    Narrower than the page's Why panel on purpose. The panel shows every why
    touching the project, including the reason each idea was handed to it —
    those are whys about the idea, and one of them landing on the card would
    have the card explain something other than the project it is on. So: notes
    written straight onto the project, and notes on hops the project is the
    FROM end of, which is its own creation and its own placement.
    """
    rows = await run_read(
        """
        MATCH (n:Note {kind: 'why'})-[:NOTE_ON]->(target)
        WHERE target:Project OR target:Hop
        RETURN CASE WHEN target:Hop THEN target.from_id ELSE target.id END AS pid,
               target:Hop AS is_hop, n.text AS text, n.date AS date
        ORDER BY n.created_at DESC
        """)
    out = {}
    for r in rows:
        pid = r["pid"]
        if pid and pid not in out:
            out[pid] = {"text": r["text"], "date": r["date"]}
    return out


async def _ideas_given() -> dict:
    rows = await run_read(
        """
        MATCH (t:Task)-[g:GIVEN_TO]->(p:Project)
        WHERE t.kind = 'idea' AND t.status = 'given'
        OPTIONAL MATCH (t)-[:CAME_FROM]->(src:Project)
        RETURN p.id AS pid, t.id AS id, t.title AS title,
               coalesce(g.date, '') AS given_on, src.name AS from_project
        ORDER BY g.date DESC, t.title
        """)
    out = {}
    for r in rows:
        out.setdefault(r["pid"], []).append(
            {"id": r["id"], "title": r["title"], "given_on": r["given_on"],
             "from_project": r["from_project"]})
    return out


def _with_hours(roll: dict, idx, pid: str) -> dict:
    """Hours come from the shared index (hours.py), not the task walk: it also
    counts sessions logged on the project itself and on everything attached to
    it, and it is the same number the phase and Repository show."""
    h = idx.of(pid)
    return {**roll, "logged_mins": h["mins"], "sessions": h["sessions"]}


def _shape_project(p: dict, roll: dict, path: str, claims: list, why) -> dict:
    return {
        "id": p["id"], "name": p.get("name") or "",
        "parent_id": p.get("parent_id"), "path": path,
        "low_h": p.get("low_h") or 0.0, "high_h": p.get("high_h") or 0.0,
        "done_when": p.get("done_when") or "", "due": p.get("due") or "",
        "priority": int(p.get("priority") or 2),
        "priority_word": PRIORITY_WORD.get(int(p.get("priority") or 2), "soon"),
        "priority_order": p.get("priority_order") or 0.0,
        "status": p.get("status") or "active",
        "kind": p.get("kind") or DEFAULT_WORK_TYPE,
        "color": p.get("color") or "",
        "done_at": p.get("done_at") or "",
        "est_override": bool(p.get("est_override")),
        "rollup": roll, "claims": claims or [],
        "why": why,
    }


def _paths(projects: list[dict]) -> dict:
    by_id = {p["id"]: p for p in projects}
    out = {}
    for p in projects:
        parts, cur, guard_n = [p.get("name") or ""], p, 0
        while cur.get("parent_id") and guard_n < 40:
            cur = by_id.get(cur["parent_id"])
            guard_n += 1
            if not cur:
                break
            parts.insert(0, cur.get("name") or "")
        out[p["id"]] = " › ".join(parts)
    return out


@router.get("/projects")
async def list_projects() -> dict:
    """Every project with its roll-ups, plus what the cards need.

    One call rather than one per card: the table and the cards are two readings
    of the same list, and fetching it twice would let them disagree.
    """
    projects = await _all_projects()
    tasks = await _all_tree_tasks()
    logged = await _logged_by_task()
    kids, own = _index(projects, tasks)
    claims = await _claims()
    whys = await _latest_whys()
    ideas = await _ideas_given()
    paths = _paths(projects)
    idx = await hours_index()

    out = []
    for p in projects:
        roll = _with_hours(_rollup(p, kids, own, logged), idx, p["id"])
        shaped = _shape_project(p, roll, paths[p["id"]], claims.get(p["id"]),
                                whys.get(p["id"]))
        shaped["ideas_given"] = len(ideas.get(p["id"], []))
        # Up to three children for the card, named with their state.
        shaped["children"] = [
            {"id": k["id"], "name": k.get("name") or "",
             "status": k.get("status") or "active",
             "low_h": _rollup(k, kids, own, logged)["low"],
             "high_h": _rollup(k, kids, own, logged)["high"]}
            for k in kids.get(p["id"], [])[:3]
        ]
        out.append(shaped)

    # Rank order: priority_order when set, then priority, then name.
    out.sort(key=lambda p: (p["priority_order"] or 0.0, p["priority"],
                            p["name"].lower()))
    return {"projects": out}


@router.get("/projects/{project_id}/tree")
async def project_tree(project_id: str) -> dict:
    """One project: its subtree, and everything the four panels need."""
    projects = await _all_projects()
    if not any(p["id"] == project_id for p in projects):
        raise HTTPException(404, "no such project")
    tasks = await _all_tree_tasks()
    logged = await _logged_by_task()
    kids, own = _index(projects, tasks)
    claims = await _claims()
    paths = _paths(projects)
    ideas = await _ideas_given()
    idx = await hours_index()

    def node(p):
        roll = _with_hours(_rollup(p, kids, own, logged), idx, p["id"])
        return {
            **_shape_project(p, roll, paths[p["id"]], claims.get(p["id"]), None),
            "tasks": [{
                "id": t["id"], "title": t.get("title") or "",
                "status": t.get("status") or "open",
                "low_h": t.get("low_h") or 0.0, "high_h": t.get("high_h") or 0.0,
                "due": t.get("due") or "", "done_at": t.get("done_at") or "",
                "logged_mins": (logged.get(t["id"]) or {}).get("mins", 0),
                "sessions": (logged.get(t["id"]) or {}).get("sessions", 0),
            } for t in own.get(p["id"], [])],
            "children": [node(k) for k in kids.get(p["id"], [])],
        }

    root = next(p for p in projects if p["id"] == project_id)

    # Hours by task, for the sessions panel: every task in the subtree that has
    # any logged time, biggest first.
    def subtree_tasks(p, acc):
        acc.extend(own.get(p["id"], []))
        for k in kids.get(p["id"], []):
            subtree_tasks(k, acc)
        return acc
    by_task = []
    for t in subtree_tasks(root, []):
        lg = logged.get(t["id"]) or {}
        if lg.get("mins"):
            by_task.append({"id": t["id"], "title": t.get("title") or "",
                            "mins": lg["mins"], "sessions": lg["sessions"]})
    by_task.sort(key=lambda t: -t["mins"])

    docs = await run_read(
        "MATCH (d:Document)-[:FOR|ABOUT|IN_PROJECT]->(p:Project {id: $id}) "
        "RETURN count(d) AS n", id=project_id)

    # Phase claims with the hours actually logged inside each phase window.
    # Hours counted there are the shared roll-up (hours.py) windowed to the
    # phase, the same number the phase's "In this phase" shows for it.
    claim_rows = []
    for r in await run_read(
        """
        MATCH (pr:Project {id: $id})-[r:CLAIMED_BY]->(ph:Phase)
        RETURN ph.id AS phase_id, ph.name AS phase, ph.start AS start, ph.end AS end,
               coalesce(r.hours, 0.0) AS planned_h
        """, id=project_id):
        win = await hours_index(str(r["start"])[:10], str(r["end"])[:10])
        claim_rows.append({"phase_id": r["phase_id"], "phase": r["phase"],
                           "planned_h": r["planned_h"],
                           "logged_mins": win.of(project_id)["mins"]})

    return {
        "root": node(root),
        "path": paths[project_id],
        "whys": await project_why(project_id),
        "ideas_given": ideas.get(project_id, []),
        "sessions_by_task": by_task,
        "docs": docs[0]["n"] if docs else 0,
        "claims": claim_rows,
    }


@router.post("/projects", status_code=201)
async def create_project(body: ProjectNest) -> dict:
    """A project, top level or nested. Nesting is the same call with a parent."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a project needs a name")
    pid = await _new_project(name, body.parent_id)
    if body.parent_id:
        await _hop_why(pid, "CHILD_OF", body.parent_id, body.why)
        parent_path = await _path_of(body.parent_id)
        await _write_move(f"project {parent_path}", "CHILD_OF ← project",
                          f'"{name}"', body.why or "")
    else:
        await _hop_why(pid, "CREATED", pid, body.why)
        await _write_move(f'project "{name}"', "CREATED", "", body.why or "")
    await record("project", "created", detail=name[:70], entity_id=pid)
    return {"id": pid, "name": name, "path": await _path_of(pid)}


@router.post("/projects/{project_id}/split", status_code=201)
async def split(project_id: str, body: ProjectSplit) -> dict:
    """Split a project: add a task under it.

    The task is a normal Inbox row that happens to be given to this project, so
    it shows up in both places. There is no such thing as a task that lives
    only in the tree.
    """
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a task needs a title")
    path = await _path_of(project_id)
    if not path:
        raise HTTPException(404, "no such project")
    tid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:Project {id: $pid})
        OPTIONAL MATCH (:Task)-[o:GIVEN_TO]->(p)
        WITH p, coalesce(max(o.order), 0.0) + 1.0 AS nxt
        CREATE (t:Task {id: $id, kind: 'task', title: $title, description: '',
                        status: 'open', category: '', priority: '',
                        paper_id: '', low_h: 0.0, high_h: 0.0, due: '',
                        done_at: '', notes: '', created_at: $now, position: 0.0})
        CREATE (t)-[:GIVEN_TO {date: $today, order: nxt}]->(p)
        """, pid=project_id, id=tid, title=title, now=_now(), today=_today())
    await _hop_why(tid, "GIVEN_TO", project_id, body.why)
    await _write_move(f"project {path}", "CHILD_OF ← task", f'"{title}"',
                      body.why or "")
    await record("project", "split into a task", detail=title[:70],
                 entity_id=tid)
    return await _one(tid)


@router.post("/projects/{project_id}/offshoot", status_code=201)
async def offshoot(project_id: str, body: ProjectOffshoot) -> dict:
    """Something the project made you think of, which is not the project.

    It lands in the Inbox as a raw idea carrying CAME_FROM, not as work. The
    whole value of an offshoot is that you did not have to decide what it was
    in order to write it down.
    """
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "an idea needs a title")
    path = await _path_of(project_id)
    if not path:
        raise HTTPException(404, "no such project")
    tid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:Project {id: $pid})
        CREATE (t:Task {id: $id, kind: 'idea', title: $title, description: '',
                        status: 'raw', category: '', priority: '',
                        paper_id: '', low_h: 0.0, high_h: 0.0, due: '',
                        done_at: '', notes: '', created_at: $now, position: 0.0})
        CREATE (t)-[:CAME_FROM {date: $today}]->(p)
        SET t:Idea
        """, pid=project_id, id=tid, title=title, now=_now(), today=_today())
    await _hop_why(tid, "CAME_FROM", project_id, body.why)
    await _write_move(f'idea "{title}"', "CAME_FROM", f"project {path}",
                      body.why or "")
    await record("project", "offshoot idea", detail=title[:70], entity_id=tid)
    return await _one(tid)


@router.post("/projects/{project_id}/ideas", status_code=201)
async def give_new_idea(project_id: str, body: ProjectOffshoot) -> dict:
    """Write an idea straight onto this project.

    Exactly what adding it in the Inbox and then giving it here would do, in
    one step: the row is created with kind='idea' and immediately handed over,
    so it lands at status 'given' rather than sitting in the Inbox as raw. The
    two-step route still exists and is the right one when you do not yet know
    where an idea belongs.
    """
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "an idea needs a title")
    path = await _path_of(project_id)
    if not path:
        raise HTTPException(404, "no such project")
    tid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:Project {id: $pid})
        CREATE (t:Task {id: $id, kind: 'idea', title: $title, description: '',
                        status: 'given', category: '', priority: '',
                        paper_id: '', low_h: 0.0, high_h: 0.0, due: '',
                        done_at: '', notes: '', created_at: $now, position: 0.0})
        CREATE (t)-[:GIVEN_TO {date: $today, order: 0.0}]->(p)
        SET t:Idea
        """, pid=project_id, id=tid, title=title, now=_now(), today=_today())
    await _hop_why(tid, "GIVEN_TO", project_id, body.why)
    await _write_move(f'idea "{title}"', "GIVEN_TO", path, body.why or "")
    await record("project", "idea given", detail=title[:70], entity_id=tid)
    return await _one(tid)


@router.patch("/projects/{project_id}")
async def edit_project(project_id: str, body: TreeProjectUpdate) -> dict:
    """Rename, re-estimate, re-rank, or say when it is done.

    An estimate typed here is an OVERRIDE: a project with children shows the
    sum of its children unless someone puts a number on the parent itself. The
    client sends `est_override` with the number so the two arrive together.
    """
    sets, params = [], {"id": project_id}
    for field in ("name", "done_when", "due", "status", "kind", "color"):
        val = getattr(body, field, None)
        if val is not None:
            if field == "status" and val not in PROJECT_STATUSES:
                raise HTTPException(
                    400, "status must be one of " + ", ".join(PROJECT_STATUSES))
            if field == "kind" and val not in WORK_TYPES:
                raise HTTPException(
                    400, "type must be one of " + ", ".join(WORK_TYPES))
            if field == "color" and val not in PROJECT_COLORS:
                raise HTTPException(
                    400, "color must be one of " + ", ".join(c or "(none)" for c in PROJECT_COLORS))
            sets.append(f"p.{field} = ${field}")
            params[field] = val
    for field in ("low_h", "high_h", "priority_order"):
        val = getattr(body, field, None)
        if val is not None:
            sets.append(f"p.{field} = ${field}")
            params[field] = float(val)
    if body.priority is not None:
        if int(body.priority) not in PRIORITIES:
            raise HTTPException(400, "priority must be 1, 2 or 3")
        sets.append("p.priority = $priority")
        params["priority"] = int(body.priority)
    if body.est_override is not None:
        sets.append("p.est_override = $est_override")
        params["est_override"] = bool(body.est_override)
    if body.done_at is not None:
        sets.append("p.done_at = $done_at")
        params["done_at"] = body.done_at
    if not sets:
        raise HTTPException(400, "nothing to change")
    rows = await run_write(
        "MATCH (p:Project {id: $id}) SET " + ", ".join(sets) +
        " RETURN p{.*} AS p", **params)
    if not rows:
        raise HTTPException(404, "no such project")
    if body.why:
        await _hop_why(project_id, "ESTIMATE", project_id, body.why)
    return dict(rows[0]["p"])


@router.post("/projects/reorder")
async def reorder_projects(body: ProjectReorder) -> dict:
    """The drag on the list's rank column. Writes priority_order for every row
    in one go, because a reorder is one decision about the whole list rather
    than n decisions about single rows."""
    await run_write(
        """
        UNWIND range(0, size($ids) - 1) AS i
        MATCH (p:Project {id: $ids[i]})
        SET p.priority_order = toFloat(i)
        """, ids=body.ids)
    return {"ok": True, "n": len(body.ids)}


@router.post("/projects/{project_id}/move")
async def move_project(project_id: str, body: ProjectMove) -> dict:
    """Re-parent a project: the drag of a row onto another row.

    Refuses to put a project inside its own subtree, which would cut that
    branch off the tree entirely and is never what the drag meant.
    """
    if body.parent_id == project_id:
        raise HTTPException(400, "a project cannot be its own parent")
    if body.parent_id:
        loop = await run_read(
            "MATCH (p:Project {id: $new})-[:CHILD_OF*1..]->(:Project {id: $me}) "
            "RETURN p.id AS id", new=body.parent_id, me=project_id)
        if loop:
            raise HTTPException(400, "that would put the project inside itself")

    old_path = await _path_of(project_id)
    await run_write(
        "MATCH (p:Project {id: $id})-[r:CHILD_OF]->() DELETE r", id=project_id)
    if body.parent_id:
        ok = await run_write(
            """
            MATCH (c:Project {id: $cid}), (p:Project {id: $pid})
            OPTIONAL MATCH (:Project)-[o:CHILD_OF]->(p)
            WITH c, p, coalesce(max(o.order), 0.0) + 1.0 AS nxt
            MERGE (c)-[r:CHILD_OF]->(p)
              ON CREATE SET r.date = $today, r.order = nxt
            RETURN p.name AS name
            """, cid=project_id, pid=body.parent_id, today=_today())
        if not ok:
            raise HTTPException(404, "no such parent project")
        await _hop_why(project_id, "CHILD_OF", body.parent_id, body.why)
    new_path = await _path_of(project_id)
    await _write_move(f"project {old_path}", "MOVED", new_path or "(top level)",
                      body.why or "")
    await record("project", "moved", detail=f"{old_path} → {new_path}"[:70],
                 entity_id=project_id)
    return {"id": project_id, "path": new_path}


@router.post("/projects/{project_id}/why", status_code=201)
async def add_project_why(project_id: str, body: WhyIn) -> dict:
    """A why or a note, written straight onto the project.

    Two kinds, one node type and one list. A why is a reason you decided
    something and a note is anything else worth keeping, and separating them
    into two stores would mean choosing which box a sentence belongs in before
    you have finished writing it. The `kind` field is the whole difference.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "a note with no words in it is not a note")
    kind = (body.kind or "why").strip().lower()
    if kind not in ("why", "note"):
        raise HTTPException(400, "kind must be why or note")
    rows = await run_write(
        """
        MATCH (p:Project {id: $id})
        CREATE (n:Note {id: $nid, date: $date, text: $text, kind: $kind,
                        created_at: $now})
        CREATE (n)-[:NOTE_ON]->(p)
        RETURN n{.*} AS n
        """, id=project_id, nid=str(uuid.uuid4()), date=_today(), text=text,
        kind=kind, now=_now())
    if not rows:
        raise HTTPException(404, "no such project")
    return dict(rows[0]["n"])


@router.get("/projects/{project_id}/why")
async def project_why(project_id: str) -> list[dict]:
    """Every why written about this project, newest first.

    Reads the notes on the node AND on the hops that touch it, because "why is
    this here" was answered when it was promoted, nested or given to, and all
    three of those are edges.
    """
    # Two reads rather than one. Collecting the node's own notes and the hops'
    # notes in a single query mixes an aggregation with a carried variable,
    # which Cypher rejects; merging two flat lists here is shorter than the
    # WITH-dance that would make one query legal.
    # Both kinds. The panel is one dated list and the kind is a label on each
    # entry, not a separate feed.
    direct = await run_read(
        """
        MATCH (n:Note)-[:NOTE_ON]->(:Project {id: $id})
        WHERE coalesce(n.kind, 'note') IN ['why', 'note']
        RETURN n{.*, on: 'project'} AS n
        """, id=project_id)
    # Both directions. Edges that END here are things handed to the project —
    # GIVEN_TO, BECAME. The edge that STARTS here is its own placement:
    # (this)-[:CHILD_OF]->(parent), and "why is this under Research" is a why
    # about this project, so reading only the inbound side would lose the
    # single most useful sentence on the page.
    on_hops = await run_read(
        """
        MATCH (n:Note)-[:NOTE_ON]->(h:Hop)
        WHERE h.to_id = $id OR h.from_id = $id
        RETURN n{.*, on: h.rel} AS n
        """, id=project_id)
    notes = [dict(r["n"]) for r in direct] + [dict(r["n"]) for r in on_hops]
    notes.sort(key=lambda n: n.get("created_at") or "", reverse=True)
    return notes


@router.post("/projects/{project_id}/done")
async def finish_project(project_id: str, body: ProjectDone) -> dict:
    """Tick a project. Optionally marks everything under it done too.

    The cascade is asked for rather than assumed: ticking a parent usually does
    mean the work under it is finished, but a project closed because it was
    abandoned has children that were never done, and silently marking them
    would write a false record.
    """
    rows = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name",
                          id=project_id)
    if not rows:
        raise HTTPException(404, "no such project")
    today = _today()
    await run_write(
        "MATCH (p:Project {id: $id}) SET p.status = $st, p.done_at = $at",
        id=project_id, st="done" if body.done else "active",
        at=today if body.done else "")
    if body.done and body.cascade:
        await run_write(
            """
            MATCH (root:Project {id: $id})
            MATCH (kid:Project)-[:CHILD_OF*1..]->(root)
            SET kid.status = 'done', kid.done_at = $at
            """, id=project_id, at=today)
        await run_write(
            """
            MATCH (root:Project {id: $id})
            MATCH (t:Task)-[:GIVEN_TO]->(p:Project)
            WHERE (p = root OR (p)-[:CHILD_OF*1..]->(root))
              AND t.kind = 'task' AND t.status = 'open'
            SET t.status = 'done', t.done_at = $at
            """, id=project_id, at=today)
    path = await _path_of(project_id)
    await _write_move(f"project {path}", "DONE" if body.done else "REOPENED",
                      "", body.why or "")
    await record("project", "done" if body.done else "reopened",
                 detail=rows[0]["name"][:70], entity_id=project_id)
    return {"id": project_id, "status": "done" if body.done else "active"}


# --------------------------------------------------------------------------- #
# Tasks in the tree
# --------------------------------------------------------------------------- #
@router.post("/tasks", status_code=201)
async def create_task(body: TreeTaskCreate) -> dict:
    """The add line under every project. A leading / already stripped by the
    client, which posts to /projects for that case."""
    return await split(body.project_id, ProjectSplit(title=body.title,
                                                     why=body.why or ""))


@router.patch("/tasks/{task_id}")
async def edit_task(task_id: str, body: TreeTaskUpdate) -> dict:
    """Rename, re-estimate, re-date or tick one task."""
    rows = await run_read(
        "MATCH (t:Task {id: $id}) RETURN t.title AS title, t.kind AS kind",
        id=task_id)
    if not rows:
        raise HTTPException(404, "no such task")

    sets, params = [], {"id": task_id}
    for field in ("title", "due"):
        val = getattr(body, field, None)
        if val is not None:
            sets.append(f"t.{field} = ${field}")
            params[field] = val
    for field in ("low_h", "high_h"):
        val = getattr(body, field, None)
        if val is not None:
            sets.append(f"t.{field} = ${field}")
            params[field] = float(val)
    if body.done is not None:
        sets.append("t.status = $status")
        sets.append("t.done_at = $done_at")
        params["status"] = "done" if body.done else "open"
        params["done_at"] = _today() if body.done else ""
    if sets:
        await run_write("MATCH (t:Task {id: $id}) SET " + ", ".join(sets),
                        **params)
    if body.done is not None:
        await _write_move(f'task "{rows[0]["title"]}"',
                          "DONE" if body.done else "REOPENED", "", "")
    if body.parent_id is not None:
        # Dragged onto another project.
        await run_write(
            """
            MATCH (t:Task {id: $id})-[r:GIVEN_TO]->() DELETE r
            """, id=task_id)
        ok = await run_write(
            """
            MATCH (t:Task {id: $id}), (p:Project {id: $pid})
            OPTIONAL MATCH (:Task)-[o:GIVEN_TO]->(p)
            WITH t, p, coalesce(max(o.order), 0.0) + 1.0 AS nxt
            MERGE (t)-[r:GIVEN_TO]->(p)
              ON CREATE SET r.date = $today, r.order = nxt
            RETURN p.name AS name
            """, id=task_id, pid=body.parent_id, today=_today())
        if not ok:
            raise HTTPException(404, "no such project")
        await _hop_why(task_id, "GIVEN_TO", body.parent_id, body.why)
        await _write_move(f'task "{rows[0]["title"]}"', "GIVEN_TO",
                          await _path_of(body.parent_id), body.why or "")
    return await _one(task_id)
