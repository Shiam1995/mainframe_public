"""/api/phases — phases as sprints (Mainframe-level, not Synapse-specific).

A phase is a fourteen-week run at a handful of projects. One is active at a
time; the next is not created for you when one ends, because deciding to start
another is the point of the break.

Three rules the endpoints exist to enforce:

  * **Counts cannot lie.** Hours, sessions and per-project totals are summed
    from the :WorkSession rows on the phase's projects inside its window. They
    are never posted, never stored on the phase, and never editable.
  * **A phase closes only when every project has an answer** — done, carried or
    dropped. Half a review is worse than none, so `close` refuses.
  * **Working on something joins it.** The lineup you tick at the start is just
    the opening one; any project with a session inside the window is absorbed
    into the phase on the next read (see `_absorb`).

Membership is the relationship (:Project)-[:IN_PHASE]->(:Phase), which carries
the outcome and its note once the phase is closed. Projects are not the only
things in a phase, though: phasehook.py files every Session, Task, CalEvent,
Goal, Mistake, Lesson, Document and Change created while one is running under
that phase too, from a single hook in activity.record(). Only projects are
asked for an outcome at the end; the rest are what the dashboard reads back.

`GET /active/dashboard` is the read the tab actually makes — the whole screen
in one payload, against one `today`.

The same :Phase nodes are what the Goals view scopes phase-goals to
(/api/goals/phases) — one phase, read two ways. Goals may still create a bare
phase inline; only this router enforces the one-active-at-a-time rule.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

import drift
import phasehook
import poolgoals
from activity import record
from hours import hours_index
from routes.attach import attachment_items
from routes.lessons import repeated_since as lessons_repeated_since
from db import run_read, run_write
from models import (
    PhaseClose, PhaseEdit, PoolGoalCreate, PoolGoalUpdate, PhaseStart,
    PullIn, Renegotiate, ServesGoal,
)

router = APIRouter(prefix="/api/phases", tags=["phases"])

OUTCOMES = ("done", "carried", "dropped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        raise HTTPException(400, f"bad date: {s!r} (expected YYYY-MM-DD)")


def _end_of(start: date, weeks: int) -> date:
    """Inclusive last day: a 14-week phase starting on a Monday ends on the
    Sunday 98 days later, not the Monday after."""
    return start + timedelta(days=weeks * 7 - 1)


# Every project in a phase, with the work done on it INSIDE the phase window.
# Sessions outside the window belong to whatever phase was running then (or to
# no phase), so they are filtered out here rather than summed over all time —
# a project carried across two phases must not show the same hours twice.
_PROJECT_ROWS = """
MATCH (p:Phase {id: $id})
OPTIONAL MATCH (pr:Project)-[r:IN_PHASE]->(p)
OPTIONAL MATCH (w:WorkSession)-[:ON]->(pr)
  WHERE w.date >= p.start AND w.date <= p.end
WITH p, pr, r, count(w) AS sessions, sum(coalesce(w.mins, 0)) AS mins
WHERE pr IS NOT NULL
RETURN pr.id AS project_id, pr.name AS name, coalesce(pr.note, '') AS note,
       coalesce(pr.status, 'active') AS status,
       sessions, mins,
       r.outcome AS outcome, coalesce(r.outcome_note, '') AS outcome_note
ORDER BY mins DESC, name
"""


async def _absorb(phase: dict) -> None:
    """Pull in any project worked on during an ACTIVE phase's window.

    "Anything you push after the start date joins on its own" — rather than
    hooking every place a session can be written, membership is reconciled on
    read. Cheap (one MERGE over the window's sessions) and self-healing: a
    session backdated into the window joins its project too.

    Closed phases are left alone; their lineup is history."""
    if phase.get("status") != "active":
        return
    await run_write(
        """
        MATCH (p:Phase {id: $id})
        MATCH (w:WorkSession)-[:ON]->(x)
          WHERE w.date >= p.start AND w.date <= p.end
        MATCH (pr:Project)
          WHERE pr = x OR (pr)-[:ABOUT]->(x) OR (x)-[:PART_OF]->(pr)
        MERGE (pr)-[:IN_PHASE]->(p)
        """, id=phase["id"])


def _shape(p: dict, rows: list[dict], total: dict | None = None) -> dict:
    """One phase plus the derived summary row. `weeks_in` is how far through it
    is today — 0 before it starts, capped at its length once it is over.

    `total` is the phase's own roll-up (hours.py over all its projects, each
    session once). Summing the rows would count a child project's hours twice,
    once on its own row and once inside its parent's."""
    mins = total["mins"] if total else sum(r["mins"] or 0 for r in rows)
    today = date.today()
    start, end = _parse_date(p["start"]), _parse_date(p["end"])
    weeks = int(p.get("weeks") or 1)
    if today < start:
        weeks_in = 0
    elif today > end:
        weeks_in = weeks
    else:
        weeks_in = min(weeks, (today - start).days // 7 + 1)
    out = dict(p)
    # `number` is the spec's name for what has always been stored as `seq`. It
    # is published rather than renamed: the property is already on every row in
    # the database and read by the Goals view, and a migration buys nothing.
    out["number"] = int(p.get("seq") or 1)
    out["banner_url"] = p.get("banner_url") or ""
    out["projects"] = rows
    out["mins"] = mins
    out["hours"] = round(mins / 60.0, 1)
    out["sessions"] = total["sessions"] if total else sum(r["sessions"] or 0 for r in rows)
    out["project_count"] = len(rows)
    out["weeks_in"] = weeks_in
    # Hours a week is measured against the phase's full length, not against how
    # much of it has gone — the figure you are being asked to live up to.
    out["hours_per_week"] = round(mins / 60.0 / weeks, 1) if weeks else 0.0
    out["unanswered"] = len([r for r in rows if not r.get("outcome")])
    out["tally"] = {k: len([r for r in rows if r.get("outcome") == k]) for k in OUTCOMES}
    return out


async def _one(pid: str) -> dict:
    rows = await run_read("MATCH (p:Phase {id: $id}) RETURN p", id=pid)
    if not rows:
        raise HTTPException(404, "no such phase")
    phase = dict(rows[0]["p"])
    await _absorb(phase)
    projects = [dict(r) for r in await run_read(_PROJECT_ROWS, id=pid)]
    # Hours are the shared roll-up (hours.py) windowed to the phase: a
    # project's row counts its sub-projects, tasks and attachments too, the
    # same number its project page shows for these weeks.
    idx = await hours_index(str(phase["start"])[:10], str(phase["end"])[:10])
    for r in projects:
        h = idx.of(r["project_id"])
        r["mins"], r["sessions"] = h["mins"], h["sessions"]
    projects.sort(key=lambda r: (-(r["mins"] or 0), r["name"] or ""))
    return _shape(phase, projects, idx.of_all([r["project_id"] for r in projects]))


async def _filed(pid: str) -> dict:
    """How much of each kind the IN_PHASE hook has filed under this phase.

    Small on its own, but it is the only place the hook is visible: if work you
    did this week is not showing up on the dashboard, this row says whether it
    was never filed or is being filed and dropped somewhere later.
    """
    rows = await run_read(
        """
        MATCH (n)-[:IN_PHASE]->(:Phase {id: $id})
        UNWIND labels(n) AS lbl
        WITH lbl, count(DISTINCT n) AS n WHERE lbl IN $labels
        RETURN lbl, n ORDER BY lbl
        """, id=pid, labels=list(phasehook.LABELS))
    return {r["lbl"]: r["n"] for r in rows}


async def _active_id() -> str | None:
    rows = await run_read(
        "MATCH (p:Phase) WHERE coalesce(p.status,'active') = 'active' "
        "RETURN p.id AS id ORDER BY p.start DESC LIMIT 1")
    return rows[0]["id"] if rows else None


@router.get("")
async def list_phases() -> list[dict]:
    """Every phase, newest first, each with its derived totals."""
    rows = await run_read("MATCH (p:Phase) RETURN p.id AS id ORDER BY p.start DESC")
    return [await _one(r["id"]) for r in rows]


@router.get("/active")
async def active_phase() -> dict:
    """The phase you are in, or `{"phase": null}` — a break is a real state,
    not an error."""
    pid = await _active_id()
    return {"phase": await _one(pid) if pid else None}


async def _lineup(phase: dict) -> dict:
    """"In this phase": the projects the phase pulled in (CLAIMED_BY), each with
    what is attached to it, then whatever joined on its own.

    A phase pulls whole projects; attachments come with the project, so there
    is no per-item pull. A claimed project whose parent is also claimed is
    shown inside the parent, not again at the top. Projects that joined only
    because a session landed in the window (IN_PHASE, no claim) are listed
    when they carry hours here, and collapse to one line when they carry none.
    Every number is hours.py windowed to the phase."""
    pid = phase["id"]
    idx = await hours_index(str(phase["start"])[:10], str(phase["end"])[:10])
    claims = await run_read(
        """
        MATCH (pr:Project)-[r:CLAIMED_BY]->(ph:Phase {id: $id})
        OPTIONAL MATCH (pr)-[:CHILD_OF]->(par:Project)
        RETURN pr.id AS id, pr.name AS name, coalesce(r.hours, 0.0) AS planned,
               coalesce(r.date, '') AS date,
               par IS NOT NULL AND (par)-[:CLAIMED_BY]->(ph) AS parent_claimed
        ORDER BY r.date, pr.name
        """, id=pid)
    claimed = {c["id"] for c in claims}
    pulled, covered = [], set()
    for c in claims:
        if c["parent_claimed"]:
            continue
        covered |= idx.under(c["id"])
        kids = await run_read(
            "MATCH (k:Project)-[:CHILD_OF]->(:Project {id: $id}) RETURN k.id AS id, k.name AS name ORDER BY k.name",
            id=c["id"])
        items = [{"kind": "project", "chip": "project", "id": k["id"], "title": k["name"],
                  "where": "sub-project", "sources": [], **idx.of(k["id"])} for k in kids]
        items += await attachment_items(c["id"], idx)
        pulled.append({"id": c["id"], "name": c["name"], "planned_h": c["planned"],
                       "date": c["date"], **idx.of(c["id"]), "items": items})
    auto, auto_zero = [], []
    for r in phase.get("projects") or []:
        if r["project_id"] in claimed or r["project_id"] in covered:
            continue
        # only the hours not already shown under a pulled project: a parent
        # that joined on its own must not repeat its pulled children's hours
        h = idx.of_except(r["project_id"], covered)
        (auto if h["mins"] else auto_zero).append(
            {"id": r["project_id"], "name": r["name"], **h})
    return {"pulled": pulled, "auto": auto, "auto_zero": auto_zero}


async def _for_phase(pid: str) -> list[dict]:
    """Inbox rows marked "do this phase" — (:Task)-[:FOR_PHASE]->(:Phase), set
    from the Inbox. The same nodes the Inbox lists; read here, never copied."""
    rows = await run_read(
        "MATCH (t:Task)-[r:FOR_PHASE]->(:Phase {id: $id}) "
        "RETURN t.id AS id, t.title AS title, coalesce(t.kind,'idea') AS kind, "
        "coalesce(t.status,'raw') AS status, coalesce(t.due,'') AS due, "
        "coalesce(t.takes_min,0) AS takes_min, coalesce(t.starred,false) AS starred, "
        "coalesce(t.star_tone,'priority') AS star_tone, r.at AS at "
        "ORDER BY r.at", id=pid)
    return [dict(r) for r in rows]


@router.get("/active/dashboard")
async def active_dashboard() -> dict:
    """One payload for the whole Phases tab.

    The tab is a dashboard, not a list, and a dashboard that fires nine requests
    shows nine different moments. Everything on screen is read here, in one go,
    against one `today`.

    What this returns:
        phase     the active phase, or null on a break, with its derived totals
                  and the projects in it
        today     the server's date, so the client never disagrees about which
                  day it is drawing
        week      the Monday-to-Sunday week `today` sits in, which week of the
                  phase that is, and the hours logged in it
        filed     what the IN_PHASE hook has filed under this phase, by kind
        goals     the time viewer's week and month rows, keyed by horizon, with
                  the drift rules already run over them
        tasks     the time viewer's day: today's list, each with the goal it
                  serves and the hours actually logged against it
        flagged   how many goals are asking to be talked through

    Steps 3 to 5 add their own keys here rather than their own routes: targets,
    body + habits, score, the week's calendar and the change log.
    """
    pid = await _active_id()
    if not pid:
        return {"phase": None, "today": date.today().isoformat(),
                "week": None, "filed": {}}

    # Force the sweep: the hook debounces on the write path, but what you are
    # looking at should never be a few seconds behind what you just did.
    await phasehook.sweep(force=True)

    phase = await _one(pid)
    today = date.today()
    start = _parse_date(phase["start"])
    monday = today - timedelta(days=today.weekday())
    week = {
        "start": monday.isoformat(),
        "end": (monday + timedelta(days=6)).isoformat(),
        # Which week of the phase this is, 1-based and clamped into it, so a
        # week that straddles the start or end still lands on a real number.
        "index": max(1, min(int(phase.get("weeks") or 1),
                            (monday - (start - timedelta(days=start.weekday()))).days // 7 + 1)),
    }
    goals = await _goals(pid, week["start"], week["end"])
    week["hours"] = await _week_hours(pid, week["start"], week["end"])
    # The mistakes quarter of the weekly score, ready for the score box: any
    # lesson dated this week and marked as a repeat of an earlier one. Derived,
    # never typed — see routes/lessons.py for why `repeated` is not settable.
    mistakes = await lessons_repeated_since(week["start"])
    flagged = sum(1 for h in goals.values() for g in h if g["status"] == "flagged")
    return {"phase": phase, "today": today.isoformat(), "week": week,
            "lineup": await _lineup(phase),
            "filed": await _filed(pid), "goals": goals,
            "tasks": await _today_tasks(pid, today.isoformat()),
            "inbox": await _for_phase(pid),
            "flagged": flagged, "mistakes": mistakes}


# --------------------------------------------------------------------------- #
# Pace — planned against actual, day by day.
#
# The plan a phase is seeded with is a guess. This read is the instrument that
# tells you how good a guess it was, while there is still phase left to spend.
#
# WHERE THE TWO NUMBERS COME FROM, and why only one of them is editable:
#   planned  `r.planned` on (:Project)-[:CLAIMED_BY]->(:Phase) — fourteen numbers,
#            one per phase week, written when the phase was seeded. A plan is a
#            claim about a week, so it is stored per week and never per day.
#   logged   summed from :WorkSession rows on the phase's projects inside its
#            window, exactly as the dashboard does it. Never stored, never
#            posted. The same rule the rest of this file runs on: a count you
#            can type is a count that can lie.
#
# A WEEK IS THE UNIT THE PLAN IS WRITTEN IN; A DAY IS THE UNIT YOU LIVE IN. The
# day therefore gets three numbers rather than a target, because they answer
# three different questions and collapsing them would hide the one you need:
#   share    the week's plan spread flat over seven days — what an even week
#            would ask of today.
#   logged   what you actually put in.
#   catchup  the week's plan still outstanding, divided by the days left in it
#            (today included). This is the one that moves: skip a day and it
#            climbs, which is the earliest honest signal that a week is going.
#
# VERDICTS REFUSE TO GUESS. Two complete weeks with work in them is the floor
# for saying anything about a project, and the payload carries `weeks_complete`
# and `confidence` so the view can say "not yet" in as many words instead of
# drawing a confident bar over four days of data. Ratios are logged ÷ planned,
# so 0.5 means the plan asked for twice what happened.
# --------------------------------------------------------------------------- #

# Below this, a project's own history is too thin to draw a conclusion from.
_PACE_MIN_WEEKS = 2
# logged / planned. Under the floor the plan is heavier than the week; over the
# ceiling it is lighter. The band between them is what "about right" means: a
# plan that has to be met to the hour is not a plan, so there is ±15% of room in
# it — but no more than that. A first cut allowed down to 0.60 and it called a
# week that delivered 30.8h against a 46h plan "about right", which is the one
# thing this screen must never do. A third of the plan missing is the finding,
# not the tolerance.
_PACE_HEAVY, _PACE_LIGHT = 0.85, 1.15


def _pace_verdict(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio < _PACE_HEAVY:
        return "plan too heavy"
    if ratio > _PACE_LIGHT:
        return "plan too light"
    return "about right"


@router.get("/active/pace")
async def active_pace() -> dict:
    """Planned against actual for the running phase — the day-to-day read.

    One payload against one `today`, like the dashboard: the per-day row, the
    per-week row, the per-project verdict, and the phase-level calibration that
    says what a real week of yours actually holds.
    """
    pid = await _active_id()
    if not pid:
        return {"phase": None, "today": date.today().isoformat()}

    await phasehook.sweep(force=True)
    rows = await run_read("MATCH (p:Phase {id: $id}) RETURN p", id=pid)
    phase = dict(rows[0]["p"])
    await _absorb(phase)

    today = date.today()
    start, end = _parse_date(phase["start"]), _parse_date(phase["end"])
    weeks = int(phase.get("weeks") or 14)
    cap = float(phase.get("capacity_h_per_week") or 0.0)

    def week_of(d: date) -> int:
        """1-based phase week a date falls in; 0 before the phase, weeks+1 after."""
        if d < start:
            return 0
        i = (d - start).days // 7 + 1
        return i if i <= weeks else weeks + 1

    week_index = week_of(today) if start <= today <= end else (0 if today < start else weeks)

    # ---- the plan, per project, off the claim -----------------------------
    claims = await run_read(
        """
        MATCH (pr:Project)-[r:CLAIMED_BY]->(:Phase {id: $id})
        RETURN pr.id AS id, pr.name AS name, coalesce(pr.tier, '') AS tier,
               coalesce(pr.ref, '') AS ref, r.planned AS planned,
               coalesce(r.hours, 0.0) AS claimed
        ORDER BY pr.name
        """, id=pid)

    # ---- the actuals, per project per day, inside the window -------------
    # A session counts for a claimed project when it is ON anything in that
    # project's hours.py subtree — the project itself, a sub-project, a task,
    # an attachment, or the book it is ABOUT — the same roll-up the phase
    # totals use, so pace and totals cannot disagree.
    idx = await hours_index(str(phase["start"])[:10], str(phase["end"])[:10])
    owners: dict[str, set[str]] = {}
    for c in claims:
        for n in idx.under(c["id"]):
            owners.setdefault(n, set()).add(c["id"])
    logged = await run_read(
        """
        MATCH (p:Phase {id: $id})
        MATCH (w:WorkSession)
          WHERE w.date >= p.start AND w.date <= p.end
        OPTIONAL MATCH (w)-[:ON]->(x)
        RETURN x.id AS nid, w.date AS date,
               sum(coalesce(w.mins, 0)) AS mins, count(w) AS sessions
        """, id=pid)

    by_project: dict[str, dict[str, float]] = {}
    by_day: dict[str, dict] = {}
    # Hours logged inside the window but NOT under a claimed project. Real
    # work that the plan never accounted for, which is half of why a week
    # overruns — hiding it would make the plan look better than it is.
    off_mins = off_plan_sessions = 0
    for r in logged:
        who = owners.get(r["nid"]) if r["nid"] else None
        if not who:
            off_mins += r["mins"] or 0
            off_plan_sessions += r["sessions"] or 0
            continue
        h = (r["mins"] or 0) / 60.0
        for prid in who:
            days = by_project.setdefault(prid, {})
            days[r["date"]] = days.get(r["date"], 0.0) + h
        d = by_day.setdefault(r["date"], {"hours": 0.0, "sessions": 0})
        d["hours"] += h
        d["sessions"] += r["sessions"] or 0
    off_plan_h = round(off_mins / 60.0, 2)

    # ---- the per-week plan totals ----------------------------------------
    plan_week = [0.0] * weeks
    for c in claims:
        for i, v in enumerate(c["planned"] or []):
            if i < weeks:
                plan_week[i] += float(v or 0)

    # ---- days: phase start (or the last 28, whichever is later) to today --
    day_rows = []
    first = max(start, today - timedelta(days=27))
    if today >= start:
        d = first
        while d <= min(today, end):
            iso = d.isoformat()
            wk = week_of(d)
            got = by_day.get(iso, {"hours": 0.0, "sessions": 0})
            share = (plan_week[wk - 1] / 7.0) if 1 <= wk <= weeks else 0.0
            day_rows.append({
                "date": iso, "week": wk, "dow": d.weekday(),
                "logged_h": round(got["hours"], 2), "sessions": got["sessions"],
                "share_h": round(share, 2),
                "is_today": d == today,
            })
            d += timedelta(days=1)

    # ---- weeks: planned, logged, and whether the week is over -------------
    week_rows = []
    for i in range(weeks):
        w_start = start + timedelta(days=7 * i)
        w_end = w_start + timedelta(days=6)
        span_days = [d for k, d in by_day.items()
                     if w_start.isoformat() <= k <= w_end.isoformat()]
        got = sum(d["hours"] for d in span_days)
        days_worked = sum(1 for d in span_days if d["hours"] > 0)
        complete = w_end < today
        planned = round(plan_week[i], 2)
        week_rows.append({
            "week": i + 1, "start": w_start.isoformat(), "end": w_end.isoformat(),
            "planned_h": planned, "logged_h": round(got, 2),
            "capacity_h": cap, "days_worked": days_worked,
            "complete": complete, "current": w_start <= today <= w_end,
            # Only a finished week with work in it is evidence. An empty
            # finished week is a fact about the week, not about the plan, so it
            # is not allowed to drag a verdict down.
            "counts": complete and got > 0,
            "over_capacity_h": round(planned - cap, 2) if cap else None,
        })

    evidence = [w for w in week_rows if w["counts"]]
    weeks_complete = len(evidence)
    enough = weeks_complete >= _PACE_MIN_WEEKS

    # ---- today ------------------------------------------------------------
    cur = next((w for w in week_rows if w["current"]), None)
    today_row = None
    if cur and today >= start:
        left = (_parse_date(cur["end"]) - today).days + 1     # today included
        outstanding = max(0.0, cur["planned_h"] - cur["logged_h"])
        today_row = {
            "date": today.isoformat(),
            "week": cur["week"],
            "logged_h": round(by_day.get(today.isoformat(), {}).get("hours", 0.0), 2),
            "share_h": round(cur["planned_h"] / 7.0, 2),
            "catchup_h": round(outstanding / left, 2) if left > 0 else 0.0,
            "days_left_in_week": left,
            "week_planned_h": cur["planned_h"],
            "week_logged_h": cur["logged_h"],
        }

    # ---- per project ------------------------------------------------------
    # A claimed book is not one lump of hours. Its chapters are the units of
    # work, and the open ones with estimates on them are what is actually left
    # — so the forecast reads them as tasks. See books.chapter_forecast.
    from routes.books import chapter_forecast
    books = await chapter_forecast([c["id"] for c in claims])

    projects = []
    for c in claims:
        planned = [float(v or 0) for v in (c["planned"] or [])]
        days = by_project.get(c["id"], {})
        # Compared over the SAME weeks: only the finished weeks with work in
        # them. Measuring actuals against a plan that includes weeks that have
        # not happened yet would call every project too heavy.
        pl = lg = 0.0
        for w in evidence:
            i = w["week"] - 1
            pl += planned[i] if i < len(planned) else 0.0
            lg += sum(h for k, h in days.items() if w["start"] <= k <= w["end"])
        n = len(evidence) or 1
        ratio = (lg / pl) if pl > 0 else None
        projects.append({
            "id": c["id"], "name": c["name"], "tier": c["tier"], "ref": c["ref"],
            "claimed_h": round(float(c["claimed"] or 0), 2),
            "planned": planned,
            "planned_total_h": round(sum(planned), 2),
            "logged_total_h": round(sum(days.values()), 2),
            "planned_per_week_h": round(pl / n, 2) if enough else None,
            "logged_per_week_h": round(lg / n, 2) if enough else None,
            "ratio": round(ratio, 3) if (enough and ratio is not None) else None,
            "verdict": _pace_verdict(ratio) if enough else "not enough weeks yet",
            # Present only when this project IS a book.
            "book": books.get(c["id"]),
        })

    # ---- the phase-level calibration -------------------------------------
    real_week = (sum(w["logged_h"] for w in evidence) / weeks_complete) if enough else None
    plan_avg = (sum(w["planned_h"] for w in evidence) / weeks_complete) if enough \
        else (sum(plan_week) / weeks if weeks else 0.0)
    calibration = {
        "weeks_complete": weeks_complete,
        "weeks_needed": _PACE_MIN_WEEKS,
        "confidence": ("none" if weeks_complete == 0 else
                       "warming up" if weeks_complete < _PACE_MIN_WEEKS else
                       "first read" if weeks_complete < 3 else "settled"),
        "real_week_h": round(real_week, 2) if real_week is not None else None,
        "plan_week_h": round(plan_avg, 2),
        "capacity_h": cap,
        "capacity_floor_h": float(phase.get("capacity_floor_h") or 0.0) or None,
        "capacity_ceiling_h": float(phase.get("capacity_ceiling_h") or 0.0) or None,
        # What the whole plan asks for against what the phase says it has. This
        # one needs no data at all — it is arithmetic on the plan, and it is
        # true on day one.
        "plan_total_h": round(sum(plan_week), 2),
        "capacity_total_h": round(cap * weeks, 2) if cap else None,
        "off_plan_h": off_plan_h,
        "off_plan_sessions": off_plan_sessions,
        # The claimed books' outstanding chapters, in hours. This is a bottom-up
        # number built from the chapters themselves, so it can disagree with the
        # hours the phase claimed those books for — and when it does, that gap
        # is the finding, not a bug to reconcile away.
        "book_remaining_h": round(sum(b["remaining_h"] for b in books.values()), 2),
        "book_chapters_open": sum(b["total"] - b["done"] for b in books.values()),
        "book_chapters_unestimated": sum(b["unestimated"] for b in books.values()),
        # Hours the phase has claimed on projects with no weeks array — the
        # cadences, which were seeded with a claim but no per-week plan. They
        # are real commitments that the weekly plan above cannot see, so the
        # week totals understate the phase by exactly this much spread over it.
        "unplanned_claim_h": round(sum(
            float(c["claimed"] or 0) for c in claims if not (c["planned"] or [])), 2),
        "verdict": (_pace_verdict(real_week / plan_avg) if (enough and plan_avg > 0)
                    else "not enough weeks yet"),
    }

    return {
        "phase": {
            "id": pid, "name": phase.get("name", ""), "start": phase["start"],
            "end": phase["end"], "weeks": weeks, "week_index": week_index,
            "capacity_h_per_week": cap, "goal": phase.get("goal", ""),
        },
        "today": today.isoformat(),
        "started": today >= start,
        "days_until_start": max(0, (start - today).days),
        "today_row": today_row,
        "days": day_rows,
        "weeks": week_rows,
        "projects": projects,
        "calibration": calibration,
    }


@router.get("/candidates")
async def candidates() -> list[dict]:
    """Projects that could join the next phase: everything not done. The ones
    carried out of the last closed phase come back pre-ticked."""
    rows = await run_read(
        """
        MATCH (pr:Project) WHERE coalesce(pr.status, 'active') <> 'done'
        OPTIONAL MATCH (pr)-[r:IN_PHASE]->(prev:Phase)
          WHERE prev.status = 'closed' AND r.outcome = 'carried'
        WITH pr, max(prev.end) AS last_carried
        RETURN pr.id AS id, pr.name AS name,
               coalesce(pr.status, 'active') AS status,
               last_carried IS NOT NULL AS carried
        ORDER BY carried DESC, pr.name
        """)
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def start_phase(body: PhaseStart) -> dict:
    """Start a phase. Refused while one is running: two active phases would
    make "hours in phase" meaningless."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "give the phase a name")
    if body.weeks < 1 or body.weeks > 26:
        raise HTTPException(400, "a phase runs between 1 and 26 weeks")
    if await _active_id():
        raise HTTPException(409, "a phase is already running — end it first")

    start = _parse_date(body.start)
    end = _end_of(start, body.weeks)
    seq_rows = await run_read("MATCH (p:Phase) RETURN count(p) AS n")
    seq = (seq_rows[0]["n"] if seq_rows else 0) + 1
    pid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (p:Phase {id: $id, name: $name, start: $start, end: $end,
                         weeks: $weeks, goal: $goal, note: '', reflection: '',
                         banner_url: '',
                         status: 'active', seq: $seq, created_at: $now})
        """, id=pid, name=name, start=start.isoformat(), end=end.isoformat(),
        weeks=body.weeks, goal=body.goal, seq=seq, now=_now())
    if body.project_ids:
        await run_write(
            """
            MATCH (p:Phase {id: $id})
            UNWIND $pids AS pid
            MATCH (pr:Project {id: pid})
            MERGE (pr)-[:IN_PHASE]->(p)
            """, id=pid, pids=body.project_ids)
    await record("goal", "phase started",
                 detail=f"{name} ({start} → {end}, {len(body.project_ids)} projects)"[:70],
                 entity_id=pid)
    return await _one(pid)


@router.patch("/{pid}")
async def edit_phase(pid: str, body: PhaseEdit) -> dict:
    """Edit a phase: the pencil and the banner button on its header.

    Only the fields actually sent are written, so uploading a banner cannot wipe
    the goal you typed a week ago. `end` is not editable — it is `start + weeks`
    and nothing else, which is what keeps "week 3 of 14" true.

    A closed phase is left alone. Its dates are the frame every hour in it was
    counted against; moving them would silently restate history.
    """
    rows = await run_read("MATCH (p:Phase {id: $id}) RETURN p", id=pid)
    if not rows:
        raise HTTPException(404, "no such phase")
    phase = dict(rows[0]["p"])
    if phase.get("status") == "closed":
        raise HTTPException(409, "that phase is closed — its dates are the record")

    sets, params, changed = [], {"id": pid}, []
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "give the phase a name")
        sets.append("p.name = $name")
        params["name"] = body.name.strip()
        changed.append("name")
    if body.goal is not None:
        sets.append("p.goal = $goal")
        params["goal"] = body.goal.strip()
        changed.append("goal")
    if body.banner_url is not None:
        sets.append("p.banner_url = $banner_url")
        params["banner_url"] = body.banner_url.strip()
        changed.append("banner")

    # start and weeks move the window together, so end is recomputed whenever
    # either arrives rather than only when both do.
    if body.start is not None or body.weeks is not None:
        start = _parse_date(body.start) if body.start is not None \
            else _parse_date(phase["start"])
        weeks = body.weeks if body.weeks is not None else int(phase.get("weeks") or 14)
        if weeks < 1 or weeks > 26:
            raise HTTPException(400, "a phase runs between 1 and 26 weeks")
        sets += ["p.start = $start", "p.weeks = $weeks", "p.end = $end"]
        params |= {"start": start.isoformat(), "weeks": weeks,
                   "end": _end_of(start, weeks).isoformat()}
        changed.append("dates")

    if not sets:
        return await _one(pid)
    await run_write(f"MATCH (p:Phase {{id: $id}}) SET {', '.join(sets)}", **params)
    if "dates" in changed:
        # The window is what "inside this phase" means, so moving it re-files:
        # drop what has fallen outside, then sweep to pick up what has fallen in.
        await phasehook.refile(pid)
        await phasehook.sweep(force=True)
    await record("goal", "phase edited",
                 detail=f"{params.get('name', phase.get('name', ''))} — "
                        f"{', '.join(changed)}"[:70],
                 entity_id=pid)
    return await _one(pid)


@router.post("/{pid}/close")
async def close_phase(pid: str, body: PhaseClose) -> dict:
    """Close a phase. Every project in it needs an outcome; the endpoint counts
    them itself rather than trusting the client's tally."""
    rows = await run_read("MATCH (p:Phase {id: $id}) RETURN p", id=pid)
    if not rows:
        raise HTTPException(404, "no such phase")
    phase = dict(rows[0]["p"])
    if phase.get("status") == "closed":
        raise HTTPException(409, "phase is already closed")
    await _absorb(phase)

    members = {r["project_id"] for r in await run_read(
        "MATCH (pr:Project)-[:IN_PHASE]->(:Phase {id: $id}) "
        "RETURN pr.id AS project_id", id=pid)}
    given = {}
    for o in body.outcomes:
        if o.project_id not in members:
            raise HTTPException(400, f"{o.project_id} is not in this phase")
        given[o.project_id] = o
    missing = members - set(given)
    if missing:
        raise HTTPException(
            400, f"{len(missing)} project(s) still need an outcome")

    for o in given.values():
        await run_write(
            """
            MATCH (pr:Project {id: $pid})-[r:IN_PHASE]->(:Phase {id: $phase})
            SET r.outcome = $outcome, r.outcome_note = $note, r.answered_at = $now
            """, pid=o.project_id, phase=pid, outcome=o.outcome,
            note=o.note, now=_now())
        # A project finished inside a phase is finished everywhere — that is
        # what keeps it out of the next phase's candidate list.
        if o.outcome == "done":
            await run_write("MATCH (pr:Project {id: $pid}) SET pr.status = 'done'",
                            pid=o.project_id)

    await run_write(
        """
        MATCH (p:Phase {id: $id})
        SET p.status = 'closed', p.reflection = $reflection, p.closed_at = $now
        """, id=pid, reflection=body.reflection, now=_now())
    tally = {k: len([o for o in given.values() if o.outcome == k]) for k in OUTCOMES}
    await record("goal", "phase closed",
                 detail=f"{phase.get('name', '')} — {tally['done']} done, "
                        f"{tally['carried']} carried, {tally['dropped']} dropped"[:70],
                 entity_id=pid)
    return await _one(pid)


# =========================================================================== #
# THE TIME VIEWER
#
# One horizon at a time: the day is tasks, the week and the month are goals.
# That asymmetry is the point rather than an inconsistency — a day is a list of
# things you will actually do, and a week is a claim about what those days add
# up to. The chip on a task is the goal it serves; a task with no chip still
# counts toward hours, but not toward whether the week's claim came true.
# =========================================================================== #

# The goals of one horizon, with the two derived numbers the row shows: how many
# hours have gone into the goal's work this week, and how far through its scope
# it is. Both are summed here rather than stored, for the same reason the phase's
# hours are: a number you can type is a number that can be wrong.
# Today's list. `planned_mins` comes from the calendar block that plans the task
# and `logged_mins` from the sessions actually pushed against it, so a task can
# show "2h · 12:00" before it happens and "1.5h · logged" after.
# A task is in the phase because the project it was given to is: the phase
# claims projects, and the work under a claimed project is the phase's work.
# `due` is the new field; `due_date` is read alongside it so tasks written
# before the Inbox landed still show up on their day.
_TODAY_TASKS = """
MATCH (t:Task)-[:GIVEN_TO]->(pr:Project)-[:IN_PHASE]->(:Phase {id: $phase})
WHERE coalesce(t.kind, 'task') = 'task'
  AND (coalesce(t.due, t.due_date, '') = $today
       OR EXISTS { MATCH (e:CalEvent)-[:PLANS]->(t) WHERE e.date = $today })
WITH DISTINCT t, pr
OPTIONAL MATCH (e:CalEvent)-[:PLANS]->(t) WHERE e.date = $today
WITH t, pr, min(e.start) AS at, min(e.end) AS until
OPTIONAL MATCH (w:WorkSession)-[:ON]->(t) WHERE w.date = $today
WITH t, pr, at, until, sum(coalesce(w.mins, 0)) AS logged_mins
RETURN t{.id, .title, .done, .priority, .module, .status} AS task,
       {id: pr.id, text: pr.name} AS serves, at, until, logged_mins
ORDER BY coalesce(at, 'zz'), t.title
"""


async def _goals(pid: str, week_start: str, week_end: str) -> dict:
    """Every horizon's goals, keyed by horizon. Drift runs first so the statuses
    these rows carry are the ones the rules just decided on."""
    await drift.evaluate(pid)
    out = {}
    for horizon in ("day", "week", "month"):
        # Claimed by this phase, not merely created during it: a goal joins a
        # phase by being pulled in, and the pool is what it is pulled from.
        out[horizon] = await poolgoals.read(
            "(g)-[:CLAIMED_BY]->(:Phase {id: $phase}) AND g.horizon = $horizon",
            phase=pid, horizon=horizon)
    return out


@router.get("/goals")
async def list_goals(horizon: str | None = None) -> list[dict]:
    """The active phase's goals, all horizons or one. Flat, for anything that
    wants the list without the rest of the dashboard around it."""
    pid = await _active_id()
    if not pid:
        return []
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    goals = await _goals(pid, monday.isoformat(),
                         (monday + timedelta(days=6)).isoformat())
    if horizon:
        return goals.get(horizon, [])
    return [g for h in ("day", "week", "month") for g in goals[h]]


@router.post("/goals", status_code=201)
async def create_goal(body: PoolGoalCreate) -> dict:
    """Set a goal against the running phase.

    Refused when nothing is running: a goal for the week is a goal inside a
    phase, and one written on a break has nothing to be measured against.
    """
    pid = await _active_id()
    if not pid:
        raise HTTPException(409, "no phase is running — a goal needs one to sit in")
    if not body.text.strip():
        raise HTTPException(400, "say what the goal is")
    if body.due:
        _parse_date(body.due)
    if body.measure == "hours" and not body.project_id:
        raise HTTPException(400, "an hours goal needs a project: its hours are the sessions logged on it")
    # Due defaults to the end of the goal's window: Sunday for a week goal,
    # the last of the month for a month goal. A goal with a due date is one
    # the drift rules can check.
    due = body.due
    if not due:
        t = date.today()
        if body.horizon == "week":
            due = (t + timedelta(days=6 - t.weekday())).isoformat()
        elif body.horizon == "month":
            due = ((t.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).isoformat()
    # A week goal in hours is a weekly plan, which is what the Thursday rule
    # in drift.py reads.
    plan_h_week = body.plan_h_week or (body.target_h if body.measure == "hours" and body.horizon == "week" else 0.0)

    gid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:Phase {id: $phase})
        CREATE (g:Goal:PoolGoal {
            id: $id, text: $text, horizon: $horizon, due: $due, note: $note,
            status: 'on', flag_reason: '',
            plan_h_day: $plan_h_day, plan_h_week: $plan_h_week, estimate_h: $estimate_h,
            scope_total: $scope_total, scope_done: $scope_done,
            measure: $measure, target_h: $target_h,
            created_at: $now
        })
        CREATE (g)-[:IN_PHASE]->(p)
        // Claimed as well as filed: the Week and Month panels list what the
        // phase has CLAIMED, so a goal set here without this edge never showed.
        CREATE (g)-[:CLAIMED_BY {hours: $target_h, date: $today}]->(p)
        """, phase=pid, id=gid, text=body.text.strip(), horizon=body.horizon,
        due=due, note=body.note, plan_h_day=body.plan_h_day,
        plan_h_week=plan_h_week, estimate_h=body.estimate_h,
        scope_total=body.scope_total, scope_done=body.scope_done,
        measure=body.measure, target_h=body.target_h, today=date.today().isoformat(),
        now=_now())
    if body.project_id:
        await _link_through(gid, body.project_id)
    await record("goal", "phase goal set", detail=body.text.strip()[:70], entity_id=gid)
    return await _one_goal(gid)


@router.patch("/goals/{gid}")
async def update_goal(gid: str, body: PoolGoalUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    project_id = fields.pop("project_id", "__unset__")
    if fields.get("due"):
        _parse_date(fields["due"])
    if fields:
        sets = [f"g.{k} = ${k}" for k in fields]
        # Editing a goal that was flagged clears the flag: you have just looked
        # at it, and drift.py will put it back on the next read if it still
        # applies. A flag that survives being addressed is noise. Setting the
        # status by hand is the exception — that is you overruling the rules.
        if "status" not in fields:
            sets += ["g.status = 'on'", "g.flag_reason = ''", "g.flagged_at = null"]
        rows = await run_write(
            f"MATCH (g:PoolGoal {{id: $id}}) SET {', '.join(sets)} RETURN g.id AS id",
            id=gid, **fields)
        if not rows:
            raise HTTPException(404, "no such goal")
    if project_id != "__unset__":
        await _link_through(gid, project_id)
    await record("goal", "phase goal updated",
                 detail=", ".join(fields) or "project", entity_id=gid)
    return await _one_goal(gid)


@router.delete("/goals/{gid}", status_code=204, response_class=Response)
async def delete_goal(gid: str) -> Response:
    """Remove a goal. Its :Change rows are deliberately left behind: they carry
    the goal's text on them as `subject`, they are tagged IN_PHASE in their own
    right, and a renegotiation you had is a thing that happened whether or not
    the goal it was about still exists."""
    await run_write("MATCH (g:PoolGoal {id: $id}) DETACH DELETE g", id=gid)
    await record("goal", "phase goal removed", detail=gid)
    return Response(status_code=204)


@router.post("/goals/{gid}/renegotiate")
async def renegotiate(gid: str, body: Renegotiate) -> dict:
    """Talk a flagged goal through. Three levers, and every one writes it down.

    The spec calls this POST /goals/{id}/renegotiate. It lives under /api/phases
    because that is the only thing left that has goals: the topbar Goals tab and
    its :PeriodGoal nodes were removed with the Inbox rework, and a phase now
    claims a :Project directly rather than a goal raised from one.

    Whichever lever you pull, the goal comes out `renegotiated` rather than
    `on`: the month view says so afterwards, because a goal that has been
    renegotiated twice is worth knowing about even once it is going fine.
    """
    rows = await run_read("MATCH (g:PoolGoal {id: $id}) RETURN g", id=gid)
    if not rows:
        raise HTTPException(404, "no such goal")
    goal = dict(rows[0]["g"])
    if not body.reason.strip():
        raise HTTPException(400, "say why — the reason is the point of the log")

    # Each lever is one field, its old value, and its new one. Naming them here
    # keeps the :Change row readable years later without a lookup table.
    if body.lever == "move_due":
        _parse_date(body.value)
        what, field = "due date", "due"
        old, new = str(goal.get("due") or "not set"), body.value[:10]
        sets, params = "g.due = $v", {"v": body.value[:10]}
    elif body.lever == "cut_scope":
        try:
            v = float(body.value)
        except ValueError:
            raise HTTPException(400, "cut scope wants a number — the new total")
        what, field = "scope", "scope_total"
        old, new = f"{float(goal.get('scope_total') or 0):g}", f"{v:g}"
        sets, params = "g.scope_total = $v", {"v": v}
    else:                                   # add_hours
        try:
            v = float(body.value)
        except ValueError:
            raise HTTPException(400, "add hours wants a number — the new hours a day")
        what, field = "hours a day", "plan_h_day"
        old, new = f"{float(goal.get('plan_h_day') or 0):g}h", f"{v:g}h"
        sets, params = "g.plan_h_day = $v", {"v": v}

    cid = str(uuid.uuid4())
    now = _now()
    await run_write(
        f"""
        MATCH (g:PoolGoal {{id: $id}})
        SET {sets}, g.status = 'renegotiated', g.flag_reason = '',
            g.flagged_at = null, g.renegotiated_at = $now
        WITH g
        MATCH (p:Phase)<-[:IN_PHASE]-(g)
        CREATE (c:Change {{id: $cid, when: $now, created_at: $now,
                          what: $what, field: $field, from: $old, to: $new,
                          reason: $reason, lever: $lever, subject: g.text}})
        CREATE (c)-[:ABOUT]->(g)
        CREATE (c)-[:IN_PHASE]->(p)
        """, id=gid, cid=cid, now=now, what=f"{goal.get('text', '')} — {what}",
        field=field, old=old, new=new, reason=body.reason.strip(),
        lever=body.lever, **params)
    await record("goal", "goal renegotiated",
                 detail=f"{goal.get('text', '')[:40]}: {old} → {new}"[:70],
                 entity_id=gid)
    return await _one_goal(gid)


@router.get("/{pid}/changes")
async def phase_changes(pid: str) -> list[dict]:
    """Every renegotiation in one phase, newest first. The spine of the "what
    changed" box in step 5; useful on its own long before that."""
    rows = await run_read(
        """
        MATCH (c:Change)-[:IN_PHASE]->(:Phase {id: $id})
        OPTIONAL MATCH (c)-[:ABOUT]->(g:PoolGoal)
        RETURN c{.*} AS change, g.text AS goal, g.id AS goal_id
        ORDER BY c.when DESC
        """, id=pid)
    return [{**dict(r["change"]), "goal": r["goal"] or "",
             "goal_id": r["goal_id"] or ""} for r in rows]


async def _link_through(gid: str, project_id: str) -> None:
    """Point a goal at the project its work happens in — or at nothing.

    This is what makes rule 2 possible: without it there is no such thing as "no
    sessions against this goal", because nothing says which sessions would count.
    """
    await run_write("MATCH (g:PoolGoal {id: $id})-[r:THROUGH]->() DELETE r", id=gid)
    if project_id:
        await run_write(
            "MATCH (g:PoolGoal {id: $id}), (pr:Project {id: $pid}) "
            "MERGE (g)-[:THROUGH]->(pr)", id=gid, pid=project_id)


async def _one_goal(gid: str) -> dict:
    g = await poolgoals.one(gid)
    if not g:
        raise HTTPException(404, "no such goal")
    return g


def _mins_between(a: str | None, b: str | None) -> int:
    """"09:00" to "12:00" -> 180. Anything unparseable is 0 rather than a guess."""
    def hm(t):
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    try:
        return max(0, hm(b) - hm(a))
    except Exception:  # noqa: BLE001
        return 0


async def _today_tasks(pid: str, today: str) -> list[dict]:
    """Today, as a list you can tick.

    A task is on it if it is due today or if something in the calendar plans it
    for today — those are two different ways of saying "this is today's", and
    leaving either out means a day that looks emptier than it is.
    """
    rows = await run_read(_TODAY_TASKS, phase=pid, today=today)
    out = []
    for r in rows:
        t = dict(r["task"])
        planned = _mins_between(r.get("at"), r.get("until"))
        out.append({
            **t,
            "serves": dict(r["serves"]) if r.get("serves") else None,
            "at": r.get("at") or "",
            "planned_mins": planned,
            "logged_mins": r.get("logged_mins") or 0,
        })
    return out


async def _week_hours(pid: str, week_start: str, week_end: str) -> float:
    """Hours logged this week against anything in the phase.

    Summed over the phase's projects, the same source the phase total comes
    from, so the week and the phase can never tell different stories.
    """
    rows = await run_read(
        "MATCH (pr:Project)-[:IN_PHASE]->(:Phase {id: $id}) RETURN pr.id AS id", id=pid)
    idx = await hours_index(week_start, week_end)
    return round(idx.of_all([r["id"] for r in rows])["mins"] / 60.0, 1)


# What a task or a calendar block is allowed to be. Both are the same edge with
# the same meaning; only the label differs, so one route covers both.
_SERVES_LABEL = {"task": "Task", "event": "CalEvent"}


@router.post("/goals/{gid}/serves", status_code=201)
async def add_serves(gid: str, body: ServesGoal) -> dict:
    """Say that a task or a calendar block is there to move this goal along.

    This is what the chip on the day list reads, and what lets drift rule 1
    notice that something else took a block the goal needed. Without it a goal
    is just a sentence; with it the goal is attached to the week.
    """
    label = _SERVES_LABEL[body.kind]
    rows = await run_write(
        f"""
        MATCH (g:PoolGoal {{id: $gid}}), (n:{label} {{id: $nid}})
        MERGE (n)-[:SERVES]->(g)
        RETURN n.id AS id
        """, gid=gid, nid=body.id)
    if not rows:
        raise HTTPException(404, f"no such goal or {body.kind}")
    await record("goal", "goal linked", detail=f"{body.kind} → goal", entity_id=gid)
    return await _one_goal(gid)


@router.delete("/goals/{gid}/serves/{nid}")
async def remove_serves(gid: str, nid: str) -> dict:
    """Take the chip off. The task or block stays; it just stops counting
    toward whether this goal came true."""
    await run_write(
        "MATCH (n {id: $nid})-[r:SERVES]->(:PoolGoal {id: $gid}) DELETE r",
        gid=gid, nid=nid)
    await record("goal", "goal unlinked", detail=nid, entity_id=gid)
    return await _one_goal(gid)


# =========================================================================== #
# THE POOL
#
# Every goal there is, whether or not a phase has claimed it. The Goals tab
# reads this; it is the list a phase pulls from. Creating is not here on
# purpose — projects raise goals, and routing every creation through one place
# is what keeps that true rather than aspirational.
# =========================================================================== #

@router.get("/pool")
async def goal_pool(status: str | None = None, project_id: str | None = None,
                    unclaimed: bool = False) -> list[dict]:
    """The whole pool, newest first, with each goal's phase claims on it.

    `unclaimed=true` is what the phase's "pull in" panel asks for: goals no
    phase has taken yet. Filtering by phase is not offered because a goal can be
    claimed by several over its life, and "which phase is this in" is a question
    with more than one answer by design.
    """
    where = ["true"]
    params = {}
    if status:
        where.append("coalesce(g.status, 'on') = $status")
        params["status"] = status
    if project_id:
        where.append("(g)-[:THROUGH]->(:Project {id: $project_id})")
        params["project_id"] = project_id
    if unclaimed:
        where.append("NOT (g)-[:CLAIMED_BY]->(:Phase)")
    return await poolgoals.read(" AND ".join(where), **params)


# =========================================================================== #
# PULLING IN
#
# A phase does not make projects. It claims them:
#
#     (:Project)-[:CLAIMED_BY {hours, date}]->(:Phase)
#
# Whole projects only: what is attached to a project (PART_OF) and its tasks
# come with it, so nothing is pulled item by item.
#
# The distinction is the whole point of the pool. A project claimed by the
# spring phase and again by the summer one is one project with a history, not
# two; when the phase ends it is still there, unclaimed again, ready for the
# next one or ready to be dropped on purpose. (Phase goals are claimed the same
# way, when they are written; see create_goal.)
#
# Sessions are not pulled in. They arrive on their own through the IN_PHASE
# hook, because work you did during a phase is in it whether or not you
# remembered to say so.
# =========================================================================== #

# A phase pulls whole projects. Attachments come with the project (PART_OF),
# so there is no per-item pull: tasks and habits arrive through their project.
_PULL_LABEL = {"project": "Project"}


@router.get("/pullable")
async def pullable(kind: str = "project") -> list[dict]:
    """The projects the running phase could take on: the pool, minus what it
    already has. Each row is `id`, `text`, a `meta` line and an estimate."""
    pid = await _active_id()
    if not pid:
        return []
    if kind not in _PULL_LABEL:
        raise HTTPException(400, f"kind must be one of {', '.join(_PULL_LABEL)}")

    if kind == "project":
        # Any project node, at any depth, with its path so two projects called
        # "notes" under different parents are tellable apart. The estimate
        # offered is the project's own range; the panel lets you override it,
        # because taking a project on for fewer hours than it is worth is a
        # normal thing to decide.
        rows = await run_read(
            """
            MATCH (pr:Project)
            WHERE NOT (pr)-[:CLAIMED_BY]->(:Phase {id: $pid})
            OPTIONAL MATCH path = (pr)-[:CHILD_OF*0..]->(root:Project)
            WHERE NOT (root)-[:CHILD_OF]->(:Project)
            WITH pr, nodes(path) AS chain
            ORDER BY size(chain) DESC
            WITH pr, head(collect(chain)) AS chain
            // Every descendant, not just the direct children: the claim
            // cascades the whole way down, so this number has to be what
            // taking it on actually takes on.
            OPTIONAL MATCH (kid:Project)-[:CHILD_OF*1..]->(pr)
            RETURN pr.id AS id, pr.name AS text,
                   [n IN reverse(chain) | n.name] AS parts,
                   coalesce(pr.low_h, 0.0) AS low,
                   coalesce(pr.high_h, 0.0) AS high,
                   coalesce(pr.done_when, '') AS done_when,
                   count(kid) AS kids,
                   EXISTS { MATCH (pr)-[:ABOUT]->(:Paper {kind: 'book'}) } AS is_book
            ORDER BY parts
            LIMIT 300
            """, pid=pid)
        out = []
        for r in rows:
            path = " › ".join(r["parts"] or [r["text"]])
            bits = []
            if r["is_book"]:
                bits.append("a book — claiming it claims the book")
            if r["kids"]:
                bits.append(f"{r['kids']} project"
                            + ("s" if r["kids"] != 1 else "")
                            + " under it — claimed with it")
            if r["done_when"]:
                bits.append("done when: " + r["done_when"])
            out.append({"id": r["id"], "text": r["text"],
                        "meta": " · ".join(bits),
                        "estimate_h": r["high"] or r["low"] or 0.0,
                        "sub": path})
        return out
    return []


@router.post("/{pid}/pull", status_code=201)
async def pull_in(pid: str, body: PullIn) -> dict:
    """Claim one thing into this phase, with the hours it is being taken on for.

    Idempotent: pulling the same goal twice updates the hours rather than
    drawing a second edge, because "claimed twice" is not a state, it is a
    corrected number.
    """
    label = _PULL_LABEL.get(body.kind)
    if not label:
        raise HTTPException(400, f"kind must be one of {', '.join(_PULL_LABEL)}")
    rows = await run_write(
        f"""
        MATCH (n:{label} {{id: $nid}}), (p:Phase {{id: $pid}})
        MERGE (n)-[r:CLAIMED_BY]->(p)
          ON CREATE SET r.date = $today
        SET r.hours = $hours
        RETURN coalesce(n.text, n.title, n.name, '(untitled)') AS text
        """, nid=body.id, pid=pid, hours=body.hours,
        today=date.today().isoformat())
    if not rows:
        raise HTTPException(404, f"no such phase or {body.kind}")

    if body.kind == "project":
        # Claiming a parent claims everything under it. A phase that has taken
        # on "Research" has taken on the work inside Research; leaving the
        # children out would make the phase's hours smaller than the thing it
        # said it was doing. Hours are left at 0 on the descendants so the
        # parent's number is not counted twice.
        await run_write(
            """
            MATCH (root:Project {id: $nid}), (p:Phase {id: $pid})
            MATCH (kid:Project)-[:CHILD_OF*1..]->(root)
            MERGE (kid)-[r:CLAIMED_BY]->(p)
              ON CREATE SET r.date = $today, r.hours = 0.0
            """, nid=body.id, pid=pid, today=date.today().isoformat())
        # The IN_PHASE membership the rest of this file reads for hours and
        # counts, for the project and everything under it.
        await run_write(
            """
            MATCH (root:Project {id: $nid}), (p:Phase {id: $pid})
            MATCH (pr:Project)
            WHERE pr = root OR (pr)-[:CHILD_OF*1..]->(root)
            MERGE (pr)-[:IN_PHASE]->(p)
            """, nid=body.id, pid=pid)

    if body.why.strip():
        # Against the edge, not the goal: a goal claimed by two phases was
        # claimed for two different reasons, and the reason belongs to the claim.
        hop = await run_read(
            "MATCH (h:Hop {from_id: $f, rel: 'CLAIMED_BY', to_id: $t}) RETURN h.id AS id",
            f=body.id, t=pid)
        hid = hop[0]["id"] if hop else str(uuid.uuid4())
        if not hop:
            await run_write(
                "CREATE (h:Hop {id: $id, from_id: $f, rel: 'CLAIMED_BY', to_id: $t, "
                "created_at: $now})", id=hid, f=body.id, t=pid, now=_now())
        await run_write(
            """
            MATCH (h:Hop {id: $hid})
            CREATE (n:Note {id: randomUUID(), date: $today, text: $text,
                            kind: 'why', created_at: $now})
            CREATE (n)-[:NOTE_ON]->(h)
            """, hid=hid, text=body.why.strip(),
            today=date.today().isoformat(), now=_now())

    await record("goal", "pulled into the phase",
                 detail=f"{body.kind}: {rows[0]['text'][:44]}"[:70], entity_id=body.id)
    return {"ok": True, "kind": body.kind, "id": body.id}


@router.delete("/{pid}/pull/{nid}")
async def drop_claim(pid: str, nid: str) -> dict:
    """Let something go again. The thing itself is untouched: it returns to the
    pool, which is where it lives."""
    await run_write(
        "MATCH ({id: $nid})-[r:CLAIMED_BY]->(:Phase {id: $pid}) DELETE r",
        nid=nid, pid=pid)
    await record("goal", "dropped from the phase", detail=nid, entity_id=nid)
    return {"ok": True}


# Declared last on purpose. FastAPI matches routes in the order they are
# registered, and "/{pid}" will happily swallow "/goals" — which it did, until
# this moved down here. Any new single-segment GET under /api/phases has to be
# declared above this one.
@router.get("/{pid}")
async def get_phase(pid: str) -> dict:
    return await _one(pid)




