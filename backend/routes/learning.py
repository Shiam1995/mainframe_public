"""/api/learning — Learning Opportunities, a Mainframe-level service.

Sits alongside Tasks and Dictionary: it belongs to no module and every module
feeds it. When you make a mistake or spot something to improve, you log it.

Each opportunity is a living document, not a single entry — it carries a chain
of :LearningNote nodes written over time (observations, things you're trying,
what's working). The card expands into that workspace.

The point of the whole thing is REPEAT DETECTION. Occurrences are grouped by
`kind` — the type of mistake — and the summary reports not just how often a kind
recurs but the *gaps between* occurrences. Widening gaps mean you're improving;
narrowing gaps mean you're logging the same failure faster than you're fixing
it. A raw count alone can't tell those apart.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from activity import record
from db import run_read, run_write

router = APIRouter(prefix="/api/learning", tags=["learning"])

# open → working → resolved. Resolved stays in history but leaves the active tally.
STATUSES = ("open", "working", "resolved")
ACTIVE = ("open", "working")

# What can happen to an option. The whole point of the set is that writing one
# down is NOT a commitment: an idea sits at "option" until you deliberately pick
# it, and the ones you didn't pick stay on the record as "dropped" rather than
# being deleted — next time the same mistake comes round, what you already
# considered and rejected is the most useful thing on the card.
OPTION_STATES = ("option", "chosen", "done", "dropped")
PLANNED = ("chosen", "done")


class LOCreate(BaseModel):
    kind: str = ""                    # the TYPE of mistake — what groups repeats
    what_happened: str                # the short overview — one line
    detail: str = ""                  # the long version: what led to it
    occurred_at: Optional[str] = None  # YYYY-MM-DD; defaults to today
    module: str = "mainframe"
    action: str = ""                  # what I will do about it
    status: str = "open"
    # Both grow one entry at a time. Lists rather than one blob so each idea and
    # each conversation stays a separate thing you can add to, reorder or drop.
    ideas: list[str] = []             # "here's idea one, here's idea two…"
    consulted: list[str] = []         # "asked X this, and this came back"


class LOUpdate(BaseModel):
    kind: Optional[str] = None
    what_happened: Optional[str] = None
    detail: Optional[str] = None
    occurred_at: Optional[str] = None
    module: Optional[str] = None
    action: Optional[str] = None
    status: Optional[str] = None
    ideas: Optional[list[str]] = None
    consulted: Optional[list[str]] = None


class DistractionItem(BaseModel):
    instance_id: str
    text: str
    kind: str
    date: str = ""
    where: str = ""


class DistractionBackfill(BaseModel):
    """The corrected sweep. Entries given the same `kind` become occurrences of
    one pattern — that is what grouping them does."""
    items: list[DistractionItem] = []


class KindIn(BaseModel):
    """A type of mistake, and the high-level habit it rolls up into.

    `name` is what you file an entry under ("missed a deadline"); `group` is the
    bigger pattern it belongs to ("scheduling"). Grouping is what lets separate
    small mistakes show up as one habit.
    """
    name: str
    group: str = ""


class NoteIn(BaseModel):
    text: str


class OptionIn(BaseModel):
    """One thing you could do about a mistake. Born unpicked."""
    text: str
    status: str = "option"


class OptionPatch(BaseModel):
    text: Optional[str] = None
    status: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _norm_kind(kind: str) -> str:
    """Group key for repeats — case and punctuation shouldn't split a pattern."""
    s = re.sub(r"[^a-z0-9 ]", " ", (kind or "").lower())
    return " ".join(s.split())


# Words people put in front of a distraction that don't change what it is.
# "my phone", "the phone", "got distracted by phone" are all "phone", and if
# they each become their own kind then repeat detection — the entire point of
# this module — sees one occurrence of four things instead of four of one.
_KIND_FILLER = re.compile(
    r"^(?:got|getting|get|being|been|was|were|a|an|the|my|some|more|"
    r"distracted\s+by|interrupted\s+by|pulled\s+away\s+by|checked|checking)\s+")


def _strip_filler(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, _KIND_FILLER.sub("", s).strip()
    return s


async def match_kind(text: str) -> str:
    """The kind an occurrence should be filed under, reusing an existing one
    where the text plainly means the same thing.

    AUTOMATIC LOGGING NEEDS THIS. When a human fills the form they see the
    existing kinds and pick one; a machine posting raw free text does not, and
    "phone", "Phone", "my phone" and "phone buzzing" become four kinds that
    never repeat. Matching is deliberately conservative — a wrong merge hides a
    pattern under the wrong name, which is worse than one extra kind — so it
    only reuses a kind on an exact normalised hit, on the same text minus
    filler, or when an existing kind appears as whole words inside it.

    Returns the existing kind's name, or the cleaned-up text as a new one.
    """
    want = _norm_kind(text)
    if not want:
        return ""
    rows = await run_read("MATCH (k:LearningKind) RETURN k.name AS name")
    known = [_norm_kind(r["name"]) for r in rows if (r["name"] or "").strip()]

    if want in known:
        return want
    bare = _strip_filler(want)
    if bare and bare in known:
        return bare
    # An existing kind sitting inside what was typed: "phone" in "phone kept
    # buzzing". Longest first, so "phone notifications" wins over "phone".
    for k in sorted(known, key=len, reverse=True):
        if k and re.search(r"\b" + re.escape(k) + r"\b", want):
            return k
    return bare or want


def _pack(lo: dict, notes: list, options: list) -> dict:
    """Attach the children to an entry, and say in one number how far the
    thinking has got: how many ways out you've written down, and how many of
    them you've actually committed to."""
    lo["notes"] = [n for n in notes if n.get("id")]
    lo["options"] = sorted((o for o in options if o.get("id")),
                           key=lambda o: (o.get("order") if o.get("order") is not None else 0,
                                          o.get("created_at") or ""))
    lo["planned"] = [o for o in lo["options"] if o.get("status") in PLANNED]
    lo["option_count"] = len(lo["options"])
    lo["planned_count"] = len(lo["planned"])
    return lo


async def _one(lid: str) -> dict:
    rows = await run_read(
        """
        MATCH (l:LearningOpportunity {id: $id})
        OPTIONAL MATCH (l)-[:HAS_NOTE]->(n:LearningNote)
        WITH l, n ORDER BY n.created_at
        WITH l, collect(n{.*}) AS notes
        OPTIONAL MATCH (l)-[:HAS_OPTION]->(o:LearningOption)
        RETURN l{.*} AS l, notes, collect(o{.*}) AS options
        """,
        id=lid,
    )
    if not rows:
        raise HTTPException(404, "learning opportunity not found")
    return _pack(rows[0]["l"], rows[0]["notes"], rows[0]["options"])


@router.get("")
async def list_opportunities(status: Optional[str] = None, module: Optional[str] = None) -> list[dict]:
    where, params = [], {}
    if status:
        where.append("l.status = $status"); params["status"] = status
    if module:
        where.append("l.module = $module"); params["module"] = module
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await run_read(
        f"""
        MATCH (l:LearningOpportunity) {clause}
        OPTIONAL MATCH (l)-[:HAS_NOTE]->(n:LearningNote)
        WITH l, n ORDER BY n.created_at
        WITH l, collect(n{{.*}}) AS notes
        OPTIONAL MATCH (l)-[:HAS_OPTION]->(o:LearningOption)
        RETURN l{{.*}} AS l, notes, collect(o{{.*}}) AS options
        ORDER BY l.occurred_at DESC, l.created_at DESC
        """,
        **params,
    )
    out = [_pack(r["l"], r["notes"], r["options"]) for r in rows]
    # annotate each with how many times its kind has been logged
    counts: dict[str, int] = {}
    for lo in out:
        k = _norm_kind(lo.get("kind") or "")
        if k:
            counts[k] = counts.get(k, 0) + 1
    for lo in out:
        lo["kind_count"] = counts.get(_norm_kind(lo.get("kind") or ""), 1)
        lo["repeating"] = lo["kind_count"] > 1
    return out


@router.post("", status_code=201)
async def create_opportunity(body: LOCreate) -> dict:
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    lid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (l:LearningOpportunity {
            id: $id, kind: $kind, what_happened: $what, detail: $detail,
            occurred_at: $when, module: $module, action: $action,
            status: $status, ideas: $ideas, consulted: $consulted, created_at: $now
        })
        """,
        id=lid, kind=body.kind.strip(), what=body.what_happened.strip(),
        detail=body.detail.strip(),
        when=(body.occurred_at or _today())[:10], module=body.module,
        action=body.action, status=body.status,
        ideas=[i.strip() for i in body.ideas if i.strip()],
        consulted=[c.strip() for c in body.consulted if c.strip()],
        now=_now(),
    )
    # Filing under a kind registers it, so the catalogue always reflects what's
    # actually in use rather than needing to be curated separately.
    if body.kind.strip():
        await run_write("MERGE (:LearningKind {name: $n})", n=body.kind.strip().lower())
    await record("task", "learning logged", detail=(body.kind or body.what_happened)[:70],
                 module=body.module if body.module != "mainframe" else None)
    return await _one(lid)


# Backfilling distractions written before they were logged automatically.
#
# THE PROBLEM THE REVIEW SOLVES. Distractions get typed as sentences — "thinking
# about the meeting later", "little bit hungry" — and a sentence makes a
# terrible kind. Filed as typed, twenty-three interruptions become twenty-three
# kinds with one occurrence each, and repeat detection, the entire point of this
# module, reports nothing. So the sweep PROPOSES a kind per entry and you
# correct it before anything is written; entries you give the same kind become
# occurrences of one pattern, which is what grouping means here.
_DISTRACTION_BUCKETS = (
    ("thinking about something else",
     ("thinking", "think", "mind", "conversation", "convestauon", "ghost",
      "arguing", "meditiate", "meditate", "residue", "worry", "wondering")),
    ("phone and notifications",
     ("phone", "discord", "youtube", "youutbe", "linkedin", "notification",
      "message", "icon", "whatsapp", "email", "instagram")),
    ("hunger, thirst and energy",
     ("hungry", "hunger", "food", "meal", "eat", "water", "coffee", "tea",
      "gym", "tired", "sleep")),
    ("interrupted by someone",
     ("dad", "mum", "called", "call from", "supervisor", "meeting", "alarm",
      "flatmate", "knock", "someone")),
    ("lost the thread",
     ("rushed", "understanding", "understand", "paragraph", "pargarph",
      "feeling it", "grab onto", "reread", "lost")),
    ("an open loop from other work",
     ("task", "loop", "decomp", "atlas", "closed", "hanging", "old", "plan",
      "phase", "project")),
    ("desk and surroundings",
     ("pen", "desk", "screen", "chair", "noise", "cold", "hot", "light",
      "moving", "missing")),
)


def suggest_kind(text: str) -> str:
    """A proposed kind for one written-out distraction. A guess, shown for
    correction — never written without being seen."""
    low = (text or "").lower()
    best, hits = "", 0
    for name, words in _DISTRACTION_BUCKETS:
        n = sum(1 for w in words if w in low)
        if n > hits:
            best, hits = name, n
    return best


@router.get("/distractions/pending")
async def pending_distractions() -> dict:
    """Every distraction written on a reading pass that Learning never saw.

    `distractions_logged` on the pass is what "never saw" means, so a pass
    saved since the automatic push landed is correctly skipped and this can be
    run as many times as you like.
    """
    rows = await run_read(
        """
        MATCH (p:Paper)-[:HAS_INSTANCE]->(i:Instance)
        WHERE size(coalesce(i.distraction_items, [])) > 0
        RETURN i.id AS id, i.version AS version, p.title AS paper,
               coalesce(i.read_date, i.created_at, '') AS when,
               coalesce(i.distraction_items, []) AS items,
               coalesce(i.distractions_logged, []) AS done
        ORDER BY when
        """)
    known = {_norm_kind(r["name"]) for r in
             await run_read("MATCH (k:LearningKind) RETURN k.name AS name")}

    out = []
    for r in rows:
        done = set(r["done"])
        for raw in r["items"]:
            text = (raw or "").strip()
            if not text:
                continue
            matched = await match_kind(text)
            # An existing kind that genuinely matches beats a bucket guess —
            # it is evidence from what you have already filed.
            kind = matched if matched in known else (suggest_kind(text) or matched)
            if kind in done:
                continue
            out.append({
                "instance_id": r["id"], "version": r["version"],
                "paper": r["paper"], "date": (r["when"] or "")[:10],
                "text": text, "kind": kind,
                "matched_existing": matched in known,
            })
    return {"pending": out, "kinds": sorted(known)}


@router.post("/distractions/backfill")
async def backfill_distractions(body: DistractionBackfill) -> dict:
    """File the corrected sweep. One occurrence per pass per kind."""
    by_pass: dict[str, set] = {}
    filed = 0
    for it in body.items:
        kind = _norm_kind(it.kind)
        if not kind or not it.text.strip():
            continue
        rows = await run_read(
            "MATCH (i:Instance {id: $id}) "
            "RETURN coalesce(i.distractions_logged, []) AS done", id=it.instance_id)
        if not rows:
            continue
        already = by_pass.setdefault(it.instance_id, set(rows[0]["done"]))
        if kind in already:
            continue
        await log_distraction(it.text, where=it.where or "", skip=None,
                              kind_override=kind, when=it.date or None)
        already.add(kind)
        filed += 1

    for iid, done in by_pass.items():
        await run_write("MATCH (i:Instance {id: $id}) SET i.distractions_logged = $d",
                        id=iid, d=sorted(done))
    await record("task", "distractions backfilled", detail=f"{filed} filed",
                 module="synapse", trigger="system")
    return {"filed": filed}


async def log_distraction(text: str, where: str = "",
                          skip: set[str] | None = None,
                          kind_override: str = "", when: str | None = None) -> str:
    """File one interruption as an occurrence. Returns the kind it went under.

    Called from the reading pass on save (see routes/instances.py). Returns ""
    without writing when this kind is already logged from that pass, so the
    caller can save as many times as it likes.
    """
    text = (text or "").strip()
    if not text:
        return ""
    # The sweep has already been corrected by hand, so its kind wins over
    # anything matching would work out for itself.
    kind = _norm_kind(kind_override) if kind_override else await match_kind(text)
    if not kind or (skip and kind in skip):
        return ""

    lid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (l:LearningOpportunity {
            id: $id, kind: $kind, what_happened: $what, detail: $detail,
            occurred_at: $when, module: 'synapse', action: '',
            status: 'open', ideas: [], consulted: [], created_at: $now,
            source: 'distraction'
        })
        """, id=lid, kind=kind,
        what=f"distracted by {text}"[:200],
        # The words as typed, kept whenever the kind ended up being something
        # else: "phone kept buzzing" filed under "phone" should still be able
        # to show what was actually written.
        detail=(f"“{text}” {where}".strip() if _norm_kind(text) != kind
                else where),
        when=(when or _today())[:10], now=_now())
    await run_write("MERGE (:LearningKind {name: $n})", n=kind)
    await record("task", "distraction logged", detail=kind[:70], module="synapse",
                 trigger="system")
    return kind


# --------------------------------------------------------------------------- #
# Kinds — the types of mistake, and the high-level habits they roll into
# --------------------------------------------------------------------------- #
@router.get("/kinds")
async def list_kinds() -> list[dict]:
    """Every kind, with its group and how many entries are filed under it.

    Kinds in use but never explicitly registered still appear — the catalogue
    describes reality rather than constraining it.
    """
    rows = await run_read(
        """
        MATCH (k:LearningKind)
        OPTIONAL MATCH (l:LearningOpportunity) WHERE toLower(trim(l.kind)) = k.name
        RETURN k.name AS name, coalesce(k.group, '') AS group, count(l) AS uses
        ORDER BY group, name
        """
    )
    return [{"name": r["name"], "group": r["group"], "uses": r["uses"]} for r in rows]


@router.post("/kinds", status_code=201)
async def upsert_kind(body: KindIn) -> list[dict]:
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(400, "a kind needs a name")
    await run_write(
        "MERGE (k:LearningKind {name: $n}) SET k.group = $g",
        n=name, g=body.group.strip().lower(),
    )
    await record("task", "learning kind set", detail=f"{name} → {body.group or 'ungrouped'}")
    return await list_kinds()


@router.delete("/kinds/{name}")
async def delete_kind(name: str) -> list[dict]:
    """Drop a kind from the catalogue. Entries filed under it keep their value —
    removing a label shouldn't rewrite what you wrote."""
    await run_write("MATCH (k:LearningKind {name: $n}) DELETE k", n=name.strip().lower())
    await record("task", "learning kind removed", detail=name)
    return await list_kinds()


@router.patch("/{lid}")
async def update_opportunity(lid: str, patch: LOUpdate) -> dict:
    # exclude_unset, not exclude_none: sending an empty list is how you clear
    # every idea or consultation, and exclude_none would drop a legitimate [].
    fields = patch.model_dump(exclude_unset=True)
    fields = {k: v for k, v in fields.items() if v is not None}
    if fields.get("status") and fields["status"] not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    if fields:
        sets = ", ".join(f"l.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (l:LearningOpportunity {{id: $id}}) SET {sets} RETURN l", id=lid, **fields)
        if not rows:
            raise HTTPException(404, "learning opportunity not found")
        await record("task", "learning updated", detail=", ".join(fields))
    return await _one(lid)


@router.delete("/{lid}", status_code=204, response_class=Response)
async def delete_opportunity(lid: str) -> Response:
    await run_write(
        "MATCH (l:LearningOpportunity {id: $id}) "
        "OPTIONAL MATCH (l)-[:HAS_NOTE]->(n:LearningNote) DETACH DELETE n, l",
        id=lid,
    )
    await record("task", "learning deleted", detail=lid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Notes — the living document inside each card
# --------------------------------------------------------------------------- #
@router.post("/{lid}/notes", status_code=201)
async def add_note(lid: str, body: NoteIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "a note needs text")
    rows = await run_write(
        """
        MATCH (l:LearningOpportunity {id: $id})
        CREATE (l)-[:HAS_NOTE]->(n:LearningNote {id: $nid, text: $text, created_at: $now})
        RETURN n
        """,
        id=lid, nid=str(uuid.uuid4()), text=body.text.strip(), now=_now(),
    )
    if not rows:
        raise HTTPException(404, "learning opportunity not found")
    return await _one(lid)


@router.patch("/{lid}/notes/{nid}")
async def edit_note(lid: str, nid: str, body: NoteIn) -> dict:
    await run_write(
        "MATCH (:LearningOpportunity {id: $id})-[:HAS_NOTE]->(n:LearningNote {id: $nid}) "
        "SET n.text = $text, n.updated_at = $now",
        id=lid, nid=nid, text=body.text.strip(), now=_now(),
    )
    return await _one(lid)


@router.delete("/{lid}/notes/{nid}")
async def delete_note(lid: str, nid: str) -> dict:
    await run_write(
        "MATCH (:LearningOpportunity {id: $id})-[:HAS_NOTE]->(n:LearningNote {id: $nid}) DETACH DELETE n",
        id=lid, nid=nid,
    )
    return await _one(lid)


# --------------------------------------------------------------------------- #
# Options — the ways out, and which of them you actually picked
# --------------------------------------------------------------------------- #
@router.post("/{lid}/options", status_code=201)
async def add_option(lid: str, body: OptionIn) -> dict:
    """Write down one thing you could do. It starts unpicked on purpose —
    listing what you *could* do is a different act from deciding."""
    if not body.text.strip():
        raise HTTPException(400, "an option needs some words")
    if body.status not in OPTION_STATES:
        raise HTTPException(400, f"status must be one of {OPTION_STATES}")
    rows = await run_write(
        """
        MATCH (l:LearningOpportunity {id: $id})
        OPTIONAL MATCH (l)-[:HAS_OPTION]->(x:LearningOption)
        WITH l, count(x) AS n
        CREATE (l)-[:HAS_OPTION]->(o:LearningOption {
            id: $oid, text: $text, status: $status, order: n,
            created_at: $now, decided_at: $decided
        })
        RETURN o
        """,
        id=lid, oid=str(uuid.uuid4()), text=body.text.strip(), status=body.status,
        now=_now(), decided=_now() if body.status in PLANNED else "",
    )
    if not rows:
        raise HTTPException(404, "learning opportunity not found")
    await record("task", "option written", detail=body.text.strip()[:70])
    return await _one(lid)


@router.patch("/{lid}/options/{oid}")
async def edit_option(lid: str, oid: str, body: OptionPatch) -> dict:
    """Reword an option, or decide about it.

    `decided_at` is stamped the moment it's picked and cleared if it goes back
    to being just an option, so the card can say when you committed rather than
    only that you did.
    """
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(400, "nothing to change")
    if "status" in fields:
        if fields["status"] not in OPTION_STATES:
            raise HTTPException(400, f"status must be one of {OPTION_STATES}")
        fields["decided_at"] = _now() if fields["status"] in PLANNED else ""
    if "text" in fields:
        fields["text"] = fields["text"].strip()
        if not fields["text"]:
            raise HTTPException(400, "an option needs some words")
    sets = ", ".join(f"o.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (:LearningOpportunity {{id: $id}})-[:HAS_OPTION]->(o:LearningOption {{id: $oid}}) "
        f"SET {sets} RETURN o",
        id=lid, oid=oid, **fields,
    )
    if not rows:
        raise HTTPException(404, "option not found")
    if "status" in fields:
        await record("task", "option " + fields["status"],
                     detail=(rows[0]["o"].get("text") or "")[:70])
    return await _one(lid)


@router.delete("/{lid}/options/{oid}")
async def delete_option(lid: str, oid: str) -> dict:
    """Only for something written by mistake. An option you considered and
    rejected is worth keeping — set it to 'dropped' instead."""
    await run_write(
        "MATCH (:LearningOpportunity {id: $id})-[:HAS_OPTION]->(o:LearningOption {id: $oid}) "
        "DETACH DELETE o",
        id=lid, oid=oid,
    )
    return await _one(lid)


# --------------------------------------------------------------------------- #
# Summary + repeat detection
# --------------------------------------------------------------------------- #
@router.get("/summary")
async def summary() -> dict:
    """The master card: tallies, plus which kinds repeat and on what rhythm.

    For every kind logged more than once we report the gaps between occurrences.
    That's the bit a count can't tell you — three mistakes 40 days apart is a
    habit fading, three in a week is one getting worse.
    """
    rows = await run_read(
        "MATCH (l:LearningOpportunity) "
        "OPTIONAL MATCH (l)-[:HAS_OPTION]->(o:LearningOption) "
        "RETURN l.kind AS kind, l.occurred_at AS when, l.status AS status, "
        "l.module AS module, l.what_happened AS what, l.id AS id, "
        "collect(o.status) AS option_states"
    )
    today = datetime.now(timezone.utc).date()

    tally = {"total": len(rows), "open": 0, "working": 0, "resolved": 0}
    for r in rows:
        tally[r["status"] if r["status"] in STATUSES else "open"] += 1
    tally["active"] = tally["open"] + tally["working"]

    # How far the thinking has actually got. "Written but never decided" is the
    # number worth watching: a mistake with five options and nothing picked has
    # been thought about, not acted on.
    states = [st for r in rows for st in (r["option_states"] or []) if st]
    tally["options"] = len(states)
    tally["options_chosen"] = sum(1 for st in states if st == "chosen")
    tally["options_done"] = sum(1 for st in states if st == "done")
    tally["options_dropped"] = sum(1 for st in states if st == "dropped")
    tally["undecided"] = sum(
        1 for r in rows
        if (r["option_states"] or []) and not any(st in PLANNED for st in r["option_states"])
    )
    tally["no_options"] = sum(
        1 for r in rows
        if r["status"] in ACTIVE and not [st for st in (r["option_states"] or []) if st]
    )

    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = _norm_kind(r["kind"] or "")
        if not k:
            continue
        groups.setdefault(k, []).append(r)

    repeats = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        dates = sorted(d for d in (i["when"] for i in items) if d)
        parsed = []
        for d in dates:
            try:
                parsed.append(datetime.fromisoformat(d[:10]).date())
            except ValueError:
                continue
        gaps = [(parsed[i] - parsed[i - 1]).days for i in range(1, len(parsed))]
        window = lambda n: sum(1 for p in parsed if (today - p).days <= n)  # noqa: E731
        # widening gaps mean the mistake is receding; narrowing means it isn't
        trend = "flat"
        if len(gaps) >= 2:
            first, last = gaps[0], gaps[-1]
            if last > first * 1.25:
                trend = "improving"
            elif last < first * 0.75:
                trend = "worsening"
        unresolved = [i for i in items if i["status"] in ACTIVE]
        repeats.append({
            "kind": next((i["kind"] for i in items if i["kind"]), key),
            "count": len(items),
            "active_count": len(unresolved),
            "dates": [p.isoformat() for p in parsed],
            "last_3_days": window(3),
            "last_7_days": window(7),
            "last_30_days": window(30),
            "days_since_last": (today - parsed[-1]).days if parsed else None,
            "gaps_days": gaps,
            "avg_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "latest_gap_days": gaps[-1] if gaps else None,
            "trend": trend,
            "modules": sorted({i["module"] for i in items if i["module"]}),
            "ids": [i["id"] for i in items],
        })
    repeats.sort(key=lambda r: (-r["count"], r["days_since_last"] if r["days_since_last"] is not None else 999))

    tally["repeating_kinds"] = len(repeats)
    tally["repeating_entries"] = sum(r["count"] for r in repeats)

    # --- high-level habits ---
    # Separate small mistakes only read as one habit once they're grouped.
    # Rolls every entry up by its kind's `group`; anything ungrouped is reported
    # as such rather than silently dropped.
    kind_rows = await run_read(
        "MATCH (k:LearningKind) RETURN k.name AS name, coalesce(k.group,'') AS grp"
    )
    group_of = {r["name"]: r["grp"] for r in kind_rows}
    habits: dict[str, dict] = {}
    for r in rows:
        k = _norm_kind(r["kind"] or "")
        grp = group_of.get(k) or ""
        key = grp or "(ungrouped)"
        h = habits.setdefault(key, {"group": key, "grouped": bool(grp), "count": 0,
                                    "active": 0, "resolved": 0, "kinds": set(),
                                    "last": None})
        h["count"] += 1
        if r["status"] in ACTIVE:
            h["active"] += 1
        elif r["status"] == "resolved":
            h["resolved"] += 1
        if r["kind"]:
            h["kinds"].add(r["kind"].strip())
        d = (r["when"] or "")[:10]
        if d and (h["last"] is None or d > h["last"]):
            h["last"] = d
    habit_list = []
    for h in habits.values():
        days_since = None
        if h["last"]:
            try:
                days_since = (today - datetime.fromisoformat(h["last"]).date()).days
            except ValueError:
                pass
        habit_list.append({**h, "kinds": sorted(h["kinds"]), "days_since_last": days_since})
    habit_list.sort(key=lambda h: (-h["count"], h["group"]))

    return {"tally": tally, "repeats": repeats, "habits": habit_list,
            "kinds": sorted({(r["kind"] or "").strip() for r in rows if (r["kind"] or "").strip()})}
