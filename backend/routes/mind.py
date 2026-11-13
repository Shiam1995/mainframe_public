"""/api/mind — the mind-dump inbox (Mainframe-level, not Synapse-specific).

A global quick-capture list: "stick this idea here", "come look at this",
loose notes. Each item optionally links back to a paper and/or an external URL,
and can be checked off (status open → done). Kept as (:MindDump) nodes so items
can later be promoted to tasks/ideas or wired into the graph.

TALKING IT THROUGH. /analyse takes a transcript — spoken into the page via the
local whisper, or typed — and returns the main points as a PROPOSAL, saving
nothing; /commit files the corrected result. Same contract as the diary split
and for the same reason: the extraction is a guess, and a guess you can see and
fix before it lands is the difference between a journal you trust and one you
stop talking to.

THE TRANSCRIPT IS THE RECORD. /commit saves what you actually said, whole and
unedited, as one item; each point is its own item hanging off it by
(:MindDump)-[:FROM_DUMP]->(:MindDump), carrying the `quote` it came from. So
condensing never costs you your words — the long version is always one hop
away, which is the thing that makes it safe to let a model shorten you at all.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
import llm
from routes.inbox import create_row, give_to
from models import (
    MindAnalyse, MindCommit, MindDumpCreate, MindDumpUpdate, MoveGive,
    ReorderRequest,
)

router = APIRouter(prefix="/api/mind", tags=["mind"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def reorder_nodes(label: str, ids: list[str]) -> list[dict]:
    """Reassign the positions held by `ids` in the order given (see ReorderRequest).

    Shared by the mind-dump and idea reorder endpoints — both order their cards
    by a `position` float and both need swaps to be filter-safe.
    """
    if len(ids) < 2:
        raise HTTPException(400, "need at least two ids to reorder")
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "duplicate ids")
    rows = await run_read(
        f"MATCH (n:{label}) WHERE n.id IN $ids RETURN n.id AS id, n.position AS pos",
        ids=ids,
    )
    if len(rows) != len(ids):
        raise HTTPException(404, "one or more items not found")
    slots = sorted(
        (r["pos"] if r["pos"] is not None else float(i)) for i, r in enumerate(rows)
    )
    pairs = [{"id": nid, "pos": float(slots[i])} for i, nid in enumerate(ids)]
    await run_write(
        f"UNWIND $pairs AS p MATCH (n:{label} {{id: p.id}}) SET n.position = p.pos",
        pairs=pairs,
    )
    return pairs


@router.get("")
async def list_dumps(status: str | None = None, kind: str | None = None) -> list[dict]:
    clauses = []
    params: dict = {}
    if status:
        clauses.append("m.status = $status")
        params["status"] = status
    if kind:
        clauses.append("m.kind = $kind")
        params["kind"] = kind
    cypher = "MATCH (m:MindDump)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    # Manual order first (position ascending); anything not yet positioned falls
    # to the bottom in newest-first order.
    # `from_dump` is what a point came out of, and `points` is how many came
    # out of a transcript. Both read off the same FROM_DUMP edge, so a card
    # says which side of the split it is on without a second query.
    cypher += """
        OPTIONAL MATCH (m)-[:FROM_DUMP]->(src:MindDump)
        OPTIONAL MATCH (child:MindDump)-[:FROM_DUMP]->(m)
        WITH m, src, count(child) AS points
        RETURN m, points,
               CASE WHEN src IS NULL THEN null
                    ELSE {id: src.id, text: src.text} END AS from_dump
        ORDER BY coalesce(m.position, 1e15) ASC, m.created_at DESC"""
    rows = await run_read(cypher, **params)
    return [{**dict(r["m"]), "points": r["points"],
             "from_dump": r["from_dump"]} for r in rows]


# --------------------------------------------------------------------------- #
# Notes written *on* an item
#
# A reading pass (:Instance) and a project pass (:ProjectPass) both carry a
# `notes` field — the write-up you fill in while you're on that item. Those are
# notes in every sense except that they were never visible anywhere notes live,
# only inside the item's own Master Instance.
#
# They are surfaced here rather than copied into :MindDump. A copy would go
# stale the moment you edited the pass, and the same reasoning already governs
# the diary: a module's tab is the one store filtered, not a second store kept
# in step. So this is a read-only window — edits still happen on the pass.
# --------------------------------------------------------------------------- #
@router.get("/item-notes")
async def item_notes(ref_id: str | None = None, limit: int = 200) -> list[dict]:
    """Session write-ups, shaped like mind-dump cards. Read-only.

    `ref_id` narrows to one paper or project — that's the item's own widget
    asking "what have I already written here?".
    """
    rows = await run_read(
        """
        CALL () {
          // A reading pass's notes and "what I understood" are + rows on it
          // (kinds 'note' and 'understood'), joined back into one card here.
          MATCH (p:Paper)-[:HAS_INSTANCE]->(i:Instance)
          WITH p, i,
               COLLECT { MATCH (r:Row)-[:ON]->(i) WHERE coalesce(r.kind, 'note') = 'note'
                         RETURN r.text ORDER BY r.created_at } AS nts,
               COLLECT { MATCH (r:Row)-[:ON]->(i) WHERE r.kind = 'understood'
                         RETURN r.text ORDER BY r.created_at } AS und
          WHERE size(nts) > 0 OR size(und) > 0
          RETURN p.id AS ref_id, 'paper' AS ref_kind, p.title AS ref_title,
                 i.id AS id, i.version AS version, i.purpose AS purpose,
                 reduce(t = '', x IN nts | t + CASE WHEN t = '' THEN '' ELSE '\n' END + x) AS text,
                 reduce(t = '', x IN und | t + CASE WHEN t = '' THEN '' ELSE '\n' END + x) AS understood,
                 coalesce(i.read_date, i.created_at) AS created_at
          UNION
          MATCH (p:Project)-[:HAS_PASS]->(i:ProjectPass)
          WHERE trim(coalesce(i.notes, '')) <> ''
          RETURN p.id AS ref_id, 'project' AS ref_kind, p.name AS ref_title,
                 i.id AS id, i.version AS version, i.purpose AS purpose,
                 i.notes AS text, '' AS understood, i.created_at AS created_at
        }
        WITH * WHERE $ref_id IS NULL OR ref_id = $ref_id
        RETURN * ORDER BY coalesce(created_at, '') DESC LIMIT $limit
        """,
        ref_id=ref_id, limit=max(1, min(limit, 1000)),
    )
    return [
        {
            "id": r["id"],
            "text": r["text"] or "",
            # The write-up's second answer, carried alongside rather than as its
            # own card — it's the same pass talking, so it reads as one note.
            "understood": r["understood"] or "",
            "kind": "note",
            "origin": "session",          # tells the card it can't be edited here
            "ref_id": r["ref_id"],
            "ref_kind": r["ref_kind"],
            "ref_title": r["ref_title"],
            # paper_id/paper_title keep the card interchangeable with a MindDump
            "paper_id": r["ref_id"] if r["ref_kind"] == "paper" else None,
            "paper_title": r["ref_title"] if r["ref_kind"] == "paper" else None,
            "version": r["version"],
            "purpose": r["purpose"] or "",
            "status": "open",
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.post("", status_code=201)
async def create_dump(body: MindDumpCreate) -> dict:
    paper_title = None
    if body.paper_id:
        prows = await run_read("MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=body.paper_id)
        paper_title = prows[0]["title"] if prows else None
    mid = str(uuid.uuid4())
    rows = await run_write(
        """
        OPTIONAL MATCH (x:MindDump)
        WITH coalesce(min(x.position), 0.0) - 1.0 AS pos
        CREATE (m:MindDump {
            id: $id, text: $text, detail: $detail, kind: $kind, status: 'open',
            link: $link, paper_id: $paper_id, paper_title: $paper_title,
            created_at: $now, position: pos
        })
        WITH m
        OPTIONAL MATCH (p:Paper {id: $paper_id})
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
            MERGE (m)-[:ABOUT]->(p))
        RETURN m
        """,
        id=mid, text=body.text.strip(), detail=body.detail, kind=body.kind,
        link=body.link, paper_id=body.paper_id, paper_title=paper_title, now=_now(),
    )
    await record("mind", "captured", detail=body.text[:70], paper_id=body.paper_id, paper_title=paper_title)
    return dict(rows[0]["m"])


@router.post("/analyse")
async def analyse(body: MindAnalyse) -> dict:
    """Pull the main points out of a transcript. Writes nothing."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "nothing to analyse")
    points = await llm.extract_points(text, body.prompt_override)
    status = await llm.status()
    return {
        "points": points,
        "analysed_by": ("the local model" if status.get("effective") == "ollama"
                        else "keyword rules"),
        "kinds": list(llm.MIND_KINDS),
    }


async def _new_dump(text: str, kind: str, detail: str = "") -> str:
    """One capture card, at the top of the list. Returns its id."""
    mid = str(uuid.uuid4())
    await run_write(
        """
        OPTIONAL MATCH (x:MindDump)
        WITH coalesce(min(x.position), 0.0) - 1.0 AS pos
        CREATE (m:MindDump {
            id: $id, text: $text, detail: $detail, kind: $kind, status: 'open',
            link: null, paper_id: null, paper_title: null,
            created_at: $now, position: pos
        })
        """, id=mid, text=text[:300], detail=detail, kind=kind, now=_now())
    return mid


@router.post("/commit", status_code=201)
async def commit(body: MindCommit) -> dict:
    """File a talked-through journal: the transcript, then the points kept.

    The transcript is written FIRST and unconditionally. If the points are all
    unticked you still get the journal entry — what you said is worth keeping
    on its own, and losing it because the extraction was useless would be the
    worst outcome here.
    """
    transcript = (body.transcript or "").strip()
    if not transcript:
        raise HTTPException(400, "nothing to file")

    # The card's front is a title; the transcript itself lives in `detail`,
    # which is what the expanded card shows.
    title = (body.title or "").strip() or transcript.split("\n")[0].strip()
    if len(title) > 120:
        title = title[:117].rsplit(" ", 1)[0] + "…"
    src = await _new_dump(title, "note", detail=transcript)

    saved, sent = [], []
    for pt in body.points:
        text = (pt.text or "").strip()
        if not text:
            continue

        if pt.dest == "inbox":
            # Through the Inbox's own create, never a CREATE of our own: it is
            # what keeps the :Idea label in step with `kind`, and it records
            # this journal as where the row came from.
            tid = await create_row(text, pt.inbox_kind, came_from=src)
            if pt.project_id:
                # Giving it to a project is what puts it in the tree. The row
                # stays in the Inbox either way — one node serves both views.
                await give_to(tid, MoveGive(project_id=pt.project_id,
                                            why="said in the journal"))
            sent.append(tid)
            continue

        pid = await _new_dump(
            text, pt.kind if pt.kind in llm.MIND_KINDS else "note",
            # The quote is the point's provenance, kept on the card itself so
            # it survives the source being edited or deleted later.
            detail=(f"“{pt.quote.strip()}”" if pt.quote.strip() else ""))
        await run_write(
            "MATCH (p:MindDump {id: $pid}), (s:MindDump {id: $sid}) "
            "MERGE (p)-[:FROM_DUMP]->(s)", pid=pid, sid=src)
        saved.append(pid)

    await record("mind", "talked it through",
                 detail=f"{title[:50]} · {len(saved)} kept, {len(sent)} to inbox"[:70],
                 entity_id=src)
    return {"source_id": src, "points_saved": len(saved),
            "sent_to_inbox": len(sent)}


@router.post("/reorder")
async def reorder_dumps(body: ReorderRequest) -> dict:
    pairs = await reorder_nodes("MindDump", body.ids)
    await record("mind", "reordered", detail=f"{len(pairs)} items")
    return {"ok": True, "positions": pairs}


@router.patch("/{dump_id}")
async def update_dump(dump_id: str, patch: MindDumpUpdate) -> dict:
    # exclude_unset (not exclude_none) so a field can be cleared back to empty.
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    # Re-point the :ABOUT edge + the denormalised title when the paper changes.
    if "paper_id" in fields:
        title = None
        if fields["paper_id"]:
            prows = await run_read(
                "MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=fields["paper_id"]
            )
            title = prows[0]["title"] if prows else None
        fields["paper_title"] = title
        await run_write(
            """
            MATCH (m:MindDump {id: $id})
            OPTIONAL MATCH (m)-[r:ABOUT]->(:Paper)
            DELETE r
            WITH m
            OPTIONAL MATCH (p:Paper {id: $paper_id})
            FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                MERGE (m)-[:ABOUT]->(p))
            """,
            id=dump_id, paper_id=fields["paper_id"],
        )
    sets = ", ".join(f"m.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (m:MindDump {{id: $id}}) SET {sets} RETURN m", id=dump_id, **fields
    )
    if not rows:
        raise HTTPException(404, "mind-dump item not found")
    verb = "done" if fields.get("status") == "done" else "reopened" if fields.get("status") == "open" else "updated"
    await record("mind", verb, detail=", ".join(fields))
    return dict(rows[0]["m"])


@router.delete("/{dump_id}", status_code=204, response_class=Response)
async def delete_dump(dump_id: str) -> Response:
    await run_write("MATCH (m:MindDump {id: $id}) DETACH DELETE m", id=dump_id)
    await record("mind", "deleted", detail=dump_id)
    return Response(status_code=204)
