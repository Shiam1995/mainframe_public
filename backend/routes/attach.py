"""/api/synapse/attach and /api/synapse/projects/{id}/attachments.

ONE MASTER: THE PROJECT TREE. Everything Mainframe makes (a paper, a book, a
doc, a sheet, a video) is a node that can sit in a project. Attaching writes an
edge and moves nothing:

    (:X)-[:PART_OF {date}]->(:Project)
    (:X)-[:SOURCE_OF {date}]->(:Document)     the doc is built on X

Repository, Docs and Vision stay the places those nodes live; the project page
is where they are seen together. Detaching removes PART_OF only, never the node.

HOURS ROLL-UP. hours(x) is the time logged ON x plus the time on everything
under it; see hours.py, which every surface that shows project hours reads.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from db import run_read, run_write
from hours import hours_index
from models import ProjectAttach
from routes.inbox import _hop_why, _write_move

router = APIRouter(prefix="/api/synapse", tags=["attach"])

# kind → (label, title property, where it lives)
KINDS = {
    "project": ("Project", "name", "Project"),
    "paper": ("Paper", "title", "Repository"),
    "doc": ("Document", "title", "Docs"),
    "sheet": ("Sheet", "name", "Sheets"),
    "video": ("Video", "title", "Vision"),
    "writing": ("WritingPiece", "title", "Vision"),
}
LABEL_KIND = {v[0]: k for k, v in KINDS.items()}


# =========================================================================== #
# PICKER
# =========================================================================== #
def _where(kind: str, x: dict) -> str:
    base = KINDS[kind][2]
    if kind == "paper":
        bits = [base, x.get("status") or ""]
    elif kind == "doc":
        bits = [base, x.get("folder") or ""]
    elif kind == "video":
        bits = [base, x.get("stage") or "", ("due " + x["target_date"]) if x.get("target_date") else ""]
    else:
        bits = [base]
    return " · ".join(b for b in bits if b)


def _chip(kind: str, x: dict) -> str:
    """The kind chip: doc | paper | book | video | sheet | project."""
    if kind == "paper":
        return x.get("kind") or "paper"
    return {"writing": "writing"}.get(kind, kind)


@router.get("/attach/search")
async def search(q: str = "", kind: str = "", project_id: str = "", limit: int = 40) -> list[dict]:
    """Search everything attachable. `kind` narrows to one; blank searches all."""
    kinds = [kind] if kind in KINDS else list(KINDS)
    attached = set()
    if project_id:
        rows = await run_read("MATCH (x)-[:PART_OF]->(:Project {id: $id}) RETURN x.id AS id", id=project_id)
        attached = {r["id"] for r in rows}
    per_kind: list[list[dict]] = []
    for k in kinds:
        label, prop, _ = KINDS[k]
        rows = await run_read(
            f"MATCH (x:{label}) WHERE x.{prop} IS NOT NULL "
            f"AND ($q = '' OR toLower(x.{prop}) CONTAINS toLower($q)) "
            f"AND NOT (x:Task) RETURN x{{.*}} AS x ORDER BY coalesce(x.updated_at, x.added_at, x.created_at, '') DESC LIMIT $lim",
            q=q.strip(), lim=max(1, min(limit, 100)))
        per_kind.append([
            {"kind": k, "id": r["x"]["id"], "title": r["x"].get(prop) or "",
             "chip": _chip(k, r["x"]), "where": _where(k, r["x"]),
             "attached": r["x"]["id"] in attached}
            for r in rows if not (k == "project" and r["x"]["id"] == project_id)])
    # round-robin across kinds, so "all" shows some of each rather than
    # filling the list with whichever kind was queried first
    out: list[dict] = []
    for i in range(max((len(x) for x in per_kind), default=0)):
        out.extend(x[i] for x in per_kind if i < len(x))
    return out[: max(1, min(limit, 100))]


# =========================================================================== #
# ATTACHMENTS
# =========================================================================== #
# =========================================================================== #
# LENSES: Repository, Docs and Vision read the tree from the node's side
# =========================================================================== #
async def _memberships(ids: list[str] | None = None) -> dict[str, list[dict]]:
    """node id → the projects it sits in: attached directly (PART_OF), or as a
    source of a doc that is attached (via = that doc's title)."""
    rows = await run_read(
        """
        MATCH (x)-[:PART_OF]->(p:Project) WHERE $ids IS NULL OR x.id IN $ids
        RETURN x.id AS id, p.id AS pid, p.name AS name, null AS via
        UNION
        MATCH (x)-[:SOURCE_OF]->(d:Document)-[:PART_OF]->(p:Project)
        WHERE $ids IS NULL OR x.id IN $ids
        RETURN x.id AS id, p.id AS pid, p.name AS name, d.title AS via
        """, ids=ids)
    out: dict[str, list[dict]] = {}
    for r in rows:
        lst = out.setdefault(r["id"], [])
        if not any(m["id"] == r["pid"] and not m.get("via") for m in lst):
            lst.append({"id": r["pid"], "name": r["name"], "via": r["via"]})
    for lst in out.values():                # a direct attachment beats a via
        direct = {m["id"] for m in lst if not m["via"]}
        lst[:] = [m for m in lst if not m["via"] or m["id"] not in direct]
    return out


@router.get("/attach/membership")
async def membership(kind: str = "paper") -> dict:
    """Every node of one kind: its hours (hours.py) and the projects it is in.
    The Repository cards read this, so a card and its project agree."""
    if kind not in KINDS:
        raise HTTPException(400, "unknown kind")
    label = KINDS[kind][0]
    ids = [r["id"] for r in await run_read(f"MATCH (x:{label}) RETURN x.id AS id")]
    idx = await hours_index()
    mem = await _memberships(ids)
    return {i: {**idx.of(i), "projects": mem.get(i, [])} for i in ids}


@router.get("/attach/of/{node_id}")
async def attach_of(node_id: str) -> dict:
    """One node from its own side: hours, the projects it is in, and (for a
    doc) the sources it is built on."""
    rows = await run_read("MATCH (x {id: $id}) RETURN labels(x) AS labels", id=node_id)
    if not rows:
        raise HTTPException(404, "not found")
    idx = await hours_index()
    src = await run_read(
        "MATCH (s)-[r:SOURCE_OF]->(:Document {id: $id}) RETURN s{.*} AS s, labels(s) AS labels, r.date AS date "
        "ORDER BY r.date", id=node_id)
    sources = []
    for r in src:
        k = next((LABEL_KIND[l] for l in r["labels"] if l in LABEL_KIND), None)
        if k:
            h = idx.of(r["s"]["id"])
            sources.append({"kind": k, "id": r["s"]["id"], "title": r["s"].get(KINDS[k][1]) or "",
                            "chip": _chip(k, r["s"]), "where": _where(k, r["s"]), **h})
    return {**idx.of(node_id), "projects": (await _memberships([node_id])).get(node_id, []),
            "sources": sources}


async def attachment_items(project_id: str, idx) -> list[dict]:
    """A project's direct attachments, each with its sources, hours from `idx`.
    The project page passes the all-time index; a phase passes one windowed to
    its own dates, so the same rows read "hours in this phase"."""
    rows = await run_read(
        """
        MATCH (x)-[r:PART_OF]->(:Project {id: $id})
        OPTIONAL MATCH (s)-[sr:SOURCE_OF]->(x) WHERE x:Document
        WITH x, r, collect(CASE WHEN s IS NULL THEN NULL
                                ELSE {node: s{.*}, label: labels(s)[0], date: sr.date} END) AS sources
        RETURN x{.*} AS x, labels(x) AS labels, r.date AS date, sources
        ORDER BY r.date, coalesce(x.title, x.name)
        """, id=project_id)

    def shape(x: dict, labels: list[str], when: str | None) -> dict | None:
        kind = next((LABEL_KIND[l] for l in labels if l in LABEL_KIND), None)
        if not kind:
            return None
        h = idx.of(x["id"])
        return {"kind": kind, "id": x["id"], "title": x.get(KINDS[kind][1]) or "",
                "chip": _chip(kind, x), "where": _where(kind, x), "date": when or "",
                "mins": h["mins"], "sessions": h["sessions"]}

    items = []
    for r in rows:
        it = shape(r["x"], r["labels"], r["date"])
        if not it:
            continue
        it["sources"] = [s for s in (shape(src["node"], [src["label"]], src["date"])
                                     for src in r["sources"] if src) if s]
        items.append(it)
    return items


@router.get("/projects/{project_id}/attachments")
async def attachments(project_id: str) -> dict:
    proj = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name", id=project_id)
    if not proj:
        raise HTTPException(404, "no such project")
    idx = await hours_index()
    items = await attachment_items(project_id, idx)
    docs = [{"id": it["id"], "title": it["title"]} for it in items if it["kind"] == "doc"]
    total = idx.of(project_id)
    return {"project_id": project_id, "name": proj[0]["name"], "mins": total["mins"],
            "sessions": total["sessions"], "items": items, "docs": docs}


async def _node(kind: str, nid: str) -> dict:
    label, prop, _ = KINDS[kind]
    rows = await run_read(f"MATCH (x:{label} {{id: $id}}) RETURN x.{prop} AS title", id=nid)
    if not rows:
        raise HTTPException(404, f"no {kind} with that id")
    return {"title": rows[0]["title"] or ""}


@router.post("/projects/{project_id}/attach", status_code=201)
async def attach(project_id: str, body: ProjectAttach) -> dict:
    proj = await run_read("MATCH (p:Project {id: $id}) RETURN p.name AS name", id=project_id)
    if not proj:
        raise HTTPException(404, "no such project")
    if not body.part_of and not body.source_of:
        raise HTTPException(400, "tick part of the project, or pick a doc it is a source of")
    x = await _node(body.kind, body.id)
    label = KINDS[body.kind][0]
    today = date.today().isoformat()

    if body.kind == "project":
        if body.id == project_id:
            raise HTTPException(400, "a project can't be part of itself")
        # attaching an ancestor underneath would make the roll-up circular
        idx = await hours_index()
        if project_id in idx.under(body.id):
            raise HTTPException(400, "that project already contains this one")

    if body.part_of:
        await run_write(
            f"MATCH (x:{label} {{id: $xid}}), (p:Project {{id: $pid}}) "
            "MERGE (x)-[r:PART_OF]->(p) ON CREATE SET r.date = $today",
            xid=body.id, pid=project_id, today=today)
        await _hop_why(body.id, "PART_OF", project_id, body.why)
        await _write_move(f'{body.kind} "{x["title"]}"', "PART_OF", f"project {proj[0]['name']}", body.why)

    if body.source_of:
        doc = await run_read(
            "MATCH (d:Document {id: $did})-[:PART_OF]->(:Project {id: $pid}) RETURN d.title AS t",
            did=body.source_of, pid=project_id)
        if not doc:
            raise HTTPException(400, "that doc isn't part of this project")
        if body.source_of == body.id:
            raise HTTPException(400, "a doc can't be its own source")
        await run_write(
            f"MATCH (x:{label} {{id: $xid}}), (d:Document {{id: $did}}) "
            "MERGE (x)-[r:SOURCE_OF]->(d) ON CREATE SET r.date = $today",
            xid=body.id, did=body.source_of, today=today)
        if not body.part_of:
            await _hop_why(body.id, "SOURCE_OF", body.source_of, body.why)
        await _write_move(f'{body.kind} "{x["title"]}"', "SOURCE_OF", f'doc "{doc[0]["t"]}"', "")

    return await attachments(project_id)


@router.delete("/projects/{project_id}/attachments/{node_id}")
async def detach(project_id: str, node_id: str) -> dict:
    """Removes PART_OF only. The node, and any SOURCE_OF it has, stay."""
    rows = await run_write(
        """
        MATCH (x {id: $xid})-[r:PART_OF]->(p:Project {id: $pid})
        DELETE r RETURN coalesce(x.title, x.name) AS t, p.name AS p
        """, xid=node_id, pid=project_id)
    if not rows:
        raise HTTPException(404, "not attached to this project")
    await _write_move(f'"{rows[0]["t"]}"', "PART_OF removed", f"project {rows[0]['p']}", "")
    return await attachments(project_id)
