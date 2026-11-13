"""/api/synapse/papers — the paper repository.

Upload a PDF → store the pristine original under ~/.mainframe/papers/originals
→ extract text locally (PyMuPDF) → extract metadata with the local LLM (Ollama,
heuristic fallback) → persist a :Paper node in Neo4j. Plus list/get/update/
delete, status cycling, and re-triggerable extraction.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

import llm
import pdf
from activity import record
from config import settings
from db import run_read, run_write
from models import CypherQuery, Paper, PaperUpdate, ReorderRequest, SourceCreate
from routes.mind import reorder_nodes

router = APIRouter(prefix="/api/synapse/papers", tags=["papers"])


# A workspace subject brought in from elsewhere points at the real node, so the
# workspace can link back to it and a rename over there is never a stale copy here.
# "paper" joins the set so the reference can point the other way too: a
# project (or one pass of it) can say which paper it is being built against,
# not only a paper saying which project it belongs to.
_LINK_LABEL = {"project": "Project", "decomp": "Op", "idea": "Idea", "paper": "Paper"}
_LINK_TITLE = {"project": "name", "decomp": "label", "idea": "title", "paper": "title"}


async def link_target_title(link_kind: str, link_id: str) -> str | None:
    """The current title of a linked project / decomposition node / idea."""
    label, prop = _LINK_LABEL.get(link_kind), _LINK_TITLE.get(link_kind)
    if not label:
        return None
    rows = await run_read(f"MATCH (n:{label} {{id: $id}}) RETURN n.{prop} AS t", id=link_id)
    return rows[0]["t"] if rows else None


async def _attach_link(paper_id: str, link_kind: str | None, link_id: str | None) -> None:
    """Point an entry at what it is about. One target at a time — re-linking
    replaces, and a null link_kind detaches."""
    await run_write("MATCH (:Paper {id: $id})-[r:ABOUT]->() DELETE r", id=paper_id)
    if not link_kind or not link_id:
        return
    label = _LINK_LABEL.get(link_kind)
    if not label:
        raise HTTPException(400, f"unknown link kind: {link_kind}")
    rows = await run_write(
        f"""
        MATCH (p:Paper {{id: $pid}}), (n:{label} {{id: $nid}})
        MERGE (p)-[:ABOUT]->(n)
        RETURN n
        """,
        pid=paper_id, nid=link_id,
    )
    if not rows:
        raise HTTPException(404, f"{link_kind} not found: {link_id}")


# Every entry carries how many times work has been pushed against it, so the
# Repository card can show a ★ without a second round trip per card. "Pushed"
# here means a :WorkSession exists on the entry at all — pushing IS what the
# button does — not the `completed` flag, which marks a finished piece of work
# and is a different question.
_PUSH_ROLLUP = """
OPTIONAL MATCH (w:WorkSession)-[:ON]->(p)
WITH p, collect(w{.*}) AS ws
WITH p, size(ws) AS push_count,
     reduce(s = 0, x IN ws | s + coalesce(x.mins, 0)) AS push_mins
"""
_PUSH_RETURN = "push_count, push_mins"


def _row_to_paper(row: dict) -> dict:
    p = dict(row["p"])
    # Always present, even on reads that don't roll up, so the card never has
    # to tell "no pushes" apart from "wasn't asked".
    p["push_count"] = row.get("push_count") or 0
    p["push_mins"] = row.get("push_mins") or 0
    return p


@router.get("")
async def list_papers(
    q: str | None = None,
    status: str | None = None,
    year: int | None = None,
    kind: str | None = None,
) -> list[dict]:
    """List sources with optional search (title/author) and filters."""
    cypher = "MATCH (p:Paper) WHERE 1=1"
    params: dict = {}
    if q:
        cypher += " AND (toLower(p.title) CONTAINS toLower($q) OR any(a IN p.authors WHERE toLower(a) CONTAINS toLower($q)))"
        params["q"] = q
    if status:
        cypher += " AND p.status = $status"
        params["status"] = status
    if year:
        cypher += " AND p.year = $year"
        params["year"] = year
    if kind:
        # Entries created before `kind` existed are papers (see db.py migration),
        # but coalesce anyway so a filter can't hide a row on a stale database.
        cypher += " AND coalesce(p.kind, 'paper') = $kind"
        params["kind"] = kind
    cypher += _PUSH_ROLLUP
    # Manual order wins where it's been set; anything never moved keeps the old
    # newest-first arrangement rather than jumping to the top.
    cypher += (f" RETURN p, {_PUSH_RETURN} ORDER BY coalesce(p.position, 1e15) ASC, "
               "coalesce(p.year, 0) DESC, p.added_at DESC")
    rows = await run_read(cypher, **params)
    return [_row_to_paper(r) for r in rows]


@router.get("/linkable")
async def linkable() -> dict:
    """What a workspace subject can be brought in from.

    Declared above /{paper_id} on purpose — FastAPI matches in declaration
    order and "linkable" would otherwise be read as a paper id.
    """
    projects = await run_read(
        "MATCH (n:Project) RETURN n.id AS id, n.name AS title, n.status AS note "
        "ORDER BY toLower(n.name)"
    )
    decomps = await run_read(
        "MATCH (n:Op) WHERE NOT (:Op)-[:BREAKS_INTO]->(n) "
        "RETURN n.id AS id, n.label AS title, n.tag AS note ORDER BY toLower(n.label)"
    )
    ideas = await run_read(
        "MATCH (n:Idea) WHERE coalesce(n.title, '') <> '' "
        "RETURN n.id AS id, n.title AS title, n.category AS note "
        "ORDER BY coalesce(n.position, 1e15), n.created_at DESC"
    )
    papers = await run_read(
        "MATCH (n:Paper) WHERE coalesce(n.title, '') <> '' "
        "RETURN n.id AS id, n.title AS title, n.kind AS note "
        "ORDER BY coalesce(n.position, 1e15), n.added_at DESC"
    )
    clean = lambda rows: [{"id": r["id"], "title": r["title"], "note": r["note"] or ""} for r in rows]
    return {"project": clean(projects), "decomp": clean(decomps),
            "idea": clean(ideas), "paper": clean(papers)}


@router.get("/{paper_id}")
async def get_paper(paper_id: str) -> dict:
    rows = await run_read(
        f"MATCH (p:Paper {{id: $id}}) {_PUSH_ROLLUP} RETURN p, {_PUSH_RETURN}",
        id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    paper = _row_to_paper(rows[0])
    # Resolved live, never stored: the point of a link is that renaming the
    # project over there shows up here without a sync step.
    if paper.get("link_kind") and paper.get("link_id"):
        paper["link_title"] = await link_target_title(paper["link_kind"], paper["link_id"])
    return paper


@router.post("/reorder")
async def reorder_papers(body: ReorderRequest) -> dict:
    """Move cards in the repository.

    Same shared helper the mind-dumps, ideas and reading passes use: the listed
    ids take the positions those same nodes already hold, reassigned in the
    order given — so swapping two cards inside a filtered view can't disturb
    anything that isn't on screen.
    """
    pairs = await reorder_nodes("Paper", body.ids)
    await record("paper", "reordered", detail=f"{len(pairs)} cards")
    return {"ok": True, "positions": pairs}


@router.post("/manual", status_code=201)
async def create_source(body: SourceCreate) -> dict:
    """Add a repository entry by hand — a book, a video series, a course.

    No file, no extraction. Everything a PDF-backed entry can do afterwards
    (instances, highlights, terms, references, KG nodes, notes) works on this
    the same way, because it is the same node.
    """
    if not body.title.strip():
        raise HTTPException(400, "title cannot be empty")

    paper_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await run_write(
        """
        CREATE (p:Paper {
            id: $id, title: $title, kind: $kind, authors: $authors, year: $year,
            venue: $venue, url: $url, abstract: $abstract,
            status: $status, added_at: $added_at,
            link_kind: $link_kind, link_id: $link_id
        })
        """,
        id=paper_id, title=body.title.strip(), kind=body.kind,
        link_kind=body.link_kind, link_id=body.link_id,
        authors=[a.strip() for a in body.authors if a.strip()],
        year=body.year, venue=body.venue, url=body.url, abstract=body.abstract,
        status=body.status, added_at=now,
    )
    await _link_authors_and_venue(paper_id, body.authors, body.venue)
    await _attach_link(paper_id, body.link_kind, body.link_id)
    await record("paper", "added", detail=f"{body.kind} (manual)",
                 paper_id=paper_id, paper_title=body.title.strip())
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p", id=paper_id)
    return _row_to_paper(rows[0])


@router.post("", status_code=201)
async def upload_paper(
    file: UploadFile = File(...),
    prompt_override: str | None = Form(None),
    kind: str = Form("paper"),
    title: str | None = Form(None),
    scan: bool = Form(True),
) -> dict:
    """Upload a PDF and store it as a :Paper.

    `scan=false` skips the local LLM entirely — the entry is exactly the title
    you gave (or the filename), which is what you want for a book whose opening
    pages are a cover, or for anything you'd rather type in yourself.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a .pdf file")

    paper_id = str(uuid.uuid4())
    settings.papers_originals.mkdir(parents=True, exist_ok=True)
    safe_name = f"{paper_id}.pdf"
    dest = settings.papers_originals / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    pages_read = 0
    if scan:
        # Local text + metadata extraction.
        try:
            head, pages_read = pdf.extract_head_adaptive(dest)
        except Exception as exc:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"could not read PDF: {exc}") from exc
        meta = await llm.extract_metadata(head, prompt_override=prompt_override,
                                          filename=file.filename)
    else:
        meta = {"title": llm.title_from_filename(file.filename), "authors": [],
                "year": None, "venue": None, "doi": None, "arxiv_id": None,
                "abstract": None, "_source": "not scanned"}
    # A title typed in the upload form always wins over anything extracted.
    if title and title.strip():
        meta = {**meta, "title": title.strip(), "_source": meta["_source"] + " + typed title"}

    now = datetime.now(timezone.utc).isoformat()
    await run_write(
        """
        CREATE (p:Paper {
            id: $id, title: $title, kind: $kind, authors: $authors, year: $year,
            venue: $venue, doi: $doi, arxiv_id: $arxiv_id, abstract: $abstract,
            original_path: $original_path, status: 'unread', added_at: $added_at
        })
        """,
        id=paper_id,
        title=meta["title"],
        kind=kind,
        authors=meta["authors"],
        year=meta["year"],
        venue=meta["venue"],
        doi=meta["doi"],
        arxiv_id=meta["arxiv_id"],
        abstract=meta["abstract"],
        original_path=str(dest),
        added_at=now,
    )

    # Link authors and venue as first-class nodes (per the graph model).
    await _link_authors_and_venue(paper_id, meta["authors"], meta["venue"])

    await record(
        "paper", "uploaded",
        detail=f"source={meta['_source']}; {file.filename}",
        paper_id=paper_id, paper_title=meta["title"],
    )
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p", id=paper_id)
    result = _row_to_paper(rows[0])
    result["_extraction_source"] = meta["_source"]
    result["_pages_read"] = pages_read
    if meta.get("_no_text") and not (title and title.strip()):
        # Say it plainly rather than leaving a filename-derived title looking
        # like something we read off the page. Suppressed when you typed a title
        # — then nothing was guessed and there's nothing to warn about.
        result["_warning"] = (
            "No selectable text in this PDF — it's page images (a scan), so nothing "
            "could be read from it. The title came from the filename; edit it by hand."
        )
    return result


async def _link_authors_and_venue(paper_id: str, authors: list[str], venue: str | None) -> None:
    for name in authors or []:
        if not name.strip():
            continue
        await run_write(
            """
            MATCH (p:Paper {id: $pid})
            MERGE (a:Author {name: $name})
            MERGE (p)-[:AUTHORED_BY]->(a)
            """,
            pid=paper_id, name=name.strip(),
        )
    if venue and venue.strip():
        await run_write(
            """
            MATCH (p:Paper {id: $pid})
            MERGE (v:Venue {name: $name})
            MERGE (p)-[:PUBLISHED_AT]->(v)
            """,
            pid=paper_id, name=venue.strip(),
        )


async def _relink_authors_and_venue(paper_id: str, authors: list[str], venue: str | None) -> None:
    """Re-point a paper's author/venue edges after an edit.

    MERGE only ever adds, so correcting a mis-scanned author would otherwise leave the
    wrong one attached forever. Drop the old edges first, then prune any :Author/:Venue
    left with no papers at all (same reasoning as Vision's _prune_tools).
    """
    await run_write(
        """
        MATCH (p:Paper {id: $pid})
        OPTIONAL MATCH (p)-[r:AUTHORED_BY|PUBLISHED_AT]->()
        DELETE r
        """,
        pid=paper_id,
    )
    await _link_authors_and_venue(paper_id, authors, venue)
    await _prune_authors_and_venues()


async def _prune_authors_and_venues() -> None:
    """Drop :Author/:Venue nodes nothing points at any more.

    "No paper points at it" is not the same as orphaned: the references
    pipeline hangs :Reference nodes off the very same author and venue nodes.
    Pruning on the paper test alone tried to DELETE nodes that still had those
    relationships — Neo4j refuses, so every repository delete raised a 500 after
    having already removed the entry, and any that did go through would have
    stripped the authorship off the references.
    """
    await run_write(
        """
        MATCH (n) WHERE (n:Author OR n:Venue) AND NOT (n)<--()
        DELETE n
        """
    )


@router.patch("/{paper_id}")
async def update_paper(paper_id: str, patch: PaperUpdate) -> dict:
    # exclude_unset, not exclude_none: an explicit null is how the client clears a
    # field (Neo4j drops null properties), and an omitted field must stay untouched.
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if fields.get("title") is not None and not str(fields["title"]).strip():
        raise HTTPException(400, "title cannot be empty")
    # The frontend owns the shape of section_colors, but it still has to be JSON:
    # a malformed blob would come back out of the GET and break every reader.
    if "section_colors" in fields:
        try:
            if not isinstance(json.loads(fields["section_colors"] or "{}"), dict):
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(400, "section_colors must be a JSON object")
    sets = ", ".join(f"p.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (p:Paper {{id: $id}}) SET {sets} RETURN p",
        id=paper_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "paper not found")
    paper = _row_to_paper(rows[0])
    if "authors" in fields or "venue" in fields:
        await _relink_authors_and_venue(paper_id, paper.get("authors", []), paper.get("venue"))
    if "link_kind" in fields or "link_id" in fields:
        await _attach_link(paper_id, paper.get("link_kind"), paper.get("link_id"))
    if "title" in fields:
        # :MindDump snapshots the title it was filed under — keep those in step so a
        # rename doesn't leave the mind inbox showing the old (wrong) title.
        await run_write(
            "MATCH (m:MindDump {paper_id: $id}) SET m.paper_title = $title",
            id=paper_id, title=paper["title"],
        )
    cat = "status" if set(fields) == {"status"} else "paper"
    await record(cat, "updated", detail=", ".join(fields), paper_id=paper_id, paper_title=paper["title"])
    return paper


@router.post("/{paper_id}/cycle-status")
async def cycle_status(paper_id: str) -> dict:
    """unread → reading → read → unread. A shelved entry cycles back to reading:
    cycling it at all means you picked it back up."""
    order = {"unread": "reading", "reading": "read", "read": "unread", "shelved": "reading"}
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p", id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    cur = rows[0]["p"].get("status", "unread")
    nxt = order.get(cur, "reading")
    out = await run_write(
        "MATCH (p:Paper {id: $id}) SET p.status = $s RETURN p", id=paper_id, s=nxt
    )
    paper = _row_to_paper(out[0])
    await record("status", "changed", detail=f"{cur} → {nxt}", paper_id=paper_id, paper_title=paper["title"])
    return paper


@router.delete("/{paper_id}", status_code=204, response_class=Response)
async def delete_paper(paper_id: str) -> Response:
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p", id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    paper = rows[0]["p"]
    # Remove the original file.
    if paper.get("original_path"):
        Path(paper["original_path"]).unlink(missing_ok=True)
    # …and every instance's annotation copy. Deleting the paper detaches those
    # :Instance nodes below, which would otherwise strand their PDFs on disk with
    # nothing left in the graph pointing at them. (delete_instance already does
    # this for a single pass; this is the same job for the whole paper.)
    inst = await run_read(
        "MATCH (:Paper {id: $id})-[:HAS_INSTANCE]->(i:Instance) RETURN i.file_path AS fp",
        id=paper_id,
    )
    for row in inst:
        if row["fp"]:
            Path(row["fp"]).unlink(missing_ok=True)
    # Detach-delete the paper and its owned subgraph (instances, highlights, kg).
    await run_write(
        """
        MATCH (p:Paper {id: $id})
        OPTIONAL MATCH (p)-[:HAS_INSTANCE]->(i:Instance)-[:CONTAINS]->(h:Highlight)
        OPTIONAL MATCH (p)<-[:SCOPED_TO]-(hdr:CustomHeader)
        OPTIONAL MATCH (kn:KGNode {paper_id: $id})
        DETACH DELETE h, i, hdr, kn, p
        """,
        id=paper_id,
    )
    await _prune_authors_and_venues()
    await record("paper", "deleted", detail=paper.get("title", ""), paper_id=paper_id, paper_title=paper.get("title"))
    return Response(status_code=204)


@router.post("/{paper_id}/reextract")
async def reextract_metadata(paper_id: str, body: CypherQuery | None = None, prompt_override: str | None = Form(None)) -> dict:
    """Re-run metadata extraction, optionally with a custom prompt."""
    rows = await run_read("MATCH (p:Paper {id: $id}) RETURN p", id=paper_id)
    if not rows:
        raise HTTPException(404, "paper not found")
    path = rows[0]["p"].get("original_path")
    if not path or not Path(path).exists():
        raise HTTPException(400, "original PDF missing")
    head, _pages = pdf.extract_head_adaptive(path)
    meta = await llm.extract_metadata(head, prompt_override=prompt_override,
                                      filename=Path(path).name)
    if meta.get("_no_text"):
        # A re-scan overwrites every field, so on a text-less PDF it would
        # replace a title typed by hand with a guess from a UUID filename.
        # Refuse instead — there is nothing here to re-extract.
        raise HTTPException(
            400,
            "This PDF has no selectable text (it's a scan), so there's nothing to "
            "re-read. Edit the details by hand instead.",
        )
    out = await run_write(
        """
        MATCH (p:Paper {id: $id})
        SET p.title=$title, p.authors=$authors, p.year=$year, p.venue=$venue,
            p.doi=$doi, p.arxiv_id=$arxiv_id, p.abstract=$abstract
        RETURN p
        """,
        id=paper_id, title=meta["title"], authors=meta["authors"], year=meta["year"],
        venue=meta["venue"], doi=meta["doi"], arxiv_id=meta["arxiv_id"], abstract=meta["abstract"],
    )
    await record("paper", "re-extracted", detail=f"source={meta['_source']}", paper_id=paper_id, paper_title=meta["title"])
    result = _row_to_paper(out[0])
    result["_extraction_source"] = meta["_source"]
    return result
