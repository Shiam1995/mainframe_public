"""/api/synapse/kg — the triple-layer knowledge graph.

Layers (per node, `layer` property):
  - "manual"    — you build it
  - "auto"      — LLM-generated, FROZEN. Never edited directly.
  - "auto_edit" — a clone of an auto node that you CAN edit.

Auto nodes are generated once on demand (POST /generate) and locked. To change
one, clone it to auto_edit (POST /nodes/{id}/clone), then edit the clone. Every
edit/delete is logged with before/after. Edges are :RELATES relationships
carrying their own id so they can be deleted individually.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Response

import llm
import pdf
from activity import record
from db import run_read, run_write
from models import CypherQuery, KGEdgeCreate, KGNodeCreate, KGNodeUpdate

router = APIRouter(prefix="/api/synapse/kg", tags=["kg"])


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
@router.get("/papers")
async def paper_graph(shared_only: bool = True, projects: bool = True) -> dict:
    """How the papers in the library connect to each other — and to the work.

    Papers are the subject; most of what else is in here is connective tissue —
    the concepts, authors and citations that tie two papers together. With
    `shared_only` (the default) a bridge is drawn only when it touches at least
    two papers, which is what "how papers connect" means; turn it off to see
    every concept and author hanging off each paper.

    Four ways a paper-to-paper connection is established:
      CITES              one paper cites another directly
      REFERENCES→match   a stored reference resolved to a paper you own
      INTRODUCES         both papers introduce the same concept
      AUTHORED_BY        both papers share an author

    Projects are the exception to "everything else is a bridge": with
    `projects` on they are drawn as subjects too, alongside papers, because
    what you built is a first-class thing to have read towards. Three ways one
    joins the graph:
      ABOUT              a paper, or a project, points at the other by reference
      HAS_PASS→ABOUT     one pass of a project was worked against a paper
      HAS_IDEA           an idea attached to a project — a bridge when a paper
                         (or another project) holds the same idea
    """
    papers = await run_read(
        "MATCH (p:Paper) RETURN p.id AS id, p.title AS title, p.year AS year, "
        "coalesce(p.status, 'unread') AS status, p.understanding AS understanding "
        "ORDER BY p.title"
    )
    nodes = [{"id": p["id"], "label": "Paper", "name": p["title"], "year": p["year"],
              "status": p["status"], "understanding": p["understanding"]}
             for p in papers]
    paper_ids = {p["id"] for p in papers}
    edges: list[dict] = []

    # 1. direct citations
    for r in await run_read("MATCH (a:Paper)-[:CITES]->(b:Paper) RETURN a.id AS s, b.id AS t"):
        edges.append({"source": r["s"], "target": r["t"], "type": "cites"})

    # 2. a stored reference that resolved to a paper in the library
    for r in await run_read(
        """
        MATCH (a:Paper)-[:REFERENCES]->(x:Reference)
        WHERE x.matched_paper_id IS NOT NULL AND x.matched_paper_id <> a.id
        RETURN DISTINCT a.id AS s, x.matched_paper_id AS t
        """
    ):
        if r["t"] in paper_ids:
            edges.append({"source": r["s"], "target": r["t"], "type": "cites (reference)"})

    # 3. bridges: concepts and authors, plus KG node names shared across papers
    async def bridge(cypher: str, label: str, rel: str) -> None:
        for row in await run_read(cypher):
            pids = [x for x in row["papers"] if x in paper_ids]
            if shared_only and len(pids) < 2:
                continue
            if not pids:
                continue
            bid = label + ":" + row["name"]
            nodes.append({"id": bid, "label": label, "name": row["name"], "shared": len(pids)})
            for pid in pids:
                edges.append({"source": pid, "target": bid, "type": rel})

    await bridge(
        "MATCH (p:Paper)-[:INTRODUCES]->(c:Concept) "
        "RETURN c.name AS name, collect(DISTINCT p.id) AS papers",
        "Concept", "introduces")
    await bridge(
        "MATCH (p:Paper)-[:AUTHORED_BY]->(a:Author) "
        "RETURN a.name AS name, collect(DISTINCT p.id) AS papers",
        "Author", "authored by")
    await bridge(
        "MATCH (n:KGNode) WHERE n.name IS NOT NULL AND n.paper_id IS NOT NULL "
        "RETURN n.name AS name, collect(DISTINCT n.paper_id) AS papers",
        "Topic", "on the graph of")

    # 4. the work itself: projects as subjects, not bridges
    project_ids: set[str] = set()
    if projects:
        for r in await run_read(
            "MATCH (p:Project) RETURN p.id AS id, p.name AS name, "
            "coalesce(p.status, 'active') AS status, p.note AS note ORDER BY toLower(p.name)"
        ):
            project_ids.add(r["id"])
            nodes.append({"id": r["id"], "label": "Project", "name": r["name"],
                          "status": r["status"], "note": r["note"]})

        # A reference in either direction is the same edge — a paper saying
        # "this is for that project" and a project saying "this is built on
        # that paper" describe one relationship, so they aren't drawn twice.
        seen_refs: set[tuple[str, str]] = set()

        def ref_edge(pid: str, other: str, kind: str, rel: str) -> None:
            if pid not in project_ids:
                return
            if kind == "paper" and other not in paper_ids:
                return
            if kind == "project" and other not in project_ids:
                return
            if kind not in ("paper", "project"):
                return          # a decomposition node or idea isn't on this canvas
            key = tuple(sorted((pid, other)))
            if key in seen_refs:
                return
            seen_refs.add(key)
            edges.append({"source": pid, "target": other, "type": rel})

        # a paper brought in as "about" a project
        for r in await run_read(
            "MATCH (a:Paper)-[:ABOUT]->(n:Project) RETURN a.id AS paper, n.id AS project"
        ):
            if r["paper"] in paper_ids:
                ref_edge(r["project"], r["paper"], "paper", "about")

        # a project (or one of its passes) pointing at what it was built on
        for r in await run_read(
            """
            MATCH (n:Project)-[:ABOUT]->(t)
            RETURN n.id AS project, t.id AS target, head(labels(t)) AS label
            """
        ):
            ref_edge(r["project"], r["target"],
                     "paper" if r["label"] == "Paper" else
                     "project" if r["label"] == "Project" else "other", "about")
        for r in await run_read(
            """
            MATCH (n:Project)-[:HAS_PASS]->(:ProjectPass)-[:ABOUT]->(t)
            RETURN DISTINCT n.id AS project, t.id AS target, head(labels(t)) AS label
            """
        ):
            ref_edge(r["project"], r["target"],
                     "paper" if r["label"] == "Paper" else
                     "project" if r["label"] == "Project" else "other", "worked against")

        # Ideas bridge a project to whatever else holds the same idea. An idea
        # only one project owns is dropped under shared_only, exactly like a
        # concept only one paper introduces.
        for row in await run_read(
            """
            MATCH (n:Project)-[:HAS_IDEA]->(i:Idea)
            RETURN i.id AS id, i.title AS name,
                   collect(DISTINCT n.id) AS projects, i.paper_id AS paper_id
            """
        ):
            holders = [x for x in row["projects"] if x in project_ids]
            if row["paper_id"] in paper_ids:
                holders.append(row["paper_id"])
            if not row["name"] or not holders:
                continue
            if shared_only and len(holders) < 2:
                continue
            bid = "Idea:" + row["id"]
            nodes.append({"id": bid, "label": "Idea", "name": row["name"],
                          "shared": len(holders)})
            for h in holders:
                edges.append({"source": h, "target": bid, "type": "idea of"})

    # how connected is each paper — drives node size
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "papers": len(papers),
            "projects": len(project_ids),
            "bridges": sum(1 for n in nodes if n["label"] not in ("Paper", "Project")),
            "links": len(edges),
        },
    }


@router.get("/encounters")
async def encounters(paper_id: str | None = None, threshold: float = 0.86) -> dict:
    """Which concepts you've met in more than one paper — the ring data.

    A node gets one ring per paper it has been encountered in. Encounters come
    from three places, all folded together here:

      1. `(:Paper)-[:INTRODUCES]->(:Concept)` — a term you recorded on a paper
      2. `(:Instance)-[:CONTAINS]->(:Highlight)` whose excerpt/note names the
         concept — i.e. you highlighted it while reading
      3. `(:KGNode)` sharing the concept's name — manual links and auto-KG

    Exact name matches are certain. Near-matches (same normalised stem, or a
    high character-overlap ratio) are returned as `suggested` rather than being
    applied, so an encounter is never invented on your behalf — the UI asks.
    """
    concepts = await run_read(
        """
        MATCH (p:Paper)-[:INTRODUCES]->(c:Concept)
        RETURN c.name AS name, collect(DISTINCT p.id) AS papers
        """
    )
    papers = await run_read("MATCH (p:Paper) RETURN p.id AS id, p.title AS title ORDER BY p.title")
    title_by_id = {p["id"]: p["title"] for p in papers}

    # 3 — KG nodes carrying the same name count as an encounter on their paper
    kg_rows = await run_read(
        "MATCH (n:KGNode) WHERE n.name IS NOT NULL RETURN n.name AS name, n.paper_id AS pid"
    )
    # 2 — highlights that mention the concept
    hl_rows = await run_read(
        """
        MATCH (p:Paper)-[:HAS_INSTANCE]->(:Instance)-[:CONTAINS]->(h:Highlight)
        RETURN p.id AS pid, toLower(coalesce(h.excerpt, '') + ' ' + coalesce(h.my_note, '')) AS text
        """
    )
    # confirmed/rejected suggestions the user has already ruled on
    ruled = await run_read(
        "MATCH (e:ConceptEncounter) RETURN e.concept AS concept, e.paper_id AS pid, e.state AS state"
    )
    confirmed = {(r["concept"], r["pid"]) for r in ruled if r["state"] == "confirmed"}
    rejected = {(r["concept"], r["pid"]) for r in ruled if r["state"] == "rejected"}

    out, suggestions = [], []
    for c in concepts:
        name = c["name"]
        if not name:
            continue
        low = name.lower()
        certain = {pid for pid in c["papers"] if pid}
        maybe: dict[str, str] = {}
        # node names that resolve to this concept — the graph keys rings off
        # these, so a confirmed fuzzy variant still gets its rings drawn
        aliases = {low}
        near_names: dict[str, str] = {}

        for k in kg_rows:
            if not k["pid"] or not k["name"]:
                continue
            kn = k["name"].lower()
            if kn == low:
                certain.add(k["pid"])
            elif _near(kn, low, threshold):
                maybe.setdefault(k["pid"], "kg node “" + k["name"] + "”")
                near_names[k["pid"]] = kn

        for h in hl_rows:
            if h["pid"] in certain or not h["text"]:
                continue
            if low in h["text"]:
                certain.add(h["pid"])

        for cn, pid in confirmed:
            if cn != name:
                continue
            certain.add(pid)
            # confirming a near-match means "this node IS this concept"
            if pid in near_names:
                aliases.add(near_names[pid])
        certain -= {pid for (cn, pid) in rejected if cn == name}
        for pid, why in maybe.items():
            if pid in certain or (name, pid) in rejected:
                continue
            suggestions.append({"concept": name, "paper_id": pid,
                                "paper_title": title_by_id.get(pid, "?"), "reason": why})

        rings = [{"paper_id": pid, "paper_title": title_by_id.get(pid, "?")}
                 for pid in sorted(certain) if pid in title_by_id]
        if rings:
            out.append({"concept": name, "count": len(rings), "rings": rings,
                        "aliases": sorted(aliases)})

    out.sort(key=lambda x: (-x["count"], x["concept"]))
    if paper_id:
        out = [e for e in out if any(r["paper_id"] == paper_id for r in e["rings"])]
        suggestions = [s for s in suggestions if s["paper_id"] == paper_id]
    return {"encounters": out, "suggestions": suggestions, "papers": papers}


def _near(a: str, b: str, threshold: float) -> bool:
    """Cheap fuzzy match: same stem after normalising, or high char overlap."""
    if not a or not b or a == b:
        return False
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    if abs(len(na) - len(nb)) > max(4, int(len(nb) * 0.4)):
        return False
    import difflib
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def _norm(s: str) -> str:
    # punctuation becomes a space, so "ring-test-concept" meets "ring test concept"
    s = "".join(ch if ch.isalnum() else " " for ch in s.lower())
    s = " ".join(s.split())
    # crude singularisation so "transformers" meets "transformer"
    return " ".join(w[:-1] if len(w) > 4 and w.endswith("s") else w for w in s.split())


@router.post("/encounters/rule")
async def rule_encounter(concept: str, paper_id: str, state: str) -> dict:
    """Confirm or reject a suggested encounter. Nothing is applied until you do."""
    if state not in ("confirmed", "rejected"):
        raise HTTPException(400, "state must be 'confirmed' or 'rejected'")
    await run_write(
        """
        MERGE (e:ConceptEncounter {concept: $concept, paper_id: $pid})
        SET e.state = $state, e.ruled_at = $now
        """,
        concept=concept, pid=paper_id, state=state,
        now=datetime.now(timezone.utc).isoformat(),
    )
    await record("kg", "encounter " + state, detail=concept[:70], paper_id=paper_id)
    return {"concept": concept, "paper_id": paper_id, "state": state}


@router.get("/nodes")
async def list_nodes(paper_id: str | None = None, layer: str | None = None) -> list[dict]:
    cypher = "MATCH (n:KGNode) WHERE 1=1"
    params: dict = {}
    if paper_id:
        cypher += " AND n.paper_id = $paper_id"
        params["paper_id"] = paper_id
    if layer:
        cypher += " AND n.layer = $layer"
        params["layer"] = layer
    cypher += " RETURN n"
    rows = await run_read(cypher, **params)
    return [dict(r["n"]) for r in rows]


@router.post("/nodes", status_code=201)
async def create_node(body: KGNodeCreate) -> dict:
    if body.layer == "auto":
        raise HTTPException(400, "auto-layer nodes are created only via /generate")
    nid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (n:KGNode {
            id: $id, paper_id: $paper_id, name: $name, type: $type, layer: $layer,
            x: $x, y: $y, edit_status: 'added'
        })
        RETURN n
        """,
        id=nid, paper_id=body.paper_id, name=body.name, type=body.type,
        layer=body.layer, x=body.x, y=body.y,
    )
    await record("kg", "node added", detail=f"[{body.layer}] {body.name}", paper_id=body.paper_id)
    return dict(rows[0]["n"])


@router.patch("/nodes/{node_id}")
async def update_node(node_id: str, patch: KGNodeUpdate) -> dict:
    cur = await run_read("MATCH (n:KGNode {id: $id}) RETURN n", id=node_id)
    if not cur:
        raise HTTPException(404, "node not found")
    node = dict(cur[0]["n"])
    if node.get("layer") == "auto":
        raise HTTPException(
            409, "auto-layer nodes are frozen — clone to auto_edit first (POST /nodes/{id}/clone)"
        )

    fields = patch.model_dump(exclude_none=True)
    reason = fields.pop("edit_reason", None)
    if not fields:
        raise HTTPException(400, "no fields to update")

    # Position-only drags shouldn't spam the audit trail or flip edit_status.
    is_content_edit = any(k in fields for k in ("name", "type"))
    if is_content_edit and node.get("layer") == "auto_edit":
        fields["edit_status"] = "edited"
        fields["original_name"] = node.get("original_name") or node.get("name")
        fields["edit_reason"] = reason
        fields["edited_at"] = datetime.now(timezone.utc).isoformat()

    sets = ", ".join(f"n.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (n:KGNode {{id: $id}}) SET {sets} RETURN n", id=node_id, **fields)
    if is_content_edit:
        await record(
            "kg", "node edited",
            detail=f"{node.get('name')} → {fields.get('name', node.get('name'))}",
            paper_id=node.get("paper_id"),
        )
    return dict(rows[0]["n"])


@router.post("/nodes/{node_id}/clone", status_code=201)
async def clone_auto_node(node_id: str) -> dict:
    """Clone a frozen auto node into an editable auto_edit node."""
    cur = await run_read("MATCH (n:KGNode {id: $id}) RETURN n", id=node_id)
    if not cur:
        raise HTTPException(404, "node not found")
    src = dict(cur[0]["n"])
    if src.get("layer") != "auto":
        raise HTTPException(400, "only auto-layer nodes are cloned")
    nid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (n:KGNode {
            id: $id, paper_id: $paper_id, name: $name, type: $type,
            layer: 'auto_edit', x: $x, y: $y,
            edit_status: 'original', original_name: $name, auto_source_id: $src
        })
        RETURN n
        """,
        id=nid, paper_id=src.get("paper_id"), name=src.get("name"),
        type=src.get("type", "concept"), x=src.get("x"), y=src.get("y"), src=node_id,
    )
    await record("kg", "node cloned", detail=f"auto→auto_edit: {src.get('name')}", paper_id=src.get("paper_id"))
    return dict(rows[0]["n"])


@router.delete("/nodes/{node_id}", status_code=204, response_class=Response)
async def delete_node(node_id: str) -> Response:
    cur = await run_read("MATCH (n:KGNode {id: $id}) RETURN n", id=node_id)
    if not cur:
        raise HTTPException(404, "node not found")
    node = dict(cur[0]["n"])
    # Deleting cascades to connected :RELATES edges (DETACH).
    await run_write("MATCH (n:KGNode {id: $id}) DETACH DELETE n", id=node_id)
    await record("kg", "node deleted", detail=f"[{node.get('layer')}] {node.get('name')}",
                 paper_id=node.get("paper_id"))
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #
@router.get("/edges")
async def list_edges(paper_id: str | None = None) -> list[dict]:
    cypher = """
        MATCH (a:KGNode)-[r:RELATES]->(b:KGNode)
    """
    params: dict = {}
    if paper_id:
        cypher += " WHERE a.paper_id = $paper_id OR b.paper_id = $paper_id"
        params["paper_id"] = paper_id
    cypher += " RETURN r.id AS id, r.label AS label, r.layer AS layer, a.id AS source, b.id AS target"
    return await run_read(cypher, **params)


@router.post("/edges", status_code=201)
async def create_edge(body: KGEdgeCreate) -> dict:
    if body.source_id == body.target_id:
        raise HTTPException(400, "self-edges are not allowed")
    eid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (a:KGNode {id: $s}), (b:KGNode {id: $t})
        CREATE (a)-[r:RELATES {id: $id, label: $label, layer: $layer}]->(b)
        RETURN r.id AS id, r.label AS label, r.layer AS layer, a.id AS source, b.id AS target
        """,
        s=body.source_id, t=body.target_id, id=eid, label=body.label, layer=body.layer,
    )
    if not rows:
        raise HTTPException(404, "source or target node not found")
    await record("kg", "edge added", detail=f"{body.source_id[:8]} -[{body.label}]-> {body.target_id[:8]}")
    return rows[0]


@router.delete("/edges/{edge_id}", status_code=204, response_class=Response)
async def delete_edge(edge_id: str) -> Response:
    await run_write("MATCH ()-[r:RELATES {id: $id}]->() DELETE r", id=edge_id)
    await record("kg", "edge deleted", detail=edge_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Auto-generation (frozen layer) + raw Cypher
# --------------------------------------------------------------------------- #
@router.post("/generate")
async def generate_auto_kg(paper_id: str, prompt_override: str | None = Form(None)) -> dict:
    """Generate the frozen auto KG for a paper from its text (local LLM)."""
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p.original_path AS op", id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    op = rows[0]["op"]
    if not op:
        # A book or a video series has nothing to read. The manual and auto_edit
        # layers are unaffected — this only rules out generating the frozen one.
        raise HTTPException(
            400,
            "This source has no PDF to read, so there's nothing to generate from. "
            "Add nodes to the manual layer by hand instead.",
        )

    # Wipe any prior auto layer for this paper (regeneration replaces it).
    await run_write(
        "MATCH (n:KGNode {paper_id: $pid, layer: 'auto'}) DETACH DELETE n", pid=paper_id
    )
    text = pdf.extract_text(op, max_pages=12)
    graph = await llm.extract_kg(text, prompt_override=prompt_override)

    # Create auto nodes, remembering name→id so edges can be linked.
    name_to_id: dict[str, str] = {}
    for i, node in enumerate(graph["nodes"]):
        nid = str(uuid.uuid4())
        name_to_id[node["name"]] = nid
        await run_write(
            """
            CREATE (n:KGNode {
                id: $id, paper_id: $pid, name: $name, type: $type, layer: 'auto',
                x: $x, y: $y, edit_status: 'original'
            })
            """,
            id=nid, pid=paper_id, name=node["name"], type=node.get("type", "concept"),
            # simple ring layout so the canvas isn't a pile at the origin
            x=200 + 160 * (i % 5), y=120 + 140 * (i // 5),
        )
    edge_count = 0
    for edge in graph["edges"]:
        s = name_to_id.get(edge["source"])
        t = name_to_id.get(edge["target"])
        if s and t and s != t:
            await run_write(
                """
                MATCH (a:KGNode {id: $s}), (b:KGNode {id: $t})
                CREATE (a)-[:RELATES {id: $id, label: $label, layer: 'auto'}]->(b)
                """,
                s=s, t=t, id=str(uuid.uuid4()), label=edge.get("label", "RELATES"),
            )
            edge_count += 1

    await record(
        "kg", "auto generated",
        detail=f"source={graph['_source']}; {len(graph['nodes'])} nodes, {edge_count} edges",
        paper_id=paper_id,
    )
    return {"nodes": len(graph["nodes"]), "edges": edge_count, "source": graph["_source"]}


@router.post("/query")
async def raw_cypher(body: CypherQuery) -> dict:
    """Power-user Cypher pass-through. Read or write — you own the risk."""
    try:
        rows = await run_write(body.cypher, **body.params)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Cypher error: {exc}") from exc
    await record("kg", "raw query", detail=body.cypher[:120])
    return {"rows": rows, "count": len(rows)}
