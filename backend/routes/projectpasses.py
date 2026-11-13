"""/api/projects/{id}/passes — v1, v2, ... on a project.

The Repository's reading instances, for work you do rather than read. A paper
gets a pass each time you sit down with it; a project gets one each time you
take a run at it — "scaffold", "vault module", "make the voice layer work" —
and the hours you log go INTO a pass rather than into one undifferentiated
pile of sessions.

Three things a pass carries, all borrowed from the reading instance because
they turned out not to be about reading:

  purpose    what this run is for, written before it starts
  look_into  what you already know you want to come back to
  the link   the referenced id — the paper, decomposition node, idea or other
             project this run was worked against

A pass owns nothing. Deleting one leaves its work sessions in the database
(they lose only their `pass_id`), because the hours happened whether or not you
still want the pass they were filed under.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (ProjectLinkCreate, ProjectPassCreate, ProjectPassUpdate,
                    ReorderRequest)
from routes.mind import reorder_nodes
from routes.papers import _LINK_LABEL
from routes.rows import row_texts

router = APIRouter(prefix="/api/projects/{project_id}/passes", tags=["projects"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _project_name(project_id: str) -> str:
    rows = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name", id=project_id)
    if not rows:
        raise HTTPException(404, "project not found")
    return rows[0]["name"]


async def _attach_link(pass_id: str, link_kind: str | None, link_id: str | None) -> None:
    """Point one pass at what it was worked against. Same contract as a
    project's own link: one target, re-linking replaces, a blank kind detaches."""
    await run_write("MATCH (:ProjectPass {id: $id})-[r:ABOUT]->() DELETE r", id=pass_id)
    if not link_kind or not link_id:
        await run_write(
            "MATCH (i:ProjectPass {id: $id}) REMOVE i.link_kind, i.link_id", id=pass_id
        )
        return
    label = _LINK_LABEL.get(link_kind)
    if not label:
        raise HTTPException(400, f"unknown link kind: {link_kind}")
    rows = await run_write(
        f"""
        MATCH (i:ProjectPass {{id: $iid}}), (n:{label} {{id: $nid}})
        MERGE (i)-[:ABOUT]->(n)
        SET i.link_kind = $kind, i.link_id = $nid
        RETURN n
        """,
        iid=pass_id, nid=link_id, kind=link_kind,
    )
    if not rows:
        raise HTTPException(404, "nothing to link to with that id")


# The pass and everything hanging off it, in one read: its own properties, the
# live title of what it references, the links registered on it, and the work
# sessions filed under it rolled up. `link_title` is resolved through :ABOUT
# and never stored, so a rename over there shows here without a sync step.
_PASS_READ = """
OPTIONAL MATCH (i)-[:HAS_FILE]->(f:ProjectFile)
WITH i, f ORDER BY f.created_at
WITH i, collect(f{.*}) AS links
OPTIONAL MATCH (i)-[:ABOUT]->(t)
WITH i, links, coalesce(t.name, t.title, t.label) AS link_title
OPTIONAL MATCH (w:WorkSession) WHERE w.pass_id = i.id
WITH i, links, link_title, collect(w{.*}) AS ws
RETURN i{.*} AS pass, [x IN links WHERE x.id IS NOT NULL] AS links, link_title,
       reduce(s = 0, x IN ws | s + coalesce(x.mins, 0)) AS mins,
       size(ws) AS session_count,
       size([x IN ws WHERE coalesce(x.pushed, false) OR coalesce(x.completed, false)]) AS push_count
"""


def _shape(row: dict) -> dict:
    p = dict(row["pass"])
    p["links"] = row["links"]
    p["link_title"] = row["link_title"]
    p["mins"] = row["mins"] or 0
    p["session_count"] = row["session_count"] or 0
    p["push_count"] = row["push_count"] or 0
    p.setdefault("link_kind", None)
    p.setdefault("link_id", None)
    return p


@router.get("")
async def list_passes(project_id: str) -> list[dict]:
    await _project_name(project_id)
    rows = await run_read(
        f"""
        MATCH (:Project {{id: $pid}})-[:HAS_PASS]->(i:ProjectPass)
        {_PASS_READ}
        """,
        pid=project_id,
    )
    passes = [_shape(r) for r in rows]
    # "To look into later" is + rows on the pass; the chip's ⌛ hover reads them.
    texts = await row_texts([p["id"] for p in passes])
    for p in passes:
        p["row_text"] = texts.get(p["id"], {})
    # Ordered here rather than in Cypher: the read aggregates (links, sessions),
    # and an ORDER BY before an aggregation isn't guaranteed to survive it.
    passes.sort(key=lambda p: (p.get("position")
                               if p.get("position") is not None
                               else float(p.get("version") or 0),
                               p.get("version") or 0))
    return passes


@router.post("/reorder")
async def reorder_passes(project_id: str, body: ReorderRequest) -> dict:
    """Move passes around on screen.

    `version` records which run came first and never changes — that's a fact
    about the past. `position` is only the arrangement, so a pass can be moved
    without rewriting history. Same helper the reading instances use.
    """
    pairs = await reorder_nodes("ProjectPass", body.ids)
    await record("project", "passes reordered", detail=f"{len(pairs)} passes",
                 entity_id=project_id)
    return {"ok": True, "positions": pairs}


async def _one(project_id: str, pass_id: str) -> dict:
    rows = await run_read(
        f"""
        MATCH (:Project {{id: $pid}})-[:HAS_PASS]->(i:ProjectPass {{id: $iid}})
        {_PASS_READ}
        """,
        pid=project_id, iid=pass_id,
    )
    if not rows:
        raise HTTPException(404, "pass not found on this project")
    p = _shape(rows[0])
    p["row_text"] = (await row_texts([p["id"]])).get(p["id"], {})
    return p


@router.post("", status_code=201)
async def create_pass(project_id: str, body: ProjectPassCreate) -> dict:
    await _project_name(project_id)          # 404 before minting a version
    cnt = await run_read(
        "MATCH (:Project {id: $id})-[:HAS_PASS]->(i:ProjectPass) RETURN count(i) AS n",
        id=project_id,
    )
    version = (cnt[0]["n"] or 0) + 1
    pass_id = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:Project {id: $pid})
        CREATE (i:ProjectPass {
            id: $id, version: $version, position: $position, created_at: $now,
            purpose: $purpose, look_into: $look_into, notes: $notes
        })
        CREATE (p)-[:HAS_PASS]->(i)
        """,
        pid=project_id, id=pass_id, version=version, position=float(version),
        now=_now(),
        purpose=(body.purpose or "").strip() or f"pass {version}",
        # "" not null: Neo4j drops null properties, which would change the shape
        # of the response between a pass that has notes and one that doesn't.
        look_into=body.look_into or "", notes=body.notes or "",
    )
    if body.link_kind and body.link_id:
        await _attach_link(pass_id, body.link_kind, body.link_id)
    await record("project", "pass created", detail=f"v{version} — {body.purpose}",
                 entity_id=project_id)
    return await _one(project_id, pass_id)


@router.patch("/{pass_id}")
async def update_pass(project_id: str, pass_id: str, patch: ProjectPassUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    sent = patch.model_fields_set
    # The reference is a pair and has to be clearable, so it never goes through
    # the generic SET (see the same rule on a project).
    if "link_kind" in sent or "link_id" in sent:
        fields.pop("link_kind", None)
        fields.pop("link_id", None)
        await _attach_link(pass_id, patch.link_kind or None, patch.link_id or None)
    if fields:
        sets = ", ".join(f"i.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"""
            MATCH (:Project {{id: $pid}})-[:HAS_PASS]->(i:ProjectPass {{id: $iid}})
            SET {sets} RETURN i
            """,
            pid=project_id, iid=pass_id, **fields,
        )
        if not rows:
            raise HTTPException(404, "pass not found on this project")
        await record("project", "pass updated", detail=", ".join(fields),
                     entity_id=project_id)
    return await _one(project_id, pass_id)


@router.delete("/{pass_id}", status_code=204, response_class=Response)
async def delete_pass(project_id: str, pass_id: str) -> Response:
    """Delete one pass and the links registered on it.

    The work sessions filed under it are NOT deleted — they only lose their
    `pass_id`. Hours you actually spent are the one thing in here that isn't a
    way of organising; losing them because you renamed a plan would be wrong.
    """
    rows = await run_read(
        """
        MATCH (:Project {id: $pid})-[:HAS_PASS]->(i:ProjectPass {id: $iid})
        OPTIONAL MATCH (w:WorkSession) WHERE w.pass_id = i.id
        RETURN i.version AS version, i.purpose AS purpose, count(w) AS sessions
        """,
        pid=project_id, iid=pass_id,
    )
    if not rows:
        raise HTTPException(404, "pass not found on this project")
    meta = rows[0]
    await run_write(
        """
        MATCH (i:ProjectPass {id: $iid})
        OPTIONAL MATCH (i)-[:HAS_FILE]->(f:ProjectFile)
        DETACH DELETE f, i
        """,
        iid=pass_id,
    )
    await run_write(
        "MATCH (w:WorkSession) WHERE w.pass_id = $iid SET w.pass_id = ''", iid=pass_id
    )
    await record(
        "project", "pass deleted",
        detail=f"v{meta['version']} — {meta['sessions']} session(s) kept, unfiled",
        entity_id=project_id,
    )
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Links on a pass — a URL or a path to something you already own.
#
# Same :ProjectFile node the project's own links use, hung off the pass instead
# of the project, so "link" means one thing everywhere in the Project area.
# --------------------------------------------------------------------------- #
@router.post("/{pass_id}/links", status_code=201)
async def add_pass_link(project_id: str, pass_id: str, body: ProjectLinkCreate) -> dict:
    if not (body.url or body.path):
        raise HTTPException(400, "give the link a url or a path")
    lid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (:Project {id: $pid})-[:HAS_PASS]->(i:ProjectPass {id: $iid})
        CREATE (f:ProjectFile {
            id: $lid, kind: 'link', name: $name, url: $url, path: $path,
            note: $note, created_at: $now
        })
        CREATE (i)-[:HAS_FILE]->(f)
        RETURN f{.*} AS f
        """,
        pid=project_id, iid=pass_id, lid=lid, name=body.name.strip(),
        url=body.url, path=body.path, note=body.note, now=_now(),
    )
    if not rows:
        raise HTTPException(404, "pass not found on this project")
    await record("project", "pass link added", detail=body.name[:70], entity_id=project_id)
    return rows[0]["f"]


@router.delete("/{pass_id}/links/{link_id}", status_code=204, response_class=Response)
async def delete_pass_link(project_id: str, pass_id: str, link_id: str) -> Response:
    await run_write(
        """
        MATCH (:ProjectPass {id: $iid})-[:HAS_FILE]->(f:ProjectFile {id: $lid})
        DETACH DELETE f
        """,
        iid=pass_id, lid=link_id,
    )
    await record("project", "pass link removed", detail=link_id, entity_id=project_id)
    return Response(status_code=204)
