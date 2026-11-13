"""/api/projects — the Project area (Mainframe-level, not Synapse-specific).

A project holds files the user either UPLOADS (copied to ~/.mainframe/projects/,
size recorded) or LINKS (a path/URL to something they already own, with a note).
Every mutation writes a `project` ChangeEvent, which feeds the contribution grid.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

import poolgoals
from activity import record
from config import settings
from db import run_read, run_write
from models import (DEFAULT_WORK_TYPE, IdeaLinkCreate, ProjectCreate,
                    ProjectIdeaAttach, ProjectIdeaUpdate, ProjectLinkCreate,
                    ProjectPush, ProjectUpdate, RaiseToGoal)
from routes.papers import _LINK_LABEL
from routes.work import create_session
from models import WorkSessionCreate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Every project read carries its work totals so the card can show hours spent
# without a second round trip — plus how many passes it has, and the CURRENT
# title of whatever it references. The title is resolved through the :ABOUT
# relationship rather than stored, so renaming the target over there is never a
# stale copy here (same rule as a Repository entry's link).
# `completed` is the live name for the finished-work flag and `pushed` the
# legacy alias for the same thing (see WorkSessionCreate). The form writes
# `completed`, so counting only `pushed` — as this did — made every push_count
# in the app permanently 0. Read both, the way the frontend already does.
_SESSION_ROLLUP = """
OPTIONAL MATCH (w:WorkSession)-[:ON]->(p)
WITH p, files, collect(w{.*}) AS ws
OPTIONAL MATCH (p)-[:HAS_PASS]->(pp:ProjectPass)
WITH p, files, ws, count(pp) AS pass_count
OPTIONAL MATCH (p)-[:ABOUT]->(t)
WITH p, files, ws, pass_count, coalesce(t.name, t.title, t.label) AS link_title
WITH p, files, ws, pass_count, link_title,
     reduce(s = 0, x IN ws | s + coalesce(x.mins, 0)) AS total_mins,
     size([x IN ws WHERE coalesce(x.pushed, false) OR coalesce(x.completed, false)]) AS push_count
"""
_ROLLUP_RETURN = "pass_count, link_title, total_mins, push_count"


def _shape(row: dict) -> dict:
    proj = row["project"]
    proj["files"] = [f for f in row["files"] if f.get("id")]
    sessions = [s for s in row.get("sessions") or [] if s.get("id")]
    sessions.sort(key=lambda s: (s.get("date") or "", s.get("start") or ""), reverse=True)
    proj["sessions"] = sessions
    proj["total_mins"] = row.get("total_mins") or 0
    proj["push_count"] = row.get("push_count") or 0
    proj["pass_count"] = row.get("pass_count") or 0
    proj["link_title"] = row.get("link_title")
    proj["last_worked"] = sessions[0]["date"] if sessions else None
    proj.setdefault("contributes", True)
    # Present on every project even if the migration has not reached it, so the
    # type chip never has to render a null.
    proj.setdefault("kind", DEFAULT_WORK_TYPE)
    proj.setdefault("link_kind", None)
    proj.setdefault("link_id", None)
    proj["parent_id"] = row.get("parent_id") or ""
    proj["parent_name"] = row.get("parent_name") or ""
    return proj


async def _attach_link(project_id: str, link_kind: str | None, link_id: str | None) -> None:
    """Point a project at what it is about — a paper, a decomposition node, an
    idea, or another project. One target at a time: re-linking replaces, and a
    blank kind detaches. The properties are kept in step with the relationship
    so a client can read the pair back without walking the graph."""
    await run_write("MATCH (:Project {id: $id})-[r:ABOUT]->() DELETE r", id=project_id)
    if not link_kind or not link_id:
        await run_write(
            "MATCH (p:Project {id: $id}) REMOVE p.link_kind, p.link_id", id=project_id
        )
        return
    label = _LINK_LABEL.get(link_kind)
    if not label:
        raise HTTPException(400, f"unknown link kind: {link_kind}")
    rows = await run_write(
        f"""
        MATCH (p:Project {{id: $pid}}), (n:{label} {{id: $nid}})
        MERGE (p)-[:ABOUT]->(n)
        SET p.link_kind = $kind, p.link_id = $nid
        RETURN n
        """,
        pid=project_id, nid=link_id, kind=link_kind,
    )
    if not rows:
        raise HTTPException(404, "nothing to link to with that id")


async def _with_files(project_id: str) -> dict:
    rows = await run_read(
        f"""
        MATCH (p:Project {{id: $id}})
        OPTIONAL MATCH (p)-[:HAS_FILE]->(f:ProjectFile)
        WITH p, f ORDER BY f.created_at
        WITH p, collect(f{{.*}}) AS files
        {_SESSION_ROLLUP}
        OPTIONAL MATCH (p)-[:PARENT]->(par:Project)
        RETURN p{{.*}} AS project, files, ws AS sessions, {_ROLLUP_RETURN},
               par.id AS parent_id, par.name AS parent_name
        """,
        id=project_id,
    )
    if not rows:
        raise HTTPException(404, "project not found")
    return _shape(rows[0])


@router.get("")
async def list_projects() -> list[dict]:
    rows = await run_read(
        f"""
        MATCH (p:Project)
        OPTIONAL MATCH (p)-[:HAS_FILE]->(f:ProjectFile)
        WITH p, f ORDER BY f.created_at
        WITH p, collect(f{{.*}}) AS files
        {_SESSION_ROLLUP}
        OPTIONAL MATCH (p)-[:PARENT]->(par:Project)
        RETURN p{{.*}} AS project, files, ws AS sessions, {_ROLLUP_RETURN},
               par.id AS parent_id, par.name AS parent_name
        ORDER BY project.created_at DESC
        """
    )
    return [_shape(r) for r in rows]


@router.post("", status_code=201)
async def create_project(body: ProjectCreate) -> dict:
    pid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (p:Project {
            id: $id, name: $name, note: $note, created_at: $now,
            contributes: true, status: 'active', repo: '', kind: $kind
        })
        """,
        id=pid, name=body.name.strip(), note=body.note, now=_now(),
        kind=body.kind,
    )
    if body.link_kind and body.link_id:
        await _attach_link(pid, body.link_kind, body.link_id)
    await record("project", "created", detail=body.name[:70])
    return await _with_files(pid)


@router.patch("/{project_id}")
async def update_project(project_id: str, patch: ProjectUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    # The reference is a pair, not two independent properties, and it has to be
    # clearable — so it's taken out of the generic SET and relinked as one move.
    # Sending link_kind at all (even "") is what asks for that; leaving it off
    # entirely leaves an existing link alone.
    sent = patch.model_fields_set
    # Nesting is an edge, not a column, so it comes out of the generic SET the
    # same way the reference pair does.
    if "parent_id" in sent:
        fields.pop("parent_id", None)
        await _set_parent(project_id, patch.parent_id or "")
    if "link_kind" in sent or "link_id" in sent:
        fields.pop("link_kind", None)
        fields.pop("link_id", None)
        await _attach_link(project_id, patch.link_kind or None, patch.link_id or None)
    if fields:
        sets = ", ".join(f"p.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (p:Project {{id: $id}}) SET {sets} RETURN p", id=project_id, **fields)
        if not rows:
            raise HTTPException(404, "project not found")
        await record("project", "updated", detail=", ".join(fields))
    return await _with_files(project_id)   # 404s on its own if the id is bad


@router.delete("/{project_id}", status_code=204, response_class=Response)
async def delete_project(project_id: str) -> Response:
    # remove uploaded files from disk
    files = await run_read(
        "MATCH (:Project {id: $id})-[:HAS_FILE]->(f:ProjectFile) WHERE f.kind = 'upload' RETURN f.path AS path",
        id=project_id,
    )
    for f in files:
        if f["path"]:
            Path(f["path"]).unlink(missing_ok=True)
    proj_dir = settings.projects_dir / project_id
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
    await run_write(
        """
        MATCH (p:Project {id: $id})
        OPTIONAL MATCH (p)-[:HAS_FILE]->(f:ProjectFile)
        OPTIONAL MATCH (p)-[:HAS_PASS]->(i:ProjectPass)
        OPTIONAL MATCH (i)-[:HAS_FILE]->(pf:ProjectFile)
        DETACH DELETE pf, i, f, p
        """,
        id=project_id,
    )
    await record("project", "deleted", detail=project_id)
    return Response(status_code=204)


@router.post("/{project_id}/push", status_code=201)
async def push_project(project_id: str, body: ProjectPush) -> dict:
    """Record a push — writes a work session flagged `pushed`, which puts a ★ on
    that day's contribution square and lands a row in the work database."""
    rows = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name", id=project_id)
    if not rows:
        raise HTTPException(404, "project not found")
    await create_session(WorkSessionCreate(
        date=body.date,
        mins=body.mins,
        module="mainframe",
        ref_kind="project",
        ref_id=project_id,
        ref_title=rows[0]["name"],
        what=body.note or "pushed",
        pushed=True,
    ))
    return await _with_files(project_id)


@router.get("/{project_id}/master")
async def project_master(project_id: str) -> dict:
    """Everything written about this project, rolled into one readable document:
    the note, every file note, and every work session's text — plus the totals
    (hours spent, sessions, pushes, span) so they're readable at a glance."""
    proj = await _with_files(project_id)
    sessions = proj["sessions"]
    dates = sorted(s["date"] for s in sessions if s.get("date"))
    # every piece of prose attached to the project, in one place
    blocks = []
    if (proj.get("note") or "").strip():
        blocks.append({"source": "project note", "date": None, "text": proj["note"].strip()})
    for f in proj["files"]:
        if (f.get("note") or "").strip():
            blocks.append({"source": "file · " + f.get("name", ""), "date": None, "text": f["note"].strip()})
    for s in sessions:
        text = " · ".join(x for x in (s.get("what"), s.get("notes")) if (x or "").strip())
        if text:
            blocks.append({
                "source": "session · " + (s.get("date") or ""),
                "date": s.get("date"),
                "mins": s.get("mins") or 0,
                "text": text,
            })
    focus_mins = {"active": 0, "passive": 0, "none": 0}
    for s in sessions:
        focus_mins[s.get("focus") or "none"] = focus_mins.get(s.get("focus") or "none", 0) + (s.get("mins") or 0)
    return {
        "id": proj["id"],
        "name": proj["name"],
        "contributes": proj.get("contributes", True),
        "total_mins": proj["total_mins"],
        "session_count": len(sessions),
        "push_count": proj["push_count"],
        "first_worked": dates[0] if dates else None,
        "last_worked": dates[-1] if dates else None,
        "distinct_days": len(set(dates)),
        "distraction_mins": sum(s.get("distraction_mins") or 0 for s in sessions),
        "focus_mins": focus_mins,
        "file_count": len(proj["files"]),
        "blocks": blocks,
    }


# --------------------------------------------------------------------------- #
# Documents written for this project
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/docs")
async def project_docs(project_id: str) -> list[dict]:
    """The documents bound to this project, with the work done inside each.

    Hours here are the sessions pushed from inside a document — which are also
    :ON the project. They are a slice of the project's total, never an addition
    to it: adding these to `total_mins` would count the same hours twice.
    """
    rows = await run_read(
        """
        MATCH (d:Document)-[:FOR]->(:Project {id: $id})
        OPTIONAL MATCH (w:WorkSession)-[:WORKED_ON]->(d)
        WITH d, collect(w) AS ws
        RETURN d.id AS id, d.title AS title,
               reduce(m = 0, x IN ws | m + coalesce(x.mins, 0)) AS mins,
               size(ws) AS session_count,
               reduce(last = '', x IN ws |
                      CASE WHEN coalesce(x.date, '') > last THEN x.date ELSE last END) AS last_worked,
               d.updated_at AS updated_at
        ORDER BY mins DESC, toLower(coalesce(title, ''))
        """,
        id=project_id,
    )
    return [{**r, "last_worked": r["last_worked"] or None} for r in rows]


@router.post("/{project_id}/files", status_code=201)
async def upload_file(project_id: str, file: UploadFile = File(...)) -> dict:
    ctx = await run_read("MATCH (p:Project {id: $id}) RETURN p", id=project_id)
    if not ctx:
        raise HTTPException(404, "project not found")
    fid = str(uuid.uuid4())
    proj_dir = settings.projects_dir / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    name = os.path.basename(file.filename or "file")
    dest = proj_dir / f"{fid}__{name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    size = dest.stat().st_size
    await run_write(
        """
        MATCH (p:Project {id: $pid})
        CREATE (p)-[:HAS_FILE]->(f:ProjectFile {
            id: $id, name: $name, kind: 'upload', size: $size,
            path: $path, url: null, note: '', created_at: $now
        })
        """,
        pid=project_id, id=fid, name=name, size=size, path=str(dest), now=_now(),
    )
    await record("project", "file uploaded", detail=f"{name} ({size} B)")
    return await _with_files(project_id)


@router.post("/{project_id}/links", status_code=201)
async def add_link(project_id: str, body: ProjectLinkCreate) -> dict:
    ctx = await run_read("MATCH (p:Project {id: $id}) RETURN p", id=project_id)
    if not ctx:
        raise HTTPException(404, "project not found")
    if not (body.url or body.path):
        raise HTTPException(400, "provide a url or a path")
    # if it's a local path that exists, record its size for reference
    size = None
    if body.path:
        try:
            p = Path(os.path.expanduser(body.path))
            if p.is_file():
                size = p.stat().st_size
        except Exception:  # noqa: BLE001
            size = None
    fid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:Project {id: $pid})
        CREATE (p)-[:HAS_FILE]->(f:ProjectFile {
            id: $id, name: $name, kind: 'link', size: $size,
            path: $path, url: $url, note: $note, created_at: $now
        })
        """,
        pid=project_id, id=fid, name=body.name.strip(), size=size,
        path=body.path, url=body.url, note=body.note, now=_now(),
    )
    await record("project", "link added", detail=body.name[:70])
    return await _with_files(project_id)


@router.delete("/{project_id}/files/{file_id}", status_code=204, response_class=Response)
async def delete_file(project_id: str, file_id: str) -> Response:
    rows = await run_read(
        "MATCH (:Project {id: $pid})-[:HAS_FILE]->(f:ProjectFile {id: $fid}) RETURN f.kind AS kind, f.path AS path",
        pid=project_id, fid=file_id,
    )
    if rows and rows[0]["kind"] == "upload" and rows[0]["path"]:
        Path(rows[0]["path"]).unlink(missing_ok=True)
    await run_write("MATCH (f:ProjectFile {id: $fid}) DETACH DELETE f", fid=file_id)
    await record("project", "file removed", detail=file_id)
    return Response(status_code=204)


@router.get("/{project_id}/files/{file_id}/download")
async def download_file(project_id: str, file_id: str) -> FileResponse:
    rows = await run_read(
        "MATCH (:Project {id: $pid})-[:HAS_FILE]->(f:ProjectFile {id: $fid}) RETURN f.path AS path, f.name AS name, f.kind AS kind",
        pid=project_id, fid=file_id,
    )
    if not rows or rows[0]["kind"] != "upload" or not rows[0]["path"]:
        raise HTTPException(404, "no downloadable file")
    path = Path(rows[0]["path"])
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(str(path), filename=rows[0]["name"])


# --------------------------------------------------------------------------- #
# Project ideas — reference list, database and knowledge graph
#
# All three views read the same edge. `(:Project)-[:HAS_IDEA {status, note,
# x, y}]->(:Idea)` keeps the per-project judgement ("worth looking at") on the
# relationship, so the Idea node itself stays global and can belong to several
# projects at once. Connections BETWEEN ideas are global too — an idea that
# links to another does so regardless of which project you're looking from.
# --------------------------------------------------------------------------- #
_IDEA_FIELDS = "i{.id, .title, .category, .priority, .status, .description, .notes}"


async def _project_ideas(project_id: str) -> list[dict]:
    rows = await run_read(
        f"""
        MATCH (:Project {{id: $id}})-[r:HAS_IDEA]->(i:Idea)
        RETURN {_IDEA_FIELDS} AS idea, r{{.status, .note, .x, .y, .w, .h, .added_at}} AS link
        ORDER BY coalesce(r.added_at, '')
        """,
        id=project_id,
    )
    out = []
    for row in rows:
        idea = dict(row["idea"])
        link = dict(row["link"] or {})
        # `status` means two different things — the idea's own lifecycle and
        # what this project thinks of it. Keep them apart.
        idea["look_status"] = link.get("status") or "to-look-at"
        idea["look_note"] = link.get("note") or ""
        idea["x"] = link.get("x")
        idea["y"] = link.get("y")
        # Box size on the knowledge map. Null means "never resized" — the canvas
        # picks its own default rather than this deciding one for it.
        idea["w"] = link.get("w")
        idea["h"] = link.get("h")
        idea["added_at"] = link.get("added_at")
        out.append(idea)
    return out


@router.get("/{project_id}/ideas")
async def list_project_ideas(project_id: str) -> list[dict]:
    return await _project_ideas(project_id)


@router.post("/{project_id}/ideas", status_code=201)
async def attach_idea(project_id: str, body: ProjectIdeaAttach) -> dict:
    rows = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name", id=project_id)
    if not rows:
        raise HTTPException(404, "project not found")

    idea_id = body.idea_id
    if not idea_id:
        title = (body.title or "").strip()
        if not title:
            raise HTTPException(400, "give the idea a title, or attach an existing one")
        idea_id = str(uuid.uuid4())
        await run_write(
            """
            OPTIONAL MATCH (x:Idea)
            WITH coalesce(min(x.position), 0.0) - 1.0 AS pos
            CREATE (i:Idea:Task {id: $id, title: $title, category: $category,
                            kind: 'idea', priority: 'medium', status: 'raw',
                            description: '', low_h: 0.0, high_h: 0.0, due: '',
                            notes: '', created_at: $now, position: pos})
            """,
            id=idea_id, title=title, category=body.category or "research", now=_now(),
        )
    else:
        exists = await run_read("MATCH (i:Idea {id: $id}) RETURN i.id AS id", id=idea_id)
        if not exists:
            raise HTTPException(404, "idea not found")

    # Attaching an idea that's already attached must not silently reset it.
    # Only fields the caller actually sent are written; the rest keep whatever
    # the existing edge holds, so re-attaching never eats your note.
    sent = body.model_fields_set
    await run_write(
        """
        MATCH (p:Project {id: $pid}), (i:Idea {id: $iid})
        MERGE (p)-[r:HAS_IDEA]->(i)
          ON CREATE SET r.added_at = $now, r.status = $status, r.note = $note
        SET r.status = coalesce($status_set, r.status),
            r.note = coalesce($note_set, r.note)
        """,
        pid=project_id, iid=idea_id, now=_now(),
        status=body.status, note=body.note,
        status_set=body.status if "status" in sent else None,
        note_set=body.note if "note" in sent else None,
    )
    await record("project", "idea attached", detail=(body.title or idea_id)[:70],
                 entity_id=project_id)
    ideas = await _project_ideas(project_id)
    return next((i for i in ideas if i["id"] == idea_id), {"id": idea_id})


@router.patch("/{project_id}/ideas/{idea_id}")
async def update_project_idea(project_id: str, idea_id: str,
                              patch: ProjectIdeaUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"r.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"""
        MATCH (:Project {{id: $pid}})-[r:HAS_IDEA]->(:Idea {{id: $iid}})
        SET {sets}
        RETURN r{{.*}} AS r
        """,
        pid=project_id, iid=idea_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "that idea is not attached to this project")
    # Dragging or resizing a node on the canvas is a geometry write and nothing
    # more — logging every pixel would drown the activity feed.
    if any(k not in {"x", "y", "w", "h"} for k in fields):
        await record("project", "idea updated", detail=", ".join(fields), entity_id=project_id)
    # A map projection, not the bare relationship: the driver turns a returned
    # relationship into a (start, type, end) tuple, and dict() on that raises —
    # which made every edit here answer 500 after having already written.
    return dict(rows[0]["r"] or {})


@router.delete("/{project_id}/ideas/{idea_id}", status_code=204, response_class=Response)
async def detach_idea(project_id: str, idea_id: str) -> Response:
    """Detach only. The idea is global — deleting it here would remove it from
    the Ideas tab and from any other project holding it."""
    await run_write(
        "MATCH (:Project {id: $pid})-[r:HAS_IDEA]->(:Idea {id: $iid}) DELETE r",
        pid=project_id, iid=idea_id,
    )
    await record("project", "idea detached", detail=idea_id, entity_id=project_id)
    return Response(status_code=204)


@router.get("/{project_id}/graph")
async def project_graph(project_id: str) -> dict:
    """Nodes = this project's ideas. Edges = connections between them.

    Only edges whose BOTH ends are attached here are returned; a link out to an
    idea that lives in another project would draw an arrow to nowhere.
    """
    nodes = await _project_ideas(project_id)
    ids = [n["id"] for n in nodes]
    edges = await run_read(
        """
        MATCH (a:Idea)-[r:RELATES_TO]->(b:Idea)
        WHERE a.id IN $ids AND b.id IN $ids
        RETURN r.id AS id, a.id AS from_id, b.id AS to_id, coalesce(r.label, '') AS label
        """,
        ids=ids,
    )
    return {"nodes": nodes, "edges": [dict(e) for e in edges]}


@router.post("/{project_id}/graph/edges", status_code=201)
async def connect_ideas(project_id: str, body: IdeaLinkCreate) -> dict:
    if body.from_id == body.to_id:
        raise HTTPException(400, "an idea can't connect to itself")
    eid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (a:Idea {id: $a}), (b:Idea {id: $b})
        MERGE (a)-[r:RELATES_TO]->(b)
          ON CREATE SET r.id = $eid, r.created_at = $now
        SET r.label = $label
        RETURN r.id AS id, coalesce(r.label, '') AS label
        """,
        a=body.from_id, b=body.to_id, eid=eid, label=body.label, now=_now(),
    )
    if not rows:
        raise HTTPException(404, "one of those ideas doesn't exist")
    await record("project", "ideas connected", detail=body.label or "link",
                 entity_id=project_id)
    return {"id": rows[0]["id"], "from_id": body.from_id, "to_id": body.to_id,
            "label": rows[0]["label"]}


@router.delete("/{project_id}/graph/edges/{edge_id}", status_code=204,
               response_class=Response)
async def disconnect_ideas(project_id: str, edge_id: str) -> Response:
    await run_write("MATCH (:Idea)-[r:RELATES_TO {id: $eid}]->(:Idea) DELETE r", eid=edge_id)
    await record("project", "ideas disconnected", detail=edge_id, entity_id=project_id)
    return Response(status_code=204)


# =========================================================================== #
# NESTING, AND WHAT A PROJECT HAS TAKEN ON
#
# A project page answers three questions in order: what was handed to it, what
# it committed to as a result, and what sits under it. The first two are the
# chain Ideas and Goals are two ends of, seen from the middle.
# =========================================================================== #

@router.get("/{project_id}/given")
async def ideas_given_to(project_id: str) -> list[dict]:
    """Ideas handed to this project, with the date and the reason.

    The reason is the current note on the GIVEN_TO edge, read through the same
    :Hop the Ideas table wrote it against. Superseded reasons are not shown here
    (the note panel is where you go for the history); this is the answer as it
    stands.
    """
    rows = await run_read(
        """
        MATCH (i:Idea)-[g:GIVEN_TO]->(:Project {id: $id})
        OPTIONAL MATCH (h:Hop {from_id: i.id, rel: 'GIVEN_TO', to_id: $id})
        OPTIONAL MATCH (n:Note)-[:NOTE_ON]->(h)
          WHERE n.kind = 'why' AND NOT (:Note)-[:SUPERSEDES]->(n)
        WITH i, g, n ORDER BY n.created_at DESC
        WITH i, g, head(collect(n)) AS why
        RETURN i{.id, .title, .description, .category, .priority, .status} AS idea,
               g.date AS given_on, why.text AS why, why.date AS why_date
        ORDER BY g.date DESC, i.title
        """, id=project_id)
    return [{**dict(r["idea"]), "given_on": r["given_on"] or "",
             "why": r["why"] or "", "why_date": r["why_date"] or ""} for r in rows]


@router.get("/{project_id}/goals")
async def project_goals(project_id: str) -> list[dict]:
    """Goals raised from this project, each with its estimate, due date and the
    phases that have claimed it."""
    return await poolgoals.read(
        "(g)-[:THROUGH]->(:Project {id: $pid})", pid=project_id)


@router.post("/{project_id}/goals", status_code=201)
async def raise_to_goal(project_id: str, body: RaiseToGoal) -> dict:
    """Raise a goal from this project. The only way a goal is created.

    Every other tab reads goals; none of them makes one. That is deliberate: a
    goal with no project and no raising is a wish, and the one place it is
    reasonable to write one down is in front of the work it belongs to.

    Ticked ideas become (:Goal)-[:FROM_IDEA]->(:Idea), so the goal can say what
    it came out of and the idea can be followed forward to what became of it.
    """
    if not body.text.strip():
        raise HTTPException(400, "say what the goal is")
    exists = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name",
                            id=project_id)
    if not exists:
        raise HTTPException(404, "no such project")
    if body.due:
        date.fromisoformat(body.due[:10])

    gid = await poolgoals.create(
        body.text, horizon=body.horizon, due=body.due,
        estimate_h=body.estimate_h, project_id=project_id,
        idea_ids=body.idea_ids)

    if body.why.strip():
        # Written as a note rather than a field so the Reasoning tab picks it up
        # with everything else. A why in a column is a why nothing can find.
        await run_write(
            """
            MATCH (g:PoolGoal {id: $gid})
            CREATE (n:Note {id: randomUUID(), date: $today, text: $text,
                            kind: 'why', created_at: $now})
            CREATE (n)-[:NOTE_ON]->(g)
            """, gid=gid, text=body.why.strip(),
            today=date.today().isoformat(), now=_now())

    await record("goal", "raised from a project",
                 detail=f"{exists[0]['name'][:30]}: {body.text.strip()[:38]}"[:70],
                 entity_id=gid)
    return await poolgoals.one(gid)


@router.get("/{project_id}/children")
async def project_children(project_id: str) -> list[dict]:
    """Projects sitting under this one. One level: the page shows its own
    children, and each of those is a page with its own."""
    rows = await run_read(
        """
        MATCH (c:Project)-[:PARENT]->(:Project {id: $id})
        OPTIONAL MATCH (w:WorkSession)-[:ON]->(c)
        WITH c, count(w) AS sessions, sum(coalesce(w.mins, 0)) AS mins
        RETURN c{.id, .name, .status, .note} AS child, sessions, mins
        ORDER BY c.name
        """, id=project_id)
    return [{**dict(r["child"]), "sessions": r["sessions"],
             "mins": r["mins"] or 0} for r in rows]


async def _set_parent(project_id: str, parent_id: str) -> None:
    """Move a project under another, or out to the top level.

    Refuses to make a project its own ancestor. Without that check one wrong
    pick makes a cycle, and a cycle in a tree the UI walks is a hang, not a
    tidy error.
    """
    await run_write("MATCH (p:Project {id: $id})-[r:PARENT]->() DELETE r", id=project_id)
    if not parent_id or parent_id == project_id:
        return
    loop = await run_read(
        "MATCH (candidate:Project {id: $parent})-[:PARENT*1..20]->(p:Project {id: $id}) "
        "RETURN count(*) AS n", parent=parent_id, id=project_id)
    if loop and loop[0]["n"]:
        raise HTTPException(400, "that project already sits under this one")
    await run_write(
        "MATCH (p:Project {id: $id}), (q:Project {id: $parent}) "
        "MERGE (p)-[:PARENT]->(q)", id=project_id, parent=parent_id)
