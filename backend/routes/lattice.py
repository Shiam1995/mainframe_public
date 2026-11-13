"""/api/synapse/lattice — persistence for the Lattice decomposition canvas.

The canvas itself (frontend/lattice.html) is a self-contained page whose
in-memory model is the spec: Concept {id, name, body, tags, sources, kids},
where kids entries are either "id" or ["id", times]. This router stores that
graph in Neo4j and hands it back verbatim, so the page's Export JSON, the
API payload and the graph stay interchangeable.

Storage: (:LatticeConcept)-[:LATTICE_PART {times, idx}]->(:LatticeConcept).
The label is prefixed because :Concept is already taken by the Synapse KG.
Sources ride along as a JSON string property — they're display data, never
queried. The current root lives on a (:LatticeMeta {key:'main'}) singleton.

Saves are whole-graph replaces: the page edits everything in memory and
autosaves the lot, so a full swap in one transaction is both the simplest
and the only write shape it needs.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from activity import record
from db import run_read, run_write

router = APIRouter(prefix="/api/synapse/lattice", tags=["lattice"])

MAX_CONCEPTS = 5000


class ConceptIn(BaseModel):
    id: str
    name: str = ""
    body: str = ""
    tags: list[str] = []
    sources: list[dict] = []
    # "child_id" or ["child_id", times] — the canvas's native shape.
    kids: list[Any] = []


class GraphIn(BaseModel):
    root: Optional[str] = None
    concepts: list[ConceptIn] = []


def _kid_pairs(kids: list[Any]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for k in kids:
        if isinstance(k, str):
            out.append((k, 1))
        elif isinstance(k, (list, tuple)) and len(k) == 2 and isinstance(k[0], str):
            try:
                out.append((k[0], max(1, int(k[1]))))
            except (TypeError, ValueError):
                out.append((k[0], 1))
    return out


@router.get("")
async def get_graph() -> dict:
    rows = await run_read(
        """
        MATCH (n:LatticeConcept)
        OPTIONAL MATCH (n)-[r:LATTICE_PART]->(k:LatticeConcept)
        WITH n, r, k ORDER BY n.seq, r.idx
        RETURN n.id AS id, n.name AS name, n.body AS body, n.tags AS tags,
               n.sources_json AS sources_json,
               collect(CASE WHEN k IS NULL THEN NULL
                            ELSE {id: k.id, times: r.times} END) AS kids
        """
    )
    concepts = []
    for row in rows:
        kids: list[Any] = []
        for k in row["kids"]:
            if k is None:
                continue
            times = k.get("times") or 1
            kids.append([k["id"], times] if times > 1 else k["id"])
        try:
            sources = json.loads(row["sources_json"] or "[]")
        except (TypeError, ValueError):
            sources = []
        concepts.append({
            "id": row["id"], "name": row["name"] or "", "body": row["body"] or "",
            "tags": row["tags"] or [], "sources": sources, "kids": kids,
        })
    meta = await run_read("MATCH (m:LatticeMeta {key:'main'}) RETURN m.root AS root")
    root = meta[0]["root"] if meta else None
    ids = {c["id"] for c in concepts}
    return {"root": root if root in ids else None, "concepts": concepts}


@router.put("")
async def put_graph(graph: GraphIn) -> dict:
    if len(graph.concepts) > MAX_CONCEPTS:
        raise HTTPException(413, f"more than {MAX_CONCEPTS} concepts")
    ids = [c.id for c in graph.concepts]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "duplicate concept ids")
    id_set = set(ids)

    nodes = [
        {
            "id": c.id, "name": c.name or "", "body": c.body or "",
            "tags": c.tags or [], "sources_json": json.dumps(c.sources or []),
            "seq": i,
        }
        for i, c in enumerate(graph.concepts)
    ]
    edges = [
        {"parent": c.id, "child": kid, "times": times, "idx": idx}
        for c in graph.concepts
        for idx, (kid, times) in enumerate(_kid_pairs(c.kids))
        if kid in id_set
    ]
    root = graph.root if graph.root in id_set else None

    # One transaction: swap the whole graph, then stamp the root.
    await run_write(
        """
        CALL { MATCH (old:LatticeConcept) DETACH DELETE old }
        CALL {
          UNWIND $nodes AS c
          CREATE (:LatticeConcept {id: c.id, name: c.name, body: c.body,
                                   tags: c.tags, sources_json: c.sources_json,
                                   seq: c.seq})
        }
        CALL {
          UNWIND $edges AS e
          MATCH (p:LatticeConcept {id: e.parent}), (k:LatticeConcept {id: e.child})
          CREATE (p)-[:LATTICE_PART {times: e.times, idx: e.idx}]->(k)
        }
        MERGE (m:LatticeMeta {key: 'main'})
        SET m.root = $root
        """,
        nodes=nodes, edges=edges, root=root,
    )
    await record("lattice", "saved",
                 f"{len(nodes)} concepts, {len(edges)} parts", trigger="manual")
    return {"ok": True, "concepts": len(nodes), "parts": len(edges)}
