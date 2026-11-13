"""/api/diary — the day in your own words, filed where it belongs.

There is ONE diary. The Mainframe tab and each module's diary tab are two
windows onto the same `:DiaryEntry` nodes, separated only by a `module`
property — which is why an entry written in Vault already appears in the day
view, and an entry routed to Vault from a mind-dump already appears in Vault.
Nothing is copied, so nothing can drift out of sync.

Two ways in, because some days work one way and some the other:

  - **section by section** — you already know where it goes, so say so. POST
    straight to /api/diary with a module.
  - **mind dump** — one blob for the whole day. POST /api/diary/split returns a
    PROPOSAL of segments and their modules and saves nothing; you correct it,
    then POST /api/diary/commit. The split never rewrites your words, only cuts
    them, so committing can't quietly replace what you wrote with a summary.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

import llm
from activity import record
from db import run_read, run_write
from models import DiaryCommit, DiaryCreate, DiarySplitRequest, DiaryUpdate

router = APIRouter(prefix="/api/diary", tags=["diary"])

MODULES = llm.DIARY_MODULES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now().date().isoformat()


def _module(m: str | None) -> str:
    """An unknown module would make an entry invisible in every view, so an
    unrecognised value lands in mainframe rather than nowhere."""
    m = (m or "").strip().lower()
    return m if m in MODULES else "mainframe"


@router.get("")
async def list_entries(date: str | None = None, module: str | None = None,
                       since: str | None = None, limit: int = 200) -> list[dict]:
    clauses, params = [], {"limit": limit}
    if date:
        clauses.append("e.date = $date")
        params["date"] = date[:10]
    if since:
        clauses.append("e.date >= $since")
        params["since"] = since[:10]
    if module:
        clauses.append("e.module = $module")
        params["module"] = _module(module)
    cypher = "MATCH (e:DiaryEntry)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    cypher += " RETURN e ORDER BY e.date DESC, e.created_at DESC LIMIT $limit"
    return [dict(r["e"]) for r in await run_read(cypher, **params)]


@router.get("/day/{day}")
async def day(day: str) -> dict:
    """One day, grouped by module — what the Mainframe diary tab renders."""
    entries = await list_entries(date=day[:10])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        grouped[_module(e.get("module"))].append(e)
    return {
        "date": day[:10],
        "count": len(entries),
        "modules": {m: grouped.get(m, []) for m in MODULES if grouped.get(m)},
        "words": sum(len((e.get("text") or "").split()) for e in entries),
    }


@router.get("/days")
async def recent_days(limit: int = 30) -> list[dict]:
    """The strip of recent days: which ones you wrote on, and where it went."""
    rows = await run_read(
        """
        MATCH (e:DiaryEntry)
        RETURN e.date AS date, count(e) AS count,
               collect(DISTINCT e.module) AS modules
        ORDER BY date DESC LIMIT $limit
        """, limit=limit)
    return [{"date": r["date"], "count": r["count"],
             "modules": [_module(m) for m in (r["modules"] or [])]} for r in rows]


async def _create(body: DiaryCreate) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "write something first")
    eid = str(uuid.uuid4())
    mod = _module(body.module)
    rows = await run_write(
        """
        CREATE (e:DiaryEntry {
            id: $id, date: $date, text: $text, title: $title, module: $module,
            section: $section, tags: $tags, source: $source,
            created_at: $now, updated_at: $now
        })
        WITH e
        MERGE (m:Module {name: $module})
        MERGE (e)-[:OWNED_BY]->(m)
        RETURN e
        """,
        id=eid, date=(body.date or _today())[:10], text=body.text.strip(),
        title=body.title.strip(), module=mod, section=(body.section or "").strip().lower(),
        tags=body.tags, source=body.source, now=_now(),
    )
    await record("diary", "entry added", detail=(body.title or body.text)[:60],
                 module=mod, entity_id=eid)
    return dict(rows[0]["e"])


@router.post("", status_code=201)
async def create_entry(body: DiaryCreate) -> dict:
    return await _create(body)


@router.put("/{eid}")
async def update_entry(eid: str, patch: DiaryUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "module" in fields:
        fields["module"] = _module(fields["module"])
    if "date" in fields:
        fields["date"] = (fields["date"] or _today())[:10]
    fields["updated_at"] = _now()
    sets = ", ".join(f"e.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (e:DiaryEntry {{id: $id}}) SET {sets} RETURN e", id=eid, **fields)
    if not rows:
        raise HTTPException(404, "entry not found")
    # Re-filing an entry has to move the ownership edge too, or the module
    # graph keeps claiming it long after the diary stopped showing it there.
    if "module" in fields:
        await run_write(
            """
            MATCH (e:DiaryEntry {id: $id})-[r:OWNED_BY]->(:Module) DELETE r
            WITH e MERGE (m:Module {name: $module}) MERGE (e)-[:OWNED_BY]->(m)
            """, id=eid, module=fields["module"])
    await record("diary", "entry updated", detail=", ".join(fields),
                 module=fields.get("module"), entity_id=eid)
    return dict(rows[0]["e"])


@router.delete("/{eid}", status_code=204, response_class=Response)
async def delete_entry(eid: str) -> Response:
    await run_write("MATCH (e:DiaryEntry {id: $id}) DETACH DELETE e", id=eid)
    await record("diary", "entry deleted", detail=eid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Mind dump → proposal → commit
# --------------------------------------------------------------------------- #
@router.post("/split")
async def split(body: DiarySplitRequest) -> dict:
    """Work out what goes where. Returns a proposal; writes nothing.

    Deliberately not a save: the routing is a guess, and a guess you can see
    and correct before it lands is the difference between a useful diary and
    one you stop trusting.
    """
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "nothing to sort")
    segments = await llm.route_diary(text, body.prompt_override)
    status = await llm.status()
    return {
        "segments": segments,
        "routed_by": "the local model" if status.get("effective") == "ollama" else "keyword rules",
        "modules": list(MODULES),
    }


@router.post("/commit", status_code=201)
async def commit(body: DiaryCommit) -> dict:
    """File a corrected proposal. One entry per segment, all on the same day."""
    if not body.segments:
        raise HTTPException(400, "nothing to file")
    saved = []
    for seg in body.segments:
        if not seg.text.strip():
            continue
        seg.date = body.date or seg.date or _today()
        seg.source = "dump"
        saved.append(await _create(seg))
    if not saved:
        raise HTTPException(400, "every segment was empty")
    return {"saved": len(saved), "entries": saved}
