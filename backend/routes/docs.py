"""/api/docs — Documents, the Mainframe word processor (Mainframe-level).

Write long-form text the way you would in a cloud editor, except the file is
yours: every document is a **real file on disk** under `~/.mainframe/documents/`
(`.md`, `.tex` or `.txt`), organised into folders that are real directories.
Neo4j holds only the metadata — title, folder, format, timestamps — and a
relative path pointing at the file. Open a document in vim, grep the folder,
rsync it to a backup: nothing here needs this app to stay readable.

Autosave keeps a rolling snapshot history under `documents/.history/<id>/`, so
an overwrite is recoverable without a version-control ceremony.

A document can also say what it is PART OF — a project, a paper, an idea, a
decomposition node — through the same `:ABOUT` relationship the rest of
Mainframe uses, and can be **pushed**: a timestamped work session that puts a ★
on that day's contribution square. Push a document that belongs to a project and
the time counts toward the project too.
"""
from __future__ import annotations

import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

import mdrender
from activity import record
from config import settings
from db import run_read, run_write
from models import (DocumentContent, DocumentCreate, DocumentPush, DocumentUpdate,
                    WorkSessionCreate)
from routes.papers import _LINK_LABEL
from routes.work import create_session

router = APIRouter(prefix="/api/docs", tags=["docs"])

EXT = {"markdown": ".md", "latex": ".tex", "plain": ".txt"}
# What an uploaded file is taken to be. Anything else is refused rather than
# guessed at — a .docx renamed to .md is not a document this app can edit.
IMPORT_FORMAT = {".md": "markdown", ".markdown": "markdown", ".mdown": "markdown",
                 ".tex": "latex", ".latex": "latex",
                 ".txt": "plain", ".text": "plain", "": "plain"}
# Snapshots are for recovering a bad overwrite, not for a full history: one per
# document per interval, newest kept.
SNAPSHOT_EVERY_S = 300
SNAPSHOT_KEEP = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    p = Path(settings.documents_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(text: str, fallback: str = "untitled") -> str:
    """Filesystem-safe stem. Accents are folded rather than dropped so
    'Résumé' becomes 'resume' instead of 'rsum'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_]+", "-", text)[:60].strip("-") or fallback


def _safe_folder(folder: str) -> str:
    """Folders are real directories, so they get the paranoid treatment:
    each segment slugged, depth capped, `..` impossible by construction."""
    parts = [_slug(p, "") for p in (folder or "").replace("\\", "/").split("/")]
    return "/".join([p for p in parts if p][:3])


def _abs(rel: str) -> Path:
    """Resolve a stored relative path, refusing anything outside the root.

    The path in Neo4j is only ever written by `_file_for`, but a corrupted or
    hand-edited value must not be able to read /etc/passwd.
    """
    root = _root().resolve()
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise HTTPException(400, "document path escapes the documents directory")
    return p


def _file_for(doc_id: str, title: str, folder: str, fmt: str) -> Path:
    """Where a document's file belongs. The id suffix keeps two documents with
    the same title in the same folder from colliding."""
    d = _root() / _safe_folder(folder) if _safe_folder(folder) else _root()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(title)}-{doc_id[:8]}{EXT.get(fmt, '.txt')}"


def _rel(path: Path) -> str:
    return str(path.relative_to(_root().resolve() if path.is_absolute() else _root()))


def _read(rel: str) -> str:
    p = _abs(rel)
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="replace")


def _snapshot(doc_id: str, path: Path) -> None:
    """Copy the current file aside before it's overwritten, at most once per
    SNAPSHOT_EVERY_S. Best-effort — a failed snapshot must never fail a save."""
    if not path.is_file():
        return
    try:
        hist = _root() / ".history" / doc_id
        hist.mkdir(parents=True, exist_ok=True)
        existing = sorted(hist.iterdir(), key=lambda p: p.stat().st_mtime)
        now = datetime.now(timezone.utc).timestamp()
        if existing and now - existing[-1].stat().st_mtime < SNAPSHOT_EVERY_S:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, hist / f"{stamp}{path.suffix}")
        for old in sorted(hist.iterdir(), key=lambda p: p.stat().st_mtime)[:-SNAPSHOT_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


# What a document can say it is part of. Same table the Papers and Projects
# views use, so "part of" reads the same everywhere.
#
# `-[:FOR]->(:Project)` is the narrower, second question: not what the document
# is about, but whose hours it is. It is the edge the work totals aggregate over,
# so it is read back on every document rather than fetched separately — the rail
# shows an hour count against every title.
_FOR = """
OPTIONAL MATCH (d)-[:ABOUT]->(t)
OPTIONAL MATCH (d)-[:FOR]->(fp:Project)
OPTIONAL MATCH (w:WorkSession)-[:WORKED_ON]->(d)
WITH d, coalesce(t.name, t.title, t.label) AS link_title, fp,
     sum(coalesce(w.mins, 0)) AS doc_mins, count(w) AS doc_sessions
"""
_DOC_RETURN = """
RETURN d{.*, link_title: link_title,
           project_id: fp.id, project_name: fp.name,
           mins: doc_mins, session_count: doc_sessions} AS d
"""
_ABOUT = _FOR + _DOC_RETURN


async def _get(doc_id: str) -> dict:
    rows = await run_read("MATCH (d:Document {id: $id}) " + _ABOUT, id=doc_id)
    if not rows:
        raise HTTPException(404, "document not found")
    return dict(rows[0]["d"])


async def _set_for(doc_id: str, project_id: str | None) -> None:
    """Bind the document to the project its hours belong to, or clear it.

    At most one project: the old edge goes before the new one is drawn, so
    re-binding replaces rather than accumulating. The project's NAME is never
    copied onto the document — it is read back through the relationship, so
    renaming the project over there can't leave a stale name here.
    """
    await run_write("MATCH (:Document {id: $id})-[r:FOR]->() DELETE r", id=doc_id)
    if not project_id:
        return
    rows = await run_write(
        """
        MATCH (d:Document {id: $did}), (p:Project {id: $pid})
        MERGE (d)-[:FOR]->(p)
        RETURN p
        """,
        did=doc_id, pid=project_id,
    )
    if not rows:
        raise HTTPException(404, f"no project with id {project_id}")


async def _attach_link(doc_id: str, link_kind: str | None, link_id: str | None) -> None:
    """Point a document at what it is part of. One target at a time — re-linking
    replaces, and an empty link_kind detaches. The title is never copied onto
    the document: it's read back through :ABOUT, so renaming the project over
    there can't leave a stale name here."""
    await run_write("MATCH (:Document {id: $id})-[r:ABOUT]->() DELETE r", id=doc_id)
    if not link_kind or not link_id:
        await run_write(
            "MATCH (d:Document {id: $id}) REMOVE d.link_kind, d.link_id", id=doc_id
        )
        return
    label = _LINK_LABEL.get(link_kind)
    if not label:
        raise HTTPException(400, f"unknown link kind: {link_kind}")
    rows = await run_write(
        f"""
        MATCH (d:Document {{id: $did}}), (n:{label} {{id: $nid}})
        MERGE (d)-[:ABOUT]->(n)
        SET d.link_kind = $kind, d.link_id = $nid
        RETURN d
        """,
        did=doc_id, nid=link_id, kind=link_kind,
    )
    if not rows:
        raise HTTPException(404, f"no {link_kind} with id {link_id}")


# --------------------------------------------------------------------------- #
# List / create
# --------------------------------------------------------------------------- #
@router.get("")
async def list_docs(q: str | None = None, folder: str | None = None) -> list[dict]:
    """Metadata for every document. `q` also searches the file bodies, which is
    the whole point of keeping them as plain text on disk."""
    cypher = "MATCH (d:Document)"
    params: dict = {}
    if folder is not None:
        cypher += " WHERE d.folder = $folder"
        params["folder"] = folder
    cypher += _FOR + "ORDER BY d.starred DESC, d.updated_at DESC" + _DOC_RETURN
    docs = [dict(r["d"]) for r in await run_read(cypher, **params)]
    if q:
        needle = q.strip().lower()
        hits = []
        for d in docs:
            body = _read(d.get("path") or "")
            in_title = needle in (d.get("title") or "").lower()
            at = body.lower().find(needle)
            if in_title or at >= 0:
                if at >= 0:
                    d["excerpt"] = " ".join(body[max(0, at - 60):at + 120].split())
                hits.append(d)
        docs = hits
    return docs


@router.get("/folders")
async def list_folders() -> list[dict]:
    rows = await run_read(
        """
        MATCH (d:Document)
        WITH coalesce(d.folder, '') AS folder, count(d) AS n
        RETURN folder, n ORDER BY folder
        """
    )
    return [{"folder": r["folder"], "count": r["n"]} for r in rows]


@router.post("", status_code=201)
async def create_doc(body: DocumentCreate) -> dict:
    did = str(uuid.uuid4())
    folder = _safe_folder(body.folder)
    path = _file_for(did, body.title, folder, body.format)
    path.write_text(body.content or "", encoding="utf-8")
    rows = await run_write(
        """
        CREATE (d:Document {
            id: $id, title: $title, format: $format, folder: $folder,
            path: $path, starred: false, created_at: $now, updated_at: $now,
            words: $words
        })
        RETURN d
        """,
        id=did, title=body.title.strip() or "Untitled", format=body.format,
        folder=folder, path=_rel(path), now=_now(),
        words=mdrender.stats(body.content)["words"],
    )
    await record("document", "created", detail=body.title[:70], entity_id=did)
    return dict(rows[0]["d"])


# --------------------------------------------------------------------------- #
# Preview — one renderer, shared by the editor and every export
# --------------------------------------------------------------------------- #
@router.post("/render")
async def render_preview(body: DocumentContent) -> dict:
    return {
        "html": mdrender.render(body.content),
        "outline": mdrender.outline(body.content),
        "stats": mdrender.stats(body.content),
    }


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
@router.post("/import", status_code=201)
async def import_doc(file: UploadFile = File(...), folder: str = "") -> dict:
    name = Path(file.filename or "untitled.txt").name
    ext = Path(name).suffix.lower()
    if ext not in IMPORT_FORMAT:
        raise HTTPException(
            400, f"can't import {ext or 'that file'} — documents are .md, .tex or .txt")
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")
    return await create_doc(DocumentCreate(
        title=Path(name).stem, format=IMPORT_FORMAT[ext],
        folder=folder, content=content,
    ))


# --------------------------------------------------------------------------- #
# Read / write one document
# --------------------------------------------------------------------------- #
@router.get("/{doc_id}")
async def get_doc(doc_id: str) -> dict:
    doc = await _get(doc_id)
    content = _read(doc.get("path") or "")
    doc["content"] = content
    doc["stats"] = mdrender.stats(content)
    doc["outline"] = mdrender.outline(content) if doc.get("format") == "markdown" else []
    return doc


@router.put("/{doc_id}/content")
async def save_content(doc_id: str, body: DocumentContent) -> dict:
    doc = await _get(doc_id)
    path = _abs(doc["path"])
    if _read(doc["path"]) == body.content:
        return {"saved": False, "updated_at": doc.get("updated_at"),
                "stats": mdrender.stats(body.content)}
    _snapshot(doc_id, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    stats = mdrender.stats(body.content)
    now = _now()
    await run_write(
        "MATCH (d:Document {id: $id}) SET d.updated_at = $now, d.words = $words",
        id=doc_id, now=now, words=stats["words"],
    )
    await record("document", "edited", detail=doc.get("title", "")[:70], entity_id=doc_id)
    return {"saved": True, "updated_at": now, "stats": stats}


@router.patch("/{doc_id}")
async def update_doc(doc_id: str, patch: DocumentUpdate) -> dict:
    doc = await _get(doc_id)
    sent = patch.model_dump(exclude_unset=True)
    fields = dict(sent)
    # The link is a relationship, not a property to SET. Sending link_kind at
    # all (even "") is what asks to change it; leaving it off leaves it alone.
    relink = "link_kind" in sent or "link_id" in sent
    # Same rule for the project binding: sending project_id at all (null
    # included) is what asks to change it — leaving it off leaves it alone.
    rebind = "project_id" in sent
    fields.pop("link_kind", None)
    fields.pop("link_id", None)
    fields.pop("project_id", None)
    if not sent:
        raise HTTPException(400, "no fields to update")
    if "folder" in fields:
        fields["folder"] = _safe_folder(fields["folder"])
    if "title" in fields:
        fields["title"] = (fields["title"] or "").strip() or "Untitled"

    # Title, folder or format changing means the file moves. Content follows the
    # node, never the other way round.
    if any(k in fields for k in ("title", "folder", "format")):
        old = _abs(doc["path"])
        new = _file_for(doc_id,
                        fields.get("title", doc.get("title", "")),
                        fields.get("folder", doc.get("folder", "")),
                        fields.get("format", doc.get("format", "plain")))
        if new != old:
            content = _read(doc["path"])
            new.parent.mkdir(parents=True, exist_ok=True)
            new.write_text(content, encoding="utf-8")
            old.unlink(missing_ok=True)
            # Leave no empty folders behind after a move.
            try:
                if old.parent != _root().resolve() and not any(old.parent.iterdir()):
                    old.parent.rmdir()
            except OSError:
                pass
            fields["path"] = _rel(new)

    if relink:
        await _attach_link(doc_id, patch.link_kind or None, patch.link_id or None)
    if rebind:
        await _set_for(doc_id, patch.project_id or None)

    fields["updated_at"] = _now()
    sets = ", ".join(f"d.{k} = ${k}" for k in fields)
    await run_write(
        f"MATCH (d:Document {{id: $id}}) SET {sets}", id=doc_id, **fields)
    changed = [k for k in sent if k != "updated_at"]
    await record("document", "updated", detail=", ".join(changed), entity_id=doc_id)
    # Re-read rather than return the SET result — link_title lives on the
    # relationship and only _get resolves it.
    return await _get(doc_id)


# --------------------------------------------------------------------------- #
# Push — a timestamped mark that work on this document happened
# --------------------------------------------------------------------------- #
@router.post("/{doc_id}/push")
async def push_doc(doc_id: str, body: DocumentPush) -> dict:
    """Record a push — writes a work session flagged `pushed`, which puts a ★ on
    that day's contribution square and lands a row in the work database.

    The session is filed against the document. When the document is FOR a
    project, it's also joined to that project, so the project's hours and
    contribution squares include the writing done for it — which is the whole
    point of binding a document to a project.
    """
    doc = await _get(doc_id)
    session = await create_session(WorkSessionCreate(
        date=body.date,
        mins=body.mins,
        module="mainframe",
        ref_kind="document",
        ref_id=doc_id,
        ref_title=doc.get("title", ""),
        what=body.note or "pushed",
        pushed=True,
        doc_id=doc_id,
    ))
    if doc.get("project_id"):
        await run_write(
            """
            MATCH (w:WorkSession {id: $wid}), (p:Project {id: $pid})
            MERGE (w)-[:ON]->(p)
            """,
            wid=session["id"], pid=doc["project_id"],
        )
    return {"pushed": True, "date": session["date"], "session_id": session["id"],
            "project": doc.get("project_name")}


@router.post("/{doc_id}/duplicate", status_code=201)
async def duplicate_doc(doc_id: str) -> dict:
    doc = await _get(doc_id)
    return await create_doc(DocumentCreate(
        title=f"{doc.get('title', 'Untitled')} (copy)",
        format=doc.get("format", "markdown"),
        folder=doc.get("folder", ""),
        content=_read(doc.get("path") or ""),
    ))


@router.delete("/{doc_id}", status_code=204, response_class=Response)
async def delete_doc(doc_id: str) -> Response:
    doc = await _get(doc_id)
    _abs(doc["path"]).unlink(missing_ok=True)
    shutil.rmtree(_root() / ".history" / doc_id, ignore_errors=True)
    await run_write("MATCH (d:Document {id: $id}) DETACH DELETE d", id=doc_id)
    await record("document", "deleted", detail=doc.get("title", "")[:70])
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Snapshots — recovering an overwrite
# --------------------------------------------------------------------------- #
@router.get("/{doc_id}/history")
async def list_history(doc_id: str) -> list[dict]:
    hist = _root() / ".history" / doc_id
    if not hist.is_dir():
        return []
    out = []
    for p in sorted(hist.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({
            "name": p.name,
            "saved_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            "bytes": p.stat().st_size,
        })
    return out


@router.get("/{doc_id}/history/{name}")
async def read_history(doc_id: str, name: str) -> dict:
    p = _root() / ".history" / doc_id / Path(name).name
    if not p.is_file():
        raise HTTPException(404, "snapshot not found")
    return {"name": p.name, "content": p.read_text(encoding="utf-8", errors="replace")}


# --------------------------------------------------------------------------- #
# Export — files you can take elsewhere, plus a print view for PDF
# --------------------------------------------------------------------------- #
_PRINT_CSS = """
@page { margin: 22mm 18mm; }
* { box-sizing: border-box; }
body { max-width: 46rem; margin: 0 auto; padding: 3rem 1.5rem;
       font: 16px/1.7 Georgia, 'Times New Roman', serif; color: #111; background: #fff; }
h1, h2, h3, h4, h5, h6 { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
       line-height: 1.25; margin: 2em 0 .6em; page-break-after: avoid; }
h1 { font-size: 2em; margin-top: 0; } h2 { font-size: 1.5em; } h3 { font-size: 1.2em; }
p, ul, ol, blockquote, table, pre { margin: 0 0 1.1em; }
ul, ol { padding-left: 1.5em; } li { margin: .25em 0; }
li.task { list-style: none; margin-left: -1.2em; }
a { color: #0b57d0; }
code { font: .89em/1.5 ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
       background: #f2f2f4; padding: .12em .35em; border-radius: 3px; }
pre { background: #f7f7f9; border: 1px solid #e3e3e8; border-radius: 6px;
      padding: .9em 1.1em; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #d0d0d8; margin-left: 0; padding-left: 1.1em; color: #444; }
table { border-collapse: collapse; width: 100%; page-break-inside: avoid; }
th, td { border: 1px solid #d8d8de; padding: .45em .7em; text-align: left; }
th { background: #f4f4f7; }
img { max-width: 100%; }
hr { border: none; border-top: 1px solid #ddd; margin: 2em 0; }
.doc-meta { color: #777; font-size: .8em; font-family: sans-serif;
            border-bottom: 1px solid #eee; padding-bottom: .8em; margin-bottom: 2.2em; }
@media print { .doc-meta { display: none; } body { padding: 0; max-width: none; } }
"""


def _page(title: str, inner: str, meta: str = "") -> str:
    import html as _html
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title><style>{_PRINT_CSS}</style></head><body>"
        + (f"<div class='doc-meta'>{_html.escape(meta)}</div>" if meta else "")
        + inner + "</body></html>"
    )


def _as_html(doc: dict, content: str) -> str:
    import html as _html
    if doc.get("format") == "markdown":
        return mdrender.render(content)
    # LaTeX and plain text have no renderer here (no TeX toolchain installed),
    # so they print as their own source — monospaced and intact.
    return "<pre>" + _html.escape(content) + "</pre>"


@router.get("/{doc_id}/print", response_class=HTMLResponse)
async def print_view(doc_id: str) -> HTMLResponse:
    """A clean, styled page whose only job is to be Ctrl+P'd into a PDF."""
    doc = await _get(doc_id)
    content = _read(doc.get("path") or "")
    meta = f"{doc.get('title', '')} · {mdrender.stats(content)['words']} words"
    return HTMLResponse(_page(doc.get("title", "Document"), _as_html(doc, content), meta))


@router.get("/{doc_id}/export")
async def export_doc(doc_id: str, fmt: str = "source"):
    """`source` downloads the file itself; `html` renders it first."""
    doc = await _get(doc_id)
    stem = _slug(doc.get("title", ""), "document")
    if fmt == "html":
        content = _read(doc.get("path") or "")
        page = _page(doc.get("title", "Document"), _as_html(doc, content))
        await record("document", "exported", detail=f"{doc.get('title','')[:50]} → html",
                     entity_id=doc_id)
        return HTMLResponse(page, headers={
            "Content-Disposition": f'attachment; filename="{stem}.html"'})
    path = _abs(doc["path"])
    if not path.is_file():
        raise HTTPException(404, "the document's file is missing from disk")
    await record("document", "exported", detail=f"{doc.get('title','')[:50]} → {path.suffix}",
                 entity_id=doc_id)
    return FileResponse(path, filename=f"{stem}{path.suffix}", media_type="text/plain")
