"""/api/synapse/dictionary — the global Mainframe Dictionary.

A rich term store that spans every domain (not Synapse-only). Each entry is a
:Term node holding an ELI5, a technical definition, a video, a 0-10 familiarity
score, a classification tag (term/concept/method/person), an optional "starred"
flag, and an optional header image. Terms link to questions, notes, and to each
other (bidirectionally).

Distinct from the per-paper :Concept nodes in routes/terms.py — a Concept can be
promoted here with one click (POST /from-concept).

Neo4j model:
  (:Term {id, name, eli5, definition, familiarity, video, domain, source,
          type, starred, image, created_at})
  (:Term)-[:HAS_QUESTION]->(:DictQuestion {id, question, answer})
  (:Term)-[:HAS_NOTE]->(:DictNote {id, text, image, date})
  (:Term)-[:RELATED_TO]->(:Term)          — bidirectional (both directions written)
"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from activity import record
from config import settings
from db import run_read, run_write
from models import (
    BulkAddTerms, ScanRequest,
    DictEntryCreate,
    DictEntryUpdate,
    DictFromConcept,
    DictNoteCreate,
    DictQuestionCreate,
    DictQuestionUpdate,
)

router = APIRouter(prefix="/api/synapse/dictionary", tags=["dictionary"])

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Terms — list / create / detail / update / delete
# --------------------------------------------------------------------------- #
@router.get("/terms")
async def list_terms(
    q: str | None = None,
    fam: str | None = None,      # "0-3" | "4-6" | "7-10"
    type: str | None = None,     # term|concept|method|person
    starred: bool | None = None,
) -> list[dict]:
    """List every term with lightweight counts for the card grid."""
    cypher = "MATCH (t:Term) WHERE 1=1"
    params: dict = {}
    if q:
        cypher += (
            " AND (toLower(t.name) CONTAINS toLower($q)"
            " OR toLower(coalesce(t.eli5,'')) CONTAINS toLower($q)"
            " OR toLower(coalesce(t.domain,'')) CONTAINS toLower($q))"
        )
        params["q"] = q
    if fam == "0-3":
        cypher += " AND t.familiarity <= 3"
    elif fam == "4-6":
        cypher += " AND t.familiarity >= 4 AND t.familiarity <= 6"
    elif fam == "7-10":
        cypher += " AND t.familiarity >= 7"
    if type:
        cypher += " AND t.type = $type"
        params["type"] = type
    if starred:
        cypher += " AND t.starred = true"
    cypher += """
        OPTIONAL MATCH (t)-[:HAS_QUESTION]->(q:DictQuestion)
        OPTIONAL MATCH (t)-[:HAS_NOTE]->(n:DictNote)
        OPTIONAL MATCH (t)-[:RELATED_TO]->(r:Term)
        RETURN t,
               count(DISTINCT q) AS n_questions,
               count(DISTINCT n) AS n_notes,
               count(DISTINCT r) AS n_related
        ORDER BY t.name
    """
    rows = await run_read(cypher, **params)
    return [_pack(r) for r in rows]


@router.get("/lookup")
async def lookup_term(name: str) -> dict:
    """Exact (case-insensitive) existence check for one word — used by the
    Workspace 'is this already in the dictionary?' quick-check.
    Returns {exists, term}. `term` is null when not found."""
    rows = await run_read(
        "MATCH (t:Term) WHERE toLower(t.name) = toLower($name) RETURN t LIMIT 1",
        name=name.strip(),
    )
    if not rows:
        return {"exists": False, "term": None}
    return {"exists": True, "term": dict(rows[0]["t"])}


def _pack(row: dict) -> dict:
    t = dict(row["t"])
    t["n_questions"] = row.get("n_questions", 0)
    t["n_notes"] = row.get("n_notes", 0)
    t["n_related"] = row.get("n_related", 0)
    return t


@router.post("/terms", status_code=201)
async def create_term(body: DictEntryCreate) -> dict:
    exists = await run_read("MATCH (t:Term {name: $name}) RETURN t.id AS id", name=body.name)
    if exists:
        raise HTTPException(409, f'"{body.name}" is already in the dictionary')
    tid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (t:Term {
            id: $id, name: $name, eli5: $eli5, definition: $definition,
            familiarity: $familiarity, video: $video, domain: $domain,
            source: $source, type: $type, starred: $starred, image: null,
            created_at: $created_at
        })
        RETURN t
        """,
        id=tid, name=body.name, eli5=body.eli5, definition=body.definition,
        familiarity=body.familiarity, video=body.video, domain=body.domain,
        source=body.source, type=body.type, starred=body.starred, created_at=_now(),
    )
    await record("dictionary", "term added", detail=f"{body.name} ({body.type})")
    return dict(rows[0]["t"])


@router.get("/terms/{term_id}")
async def get_term(term_id: str) -> dict:
    rows = await run_read("MATCH (t:Term {id: $id}) RETURN t", id=term_id)
    if not rows:
        raise HTTPException(404, "term not found")
    term = dict(rows[0]["t"])

    qrows = await run_read(
        "MATCH (t:Term {id: $id})-[:HAS_QUESTION]->(q:DictQuestion) RETURN q ORDER BY q.question",
        id=term_id,
    )
    term["questions"] = [dict(r["q"]) for r in qrows]

    nrows = await run_read(
        "MATCH (t:Term {id: $id})-[:HAS_NOTE]->(n:DictNote) RETURN n ORDER BY n.date",
        id=term_id,
    )
    term["notes"] = [dict(r["n"]) for r in nrows]

    rrows = await run_read(
        "MATCH (t:Term {id: $id})-[:RELATED_TO]->(r:Term) RETURN r.id AS id, r.name AS name ORDER BY r.name",
        id=term_id,
    )
    term["related"] = [{"id": r["id"], "name": r["name"]} for r in rrows]
    return term


@router.put("/terms/{term_id}")
async def update_term(term_id: str, patch: DictEntryUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    old = await run_read(
        "MATCH (t:Term {id: $id}) RETURN t.familiarity AS f, t.name AS name", id=term_id
    )
    if not old:
        raise HTTPException(404, "term not found")
    # Renaming must not collide with another entry (name is unique).
    if "name" in fields and fields["name"] != old[0]["name"]:
        clash = await run_read(
            "MATCH (t:Term {name: $name}) RETURN t.id AS id", name=fields["name"]
        )
        if clash:
            raise HTTPException(409, f'"{fields["name"]}" already exists')
    sets = ", ".join(f"t.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (t:Term {{id: $id}}) SET {sets} RETURN t", id=term_id, **fields
    )
    if "familiarity" in fields:
        await record(
            "dictionary", "familiarity changed",
            detail=f"{old[0]['name']}: {old[0]['f']} → {fields['familiarity']}",
        )
    else:
        await record("dictionary", "term updated", detail=f"{old[0]['name']}: {', '.join(fields)}")
    return dict(rows[0]["t"])


@router.delete("/terms/{term_id}", status_code=204, response_class=Response)
async def delete_term(term_id: str) -> Response:
    rows = await run_read("MATCH (t:Term {id: $id}) RETURN t", id=term_id)
    if not rows:
        raise HTTPException(404, "term not found")
    term = dict(rows[0]["t"])
    # Remove any uploaded header image from disk.
    _delete_image_file(term_id)
    await run_write(
        """
        MATCH (t:Term {id: $id})
        OPTIONAL MATCH (t)-[:HAS_QUESTION]->(q:DictQuestion)
        OPTIONAL MATCH (t)-[:HAS_NOTE]->(n:DictNote)
        DETACH DELETE q, n, t
        """,
        id=term_id,
    )
    await record("dictionary", "term deleted", detail=term.get("name", term_id))
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# One-click capture from a workspace :Concept
# --------------------------------------------------------------------------- #
@router.post("/from-concept", status_code=201)
async def add_from_concept(body: DictFromConcept) -> dict:
    """Promote a paper concept into the dictionary. Idempotent by name —
    if the term already exists it is returned untouched (no error)."""
    existing = await run_read("MATCH (t:Term {name: $name}) RETURN t", name=body.name)
    if existing:
        result = dict(existing[0]["t"])
        result["_already"] = True
        return result
    tid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (t:Term {
            id: $id, name: $name, eli5: null, definition: $definition,
            familiarity: $familiarity, video: null, domain: $domain,
            source: null, type: $type, starred: false, image: null,
            created_at: $created_at
        })
        RETURN t
        """,
        id=tid, name=body.name, definition=body.definition, domain=body.domain,
        familiarity=body.familiarity, type=body.type, created_at=_now(),
    )
    await record("dictionary", "term added", detail=f"{body.name} (from repository)")
    result = dict(rows[0]["t"])
    result["_already"] = False
    return result


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #
@router.post("/terms/{term_id}/questions", status_code=201)
async def add_question(term_id: str, body: DictQuestionCreate) -> dict:
    qid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (t:Term {id: $tid})
        CREATE (q:DictQuestion {id: $qid, question: $question, answer: $answer})
        CREATE (t)-[:HAS_QUESTION]->(q)
        RETURN q, t.name AS name
        """,
        tid=term_id, qid=qid, question=body.question, answer=body.answer,
    )
    if not rows:
        raise HTTPException(404, "term not found")
    await record("dictionary", "question added", detail=f"{rows[0]['name']}: {body.question}")
    return dict(rows[0]["q"])


@router.put("/terms/{term_id}/questions/{qid}")
async def update_question(term_id: str, qid: str, patch: DictQuestionUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"q.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:Term {{id: $tid}})-[:HAS_QUESTION]->(q:DictQuestion {{id: $qid}}) SET {sets} RETURN q",
        tid=term_id, qid=qid, **fields,
    )
    if not rows:
        raise HTTPException(404, "question not found")
    await record("dictionary", "answer updated" if "answer" in fields else "question updated")
    return dict(rows[0]["q"])


@router.delete("/terms/{term_id}/questions/{qid}", status_code=204, response_class=Response)
async def delete_question(term_id: str, qid: str) -> Response:
    await run_write(
        "MATCH (:Term {id: $tid})-[:HAS_QUESTION]->(q:DictQuestion {id: $qid}) DETACH DELETE q",
        tid=term_id, qid=qid,
    )
    await record("dictionary", "question deleted")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #
@router.post("/terms/{term_id}/notes", status_code=201)
async def add_note(term_id: str, body: DictNoteCreate) -> dict:
    nid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (t:Term {id: $tid})
        CREATE (n:DictNote {id: $nid, text: $text, image: $image, date: $date})
        CREATE (t)-[:HAS_NOTE]->(n)
        RETURN n, t.name AS name
        """,
        tid=term_id, nid=nid, text=body.text, image=body.image, date=_now(),
    )
    if not rows:
        raise HTTPException(404, "term not found")
    await record("dictionary", "note added", detail=rows[0]["name"])
    return dict(rows[0]["n"])


@router.delete("/terms/{term_id}/notes/{nid}", status_code=204, response_class=Response)
async def delete_note(term_id: str, nid: str) -> Response:
    await run_write(
        "MATCH (:Term {id: $tid})-[:HAS_NOTE]->(n:DictNote {id: $nid}) DETACH DELETE n",
        tid=term_id, nid=nid,
    )
    await record("dictionary", "note deleted")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Related terms (bidirectional)
# --------------------------------------------------------------------------- #
@router.post("/terms/{term_id}/related/{target_id}", status_code=201)
async def link_related(term_id: str, target_id: str) -> dict:
    if term_id == target_id:
        raise HTTPException(400, "cannot link a term to itself")
    rows = await run_write(
        """
        MATCH (a:Term {id: $a}), (b:Term {id: $b})
        MERGE (a)-[:RELATED_TO]->(b)
        MERGE (b)-[:RELATED_TO]->(a)
        RETURN a.name AS an, b.name AS bn
        """,
        a=term_id, b=target_id,
    )
    if not rows:
        raise HTTPException(404, "one or both terms not found")
    await record("dictionary", "terms linked", detail=f"{rows[0]['an']} ↔ {rows[0]['bn']}")
    return {"ok": True}


@router.delete("/terms/{term_id}/related/{target_id}", status_code=204, response_class=Response)
async def unlink_related(term_id: str, target_id: str) -> Response:
    await run_write(
        """
        MATCH (a:Term {id: $a})-[r1:RELATED_TO]->(b:Term {id: $b})
        MATCH (b)-[r2:RELATED_TO]->(a)
        DELETE r1, r2
        """,
        a=term_id, b=target_id,
    )
    await record("dictionary", "terms unlinked")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Header image — upload / serve / remove
# --------------------------------------------------------------------------- #
def _image_path_for(term_id: str) -> Path | None:
    """Return the on-disk image for a term id, if one exists (any extension)."""
    d = settings.dictionary_images
    if not d.exists():
        return None
    for f in d.glob(f"{term_id}.*"):
        return f
    return None


def _delete_image_file(term_id: str) -> None:
    p = _image_path_for(term_id)
    if p:
        p.unlink(missing_ok=True)


@router.post("/terms/{term_id}/image")
async def upload_image(term_id: str, file: UploadFile = File(...)) -> dict:
    rows = await run_read("MATCH (t:Term {id: $id}) RETURN t.name AS name", id=term_id)
    if not rows:
        raise HTTPException(404, "term not found")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMG_EXTS:
        raise HTTPException(400, f"unsupported image type '{ext or '?'}' (png/jpg/gif/webp/svg)")

    settings.dictionary_images.mkdir(parents=True, exist_ok=True)
    _delete_image_file(term_id)  # clear any previous extension
    dest = settings.dictionary_images / f"{term_id}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    # A cache-busting query param makes the browser re-fetch after replace.
    url = f"/api/synapse/dictionary/images/{dest.name}?v={int(dest.stat().st_mtime)}"
    await run_write("MATCH (t:Term {id: $id}) SET t.image = $url RETURN t", id=term_id, url=url)
    await record("dictionary", "image set", detail=rows[0]["name"])
    return {"image": url}


@router.delete("/terms/{term_id}/image", status_code=204, response_class=Response)
async def delete_image(term_id: str) -> Response:
    _delete_image_file(term_id)
    await run_write("MATCH (t:Term {id: $id}) SET t.image = null", id=term_id)
    await record("dictionary", "image removed")
    return Response(status_code=204)


@router.get("/images/{filename}")
async def serve_image(filename: str) -> FileResponse:
    # Guard against path traversal — only serve flat files from the image dir.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "bad filename")
    path = settings.dictionary_images / filename
    if not path.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(path)


# =========================================================================== #
# PDF / TEXT SCANNER — frequency-based candidate extraction
# =========================================================================== #
# Spec is explicit: NOT LLM-powered in the prototype. This is the exact
# algorithm it describes, so results are deterministic and explainable.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "is", "it", "that", "this", "by", "with", "from", "as", "are", "was",
    "were", "be", "been", "have", "has", "had", "do", "does", "did", "will",
    "would", "shall", "should", "may", "might", "can", "could", "not", "no",
    "nor", "so", "yet", "also", "very", "much", "more", "most", "than", "then",
    "when", "where", "which", "who", "whom", "what", "how", "why", "all",
    "each", "every", "both", "few", "many", "some", "any", "such", "only",
    "own", "same", "too", "just", "already", "always", "never", "often",
    "sometimes", "usually",
}


@router.post("/scan")
async def scan_text(body: ScanRequest) -> dict:
    """Pull candidate terms out of pasted paper text, ranked by frequency.

    Single words and two-word phrases (bigrams where neither half is a
    stopword). Candidates already in the dictionary are flagged so the UI can
    show them as ✓ and block re-adding.
    """
    import re as _re
    from collections import Counter

    cleaned = _re.sub(r"[^a-z0-9 \-]", " ", (body.text or "").lower())
    words = [w for w in cleaned.split() if len(w) > 2]

    counts: Counter = Counter(w for w in words if w not in _STOPWORDS)
    for a, b in zip(words, words[1:]):
        if a not in _STOPWORDS and b not in _STOPWORDS and len(a) > 2 and len(b) > 2:
            counts[f"{a} {b}"] += 1

    limit = max(1, min(body.limit, 300))
    top = counts.most_common(limit)
    if not top:
        return {"candidates": [], "total_words": len(words)}

    rows = await run_read(
        "MATCH (t:Term) WHERE toLower(t.name) IN $names RETURN toLower(t.name) AS n",
        names=[t for t, _ in top],
    )
    existing = {r["n"] for r in rows}
    return {
        "total_words": len(words),
        "candidates": [
            {"term": t, "count": c, "in_dict": t in existing,
             "words": 2 if " " in t else 1}
            for t, c in top
        ],
    }


@router.post("/bulk-add", status_code=201)
async def bulk_add_terms(body: BulkAddTerms) -> dict:
    """Create stub entries from the scanner — name + familiarity 0, everything
    else blank for the user to fill in later. Existing names are skipped, not
    duplicated (:Term.name is unique)."""
    # Dedupe within the request as well as against the store — :Term.name is
    # unique, so the same name twice in one payload would blow up the second
    # CREATE and fail the whole batch.
    seen: set[str] = set()
    wanted: list[str] = []
    for t in body.terms:
        t = (t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            wanted.append(t)
    if not wanted:
        raise HTTPException(400, "no terms given")
    rows = await run_read(
        "MATCH (t:Term) WHERE toLower(t.name) IN $names RETURN toLower(t.name) AS n",
        names=[w.lower() for w in wanted],
    )
    existing = {r["n"] for r in rows}
    fresh = [w for w in wanted if w.lower() not in existing]
    now = datetime.now(timezone.utc).isoformat()
    for name in fresh:
        await run_write(
            """
            CREATE (t:Term {id: $id, name: $name, eli5: '', definition: '',
                            familiarity: 0, video: '', domain: '', source: 'scanner',
                            type: 'term', starred: false, created_at: $now})
            """,
            id=str(uuid.uuid4()), name=name, now=now,
        )
    if fresh:
        await record("dictionary", "bulk added", detail=f"{len(fresh)} terms from scanner")
    return {"added": len(fresh), "skipped": len(wanted) - len(fresh), "terms": fresh}
