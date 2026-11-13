"""/api/books — the book master record.

A book is a :Paper{kind:'book'} paired with a :Project{kind:'study'} that points
at it:

    (:Project {kind:'study'})-[:ABOUT]->(:Paper {kind:'book'})-[:HAS_INSTANCE]->(:Instance)

ONE BOOK, TWO VIEWS, ONE PAIR. The paper keeps the sessions, the highlights and
the knowledge graph; the project is what a phase claims and what carries hours
into the plan. The alternative — collapsing them into a single node — was
rejected because whichever label lost would take the workspace or the phase with
it. The pairing is drawn with the link_kind/link_id pair the Repository already
uses for project/decomp/idea entries, so nothing new had to be invented to
express "this project IS that book".

The master record itself is GENERATED AND READ-ONLY, like the Master Instance it
grew out of. Nothing here is authored; it assembles from the sessions, so a
session deleted upstream takes its part of the record with it. The only two
things a user writes directly are a chapter's manual done-tick and its estimate,
which live on :BookChapter and are deliberately NOT derivable from sessions.
"""
from __future__ import annotations

import html as _html
import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

import bookref
from activity import record
from db import run_read, run_write
from models import BookChapterUpdate, BookPairingApply, BookBackfillApply
from routes.rows import row_texts

router = APIRouter(prefix="/api/books", tags=["books"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Pairing a book with its project
# --------------------------------------------------------------------------- #
# Enough punctuation and subtitle noise is stripped that "Cooking For Busy
# People" finds "Cooking for Busy People (Second Edition)", without being so
# loose that two different books collide. Matches are PROPOSED, never applied on
# read — see propose_pairing.
# The dash here must be SPACED. An unspaced one lives inside words -- strip on
# that and "Hands-On Gardening with Self-Seeding Plants" becomes "hands", which
# matches every other hyphenated title in the library.
_NOISE = re.compile(r"\(.*?\)|\[.*?\]|\s[–—-]\s.*$|[,:].*$")
_ALNUM = re.compile(r"[^a-z0-9]+")
# Words that carry no identity: every other book is "an introduction to" one.
_STOP = {"the", "a", "an", "and", "of", "for", "to", "with", "in", "on",
         "introduction", "intro", "edition", "volume"}
# Two titles must share at least this many real words before an overlap counts
# as evidence. At one, "Statistics for Field Engineers" matches the unrelated
# "Statistics for Biologists" perfectly, because the only word either has left is
# "statistics".
_MIN_SHARED = 2


def _norm(name: str) -> str:
    return _ALNUM.sub("", _NOISE.sub("", (name or "").lower()))


def _tokens(name: str) -> set[str]:
    words = _ALNUM.sub(" ", (name or "").lower()).split()
    return {w for w in words if w not in _STOP and len(w) > 1}


def _score(book: str, project: str) -> tuple[float, bool]:
    """(score, certain).

    Only an exact or prefix match of the normalised titles is ever reported as
    certain. A shared-word overlap is offered but never trusted: "UK, A Short
    History" IS "United Kingdom A Short History", and no amount of
    string comparison can know that — a person can, in one glance, which is
    what the review step is for.
    """
    nb, np = _norm(book), _norm(project)
    if nb and nb == np:
        return 1.0, True
    if nb and np and (nb.startswith(np) or np.startswith(nb)):
        return 0.95, True
    tb, tp = _tokens(book), _tokens(project)
    shared = tb & tp
    if len(shared) < _MIN_SHARED:
        return 0.0, False
    return len(shared) / min(len(tb), len(tp)), False


# Below this, a name match is not evidence of anything and the book is proposed
# a new project instead of being married to an unrelated one.
_MATCH_FLOOR = 0.6


async def _books() -> list[dict]:
    rows = await run_read(
        """
        MATCH (b:Paper) WHERE b.kind = 'book'
        OPTIONAL MATCH (pr:Project)-[:ABOUT]->(b)
        OPTIONAL MATCH (b)-[:HAS_INSTANCE]->(i:Instance)
        RETURN b.id AS id, b.title AS title, b.authors AS authors,
               b.year AS year, b.status AS status,
               pr.id AS project_id, pr.name AS project_name,
               count(i) AS sessions
        ORDER BY b.title
        """)
    return [dict(r) for r in rows]


@router.get("")
async def list_books() -> list[dict]:
    """Every book, with the project it is paired with (or null)."""
    return await _books()


@router.get("/pairing")
async def propose_pairing() -> dict:
    """The proposed book → project map. READ-ONLY: proposes, never writes.

    Three outcomes per book: already paired, match an existing project by name,
    or create one. Anything below `_MATCH_SURE` is returned with `sure: false`
    so the review step can show it differently — a wrong pairing is worse than
    no pairing, because hours would land on another book's project.
    """
    books = await _books()
    prows = await run_read(
        """
        MATCH (pr:Project)
        OPTIONAL MATCH (pr)-[:ABOUT]->(t)
        RETURN pr.id AS id, pr.name AS name, coalesce(pr.kind, 'study') AS kind,
               t.id AS about_id
        ORDER BY pr.name
        """)
    projects = [dict(r) for r in prows]
    # A project already pointing at something else is not available: re-aiming
    # it would silently detach whatever it was about.
    free = [p for p in projects if not p["about_id"]]

    taken: set[str] = set()
    out = []
    for b in books:
        if b["project_id"]:
            out.append({"book_id": b["id"], "book": b["title"], "action": "already",
                        "project_id": b["project_id"], "project": b["project_name"],
                        "score": 1.0, "sure": True, "sessions": b["sessions"]})
            continue
        best, best_score, best_sure = None, 0.0, False
        for p in free:
            if p["id"] in taken:
                continue
            sc, sure = _score(b["title"], p["name"])
            if sc > best_score:
                best, best_score, best_sure = p, sc, sure
        if best and best_score >= _MATCH_FLOOR:
            taken.add(best["id"])
            out.append({"book_id": b["id"], "book": b["title"], "action": "link",
                        "project_id": best["id"], "project": best["name"],
                        "score": round(best_score, 2),
                        "sure": best_sure,
                        "kind_change": best["kind"] != "study",
                        "sessions": b["sessions"]})
        else:
            out.append({"book_id": b["id"], "book": b["title"], "action": "create",
                        "project_id": None, "project": b["title"],
                        "score": 0.0, "sure": True, "sessions": b["sessions"]})
    return {
        "generated": _now(),
        "counts": {a: sum(1 for x in out if x["action"] == a)
                   for a in ("already", "link", "create")},
        "unsure": [x["book"] for x in out if not x["sure"]],
        "pairs": out,
    }


@router.post("/pairing")
async def apply_pairing(body: BookPairingApply) -> dict:
    """Draw the pairing. Only the rows handed back are applied.

    The review step sends what it approved, not a "yes" to whatever the server
    proposes — so an edited or trimmed map is what lands, and re-reading the
    proposal cannot change the outcome between review and apply.
    """
    linked, created = [], []
    for item in body.pairs:
        brow = await run_read(
            "MATCH (b:Paper {id: $id}) WHERE b.kind = 'book' RETURN b.title AS title",
            id=item.book_id)
        if not brow:
            raise HTTPException(404, f"no book with id {item.book_id}")
        title = brow[0]["title"]

        pid = item.project_id
        if not pid:
            pid = str(uuid.uuid4())
            await run_write(
                """
                CREATE (pr:Project {id: $id, name: $name, note: '', kind: 'study',
                                    created_at: $now, contributes: true, status: 'active'})
                """, id=pid, name=(item.project_name or title).strip(), now=_now())
            created.append(item.project_name or title)
        else:
            # A project claimed for a book is study work by definition.
            await run_write(
                "MATCH (pr:Project {id: $id}) SET pr.kind = 'study'", id=pid)

        rows = await run_write(
            """
            MATCH (pr:Project {id: $pid}), (b:Paper {id: $bid})
            OPTIONAL MATCH (pr)-[old:ABOUT]->()
            DELETE old
            MERGE (pr)-[:ABOUT]->(b)
            SET pr.link_kind = 'paper', pr.link_id = $bid
            RETURN pr.name AS name
            """, pid=pid, bid=item.book_id)
        if not rows:
            raise HTTPException(404, f"no project with id {pid}")
        linked.append({"book": title, "project": rows[0]["name"], "project_id": pid})
        await record("project", "linked", detail=f"{rows[0]['name'][:40]} → book {title[:40]}",
                     entity_id=pid)
    return {"ok": True, "linked": linked, "created": created}


# --------------------------------------------------------------------------- #
# Backfill — chapter and pages out of the old free-text purpose
# --------------------------------------------------------------------------- #
@router.get("/backfill")
async def propose_backfill(book_id: str | None = None) -> dict:
    """What the parser reads out of every book session's `purpose`. READ-ONLY.

    Sessions that already carry a chapter or pages are reported as `skip`: the
    backfill never overwrites a value typed by hand with one guessed from text.
    """
    rows = await run_read(
        """
        MATCH (b:Paper)-[:HAS_INSTANCE]->(i:Instance)
        WHERE b.kind = 'book' AND ($bid IS NULL OR b.id = $bid)
        RETURN b.id AS book_id, b.title AS book, i{.*} AS inst
        ORDER BY b.title, i.version
        """, bid=book_id)
    out = []
    for r in rows:
        inst = r["inst"]
        already = bool((inst.get("chapter") or "").strip()) or inst.get("pages_from") is not None
        parsed = bookref.parse(inst.get("purpose") or "")
        got = {k: v for k, v in parsed.items() if v is not None}
        out.append({
            "instance_id": inst["id"], "book": r["book"], "book_id": r["book_id"],
            "version": inst.get("version"), "purpose": inst.get("purpose") or "",
            "action": "skip" if already else ("fill" if got else "nothing"),
            "parsed": parsed,
        })
    return {
        "generated": _now(),
        "counts": {a: sum(1 for x in out if x["action"] == a)
                   for a in ("fill", "skip", "nothing")},
        "sessions": out,
    }


@router.post("/backfill")
async def apply_backfill(body: BookBackfillApply) -> dict:
    """Write the approved parse onto the named sessions, and nothing else."""
    written = 0
    for item in body.sessions:
        fields = {k: v for k, v in
                  (("chapter", item.chapter), ("pages_from", item.pages_from),
                   ("pages_to", item.pages_to), ("mode", item.mode))
                  if v is not None}
        if not fields:
            continue
        sets = ", ".join(f"i.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (i:Instance {{id: $id}}) SET {sets} RETURN i.id AS id",
            id=item.instance_id, **fields)
        if rows:
            written += 1
    await record("instance", "backfilled", detail=f"{written} book sessions")
    return {"ok": True, "written": written}


# --------------------------------------------------------------------------- #
# Chapters — the two things about a chapter that sessions cannot tell you
# --------------------------------------------------------------------------- #
# A chapter is DONE when it has been both read and worked: at least one `read`
# session and at least one `exercises` session. Reading a chapter and never
# touching its exercises is the failure mode this rule exists to make visible,
# so it is not softened to "read is enough".
#
# The hand tick is the escape hatch for the chapters the rule cannot judge — a
# chapter with no exercises in it, or one you decided was enough. It only ever
# turns a chapter ON. A chapter that satisfies the rule cannot be un-done by
# hand, because the sessions saying you did the work are still there.
async def _chapter_nodes(book_id: str) -> dict[str, dict]:
    rows = await run_read(
        "MATCH (c:BookChapter) WHERE c.book_id = $bid RETURN c{.*} AS c", bid=book_id)
    return {(r["c"].get("chapter") or ""): r["c"] for r in rows}


@router.patch("/{book_id}/chapters/{chapter}")
async def update_chapter(book_id: str, chapter: str, patch: BookChapterUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "done" in fields:
        fields["done_at"] = date.today().isoformat() if fields["done"] else ""
    sets = ", ".join(f"c.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"""
        MATCH (b:Paper {{id: $bid}})
        MERGE (b)-[:HAS_CHAPTER]->(c:BookChapter {{book_id: $bid, chapter: $chapter}})
          ON CREATE SET c.id = $cid, c.created_at = $now, c.done = false, c.estimate_h = 0.0
        SET {sets}
        RETURN c{{.*}} AS c
        """, bid=book_id, chapter=chapter, cid=str(uuid.uuid4()), now=_now(), **fields)
    if not rows:
        raise HTTPException(404, "book not found")
    await record("book", "chapter updated", detail=f"ch {chapter} — {', '.join(fields)}",
                 entity_id=book_id)
    return rows[0]["c"]


# --------------------------------------------------------------------------- #
# The master record
# --------------------------------------------------------------------------- #
def _authors(value) -> str:
    """:Paper.authors is a list of names; the record wants one readable line."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "").strip()


async def _master(book_id: str) -> dict:
    brows = await run_read(
        """
        MATCH (b:Paper {id: $bid})
        OPTIONAL MATCH (pr:Project)-[:ABOUT]->(b)
        RETURN b{.*} AS b, pr.id AS project_id, pr.name AS project_name
        """, bid=book_id)
    if not brows:
        raise HTTPException(404, "book not found")
    book, project_id, project_name = brows[0]["b"], brows[0]["project_id"], brows[0]["project_name"]

    irows = await run_read(
        """
        MATCH (:Paper {id: $bid})-[:HAS_INSTANCE]->(i:Instance)
        OPTIONAL MATCH (q:Question)-[:ON]->(i)
        OPTIONAL MATCH (i)-[:HAS_IMAGE]->(im:Image)
        WITH i, collect(DISTINCT q{.*}) AS questions, collect(DISTINCT im{.*}) AS images
        RETURN i{.*} AS inst, questions, images
        ORDER BY coalesce(i.position, toFloat(i.version)), i.version
        """, bid=book_id)

    # The write-up is + rows on each session now, one thought per row.
    texts = await row_texts([r["inst"].get("id") for r in irows])

    sessions = []
    for r in irows:
        i = r["inst"]
        rt = texts.get(i["id"], {})
        imgs = sorted([im for im in r["images"] if im.get("id")],
                      key=lambda m: (m.get("position") if m.get("position") is not None else 1e15))
        sessions.append({
            "id": i["id"], "version": i.get("version"),
            "date": (i.get("read_date") or (i.get("created_at") or ""))[:10],
            "purpose": i.get("purpose") or "",
            "chapter": (i.get("chapter") or "").strip() or None,
            "mode": i.get("mode") or None,
            "pages_from": i.get("pages_from"), "pages_to": i.get("pages_to"),
            "mins": i.get("mins") or 0,
            "start": i.get("start") or "", "end": i.get("end") or "",
            "understood": rt.get("understood", []),
            "look_into": rt.get("look into", []),
            "notes": rt.get("note", []),
            "questions": [q.get("text", "") for q in r["questions"] if q.get("id")],
            "distractions": [d for d in (i.get("distraction_items") or []) if (d or "").strip()],
            "images": [{"id": m["id"], "name": m.get("name") or "",
                        "url": f"/api/images/{m['id']}/file"} for m in imgs],
        })

    hand = await _chapter_nodes(book_id)
    groups: dict[str, list] = {}
    for s in sessions:
        groups.setdefault(s["chapter"] or "", []).append(s)
    # A chapter that has only ever been ticked or estimated still belongs in the
    # record — it is part of the book's plan even with no sessions on it yet.
    for key in hand:
        groups.setdefault(key, [])

    chapters = []
    for key in sorted(groups, key=lambda k: bookref.chapter_sort_key(k or None)):
        rows = sorted(groups[key], key=lambda s: (s["date"] or "9999", s["version"] or 0))
        modes = {s["mode"] for s in rows}
        by_rule = "read" in modes and "exercises" in modes
        node = hand.get(key, {})
        ticked = bool(node.get("done"))
        chapters.append({
            "chapter": key or None,
            "hours": round(sum(s["mins"] for s in rows) / 60.0, 2),
            "mins": sum(s["mins"] for s in rows),
            "sessions": rows,
            "done": by_rule or ticked,
            # Which of the two made it done, so the record can say so rather
            # than just showing a tick nobody can account for.
            "done_by": "rule" if by_rule else ("hand" if ticked else None),
            "done_at": node.get("done_at") or "",
            "has_read": "read" in modes, "has_exercises": "exercises" in modes,
            "estimate_h": float(node.get("estimate_h") or 0.0),
        })

    dates = sorted(s["date"] for s in sessions if s["date"])
    total_mins = sum(s["mins"] for s in sessions)
    # "no chapter recorded" is a real bucket but not a chapter of the book, so
    # it is excluded from both counts — otherwise the denominator drifts.
    real = [c for c in chapters if c["chapter"]]
    return {
        "generated": _now(),
        "book": {
            "id": book["id"], "title": book.get("title") or "",
            # :Paper.authors is a LIST on the node. Everything downstream wants
            # one line of text, so it is joined here rather than in each caller.
            "authors": _authors(book.get("authors")), "year": book.get("year"),
            "status": book.get("status") or "",
            "project_id": project_id, "project_name": project_name,
        },
        "totals": {
            "hours": round(total_mins / 60.0, 2), "mins": total_mins,
            "sessions": len(sessions),
            "chapters_done": sum(1 for c in real if c["done"]),
            "chapters_total": len(real),
            "first_session": dates[0] if dates else None,
            "last_session": dates[-1] if dates else None,
            "estimate_h": round(sum(c["estimate_h"] for c in real), 2),
        },
        "chapters": chapters,
    }


@router.get("/{book_id}/master")
async def book_master(book_id: str) -> dict:
    """The book's master record: generated, read-only, one document."""
    return await _master(book_id)


# --------------------------------------------------------------------------- #
# Share — the master record as one file you can hand to someone
# --------------------------------------------------------------------------- #
# SELF-CONTAINED OR IT IS NOT A SHARE. Images are inlined as data URIs rather
# than linked to /api/images/..., because a file whose pictures only load while
# Mainframe is running on this machine is not something that can be shown to
# anybody. That is also why there is no PDF writer here: the export is one HTML
# file, and the browser's own print dialog turns it into a PDF without adding a
# rendering engine to a local-first stack. /share renders it to read, /share.html
# downloads the same bytes.
_SHARE_CSS = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font: 15px/1.65 -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #1a1a1f; background: #fff; max-width: 820px; margin: 0 auto; padding: 48px 28px 80px; }
  h1 { font-size: 27px; margin: 0 0 4px; letter-spacing: -.01em; }
  .byline { color: #666; font-size: 14px; margin-bottom: 22px; }
  .totals { display: flex; flex-wrap: wrap; gap: 26px; padding: 16px 20px; margin-bottom: 34px;
            border: 1px solid #e4e4ea; border-radius: 8px; background: #fafafc; }
  .t-v { font-size: 20px; font-weight: 600; }
  .t-l { font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: #777; }
  h2 { font-size: 19px; margin: 34px 0 2px; padding-top: 18px; border-top: 2px solid #1a1a1f; }
  .ch-meta { color: #666; font-size: 13px; margin-bottom: 14px; }
  .done { display: inline-block; padding: 1px 8px; border-radius: 99px; font-size: 11px;
          font-weight: 600; background: #e6f4ea; color: #137333; margin-left: 6px; }
  .open { background: #fdf0e3; color: #995200; }
  .sess { border-left: 3px solid #e0e0e6; padding: 0 0 2px 16px; margin: 0 0 22px; }
  .s-head { font-size: 12px; color: #555; margin-bottom: 8px; }
  .mode { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 10px;
          text-transform: uppercase; letter-spacing: .05em; background: #eef1f6; color: #3c5070;
          font-weight: 600; margin-right: 7px; }
  .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: #888;
         margin: 12px 0 3px; }
  .body { white-space: pre-wrap; }
  ul { margin: 3px 0; padding-left: 20px; }
  figure { margin: 12px 0; }
  figure img { max-width: 100%; border: 1px solid #e0e0e6; border-radius: 5px; display: block; }
  figcaption { font-size: 11px; color: #777; margin-top: 4px; }
  .foot { margin-top: 56px; padding-top: 14px; border-top: 1px solid #eee;
          font-size: 11px; color: #999; }
  @media print {
    body { padding: 0; max-width: none; font-size: 11pt; }
    h2 { page-break-after: avoid; } .sess { page-break-inside: avoid; }
    figure img { max-height: 300px; width: auto; }
  }
"""


def _pages_text(s: dict) -> str:
    lo, hi = s.get("pages_from"), s.get("pages_to")
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is None:
        return f"pp. {lo} →"          # the end page was never written down
    if lo is None:
        return f"to p. {hi}"
    return f"pp. {lo}–{hi}"


async def _inline_image(image_id: str) -> str | None:
    """An image as a data: URI, so the exported file carries its own pictures."""
    import base64
    from pathlib import Path
    rows = await run_read("MATCH (i:Image {id: $id}) RETURN i{.*} AS i", id=image_id)
    if not rows:
        return None
    img = rows[0]["i"]
    path = Path(img.get("path") or "")
    if not path.is_file():
        return None
    mime = img.get("mime_type") or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


async def _share_html(book_id: str) -> tuple[str, str]:
    m = await _master(book_id)
    b, t = m["book"], m["totals"]
    e = _html.escape

    def block(label: str, items: list[str]) -> str:
        return (f"<div class='lbl'>{e(label)}</div><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>") if items else ""

    parts = [f"<h1>{e(b['title'] or 'Untitled book')}</h1>"]
    byline = " · ".join(x for x in (b.get("authors") or "",
                                    str(b.get("year") or "")) if x)
    if byline:
        parts.append(f"<div class='byline'>{e(byline)}</div>")

    span = (f"{t['first_session']} → {t['last_session']}"
            if t["first_session"] else "not started")
    stats = [(f"{t['hours']:.1f}", "hours"), (str(t["sessions"]), "sessions"),
             (f"{t['chapters_done']}/{t['chapters_total']}", "chapters done"),
             (span, "first → last")]
    parts.append("<div class='totals'>" + "".join(
        f"<div><div class='t-v'>{e(v)}</div><div class='t-l'>{e(l)}</div></div>"
        for v, l in stats) + "</div>")

    for ch in m["chapters"]:
        name = f"Chapter {ch['chapter']}" if (ch["chapter"] or "").strip(
        ) and ch["chapter"][0].isdigit() else (ch["chapter"] or "Chapter not recorded").title()
        pill = (f"<span class='done'>done{' · by hand' if ch['done_by'] == 'hand' else ''}</span>"
                if ch["done"] else "<span class='done open'>open</span>")
        parts.append(f"<h2>{e(name)}{pill}</h2>")
        n = len(ch["sessions"])
        parts.append(f"<div class='ch-meta'>{ch['hours']:.1f} h · {n} session"
                     f"{'' if n == 1 else 's'}</div>")
        for s in ch["sessions"]:
            head = " · ".join(x for x in (s["date"], _pages_text(s),
                                          f"{s['mins']} min" if s["mins"] else "") if x)
            mode = f"<span class='mode'>{e(s['mode'])}</span>" if s["mode"] else ""
            body = [f"<div class='s-head'>{mode}{e(head)}</div>"]
            body.append(block("what I understood", s["understood"]))
            if s["questions"]:
                body.append("<div class='lbl'>questions</div><ul>" + "".join(
                    f"<li>{e(q)}</li>" for q in s["questions"]) + "</ul>")
            body.append(block("to look into later", s["look_into"]))
            body.append(block("notes", s["notes"]))
            for im in s["images"]:
                src = await _inline_image(im["id"])
                if src:
                    body.append(f"<figure><img src='{src}' alt='{e(im['name'])}'>"
                                f"<figcaption>{e(im['name'])}</figcaption></figure>")
            if s["distractions"]:
                body.append("<div class='lbl'>distractions</div><ul>" + "".join(
                    f"<li>{e(d)}</li>" for d in s["distractions"]) + "</ul>")
            parts.append("<div class='sess'>" + "".join(body) + "</div>")

    stamp = date.today().isoformat()
    parts.append(f"<div class='foot'>Master record for {e(b['title'] or '')} · "
                 f"generated {stamp} from {t['sessions']} logged session"
                 f"{'' if t['sessions'] == 1 else 's'} · Mainframe</div>")
    title = f"{b['title'] or 'Book'} — master record ({stamp})"
    page = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><style>{_SHARE_CSS}</style></head><body>"
            + "".join(parts) + "</body></html>")
    return page, stamp


@router.get("/{book_id}/share", response_class=HTMLResponse)
async def share_view(book_id: str) -> HTMLResponse:
    """The master record as a page to read, or Ctrl+P into a PDF."""
    page, _ = await _share_html(book_id)
    return HTMLResponse(page)


@router.get("/{book_id}/share.html")
async def share_download(book_id: str) -> HTMLResponse:
    """The same bytes, as a dated download."""
    page, stamp = await _share_html(book_id)
    rows = await run_read("MATCH (b:Paper {id: $id}) RETURN b.title AS t", id=book_id)
    stem = _ALNUM.sub("-", ((rows[0]["t"] if rows else "book") or "book").lower()).strip("-")[:60]
    await record("book", "shared", detail=f"{stem} → html", entity_id=book_id)
    return HTMLResponse(page, headers={
        "Content-Disposition": f'attachment; filename="{stem}-master-record-{stamp}.html"'})


# --------------------------------------------------------------------------- #
# What a phase needs: a book's chapters, as units of work with estimates
# --------------------------------------------------------------------------- #
async def chapter_forecast(project_ids: list[str]) -> dict[str, dict]:
    """Per claimed project that IS a book, its chapters as forecastable tasks.

    A phase claims the PROJECT — the pairing is what makes claiming a book
    possible at all. What the forecast then needs is smaller than the project:
    a book is not one lump of hours, it is a list of chapters, and the ones
    still open are what is actually left to do.

    Deliberately light — no sessions, no images, no prose. The pace endpoint
    calls this for every claimed project on every load, and the master record
    is where the reading happens.
    """
    if not project_ids:
        return {}
    rows = await run_read(
        """
        MATCH (pr:Project)-[:ABOUT]->(b:Paper)
        WHERE pr.id IN $pids AND b.kind = 'book'
        OPTIONAL MATCH (b)-[:HAS_INSTANCE]->(i:Instance)
        WITH pr, b, collect({chapter: coalesce(i.chapter, ''),
                             mode: coalesce(i.mode, ''),
                             mins: coalesce(i.mins, 0)}) AS sess
        OPTIONAL MATCH (b)-[:HAS_CHAPTER]->(c:BookChapter)
        RETURN pr.id AS project_id, b.id AS book_id, b.title AS title,
               sess, collect(c{.*}) AS chapters
        """, pids=project_ids)

    out: dict[str, dict] = {}
    for r in rows:
        hand = {(c.get("chapter") or ""): c for c in r["chapters"] if c.get("chapter") is not None}
        groups: dict[str, list] = {}
        for s in r["sess"]:
            if s.get("chapter") is None:
                continue
            groups.setdefault(s["chapter"] or "", []).append(s)
        for key in hand:
            groups.setdefault(key, [])

        items = []
        for key in sorted(groups, key=lambda k: bookref.chapter_sort_key(k or None)):
            if not key:
                continue                      # "chapter not recorded" is not a task
            rows_ = groups[key]
            modes = {s.get("mode") or "" for s in rows_}
            node = hand.get(key, {})
            done = ("read" in modes and "exercises" in modes) or bool(node.get("done"))
            items.append({
                "chapter": key,
                "done": done,
                "estimate_h": float(node.get("estimate_h") or 0.0),
                "logged_h": round(sum(s.get("mins") or 0 for s in rows_) / 60.0, 2),
                "sessions": len(rows_),
            })
        open_items = [c for c in items if not c["done"]]
        # Only the OPEN chapters' estimates are outstanding. A finished chapter's
        # estimate is spent, and counting it as remaining would make every book
        # look like it had not been started.
        out[r["project_id"]] = {
            "book_id": r["book_id"], "title": r["title"],
            "chapters": items,
            "total": len(items), "done": len(items) - len(open_items),
            "remaining_h": round(sum(c["estimate_h"] for c in open_items), 2),
            "logged_h": round(sum(c["logged_h"] for c in items), 2),
            # An estimate nobody has set is not a forecast of zero; the phase
            # needs to be able to say "this book has no estimates yet".
            "estimated": sum(1 for c in open_items if c["estimate_h"] > 0),
            "unestimated": sum(1 for c in open_items if c["estimate_h"] <= 0),
        }
    return out
