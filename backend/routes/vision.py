"""/api/vision — the Vision module (content creation). VISION_SPEC.

This increment covers **Blueprint**: user-built pipeline templates. Videos and
writing pieces will later be assigned to a pipeline and take their kanban stages
from its stage list, so this is the foundation the rest of Vision hangs off.

Nothing about a stage is hardcoded — the user names every stage and defines its
inputs, outputs, tools and process. The spec is emphatic about that.

Storage note (deviation from the spec's graph sketch, deliberate): the spec
shows `inputs`/`outputs` as separate (:StageIO) nodes, but it also declares them
as ordered `[String]` lists in the Stage schema. Ordering is what the user
actually sees ("one per line"), and a pattern comprehension can't be ordered, so
inputs/outputs live as array properties on the stage. Tools DO also get real
(:Tool) nodes via MERGE, because a shared tool node is what makes "which
pipelines use Claude?" answerable across the graph later — which is the whole
reason this app is on Neo4j.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (
    ContactCreate, ContactUpdate, ContactInteractionCreate, JournalEntryCreate, PipelineCreate,
    PipelineUpdate, PortfolioCreate, PortfolioUpdate, PromptEntryCreate,
    PromptEntryUpdate, ResearchNoteCreate, ResearchNoteUpdate, ScriptMarkerCreate,
    ScriptMarkerUpdate, StageCreate, StageReorder, StageUpdate, StoryPanelCreate,
    StoryPanelUpdate, PanelReorder, ThumbnailOptionCreate, ThumbnailOptionUpdate, ThumbFeedbackCreate,
    VideoCreate, VideoUpdate, WritingCreate, WritingUpdate,
)

router = APIRouter(prefix="/api/vision", tags=["vision"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(var: str) -> str:
    """Cypher snippet attaching a node to the Vision module."""
    return f"MERGE (mod:Module {{name: 'vision'}}) MERGE ({var})-[:OWNED_BY]->(mod)"


async def _prune_tools() -> None:
    """Drop (:Tool) nodes no stage points at any more.

    Tools are MERGEd, so they're shared and outlive the stage that created them
    — without this, deleting a pipeline leaves a graveyard of 0-use tools that
    pollute /tools and any future "what am I using X for?" query.
    """
    await run_write("MATCH (t:Tool) WHERE NOT (t)<-[:USES_TOOL]-() DETACH DELETE t")


# =========================================================================== #
# BLUEPRINT — pipelines + stages
# =========================================================================== #
_PIPELINE_Q = """
MATCH (p:Pipeline {id: $id})
OPTIONAL MATCH (p)-[r:HAS_STAGE]->(s:PipelineStage)
WITH p, r, s ORDER BY r.order
WITH p, collect(CASE WHEN s IS NULL THEN NULL ELSE {
    id: s.id, name: s.name, process: coalesce(s.process, ''),
    inputs: coalesce(s.inputs, []), outputs: coalesce(s.outputs, []),
    tools: coalesce(s.tools, []), order: r.order
} END) AS raw
RETURN p{.*} AS pipeline, [x IN raw WHERE x IS NOT NULL] AS stages
"""


async def _pipeline(pid: str) -> dict:
    rows = await run_read(_PIPELINE_Q, id=pid)
    if not rows:
        raise HTTPException(404, "pipeline not found")
    p = dict(rows[0]["pipeline"])
    p["stages"] = [dict(s) for s in rows[0]["stages"]]
    return p


@router.get("/pipelines")
async def list_pipelines() -> list[dict]:
    rows = await run_read("MATCH (p:Pipeline) RETURN p.id AS id ORDER BY p.created_at DESC")
    return [await _pipeline(r["id"]) for r in rows]


@router.post("/pipelines", status_code=201)
async def create_pipeline(body: PipelineCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a pipeline needs a name")
    pid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (p:Pipeline {{id: $id, name: $name, description: $desc, created_at: $now}})
        WITH p {_own('p')}
        """,
        id=pid, name=body.name.strip(), desc=body.description, now=_now(),
    )
    await record("pipeline", "created", detail=body.name[:70], module="vision", entity_id=pid)
    return await _pipeline(pid)


@router.put("/pipelines/{pid}")
async def update_pipeline(pid: str, patch: PipelineUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"p.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (p:Pipeline {{id: $id}}) SET {sets} RETURN p", id=pid, **fields)
    if not rows:
        raise HTTPException(404, "pipeline not found")
    await record("pipeline", "updated", detail=", ".join(fields), module="vision", entity_id=pid)
    return await _pipeline(pid)


@router.delete("/pipelines/{pid}", status_code=204, response_class=Response)
async def delete_pipeline(pid: str) -> Response:
    await run_write(
        """
        MATCH (p:Pipeline {id: $id})
        OPTIONAL MATCH (p)-[:HAS_STAGE]->(s:PipelineStage)
        DETACH DELETE s, p
        """,
        id=pid,
    )
    await _prune_tools()
    await record("pipeline", "deleted", detail=pid, module="vision")
    return Response(status_code=204)


@router.post("/pipelines/{pid}/stages", status_code=201)
async def add_stage(pid: str, body: StageCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a stage needs a name")
    exists = await run_read("MATCH (p:Pipeline {id: $id}) RETURN p.id AS id", id=pid)
    if not exists:
        raise HTTPException(404, "pipeline not found")
    sid = str(uuid.uuid4())
    tools = [t.strip() for t in body.tools if t.strip()]
    await run_write(
        f"""
        MATCH (p:Pipeline {{id: $pid}})
        OPTIONAL MATCH (p)-[r:HAS_STAGE]->()
        WITH p, coalesce(max(r.order), -1) + 1 AS nextOrder
        CREATE (s:PipelineStage {{
            id: $sid, name: $name, process: $process,
            inputs: $inputs, outputs: $outputs, tools: $tools, created_at: $now
        }})
        CREATE (p)-[:HAS_STAGE {{order: nextOrder}}]->(s)
        WITH s {_own('s')}
        WITH s UNWIND CASE WHEN size($tools) = 0 THEN [null] ELSE $tools END AS tname
          FOREACH (_ IN CASE WHEN tname IS NULL THEN [] ELSE [1] END |
            MERGE (t:Tool {{name: tname}})
            MERGE (s)-[:USES_TOOL]->(t))
        """,
        pid=pid, sid=sid, name=body.name.strip(), process=body.process,
        inputs=[i.strip() for i in body.inputs if i.strip()],
        outputs=[o.strip() for o in body.outputs if o.strip()],
        tools=tools, now=_now(),
    )
    await record("pipeline", "stage added", detail=body.name[:70], module="vision", entity_id=pid)
    # the new stage's id, so a form can hang its held rows (inputs, tools…) off it
    return {**(await _pipeline(pid)), "stage_id": sid}


@router.put("/pipelines/{pid}/stages/{sid}")
async def update_stage(pid: str, sid: str, patch: StageUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    for key in ("inputs", "outputs", "tools"):
        if key in fields:
            fields[key] = [v.strip() for v in (fields[key] or []) if v.strip()]
    sets = ", ".join(f"s.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Pipeline {{id: $pid}})-[:HAS_STAGE]->(s:PipelineStage {{id: $sid}}) "
        f"SET {sets} RETURN s",
        pid=pid, sid=sid, **fields,
    )
    if not rows:
        raise HTTPException(404, "stage not found")
    if "tools" in fields:
        # re-point the shared (:Tool) nodes to match the new list
        await run_write(
            """
            MATCH (s:PipelineStage {id: $sid})
            OPTIONAL MATCH (s)-[r:USES_TOOL]->(:Tool)
            DELETE r
            WITH s UNWIND CASE WHEN size($tools) = 0 THEN [null] ELSE $tools END AS tname
              FOREACH (_ IN CASE WHEN tname IS NULL THEN [] ELSE [1] END |
                MERGE (t:Tool {name: tname})
                MERGE (s)-[:USES_TOOL]->(t))
            """,
            sid=sid, tools=fields["tools"],
        )
        await _prune_tools()
    await record("pipeline", "stage updated", detail=", ".join(fields), module="vision", entity_id=pid)
    return await _pipeline(pid)


@router.delete("/pipelines/{pid}/stages/{sid}", status_code=204, response_class=Response)
async def delete_stage(pid: str, sid: str) -> Response:
    await run_write(
        """
        MATCH (p:Pipeline {id: $pid})-[:HAS_STAGE]->(s:PipelineStage {id: $sid})
        DETACH DELETE s
        WITH p
        OPTIONAL MATCH (p)-[r:HAS_STAGE]->(rest:PipelineStage)
        WITH p, r, rest ORDER BY r.order
        WITH p, collect(r) AS rels
        UNWIND range(0, size(rels) - 1) AS i
        WITH rels[i] AS rel, i
        SET rel.order = i
        """,
        pid=pid, sid=sid,
    )
    await _prune_tools()
    await record("pipeline", "stage deleted", detail=sid, module="vision", entity_id=pid)
    return Response(status_code=204)


@router.put("/pipelines/{pid}/reorder")
async def reorder_stages(pid: str, body: StageReorder) -> dict:
    """Assign order from the given list — index 0 is the first stage."""
    if not body.stage_ids:
        raise HTTPException(400, "no stage ids given")
    if len(set(body.stage_ids)) != len(body.stage_ids):
        raise HTTPException(400, "duplicate stage ids")
    rows = await run_read(
        "MATCH (:Pipeline {id: $pid})-[:HAS_STAGE]->(s:PipelineStage) "
        "WHERE s.id IN $ids RETURN count(s) AS n",
        pid=pid, ids=body.stage_ids,
    )
    if rows[0]["n"] != len(body.stage_ids):
        raise HTTPException(404, "one or more stages not in this pipeline")
    await run_write(
        """
        UNWIND range(0, size($ids) - 1) AS i
        MATCH (:Pipeline {id: $pid})-[r:HAS_STAGE]->(s:PipelineStage {id: $ids[i]})
        SET r.order = i
        """,
        pid=pid, ids=body.stage_ids,
    )
    await record("pipeline", "stages reordered", detail=f"{len(body.stage_ids)} stages",
                 module="vision", entity_id=pid)
    return await _pipeline(pid)


# =========================================================================== #
# YOUTUBE — a video is a production workspace (VISION_UPDATE_SPEC)
# =========================================================================== #
_VIDEO_Q = """
MATCH (v:Video {id: $id})
OPTIONAL MATCH (v)-[:FOLLOWS_PIPELINE]->(pl:Pipeline)
OPTIONAL MATCH (pl)-[sr:HAS_STAGE]->(ps:PipelineStage)
WITH v, pl, ps, sr ORDER BY sr.order
WITH v, pl, [x IN collect(CASE WHEN ps IS NULL THEN NULL
     ELSE {id: ps.id, name: ps.name, order: sr.order} END) WHERE x IS NOT NULL] AS pstages
OPTIONAL MATCH (v)-[:HAS_ENTRY]->(e:JournalEntry)
WITH v, pl, pstages, e ORDER BY e.date DESC
WITH v, pl, pstages, [x IN collect(CASE WHEN e IS NULL THEN NULL ELSE e{.*} END)
                      WHERE x IS NOT NULL] AS entries
OPTIONAL MATCH (v)-[:HAS_RESEARCH]->(rn:ResearchNote)
WITH v, pl, pstages, entries, rn ORDER BY rn.date DESC
WITH v, pl, pstages, entries,
     [x IN collect(CASE WHEN rn IS NULL THEN NULL ELSE rn{.*} END) WHERE x IS NOT NULL] AS research
OPTIONAL MATCH (v)-[:HAS_PROMPT]->(pe:PromptEntry)
WITH v, pl, pstages, entries, research, pe ORDER BY pe.date DESC
WITH v, pl, pstages, entries, research,
     [x IN collect(CASE WHEN pe IS NULL THEN NULL ELSE pe{.*} END) WHERE x IS NOT NULL] AS prompts
OPTIONAL MATCH (v)-[:HAS_MARKER]->(mk:ScriptMarker)
WITH v, pl, pstages, entries, research, prompts, mk ORDER BY mk.line_start, mk.line_end
WITH v, pl, pstages, entries, research, prompts,
     [x IN collect(CASE WHEN mk IS NULL THEN NULL ELSE mk{.*} END) WHERE x IS NOT NULL] AS markers
OPTIONAL MATCH (v)-[pr:HAS_PANEL]->(sp:StoryPanel)
WITH v, pl, pstages, entries, research, prompts, markers, sp, pr ORDER BY pr.order
WITH v, pl, pstages, entries, research, prompts, markers,
     [x IN collect(CASE WHEN sp IS NULL THEN NULL
        ELSE sp{.*, order: pr.order} END) WHERE x IS NOT NULL] AS panels
OPTIONAL MATCH (v)-[:HAS_THUMB_OPTION]->(th:ThumbnailOption)
WITH v, pl, pstages, entries, research, prompts, markers, panels, th ORDER BY th.created_at
WITH v, pl, pstages, entries, research, prompts, markers, panels,
     [x IN collect(CASE WHEN th IS NULL THEN NULL ELSE th{.*,
        feedback: [(th)-[:HAS_FEEDBACK]->(f:ThumbFeedback) | f{.*}]} END) WHERE x IS NOT NULL] AS thumbs
RETURN v{.*} AS video,
       CASE WHEN pl IS NULL THEN NULL ELSE {id: pl.id, name: pl.name} END AS pipeline,
       pstages, entries, research, prompts, markers, panels, thumbs,
       [(v)-[m:MENTIONS]->(t) | {id: t.id, kind: m.kind, label: coalesce(t.title, t.name, '')}] AS mentions,
       [(o:Video)-[:MENTIONS]->(v) | {id: o.id, title: o.title, thumbnail: o.thumbnail}] AS mentioned_by
"""


async def _video(vid: str) -> dict:
    rows = await run_read(_VIDEO_Q, id=vid)
    if not rows:
        raise HTTPException(404, "video not found")
    r = rows[0]
    v = dict(r["video"])
    v["pipeline"] = dict(r["pipeline"]) if r["pipeline"] else None
    v["pipeline_stages"] = [dict(s) for s in r["pstages"]]
    v["entries"] = [dict(e) for e in r["entries"]]
    v["research"] = [dict(x) for x in r["research"]]
    v["prompts"] = [dict(x) for x in r["prompts"]]
    v["markers"] = [dict(x) for x in r["markers"]]
    v["panels"] = [dict(x) for x in r["panels"]]
    v["thumbs"] = [dict(x) for x in r["thumbs"]]
    for t in v["thumbs"]:
        t["feedback"] = sorted((dict(f) for f in t.get("feedback") or []),
                               key=lambda f: f.get("date") or "", reverse=True)
    v["mentions"] = [dict(x) for x in r["mentions"]]
    v["mentioned_by"] = [dict(x) for x in r["mentioned_by"] if x["id"] != vid]
    return v


# ---------------------------------------------------------------------------
# @-mentions in a video's notes — `@[Label](kind:id)` tokens in the text are
# mirrored into (:Video)-[:MENTIONS {kind}]->(target) edges on every notes save,
# so the links survive renames (they key on id) and backlinks are one hop.
# ---------------------------------------------------------------------------
MENTION_KINDS = {"video": "Video", "concept": "Concept", "idea": "Idea", "doc": "Document"}
_MENTION_RE = re.compile(r"@\[[^\]\n]*\]\((video|concept|idea|doc):([\w-]+)\)")


async def _sync_mentions(vid: str, notes: str) -> None:
    await run_write("MATCH (:Video {id: $id})-[m:MENTIONS]->() DELETE m", id=vid)
    seen = set()
    for kind, tid in _MENTION_RE.findall(notes or ""):
        if (kind, tid) in seen or (kind == "video" and tid == vid):
            continue
        seen.add((kind, tid))
        # label comes from the whitelist above, never from the request
        await run_write(
            f"MATCH (v:Video {{id: $id}}), (t:{MENTION_KINDS[kind]} {{id: $tid}}) "
            "MERGE (v)-[m:MENTIONS]->(t) SET m.kind = $kind",
            id=vid, tid=tid, kind=kind,
        )


@router.get("/mentionables")
async def mentionables(q: str = "", limit: int = 12) -> list[dict]:
    """What a note can @-mention: other videos, Synapse concepts (dictionary
    terms), ideas and docs — matched on title/name, case-insensitive."""
    rows = await run_read(
        """
        CALL {
          MATCH (n:Video) RETURN n.id AS id, 'video' AS kind, n.title AS label
          UNION ALL
          MATCH (n:Concept) RETURN n.id AS id, 'concept' AS kind, n.name AS label
          UNION ALL
          MATCH (n:Idea) RETURN n.id AS id, 'idea' AS kind, n.title AS label
          UNION ALL
          MATCH (n:Document) RETURN n.id AS id, 'doc' AS kind, n.title AS label
        }
        WITH id, kind, label WHERE label IS NOT NULL AND label <> ''
          AND toLower(label) CONTAINS toLower($q)
        RETURN id, kind, label
        ORDER BY CASE WHEN toLower(label) STARTS WITH toLower($q) THEN 0 ELSE 1 END,
                 CASE kind WHEN 'video' THEN 0 WHEN 'concept' THEN 1 WHEN 'doc' THEN 2 ELSE 3 END,
                 size(label)
        LIMIT $limit
        """,
        q=q.strip(), limit=max(1, min(limit, 50)),
    )
    return [dict(r) for r in rows]


@router.get("/videos")
async def list_videos(type: str | None = None, stage: str | None = None) -> list[dict]:
    clauses, params = [], {}
    if type:
        clauses.append("v.type = $type")
        params["type"] = type
    if stage:
        clauses.append("v.stage = $stage")
        params["stage"] = stage
    cypher = "MATCH (v:Video)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    cypher += " RETURN v.id AS id ORDER BY v.created_at DESC"
    rows = await run_read(cypher, **params)
    return [await _video(r["id"]) for r in rows]


@router.get("/videos/{vid}")
async def get_video(vid: str) -> dict:
    return await _video(vid)


@router.post("/videos", status_code=201)
async def create_video(body: VideoCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "a video needs a title")
    vid = str(uuid.uuid4())
    stage = body.stage
    # No stage given but a pipeline was chosen → start at its first stage.
    if body.pipeline_id and not stage:
        first = await run_read(
            "MATCH (:Pipeline {id: $pid})-[r:HAS_STAGE]->(s:PipelineStage) "
            "RETURN s.name AS name ORDER BY r.order LIMIT 1",
            pid=body.pipeline_id,
        )
        stage = first[0]["name"] if first else ""
    await run_write(
        f"""
        CREATE (v:Video {{
            id: $id, title: $title, type: $type, stage: $stage,
            pipeline_id: $pipeline_id, target_date: $target_date, thumbnail: '',
            description: $description, script: '', framework: $framework,
            llms_used: $llms_used, tags: $tags, notes: $notes, created_at: $now
        }})
        WITH v {_own('v')}
        WITH v
        OPTIONAL MATCH (pl:Pipeline {{id: $pipeline_id}})
        FOREACH (_ IN CASE WHEN pl IS NULL THEN [] ELSE [1] END |
            MERGE (v)-[:FOLLOWS_PIPELINE]->(pl))
        """,
        id=vid, title=body.title.strip(), type=body.type, stage=stage,
        pipeline_id=(body.pipeline_id or ""), target_date=(body.target_date or ""),
        description=body.description, framework=body.framework,
        llms_used=body.llms_used, tags=body.tags, notes=body.notes, now=_now(),
    )
    await record("video", "created", detail=body.title[:70], module="vision", entity_id=vid)
    return await _video(vid)


@router.put("/videos/{vid}")
async def update_video(vid: str, patch: VideoUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"v.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (v:Video {{id: $id}}) SET {sets} RETURN v", id=vid, **fields)
    if not rows:
        raise HTTPException(404, "video not found")
    if "pipeline_id" in fields:
        # re-point FOLLOWS_PIPELINE, and reset the stage into the new pipeline
        await run_write(
            """
            MATCH (v:Video {id: $id})
            OPTIONAL MATCH (v)-[r:FOLLOWS_PIPELINE]->(:Pipeline)
            DELETE r
            WITH v
            OPTIONAL MATCH (pl:Pipeline {id: $pid})
            FOREACH (_ IN CASE WHEN pl IS NULL THEN [] ELSE [1] END |
                MERGE (v)-[:FOLLOWS_PIPELINE]->(pl))
            """,
            id=vid, pid=fields["pipeline_id"],
        )
        if "stage" not in fields:
            first = await run_read(
                "MATCH (:Pipeline {id: $pid})-[r:HAS_STAGE]->(s:PipelineStage) "
                "RETURN s.name AS name ORDER BY r.order LIMIT 1",
                pid=fields["pipeline_id"],
            )
            await run_write("MATCH (v:Video {id: $id}) SET v.stage = $stage",
                            id=vid, stage=first[0]["name"] if first else "")
    if "notes" in fields:
        await _sync_mentions(vid, fields["notes"] or "")
    await record("video", "updated", detail=", ".join(fields), module="vision", entity_id=vid)
    return await _video(vid)


@router.post("/videos/{vid}/advance")
async def advance_stage(vid: str) -> dict:
    """Move to the next stage of the video's pipeline. Stages come from the
    Blueprint pipeline — never a hardcoded list (spec)."""
    v = await _video(vid)
    stages = [s["name"] for s in v["pipeline_stages"]]
    if not stages:
        raise HTTPException(400, "this video isn't linked to a pipeline with stages")
    try:
        nxt = stages.index(v.get("stage") or "") + 1
    except ValueError:
        nxt = 0                     # current stage isn't in the list → start at the top
    if nxt >= len(stages):
        raise HTTPException(400, "already at the final stage")
    await run_write("MATCH (v:Video {id: $id}) SET v.stage = $stage", id=vid, stage=stages[nxt])
    await record("video", "stage advanced", detail=f"{v['title'][:40]} → {stages[nxt]}",
                 module="vision", entity_id=vid)
    return await _video(vid)


@router.delete("/videos/{vid}", status_code=204, response_class=Response)
async def delete_video(vid: str) -> Response:
    # child nodes go with it; video FILES are never stored (spec is explicit)
    await run_write(
        """
        MATCH (v:Video {id: $id})
        OPTIONAL MATCH (v)-[:HAS_ENTRY]->(e:JournalEntry)
        OPTIONAL MATCH (v)-[:HAS_RESEARCH]->(rn:ResearchNote)
        OPTIONAL MATCH (v)-[:HAS_MARKER]->(mk:ScriptMarker)
        OPTIONAL MATCH (v)-[:HAS_PROMPT]->(pe:PromptEntry)
        OPTIONAL MATCH (v)-[:HAS_PANEL]->(sp:StoryPanel)
        OPTIONAL MATCH (v)-[:HAS_THUMB_OPTION]->(th:ThumbnailOption)
        OPTIONAL MATCH (th)-[:HAS_FEEDBACK]->(tf:ThumbFeedback)
        DETACH DELETE e, rn, mk, pe, sp, tf, th, v
        """,
        id=vid,
    )
    await record("video", "deleted", detail=vid, module="vision")
    return Response(status_code=204)


@router.post("/videos/{vid}/entries", status_code=201)
async def add_entry(vid: str, body: JournalEntryCreate) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "an entry needs some text")
    rows = await run_write(
        """
        MATCH (v:Video {id: $vid})
        CREATE (e:JournalEntry {id: $eid, text: $text, date: $date})
        CREATE (v)-[:HAS_ENTRY]->(e)
        RETURN e
        """,
        vid=vid, eid=str(uuid.uuid4()), text=body.text.strip(), date=body.date or _now(),
    )
    if not rows:
        raise HTTPException(404, "video not found")
    await record("video", "journal entry", detail=body.text[:70], module="vision", entity_id=vid)
    return await _video(vid)


@router.delete("/videos/{vid}/entries/{eid}", status_code=204, response_class=Response)
async def delete_entry(vid: str, eid: str) -> Response:
    await run_write(
        "MATCH (:Video {id: $vid})-[:HAS_ENTRY]->(e:JournalEntry {id: $eid}) DETACH DELETE e",
        vid=vid, eid=eid,
    )
    await record("video", "entry deleted", detail=eid, module="vision", entity_id=vid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Research notes
# --------------------------------------------------------------------------- #
@router.post("/videos/{vid}/research", status_code=201)
async def add_research(vid: str, body: ResearchNoteCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "a source needs a title")
    rows = await run_write(
        """
        MATCH (v:Video {id: $vid})
        CREATE (r:ResearchNote {id: $rid, title: $title, url: $url,
                                summary: $summary, date: $now})
        CREATE (v)-[:HAS_RESEARCH]->(r)
        RETURN r
        """,
        # empty string, not null — Neo4j drops null props entirely, which would
        # make the API return a different shape for notes without a url
        vid=vid, rid=str(uuid.uuid4()), title=body.title.strip(),
        url=(body.url or ""), summary=body.summary, now=_now(),
    )
    if not rows:
        raise HTTPException(404, "video not found")
    await record("video", "research added", detail=body.title[:70], module="vision", entity_id=vid)
    return await _video(vid)


@router.put("/videos/{vid}/research/{rid}")
async def update_research(vid: str, rid: str, patch: ResearchNoteUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"r.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Video {{id: $vid}})-[:HAS_RESEARCH]->(r:ResearchNote {{id: $rid}}) "
        f"SET {sets} RETURN r",
        vid=vid, rid=rid, **fields,
    )
    if not rows:
        raise HTTPException(404, "research note not found")
    await record("video", "research updated", detail=", ".join(fields), module="vision", entity_id=vid)
    return await _video(vid)


@router.delete("/videos/{vid}/research/{rid}", status_code=204, response_class=Response)
async def delete_research(vid: str, rid: str) -> Response:
    await run_write(
        "MATCH (:Video {id: $vid})-[:HAS_RESEARCH]->(r:ResearchNote {id: $rid}) DETACH DELETE r",
        vid=vid, rid=rid,
    )
    await record("video", "research deleted", detail=rid, module="vision", entity_id=vid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Script markers — annotate line ranges of the script
# --------------------------------------------------------------------------- #
@router.post("/videos/{vid}/markers", status_code=201)
async def add_marker(vid: str, body: ScriptMarkerCreate) -> dict:
    start, end = sorted((body.line_start, body.line_end))   # tolerate either order
    rows = await run_write(
        """
        MATCH (v:Video {id: $vid})
        CREATE (m:ScriptMarker {id: $mid, line_start: $s, line_end: $e,
                                label: $label, note: $note})
        CREATE (v)-[:HAS_MARKER]->(m)
        RETURN m
        """,
        vid=vid, mid=str(uuid.uuid4()), s=start, e=end, label=body.label, note=body.note,
    )
    if not rows:
        raise HTTPException(404, "video not found")
    await record("video", "marker added", detail=f"{body.label} L{start}-{end}",
                 module="vision", entity_id=vid)
    return await _video(vid)


@router.put("/videos/{vid}/markers/{mid}")
async def update_marker(vid: str, mid: str, patch: ScriptMarkerUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "line_start" in fields and "line_end" in fields:
        fields["line_start"], fields["line_end"] = sorted((fields["line_start"], fields["line_end"]))
    sets = ", ".join(f"m.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Video {{id: $vid}})-[:HAS_MARKER]->(m:ScriptMarker {{id: $mid}}) "
        f"SET {sets} RETURN m",
        vid=vid, mid=mid, **fields,
    )
    if not rows:
        raise HTTPException(404, "marker not found")
    await record("video", "marker updated", detail=", ".join(fields), module="vision", entity_id=vid)
    return await _video(vid)


@router.delete("/videos/{vid}/markers/{mid}", status_code=204, response_class=Response)
async def delete_marker(vid: str, mid: str) -> Response:
    await run_write(
        "MATCH (:Video {id: $vid})-[:HAS_MARKER]->(m:ScriptMarker {id: $mid}) DETACH DELETE m",
        vid=vid, mid=mid,
    )
    await record("video", "marker deleted", detail=mid, module="vision", entity_id=vid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Prompt log — MANUAL. Nothing here calls a model API (spec).
# --------------------------------------------------------------------------- #
@router.post("/videos/{vid}/prompts", status_code=201)
async def add_prompt(vid: str, body: PromptEntryCreate) -> dict:
    props = body.model_dump(exclude_none=True)
    if not str(props.get("llm", "")).strip():
        raise HTTPException(400, "say which LLM this was")
    if not str(props.get("prompt", "")).strip():
        raise HTTPException(400, "a prompt entry needs the prompt")
    props["id"] = str(uuid.uuid4())
    props["date"] = _now()
    rows = await run_write(
        """
        MATCH (v:Video {id: $vid})
        CREATE (p:PromptEntry $props)
        CREATE (v)-[:HAS_PROMPT]->(p)
        RETURN p
        """,
        vid=vid, props=props,
    )
    if not rows:
        raise HTTPException(404, "video not found")
    await record("video", "prompt logged", detail=f"{props['llm'][:30]} · {props.get('status', 'draft')}",
                 module="vision", entity_id=vid)
    return await _video(vid)


@router.put("/videos/{vid}/prompts/{pid}")
async def update_prompt(vid: str, pid: str, patch: PromptEntryUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"p.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Video {{id: $vid}})-[:HAS_PROMPT]->(p:PromptEntry {{id: $pid}}) "
        f"SET {sets} RETURN p",
        vid=vid, pid=pid, **fields,
    )
    if not rows:
        raise HTTPException(404, "prompt entry not found")
    await record("video", "prompt updated", detail=", ".join(fields), module="vision", entity_id=vid)
    return await _video(vid)


@router.post("/videos/{vid}/prompts/{pid}/use-as-script")
async def use_prompt_as_script(vid: str, pid: str) -> dict:
    """Push an approved response into the video's script — the spec's 'the
    approved entry feeds into the script field', done explicitly so nothing
    silently overwrites work."""
    rows = await run_read(
        "MATCH (:Video {id: $vid})-[:HAS_PROMPT]->(p:PromptEntry {id: $pid}) "
        "RETURN p.response AS response",
        vid=vid, pid=pid,
    )
    if not rows:
        raise HTTPException(404, "prompt entry not found")
    if not (rows[0]["response"] or "").strip():
        raise HTTPException(400, "that entry has no response to use")
    await run_write("MATCH (v:Video {id: $vid}) SET v.script = $s", vid=vid, s=rows[0]["response"])
    await record("video", "script from prompt", detail=pid, module="vision", entity_id=vid)
    return await _video(vid)


@router.delete("/videos/{vid}/prompts/{pid}", status_code=204, response_class=Response)
async def delete_prompt(vid: str, pid: str) -> Response:
    await run_write(
        "MATCH (:Video {id: $vid})-[:HAS_PROMPT]->(p:PromptEntry {id: $pid}) DETACH DELETE p",
        vid=vid, pid=pid,
    )
    await record("video", "prompt deleted", detail=pid, module="vision", entity_id=vid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Storyboard — comic panel grid. Panels are the PLAN (image + caption +
# duration), never video files (spec is explicit).
# --------------------------------------------------------------------------- #
@router.post("/videos/{vid}/storyboard", status_code=201)
async def add_panel(vid: str, body: StoryPanelCreate) -> dict:
    rows = await run_write(
        """
        MATCH (v:Video {id: $vid})
        OPTIONAL MATCH (v)-[r:HAS_PANEL]->()
        WITH v, coalesce(max(r.order), -1) + 1 AS nextOrder
        CREATE (p:StoryPanel {id: $pid, caption: $caption, dialog: $dialog,
                              duration: $duration, notes: $notes, image: $image})
        CREATE (v)-[:HAS_PANEL {order: nextOrder}]->(p)
        RETURN p
        """,
        vid=vid, pid=str(uuid.uuid4()), caption=body.caption, dialog=body.dialog,
        duration=body.duration, notes=body.notes, image=body.image,
    )
    if not rows:
        raise HTTPException(404, "video not found")
    await record("video", "panel added", detail=body.caption[:60], module="vision", entity_id=vid)
    return await _video(vid)


# NB declared BEFORE /storyboard/{sid} — FastAPI matches in declaration order,
# so the literal path must win over the parameterised one.
@router.put("/videos/{vid}/storyboard/reorder")
async def reorder_panels(vid: str, body: PanelReorder) -> dict:
    if not body.panel_ids:
        raise HTTPException(400, "no panel ids given")
    if len(set(body.panel_ids)) != len(body.panel_ids):
        raise HTTPException(400, "duplicate panel ids")
    rows = await run_read(
        "MATCH (:Video {id: $vid})-[:HAS_PANEL]->(p:StoryPanel) "
        "WHERE p.id IN $ids RETURN count(p) AS n",
        vid=vid, ids=body.panel_ids,
    )
    if rows[0]["n"] != len(body.panel_ids):
        raise HTTPException(404, "one or more panels not in this video")
    await run_write(
        """
        UNWIND range(0, size($ids) - 1) AS i
        MATCH (:Video {id: $vid})-[r:HAS_PANEL]->(p:StoryPanel {id: $ids[i]})
        SET r.order = i
        """,
        vid=vid, ids=body.panel_ids,
    )
    await record("video", "storyboard reordered", detail=f"{len(body.panel_ids)} panels",
                 module="vision", entity_id=vid)
    return await _video(vid)


@router.put("/videos/{vid}/storyboard/{sid}")
async def update_panel(vid: str, sid: str, patch: StoryPanelUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"p.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Video {{id: $vid}})-[:HAS_PANEL]->(p:StoryPanel {{id: $sid}}) "
        f"SET {sets} RETURN p",
        vid=vid, sid=sid, **fields,
    )
    if not rows:
        raise HTTPException(404, "panel not found")
    await record("video", "panel updated", detail=", ".join(fields), module="vision", entity_id=vid)
    return await _video(vid)


@router.delete("/videos/{vid}/storyboard/{sid}", status_code=204, response_class=Response)
async def delete_panel(vid: str, sid: str) -> Response:
    await run_write(
        """
        MATCH (:Video {id: $vid})-[:HAS_PANEL]->(p:StoryPanel {id: $sid})
        DETACH DELETE p
        WITH 1 AS _
        MATCH (:Video {id: $vid})-[r:HAS_PANEL]->(rest:StoryPanel)
        WITH r ORDER BY r.order
        WITH collect(r) AS rels
        UNWIND range(0, size(rels) - 1) AS i
        WITH rels[i] AS rel, i
        SET rel.order = i
        """,
        vid=vid, sid=sid,
    )
    await record("video", "panel deleted", detail=sid, module="vision", entity_id=vid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Thumbnail comparison board — several options, exactly one chosen
# --------------------------------------------------------------------------- #
@router.post("/videos/{vid}/thumbnails", status_code=201)
async def add_thumb(vid: str, body: ThumbnailOptionCreate) -> dict:
    rows = await run_write(
        """
        MATCH (v:Video {id: $vid})
        CREATE (t:ThumbnailOption {id: $tid, image: $image, style: $style,
                                   notes: $notes, chosen: false, created_at: $now})
        CREATE (v)-[:HAS_THUMB_OPTION]->(t)
        RETURN t
        """,
        vid=vid, tid=str(uuid.uuid4()), image=body.image, style=body.style,
        notes=body.notes, now=_now(),
    )
    if not rows:
        raise HTTPException(404, "video not found")
    await record("video", "thumbnail option added", detail=body.style[:60],
                 module="vision", entity_id=vid)
    return await _video(vid)


@router.put("/videos/{vid}/thumbnails/{tid}")
async def update_thumb(vid: str, tid: str, patch: ThumbnailOptionUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"t.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Video {{id: $vid}})-[:HAS_THUMB_OPTION]->(t:ThumbnailOption {{id: $tid}}) "
        f"SET {sets} RETURN t",
        vid=vid, tid=tid, **fields,
    )
    if not rows:
        raise HTTPException(404, "thumbnail option not found")
    if fields.get("chosen"):
        # exactly one chosen, and it becomes the video's thumbnail (spec)
        await run_write(
            """
            MATCH (v:Video {id: $vid})-[:HAS_THUMB_OPTION]->(other:ThumbnailOption)
            WHERE other.id <> $tid
            SET other.chosen = false
            """,
            vid=vid, tid=tid,
        )
        img = dict(rows[0]["t"]).get("image", "")
        await run_write("MATCH (v:Video {id: $vid}) SET v.thumbnail = $img", vid=vid, img=img)
    return await _video(vid)


@router.delete("/videos/{vid}/thumbnails/{tid}", status_code=204, response_class=Response)
async def delete_thumb(vid: str, tid: str) -> Response:
    rows = await run_read(
        "MATCH (:Video {id: $vid})-[:HAS_THUMB_OPTION]->(t:ThumbnailOption {id: $tid}) "
        "RETURN t.chosen AS chosen",
        vid=vid, tid=tid,
    )
    await run_write(
        "MATCH (:Video {id: $vid})-[:HAS_THUMB_OPTION]->(t:ThumbnailOption {id: $tid}) "
        "OPTIONAL MATCH (t)-[:HAS_FEEDBACK]->(f:ThumbFeedback) "
        "DETACH DELETE f, t",
        vid=vid, tid=tid,
    )
    # deleting the chosen option must clear the video's thumbnail, or the card
    # keeps showing an image whose option no longer exists
    if rows and rows[0]["chosen"]:
        await run_write("MATCH (v:Video {id: $vid}) SET v.thumbnail = ''", vid=vid)
    await record("video", "thumbnail option deleted", detail=tid, module="vision", entity_id=vid)
    return Response(status_code=204)


# Feedback on one thumbnail option — a dated thread, newest first, so an
# option's critique accumulates as it's revised instead of being overwritten.
@router.post("/videos/{vid}/thumbnails/{tid}/feedback", status_code=201)
async def add_thumb_feedback(vid: str, tid: str, body: ThumbFeedbackCreate) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "feedback can't be empty")
    fid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (:Video {id: $vid})-[:HAS_THUMB_OPTION]->(t:ThumbnailOption {id: $tid})
        CREATE (t)-[:HAS_FEEDBACK]->(f:ThumbFeedback {id: $fid, text: $text,
                                                      verdict: $verdict, date: $now})
        RETURN f{.*} AS f
        """,
        vid=vid, tid=tid, fid=fid, text=body.text.strip(), verdict=body.verdict, now=_now(),
    )
    if not rows:
        raise HTTPException(404, "thumbnail option not found")
    await record("video", "thumbnail feedback", detail=body.text[:60], module="vision", entity_id=vid)
    return dict(rows[0]["f"])


@router.delete("/videos/{vid}/thumbnails/{tid}/feedback/{fid}", status_code=204, response_class=Response)
async def delete_thumb_feedback(vid: str, tid: str, fid: str) -> Response:
    await run_write(
        "MATCH (:Video {id: $vid})-[:HAS_THUMB_OPTION]->(:ThumbnailOption {id: $tid})"
        "-[:HAS_FEEDBACK]->(f:ThumbFeedback {id: $fid}) DETACH DELETE f",
        vid=vid, tid=tid, fid=fid,
    )
    return Response(status_code=204)


# =========================================================================== #
# WRITING — blog / article / thread, tracked through a pipeline
# =========================================================================== #
_WRITING_Q = """
MATCH (w:WritingPiece {id: $id})
OPTIONAL MATCH (w)-[:IN_PIPELINE]->(pl:Pipeline)
OPTIONAL MATCH (pl)-[sr:HAS_STAGE]->(ps:PipelineStage)
WITH w, pl, ps, sr ORDER BY sr.order
RETURN w{.*} AS piece,
       CASE WHEN pl IS NULL THEN NULL ELSE {id: pl.id, name: pl.name} END AS pipeline,
       [x IN collect(CASE WHEN ps IS NULL THEN NULL
          ELSE {id: ps.id, name: ps.name, order: sr.order} END) WHERE x IS NOT NULL] AS pstages
"""


async def _writing(wid: str) -> dict:
    rows = await run_read(_WRITING_Q, id=wid)
    if not rows:
        raise HTTPException(404, "writing piece not found")
    w = dict(rows[0]["piece"])
    w["pipeline"] = dict(rows[0]["pipeline"]) if rows[0]["pipeline"] else None
    w["pipeline_stages"] = [dict(s) for s in rows[0]["pstages"]]
    return w


@router.get("/writing")
async def list_writing() -> list[dict]:
    rows = await run_read("MATCH (w:WritingPiece) RETURN w.id AS id ORDER BY w.created_at DESC")
    return [await _writing(r["id"]) for r in rows]


@router.post("/writing", status_code=201)
async def create_writing(body: WritingCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "a piece needs a title")
    wid = str(uuid.uuid4())
    stage = body.stage
    if body.pipeline_id and not stage:
        first = await run_read(
            "MATCH (:Pipeline {id: $pid})-[r:HAS_STAGE]->(s:PipelineStage) "
            "RETURN s.name AS name ORDER BY r.order LIMIT 1", pid=body.pipeline_id)
        stage = first[0]["name"] if first else ""
    await run_write(
        f"""
        CREATE (w:WritingPiece {{
            id: $id, title: $title, type: $type, platform: $platform,
            pipeline_id: $pipeline_id, stage: $stage, link: $link,
            notes: $notes, created_at: $now
        }})
        WITH w {_own('w')}
        WITH w
        OPTIONAL MATCH (pl:Pipeline {{id: $pipeline_id}})
        FOREACH (_ IN CASE WHEN pl IS NULL THEN [] ELSE [1] END |
            MERGE (w)-[:IN_PIPELINE]->(pl))
        """,
        id=wid, title=body.title.strip(), type=body.type, platform=body.platform,
        pipeline_id=(body.pipeline_id or ""), stage=stage, link=body.link,
        notes=body.notes, now=_now(),
    )
    await record("writing", "created", detail=body.title[:70], module="vision", entity_id=wid)
    return await _writing(wid)


@router.put("/writing/{wid}")
async def update_writing(wid: str, patch: WritingUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "pipeline_id" in fields:
        fields["pipeline_id"] = fields["pipeline_id"] or ""
    sets = ", ".join(f"w.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (w:WritingPiece {{id: $id}}) SET {sets} RETURN w", id=wid, **fields)
    if not rows:
        raise HTTPException(404, "writing piece not found")
    if "pipeline_id" in fields:
        await run_write(
            """
            MATCH (w:WritingPiece {id: $id})
            OPTIONAL MATCH (w)-[r:IN_PIPELINE]->(:Pipeline)
            DELETE r
            WITH w
            OPTIONAL MATCH (pl:Pipeline {id: $pid})
            FOREACH (_ IN CASE WHEN pl IS NULL THEN [] ELSE [1] END |
                MERGE (w)-[:IN_PIPELINE]->(pl))
            """,
            id=wid, pid=fields["pipeline_id"],
        )
        if "stage" not in fields:
            first = await run_read(
                "MATCH (:Pipeline {id: $pid})-[r:HAS_STAGE]->(s:PipelineStage) "
                "RETURN s.name AS name ORDER BY r.order LIMIT 1", pid=fields["pipeline_id"])
            await run_write("MATCH (w:WritingPiece {id: $id}) SET w.stage = $s",
                            id=wid, s=first[0]["name"] if first else "")
    await record("writing", "updated", detail=", ".join(fields), module="vision", entity_id=wid)
    return await _writing(wid)


@router.post("/writing/{wid}/advance")
async def advance_writing(wid: str) -> dict:
    w = await _writing(wid)
    stages = [s["name"] for s in w["pipeline_stages"]]
    if not stages:
        raise HTTPException(400, "this piece isn't linked to a pipeline with stages")
    try:
        nxt = stages.index(w.get("stage") or "") + 1
    except ValueError:
        nxt = 0
    if nxt >= len(stages):
        raise HTTPException(400, "already at the final stage")
    await run_write("MATCH (w:WritingPiece {id: $id}) SET w.stage = $s", id=wid, s=stages[nxt])
    await record("writing", "stage advanced", detail=f"{w['title'][:40]} → {stages[nxt]}",
                 module="vision", entity_id=wid)
    return await _writing(wid)


@router.delete("/writing/{wid}", status_code=204, response_class=Response)
async def delete_writing(wid: str) -> Response:
    await run_write("MATCH (w:WritingPiece {id: $id}) DETACH DELETE w", id=wid)
    await record("writing", "deleted", detail=wid, module="vision")
    return Response(status_code=204)


# =========================================================================== #
# PORTFOLIO — project showcase (:PortfolioProject, distinct from the
# Mainframe-level :Project used by the shared Project tab)
# =========================================================================== #
def _portfolio(p) -> dict:
    # A project owns an ordered list of images; `image` stays as the cover
    # (always images[0]) so anything reading the single field still works.
    # Projects saved before the list existed have only `image`.
    p = dict(p)
    imgs = [u for u in (p.get("images") or []) if u]
    if not imgs and p.get("image"):
        imgs = [p["image"]]
    p["images"] = imgs
    p["image"] = imgs[0] if imgs else ""
    return p


@router.get("/portfolio")
async def list_portfolio() -> list[dict]:
    rows = await run_read("MATCH (p:PortfolioProject) RETURN p ORDER BY p.created_at DESC")
    return [_portfolio(r["p"]) for r in rows]


@router.post("/portfolio", status_code=201)
async def create_portfolio(body: PortfolioCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "a project needs a title")
    pid = str(uuid.uuid4())
    images = [u for u in body.images if u] or ([body.image] if body.image else [])
    rows = await run_write(
        f"""
        CREATE (p:PortfolioProject {{
            id: $id, title: $title, description: $description, type: $type,
            link: $link, image: $image, images: $images, tags: $tags, created_at: $now
        }})
        WITH p {_own('p')}
        RETURN p
        """,
        id=pid, title=body.title.strip(), description=body.description, type=body.type,
        link=body.link, image=images[0] if images else "", images=images, tags=body.tags, now=_now(),
    )
    await record("portfolio", "created", detail=body.title[:70], module="vision", entity_id=pid)
    return _portfolio(rows[0]["p"])


@router.put("/portfolio/{pid}")
async def update_portfolio(pid: str, patch: PortfolioUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    # the list wins and sets the cover; a bare `image` (old clients) replaces the cover
    if "images" in fields:
        fields["images"] = [u for u in (fields["images"] or []) if u]
        fields["image"] = fields["images"][0] if fields["images"] else ""
    elif "image" in fields:
        cur = await run_read("MATCH (p:PortfolioProject {id: $id}) RETURN p", id=pid)
        rest = _portfolio(cur[0]["p"])["images"][1:] if cur else []
        fields["image"] = fields["image"] or ""
        fields["images"] = ([fields["image"]] if fields["image"] else []) + rest
    sets = ", ".join(f"p.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (p:PortfolioProject {{id: $id}}) SET {sets} RETURN p", id=pid, **fields)
    if not rows:
        raise HTTPException(404, "project not found")
    await record("portfolio", "updated", detail=", ".join(fields), module="vision", entity_id=pid)
    return _portfolio(rows[0]["p"])


@router.delete("/portfolio/{pid}", status_code=204, response_class=Response)
async def delete_portfolio(pid: str) -> Response:
    await run_write("MATCH (p:PortfolioProject {id: $id}) DETACH DELETE p", id=pid)
    await record("portfolio", "deleted", detail=pid, module="vision")
    return Response(status_code=204)


# =========================================================================== #
# NETWORK — content-world contacts
# =========================================================================== #
_CONTACT_Q = """
MATCH (c:Contact) WHERE $id IS NULL OR c.id = $id
OPTIONAL MATCH (c)-[:HAS_INTERACTION]->(i:ContactInteraction)
WITH c, i ORDER BY i.date DESC, i.created_at DESC
WITH c, [x IN collect(CASE WHEN i IS NULL THEN NULL ELSE i{.*} END) WHERE x IS NOT NULL] AS log
RETURN c{.*} AS c, log
ORDER BY toLower(c.name)
"""


def _contact(row: dict) -> dict:
    c = dict(row["c"])
    for k in ("known_from", "first_contact", "email", "urgency"):    # pre-existing contacts lack these
        c.setdefault(k, "")
    c["interactions"] = [dict(x) for x in row["log"]]
    c["last_contact"] = c["interactions"][0]["date"] if c["interactions"] else ""
    return c


@router.get("/network")
async def list_network() -> list[dict]:
    return [_contact(r) for r in await run_read(_CONTACT_Q, id=None)]


@router.get("/network/{cid}")
async def get_contact(cid: str) -> dict:
    rows = await run_read(_CONTACT_Q, id=cid)
    if not rows:
        raise HTTPException(404, "contact not found")
    return _contact(rows[0])


@router.post("/network", status_code=201)
async def create_contact(body: ContactCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a contact needs a name")
    cid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (c:Contact {{
            id: $id, name: $name, role: $role, platform: $platform,
            link: $link, notes: $notes, avatar: $avatar, known_from: $known_from,
            first_contact: $first_contact, email: $email, urgency: $urgency,
            created_at: $now
        }})
        WITH c {_own('c')}
        RETURN c
        """,
        id=cid, name=body.name.strip(), role=body.role, platform=body.platform,
        link=body.link, notes=body.notes, avatar=body.avatar, known_from=body.known_from,
        first_contact=body.first_contact, email=body.email, urgency=body.urgency, now=_now(),
    )
    await record("contact", "added", detail=body.name[:70], module="vision", entity_id=cid)
    return await get_contact(cid)


@router.put("/network/{cid}")
async def update_contact(cid: str, patch: ContactUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    fields = {k: ("" if v is None else v) for k, v in fields.items()}
    sets = ", ".join(f"c.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (c:Contact {{id: $id}}) SET {sets} RETURN c", id=cid, **fields)
    if not rows:
        raise HTTPException(404, "contact not found")
    await record("contact", "updated", detail=", ".join(fields), module="vision", entity_id=cid)
    return await get_contact(cid)


@router.delete("/network/{cid}", status_code=204, response_class=Response)
async def delete_contact(cid: str) -> Response:
    await run_write(
        "MATCH (c:Contact {id: $id}) "
        "OPTIONAL MATCH (c)-[:HAS_INTERACTION]->(i:ContactInteraction) "
        "DETACH DELETE i, c", id=cid)
    await record("contact", "deleted", detail=cid, module="vision")
    return Response(status_code=204)


@router.post("/network/{cid}/interactions", status_code=201)
async def add_interaction(cid: str, body: ContactInteractionCreate) -> dict:
    if not body.date:
        raise HTTPException(400, "an interaction needs a date")
    rows = await run_write(
        """
        MATCH (c:Contact {id: $cid})
        CREATE (c)-[:HAS_INTERACTION]->(:ContactInteraction {
            id: $iid, date: $date, channel: $channel, note: $note, created_at: $now})
        RETURN c.name AS name
        """,
        cid=cid, iid=str(uuid.uuid4()), date=body.date, channel=body.channel,
        note=body.note, now=_now(),
    )
    if not rows:
        raise HTTPException(404, "contact not found")
    await record("contact", "contacted", detail=f"{rows[0]['name'][:40]} · {body.channel or body.date}",
                 module="vision", entity_id=cid)
    return await get_contact(cid)


@router.delete("/network/{cid}/interactions/{iid}", status_code=204, response_class=Response)
async def delete_interaction(cid: str, iid: str) -> Response:
    await run_write(
        "MATCH (:Contact {id: $cid})-[:HAS_INTERACTION]->(i:ContactInteraction {id: $iid}) DETACH DELETE i",
        cid=cid, iid=iid)
    return Response(status_code=204)


@router.get("/tools")
async def list_tools() -> list[dict]:
    """Every tool/LLM named across all stages — the cross-link payoff of giving
    tools their own nodes. Useful later for "what am I using Claude for?"."""
    rows = await run_read(
        """
        MATCH (t:Tool)
        OPTIONAL MATCH (s:PipelineStage)-[:USES_TOOL]->(t)
        OPTIONAL MATCH (p:Pipeline)-[:HAS_STAGE]->(s)
        RETURN t.name AS name, count(DISTINCT s) AS stages,
               collect(DISTINCT p.name) AS pipelines
        ORDER BY name
        """
    )
    return [dict(r) for r in rows]
