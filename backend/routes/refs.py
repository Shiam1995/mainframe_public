"""/api/synapse/refs — citation cross-reference matrix.

Row cites column. Each cell cycles: none → cites → highlighted → none, stored as
(:Paper)-[:CITES {highlighted: Boolean}]->(:Paper). Also exposes density stats
and an LLM-assisted reference-parsing helper.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Response

import llm
import pdf
from activity import record
from db import run_read, run_write
import refparse
import refpipeline
from models import BulkRefs, ReferenceCreate, RefFlagSet, RefStateSet, RefToggle

router = APIRouter(prefix="/api/synapse/refs", tags=["refs"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _match_paper_id(title: str) -> str | None:
    """Best-effort match of a reference title to a paper already in the repo."""
    rt = (title or "").lower()
    if not rt:
        return None
    existing = await run_read("MATCH (p:Paper) RETURN p.id AS id, toLower(p.title) AS t")
    for e in existing:
        if e["t"] and (e["t"] in rt or rt[:40] in e["t"]):
            return e["id"]
    return None


@router.get("")
async def get_matrix() -> dict:
    """Return papers (matrix axes) and the current citation edges."""
    papers = await run_read(
        "MATCH (p:Paper) RETURN p.id AS id, p.title AS title, p.year AS year "
        "ORDER BY coalesce(p.year, 0), p.title"
    )
    edges = await run_read(
        """
        MATCH (a:Paper)-[r:CITES]->(b:Paper)
        RETURN a.id AS source, b.id AS target, coalesce(r.highlighted, false) AS highlighted
        """
    )
    return {"papers": papers, "edges": edges}


@router.post("/toggle")
async def toggle_ref(body: RefToggle) -> dict:
    if body.source_id == body.target_id:
        raise HTTPException(400, "a paper cannot cite itself")
    if body.state == "none":
        await run_write(
            "MATCH (a:Paper {id: $s})-[r:CITES]->(b:Paper {id: $t}) DELETE r",
            s=body.source_id, t=body.target_id,
        )
    else:
        highlighted = body.state == "highlighted"
        await run_write(
            """
            MATCH (a:Paper {id: $s}), (b:Paper {id: $t})
            MERGE (a)-[r:CITES]->(b)
            SET r.highlighted = $hl
            """,
            s=body.source_id, t=body.target_id, hl=highlighted,
        )
    await record("ref", "toggled", detail=f"{body.source_id[:8]}→{body.target_id[:8]} = {body.state}")
    return {"ok": True, "state": body.state}


@router.get("/stats")
async def ref_stats() -> dict:
    most_cited = await run_read(
        """
        MATCH (p:Paper) OPTIONAL MATCH (p)<-[:CITES]-()
        WITH p, count(*) AS cited_by
        RETURN p.title AS title, p.id AS id, cited_by ORDER BY cited_by DESC LIMIT 5
        """
    )
    most_citing = await run_read(
        """
        MATCH (p:Paper) OPTIONAL MATCH (p)-[:CITES]->()
        WITH p, count(*) AS cites
        RETURN p.title AS title, p.id AS id, cites ORDER BY cites DESC LIMIT 5
        """
    )
    total = await run_read("MATCH ()-[r:CITES]->() RETURN count(r) AS n")
    return {"most_cited": most_cited, "most_citing": most_citing, "total_edges": total[0]["n"]}


@router.post("/parse")
async def parse_refs(paper_id: str, prompt_override: str | None = Form(None)) -> dict:
    """Extract the references section and match against existing papers (local LLM)."""
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p.original_path AS op", id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    refs_text = pdf.extract_references_section(rows[0]["op"]) if rows[0]["op"] else ""
    parsed = await llm.parse_references(refs_text, prompt_override=prompt_override)

    # Naive title matching against the repo.
    existing = await run_read("MATCH (p:Paper) RETURN p.id AS id, toLower(p.title) AS t")
    for ref in parsed:
        rt = (ref.get("title") or "").lower()
        ref["matched_paper_id"] = None
        for e in existing:
            if e["t"] and (e["t"] in rt or rt[:40] in e["t"]):
                ref["matched_paper_id"] = e["id"]
                break
    await record("ref", "parsed", detail=f"{len(parsed)} references", paper_id=paper_id)
    return {"references": parsed}


# --------------------------------------------------------------------------- #
# Stored references per paper — name + link, kept as (:Reference) nodes so they
# can seed a citation knowledge-map later.
#   (:Paper)-[:REFERENCES]->(:Reference {title, link, year, matched_paper_id})
# --------------------------------------------------------------------------- #
def _normalize_link(link: str | None) -> str | None:
    """Make a reference link clickable: DOI/bare-domain → proper URL."""
    if not link:
        return None
    s = link.strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith(("http://", "https://")):
        return s
    if low.startswith("doi:"):
        return "https://doi.org/" + s[4:].strip()
    if low.startswith("10."):  # bare DOI
        return "https://doi.org/" + s
    if low.startswith("www."):
        return "https://" + s
    return s


async def _store_reference(paper_id: str, title: str, link: str | None, year: int | None,
                            position: int | None = None) -> dict:
    """`position` is the entry's place in the list it came from (a pasted
    bibliography, a scanned PDF). Without one (a single manual add) a new
    reference goes to the end and an existing one keeps its place."""
    link = _normalize_link(link)
    matched = await _match_paper_id(title)
    rows = await run_write(
        """
        MATCH (p:Paper {id: $pid})
        OPTIONAL MATCH (p)-[:REFERENCES]->(o:Reference)
        WITH p, coalesce(max(o.position), -1) AS top
        MERGE (p)-[:REFERENCES]->(r:Reference {paper_id: $pid, title: $title})
          ON CREATE SET r.id = $id, r.created_at = $now
        SET r.position = coalesce($position, r.position, top + 1),
            r.link = $link, r.year = $year, r.matched_paper_id = $matched,
            r.state = CASE WHEN $matched IS NOT NULL THEN 'in_library'
                           ELSE coalesce(r.state, 'unread') END
        RETURN r
        """,
        pid=paper_id, id=str(uuid.uuid4()), title=title[:300], link=link,
        year=year, matched=matched, now=_now(), position=position,
    )
    # If the reference is itself a paper in the repo, also draw the citation edge.
    if matched and matched != paper_id:
        await run_write(
            "MATCH (a:Paper {id: $s}), (b:Paper {id: $t}) MERGE (a)-[:CITES]->(b)",
            s=paper_id, t=matched,
        )
    return dict(rows[0]["r"]) if rows else {}


async def _next_position(paper_id: str) -> int:
    """One past the last reference on the paper: where a new batch starts."""
    rows = await run_read(
        "MATCH (:Paper {id: $pid})-[:REFERENCES]->(r:Reference) "
        "RETURN coalesce(max(r.position), -1) + 1 AS n", pid=paper_id)
    return rows[0]["n"] if rows else 0


@router.get("/stored")
async def list_stored(paper_id: str) -> list[dict]:
    rows = await run_read(
        "MATCH (:Paper {id: $pid})-[:REFERENCES]->(r:Reference) "
        # The order you put them in: the bibliography's own order, not by year.
        "RETURN r ORDER BY coalesce(r.position, 1e9), r.created_at",
        pid=paper_id,
    )
    return [dict(row["r"]) for row in rows]


@router.post("/scan", status_code=201)
async def scan_and_store(paper_id: str, prompt_override: str | None = Form(None)) -> dict:
    """Scan the paper's reference section and store each work (name + link)."""
    rows = await run_read(
        "MATCH (p:Paper {id: $id}) RETURN p.original_path AS op, p.title AS title", id=paper_id
    )
    if not rows:
        raise HTTPException(404, "paper not found")
    refs_text = pdf.extract_references_section(rows[0]["op"]) if rows[0]["op"] else ""
    parsed = await llm.parse_references(refs_text, prompt_override=prompt_override)
    stored = []
    base = await _next_position(paper_id)
    for ref in parsed:
        title = (ref.get("title") or "").strip()
        if not title:
            continue
        stored.append(await _store_reference(paper_id, title, ref.get("link"), ref.get("year"),
                                             position=base + len(stored)))
    await record("ref", "scanned", detail=f"stored {len(stored)} references",
                 paper_id=paper_id, paper_title=rows[0]["title"], trigger="llm")
    return {"count": len(stored), "references": stored}


@router.post("/stored", status_code=201)
async def add_stored(paper_id: str, body: ReferenceCreate) -> dict:
    """Manually add one reference (name + optional link)."""
    ctx = await run_read("MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=paper_id)
    if not ctx:
        raise HTTPException(404, "paper not found")
    r = await _store_reference(paper_id, body.title.strip(), body.link, body.year)
    await record("ref", "reference added", detail=body.title[:70], paper_id=paper_id, paper_title=ctx[0]["title"])
    return r


@router.get("/table")
async def paper_table() -> list[dict]:
    """One row per paper: where you are with it, and how connected it is.

    Feeds the sheet under the Reference Map — understanding score first, then
    read state, then the counts that say how wired into the library it is.
    """
    rows = await run_read(
        """
        MATCH (p:Paper)
        OPTIONAL MATCH (p)-[:REFERENCES]->(r:Reference)
        WITH p, count(DISTINCT r) AS refs,
             count(DISTINCT CASE WHEN r.matched_paper_id IS NOT NULL THEN r END) AS refs_in_library
        OPTIONAL MATCH (p)-[:CITES]->(o:Paper)
        WITH p, refs, refs_in_library, count(DISTINCT o) AS cites_out
        OPTIONAL MATCH (p)<-[:CITES]-(i:Paper)
        WITH p, refs, refs_in_library, cites_out, count(DISTINCT i) AS cited_by
        OPTIONAL MATCH (p)-[:INTRODUCES]->(c:Concept)
        WITH p, refs, refs_in_library, cites_out, cited_by, count(DISTINCT c) AS concepts
        OPTIONAL MATCH (p)-[:HAS_INSTANCE]->(inst:Instance)
        WITH p, refs, refs_in_library, cites_out, cited_by, concepts,
             count(DISTINCT inst) AS passes,
             sum(coalesce(inst.mins, 0)) AS mins
        OPTIONAL MATCH (p)-[:HAS_INSTANCE]->(:Instance)-[:CONTAINS]->(h:Highlight)
        WITH p, refs, refs_in_library, cites_out, cited_by, concepts, passes, mins,
             count(DISTINCT h) AS highlights
        OPTIONAL MATCH (n:KGNode) WHERE n.paper_id = p.id
        RETURN p.id AS id, p.title AS title, p.year AS year,
               coalesce(p.status, 'unread') AS status,
               p.understanding AS understanding,
               refs, refs_in_library, cites_out, cited_by, concepts,
               passes, mins, highlights, count(DISTINCT n) AS kg_nodes
        ORDER BY toLower(p.title)
        """
    )
    out = []
    for r in rows:
        d = dict(r)
        # "links" = every edge that ties this paper to something else in the library
        d["links"] = (d["cites_out"] or 0) + (d["cited_by"] or 0) + (d["refs_in_library"] or 0)
        d["nodes"] = (d["kg_nodes"] or 0) + (d["concepts"] or 0)
        out.append(d)
    return out


@router.post("/bulk")
async def bulk_references(paper_id: str, body: BulkRefs) -> dict:
    """Paste a bibliography as text and store it, no LLM involved.

    The scanner's model invents identifiers — measured against a real
    bibliography, 5 of 8 arXiv ids were fabricated and one was copied from
    another entry. This path only ever keeps a link that literally appears in
    the text you pasted, so that can't happen.

    `commit=False` returns the parse for review without writing anything.
    """
    ctx = await run_read("MATCH (p:Paper {id: $id}) RETURN p.title AS title", id=paper_id)
    if not ctx:
        raise HTTPException(404, "paper not found")
    entries = refpipeline.parse(body.text)
    if not body.commit:
        profile = refpipeline.profile_of(body.text)
        return {
            "parsed": len(entries), "entries": entries, "committed": False,
            # what the parser decided the bibliography IS, so a bad parse is
            # legible as a misread style rather than an unexplained mess
            "style": {
                "names": profile.order, "separator": profile.sep,
                "family": profile.family, "marker": profile.marker,
                "agreement": round(profile.agreement, 2),
            },
        }

    if body.replace:
        await run_write(
            "MATCH (:Paper {id: $pid})-[:REFERENCES]->(r:Reference) DETACH DELETE r",
            pid=paper_id,
        )
    stored = []
    base = await _next_position(paper_id)
    for i, e in enumerate(entries):
        stored.append(await _store_reference(paper_id, e["title"], e["link"], e["year"],
                                             position=base + i))
    await record(
        "ref", "bulk pasted",
        detail=f"{len(stored)} references{' (replaced)' if body.replace else ''}",
        paper_id=paper_id, paper_title=ctx[0]["title"],
    )
    return {"parsed": len(entries), "entries": entries, "committed": True, "stored": len(stored)}


@router.patch("/stored/{ref_id}/state")
async def set_ref_state(ref_id: str, body: RefStateSet) -> dict:
    """Cycle a reference's reading state: unread → read → in_library → dismissed.

    `in_library` is normally derived (the title matched a paper you own), but
    it's settable by hand for a match the fuzzy check missed.
    """
    rows = await run_write(
        "MATCH (r:Reference {id: $id}) SET r.state = $state RETURN r",
        id=ref_id, state=body.state,
    )
    if not rows:
        raise HTTPException(404, "reference not found")
    ref = dict(rows[0]["r"])
    await record("ref", "state → " + body.state, detail=(ref.get("title") or "")[:70])
    return ref


@router.patch("/stored/{ref_id}/flag")
async def set_ref_flag(ref_id: str, body: RefFlagSet) -> dict:
    """Star a reference and/or pin a note to it.

    Starring is the "come back to this one" mark: it's what turns this paper's
    citation edge yellow on the Reference Map, and the note travels with the
    edge so the reason is on the map too, not just in the list.

    The two fields are set independently — a body with only `note` leaves the
    star alone, and vice versa. A blank note clears it. Unstarring drops
    `starred_at` but keeps the note: you may still want the thought after the
    work has stopped being urgent.

    Neither field is touched by _store_reference, so a re-scan of the PDF
    re-parses titles and links without losing what you marked by hand.
    """
    sets = ["r.starred = coalesce(r.starred, false)"]
    params: dict = {"id": ref_id, "now": _now()}
    if body.starred is not None:
        sets[0] = "r.starred = $starred"
        params["starred"] = body.starred
        # First star stamps the time; re-starring an old one doesn't reset it.
        sets.append("r.starred_at = " + ("coalesce(r.starred_at, $now)" if body.starred else "null"))
    if body.note is not None:
        sets.append("r.note = $note")
        params["note"] = body.note.strip()[:500] or None

    rows = await run_write(
        "MATCH (r:Reference {id: $id}) SET " + ", ".join(sets) + " RETURN r", **params
    )
    if not rows:
        raise HTTPException(404, "reference not found")
    ref = dict(rows[0]["r"])
    what = ("starred" if body.starred else "unstarred") if body.starred is not None else "note"
    await record("ref", "reference " + what, detail=(ref.get("title") or "")[:70])
    return ref


@router.post("/stored/{ref_id}/kg", status_code=201)
async def reference_to_kg(ref_id: str) -> dict:
    """Put a reference on the citing paper's knowledge graph.

    Creates a :KGNode for the cited work and links it with CITES. If the
    reference matched a paper already in the library, the citing paper is also
    wired straight to that paper so the citation map picks it up.
    """
    rows = await run_read(
        """
        MATCH (p:Paper)-[:REFERENCES]->(r:Reference {id: $id})
        RETURN r{.*} AS ref, p.id AS pid, p.title AS ptitle
        """,
        id=ref_id,
    )
    if not rows:
        raise HTTPException(404, "reference not found")
    ref, pid, ptitle = rows[0]["ref"], rows[0]["pid"], rows[0]["ptitle"]
    title = (ref.get("title") or "").strip()

    # reuse the node if this reference is already on the graph
    existing = await run_read(
        "MATCH (n:KGNode {paper_id: $pid, name: $name}) RETURN n{.*} AS n LIMIT 1",
        pid=pid, name=title[:120],
    )
    if existing:
        node = existing[0]["n"]
    else:
        node = (await run_write(
            """
            CREATE (n:KGNode {
                id: $id, paper_id: $pid, name: $name, type: 'paper',
                layer: 'manual', x: $x, y: $y, edit_status: 'added',
                reference_id: $ref_id, matched_paper_id: $matched
            })
            RETURN n{.*} AS n
            """,
            id=str(uuid.uuid4()), pid=pid, name=title[:120],
            x=120.0, y=120.0, ref_id=ref_id, matched=ref.get("matched_paper_id"),
        ))[0]["n"]

    # CITES edge from the paper's own node (or the paper itself) to the reference
    await run_write(
        """
        MATCH (r:Reference {id: $rid}) SET r.kg_node_id = $nid, r.state = coalesce(r.state, 'unread')
        """,
        rid=ref_id, nid=node["id"],
    )
    matched = ref.get("matched_paper_id")
    if matched and matched != pid:
        await run_write(
            "MATCH (a:Paper {id: $s}), (b:Paper {id: $t}) MERGE (a)-[:CITES]->(b)",
            s=pid, t=matched,
        )
    await record("kg", "reference → node", detail=title[:70], paper_id=pid, paper_title=ptitle)
    return {"node": node, "linked_paper_id": matched}


@router.delete("/stored/{ref_id}", status_code=204, response_class=Response)
async def delete_stored(ref_id: str) -> Response:
    await run_write("MATCH (r:Reference {id: $id}) DETACH DELETE r", id=ref_id)
    await record("ref", "reference removed", detail=ref_id)
    return Response(status_code=204)
