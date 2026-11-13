"""/api/decomposition — break complex things into hierarchies of simpler things.

A Synapse module. Educational, not verificational: code stored on a node is
CONTENT, exactly like prose. It is written, read and displayed. It is never
compiled, executed or checked. There is deliberately no test runner, no
assertions, no status/PASS/FAIL field, and no notion of a breakdown being
"correct" — correctness lives in the user's separate code repository.

Two structural facts drive most of the code below:

  * The graph is a DAG, not a tree. A node may have several parents, and the
    same child may appear under two different parents. Nothing here may assume
    a tree — traversal, depth and markdown all guard against revisiting.
  * Depth is never stored. It is computed as path length from whichever node is
    being viewed as the top, which is what lets a layer be inserted anywhere
    without migrating anything.

Snapshots and architectures are frozen copies held as opaque JSON payloads on a
single node rather than as graph structure. If they were real :Op nodes, editing
a live node could reach in and mutate them — and freezing is the entire point.

Mounted at /api/decomposition rather than the spec's /decomposition: the app
serves its frontend from / with a catch-all, so every API in this codebase
lives under /api.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from activity import record
from db import run_read, run_write

router = APIRouter(prefix="/api/decomposition", tags=["decomposition"])

MAX_DEPTH = 25
DEFAULT_VIEW = "main"


# --------------------------------------------------------------------------- #
# Models — the spec deliberately does not enumerate tags or languages beyond a
# hint, so `tag` is free text and `lang` is validated loosely.
# --------------------------------------------------------------------------- #
class CodeBlockIn(BaseModel):
    lang: str = "other"
    path: str = ""
    code: str = ""


class NodeIn(BaseModel):
    id: Optional[str] = None
    label: str = ""
    tag: str = ""
    summary: str = ""
    notes: str = ""
    ref: str = ""
    blocks: list[CodeBlockIn] = []
    views: dict[str, list[str]] = {}


class NodePatch(BaseModel):
    label: Optional[str] = None
    tag: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    ref: Optional[str] = None


class ChildIn(BaseModel):
    view: str = DEFAULT_VIEW
    child_id: str
    index: Optional[int] = None


class ViewIn(BaseModel):
    name: str


class CaptureIn(BaseModel):
    root: str
    name: str = ""


class ArchPatch(BaseModel):
    name: Optional[str] = None
    root: Optional[str] = None      # re-capture from a different root


class InsertIn(BaseModel):
    prefix: str = ""


class MeansIn(BaseModel):
    term_id: str


class SourceIn(BaseModel):
    node_id: str                     # elementId of any Mainframe node


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    """lowercase, non-alphanumeric → _, strip leading/trailing _. Empty → error."""
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    if not s:
        raise HTTPException(400, "id slugifies to nothing — give it letters or digits")
    return s


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
async def _blocks(op_id: str) -> list[dict]:
    rows = await run_read(
        "MATCH (:Op {id: $id})-[r:HAS_CODE]->(b:CodeBlock) "
        "RETURN b{.*} AS b, r.order AS o ORDER BY r.order",
        id=op_id,
    )
    return [r["b"] for r in rows]


async def _views(op_id: str) -> dict[str, list[str]]:
    rows = await run_read(
        "MATCH (:Op {id: $id})-[r:BREAKS_INTO]->(c:Op) "
        "RETURN r.view AS view, c.id AS child, r.order AS o ORDER BY r.view, r.order",
        id=op_id,
    )
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["view"] or DEFAULT_VIEW, []).append(r["child"])
    # a node always has at least `main`, even when nothing hangs off it yet
    named = await run_read("MATCH (o:Op {id: $id}) RETURN coalesce(o.view_names, []) AS v", id=op_id)
    for v in (named[0]["v"] if named else []):
        out.setdefault(v, [])
    out.setdefault(DEFAULT_VIEW, [])
    return out


async def _node(op_id: str, with_children: bool = True) -> dict:
    rows = await run_read("MATCH (o:Op {id: $id}) RETURN o{.*} AS o", id=op_id)
    if not rows:
        raise HTTPException(404, f"node '{op_id}' not found")
    node = rows[0]["o"]
    node.pop("view_names", None)
    node["blocks"] = await _blocks(op_id)
    node["views"] = await _views(op_id)
    if with_children:
        kids = {c for ids in node["views"].values() for c in ids}
        if kids:
            crows = await run_read(
                "MATCH (o:Op) WHERE o.id IN $ids RETURN o{.id, .label, .tag, .summary} AS o",
                ids=sorted(kids),
            )
            node["children"] = {r["o"]["id"]: r["o"] for r in crows}
        else:
            node["children"] = {}
    return node


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
async def _ensure_stub(op_id: str, label: str = "") -> None:
    """A child id that doesn't exist yet becomes an empty node.

    This is the primary authoring flow — the user types a name that isn't in the
    graph and expects a stub to appear.
    """
    await run_write(
        """
        MERGE (o:Op {id: $id})
          ON CREATE SET o.label = $label, o.tag = '', o.summary = '', o.notes = '',
                        o.ref = '', o.view_names = [$main],
                        o.created_at = $now, o.updated_at = $now
        """,
        id=op_id, label=label or op_id, main=DEFAULT_VIEW, now=_now(),
    )


@router.post("/nodes", status_code=201)
async def create_node(body: NodeIn) -> dict:
    op_id = slugify(body.id or body.label)
    now = _now()
    await run_write(
        """
        MERGE (o:Op {id: $id})
          ON CREATE SET o.created_at = $now
        SET o.label = $label, o.tag = $tag, o.summary = $summary,
            o.notes = $notes, o.ref = $ref, o.updated_at = $now,
            o.view_names = $views
        """,
        id=op_id, label=body.label or op_id, tag=body.tag, summary=body.summary,
        notes=body.notes, ref=body.ref, now=now,
        views=sorted({DEFAULT_VIEW, *body.views.keys()}),
    )
    for i, b in enumerate(body.blocks):
        await _add_block(op_id, b, i)
    for view, children in body.views.items():
        for order, cid in enumerate(children):
            child = slugify(cid)
            await _ensure_stub(child)
            await _link(op_id, child, view, order)
    await record("kg", "decomposition node created", detail=op_id)
    return await _node(op_id)


@router.get("/nodes")
async def list_nodes(tag: Optional[str] = None, q: Optional[str] = None) -> list[dict]:
    where, params = [], {}
    if tag:
        where.append("o.tag = $tag"); params["tag"] = tag
    if q:
        where.append("(toLower(o.label) CONTAINS toLower($q) "
                     "OR toLower(coalesce(o.summary,'')) CONTAINS toLower($q) "
                     "OR toLower(coalesce(o.notes,'')) CONTAINS toLower($q))")
        params["q"] = q
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await run_read(
        f"""
        MATCH (o:Op) {clause}
        OPTIONAL MATCH (o)-[:BREAKS_INTO]->(c:Op)
        OPTIONAL MATCH (p:Op)-[:BREAKS_INTO]->(o)
        RETURN o{{.id, .label, .tag, .summary, .ref}} AS o,
               count(DISTINCT c) AS children, count(DISTINCT p) AS parents
        ORDER BY o.label
        """,
        **params,
    )
    return [{**r["o"], "children": r["children"], "parents": r["parents"]} for r in rows]


@router.get("/tops")
async def tops() -> list[dict]:
    """Nodes nothing breaks into — the natural entry points."""
    rows = await run_read(
        """
        MATCH (o:Op) WHERE NOT (:Op)-[:BREAKS_INTO]->(o)
        OPTIONAL MATCH (o)-[:BREAKS_INTO]->(c:Op)
        RETURN o{.id, .label, .tag, .summary} AS o, count(DISTINCT c) AS children
        ORDER BY o.label
        """
    )
    return [{**r["o"], "children": r["children"]} for r in rows]


@router.get("/nodes/{op_id}")
async def get_node(op_id: str) -> dict:
    return await _node(op_id)


@router.patch("/nodes/{op_id}")
async def patch_node(op_id: str, patch: NodePatch) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if fields:
        sets = ", ".join(f"o.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (o:Op {{id: $id}}) SET {sets}, o.updated_at = $now RETURN o",
            id=op_id, now=_now(), **fields,
        )
        if not rows:
            raise HTTPException(404, f"node '{op_id}' not found")
        await record("kg", "decomposition node updated", detail=f"{op_id}: {', '.join(fields)}")
    return await _node(op_id)


@router.delete("/nodes/{op_id}", status_code=204, response_class=Response)
async def delete_node(op_id: str) -> Response:
    """Delete the node, every edge pointing at it in every view, and its blocks.

    Nothing cascades — children are shared by design and are left alone.
    """
    await run_write(
        """
        MATCH (o:Op {id: $id})
        OPTIONAL MATCH (o)-[:HAS_CODE]->(b:CodeBlock)
        DETACH DELETE b, o
        """,
        id=op_id,
    )
    await record("kg", "decomposition node deleted", detail=op_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #
async def _link(parent: str, child: str, view: str, order: Optional[int] = None) -> None:
    if order is None:
        rows = await run_read(
            "MATCH (:Op {id: $p})-[r:BREAKS_INTO {view: $v}]->() "
            "RETURN coalesce(max(r.order), -1) AS last",
            p=parent, v=view,
        )
        last = rows[0]["last"] if rows else None
        # explicit None check — `0 or -1` is -1 in Python, which would
        # silently collapse every order back to 0
        order = (int(last) if last is not None else -1) + 1
    await run_write(
        """
        MATCH (p:Op {id: $p}), (c:Op {id: $c})
        MERGE (p)-[r:BREAKS_INTO {view: $v}]->(c)
        SET r.order = $o
        WITH p
        SET p.view_names = CASE WHEN $v IN coalesce(p.view_names, [])
                                THEN p.view_names ELSE coalesce(p.view_names, []) + $v END
        """,
        p=parent, c=child, v=view, o=order,
    )


@router.post("/nodes/{op_id}/children", status_code=201)
async def add_child(op_id: str, body: ChildIn) -> dict:
    await _node(op_id, with_children=False)      # 404 if the parent is missing
    child = slugify(body.child_id)
    await _ensure_stub(child)                    # typing a new name creates a stub
    if child == op_id:
        raise HTTPException(400, "a node cannot break into itself")
    await _link(op_id, child, body.view or DEFAULT_VIEW, body.index)
    await record("kg", "decomposition child added", detail=f"{op_id} → {child}")
    return await _node(op_id)


@router.delete("/nodes/{op_id}/children/{child_id}")
async def remove_child(op_id: str, child_id: str, view: str = DEFAULT_VIEW) -> dict:
    await run_write(
        "MATCH (:Op {id: $p})-[r:BREAKS_INTO {view: $v}]->(:Op {id: $c}) DELETE r",
        p=op_id, c=child_id, v=view,
    )
    return await _node(op_id)


@router.post("/nodes/{op_id}/views", status_code=201)
async def add_view(op_id: str, body: ViewIn) -> dict:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "a view needs a name")
    rows = await run_write(
        """
        MATCH (o:Op {id: $id})
        SET o.view_names = CASE WHEN $v IN coalesce(o.view_names, [])
                                THEN o.view_names ELSE coalesce(o.view_names, []) + $v END
        RETURN o
        """,
        id=op_id, v=name,
    )
    if not rows:
        raise HTTPException(404, f"node '{op_id}' not found")
    return await _node(op_id)


@router.delete("/nodes/{op_id}/views/{view}")
async def delete_view(op_id: str, view: str) -> dict:
    if view == DEFAULT_VIEW:
        raise HTTPException(400, "the main view cannot be removed")
    await run_write(
        """
        MATCH (o:Op {id: $id})
        OPTIONAL MATCH (o)-[r:BREAKS_INTO {view: $v}]->()
        DELETE r
        WITH o
        SET o.view_names = [x IN coalesce(o.view_names, []) WHERE x <> $v]
        """,
        id=op_id, v=view,
    )
    return await _node(op_id)


@router.get("/tree/{op_id}")
async def tree(op_id: str, view: str = DEFAULT_VIEW) -> dict:
    """Subtree with a computed depth per node.

    Depth is path length from `op_id`, never stored. Because the graph is a DAG
    a node can be reached by several paths — the depth reported is the longest,
    matching `max(length(path))`. Traversal is capped and cycle-guarded.
    """
    await _node(op_id, with_children=False)
    depth: dict[str, int] = {op_id: 0}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    frontier = [op_id]
    for level in range(1, MAX_DEPTH + 1):
        if not frontier:
            break
        rows = await run_read(
            "MATCH (p:Op)-[r:BREAKS_INTO {view: $v}]->(c:Op) "
            "WHERE p.id IN $ids RETURN p.id AS p, c.id AS c, r.order AS o ORDER BY r.order",
            ids=frontier, v=view,
        )
        nxt: list[str] = []
        for r in rows:
            key = (r["p"], r["c"])
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"parent": r["p"], "child": r["c"], "order": r["o"]})
            # longest path wins, and a node is only re-expanded if it got deeper
            if depth.get(r["c"], -1) < level:
                depth[r["c"]] = level
                if r["c"] not in nxt:
                    nxt.append(r["c"])
        frontier = nxt
    rows = await run_read(
        "MATCH (o:Op) WHERE o.id IN $ids RETURN o{.id, .label, .tag, .summary, .ref} AS o",
        ids=sorted(depth),
    )
    nodes = [{**r["o"], "depth": depth[r["o"]["id"]]} for r in rows]
    nodes.sort(key=lambda n: (n["depth"], n["label"] or ""))
    return {"root": op_id, "view": view, "nodes": nodes, "edges": edges,
            "truncated_at": MAX_DEPTH if max(depth.values(), default=0) >= MAX_DEPTH else None}


# --------------------------------------------------------------------------- #
# Code blocks — content, never executed
# --------------------------------------------------------------------------- #
async def _add_block(op_id: str, b: CodeBlockIn, order: Optional[int] = None) -> None:
    if order is None:
        rows = await run_read(
            "MATCH (:Op {id: $id})-[r:HAS_CODE]->() RETURN coalesce(max(r.order), -1) AS last",
            id=op_id,
        )
        last = rows[0]["last"] if rows else None
        # explicit None check — `0 or -1` is -1 in Python, which would
        # silently collapse every order back to 0
        order = (int(last) if last is not None else -1) + 1
    await run_write(
        """
        MATCH (o:Op {id: $id})
        CREATE (o)-[:HAS_CODE {order: $order}]->(:CodeBlock {
            id: $bid, lang: $lang, path: $path, code: $code
        })
        """,
        id=op_id, bid=str(uuid.uuid4()), lang=b.lang, path=b.path, code=b.code, order=order,
    )


@router.post("/nodes/{op_id}/blocks", status_code=201)
async def add_block(op_id: str, body: CodeBlockIn) -> dict:
    await _node(op_id, with_children=False)
    await _add_block(op_id, body)
    return await _node(op_id)


@router.patch("/nodes/{op_id}/blocks/{index}")
async def patch_block(op_id: str, index: int, body: CodeBlockIn) -> dict:
    rows = await run_write(
        """
        MATCH (:Op {id: $id})-[r:HAS_CODE {order: $o}]->(b:CodeBlock)
        SET b.lang = $lang, b.path = $path, b.code = $code
        RETURN b
        """,
        id=op_id, o=index, lang=body.lang, path=body.path, code=body.code,
    )
    if not rows:
        raise HTTPException(404, "block not found")
    return await _node(op_id)


@router.delete("/nodes/{op_id}/blocks/{index}")
async def delete_block(op_id: str, index: int) -> dict:
    await run_write(
        "MATCH (:Op {id: $id})-[r:HAS_CODE {order: $o}]->(b:CodeBlock) DETACH DELETE b",
        id=op_id, o=index,
    )
    # close the gap so indexes stay contiguous
    rows = await run_read(
        "MATCH (:Op {id: $id})-[r:HAS_CODE]->(b:CodeBlock) RETURN b.id AS id ORDER BY r.order",
        id=op_id,
    )
    for i, r in enumerate(rows):
        await run_write(
            "MATCH (:Op {id: $id})-[r:HAS_CODE]->(b:CodeBlock {id: $bid}) SET r.order = $i",
            id=op_id, bid=r["id"], i=i,
        )
    return await _node(op_id)


# --------------------------------------------------------------------------- #
# Capture — the shared machinery behind snapshots and architectures
# --------------------------------------------------------------------------- #
async def _capture(root: str) -> dict[str, dict]:
    """Full copies of `root` and everything under it, across every view."""
    await _node(root, with_children=False)
    collected: dict[str, dict] = {}
    frontier = [root]
    for _ in range(MAX_DEPTH):
        todo = [i for i in frontier if i not in collected]
        if not todo:
            break
        nxt: list[str] = []
        for nid in todo:
            n = await _node(nid, with_children=False)
            collected[nid] = {
                "label": n.get("label", ""), "tag": n.get("tag", ""),
                "summary": n.get("summary", ""), "notes": n.get("notes", ""),
                "ref": n.get("ref", ""),
                "blocks": [{"lang": b.get("lang", "other"), "path": b.get("path", ""),
                            "code": b.get("code", "")} for b in n["blocks"]],
                "views": n["views"],
            }
            for ids in n["views"].values():
                nxt.extend(ids)
        frontier = nxt
    return collected


async def _materialise(payload: dict[str, dict], prefix: str) -> dict[str, str]:
    """Write frozen copies back as fresh live nodes under a prefix.

    Ids collide → append _2, _3, … The stored payload is never touched.
    """
    mapping: dict[str, str] = {}
    for old in payload:
        base = slugify(f"{prefix}_{old}") if prefix else slugify(old)
        cand, n = base, 1
        while True:
            exists = await run_read("MATCH (o:Op {id: $id}) RETURN o.id AS id", id=cand)
            if not exists:
                break
            n += 1
            cand = f"{base}_{n}"
        mapping[old] = cand
    now = _now()
    for old, data in payload.items():
        new = mapping[old]
        await run_write(
            """
            CREATE (o:Op {id: $id, label: $label, tag: $tag, summary: $summary,
                          notes: $notes, ref: $ref, view_names: $views,
                          created_at: $now, updated_at: $now})
            """,
            id=new, label=data.get("label", ""), tag=data.get("tag", ""),
            summary=data.get("summary", ""), notes=data.get("notes", ""),
            ref=data.get("ref", ""), now=now,
            views=sorted({DEFAULT_VIEW, *(data.get("views") or {}).keys()}),
        )
        for i, b in enumerate(data.get("blocks") or []):
            await _add_block(new, CodeBlockIn(**b), i)
    # rewrite internal edges to point at the copies
    for old, data in payload.items():
        for view, children in (data.get("views") or {}).items():
            for order, cid in enumerate(children):
                if cid in mapping:
                    await _link(mapping[old], mapping[cid], view, order)
    return mapping


# --------------------------------------------------------------------------- #
# Snapshots — dated records; editing live nodes must never change them
# --------------------------------------------------------------------------- #
@router.post("/snapshots", status_code=201)
async def create_snapshot(body: CaptureIn) -> dict:
    payload = await _capture(body.root)
    sid = str(uuid.uuid4())
    saved = datetime.now(timezone.utc).date().isoformat()
    await run_write(
        """
        CREATE (s:Snapshot {id: $id, name: $name, saved: $saved, root: $root,
                            payload: $payload, created_at: $now})
        """,
        id=sid, name=body.name or body.root, saved=saved, root=body.root,
        payload=json.dumps(payload), now=_now(),
    )
    await record("kg", "decomposition snapshot", detail=f"{body.name or body.root} ({len(payload)} nodes)")
    return {"id": sid, "name": body.name or body.root, "saved": saved,
            "root": body.root, "nodes": payload}


@router.get("/snapshots")
async def list_snapshots() -> list[dict]:
    rows = await run_read(
        "MATCH (s:Snapshot) RETURN s{.id, .name, .saved, .root, .payload} AS s ORDER BY s.saved DESC")
    out = []
    for r in rows:
        s = r["s"]
        s["node_count"] = len(json.loads(s.pop("payload") or "{}"))
        out.append(s)
    return out


async def _snapshot(sid: str) -> dict:
    rows = await run_read("MATCH (s:Snapshot {id: $id}) RETURN s{.*} AS s", id=sid)
    if not rows:
        raise HTTPException(404, "snapshot not found")
    s = rows[0]["s"]
    s["nodes"] = json.loads(s.pop("payload") or "{}")
    return s


@router.get("/snapshots/{sid}")
async def get_snapshot(sid: str) -> dict:
    return await _snapshot(sid)


@router.post("/snapshots/{sid}/restore", status_code=201)
async def restore_snapshot(sid: str, body: InsertIn) -> dict:
    snap = await _snapshot(sid)
    mapping = await _materialise(snap["nodes"], body.prefix)
    await record("kg", "snapshot restored", detail=f"{snap.get('name')} → {len(mapping)} nodes")
    return {"created": mapping, "root": mapping.get(snap["root"])}


@router.delete("/snapshots/{sid}", status_code=204, response_class=Response)
async def delete_snapshot(sid: str) -> Response:
    await run_write("MATCH (s:Snapshot {id: $id}) DETACH DELETE s", id=sid)
    return Response(status_code=204)


@router.get("/snapshots/{sid}/markdown", response_class=PlainTextResponse)
async def snapshot_markdown(sid: str) -> str:
    snap = await _snapshot(sid)
    return _render_markdown(snap)


def _render_markdown(snap: dict) -> str:
    nodes: dict[str, dict] = snap["nodes"]
    root = snap["root"]
    r = nodes.get(root, {})
    out: list[str] = [f"# {r.get('label', root)}", "", f"_snapshot {snap.get('saved', '')}_"]
    if r.get("tag"):
        out.append(f"tag: {r['tag']}")
    out += ["", r.get("summary", ""), "", "## Breakdown"]

    # the graph is a DAG — a node reached twice is marked, not re-expanded
    emitted: set[str] = set()

    def outline(nid: str, level: int) -> None:
        n = nodes.get(nid)
        if n is None:
            return
        pad = "  " * level
        if nid in emitted:
            out.append(f"{pad}- {n.get('label', nid)} ↩")
            return
        emitted.add(nid)
        out.append(f"{pad}- {n.get('label', nid)}")
        if level >= MAX_DEPTH:
            return
        for cid in (n.get("views") or {}).get(DEFAULT_VIEW, []):
            outline(cid, level + 1)

    outline(root, 0)
    out += ["", "## Nodes"]
    for nid, n in nodes.items():
        out += ["", f"### {n.get('label', nid)}"]
        if n.get("tag"):
            out.append(f"tag: {n['tag']}")
        if n.get("summary"):
            out += ["", n["summary"]]
        if n.get("notes"):
            out += ["", n["notes"]]
        if n.get("ref"):
            out += ["", f"ref: {n['ref']}"]
        for view, kids in (n.get("views") or {}).items():
            if kids:
                labels = [nodes.get(k, {}).get("label", k) for k in kids]
                out.append(f"{view}: {', '.join(labels)}")
        for b in n.get("blocks") or []:
            out.append("")
            if b.get("path"):
                out.append(f"`{b['path']}`")
            out.append("```" + (b.get("lang") or ""))
            out.append(b.get("code", ""))
            out.append("```")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Architectures — reusable shapes, stamped out with a prefix
# --------------------------------------------------------------------------- #
@router.post("/architectures", status_code=201)
async def create_architecture(body: CaptureIn) -> dict:
    payload = await _capture(body.root)
    aid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (a:Architecture {id: $id, name: $name, root: $root,
                                payload: $payload, created_at: $now})
        """,
        id=aid, name=body.name or body.root, root=body.root,
        payload=json.dumps(payload), now=_now(),
    )
    await record("kg", "architecture saved", detail=f"{body.name or body.root} ({len(payload)} nodes)")
    return {"id": aid, "name": body.name or body.root, "root": body.root, "nodes": payload}


@router.get("/architectures")
async def list_architectures() -> list[dict]:
    rows = await run_read("MATCH (a:Architecture) RETURN a{.id, .name, .root, .payload} AS a ORDER BY a.name")
    out = []
    for r in rows:
        a = r["a"]
        a["node_count"] = len(json.loads(a.pop("payload") or "{}"))
        out.append(a)
    return out


async def _architecture(aid: str) -> dict:
    rows = await run_read("MATCH (a:Architecture {id: $id}) RETURN a{.*} AS a", id=aid)
    if not rows:
        raise HTTPException(404, "architecture not found")
    a = rows[0]["a"]
    a["nodes"] = json.loads(a.pop("payload") or "{}")
    return a


@router.get("/architectures/{aid}")
async def get_architecture(aid: str) -> dict:
    return await _architecture(aid)


@router.patch("/architectures/{aid}")
async def patch_architecture(aid: str, body: ArchPatch) -> dict:
    await _architecture(aid)
    if body.root:                                   # re-capture from a new root
        payload = await _capture(body.root)
        await run_write(
            "MATCH (a:Architecture {id: $id}) SET a.root = $root, a.payload = $payload",
            id=aid, root=body.root, payload=json.dumps(payload),
        )
    if body.name:
        await run_write("MATCH (a:Architecture {id: $id}) SET a.name = $name", id=aid, name=body.name)
    return await _architecture(aid)


@router.post("/architectures/{aid}/insert", status_code=201)
async def insert_architecture(aid: str, body: InsertIn) -> dict:
    arch = await _architecture(aid)
    mapping = await _materialise(arch["nodes"], body.prefix)
    await record("kg", "architecture inserted", detail=f"{arch.get('name')} as '{body.prefix}'")
    return {"created": mapping, "root": mapping.get(arch["root"])}


@router.delete("/architectures/{aid}", status_code=204, response_class=Response)
async def delete_architecture(aid: str) -> Response:
    await run_write("MATCH (a:Architecture {id: $id}) DETACH DELETE a", id=aid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Seams into the rest of Mainframe — no duplication of what others own
# --------------------------------------------------------------------------- #
@router.post("/nodes/{op_id}/means", status_code=201)
async def link_term(op_id: str, body: MeansIn) -> dict:
    """This decomposition node is also a Dictionary term."""
    rows = await run_write(
        "MATCH (o:Op {id: $op}), (t:Term {id: $term}) MERGE (o)-[:MEANS]->(t) RETURN t.name AS name",
        op=op_id, term=body.term_id,
    )
    if not rows:
        raise HTTPException(404, "node or dictionary term not found")
    return {"op": op_id, "term": body.term_id, "name": rows[0]["name"]}


@router.post("/nodes/{op_id}/source", status_code=201)
async def link_source(op_id: str, body: SourceIn) -> dict:
    """This decomposition is rooted in something Synapse already tracks."""
    rows = await run_write(
        "MATCH (o:Op {id: $op}), (s) WHERE elementId(s) = $sid MERGE (o)-[:FROM_SOURCE]->(s) RETURN labels(s) AS l",
        op=op_id, sid=body.node_id,
    )
    if not rows:
        raise HTTPException(404, "node or source not found")
    return {"op": op_id, "source": body.node_id, "labels": rows[0]["l"]}


# --------------------------------------------------------------------------- #
# Transfer — the reference client's export shape, unchanged
# --------------------------------------------------------------------------- #
@router.get("/export")
async def export_all(tag: Optional[str] = None) -> dict:
    rows = await run_read(
        "MATCH (o:Op) " + ("WHERE o.tag = $tag " if tag else "") + "RETURN o.id AS id",
        **({"tag": tag} if tag else {}),
    )
    nodes: dict[str, dict] = {}
    for r in rows:
        n = await _node(r["id"], with_children=False)
        nodes[n["id"]] = {
            "label": n.get("label", ""), "tag": n.get("tag", ""),
            "summary": n.get("summary", ""), "notes": n.get("notes", ""),
            "ref": n.get("ref", ""),
            "blocks": [{"lang": b.get("lang", "other"), "path": b.get("path", ""),
                        "code": b.get("code", "")} for b in n["blocks"]],
            "views": n["views"],
        }
    snaps = {s["id"]: {"name": s["name"], "saved": s["saved"], "root": s["root"],
                       "nodes": s["nodes"]}
             for s in [await _snapshot(x["s"]["id"])
                       for x in await run_read("MATCH (s:Snapshot) RETURN s{.id} AS s")]}
    archs = {a["id"]: {"name": a["name"], "root": a["root"], "nodes": a["nodes"]}
             for a in [await _architecture(x["a"]["id"])
                       for x in await run_read("MATCH (a:Architecture) RETURN a{.id} AS a")]}
    return {"nodes": nodes, "snapshots": snaps, "architectures": archs}


@router.post("/import")
async def import_all(payload: dict[str, Any], merge: bool = True) -> dict:
    """Accepts the reference client's export shape unchanged.

    Merging (the default) leaves existing ids alone and adds new ones — this is
    how a decomposition authored elsewhere links into shared nodes already here.
    Any child id referenced but never defined becomes an empty stub.
    """
    nodes = payload.get("nodes") or {}
    if not merge:
        await run_write("MATCH (o:Op) OPTIONAL MATCH (o)-[:HAS_CODE]->(b:CodeBlock) DETACH DELETE b, o")
        await run_write("MATCH (s:Snapshot) DETACH DELETE s")
        await run_write("MATCH (a:Architecture) DETACH DELETE a")

    existing = {r["id"] for r in await run_read("MATCH (o:Op) RETURN o.id AS id")}
    added, skipped = 0, 0
    for nid, data in nodes.items():
        oid = slugify(nid)
        if merge and oid in existing:
            skipped += 1
            continue
        await run_write(
            """
            MERGE (o:Op {id: $id})
              ON CREATE SET o.created_at = $now
            SET o.label = $label, o.tag = $tag, o.summary = $summary, o.notes = $notes,
                o.ref = $ref, o.view_names = $views, o.updated_at = $now
            """,
            id=oid, label=data.get("label", oid), tag=data.get("tag", ""),
            summary=data.get("summary", ""), notes=data.get("notes", ""),
            ref=data.get("ref", ""), now=_now(),
            views=sorted({DEFAULT_VIEW, *(data.get("views") or {}).keys()}),
        )
        for i, b in enumerate(data.get("blocks") or []):
            await _add_block(oid, CodeBlockIn(**b), i)
        added += 1
    # edges last, so every target exists (stubbing anything still missing)
    for nid, data in nodes.items():
        oid = slugify(nid)
        for view, children in (data.get("views") or {}).items():
            for order, cid in enumerate(children):
                child = slugify(cid)
                await _ensure_stub(child)
                await _link(oid, child, view, order)

    for sid, s in (payload.get("snapshots") or {}).items():
        await run_write(
            """
            MERGE (s:Snapshot {id: $id})
            SET s.name = $name, s.saved = $saved, s.root = $root, s.payload = $payload
            """,
            id=sid, name=s.get("name", ""), saved=s.get("saved", ""),
            root=s.get("root", ""), payload=json.dumps(s.get("nodes") or {}),
        )
    for aid, a in (payload.get("architectures") or {}).items():
        await run_write(
            """
            MERGE (a:Architecture {id: $id})
            SET a.name = $name, a.root = $root, a.payload = $payload
            """,
            id=aid, name=a.get("name", ""), root=a.get("root", ""),
            payload=json.dumps(a.get("nodes") or {}),
        )
    await record("kg", "decomposition imported", detail=f"{added} added, {skipped} kept")
    return {"added": added, "kept": skipped,
            "snapshots": len(payload.get("snapshots") or {}),
            "architectures": len(payload.get("architectures") or {})}
