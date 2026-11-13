"""/api/timeline — the master timeline: every module on one horizontal time axis.

A *reader*, like /api/snapshot: no node, table or migration belongs to this
file. Each lane is one or two Cypher reads over data the modules already keep,
so the strip can never drift out of date with them.

The payload is lanes of two shapes:
  spans  — things that last (phases, projects, cycles, experiments), drawn as bars
  points — things that happen on a day (workouts, papers, payments), drawn as dots
plus `work`, minutes logged per day, drawn as a heat strip.

Every lane runs inside its own try/except: one module with odd data must not
blank the whole strip (the snapshot rule). A failed lane comes back with
`error` set and nothing in it.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter

from db import run_read

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

# created_at / added_at / done_at are full ISO timestamps; the strip works in days.
_DAY = "substring(toString({0}), 0, 10)"


def _d(expr: str) -> str:
    return _DAY.format(expr)


def _plus(start: str, days: int) -> str:
    try:
        return (date.fromisoformat(start) + timedelta(days=max(days, 1) - 1)).isoformat()
    except ValueError:
        return start


async def _phases() -> dict:
    rows = await run_read(
        "MATCH (p:Phase) WHERE coalesce(p.start,'') <> '' "
        "RETURN p.id AS id, p.name AS title, p.start AS start, p.end AS end, "
        "p.status AS status, p.goal AS note ORDER BY p.start"
    )
    return {"spans": [dict(r, tab="phases") for r in rows], "points": []}


async def _projects() -> dict:
    # A project runs from when it was made until it was finished; an open one
    # runs to its due date, or to today if it has none. Dropped ones are left
    # off — they never happened, and they'd crowd the ones that did.
    rows = await run_read(
        f"MATCH (p:Project) WHERE coalesce(p.created_at,'') <> '' "
        f"AND NOT coalesce(p.status,'') IN ['dropped','archived'] "
        f"RETURN p.id AS id, p.name AS title, {_d('p.created_at')} AS start, "
        f"CASE WHEN coalesce(p.done_at,'') <> '' THEN {_d('p.done_at')} "
        f"     WHEN coalesce(p.due,'') <> '' THEN p.due ELSE null END AS end, "
        f"p.status AS status, p.kind AS note ORDER BY start"
    )
    today = date.today().isoformat()
    spans = []
    for r in rows:
        end = r["end"] or today
        if end < r["start"]:  # due date set before the project was logged
            end = r["start"]
        spans.append(dict(r, end=end, open=not r["end"], tab="project"))
    return {"spans": spans, "points": []}


async def _pulse() -> dict:
    cycles, exps, workouts, recovery = await asyncio.gather(
        run_read("MATCH (c:Cycle) WHERE coalesce(c.start_date,'') <> '' "
                 "RETURN c.id AS id, c.name AS title, c.start_date AS start, "
                 "toInteger(coalesce(c.weeks, 1)) AS weeks, c.status AS status, c.phase AS note"),
        run_read("MATCH (e:Experiment) WHERE coalesce(e.start_date,'') <> '' "
                 "RETURN e.id AS id, e.name AS title, e.start_date AS start, "
                 "toInteger(coalesce(e.days, 1)) AS days, e.status AS status, e.conclusion AS note"),
        run_read("MATCH (w:Workout) WHERE coalesce(w.date,'') <> '' "
                 "RETURN w.id AS id, coalesce(w.type,'workout') AS title, w.date AS date"),
        run_read("MATCH (r:RecoverySession) WHERE coalesce(r.date,'') <> '' "
                 "RETURN r.id AS id, coalesce(r.type, r.kind, 'recovery') AS title, r.date AS date"),
    )
    spans = [dict(id=c["id"], title="cycle · " + (c["title"] or ""), start=c["start"],
                  end=_plus(c["start"], (c["weeks"] or 1) * 7), status=c["status"],
                  note=c["note"], tab="fitness") for c in cycles]
    spans += [dict(id=e["id"], title="experiment · " + (e["title"] or ""), start=e["start"],
                   end=_plus(e["start"], e["days"] or 1), status=e["status"],
                   note=e["note"], tab="experiments") for e in exps]
    points = [dict(w, kind="workout", tab="fitness") for w in workouts]
    points += [dict(r, kind="recovery", tab="recovery") for r in recovery]
    return {"spans": spans, "points": points}


async def _synapse() -> dict:
    papers, passes = await asyncio.gather(
        run_read(f"MATCH (p:Paper) WHERE coalesce(p.added_at,'') <> '' "
                 f"RETURN p.id AS id, p.title AS title, {_d('p.added_at')} AS date, p.kind AS kind"),
        # A pass dates from its read_date when one was entered, else from when it was opened.
        run_read(f"MATCH (p:Paper)-[]-(i:Instance) "
                 f"WITH p, i, CASE WHEN coalesce(i.read_date,'') <> '' THEN i.read_date "
                 f"               ELSE {_d('i.created_at')} END AS day WHERE day <> '' "
                 f"RETURN DISTINCT p.id AS id, 'v' + toString(i.version) + ' · ' + p.title AS title, "
                 f"day AS date"),
    )
    points = [dict(p, kind="added " + (p.pop("kind") or "paper"), tab="workspace") for p in papers]
    points += [dict(p, kind="reading pass", tab="workspace") for p in passes]
    return {"spans": [], "points": points}


async def _calendar() -> dict:
    rows = await run_read(
        "MATCH (e:CalEvent) WHERE coalesce(e.date,'') <> '' "
        "RETURN e.id AS id, e.title AS title, e.date AS date, e.end_date AS end_date, e.kind AS kind"
    )
    spans, points = [], []
    for r in rows:
        if r["end_date"] and r["end_date"] > r["date"]:
            spans.append(dict(id=r["id"], title=r["title"], start=r["date"], end=r["end_date"], tab="calendar"))
        else:
            points.append(dict(id=r["id"], title=r["title"], date=r["date"], kind=r["kind"] or "event", tab="calendar"))
    return {"spans": spans, "points": points}


async def _vision() -> dict:
    rows = await run_read(
        f"MATCH (v:Video) RETURN v.id AS id, v.title AS title, "
        f"CASE WHEN coalesce(v.target_date,'') <> '' THEN v.target_date ELSE {_d('v.created_at')} END AS date, "
        f"CASE WHEN coalesce(v.target_date,'') <> '' THEN 'video due' ELSE 'video started' END AS kind"
    )
    return {"spans": [], "points": [dict(r, tab="youtube") for r in rows if r["date"]]}


async def _vault() -> dict:
    rows = await run_read(
        "MATCH (t:Transaction) WHERE coalesce(t.date,'') <> '' "
        "RETURN t.id AS id, coalesce(t.description, t.category, 'transaction') AS title, "
        "t.date AS date, toFloat(coalesce(t.amount, 0)) AS amount"
    )
    for r in rows:
        r["title"] = f"{r['title']} {r['amount']:+.2f}"
    return {"spans": [], "points": [dict(r, kind="transaction", tab="transactions") for r in rows]}


async def _life() -> dict:
    lessons, done = await asyncio.gather(
        run_read("MATCH (l:Lesson) WHERE coalesce(l.date,'') <> '' "
                 "RETURN l.id AS id, l.wrong AS title, l.date AS date"),
        run_read(f"MATCH (t:Task) WHERE coalesce(t.done_at,'') <> '' "
                 f"RETURN t.id AS id, t.title AS title, {_d('t.done_at')} AS date"),
    )
    points = [dict(r, kind="lesson", tab="learning") for r in lessons]
    points += [dict(r, kind="done", tab="inbox") for r in done]
    return {"spans": [], "points": points}


async def _work() -> dict:
    rows = await run_read(
        "MATCH (w:WorkSession) WHERE coalesce(w.date,'') <> '' "
        "RETURN w.date AS date, sum(toInteger(coalesce(w.mins, 0))) AS mins ORDER BY date"
    )
    return {"spans": [], "points": [], "days": {r["date"]: r["mins"] for r in rows}}


# Order here is the order the lanes are drawn, top to bottom.
LANES = [
    ("phases",   "Phases",   "mainframe", _phases),
    ("projects", "Projects", "mainframe", _projects),
    ("work",     "Hours",    "mainframe", _work),
    ("calendar", "Calendar", "mainframe", _calendar),
    ("life",     "Done + lessons", "mainframe", _life),
    ("synapse",  "Synapse",  "synapse",   _synapse),
    ("pulse",    "Pulse",    "pulse",     _pulse),
    ("vision",   "Vision",   "vision",    _vision),
    ("vault",    "Vault",    "vault",     _vault),
]


async def _lane(key: str, label: str, module: str, fn) -> dict:
    try:
        return {"key": key, "label": label, "module": module, **await fn()}
    except Exception as e:  # noqa: BLE001 — one bad lane must not blank the strip
        return {"key": key, "label": label, "module": module, "spans": [], "points": [],
                "error": f"{type(e).__name__}: {e}"}


@router.get("")
async def timeline():
    lanes = await asyncio.gather(*(_lane(*l) for l in LANES))
    days = [s["start"] for l in lanes for s in l["spans"]] + \
           [s["end"] for l in lanes for s in l["spans"] if s.get("end")] + \
           [p["date"] for l in lanes for p in l["points"]] + \
           [d for l in lanes for d in (l.get("days") or {})]
    days = [d for d in days if isinstance(d, str) and len(d) == 10]
    today = date.today().isoformat()
    return {
        "today": today,
        "min": min(days + [today]),
        "max": max(days + [today]),
        "lanes": lanes,
    }
