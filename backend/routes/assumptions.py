"""/api/assumptions — what you took for granted, wherever you took it.

    (:Assumption {id, number, text, kind, status, note, created_at, checked_at})
    (:Assumption)-[:ON]->(anything)        what it was assumed about
    (:Assumption)-[:ABOUT]->(:Paper)       the paper or book behind that, if any

THE SAME SHAPE AS A QUESTION, so the one ListBox serves both: GET ?parent_id=
&kind=, POST {text, kind, parent_id}, PATCH /:id, DELETE /:id. A question asks
something; an assumption is the thing you didn't ask and went ahead on anyway,
and listing them is what lets you go back and check them.

NUMBERED ONCE, NEVER REUSED. `number` comes from a single :Counter so A7 is A7
in the reading pass, the project and the Assumptions tab, and deleting A3
doesn't renumber everything after it — a number you've written down elsewhere
has to keep meaning the same thing.

CHECKING, NOT ANSWERING. An assumption is open until you test it, and then it
either held or broke. `note` is what showed you which.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import match_by_id, record
from db import run_read, run_write
from models import AssumptionCreate, AssumptionUpdate

router = APIRouter(prefix="/api/assumptions", tags=["assumptions"])

STATUSES = ("open", "held", "broke")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_TITLE = "coalesce(x.title, x.name, x.text, x.label, '')"

_ROWS = """
MATCH (a:Assumption)
WHERE $$WHERE$$
OPTIONAL MATCH (a)-[:ON]->(x)
OPTIONAL MATCH (a)-[:ABOUT]->(p:Paper)
RETURN a{.*} AS a, x.id AS on_id, head(labels(x)) AS on_label,
       CASE WHEN x IS NULL THEN '' ELSE %s END AS on_title,
       x.version AS on_version, x.date AS on_date,
       p.id AS paper_id, p.title AS paper_title
ORDER BY a.number DESC
""" % _TITLE


def _shape(r: dict) -> dict:
    a = dict(r["a"])
    a["status"] = a.get("status") or "open"
    a["note"] = a.get("note") or ""
    a["kind"] = a.get("kind") or "assumption"
    a["on"] = ({"id": r["on_id"], "label": r["on_label"], "title": r["on_title"],
                "version": r.get("on_version"), "date": r.get("on_date")}
               if r.get("on_id") else None)
    a["paper"] = ({"id": r["paper_id"], "title": r["paper_title"]}
                  if r.get("paper_id") else None)
    return a


@router.get("")
async def list_assumptions(parent_id: str | None = None, kind: str | None = None,
                           status: str | None = None) -> list[dict]:
    where, params = ["true"], {}
    if parent_id:
        where.append("EXISTS { MATCH (a)-[:ON]->(n) WHERE n.id = $pid }")
        params["pid"] = parent_id
    if kind:
        where.append("coalesce(a.kind, 'assumption') = $kind")
        params["kind"] = kind
    if status:
        where.append("coalesce(a.status, 'open') = $status")
        params["status"] = status
    rows = await run_read(_ROWS.replace("$$WHERE$$", " AND ".join(where)), **params)
    out = [_shape(r) for r in rows]
    # A list box reads top to bottom in the order you wrote them; the tab
    # reads newest first.
    if parent_id:
        out.reverse()
    return out


@router.get("/count")
async def count_assumptions() -> dict:
    """The top-bar badge: how many are still unchecked, and how many in all."""
    rows = await run_read(
        "MATCH (a:Assumption) RETURN count(a) AS total, "
        "count(CASE WHEN coalesce(a.status, 'open') = 'open' THEN 1 END) AS open")
    return rows[0] if rows else {"total": 0, "open": 0}


@router.post("", status_code=201)
async def add_assumption(body: AssumptionCreate) -> dict:
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "an assumption with no text is not an assumption")
    aid = str(uuid.uuid4())
    await run_write(
        """
        MERGE (c:Counter {name: 'assumption'})
        SET c.n = coalesce(c.n, 0) + 1
        CREATE (a:Assumption {id: $id, number: c.n, text: $text, kind: $kind,
                              status: 'open', note: '', created_at: $now,
                              checked_at: ''})
        """, id=aid, text=text,
        kind=(body.kind or "assumption").strip() or "assumption", now=_now())
    if body.parent_id:
        await run_write(
            "MATCH (a:Assumption {id: $id}) " + match_by_id("pid", "n") + " "
            "MERGE (a)-[:ON]->(n)", id=aid, pid=body.parent_id)
        await run_write(
            """
            MATCH (a:Assumption {id: $id})-[:ON]->(n)
            OPTIONAL MATCH (p1:Paper)-[:HAS_INSTANCE]->(n)
            WITH a, coalesce(p1, CASE WHEN n:Paper THEN n END) AS p
            WHERE p IS NOT NULL
            MERGE (a)-[:ABOUT]->(p)
            """, id=aid)
    await record("assumption", "assumption made", detail=text[:70], entity_id=aid)
    rows = await run_read(_ROWS.replace("$$WHERE$$", "a.id = $id"), id=aid)
    return _shape(rows[0])


@router.patch("/{aid}")
async def update_assumption(aid: str, patch: AssumptionUpdate) -> dict:
    fields = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    if not fields:
        raise HTTPException(400, "nothing to update")
    if "text" in fields:
        fields["text"] = (fields["text"] or "").strip()
        if not fields["text"]:
            raise HTTPException(400, "an assumption with no text is not an assumption")
    if "status" in fields:
        if fields["status"] not in STATUSES:
            raise HTTPException(400, "status is one of " + ", ".join(STATUSES))
        fields["checked_at"] = "" if fields["status"] == "open" else _now()
    sets = ", ".join(f"a.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (a:Assumption {{id: $id}}) SET {sets} RETURN a.id AS id",
        id=aid, **fields)
    if not rows:
        raise HTTPException(404, "no such assumption")
    rows = await run_read(_ROWS.replace("$$WHERE$$", "a.id = $id"), id=aid)
    return _shape(rows[0])


@router.delete("/{aid}", status_code=204, response_class=Response)
async def delete_assumption(aid: str) -> Response:
    await run_write("MATCH (a:Assumption {id: $id}) DETACH DELETE a", id=aid)
    await record("assumption", "assumption deleted", entity_id=aid)
    return Response(status_code=204)
