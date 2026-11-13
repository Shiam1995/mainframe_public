"""/api/pulse/areas — Habits by area (mainframe_habits_areas.html).

Every habit belongs to one AREA (Fitness, Sleep, Diet, …). Each area links to
the module its data lives in. The week view is Mon–Sun, and every day of every
habit is DERIVED on read, never stored:

  · a hand mark on the day's HabitLog wins: `exception` (excused, counts
    neither way), `adjusted` (moved / made up — on a future day it is a
    planned make-up), or level > 0 (done)
  · otherwise the habit's `source` decides: a recovery session of the right
    type, a workout, a food entry, enough study minutes, or a day with no
    spending. Anything without a source is ticked by hand.

So a habit can never disagree with the module it reads from: log a workout in
Fitness and the gym habit is done; import a bank statement and the no-spend
days back-fill themselves.

Daily habits count each due day up to today (today only once it's done, so the
morning doesn't read as a failure). Weekly habits ("3 per week") count done days
against the target and never miss a single day.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from activity import record
from db import run_read, run_write
from models import HabitAreaCreate, HabitAreaUpdate, HabitDayMark

router = APIRouter(prefix="/api/pulse/areas", tags=["habit-areas"])

# (key, name, colour, tab the area links to). Editable from the UI; seeded once.
_DEFAULT_AREAS = [
    ("fitness", "Fitness", "#4ADE80", "fitness"),
    ("recovery", "Recovery", "#4AC6E0", "recovery"),
    ("sleep", "Sleep", "#5A9DE0", "recovery"),
    ("diet", "Diet", "#F0834A", "nutrition"),
    ("learning", "Learning", "#00D4AA", "phases"),
    ("finance", "Finance", "#D4A017", "transactions"),
    ("focus", "Focus", "#F0A030", "learning"),          # the Lessons tab's view id
    ("output", "Output", "#8B7EC8", "youtube"),
    ("admin", "Admin", "#8a97a8", "inbox"),
    ("medical", "Medical", "#E05A5A", "medications"),
]

# A habit with no `area` set falls into one by its category.
_CATEGORY_AREA = {
    "sleep": "sleep", "fitness": "fitness", "nutrition": "diet", "learning": "learning",
    "mindfulness": "recovery", "recovery": "recovery", "productivity": "focus",
    "creative": "output", "health": "medical", "social": "admin", "other": "admin",
}

_WEEKLY_TARGET = {"3x-week": 3, "weekly": 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(v: str) -> str:
    return f"MERGE (mod:Module {{name: 'pulse'}}) MERGE ({v})-[:OWNED_BY]->(mod)"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _norm(x: str) -> str:
    return " ".join(str(x or "").lower().split())


# =========================================================================== #
# AREAS (config list)
# =========================================================================== #
async def _seed() -> None:
    rows = await run_read("MATCH (a:HabitArea) RETURN count(a) AS n")
    if rows and rows[0]["n"]:
        return
    for i, (key, name, color, tab) in enumerate(_DEFAULT_AREAS):
        await run_write(
            f"MERGE (a:HabitArea {{key: $key}}) SET a.name = $name, a.color = $color, "
            f"a.link_tab = $tab, a.order = $ord, a.custom = false WITH a {_own('a')}",
            key=key, name=name, color=color, tab=tab, ord=i)


@router.get("")
async def list_areas() -> list[dict]:
    await _seed()
    rows = await run_read("MATCH (a:HabitArea) RETURN a{.*} AS a ORDER BY a.order, a.name")
    return [r["a"] for r in rows]


@router.post("", status_code=201)
async def add_area(body: HabitAreaCreate) -> dict:
    await _seed()
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name required")
    key = _norm(name).replace(" ", "-") or str(uuid.uuid4())
    if await run_read("MATCH (a:HabitArea {key: $k}) RETURN a.key", k=key):
        raise HTTPException(409, "that area already exists")
    await run_write(
        f"""
        OPTIONAL MATCH (x:HabitArea) WITH coalesce(max(x.order), -1) + 1 AS o
        CREATE (a:HabitArea {{key: $key, name: $name, color: $color, link_tab: $tab,
                              order: o, custom: true}})
        WITH a {_own('a')}
        """, key=key, name=name, color=body.color, tab=body.link_tab)
    await record("habit", "area added", detail=name[:60])
    return {"key": key}


@router.patch("/{key}")
async def update_area(key: str, body: HabitAreaUpdate) -> dict:
    fields = body.model_dump(exclude_none=True)
    if "name" in fields and not fields["name"].strip():
        raise HTTPException(422, "name required")
    if fields:
        sets = ", ".join(f"a.{k} = ${k}" for k in fields)
        if not await run_write(f"MATCH (a:HabitArea {{key: $key}}) SET {sets} RETURN a.key",
                               key=key, **fields):
            raise HTTPException(404, "area not found")
        await record("habit", "area updated", detail=f"{key}: {', '.join(fields)}")
    return {"key": key}


@router.delete("/{key}")
async def delete_area(key: str) -> dict:
    """Habits in it fall back to their category's area; the habits are kept."""
    await run_write("MATCH (h:Habit {area: $key}) REMOVE h.area", key=key)
    await run_write("MATCH (a:HabitArea {key: $key}) DETACH DELETE a", key=key)
    await record("habit", "area removed", detail=key)
    return {"deleted": key}


# =========================================================================== #
# THE WEEK
# =========================================================================== #
async def _sources(lo: str, hi: str) -> dict:
    """Everything the derived habits read, for one Mon–Sun window."""
    rec = await run_read(
        "MATCH (s:RecoverySession) WHERE substring(s.date, 0, 10) >= $lo AND substring(s.date, 0, 10) <= $hi "
        "RETURN substring(s.date, 0, 10) AS d, s.type_name AS t", lo=lo, hi=hi)
    wk = await run_read(
        "MATCH (w:Workout) WHERE substring(w.date, 0, 10) >= $lo AND substring(w.date, 0, 10) <= $hi "
        "RETURN substring(w.date, 0, 10) AS d, w.type AS t", lo=lo, hi=hi)
    food = await run_read(
        "MATCH (f:FoodEntry) WHERE substring(f.date, 0, 10) >= $lo AND substring(f.date, 0, 10) <= $hi AND f.demo_seed IS NULL "
        "RETURN substring(f.date, 0, 10) AS d, sum(coalesce(f.calories, 0)) AS kcal", lo=lo, hi=hi)
    study = await run_read(
        "MATCH (s:WorkSession) WHERE substring(s.date, 0, 10) >= $lo AND substring(s.date, 0, 10) <= $hi "
        "RETURN substring(s.date, 0, 10) AS d, s.kind AS k, sum(coalesce(s.mins, 0)) AS m", lo=lo, hi=hi)
    spend = await run_read(
        "MATCH (t:Transaction) WHERE substring(t.date, 0, 10) >= $lo AND substring(t.date, 0, 10) <= $hi AND t.amount < 0 "
        "RETURN substring(t.date, 0, 10) AS d, sum(-t.amount) AS s", lo=lo, hi=hi)
    last_tx = await run_read("MATCH (t:Transaction) RETURN max(t.date) AS d")
    dist = await run_read(
        "MATCH (l:Lesson {source: 'distraction'}) WHERE substring(coalesce(l.date, l.created_at), 0, 10) >= $lo "
        "AND substring(coalesce(l.date, l.created_at), 0, 10) <= $hi RETURN count(l) AS n", lo=lo, hi=hi)

    by = lambda: {}  # noqa: E731
    out = {"recovery": by(), "workout": by(), "food": {}, "study": by(), "spend": {}}
    for r in rec:
        out["recovery"].setdefault(r["d"], set()).add(_norm(r["t"]))
    for r in wk:
        out["workout"].setdefault(r["d"], set()).add(_norm(r["t"]))
    for r in food:
        out["food"][str(r["d"])[:10]] = float(r["kcal"] or 0)
    for r in study:
        out["study"].setdefault(str(r["d"])[:10], {})[_norm(r["k"])] = int(r["m"] or 0)
    for r in spend:
        out["spend"][str(r["d"])[:10]] = float(r["s"] or 0)
    out["last_tx"] = str(last_tx[0]["d"] or "")[:10] if last_tx else ""
    out["distractions"] = dist[0]["n"] if dist else 0
    return out


def _derived_done(h: dict, iso: str, src: dict) -> bool | None:
    """True/False from the habit's source; None when it has no source (tick)."""
    source = h.get("source") or ("recovery" if h.get("rule") == "sessions" else "tick")
    types = {_norm(t) for t in (h.get("source_types") or h.get("rule_types") or []) if t}
    if source == "recovery":
        return bool(types & src["recovery"].get(iso, set()))
    if source == "workout":
        got = src["workout"].get(iso, set())
        return bool(got & types) if types else bool(got)
    if source == "food":
        return iso in src["food"]
    if source == "study":
        kinds = types or {"study", "build"}
        mins = sum(m for k, m in src["study"].get(iso, {}).items() if k in kinds)
        return mins >= (h.get("source_min") or 1)
    if source == "no_spend":
        # a day past the last imported transaction isn't a no-spend day, it's unknown
        if not src["last_tx"] or iso > src["last_tx"]:
            return False
        return src["spend"].get(iso, 0) == 0
    return None


def _habit_week(h: dict, logs: dict, src: dict, monday: date, today: date) -> dict:
    created = (h.get("created_at") or "")[:10] or monday.isoformat()
    freq = h.get("frequency") or "daily"
    # per_week only applies to a weekly frequency; a stale value on a habit
    # switched back to daily must not turn it weekly
    target = (h.get("per_week") or _WEEKLY_TARGET[freq]) if freq in _WEEKLY_TARGET else None
    weekly = target is not None
    dows = set(h.get("days_of_week") or [])
    if freq == "weekdays":
        due_dow = {0, 1, 2, 3, 4}
    elif freq == "custom" and dows:
        due_dow = dows
    else:
        due_dow = set(range(7))
    source = h.get("source") or ("recovery" if h.get("rule") == "sessions" else "tick")

    days, done, due, exc, adj_pending = [], 0, 0, 0, 0
    for i in range(7):
        d = monday + timedelta(days=i)
        iso = d.isoformat()
        log = logs.get(iso) or {}
        is_done = (log.get("level") or 0) > 0 or bool(_derived_done(h, iso, src))
        if iso < created:
            state = "before"
        elif not weekly and d.weekday() not in due_dow:
            state = "off"
        elif log.get("exception"):
            state = "exception"
        elif is_done:
            state = "done"
        elif log.get("adjusted"):
            state = "adjust"
        elif d > today:
            state = "future"
        elif source == "no_spend" and (not src["last_tx"] or iso > src["last_tx"]):
            state = "nodata"                     # transactions not imported that far yet
        elif d == today:
            state = "today"
        else:
            state = "open" if weekly else "miss"
        if state == "exception":
            exc += 1
        if state == "adjust" and d >= today:
            adj_pending += 1
        if state == "done":
            done += 1
        # daily: a past due day counts; today counts only once it's done
        if not weekly and state in ("done", "miss"):
            due += 1
        days.append({"date": iso, "state": state})

    if weekly:
        due = target
    pct = round(100 * min(done, due) / due) if due else None
    trial = None
    if (h.get("tier") == "experimental") and h.get("trial_start"):
        try:
            wk = (today - date.fromisoformat(h["trial_start"][:10])).days // 7 + 1
            trial = {"week": max(1, wk), "of": h.get("trial_weeks") or 4}
        except ValueError:
            trial = None
    return {"days": days, "done": done, "due": due, "pct": pct, "exceptions": exc,
            "adjust_pending": adj_pending, "weekly": weekly, "target": target, "trial": trial,
            "source": source}


def _area_strip(habits: list[dict]) -> list[str]:
    """One state per weekday for the area card: on · half · miss · exc · ''.

    on = something done and nothing missed or still open; half = some done;
    miss = nothing done and something missed; exc = only excused/moved days."""
    out = []
    for i in range(7):
        states = [h["week"]["days"][i]["state"] for h in habits]
        done, miss = states.count("done"), states.count("miss")
        pending = states.count("today") + states.count("open")
        if done and not miss and not pending:
            out.append("on")
        elif done:
            out.append("half")
        elif miss:
            out.append("miss")
        elif "exception" in states or "adjust" in states:
            out.append("exc")
        else:
            out.append("")
    return out


@router.get("/week")
async def week(date_: str | None = Query(None, alias="date")) -> dict:
    """The whole Habits-by-area page for the Mon–Sun week holding `date`."""
    today = date.today()
    try:
        anchor = date.fromisoformat(date_) if date_ else today
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    monday = anchor - timedelta(days=anchor.weekday())
    lo, hi = monday.isoformat(), (monday + timedelta(days=6)).isoformat()

    areas = await list_areas()
    keys = {a["key"] for a in areas}
    rows = await run_read(
        """
        MATCH (h:Habit) WHERE coalesce(h.active, true) = true
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog) WHERE l.date >= $lo AND l.date <= $hi
        OPTIONAL MATCH (p:RecoveryProtocol)-[:INCLUDES]->(h) WHERE p.ended IS NULL
        RETURN h{.*} AS h, collect(DISTINCT l{.*}) AS logs, count(p) > 0 AS in_protocol
        ORDER BY h.created_at
        """, lo=lo, hi=hi)
    src = await _sources(lo, hi)

    by_area: dict[str, list[dict]] = {}
    for r in rows:
        h = r["h"]
        area = h.get("area") if h.get("area") in keys else _CATEGORY_AREA.get(h.get("category") or "", "admin")
        if area not in keys:
            area = "admin" if "admin" in keys else (areas[0]["key"] if areas else "other")
        logs = {str(l["date"])[:10]: l for l in r["logs"] if l.get("date")}
        by_area.setdefault(area, []).append({
            "id": h["id"], "name": h["name"], "icon": h.get("icon") or "",
            "category": h.get("category"), "frequency": h.get("frequency") or "daily",
            "tier": h.get("tier") or "main", "area": area, "area_set": bool(h.get("area")),
            "source_types": h.get("source_types") or h.get("rule_types") or [],
            "source_min": h.get("source_min"), "per_week": h.get("per_week"),
            "trial_weeks": h.get("trial_weeks"), "in_protocol": r["in_protocol"],
            "week": _habit_week(h, logs, src, monday, today),
        })

    extras = {
        "learning": f"{sum(m for d in src['study'].values() for m in d.values()) / 60:.1f}h of study + build",
        "fitness": _plural(sum(len(v) for v in src["workout"].values()), "workout") + " logged",
        "recovery": _plural(sum(len(v) for v in src["recovery"].values()), "recovery session"),
        "diet": (f"kcal avg {round(sum(src['food'].values()) / len(src['food'])):,} on logged days"
                 if src["food"] else "nothing logged in Nutrition"),
        "finance": (f"£{sum(src['spend'].values()):,.0f} spent" +
                    (f" · transactions to {src['last_tx']}" if src["last_tx"] and src["last_tx"] < hi else "")),
        "focus": _plural(src["distractions"], "distraction") + " logged",
    }
    out_areas = []
    for a in areas:
        hs = by_area.get(a["key"], [])
        due = sum(h["week"]["due"] or 0 for h in hs)
        done = sum(min(h["week"]["done"], h["week"]["due"] or 0) for h in hs)
        out_areas.append({
            **a, "habits": hs, "pct": round(100 * done / due) if due else None,
            "strip": _area_strip(hs) if hs else [""] * 7,
            "exceptions": sum(h["week"]["exceptions"] for h in hs),
            "adjust_pending": sum(h["week"]["adjust_pending"] for h in hs),
            "extra": extras.get(a["key"], ""),
        })
    return {"week_start": lo, "week_end": hi, "today": today.isoformat(), "areas": out_areas}


@router.post("/habits/{hid}/day")
async def mark_day(hid: str, body: HabitDayMark) -> dict:
    """Hand-mark one day. Derived done-ness can't be cleared — it comes from the source."""
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    level, exc, adj = {"done": (3, False, False), "exception": (0, True, False),
                       "adjust": (0, False, True), "clear": (0, False, False)}[body.state]
    rows = await run_write(
        """
        MATCH (h:Habit {id: $hid})
        MERGE (h)-[:HAS_LOG]->(l:HabitLog {habit_id: $hid, date: $date})
          ON CREATE SET l.id = $id, l.time_spent = '', l.notes = '', l.feel = '', l.connections = ''
        SET l.level = $level, l.exception = $exc, l.adjusted = $adj
        RETURN h.name AS n
        """, hid=hid, date=body.date, id=str(uuid.uuid4()), level=level, exc=exc, adj=adj)
    if not rows:
        raise HTTPException(404, "habit not found")
    await record("habit", "day " + body.state, detail=f"{rows[0]['n'][:40]} · {body.date}")
    return {"ok": True}
