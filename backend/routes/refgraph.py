"""/api/synapse/refgraph — the Reference Map: a global citation graph.

Nodes = every repo Paper + every stored Reference + manual RefNodes.
Edges = (:Paper)-[:REFERENCES]->(:Reference)  (a paper cites this work)
        (:Paper)-[:CITES]->(:Paper)           (repo-to-repo citation)
        (a)-[:REF_LINK {label}]->(b)           (manual, between any two nodes)

**Storage keeps one :Reference per paper** — that's what lets each paper hold its
own read-state for the same cited work, and it is not changed here. The merging
below happens only while building this payload: works cited by several papers
collapse into a single node with an edge to each citing paper, so the shared
ground between clusters is visible instead of being duplicated into invisibility.
A reference that resolves to a paper you actually hold gets no leaf at all — the
edge goes straight to the real paper.

A reference starred in the Workspace ships `starred` + `note` on its edge, which
is what the map draws yellow: the star belongs to the (citing paper, cited work)
pair rather than to the work, so "read this after" stays attached to the paper
that made you want to read it.

The heavy lifting (layout, zoom/pan) is client-side; this route just serves the
payload and handles manual node/edge CRUD. Structured reference add + PDF scan
already live in routes/refs.py and are reused unchanged.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import RefEdgeCreate, RefNodeCreate

router = APIRouter(prefix="/api/synapse/refgraph", tags=["refgraph"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(title: str) -> str:
    """Title → comparison key. Punctuation and case vary between bibliographies
    for the same work, so neither can be allowed to split it into two nodes."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


@router.get("")
async def get_graph() -> dict:
    """The whole reference graph in one payload (nodes + edges)."""
    papers = await run_read(
        "MATCH (p:Paper) RETURN p.id AS id, p.title AS label, p.year AS year, "
        "coalesce(p.kind, 'paper') AS kind"
    )
    references = await run_read(
        "MATCH (r:Reference) "
        "RETURN r.id AS id, r.title AS label, r.link AS link, r.year AS year, "
        "r.paper_id AS paper_id, r.matched_paper_id AS matched_paper_id, "
        "coalesce(r.starred, false) AS starred, r.note AS note"
    )
    manual = await run_read(
        "MATCH (n:RefNode) RETURN n.id AS id, n.label AS label, n.type AS type"
    )
    paper_ids = {p["id"] for p in papers}
    paper_by_title = {_norm(p["label"]): p["id"] for p in papers}

    ref_nodes: dict[str, dict] = {}
    ref_edges: list[dict] = []
    # A reference that resolved to a paper you own has no leaf of its own, so
    # its star and note have to land on the real paper instead — otherwise
    # marking a work you already hold would draw a yellow edge to a node that
    # can't tell you why.
    paper_marks: dict[str, dict] = {}
    resolved = 0
    for r in references:
        key = _norm(r["label"])
        src = r.get("paper_id")
        if not key or not src:
            continue
        # A reference that IS a paper in the repo shouldn't be a leaf saying so —
        # point the edge at the real paper and let the two clusters touch.
        # A star lives on the (citing paper → cited work) pair, which is exactly
        # what an edge is — so it rides on the edge, not the merged node. A work
        # you starred from one paper stays unstarred from another.
        mark = {"ref_id": r["id"], "starred": bool(r.get("starred")), "note": r.get("note")}
        hit = r.get("matched_paper_id") or paper_by_title.get(key)
        if hit and hit in paper_ids and hit != src:
            ref_edges.append({"source": src, "target": hit, "kind": "cites", **mark})
            if mark["starred"] or mark["note"]:
                m = paper_marks.setdefault(hit, {"starred": False, "notes": []})
                m["starred"] = m["starred"] or mark["starred"]
                if mark["note"]:
                    m["notes"].append({"paper_id": src, "note": mark["note"]})
            resolved += 1
            continue
        node = ref_nodes.get(key)
        if node is None:
            node = ref_nodes[key] = {
                # Synthetic but stable: the same work yields the same id across
                # reloads, so saved node positions survive.
                "id": "ref:" + key, "label": r["label"], "type": "reference",
                "link": r.get("link"), "year": r.get("year"),
                "paper_ids": [], "ref_ids": [], "starred": False, "notes": [],
            }
        if src not in node["paper_ids"]:
            node["paper_ids"].append(src)
            ref_edges.append({"source": src, "target": node["id"], "kind": "references", **mark})
        node["ref_ids"].append(r["id"])
        # The node is starred if any paper starred it — that's what makes it
        # findable when the map is zoomed out past edge colour.
        node["starred"] = node["starred"] or mark["starred"]
        if mark["note"]:
            node["notes"].append({"paper_id": src, "note": mark["note"]})
        # Keep the first link/year we see — any is as good as any other, and a
        # later blank must not wipe one we already have.
        node["link"] = node["link"] or r.get("link")
        node["year"] = node["year"] or r.get("year")

    for node in ref_nodes.values():
        node["shared"] = len(node["paper_ids"]) > 1
        node["paper_id"] = node["paper_ids"][0]   # where it's parked at layout time

    shared = sum(1 for n in ref_nodes.values() if n["shared"])
    starred = sum(1 for e in ref_edges if e.get("starred"))

    nodes = (
        # `type` stays "paper" — it's what the renderer keys layout and edges on
        # — while `kind` carries book / video / course so a source can be drawn
        # as what it actually is.
        [{"id": p["id"], "label": p["label"], "type": "paper", "year": p.get("year"),
          "kind": p.get("kind") or "paper",
          **paper_marks.get(p["id"], {"starred": False, "notes": []})} for p in papers]
        + list(ref_nodes.values())
        + [{"id": m["id"], "label": m["label"], "type": "manual", "kind": m.get("type")} for m in manual]
    )

    cites_edges = await run_read(
        "MATCH (a:Paper)-[:CITES]->(b:Paper) RETURN a.id AS source, b.id AS target"
    )
    manual_edges = await run_read(
        "MATCH (a)-[l:REF_LINK]->(b) "
        "RETURN l.id AS id, a.id AS source, b.id AS target, l.label AS label"
    )
    edges = (
        ref_edges
        + [{"source": e["source"], "target": e["target"], "kind": "cites"} for e in cites_edges]
        + [
            {"id": e["id"], "source": e["source"], "target": e["target"], "kind": "manual", "label": e.get("label")}
            for e in manual_edges
        ]
    )
    # de-dupe edges: the same pair can arrive from both a resolved reference and
    # a real :CITES relationship
    seen: set = set()
    deduped = []
    for e in edges:
        k = (e["source"], e["target"], e["kind"], e.get("id"))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(e)
    edges = deduped

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {"papers": len(papers), "references": len(ref_nodes),
                   "reference_rows": len(references), "shared": shared,
                   "resolved_to_papers": resolved, "starred": starred,
                   "manual": len(manual), "edges": len(edges)},
    }


@router.post("/nodes", status_code=201)
async def create_node(body: RefNodeCreate) -> dict:
    nid = str(uuid.uuid4())
    rows = await run_write(
        "CREATE (n:RefNode {id: $id, label: $label, type: $type, created_at: $now}) RETURN n",
        id=nid, label=body.label.strip(), type=body.type, now=_now(),
    )
    await record("ref", "map node added", detail=body.label[:70])
    return dict(rows[0]["n"])


@router.delete("/nodes/{node_id}", status_code=204, response_class=Response)
async def delete_node(node_id: str) -> Response:
    await run_write("MATCH (n:RefNode {id: $id}) DETACH DELETE n", id=node_id)
    await record("ref", "map node removed", detail=node_id)
    return Response(status_code=204)


@router.post("/edges", status_code=201)
async def create_edge(body: RefEdgeCreate) -> dict:
    if body.source_id == body.target_id:
        raise HTTPException(400, "a node cannot link to itself")
    eid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (a) WHERE a.id = $s
        MATCH (b) WHERE b.id = $t
        CREATE (a)-[l:REF_LINK {id: $id, label: $label}]->(b)
        RETURN l.id AS id, a.id AS source, b.id AS target, l.label AS label
        """,
        s=body.source_id, t=body.target_id, id=eid, label=body.label,
    )
    if not rows:
        raise HTTPException(404, "source or target node not found")
    await record("ref", "map edge added", detail=f"{body.label}")
    return dict(rows[0])


@router.delete("/edges/{edge_id}", status_code=204, response_class=Response)
async def delete_edge(edge_id: str) -> Response:
    await run_write("MATCH ()-[l:REF_LINK {id: $id}]-() DELETE l", id=edge_id)
    await record("ref", "map edge removed", detail=edge_id)
    return Response(status_code=204)
