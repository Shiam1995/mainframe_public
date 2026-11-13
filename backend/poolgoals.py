"""Pool goals — the one place a goal is defined, read and shaped.

    (:Goal:PoolGoal {id, text, horizon, due, estimate_h, status, ...})

Three tabs touch these and none of them owns them:

    Project   raises them. "raise to goal" is the only way one is created, so
              every goal has somewhere it came from or a deliberate decision
              that it came from nowhere.
    Goals     is the pool. It lists them, edits them, and shows which phases
              have claimed which. It does not create them.
    Phases    pulls from the pool, writing (:Goal)-[:CLAIMED_BY {hours, date}]
              ->(:Phase). Claiming is not creating: the goal outlives the phase
              and can be claimed again by the next one.

WHY THE EXTRA LABEL. The bare :Goal label already has two tenants with
different shapes (the focus panel and the fitness module) and goals.py warns in
as many words that a third would make every MATCH a guessing game. :PoolGoal is
what lets those two keep their own goals to themselves.

TWO EDGES, ONE MEANING EACH:

    (g)-[:THROUGH]->(:Project)     which project the work happens in. It is
                                   also which project raised it, because those
                                   are the same project every time one is
                                   raised, and two edges saying that would be
                                   two things to keep in step. drift.py reads
                                   this to know whose sessions count.
    (g)-[:FROM_IDEA]->(:Idea)      the ideas a raised goal came out of, if any
                                   were ticked when it was raised.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from db import run_read, run_write

HORIZONS = ("day", "week", "month")
STATUSES = ("on", "flagged", "renegotiated", "done")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# One goal with everything the three tabs read off it. `$$WHERE$$` is replaced
# rather than formatted because the query is full of Cypher map projections and
# str.format would choke on their braces.
ROWS = """
MATCH (g:PoolGoal)
WHERE $$WHERE$$
OPTIONAL MATCH (g)-[:THROUGH]->(pr:Project)
// The goal's own window, from its due date: the Mon-Sun week and the calendar
// month that contain it. A goal with no due falls back to the current ones.
// Counting against "this week" instead would reset a September goal to zero
// on the first of October.
WITH g, pr,
     CASE WHEN coalesce(g.due, '') = '' THEN null ELSE date(substring(g.due, 0, 10)) END AS d
WITH g, pr,
     CASE WHEN d IS NULL THEN $week_start ELSE toString(d - duration({days: d.dayOfWeek - 1})) END AS gw_start,
     CASE WHEN d IS NULL THEN $week_end ELSE toString(d + duration({days: 7 - d.dayOfWeek})) END AS gw_end,
     CASE WHEN d IS NULL THEN $month_start ELSE toString(date.truncate('month', d)) END AS gm_start,
     CASE WHEN d IS NULL THEN $month_end ELSE toString(date.truncate('month', d) + duration({months: 1}) - duration({days: 1})) END AS gm_end
OPTIONAL MATCH (w:WorkSession)-[:ON]->(x)
  WHERE ((pr IS NOT NULL AND x = pr) OR (x:Task AND (x)-[:SERVES]->(g)))
    AND ((w.date >= gw_start AND w.date <= gw_end) OR (w.date >= gm_start AND w.date <= gm_end))
WITH g, pr,
     sum(CASE WHEN w.date >= gw_start AND w.date <= gw_end THEN coalesce(w.mins, 0) ELSE 0 END) AS week_mins,
     sum(CASE WHEN w.date >= gm_start AND w.date <= gm_end THEN coalesce(w.mins, 0) ELSE 0 END) AS month_mins
OPTIONAL MATCH (t:Task)-[:SERVES]->(g)
WITH g, pr, week_mins, month_mins, count(t) AS task_count,
     count(CASE WHEN coalesce(t.done, false) OR t.status = 'done' THEN 1 END) AS tasks_done
OPTIONAL MATCH (c:Change)-[:ABOUT]->(g)
WITH g, pr, week_mins, month_mins, task_count, tasks_done, count(c) AS changes
OPTIONAL MATCH (g)-[cl:CLAIMED_BY]->(ph:Phase)
WITH g, pr, week_mins, month_mins, task_count, tasks_done, changes,
     collect(CASE WHEN ph IS NULL THEN null ELSE {
       id: ph.id, name: ph.name, number: coalesce(ph.seq, 1),
       status: coalesce(ph.status, 'active'),
       hours: coalesce(cl.hours, 0), date: cl.date } END) AS claims
OPTIONAL MATCH (g)-[:FROM_IDEA]->(i:Idea)
WITH g, pr, week_mins, month_mins, task_count, tasks_done, changes, claims,
     collect(i{.id, .title}) AS ideas
RETURN g{.*} AS goal, pr.name AS project, pr.id AS project_id,
       week_mins, month_mins, task_count, tasks_done, changes, claims, ideas
ORDER BY coalesce(g.due, '9999'), g.created_at
"""


def shape(row: dict) -> dict:
    """One goal as the row on screen, with the meta line already worked out.

    The meta line is built here rather than in the client because it is the
    sentence the drift rules are arguing with: "3 of 5 sections" and the flag
    reason that replaces it have to come from the same numbers.
    """
    g = dict(row["goal"])
    g["project"] = row.get("project") or ""
    g["project_id"] = row.get("project_id") or ""
    g["week_hours"] = round((row.get("week_mins") or 0) / 60.0, 1)
    g["month_hours"] = round((row.get("month_mins") or 0) / 60.0, 1)
    g["task_count"] = row.get("task_count") or 0
    g["tasks_done"] = row.get("tasks_done") or 0
    g["changes"] = row.get("changes") or 0
    g["status"] = g.get("status") or "on"
    g["flag_reason"] = g.get("flag_reason") or ""
    g["estimate_h"] = float(g.get("estimate_h") or 0)

    claims = [c for c in (row.get("claims") or []) if c and c.get("id")]
    claims.sort(key=lambda c: c.get("date") or "")
    g["claims"] = claims
    # Hours already promised to a phase, so the Goals pool can say how much of
    # an estimate is spoken for without the client adding up a list.
    g["claimed_h"] = round(sum(float(c.get("hours") or 0) for c in claims), 1)
    g["ideas"] = [i for i in (row.get("ideas") or []) if i and i.get("id")]

    bits = []
    total, done = float(g.get("scope_total") or 0), float(g.get("scope_done") or 0)
    if total > 0:
        bits.append(f"{done:g} of {total:g}")
    elif g["task_count"]:
        bits.append(f"{g['tasks_done']} of {g['task_count']} tasks")
    if g.get("due"):
        bits.append("due " + str(g["due"])[:10])
    if g["estimate_h"]:
        bits.append(f"{g['estimate_h']:g}h estimated")
    if g.get("horizon") == "month":
        if g["month_hours"]:
            bits.append(f"{g['month_hours']:g}h this month")
    elif g["week_hours"]:
        bits.append(f"{g['week_hours']:g}h this week")
    if g.get("renegotiated_at"):
        bits.append("renegotiated " + str(g["renegotiated_at"])[:10])
    g["meta"] = " · ".join(bits)
    g["progress"] = progress(g)
    return g


def _month() -> tuple[str, str]:
    today = date.today()
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


def progress(g: dict) -> dict:
    """The goal's bar: {measure, done, total, pct, unit, label, auto}.

    count  scope_done of scope_total, bumped by hand
    hours  sessions on its project inside its window against target_h. The
           window is the week (week goal) or calendar month (month goal) that
           holds its due date. Never typed, so it can't be fudged.
    tasks  tasks that SERVE it, done of all
    """
    m = g.get("measure") or ("count" if float(g.get("scope_total") or 0) else
                             "tasks" if g.get("task_count") else "count")
    if m == "hours":
        done = g["month_hours"] if g.get("horizon") == "month" else g["week_hours"]
        total = float(g.get("target_h") or g.get("plan_h_week") or 0)
        unit, auto = "h", True
    elif m == "tasks":
        done, total, unit, auto = float(g["tasks_done"]), float(g["task_count"]), "tasks", True
    else:
        done, total, unit, auto = float(g.get("scope_done") or 0), float(g.get("scope_total") or 0), "", False
    pct = min(100, round(done / total * 100)) if total > 0 else 0
    label = f"{done:g} of {total:g}{(' ' + unit) if unit else ''}" if total > 0 else f"{done:g}{unit} so far"
    return {"measure": m, "done": done, "total": total, "pct": pct,
            "unit": unit, "label": label, "auto": auto}


def _week() -> tuple[str, str]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


async def read(where: str, **params) -> list[dict]:
    """Goals matching a WHERE clause, shaped. The clause is written by the
    caller because each tab asks a different question of the same pool."""
    ws, we = _week()
    ms, me = _month()
    rows = await run_read(ROWS.replace("$$WHERE$$", where),
                          week_start=ws, week_end=we, month_start=ms, month_end=me, **params)
    return [shape(dict(r)) for r in rows]


async def one(gid: str) -> dict | None:
    rows = await read("g.id = $gid", gid=gid)
    return rows[0] if rows else None


async def create(text: str, *, horizon: str = "week", due: str = "",
                 estimate_h: float = 0.0, project_id: str = "",
                 idea_ids: list[str] | None = None, note: str = "",
                 plan_h_day: float = 0.0, plan_h_week: float = 0.0,
                 scope_total: float = 0.0, scope_done: float = 0.0) -> str:
    """Raise a goal. Returns its id.

    Deliberately not an endpoint of its own: goals are raised from a project (or
    from the pool with no project, which is allowed and is a real state), and
    routing every caller through here is what keeps "no other tab creates goals"
    true rather than aspirational.
    """
    gid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (g:Goal:PoolGoal {
            id: $id, text: $text, horizon: $horizon, due: $due, note: $note,
            status: 'on', flag_reason: '',
            estimate_h: $estimate_h,
            plan_h_day: $plan_h_day, plan_h_week: $plan_h_week,
            scope_total: $scope_total, scope_done: $scope_done,
            created_at: $now
        })
        """, id=gid, text=text.strip(), horizon=horizon, due=due, note=note,
        estimate_h=estimate_h, plan_h_day=plan_h_day, plan_h_week=plan_h_week,
        scope_total=scope_total, scope_done=scope_done, now=_now())
    if project_id:
        await link_project(gid, project_id)
    if idea_ids:
        await run_write(
            """
            MATCH (g:PoolGoal {id: $id})
            UNWIND $ideas AS iid
            MATCH (i:Idea {id: iid})
            MERGE (g)-[:FROM_IDEA]->(i)
            """, id=gid, ideas=idea_ids)
    return gid


async def link_project(gid: str, project_id: str) -> None:
    """Point a goal at its project, or at none.

    One project at a time: this is both "raised from" and "the work runs
    through", and a goal that runs through two projects is a goal that has not
    been split yet.
    """
    await run_write("MATCH (g:PoolGoal {id: $id})-[r:THROUGH]->() DELETE r", id=gid)
    if project_id:
        await run_write(
            "MATCH (g:PoolGoal {id: $id}), (pr:Project {id: $pid}) "
            "MERGE (g)-[:THROUGH]->(pr)", id=gid, pid=project_id)
