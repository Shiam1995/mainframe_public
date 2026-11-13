"""/api/synapse/instances — reading instances (v1, v2, ...) per paper.

Each time you read a paper you create an Instance: a versioned engagement with
pre/post familiarity coverage and a code-depth level (L0-L5). The annotated copy
lives under ~/.mainframe/papers/instances.
"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from activity import record
from routes.lessons import log_distraction_as_lesson
from config import settings
from db import run_read, run_write
from models import InstanceCreate, InstanceUpdate, ReorderRequest
from routes.mind import reorder_nodes
from routes.rows import row_texts

router = APIRouter(prefix="/api/synapse/instances", tags=["instances"])


def _mins_between(start: str, end: str) -> int:
    """Duration from HH:MM..HH:MM. A session crossing midnight wraps."""
    try:
        sh, sm = (int(x) for x in start.split(":")[:2])
        eh, em = (int(x) for x in end.split(":")[:2])
    except (ValueError, AttributeError):
        return 0
    delta = (eh * 60 + em) - (sh * 60 + sm)
    return delta + 24 * 60 if delta < 0 else delta


@router.get("")
async def list_instances(paper_id: str) -> list[dict]:
    """Every pass on a paper, each carrying how often it has been pushed.

    `push_count` is how many :WorkSession rows were pushed FROM this pass —
    matched on the `instance_id` the push writes, not on a relationship, so
    deleting the pass leaves the hours in the work database where they belong.
    Passes read before that field existed report 0: their hours are on the
    paper, they just never said which pass they came from.
    """
    rows = await run_read(
        """
        MATCH (p:Paper {id: $pid})-[:HAS_INSTANCE]->(i:Instance)
        OPTIONAL MATCH (w:WorkSession) WHERE w.instance_id = i.id
        WITH i, collect(w{.*}) AS ws
        RETURN i, size(ws) AS push_count,
               reduce(s = 0, x IN ws | s + coalesce(x.mins, 0)) AS push_mins
        ORDER BY coalesce(i.position, toFloat(i.version)) ASC, i.version ASC
        """,
        pid=paper_id,
    )
    # The + rows on each pass (notes, what I understood, to look into), by
    # kind: the chip's ⌛ hover and the push-to-database prefill read them.
    texts = await row_texts([r["i"]["id"] for r in rows])
    out = []
    for r in rows:
        inst = dict(r["i"])
        inst["push_count"] = r["push_count"] or 0
        inst["push_mins"] = r["push_mins"] or 0
        inst["row_text"] = texts.get(inst["id"], {})
        out.append(inst)
    return out


@router.post("/reorder")
async def reorder_instances(body: ReorderRequest) -> dict:
    """Move reading passes around.

    `version` still records which pass came first and never changes — the order
    you *read* in is a fact. `position` is only how they're arranged on screen,
    so a pass can be moved without rewriting history. Same shared helper the
    mind-dumps and ideas use, so reordering inside a filtered view is safe.
    """
    pairs = await reorder_nodes("Instance", body.ids)
    await record("instance", "reordered", detail=f"{len(pairs)} passes")
    return {"ok": True, "positions": pairs}


@router.get("/master")
async def master_instance(paper_id: str) -> dict:
    """The Master Instance — everything you wrote about a paper, in one document.

    Read-only and auto-generated: it pulls highlights, session notes, concepts,
    ideas and mind-dumps from every reading pass and merges them into one
    chronological stream. Each block is tagged with the instance it came from
    (v1, v2, ...), a timestamp, a section where one exists, and the time spent
    on that pass. Nothing here is authored directly — delete a pass and its
    blocks disappear with it.
    """
    ctx = await run_read("MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=paper_id)
    if not ctx:
        raise HTTPException(404, "paper not found")

    insts = await run_read(
        """
        MATCH (:Paper {id: $pid})-[:HAS_INSTANCE]->(i:Instance)
        OPTIONAL MATCH (i)-[:CONTAINS]->(h:Highlight)
        WITH i, collect(h{.*}) AS highlights
        RETURN i{.*} AS inst, highlights
        ORDER BY i.version ASC
        """,
        pid=paper_id,
    )
    concepts = await run_read(
        """
        MATCH (:Paper {id: $pid})-[:INTRODUCES]->(c:Concept)
        RETURN c{.*} AS c ORDER BY c.name
        """,
        pid=paper_id,
    )
    ideas = await run_read(
        "MATCH (i:Idea) WHERE i.paper_id = $pid RETURN i{.*} AS i ORDER BY coalesce(i.created_at, '')",
        pid=paper_id,
    )
    dumps = await run_read(
        """
        MATCH (m:MindDump)-[:ABOUT]->(:Paper {id: $pid})
        RETURN m{.*} AS m ORDER BY coalesce(m.created_at, '')
        """,
        pid=paper_id,
    )
    # Everything that has happened to this paper. The activity log already
    # records every mutation against `paper_id`, so the history comes free —
    # what was missing was somewhere to read it alongside the writing.
    events = await run_read(
        """
        MATCH (c:ChangeEvent) WHERE c.paper_id = $pid
        RETURN c{.*} AS c ORDER BY coalesce(c.timestamp, '') DESC LIMIT 200
        """,
        pid=paper_id,
    )

    # notes / understood / look into are + rows on the pass now, not strings.
    texts = await row_texts([r["inst"].get("id") for r in insts])

    blocks: list[dict] = []
    passes: list[dict] = []
    totals = {"mins": 0, "active_mins": 0, "passive_mins": 0, "distractions": 0, "highlights": 0}

    for row in insts:
        inst, hls = row["inst"], [h for h in row["highlights"] if h.get("id")]
        label = "v" + str(inst.get("version"))
        stamp = inst.get("read_date") or (inst.get("created_at") or "")[:10]
        mins = inst.get("mins") or 0
        totals["mins"] += mins
        totals["active_mins"] += inst.get("active_mins") or 0
        totals["passive_mins"] += inst.get("passive_mins") or 0
        totals["distractions"] += inst.get("distractions") or 0
        totals["highlights"] += len(hls)
        passes.append({
            "instance_id": inst.get("id"), "version": inst.get("version"),
            "purpose": inst.get("purpose"), "date": stamp, "mins": mins,
            "active_mins": inst.get("active_mins") or 0,
            "passive_mins": inst.get("passive_mins") or 0,
            "distractions": inst.get("distractions") or 0,
            "highlight_count": len(hls),
            "coverage_pre": inst.get("coverage_pre"), "coverage_post": inst.get("coverage_post"),
            "code_depth": inst.get("code_depth"),
        })
        rt = texts.get(inst.get("id"), {})
        if rt.get("note"):
            blocks.append({
                "kind": "session note", "instance": label, "date": stamp,
                "section": None, "mins": mins, "tag": inst.get("purpose"),
                "title": "", "body": "\n".join(rt["note"]),
            })
        if rt.get("understood"):
            blocks.append({
                "kind": "understood", "instance": label, "date": stamp,
                "section": None, "mins": 0, "tag": "what I understood",
                "title": "", "body": "\n".join(rt["understood"]),
            })
        if (inst.get("main_question") or "").strip():
            blocks.append({
                "kind": "main question", "instance": label, "date": stamp,
                "section": None, "mins": 0, "tag": "left open",
                "title": "", "body": inst["main_question"].strip(),
            })
        if rt.get("look into"):
            blocks.append({
                "kind": "look into", "instance": label, "date": stamp,
                "section": None, "mins": 0, "tag": "to come back to",
                "title": "", "body": "\n".join(rt["look into"]),
            })
        items = [d for d in (inst.get("distraction_items") or []) if (d or "").strip()]
        if items:
            blocks.append({
                "kind": "distractions", "instance": label, "date": stamp,
                "section": None, "mins": 0,
                "tag": str(inst.get("distractions") or len(items)) + "×",
                "title": "",
                # One per line — they're separate interruptions, not one phrase.
                "body": "\n".join("· " + d.strip() for d in items),
            })
        hls.sort(key=lambda h: (h.get("section") or "", h.get("page") or 0))
        for h in hls:
            blocks.append({
                "kind": "highlight", "instance": label, "date": stamp,
                "section": h.get("section") or None, "page": h.get("page"),
                "mins": mins, "tag": h.get("tag"),
                "title": (h.get("excerpt") or "").strip(),
                "body": (h.get("my_note") or "").strip(),
            })

    for r in concepts:
        c = r["c"]
        blocks.append({
            "kind": "concept", "instance": None, "date": None, "section": None,
            "mins": 0, "tag": "familiarity " + str(c.get("familiarity", "")),
            "title": c.get("name") or "", "body": (c.get("definition") or "").strip(),
        })
    for r in ideas:
        i = r["i"]
        blocks.append({
            "kind": "idea", "instance": None, "date": (i.get("created_at") or "")[:10],
            "section": None, "mins": 0, "tag": i.get("category"),
            "title": i.get("title") or "", "body": (i.get("description") or "").strip(),
        })
    for r in dumps:
        m = r["m"]
        blocks.append({
            "kind": m.get("kind") or "mind dump", "instance": None,
            "date": (m.get("created_at") or "")[:10], "section": None, "mins": 0,
            "tag": m.get("link"), "title": m.get("text") or "",
            "body": (m.get("detail") or "").strip(),
        })

    # The log is kept OUT of `blocks` and returned separately: blocks are things
    # you wrote, the log is what happened to the paper. Merging them would bury
    # a highlight under twenty "updated" rows.
    log = [{
        "timestamp": r["c"].get("timestamp"),
        "category": r["c"].get("category"),
        "action": r["c"].get("action"),
        "detail": r["c"].get("detail"),
        "trigger": r["c"].get("trigger"),
    } for r in events]

    return {
        "paper_id": paper_id,
        "paper_title": ctx[0]["title"],
        "passes": passes,
        "totals": totals,
        "blocks": blocks,
        "log": log,
        "counts": {
            "passes": len(passes), "highlights": totals["highlights"],
            "concepts": len(concepts), "ideas": len(ideas), "dumps": len(dumps),
            "blocks": len(blocks), "log": len(log),
        },
    }


@router.post("", status_code=201)
async def create_instance(paper_id: str, body: InstanceCreate) -> dict:
    prows = await run_read("MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=paper_id)
    if not prows:
        raise HTTPException(404, "paper not found")
    title = prows[0]["title"]

    # Next version number = current count + 1.
    cnt = await run_read(
        "MATCH (:Paper {id: $id})-[:HAS_INSTANCE]->(i:Instance) RETURN count(i) AS n",
        id=paper_id,
    )
    version = (cnt[0]["n"] or 0) + 1

    inst_id = str(uuid.uuid4())
    # Copy the original PDF into instances/ as the annotation base — when there
    # is one. A source with no file (a book you own on paper, a video series)
    # still gets passes; they just have nothing to annotate on top of.
    settings.papers_instances.mkdir(parents=True, exist_ok=True)
    orig = await run_read("MATCH (p:Paper {id: $id}) RETURN p.original_path AS op", id=paper_id)
    op = orig[0]["op"] if orig else None
    file_path = ""
    if op and Path(op).exists():
        inst_path = settings.papers_instances / f"{inst_id}.pdf"
        shutil.copyfile(op, inst_path)
        # Store "" rather than a path to a file that was never written — and ""
        # rather than null, because Neo4j drops null properties and the key
        # would vanish from the API response entirely.
        file_path = str(inst_path)

    now = datetime.now(timezone.utc).isoformat()
    rows = await run_write(
        """
        MATCH (p:Paper {id: $pid})
        CREATE (i:Instance {
            id: $id, version: $version, created_at: $created_at, purpose: $purpose,
            file_path: $file_path, coverage_pre: $coverage_pre, coverage_post: 0.0,
            look_into: $look_into, distraction_items: $distraction_items,
            position: $position,
            code_depth: 'L0', read_date: $read_date, time_spent: $time_spent, notes: $notes,
            understood: $understood, main_question: $main_question,
            start: $start, end: $end, mins: $mins,
            active_mins: $active_mins, passive_mins: $passive_mins, distractions: $distractions
        })
        CREATE (p)-[:HAS_INSTANCE]->(i)
        RETURN i
        """,
        pid=paper_id, id=inst_id, version=version, created_at=now,
        purpose=body.purpose, file_path=file_path, coverage_pre=body.coverage_pre,
        # New passes land at the end; reordering rewrites these (see /reorder).
        # "" not null for the text fields — Neo4j drops null properties, which
        # would change the shape of the API response.
        look_into=body.look_into or "",
        distraction_items=[d.strip() for d in (body.distraction_items or []) if d.strip()],
        position=float(version),
        read_date=body.read_date, time_spent=body.time_spent, notes=body.notes,
        understood=body.understood or "", main_question=body.main_question or "",
        start=body.start, end=body.end,
        mins=body.mins or _mins_between(body.start, body.end),
        active_mins=body.active_mins, passive_mins=body.passive_mins,
        distractions=body.distractions,
    )
    await record("instance", "created", detail=f"v{version} — {body.purpose}",
                 paper_id=paper_id, paper_title=title)
    return dict(rows[0]["i"])


@router.patch("/{instance_id}")
async def update_instance(instance_id: str, patch: InstanceUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    # keep the duration in step when the clock times move, unless one was typed
    if ("start" in fields or "end" in fields) and "mins" not in fields:
        cur = await run_read(
            "MATCH (i:Instance {id: $id}) RETURN i.start AS start, i.end AS end", id=instance_id
        )
        prev = cur[0] if cur else {}
        s = fields.get("start", prev.get("start") or "")
        e = fields.get("end", prev.get("end") or "")
        if s and e:
            fields["mins"] = _mins_between(s, e)
    sets = ", ".join(f"i.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"""
        MATCH (p:Paper)-[:HAS_INSTANCE]->(i:Instance {{id: $id}})
        SET {sets}
        RETURN i, p.id AS pid, p.title AS title
        """,
        id=instance_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "instance not found")
    if "distraction_items" in fields:
        await _push_distractions(instance_id, fields["distraction_items"],
                                 rows[0]["title"], dict(rows[0]["i"]).get("version"))
    await record("instance", "updated", detail=", ".join(fields),
                 paper_id=rows[0]["pid"], paper_title=rows[0]["title"])
    return dict(rows[0]["i"])


async def _push_distractions(instance_id: str, items: list[str],
                             paper_title: str, version) -> None:
    """Every distraction goes to Learning, on save, with no button.

    WHY AUTOMATIC. A distraction is only worth recording if the record is
    complete — the useful question is "is this happening more often or less",
    and gaps computed from the ones you happened to remember to push answer it
    wrongly. So saving the session is the log.

    WHY IT CAN'T DOUBLE UP. `distractions_logged` on the pass holds the kinds
    already sent from it. Saving a session four times while editing it must not
    read as four interruptions, and a count that inflates every time you fix a
    typo is a count nobody trusts.
    """
    rows = await run_read(
        "MATCH (i:Instance {id: $id}) "
        "RETURN coalesce(i.distractions_logged, []) AS done", id=instance_id)
    already = set(rows[0]["done"] if rows else [])

    logged = []
    for raw in items:
        text = (raw or "").strip()
        if not text:
            continue
        kind = await log_distraction_as_lesson(
            text,
            instance_id=instance_id,
            where=f"while reading v{version}" + (f" ({paper_title})" if paper_title else ""),
            skip=already)
        if kind:
            already.add(kind)
            logged.append(kind)

    if logged:
        await run_write(
            "MATCH (i:Instance {id: $id}) SET i.distractions_logged = $done",
            id=instance_id, done=sorted(already))


@router.delete("/{instance_id}", status_code=204, response_class=Response)
async def delete_instance(instance_id: str) -> Response:
    """Delete one reading pass.

    Removes the pass itself, its highlights/annotations, and its annotated PDF
    copy under papers/instances. Deliberately leaves alone:
      - the original paper and its file in the vault (:Paper.original_path)
      - the frozen auto-generated KG (:KGNode hangs off the paper, not the pass)
    """
    rows = await run_read(
        """
        MATCH (p:Paper)-[:HAS_INSTANCE]->(i:Instance {id: $id})
        OPTIONAL MATCH (i)-[:CONTAINS]->(h:Highlight)
        RETURN i.file_path AS fp, i.version AS version, p.id AS pid, p.title AS title,
               count(h) AS highlights
        """,
        id=instance_id,
    )
    if not rows:
        raise HTTPException(404, "instance not found")
    meta = rows[0]
    # only the instance's own annotated copy — never the vault original
    if meta["fp"]:
        Path(meta["fp"]).unlink(missing_ok=True)
    await run_write(
        """
        MATCH (i:Instance {id: $id})
        OPTIONAL MATCH (i)-[:CONTAINS]->(h:Highlight)
        DETACH DELETE h, i
        """,
        id=instance_id,
    )
    await record(
        "instance", "deleted",
        detail=f"v{meta['version']} — {meta['highlights']} highlights removed; original + auto-KG kept",
        paper_id=meta["pid"], paper_title=meta["title"],
    )
    return Response(status_code=204)
