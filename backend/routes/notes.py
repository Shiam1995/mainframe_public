"""/api/notes — one note shape, for everything.

    (:Note {id, date, text, kind: note|why, created_at})-[:NOTE_ON]->(anything)

There is exactly one of these and every tab uses it. The alternative was a note
field per tab, which is how you end up unable to answer "why did I do that" in
one query because the answer is spread across nine tables.

APPEND ONLY. Editing a note does not change it. It writes a new one, dated
today, pointing at the old one with :SUPERSEDES; the old one stays exactly as
written. The newest note in a chain is the one that counts, the rest are
history you can open. This is the whole point of the shape: a reason you gave
in September and revised in November is two facts, not one fact that has been
overwritten, and the September one is often the more interesting.

NOTES ON EDGES. A note frequently belongs to a relationship rather than a thing
"why was this idea given to that project" is about the giving, not about the
idea and not about the project. Two ways to store that, and this file picks one:

    CHOSEN: a (:Hop) node standing in for the edge, notes hang off it like any
    other node. (:Idea)-[:GIVEN_TO]->(:Project) gets a companion
    (:Hop {rel: 'GIVEN_TO', from_id, to_id}) and notes attach to the Hop.

    REJECTED: notes as properties on the relationship itself. Simpler for one
    note, but append-only means an edge accumulates them, and a growing list on
    a relationship has to be serialised into a string to fit. That is a blob you
    cannot query, and the Reasoning tab exists specifically to query these.

The Hop pays for itself twice over: because it is a node, `NOTE_ON` is the only
attachment mechanism in the system, and the Reasoning tab reads every note ever
written with one MATCH instead of one for nodes and another for edges.

A Hop is created on demand by the first note written against that edge, and is
never created empty.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from activity import _entity_lookup, record
from db import run_read, run_write
from models import NoteCreate

router = APIRouter(prefix="/api/notes", tags=["notes"])

KINDS = ("note", "why")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# What a note is attached to, in words. The Reasoning tab shows this beside
# every why, so it has to work for a label this file has never heard of:
# whichever of these properties the node happens to carry is its name.
_TITLE = ("coalesce(t.title, t.name, t.text, t.label, t.what, t.question, "
          "t.summary, '(untitled)')")


async def _hop_id(from_id: str, rel: str, to_id: str, create: bool) -> str | None:
    """The :Hop standing in for one edge, made on demand.

    `rel` is stored as a property rather than being the Hop's label because a
    Hop is a Hop whichever relationship it stands for, and the Reasoning tab
    wants them all in one MATCH.
    """
    rows = await run_read(
        "MATCH (h:Hop {from_id: $f, rel: $r, to_id: $t}) RETURN h.id AS id",
        f=from_id, r=rel, t=to_id)
    if rows:
        return rows[0]["id"]
    if not create:
        return None
    hid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (h:Hop {id: $id, from_id: $f, rel: $r, to_id: $t, created_at: $now})
        """, id=hid, f=from_id, r=rel, t=to_id, now=_now())
    return hid


def _target_of(body: NoteCreate) -> tuple[str, str] | None:
    """Read the two ways of saying what a note is about. Returns (kind, value)
    so the caller can tell a node id from an edge triple without re-checking."""
    if body.target_id:
        return ("node", body.target_id)
    if body.from_id and body.rel and body.to_id:
        return ("edge", f"{body.from_id}|{body.rel}|{body.to_id}")
    return None


@router.post("", status_code=201)
async def create_note(body: NoteCreate) -> dict:
    """Write a note against a node or an edge.

    `supersedes` is how editing works: pass the id of the note this one
    replaces and both are kept, chained. Nothing is ever updated in place, so
    there is no PATCH on this router and there is not meant to be one.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "a note with no words in it is not a note")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")

    where = _target_of(body)
    if not where:
        raise HTTPException(400, "say what the note is about: target_id, or "
                                 "from_id + rel + to_id for an edge")

    if where[0] == "edge":
        target_id = await _hop_id(body.from_id, body.rel, body.to_id, create=True)
    else:
        target_id = where[1]

    nid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        UNWIND [$target] AS lid
        CALL (lid) {{ {_entity_lookup()} }}
        WITH e
        CREATE (n:Note {{id: $id, date: $date, text: $text, kind: $kind,
                        created_at: $now}})
        CREATE (n)-[:NOTE_ON]->(e)
        RETURN n{{.*}} AS note
        """, target=target_id, id=nid, date=body.date or date.today().isoformat(),
        text=text, kind=body.kind, now=_now())
    if not rows:
        raise HTTPException(404, "nothing with that id to attach a note to")

    if body.supersedes:
        # The chain, not a replacement: the old note keeps its text, its date
        # and its own place in the list.
        await run_write(
            "MATCH (new:Note {id: $new}), (old:Note {id: $old}) "
            "MERGE (new)-[:SUPERSEDES]->(old)", new=nid, old=body.supersedes)

    await record("note", "why written" if body.kind == "why" else "note written",
                 detail=text[:70], entity_id=target_id)
    return dict(rows[0]["note"])


@router.get("")
async def list_notes(
    target_id: str | None = None,
    from_id: str | None = None,
    rel: str | None = None,
    to_id: str | None = None,
    kind: str | None = Query(None, description="note | why"),
    limit: int = 200,
) -> list[dict]:
    """Notes on one thing, newest first.

    Every note in the chain comes back, including superseded ones: the client
    decides how much history to show, and a route that silently dropped the
    revised-away version would make the append-only store pointless.
    """
    if from_id and rel and to_id:
        target_id = await _hop_id(from_id, rel, to_id, create=False)
        if not target_id:
            return []                        # no hop yet means no notes yet
    if not target_id:
        raise HTTPException(400, "ask about something: target_id, or from_id + rel + to_id")

    rows = await run_read(
        f"""
        MATCH (n:Note)-[:NOTE_ON]->(t) WHERE t.id = $target
          AND ($kind IS NULL OR n.kind = $kind)
        OPTIONAL MATCH (newer:Note)-[:SUPERSEDES]->(n)
        OPTIONAL MATCH (n)-[:SUPERSEDES]->(older:Note)
        RETURN n{{.*}} AS note, newer.id AS superseded_by, older.id AS supersedes,
               head(labels(t)) AS target_label, {_TITLE} AS target_title
        ORDER BY n.created_at DESC
        LIMIT $limit
        """, target=target_id, kind=kind, limit=limit)
    return [_shape(r) for r in rows]


def _shape(r: dict) -> dict:
    n = dict(r["note"])
    n["superseded_by"] = r.get("superseded_by") or ""
    n["supersedes"] = r.get("supersedes") or ""
    # `current` is the one that counts: nothing later replaced it.
    n["current"] = not n["superseded_by"]
    n["target_label"] = r.get("target_label") or ""
    n["target_title"] = r.get("target_title") or ""
    return n


@router.get("/on/{target_id}/latest")
async def latest_note(target_id: str, kind: str = "why") -> dict:
    """The note that currently stands on something, or `{"note": null}`.

    A convenience for the many places that want to show one line rather than a
    history: a project's current why, an idea's current reason for being given
    away. The full chain is one call away when you want it.
    """
    rows = await run_read(
        """
        MATCH (n:Note)-[:NOTE_ON]->(t) WHERE t.id = $target AND n.kind = $kind
          AND NOT (:Note)-[:SUPERSEDES]->(n)
        RETURN n{.*} AS note ORDER BY n.created_at DESC LIMIT 1
        """, target=target_id, kind=kind)
    return {"note": dict(rows[0]["note"]) if rows else None}


# =========================================================================== #
# THE REASONING VIEW
#
# Every why ever written, with what it is attached to. This is the query the
# whole one-note-shape decision was made for: because notes hang off nodes and
# off :Hop nodes standing in for edges, one MATCH answers "why did I do that"
# across ideas, goals, projects, habits, phases and the claims between them.
# =========================================================================== #

# What each label is called in the view, and which area it belongs to. Anything
# not listed still shows, under its own label and "other" — a tab that hides
# reasoning because a new node type appeared would be worse than useless.
_AREA = {
    "Idea": ("idea", "synapse"), "PoolGoal": ("goal", "mainframe"),
    "Goal": ("goal", "mainframe"), "Project": ("project", "mainframe"),
    "Phase": ("phase", "mainframe"), "Task": ("task", "mainframe"),
    "Habit": ("habit", "pulse"), "Document": ("doc", "mainframe"),
    "Lesson": ("lesson", "mainframe"), "Hop": ("link", "mainframe"),
}

async def _titles(ids: list[str]) -> dict[str, str]:
    """Resolve a batch of node ids to something readable, by index.

    A :Hop is an edge, so its title is its two ends and the relationship
    between them, which means resolving ids the query does not hold as nodes.
    The obvious way to write that is `OPTIONAL MATCH (a) WHERE a.id = t.from_id`
    inside the main query — and that is an UNLABELLED match, which cannot use an
    index and therefore scans every node in the database. With the four-million
    row food catalogue in there it took this endpoint from instant to eighteen
    seconds a call. activity._entity_lookup() exists to avoid exactly that, so
    it is reused here: one UNWIND over the ids, one indexed seek each.
    """
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    rows = await run_read(
        f"""
        UNWIND $ids AS lid
        CALL (lid) {{ {_entity_lookup()} }}
        RETURN e.id AS id,
               coalesce(e.name, e.title, e.text, e.label, '') AS title
        """, ids=ids)
    return {r["id"]: r["title"] for r in rows if r["id"]}


@router.get("/why")
async def why_notes(
    phase_id: str | None = None,
    target_id: str | None = None,
    area: str | None = None,
    limit: int = 400,
) -> list[dict]:
    """Every why, newest first, with what it is about.

    Filters are the two the Reasoning tab offers: `phase_id` narrows to reasons
    written while that phase was running (the IN_PHASE hook files notes like
    everything else), and `target_id` narrows to one thing — a habit, an idea,
    a goal, a project.

    Superseded whys are included and marked. The point of an append-only store
    is being able to read what you used to think, so a view that dropped them
    would be arguing with its own design.
    """
    where = ["n.kind = 'why'"]
    params: dict = {"limit": limit}
    if phase_id:
        where.append("(n)-[:IN_PHASE]->(:Phase {id: $phase_id})")
        params["phase_id"] = phase_id
    if target_id:
        # Either the note is on the thing, or on an edge with the thing at
        # either end: asking "why this habit" should turn up the reason it was
        # claimed into a phase as well as the reason it exists.
        where.append("(t.id = $target_id OR t.from_id = $target_id OR t.to_id = $target_id)")
        params["target_id"] = target_id

    rows = await run_read(
        f"""
        MATCH (n:Note)-[:NOTE_ON]->(t)
        WHERE {' AND '.join(where)}
        OPTIONAL MATCH (newer:Note)-[:SUPERSEDES]->(n)
        OPTIONAL MATCH (n)-[:IN_PHASE]->(ph:Phase)
        RETURN n{{.*}} AS note, head(labels(t)) AS label, t.id AS target_id,
               {_TITLE} AS title, t.rel AS rel,
               t.from_id AS from_id, t.to_id AS to_id,
               newer.id AS superseded_by,
               ph.name AS phase, ph.id AS phase_id
        ORDER BY n.created_at DESC
        LIMIT $limit
        """, **params)

    ends = await _titles([e for r in rows for e in (r["from_id"], r["to_id"])])

    out = []
    for r in rows:
        label = r["label"] or ""
        kind, area_of = _AREA.get(label, (label.lower() or "thing", "other"))
        if label == "Hop":
            # "idea X -> project Y", so a reason about a link reads as one.
            rel = str(r["rel"] or "linked").lower().replace("_", " ")
            title = (f"{ends.get(r['from_id']) or '?'} {rel} "
                     f"{ends.get(r['to_id']) or '?'}")
        else:
            title = r["title"] or "(untitled)"
        if area and area_of != area:
            continue
        n = dict(r["note"])
        out.append({
            **n,
            "about": {"id": r["target_id"], "kind": kind, "area": area_of,
                      "title": title, "label": label},
            "phase": r["phase"] or "", "phase_id": r["phase_id"] or "",
            "current": not r["superseded_by"],
        })
    return out


@router.get("/why/things")
async def why_things() -> list[dict]:
    """Everything that has a why on it, for the "pick a thing" filter.

    Built from the notes rather than from a list of node types, so a habit that
    has never been explained does not clutter a filter that exists to find
    explanations.
    """
    rows = await run_read(
        f"""
        MATCH (n:Note)-[:NOTE_ON]->(t) WHERE n.kind = 'why'
        WITH t, count(n) AS notes
        RETURN t.id AS id, head(labels(t)) AS label, {_TITLE} AS title,
               t.rel AS rel, t.from_id AS from_id, t.to_id AS to_id, notes
        ORDER BY notes DESC, title
        """)
    ends = await _titles([e for r in rows for e in (r["from_id"], r["to_id"])])
    out = []
    for r in rows:
        label = r["label"] or ""
        kind, area_of = _AREA.get(label, (label.lower() or "thing", "other"))
        if label == "Hop":
            rel = str(r["rel"] or "linked").lower().replace("_", " ")
            title = (f"{ends.get(r['from_id']) or '?'} {rel} "
                     f"{ends.get(r['to_id']) or '?'}")
        else:
            title = r["title"] or "(untitled)"
        out.append({"id": r["id"], "kind": kind, "area": area_of,
                    "title": title, "notes": r["notes"]})
    return out
