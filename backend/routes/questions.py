"""/api/questions — the open questions, wherever they were asked.

    (:Question {id, text, kind, answer, answered, created_at, answered_at})
    (:Question)-[:ON]->(anything)        what it was asked of
    (:Question)-[:ABOUT]->(:Paper)       the paper or book behind that, if any
    (:Task)-[:CAME_FROM]->(:Question)    its Inbox row

ONE QUESTION PER NODE. The main question used to be a textarea on the reading
instance, which meant three questions from one pass were one string that
nothing could count, answer or carry forward. A row per question is what lets
the Questions tab exist at all.

EVERY QUESTION LANDS IN THE INBOX as an idea, with `came from` pointing at the
question. An idea you mark as a question the other way round (the ❓ in the
Inbox) reuses the row it is already written on — see `row_id`. That is the
same rule distractions follow into Lessons: the capture surface writes the
record, so there is nothing to remember to push. Answering
a question here does not touch its Inbox row; deciding what to do about a
question is the Inbox's job and closing it is a different act from answering.

ON, NOT ABOUT. `ON` is the thing you were looking at when you asked (the pass,
the task). `ABOUT` is the paper or book that pass belongs to, resolved here so
the Questions tab can group by source without walking the graph per row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import match_by_id, record
from db import run_read, run_write
from models import QuestionCreate, QuestionUpdate
from routes.inbox import create_row

router = APIRouter(prefix="/api/questions", tags=["questions"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_TITLE = "coalesce(x.title, x.name, x.text, x.label, '')"

_ROWS = """
MATCH (q:Question)
WHERE $$WHERE$$
OPTIONAL MATCH (q)-[:ON]->(x)
OPTIONAL MATCH (q)-[:ABOUT]->(p:Paper)
OPTIONAL MATCH (t:Task)-[:CAME_FROM]->(q)
RETURN q{.*} AS q, x.id AS on_id, head(labels(x)) AS on_label,
       CASE WHEN x IS NULL THEN '' ELSE %s END AS on_title,
       x.version AS on_version,
       p.id AS paper_id, p.title AS paper_title, t.id AS task_id
ORDER BY q.created_at DESC
""" % _TITLE


def _shape(r: dict) -> dict:
    q = dict(r["q"])
    q["answered"] = bool(q.get("answered"))
    q["answer"] = q.get("answer") or ""
    q["kind"] = q.get("kind") or "question"
    q["starred"] = bool(q.get("starred"))
    q["star_tone"] = (q.get("star_tone") or "priority") if q["starred"] else ""
    q["on"] = ({"id": r["on_id"], "label": r["on_label"], "title": r["on_title"],
                "version": r.get("on_version")} if r.get("on_id") else None)
    q["paper"] = ({"id": r["paper_id"], "title": r["paper_title"]}
                  if r.get("paper_id") else None)
    q["task_id"] = r.get("task_id")
    return q


@router.get("")
async def list_questions(parent_id: str | None = None, kind: str | None = None,
                         answered: bool | None = None) -> list[dict]:
    """Every question, or just the ones on one node. `parent_id` is what the
    list box passes so a box only ever shows its own rows."""
    where, params = ["true"], {}
    if parent_id:
        where.append("EXISTS { MATCH (q)-[:ON]->(n) WHERE n.id = $pid }")
        params["pid"] = parent_id
    if kind:
        where.append("coalesce(q.kind, 'question') = $kind")
        params["kind"] = kind
    if answered is not None:
        where.append("coalesce(q.answered, false) = $answered")
        params["answered"] = answered
    rows = await run_read(_ROWS.replace("$$WHERE$$", " AND ".join(where)), **params)
    return [_shape(r) for r in rows]


@router.post("", status_code=201)
async def add_question(body: QuestionCreate) -> dict:
    """A question, its edges, and its Inbox row, in that order."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "a question with no text is not a question")
    qid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (q:Question {id: $id, text: $text, kind: $kind, answer: '',
                            answered: false, created_at: $now, answered_at: ''})
        """, id=qid, text=text, kind=(body.kind or "question").strip() or "question",
        now=_now())
    if body.parent_id:
        await run_write(
            "MATCH (q:Question {id: $id}) " + match_by_id("pid", "n") + " "
            "MERGE (q)-[:ON]->(n)", id=qid, pid=body.parent_id)
        # The paper behind the pass, so the Questions tab can group by source.
        # Works whether the parent is the instance or the paper itself.
        await run_write(
            """
            MATCH (q:Question {id: $id})-[:ON]->(n)
            OPTIONAL MATCH (p1:Paper)-[:HAS_INSTANCE]->(n)
            WITH q, coalesce(p1, CASE WHEN n:Paper THEN n END) AS p
            WHERE p IS NOT NULL
            MERGE (q)-[:ABOUT]->(p)
            """, id=qid)
    # The Inbox row. A question asked from a list box writes one; a question
    # marked on a row you already wrote reuses that row, or the Inbox would
    # end up with the same sentence twice and you would have to drop one.
    # A question asked on a paper or a reading pass lives with the paper (and in
    # the Questions tab) — it never files an Inbox row (2026-11-08).
    on_paper = bool(body.parent_id) and not body.row_id and bool(await run_read(
        "MATCH (:Question {id: $id})-[:ON]->(n) WHERE n:Paper OR n:Instance "
        "RETURN 1 AS x", id=qid))
    if on_paper:
        tid = None
    elif body.row_id:
        rows = await run_read(
            "MATCH (t:Task {id: $tid}) RETURN t.id AS id, t.category AS category",
            tid=body.row_id)
        if not rows:
            raise HTTPException(404, "no such inbox row")
        tid = rows[0]["id"]
        # Only when it is blank: a row you filed under "rq" or "reading" keeps
        # that. The ❓ is drawn from the edge, not from this word.
        if not (rows[0].get("category") or "").strip():
            await run_write(
                "MATCH (t:Task {id: $tid}) SET t.category = 'question'", tid=tid)
    else:
        tid = await create_row(text, "idea", "question",
                               came_from=body.parent_id or qid)
    if tid:
        await run_write(
            "MATCH (t:Task {id: $tid}), (q:Question {id: $qid}) "
            "MERGE (t)-[:CAME_FROM]->(q)", tid=tid, qid=qid)
    await record("synapse", "question asked", detail=text[:70], entity_id=qid)
    rows = await run_read(_ROWS.replace("$$WHERE$$", "q.id = $id"), id=qid)
    return _shape(rows[0])


@router.patch("/{qid}")
async def update_question(qid: str, patch: QuestionUpdate) -> dict:
    fields = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    if not fields:
        raise HTTPException(400, "nothing to update")
    if "star_tone" in fields and fields["star_tone"] not in ("priority", "soon", "later"):
        raise HTTPException(400, "star_tone is priority, soon or later")
    if "text" in fields:
        fields["text"] = (fields["text"] or "").strip()
        if not fields["text"]:
            raise HTTPException(400, "a question with no text is not a question")
    # Answering stamps itself. A date you can type is a date that can be wrong.
    if fields.get("answered"):
        fields["answered_at"] = _now()
    elif fields.get("answered") is False:
        fields["answered_at"] = ""
    sets = ", ".join(f"q.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (q:Question {{id: $id}}) SET {sets} RETURN q.id AS id",
        id=qid, **fields)
    if not rows:
        raise HTTPException(404, "no such question")
    rows = await run_read(_ROWS.replace("$$WHERE$$", "q.id = $id"), id=qid)
    return _shape(rows[0])


@router.delete("/{qid}", status_code=204, response_class=Response)
async def delete_question(qid: str) -> Response:
    """Deletes the question. Its Inbox row stays: that row may have been given
    to a project and worked on, and deleting it here would take work with it."""
    await run_write("MATCH (q:Question {id: $id}) DETACH DELETE q", id=qid)
    await record("synapse", "question deleted", entity_id=qid)
    return Response(status_code=204)
