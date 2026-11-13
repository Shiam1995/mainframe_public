"""/api/snapshot — one call that answers "where am I right now?"

The top-bar panel behind the ◈ chip. It is deliberately a *reader*: not one
node, table or migration belongs to this file. Every section below re-uses a
function or query the rest of the Mainframe already runs, because a snapshot
with its own bookkeeping goes stale within a fortnight and a stale overview is
worse than none — the same rule /api/focus was built on.

Two design rules worth keeping:

1. **Only the sections asked for are computed.** Fourteen sections is a lot of
   Cypher; the panel usually shows five. `?sections=` scopes the work, so
   turning a section off makes the panel genuinely cheaper, not just shorter.

2. **A section that fails returns an error, not a 500.** The panel is the first
   thing seen on opening the app. One module with no data set up must never be
   able to blank the whole overview, so every section is run inside its own
   try/except and reports its own failure in place.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query

from db import run_read, run_write

from models import DayNotePut

router = APIRouter(prefix="/api/snapshot", tags=["snapshot"])


def _today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
SECTIONS: list[dict] = []


def section(key: str, label: str, blurb: str, default: bool = False):
    """Register one section of the snapshot.

    `label`/`blurb` are served to the frontend's ⚙ editor rather than being
    duplicated in JS — a checkbox for a section the backend cannot actually
    serve would be a dead toggle, and the two lists would drift apart the first
    time one was renamed.
    """
    def deco(fn):
        SECTIONS.append({"key": key, "label": label, "blurb": blurb,
                         "default": default, "fn": fn})
        return fn
    return deco


DEFAULT_KEYS = ["now", "pace", "calendar", "due", "goals", "suggest"]


# ============================== WHAT I'M DOING ============================== #
@section("now", "Now", "Work logged today, and what you're in the middle of.", True)
async def _now() -> dict:
    d = _today()
    rows = await run_read(
        """
        MATCH (w:WorkSession) WHERE w.date = $d
        RETURN w{.id, .start, .end, .mins, .what, .ref_title, .ref_kind,
                 .module, .focus} AS w
        ORDER BY coalesce(w.start, '')
        """, d=d)
    sessions = [r["w"] for r in rows]
    return {
        "date": d,
        "sessions": [{
            "label": s.get("what") or s.get("ref_title") or "work",
            "start": s.get("start") or "", "end": s.get("end") or "",
            "mins": s.get("mins") or 0, "module": s.get("module") or "",
            "kind": s.get("ref_kind") or "other",
        } for s in sessions],
        "total_mins": sum(s.get("mins") or 0 for s in sessions),
        "count": len(sessions),
    }


# ================================ CALENDAR ================================== #
@section("calendar", "Today's calendar", "Events, and the next free block.", True)
async def _calendar() -> dict:
    from routes.calendar import freebusy, range_feed
    d = _today()
    feed = await range_feed(from_=d, to=d)
    fb = await freebusy(date_=d)

    now_hm = datetime.now().strftime("%H:%M")
    upcoming = [g for g in fb["free"] if g["end"] > now_hm]

    return {
        "date": d,
        "events": [{"title": e["title"], "start": e.get("start") or "",
                    "end": e.get("end") or "", "all_day": bool(e.get("all_day")),
                    "location": e.get("location") or "",
                    "source": e.get("source") or ""} for e in feed["events"]],
        "logged": [{"kind": l["kind"], "label": l.get("label") or ""}
                   for l in feed["logged"]],
        "next_free": upcoming[0] if upcoming else None,
        "free_mins": fb["free_mins"],
        "busy_mins": fb["busy_mins"],
    }


# ================================== TASKS =================================== #
@section("due", "Due", "Overdue, due today, and what's coming this week.", True)
async def _due() -> dict:
    today = _today()
    soon = (date.today() + timedelta(days=7)).isoformat()
    rows = await run_read(
        """
        MATCH (t:Task)
        WHERE NOT coalesce(t.done, false)
          AND coalesce(t.due_date, '') <> ''
          AND t.due_date <= $soon
        RETURN t{.id, .title, .due_date, .priority, .module, .status} AS t
        ORDER BY t.due_date, coalesce(t.priority, 'zz')
        LIMIT 40
        """, soon=soon)
    tasks = [r["t"] for r in rows]

    def bucket(t: dict) -> str:
        if t["due_date"] < today:
            return "overdue"
        return "today" if t["due_date"] == today else "soon"

    out: dict[str, list] = {"overdue": [], "today": [], "soon": []}
    for t in tasks:
        out[bucket(t)].append(t)

    open_rows = await run_read(
        "MATCH (t:Task) WHERE NOT coalesce(t.done, false) "
        "AND coalesce(t.status,'') <> 'hidden' RETURN count(t) AS n")
    return {**out, "open_total": open_rows[0]["n"] if open_rows else 0}


# ================================== FOCUS =================================== #
@section("goals", "Goals & phase", "The phase you're in and the goals you set.", True)
async def _goals() -> dict:
    from routes.focus import overview
    f = await overview()
    return {"phase": f["phase"], "note": f["note"], "goals": f["goals"],
            "done_goals": f["done_goals"]}


@section("pace", "Pace", "Today against the phase's plan, and whether the plan is holding.", True)
async def _pace() -> dict:
    """The Phases → pace read, cut down to what fits on a tile.

    Reuses routes.phases.active_pace rather than re-deriving planned-vs-logged
    here: a second copy of that arithmetic is exactly the bookkeeping this file
    refuses to keep, and the two would disagree within a fortnight.
    """
    from routes.phases import active_pace
    d = await active_pace()
    if not d.get("phase"):
        return {"phase": None}
    cal, t = d["calibration"], d.get("today_row") or {}
    return {
        "phase": d["phase"]["name"],
        "week_index": d["phase"]["week_index"],
        "weeks": d["phase"]["weeks"],
        "started": d["started"],
        "days_until_start": d["days_until_start"],
        # today's three numbers — see phase-pace.js for why a day gets three
        "logged_h": t.get("logged_h"),
        "share_h": t.get("share_h"),
        "catchup_h": t.get("catchup_h"),
        "week_planned_h": t.get("week_planned_h"),
        "week_logged_h": t.get("week_logged_h"),
        "capacity_h": cal["capacity_h"],
        # the verdict, and how much it is worth yet
        "verdict": cal["verdict"],
        "confidence": cal["confidence"],
        "weeks_complete": cal["weeks_complete"],
        "weeks_needed": cal["weeks_needed"],
        "real_week_h": cal["real_week_h"],
        "plan_week_h": cal["plan_week_h"],
        # true before a single hour is logged, which is why the tile is never blank
        "plan_total_h": cal["plan_total_h"],
        "capacity_total_h": cal["capacity_total_h"],
    }


@section("projects", "Moving lately", "Projects actually worked in the last three weeks.")
async def _projects() -> dict:
    from routes.focus import overview
    return {"projects": (await overview())["projects"]}


@section("learning", "Learning", "What's open in the learning module.")
async def _learning() -> dict:
    from routes.focus import overview
    return {"learning": (await overview())["learning"]}


# =============================== SUGGESTIONS ================================ #
@section("suggest", "Suggestions", "Clashes, overdue work and free blocks — computed, not guessed.", True)
async def _suggest() -> dict:
    from routes.calendar import suggestions
    out = await suggestions()
    return {"suggestions": out[:8], "total": len(out)}


# ============================ REMINDERS & MONEY ============================= #
@section("owing", "Reminders & bills", "Reminders that have landed and payments about to leave.")
async def _owing() -> dict:
    from routes.recurring import due_now
    d = await due_now()
    return {
        "reminders": [{"title": r.get("title") or "", "days_until": r.get("days_until"),
                       "id": r.get("id")} for r in d["reminders"]],
        "payments": [{"name": p.get("name") or "", "amount": p.get("amount"),
                      "days_until": p.get("days_until"), "id": p.get("id")}
                     for p in d["payments"]],
        "total": d["total"],
    }


@section("vault", "Money", "Balances, and this month's spending against the plan.")
async def _vault() -> dict:
    from routes.vault import budget_actual
    accounts = await run_read(
        "MATCH (a:Account) WHERE coalesce(a.archived,false) = false "
        "RETURN a{.name, .balance, .type} AS a ORDER BY a.name")
    month = date.today().strftime("%Y-%m")
    # The same calculator Monthly Plan, Overview and Analytics all call, so the
    # snapshot can never disagree with the page it's summarising.
    b = await budget_actual(month)
    over = [c for c in b["categories"] if c.get("over")]
    over.sort(key=lambda c: (c["actual"] - c["target"]), reverse=True)
    return {
        "accounts": [r["a"] for r in accounts],
        "total_balance": round(sum((r["a"].get("balance") or 0) for r in accounts), 2),
        "month": month,
        "spent": round(b["spent"], 2),
        "allocated": round(b["allocated"], 2),
        "income": round(b["income"], 2),
        "over": [{"name": c["name"], "icon": c.get("icon") or "",
                  "actual": round(c["actual"], 2), "target": round(c["target"], 2)}
                 for c in over[:4]],
        # Money spent in categories with no budget line — Monthly Plan surfaces
        # this deliberately, because otherwise it vanishes from the comparison.
        "unbudgeted": round(sum(c["actual"] for c in b["unbudgeted"]), 2),
    }


# ================================== PULSE =================================== #
@section("habits", "Habits today", "Ticked off, and still outstanding.")
async def _habits() -> dict:
    d = _today()
    rows = await run_read(
        """
        MATCH (h:Habit) WHERE coalesce(h.archived, false) = false
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog {date: $d})
        RETURN h.name AS name, count(l) > 0 AS done ORDER BY name
        """, d=d)
    habits = [{"name": r["name"], "done": r["done"]} for r in rows]
    return {"date": d, "habits": habits,
            "done": sum(1 for h in habits if h["done"]), "total": len(habits)}


@section("scores", "Pulse scores", "Consistency, recovery, movement and fuel over 14 days.")
async def _scores() -> dict:
    from routes.pulsescore import scores
    return await scores()


@section("nutrition", "Nutrition today", "Calories and macros against target.")
async def _nutrition() -> dict:
    from routes.nutrition import dashboard
    d = await dashboard()
    return {
        "date": d["date"],
        "calories": d["totals"].get("calories"),
        "target": d["goals"].get("daily_calories"),
        "remaining": d["remaining"].get("calories"),
        "protein": d["totals"].get("protein"),
        "protein_target": d["goals"].get("daily_protein"),
        "water_ml": d["water"]["total_ml"],
        "entries": d["entry_count"],
    }


# ================================ CROSS-APP ================================= #
@section("mind", "Mind Dump", "Captures still sitting in the inbox.")
async def _mind() -> dict:
    rows = await run_read(
        """
        MATCH (m:MindDump) WHERE coalesce(m.status, 'open') <> 'done'
        RETURN m{.id, .text, .kind, .status} AS m
        ORDER BY coalesce(m.position, 1e15) ASC, m.created_at DESC LIMIT 6
        """)
    total = await run_read(
        "MATCH (m:MindDump) WHERE coalesce(m.status,'open') <> 'done' RETURN count(m) AS n")
    return {"items": [r["m"] for r in rows],
            "total": total[0]["n"] if total else 0}


@section("activity", "Recent activity", "The last things that happened, across every module.")
async def _activity() -> dict:
    rows = await run_read(
        "MATCH (c:ChangeEvent) RETURN c{.category, .action, .detail, .module, "
        ".timestamp} AS c ORDER BY c.timestamp DESC LIMIT 8")
    return {"events": [r["c"] for r in rows]}


# --------------------------------------------------------------------------- #
# The endpoints
# --------------------------------------------------------------------------- #
@router.get("/sections")
async def catalogue() -> dict:
    """Every section this backend can serve, for the panel's ⚙ editor."""
    return {
        "sections": [{"key": s["key"], "label": s["label"], "blurb": s["blurb"],
                      "default": s["default"]} for s in SECTIONS],
        "defaults": DEFAULT_KEYS,
    }


async def _run(spec: dict) -> tuple[str, dict]:
    try:
        return spec["key"], await spec["fn"]()
    except Exception as exc:                # noqa: BLE001 — see module docstring
        return spec["key"], {"error": f"{type(exc).__name__}: {exc}"}


@router.get("")
async def snapshot(sections: str | None = None) -> dict:
    """The panel's single call.

    `sections` is a comma-separated list of keys. Unknown keys are ignored
    rather than rejected, so a browser holding a preference for a section that
    has since been renamed degrades to a smaller panel instead of an error.
    """
    wanted = [s.strip() for s in (sections or "").split(",") if s.strip()] or DEFAULT_KEYS
    specs = [s for s in SECTIONS if s["key"] in wanted]

    # Sections are independent reads, so pay for the slowest rather than the sum.
    results = await asyncio.gather(*(_run(s) for s in specs))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": _today(),
        # Ordered as the caller asked, not as the registry happens to be declared.
        "sections": {k: v for k, v in sorted(
            results, key=lambda kv: wanted.index(kv[0]))},
    }


# --------------------------------------------------------------------------- #
# The Snapshot VIEW (topbar tab) — one day, live or in the past
# --------------------------------------------------------------------------- #
# The panel above answers "where am I right now?"; the view answers "what
# happened on this day?". Same reader philosophy: the feed is the ChangeEvent
# log every mutation already writes, so the view fills itself as you use the
# app. The only thing the view *stores* is the day note.

@router.get("/day")
async def day_feed(date_: str | None = Query(None, alias="date")) -> dict:
    """Everything that happened on one day: the change feed + the day's note.

    Day boundaries follow the stored UTC timestamps — the same convention the
    Log tab's by-day grouping already uses, so the two views never disagree
    about which day an event belongs to.
    """
    d = (date_ or _today())[:10]
    rows = await run_read(
        """
        MATCH (c:ChangeEvent) WHERE c.ts STARTS WITH $d
        RETURN c{.id, .ts, .category, .action, .detail, .module, .trigger} AS c
        ORDER BY c.ts DESC LIMIT 500
        """, d=d)
    note_rows = await run_read(
        "MATCH (n:DayNote {date: $d}) RETURN n.text AS t", d=d)
    events = [r["c"] for r in rows]
    by_module: dict[str, int] = {}
    for e in events:
        m = e.get("module") or "?"
        by_module[m] = by_module.get(m, 0) + 1
    return {"date": d, "events": events, "count": len(events),
            "by_module": by_module,
            "note": (note_rows[0]["t"] if note_rows else "") or ""}


@router.put("/note")
async def put_day_note(body: DayNotePut) -> dict:
    d = body.date[:10]
    await run_write(
        """
        MERGE (n:DayNote {date: $d})
        SET n.text = $text, n.updated_at = $now
        """, d=d, text=body.text, now=datetime.now().isoformat(timespec="seconds"))
    return {"date": d, "text": body.text}
