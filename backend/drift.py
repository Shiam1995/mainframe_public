"""Drift — the four rules that decide a phase goal has stopped going to plan.

A goal on the dashboard is not a checkbox. It is a claim about the next week or
month, and the point of the phase view is to catch the claim going wrong while
there is still time to do something about it, rather than at the end when all
you can do is write it down. These rules are that catch.

THE FOUR RULES, from the v1 header. Each returns a reason in your own words or
nothing at all; the first one to fire wins, because a goal with four reasons
attached is a goal you will not read.

  1. DISPLACED   something landed in a slot the goal's plan needed. A planned
                 block that serves the goal is overlapped, on the same day, by
                 an event that does not.
  2. STALE       no session against the goal's work for STALE_DAYS (4). Counts
                 sessions on the project the goal runs through and on any task
                 that serves it.
  3. BURN        what is left will not fit in what is left: remaining estimated
                 hours > days to the due date * the hours a day you planned.
  4. THURSDAY    hours logged this week are under 60% of the week's plan, and it
                 is Thursday or later. Before Thursday a slow start is a slow
                 start; from Thursday it is a week that will not land.

WHAT FLAGGING DOES AND DOES NOT DO. It sets `status = 'flagged'` and writes the
reason. It does not move a date, cut anything, or touch the plan: those are the
three levers behind "talk this through", and they are yours to pull. A goal that
is `done` is never flagged. A goal that was already renegotiated can be flagged
again — agreeing new terms once does not make them true.

WHEN IT RUNS. On every read of the dashboard, which is the only place flags are
shown, so what you are looking at was computed against the clock you are looking
at it with. There is no nightly tick: a flag nobody is looking at changes
nothing, and computing it on read means it can never be stale.

Un-flagging is part of the same pass. A goal whose reason has gone away — the
clashing event was moved, the sessions resumed — goes quietly back to `on`. The
flag is a description of right now, not a mark on your record.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from db import run_read, run_write

log = logging.getLogger("synapse.drift")

# Days without a session before a goal counts as stale. Four rather than a week:
# a goal you have not touched since Friday is in trouble by Wednesday, and being
# told on Wednesday is the whole point.
STALE_DAYS = 4

# Fraction of the week's planned hours that has to be in by Thursday.
THURSDAY_FLOOR = 0.6

# Monday is 0, so Thursday is 3.
THURSDAY = 3

# Statuses a rule may move. `done` is finished and `flagged` is already flagged;
# `renegotiated` is live again the moment the new terms are agreed.
LIVE = ("on", "renegotiated", "flagged", "")


def _hm(t: str | None) -> int:
    """"18:30" -> 1110 minutes. Unparseable or missing reads as -1, which never
    overlaps anything — an event with no time cannot displace a block."""
    try:
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return -1


def _pretty(iso: str) -> str:
    """"2026-10-01" -> "thu 1 oct", the way the reasons are written."""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%a %-d %b").lower()
    except Exception:  # noqa: BLE001
        return iso


# Everything the rules need about one goal, in one read. Kept as a single query
# per phase rather than one per goal: a dozen goals should not be a dozen round
# trips on every dashboard load.
_GOAL_FACTS = """
MATCH (g:PoolGoal)-[:CLAIMED_BY]->(:Phase {id: $phase})
WHERE coalesce(g.status, 'on') <> 'done'

// the project this goal's work runs through, if it was given one
OPTIONAL MATCH (g)-[:THROUGH]->(pr:Project)

// the last session against either the project or a task serving the goal
OPTIONAL MATCH (w:WorkSession)-[:ON]->(x)
  WHERE (pr IS NOT NULL AND x = pr) OR (x:Task AND (x)-[:SERVES]->(g))
WITH g, pr, max(w.date) AS last_session,
     sum(CASE WHEN w.date >= $week_start AND w.date <= $week_end
              THEN coalesce(w.mins, 0) ELSE 0 END) AS week_mins

// blocks planned for this goal in the week being looked at
OPTIONAL MATCH (blk:CalEvent)-[:SERVES]->(g)
  WHERE blk.date >= $week_start AND blk.date <= $week_end
RETURN g{.*} AS goal, pr.name AS project, pr.id AS project_id,
       last_session, week_mins,
       collect(blk{.id, .date, .start, .end, .title}) AS blocks
"""

# Anything else on the same day that could have taken a block's place. Read once
# for the week rather than once per block.
_WEEK_EVENTS = """
MATCH (e:CalEvent)
WHERE e.date >= $week_start AND e.date <= $week_end
OPTIONAL MATCH (e)-[:SERVES]->(g:PoolGoal)
RETURN e{.id, .date, .start, .end, .title} AS event,
       collect(g.id) AS serves
"""


def _displaced(blocks: list[dict], events: list[dict]) -> str | None:
    """Rule 1. A planned block overlapped, on its own day, by something else."""
    for blk in blocks:
        if not blk or not blk.get("id"):
            continue
        b0, b1 = _hm(blk.get("start")), _hm(blk.get("end"))
        if b0 < 0 or b1 <= b0:
            continue
        for ev in events:
            e = ev["event"]
            if e["id"] == blk["id"] or e["date"] != blk["date"]:
                continue
            if blk["id"] in (ev["serves"] or []) or e["id"] in (ev["serves"] or []):
                continue
            e0, e1 = _hm(e.get("start")), _hm(e.get("end"))
            if e0 < 0 or e1 <= e0 or e1 <= b0 or e0 >= b1:
                continue
            return (f"{_pretty(blk['date'])} {blk.get('start', '')} block lost to "
                    f"{e.get('title') or 'another event'}")
    return None


def _stale(goal: dict, last_session: str | None, project: str | None,
           today: date) -> str | None:
    """Rule 2. Nothing logged against the goal's work for STALE_DAYS."""
    # A goal with nothing to log against cannot go stale — there is no signal,
    # and inventing one would flag every goal that is not run through a project.
    if not project and not goal.get("has_tasks"):
        return None
    if not last_session:
        # Never worked on. Only worth saying once it has had a fair run at it.
        started = str(goal.get("created_at") or "")[:10]
        if started and (today - date.fromisoformat(started)).days >= STALE_DAYS:
            return f"not started since it was set on {_pretty(started)}"
        return None
    gap = (today - date.fromisoformat(last_session[:10])).days
    if gap >= STALE_DAYS:
        return f"0h since {_pretty(last_session)}, {gap} days ago"
    return None


def _burn(goal: dict, today: date) -> str | None:
    """Rule 3. What is left will not fit in the days that are left."""
    due, per_day = str(goal.get("due") or ""), float(goal.get("plan_h_day") or 0)
    if not due or per_day <= 0:
        return None
    try:
        days_left = (date.fromisoformat(due[:10]) - today).days
    except ValueError:
        return None
    if days_left < 0:
        return f"due {_pretty(due)} and not finished"
    left = _hours_left(goal)
    if left is None:
        return None
    capacity = days_left * per_day
    if left > capacity:
        return (f"{left:.1f}h left with {days_left} days to {_pretty(due)} — "
                f"that is {capacity:.1f}h at the {per_day:g}h a day you planned")
    return None


def _hours_left(goal: dict) -> float | None:
    """Estimated hours still to do.

    Scope is the better estimate when it has been given ("3 of 5 sections" says
    two fifths of the work is left), and the raw estimate is the fallback.
    """
    est = float(goal.get("estimate_h") or 0)
    if est <= 0:
        return None
    total = float(goal.get("scope_total") or 0)
    if total > 0:
        done = min(float(goal.get("scope_done") or 0), total)
        return est * (total - done) / total
    return est


def _thursday(goal: dict, week_mins: int, today: date) -> str | None:
    """Rule 4. Under 60% of the week's plan, and the week is more than half gone."""
    plan = float(goal.get("plan_h_week") or 0)
    if plan <= 0 or today.weekday() < THURSDAY:
        return None
    logged = (week_mins or 0) / 60.0
    if logged < plan * THURSDAY_FLOOR:
        return (f"{logged:.1f}h of {plan:g}h in by {today.strftime('%A').lower()} — "
                f"under {int(THURSDAY_FLOOR * 100)}% of the week with the week nearly gone")
    return None


async def evaluate(phase_id: str, today: date | None = None) -> list[dict]:
    """Run the rules over one phase's goals and write back what changed.

    Returns the goals as the dashboard should show them: each one's current
    status and, when it is flagged, the reason in the words above.
    """
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    week_start, week_end = monday.isoformat(), (monday + timedelta(days=6)).isoformat()

    try:
        rows = await run_read(_GOAL_FACTS, phase=phase_id,
                              week_start=week_start, week_end=week_end)
        events = await run_read(_WEEK_EVENTS, week_start=week_start, week_end=week_end)
    except Exception as exc:  # noqa: BLE001
        log.warning("drift check failed for phase %s: %s", phase_id, exc)
        return []

    out, changes = [], []
    for row in rows:
        goal = dict(row["goal"])
        status = goal.get("status") or "on"
        if status not in LIVE:
            out.append(goal)
            continue

        blocks = [b for b in (row["blocks"] or []) if b and b.get("id")]
        goal["has_tasks"] = False           # filled by the caller's task read
        reason = (
            _displaced(blocks, events)
            or _stale(goal, row["last_session"], row["project"], today)
            or _burn(goal, today)
            or _thursday(goal, row["week_mins"], today)
        )

        was_flagged = status == "flagged"
        if reason and not was_flagged:
            # Newly in trouble. `renegotiated` is remembered separately so the
            # month view can still say a goal has been renegotiated once.
            changes.append({"id": goal["id"], "status": "flagged", "reason": reason})
            goal["status"], goal["flag_reason"] = "flagged", reason
        elif reason and was_flagged and goal.get("flag_reason") != reason:
            # Still in trouble, but for a new reason. Say the new one.
            changes.append({"id": goal["id"], "status": "flagged", "reason": reason})
            goal["flag_reason"] = reason
        elif not reason and was_flagged:
            # It came right on its own. Back to `renegotiated` if that is what it
            # was before the flag, so the history is not quietly erased.
            back = "renegotiated" if goal.get("renegotiated_at") else "on"
            changes.append({"id": goal["id"], "status": back, "reason": ""})
            goal["status"], goal["flag_reason"] = back, ""

        out.append(goal)

    if changes:
        try:
            await run_write(
                """
                UNWIND $changes AS c
                MATCH (g:PoolGoal {id: c.id})
                SET g.status = c.status, g.flag_reason = c.reason,
                    g.flagged_at = CASE WHEN c.status = 'flagged' THEN $now ELSE null END
                """, changes=changes, now=datetime.now().isoformat(timespec="seconds"))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not write drift flags for phase %s: %s", phase_id, exc)

    return out
