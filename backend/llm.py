"""Local-first LLM layer.

Provider order:
  1. "ollama"    — POST to the LOCAL Ollama server (localhost:11434). No cloud.
  2. "heuristic" — pure-Python parsing, zero dependencies, always available.

Every task falls back to the heuristic if Ollama is unreachable or returns junk,
so ingest NEVER fails just because a model is offline. Each call is logged and
can be re-triggered with a custom prompt (the routes expose `prompt_override`).

Tasks implemented here:
  - extract_metadata(text)        title/authors/year/venue/abstract/doi/arxiv
  - extract_concepts(text)        key concepts for pre-read familiarity
  - extract_kg(text)              frozen "auto" knowledge graph (nodes+edges)
  - parse_references(refs_text)   list of {title, authors, year}
  - suggest_ideas(annotations)    optional research-question suggestions
"""
from __future__ import annotations

import json
import logging
import re

import refparse
from typing import Any

import httpx

from config import settings

log = logging.getLogger("synapse.llm")


# --------------------------------------------------------------------------- #
# Ollama transport
# --------------------------------------------------------------------------- #
async def _ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_host}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def _ollama_json(system: str, user: str, prompt_override: str | None = None) -> dict | None:
    """Ask Ollama for JSON. Returns a parsed dict, or None on any failure."""
    sys_prompt = prompt_override or system
    payload = {
        "model": settings.ollama_model,
        "system": sys_prompt,
        "prompt": user,
        "stream": False,
        "format": "json",  # Ollama constrains output to valid JSON
        "options": {"temperature": 0.1},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
            r = await client.post(f"{settings.ollama_host}/api/generate", json=payload)
            r.raise_for_status()
            body = r.json()
        raw = body.get("response", "").strip()
        log.info("ollama ok (model=%s, %d chars)", settings.ollama_model, len(raw))
        return _loads_lenient(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("ollama call failed: %s", exc)
        return None


def _loads_lenient(raw: str) -> dict | None:
    """Parse JSON, tolerating code fences or leading prose."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


async def _use_ollama(prompt_override: str | None) -> bool:
    return settings.llm_provider == "ollama" and await _ollama_available()


# --------------------------------------------------------------------------- #
# Task: metadata extraction
# --------------------------------------------------------------------------- #
_META_SYS = (
    "You extract bibliographic metadata from the first pages of an academic "
    "paper. Return ONLY JSON with keys: title (string), authors (array of "
    "strings), year (integer or null), venue (string or null), abstract "
    "(string or null), doi (string or null), arxiv_id (string or null). "
    "Use null when unknown. Do not invent values."
)


# Below this much text there is nothing to extract FROM, and a model asked to
# find a title in an empty string will supply one from memory — a scanned book
# came back as "Deep Residual Learning for Image Recognition". Refusing to ask
# is the fix; a wrong title that looks plausible is worse than no title.
META_MIN_CHARS = 120


def title_from_filename(filename: str | None) -> str:
    """`C-programming-langauge-book.pdf` → `C programming langauge book`.

    Deliberately not cleverer than this. It's a placeholder to be corrected by
    hand, and it has the one property that matters: it can't be wrong about
    something it didn't read.
    """
    if not filename:
        return "Untitled"
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename).strip()
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or "Untitled"


async def extract_metadata(head_text: str, prompt_override: str | None = None,
                           filename: str | None = None) -> dict:
    """Pull bibliographic metadata out of a PDF's opening pages.

    `_source` says where the answer came from — ollama, heuristic, or filename
    when the document gave us too little to read. Callers surface it so a guess
    is never mistaken for a reading.
    """
    if len((head_text or "").strip()) < META_MIN_CHARS:
        out = _normalize_metadata({"title": title_from_filename(filename)})
        out["_source"] = "filename"
        out["_no_text"] = True
        return out

    result: dict | None = None
    if await _use_ollama(prompt_override):
        result = await _ollama_json(_META_SYS, head_text[:6000], prompt_override)
    if not result or not result.get("title"):
        result = _heuristic_metadata(head_text)
        result["_source"] = "heuristic"
    else:
        result["_source"] = "ollama"
    return _normalize_metadata(result)


def _normalize_metadata(d: dict) -> dict:
    year = d.get("year")
    if isinstance(year, str):
        m = re.search(r"(19|20)\d{2}", year)
        year = int(m.group(0)) if m else None
    authors = d.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in re.split(r",|;| and ", authors) if a.strip()]
    return {
        "title": (d.get("title") or "").strip() or "Untitled",
        "authors": authors,
        "year": year,
        "venue": d.get("venue"),
        "abstract": d.get("abstract"),
        "doi": d.get("doi"),
        "arxiv_id": d.get("arxiv_id"),
        "_source": d.get("_source", "heuristic"),
    }


_ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5}(v\d+)?)", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_URL_RE = re.compile(r"https?://[^\s,;)\]]+", re.IGNORECASE)


def _extract_link(text: str) -> str | None:
    """First URL, else a DOI (as a doi.org URL), else None."""
    u = _URL_RE.search(text)
    if u:
        return u.group(0).rstrip(".")
    d = _DOI_RE.search(text)
    if d:
        return "https://doi.org/" + d.group(0)
    return None


def _heuristic_metadata(text: str) -> dict:
    """No-LLM fallback: title = first substantial line; regex for ids/year."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = ""
    for ln in lines[:15]:
        # skip obvious noise (arxiv stamps, page numbers, all-caps venue banners)
        if _ARXIV_RE.search(ln) or len(ln) < 12:
            continue
        title = ln
        break
    arxiv = _ARXIV_RE.search(text)
    doi = _DOI_RE.search(text)
    years = _YEAR_RE.findall(text[:3000])
    return {
        "title": title or (lines[0] if lines else ""),
        "authors": [],
        "year": int("".join(years[0]) ) if years else None,
        "venue": None,
        "abstract": _guess_abstract(text),
        "doi": doi.group(0) if doi else None,
        "arxiv_id": arxiv.group(1) if arxiv else None,
    }


def _guess_abstract(text: str) -> str | None:
    m = re.search(r"abstract\s*[:\n](.{80,1500}?)(\n\s*\n|introduction)", text, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


# --------------------------------------------------------------------------- #
# Task: concept extraction (for pre-read familiarity assessment)
# --------------------------------------------------------------------------- #
_CONCEPTS_SYS = (
    "You extract key technical concepts a reader should assess familiarity with "
    "before reading this paper. Return ONLY JSON: {\"concepts\": [{\"name\": "
    "string, \"definition\": string, \"domain\": string}]}. 6-15 concepts."
)


async def extract_concepts(text: str, prompt_override: str | None = None) -> list[dict]:
    if await _use_ollama(prompt_override):
        data = await _ollama_json(_CONCEPTS_SYS, text[:6000], prompt_override)
        if data and isinstance(data.get("concepts"), list):
            return [_norm_concept(c) for c in data["concepts"] if c.get("name")]
    return _heuristic_concepts(text)


def _norm_concept(c: dict) -> dict:
    return {
        "name": str(c.get("name", "")).strip(),
        "definition": c.get("definition"),
        "domain": c.get("domain"),
    }


def _heuristic_concepts(text: str) -> list[dict]:
    """Fallback: capitalised multiword phrases + acronyms as concept candidates."""
    candidates: dict[str, int] = {}
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text):
        candidates[m.group(1)] = candidates.get(m.group(1), 0) + 1
    for m in re.finditer(r"\b([A-Z]{2,6})\b", text):
        candidates[m.group(1)] = candidates.get(m.group(1), 0) + 1
    ranked = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": name, "definition": None, "domain": None} for name, _ in ranked[:12]]


# --------------------------------------------------------------------------- #
# Task: auto knowledge-graph extraction (frozen "auto" layer)
# --------------------------------------------------------------------------- #
_KG_SYS = (
    "You build a knowledge graph from an academic paper. Extract entities "
    "(concepts, methods, datasets, results) and relationships between them. "
    "Return ONLY JSON: {\"nodes\": [{\"name\": string, \"type\": string}], "
    "\"edges\": [{\"source\": string, \"target\": string, \"label\": string}]}. "
    "Node 'type' is one of: concept, method, dataset, result, metric. Edge "
    "'label' is a short relation like USES, ENABLES, IMPROVES, PART_OF, "
    "EVALUATED_ON. 8-20 nodes."
)


async def extract_kg(text: str, prompt_override: str | None = None) -> dict:
    if await _use_ollama(prompt_override):
        data = await _ollama_json(_KG_SYS, text[:8000], prompt_override)
        if data and isinstance(data.get("nodes"), list):
            nodes = [{"name": str(n.get("name", "")).strip(), "type": n.get("type", "concept")}
                     for n in data["nodes"] if n.get("name")]
            edges = [{"source": e.get("source"), "target": e.get("target"),
                      "label": e.get("label", "RELATES")}
                     for e in data.get("edges", [])
                     if e.get("source") and e.get("target")]
            return {"nodes": nodes, "edges": edges, "_source": "ollama"}
    # Heuristic fallback: concepts as nodes, no confident edges.
    concepts = _heuristic_concepts(text)
    return {
        "nodes": [{"name": c["name"], "type": "concept"} for c in concepts],
        "edges": [],
        "_source": "heuristic",
    }


# --------------------------------------------------------------------------- #
# Task: reference parsing
# --------------------------------------------------------------------------- #
_REFS_SYS = (
    "You parse a paper's reference list. Return ONLY JSON: {\"references\": "
    "[{\"title\": string, \"authors\": array of strings, \"year\": integer or "
    "null, \"link\": string or null}]}. One object per cited work. `link` is the "
    "URL or DOI if the reference contains one (e.g. https://... or doi:10.x/...), "
    "else null."
)


async def parse_references(refs_text: str, prompt_override: str | None = None) -> list[dict]:
    """Parse a bibliography, in windows rather than one truncated slice.

    Three things were losing references here:
      * an 8,000-char cap meant a 24k bibliography lost two thirds of itself
      * an empty model result (`{"references": []}`) counted as an answer, so
        the heuristic fallback never ran
      * the heuristic used the whole citation block as the title, which on an
        author-first bibliography yields an author list, not a title

    Now the text is chunked on citation boundaries, each window is parsed, and
    the model's output is merged with the literal parser's — whichever finds a
    reference the other missed, we keep. Deduped on the normalised title.
    """
    if not refs_text.strip():
        return []

    windows = _chunk_references(refs_text)
    found: list[dict] = []
    if await _use_ollama(prompt_override):
        for w in windows:
            data = await _ollama_json(_REFS_SYS, w, prompt_override)
            if data and isinstance(data.get("references"), list):
                found.extend(r for r in data["references"] if r.get("title"))

    # always run the literal parser too — it never invents a link, and it
    # handles author-year bibliographies the model tends to return nothing for
    literal = _heuristic_references(refs_text)
    return _merge_references(found, literal)


def _chunk_references(text: str, limit: int = 7000) -> list[str]:
    """Split into model-sized windows WITHOUT cutting through a citation."""
    entries = refparse.split_entries(text)
    if not entries:
        return [text[:limit]]
    windows, cur = [], ""
    for e in entries:
        if cur and len(cur) + len(e) + 1 > limit:
            windows.append(cur)
            cur = e
        else:
            cur = (cur + "\n" + e) if cur else e
    if cur:
        windows.append(cur)
    return windows


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _merge_references(model: list[dict], literal: list[dict]) -> list[dict]:
    """Union of both parses, deduped. A literal link always wins over a model
    one — the model fabricates identifiers, the literal parser cannot."""
    out: dict[str, dict] = {}
    for r in list(model) + list(literal):
        key = _norm_title(r.get("title"))
        if len(key) < 4:
            continue
        if key not in out:
            out[key] = dict(r)
        else:
            cur = out[key]
            cur["year"] = cur.get("year") or r.get("year")
    # The literal parser is AUTHORITATIVE about links: it only ever reports one
    # that is physically in the source text. So where it also saw a reference,
    # its link replaces the model's — including when it found none, which is how
    # a fabricated identifier gets dropped rather than surviving by default.
    for r in literal:
        key = _norm_title(r.get("title"))
        if key in out:
            out[key]["link"] = r.get("link")
    return _drop_truncations(list(out.values()))[:400]


def _drop_truncations(refs: list[dict]) -> list[dict]:
    """Remove titles the model cut off mid-word.

    The model sometimes returns a title that stops partway — "Planni" for
    "Planning with…". Dedup can't catch it, because a truncation normalises to a
    *different* key than the full title, so both survive and the fragment reads
    as its own reference.

    A fragment is only dropped when another title starts with it AND the very
    next character there is not a space — i.e. the cut fell inside a word. That
    distinction matters: "World models" is a prefix of "World models are happy"
    but breaks at a word boundary, so it's a real, distinct reference and stays.
    """
    norm = [(re.sub(r"\s+", " ", (r.get("title") or "").strip().lower()), r) for r in refs]
    keep = []
    for text, ref in norm:
        cut = any(
            other != text and other.startswith(text) and len(other) > len(text)
            and other[len(text)] != " "
            for other, _ in norm
        )
        if cut:
            log.info("reference dropped as a mid-word truncation: %r", ref.get("title"))
            continue
        keep.append(ref)
    return keep


def _heuristic_references(refs_text: str) -> list[dict]:
    """Literal parse — same engine the bulk-paste path uses.

    It strips the author run so the title is the title, and only keeps a link
    that literally appears in the text.
    """
    return [
        {"title": e["title"], "authors": [], "year": e["year"], "link": e["link"]}
        for e in refparse.parse(refs_text)
    ]


# --------------------------------------------------------------------------- #
# Task: idea suggestion (optional)
# --------------------------------------------------------------------------- #
_IDEAS_SYS = (
    "Given a reader's highlights and notes on a paper, suggest 3-5 concrete "
    "research questions or project ideas. Return ONLY JSON: {\"ideas\": "
    "[{\"title\": string, \"description\": string}]}."
)


async def suggest_ideas(annotations: str, prompt_override: str | None = None) -> list[dict]:
    if await _use_ollama(prompt_override):
        data = await _ollama_json(_IDEAS_SYS, annotations[:6000], prompt_override)
        if data and isinstance(data.get("ideas"), list):
            return [i for i in data["ideas"] if i.get("title")]
    return []  # no meaningful heuristic — suggestions are optional


# --------------------------------------------------------------------------- #
async def status() -> dict[str, Any]:
    """For /health and the UI: what LLM backing is actually available."""
    ok = await _ollama_available()
    return {
        "provider": settings.llm_provider,
        "ollama_host": settings.ollama_host,
        "ollama_model": settings.ollama_model,
        "ollama_available": ok,
        "effective": "ollama" if (settings.llm_provider == "ollama" and ok) else "heuristic",
    }


# --------------------------------------------------------------------------- #
# Task: diary routing — a day's words, sorted into the modules they belong to
# --------------------------------------------------------------------------- #
# The modules a diary line can land in. "mainframe" is the honest catch-all:
# a reflection about the day itself belongs to no module, and forcing it into
# one would put it where you'd never look for it.
DIARY_MODULES = ("synapse", "pulse", "vision", "vault", "mainframe")

_DIARY_SYS = (
    "You sort a personal diary entry into the areas of life it talks about. "
    "Split the text into consecutive segments, each about ONE area, keeping "
    "the author's original wording verbatim — never summarise, rewrite or "
    "invent. Return ONLY JSON: {\"segments\": [{\"text\": string, \"module\": "
    "string, \"section\": string, \"confidence\": number}]}. "
    "module is one of: synapse (research, reading, papers, thesis, study), "
    "pulse (body, food, training, sleep, health, habits), vision (content, "
    "video, writing, portfolio, audience), vault (money, spending, budget, "
    "purchases, investments), mainframe (the day itself, admin, mood, "
    "anything that fits nowhere else). "
    "section is an optional finer label like 'nutrition' or 'transactions' — "
    "use \"\" when unsure. confidence is 0..1. "
    "Every word of the input must appear in exactly one segment."
)


async def route_diary(text: str, prompt_override: str | None = None) -> list[dict]:
    """Split a mind-dump into segments and say where each belongs.

    Never saves anything and never rewrites the user's words — the caller shows
    the result as a proposal to correct. A wrong guess you can see and fix is
    fine; a wrong guess filed silently is a lost diary entry.
    """
    if await _use_ollama(prompt_override):
        data = await _ollama_json(_DIARY_SYS, text[:6000], prompt_override)
        segs = (data or {}).get("segments")
        if isinstance(segs, list):
            out = [_norm_segment(s) for s in segs if str(s.get("text", "")).strip()]
            # A model that drops half the dump is worse than no model at all:
            # the missing half is silently lost. Keep only a split that gives
            # back most of what went in, otherwise fall through to the rules.
            kept = sum(len(s["text"]) for s in out)
            if out and kept >= 0.6 * len(text.strip()):
                return out
            log.warning("diary split dropped too much text (%d of %d chars) — using heuristic",
                        kept, len(text.strip()))
    return heuristic_route_diary(text)


def _norm_segment(s: dict) -> dict:
    module = str(s.get("module", "")).strip().lower()
    try:
        conf = float(s.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "text": str(s.get("text", "")).strip(),
        "module": module if module in DIARY_MODULES else "mainframe",
        "section": str(s.get("section", "") or "").strip().lower(),
        "confidence": max(0.0, min(1.0, conf)),
    }


# Words that place a line. Deliberately concrete and few: a long list of vague
# words routes everything to the same module. Scored per segment, highest wins,
# ties and blanks go to mainframe.
_DIARY_WORDS: dict[str, tuple[str, ...]] = {
    "vault": ("£", "$", "money", "spent", "spend", "paid", "pay", "cost", "costs",
              "bought", "buy", "price", "invoice", "salary", "budget", "bank",
              "savings", "saving", "invest", "investment", "bill", "bills",
              "subscription", "refund", "rent", "cheap", "expensive", "afford"),
    "pulse": ("ate", "eat", "eating", "meal", "food", "breakfast", "lunch", "dinner",
              "gym", "run", "ran", "workout", "training", "trained", "lift", "sleep",
              "slept", "tired", "weight", "kg", "calories", "protein", "steps",
              "cardio", "stretch", "sick", "pain", "ache", "injury", "medication",
              "recovery", "rested", "habit", "water", "hydrated"),
    "vision": ("video", "youtube", "channel", "script", "edit", "editing", "thumbnail",
               "upload", "uploaded", "film", "filmed", "record", "recorded", "audience",
               "portfolio", "post", "posted", "content", "subscriber", "views",
               "footage", "render"),
    "synapse": ("paper", "papers", "read", "reading", "thesis", "research", "citation",
                "reference", "references", "literature", "supervisor", "phd",
                "study", "studied", "notes", "annotate", "model", "review",
                "abstract", "author", "journal", "arxiv", "lecture", "seminar"),
}


# --------------------------------------------------------------------------- #
# Thinking out loud → the main points
#
# Talking is not writing. A spoken journal circles back, trails off and says the
# same thing three ways, so the useful output is not a tidy split of every word
# (that is what route_diary does for a written dump) but the handful of points
# worth keeping.
#
# THE TRANSCRIPT IS KEPT VERBATIM and every point carries the `quote` it came
# from, so condensing can never lose what you actually said — you can always
# read back the sentence behind a point. Without that this would be the one
# place in the app where a model silently rewrites you.
# --------------------------------------------------------------------------- #
MIND_KINDS = ("idea", "look-at", "note")

_POINTS_SYS = (
    "You read a transcript of someone thinking out loud and pull out the main "
    "points. Return ONLY JSON: {\"points\": [{\"text\": string, "
    "\"kind\": string, \"quote\": string}]}. "
    "text is ONE short sentence naming the point, in the speaker's own words "
    "wherever possible. "
    "kind is one of: idea (something to make, try or build), look-at "
    "(something to go and check, read or find out), note (a fact, a decision "
    "or a feeling worth keeping). "
    "quote is the span of the transcript the point came from, copied verbatim. "
    "Give between 1 and 8 points, in the order they were said. Merge the same "
    "thought said twice into one point. Skip filler, greetings and thinking "
    "noises. Never invent a point that is not in the transcript."
)


async def extract_points(text: str,
                         prompt_override: str | None = None) -> list[dict]:
    """The main points of a spoken journal. Never saves; never the last word.

    Returns a PROPOSAL the caller shows for correction, the same contract
    route_diary has. A point you can see and edit before it lands is the
    difference between a journal you trust and one you stop talking to.
    """
    if await _use_ollama(prompt_override):
        data = await _ollama_json(_POINTS_SYS, text[:6000], prompt_override)
        pts = (data or {}).get("points")
        if isinstance(pts, list):
            out = [_norm_point(p, text) for p in pts
                   if str(p.get("text", "")).strip()]
            if out:
                return out[:8]
        log.warning("point extraction gave nothing usable — using heuristic")
    return heuristic_points(text)


def _norm_point(p: dict, source: str) -> dict:
    kind = str(p.get("kind", "")).strip().lower().replace("_", "-")
    if kind in ("look at", "lookat", "check"):
        kind = "look-at"
    if kind not in MIND_KINDS:
        kind = "note"
    # A quote the model invented is worse than no quote: it would read as
    # "this is what you said" while not being what you said. Only keep one
    # that is actually in the transcript.
    quote = str(p.get("quote", "")).strip()
    if quote and quote.lower() not in source.lower():
        quote = ""
    # Models like to lead with the label they just assigned — "look-at those
    # papers", "idea: build a sweep". The kind is already its own field, so
    # that prefix is noise the user would have to delete by hand every time.
    body = str(p.get("text", "")).strip()
    body = re.sub(r"^(idea|look[- ]?at|note)\s*[:\-\u2014]?\s+", "", body,
                  flags=re.I)
    return {"text": body.strip()[:300], "kind": kind, "quote": quote[:600]}


# Spoken markers of a point worth keeping, and what kind it is. Ordered: the
# first list that matches wins, so "I should look at X" reads as look-at rather
# than idea.
_POINT_WORDS = {
    "look-at": ("look at", "look into", "check", "find out", "read up",
                "have a look", "go and see", "research", "revisit",
                "double check"),
    "idea": ("i could", "i should", "i want to", "i need to", "what if",
             "maybe i", "idea", "we could", "try", "build", "make a",
             "would be good", "it would be", "worth"),
    "note": ("i realised", "i noticed", "turns out", "the problem is",
             "i decided", "i felt", "the thing is", "i keep"),
}


def heuristic_points(text: str, limit: int = 8) -> list[dict]:
    """Rules-only extraction. Always available, and the model's safety net.

    Scores each sentence for the markers people actually use when they say
    something that matters out loud, and keeps the best few IN THE ORDER THEY
    WERE SAID — reordering by score would tell you a story you did not tell.
    Falls back to the longest sentences when nothing scores, because a
    transcript with no markers still has a point in it somewhere.
    """
    # Collapse wrapped lines FIRST. A single newline in a transcript is where
    # the text happened to wrap, not where the speaker stopped — splitting on
    # it cuts sentences in half and every half becomes its own "point". Only a
    # blank line is a real break, and sentence enders do the rest.
    paragraphs = [re.sub(r"\s+", " ", b).strip()
                  for b in re.split(r"\n\s*\n", (text or "").strip()) if b.strip()]
    sentences = [s.strip() for para in paragraphs
                 for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
    if not sentences:
        return []

    scored: list[tuple[int, float, str, str]] = []
    for i, sent in enumerate(sentences):
        low = sent.lower()
        kind, hits = "note", 0
        for k, words in _POINT_WORDS.items():
            n = sum(1 for w in words if w in low)
            if n > hits:
                kind, hits = k, n
        # Very short fragments are usually "yeah", "right", "erm".
        if len(sent.split()) < 4:
            continue
        scored.append((i, hits + min(len(sent.split()), 30) / 100.0, kind, sent))

    if not scored:
        return []
    keep = sorted(scored, key=lambda x: -x[1])[:limit]
    keep.sort(key=lambda x: x[0])
    return [{"text": sent[:300], "kind": kind, "quote": sent[:600]}
            for _i, _sc, kind, sent in keep]


def _score_line(line: str) -> tuple[str, float]:
    low = line.lower()
    scores = {m: sum(1 for w in words if w in low) for m, words in _DIARY_WORDS.items()}
    best = max(scores, key=lambda m: scores[m])
    hits = scores[best]
    if hits == 0 or list(scores.values()).count(hits) > 1:
        return "mainframe", 0.3
    # Two independent hits is a real signal; one is a guess worth showing.
    return best, 0.75 if hits > 1 else 0.5


def heuristic_route_diary(text: str) -> list[dict]:
    """Rules-only split. Always available, and the model's safety net.

    Splits on blank lines first — a paragraph break is the author already
    telling you where one thought ends. Falls back to sentences for a wall of
    text, then merges neighbours that landed in the same module so you get a
    handful of segments to check rather than thirty.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) <= 1:
        blocks = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip()) if s.strip()]
    if not blocks:
        return []

    out: list[dict] = []
    for block in blocks:
        module, conf = _score_line(block)
        if out and out[-1]["module"] == module:
            out[-1]["text"] += "\n" + block
            out[-1]["confidence"] = max(out[-1]["confidence"], conf)
        else:
            out.append({"text": block, "module": module, "section": "", "confidence": conf})
    return out
