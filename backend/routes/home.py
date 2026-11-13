"""/api/home — the Mainframe home screen (built from mainframe-home3.html).

Three things:
  · lifetime stat tiles  (the strip across the top)
  · a period snapshot    (daily / weekly / monthly, broken down per module)
  · home preferences     (background choice, dim, particles, module card art)

Every number is computed live from the graph — nothing on the home screen is a
stored figure, so it can't drift from the modules it summarises.

Preferences live in Neo4j as a `:HomePrefs` singleton rather than localStorage,
so the home screen looks the same on any browser hitting this Mainframe.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import MAINFRAME_HOME
from db import run_read, run_write
from models import HomePrefsUpdate

router = APIRouter(prefix="/api/home", tags=["home"])

# The installed app (repo root: backend/routes/home.py → ../..)
APP_DIR = Path(__file__).resolve().parents[2]


def _period_range(period: str) -> tuple[str, str, str]:
    """(start_iso, end_iso, human label) for daily | weekly | monthly."""
    today = date.today()
    if period == "daily":
        return today.isoformat(), today.isoformat(), "Today · " + today.strftime("%-d %b")
    if period == "monthly":
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat(), today.strftime("%B %Y")
    start = today - timedelta(days=today.weekday())          # Monday
    end = start + timedelta(days=6)
    # A week can straddle a month, and "27–2 Aug" reads as nonsense — name both
    # months when they differ.
    span = (f"{start.strftime('%-d')}–{end.strftime('%-d %b')}"
            if start.month == end.month
            else f"{start.strftime('%-d %b')} – {end.strftime('%-d %b')}")
    return start.isoformat(), end.isoformat(), f"This week · {span}"


async def _count(cypher: str, **params) -> float:
    rows = await run_read(cypher, **params)
    return float(rows[0]["n"] or 0) if rows else 0.0


@router.get("/stats")
async def stats() -> dict:
    """Lifetime totals for the strip. Deliberately cheap counts."""
    hours = await _count(
        "MATCH (e:TaskEntry) RETURN sum(coalesce(e.time_spent_mins, 0)) AS n")
    workouts = await _count("MATCH (w:Workout) RETURN count(w) AS n")
    habits = await _count(
        "MATCH (l:HabitLog) WHERE coalesce(l.level, 0) > 0 RETURN count(l) AS n")
    content = await _count(
        "MATCH (n) WHERE n:Video OR n:WritingPiece RETURN count(n) AS n")
    projects = await _count("MATCH (p:PortfolioProject) RETURN count(p) AS n")
    return {
        "hours": round(hours / 60, 1),
        "tiles": [
            {"key": "workouts", "label": "WORKOUTS", "value": int(workouts)},
            {"key": "habits", "label": "HABIT INSTANCES", "value": int(habits)},
            {"key": "content", "label": "PIECES OF CONTENT", "value": int(content)},
            {"key": "projects", "label": "PROJECTS", "value": int(projects)},
        ],
    }


@router.get("/snapshot")
async def snapshot(period: str = "weekly") -> dict:
    """What actually happened this day / week / month, per module.

    Entities carrying their own date are counted on that date; the rest fall
    back to the shared activity log, which every mutation already writes to.
    """
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(400, "period must be daily, weekly or monthly")
    lo, hi, label = _period_range(period)
    hi_x = hi + "￿"          # inclusive upper bound for ISO string compares

    async def logged(module: str) -> int:
        return int(await _count(
            "MATCH (l:ChangeEvent) WHERE l.module = $m AND l.timestamp >= $lo "
            "AND l.timestamp <= $hi RETURN count(l) AS n", m=module, lo=lo, hi=hi_x))

    # --- Synapse ---
    papers = await _count(
        "MATCH (p:Paper) WHERE p.added_at >= $lo AND p.added_at <= $hi RETURN count(p) AS n",
        lo=lo, hi=hi_x)
    terms = await _count(
        "MATCH (t:Term) WHERE t.created_at >= $lo AND t.created_at <= $hi RETURN count(t) AS n",
        lo=lo, hi=hi_x)

    # --- Pulse ---
    habit_days = await _count(
        "MATCH (l:HabitLog) WHERE l.date >= $lo AND l.date <= $hi AND coalesce(l.level,0) > 0 "
        "RETURN count(l) AS n", lo=lo, hi=hi)
    workouts = await _count(
        "MATCH (w:Workout) WHERE w.date >= $lo AND w.date <= $hi RETURN count(w) AS n",
        lo=lo, hi=hi)
    recovery = await _count(
        "MATCH (s:RecoverySession) WHERE s.date >= $lo AND s.date <= $hi RETURN count(s) AS n",
        lo=lo, hi=hi)

    # --- Vision ---
    entries = await _count(
        "MATCH (e:JournalEntry) WHERE e.date >= $lo AND e.date <= $hi RETURN count(e) AS n",
        lo=lo, hi=hi_x)

    # --- Vault ---
    money = await run_read(
        """
        MATCH (t:Transaction) WHERE t.date >= $lo AND t.date <= $hi
        RETURN sum(CASE WHEN t.amount < 0 THEN -t.amount ELSE 0 END) AS spent,
               sum(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) AS income
        """, lo=lo, hi=hi)
    spent = float(money[0]["spent"] or 0) if money else 0.0
    income = float(money[0]["income"] or 0) if money else 0.0

    # --- Planner (Mainframe-level; spec §5.4) ---
    from routes.planner import planner_snapshot
    plan = await planner_snapshot(range=period)
    plan_rows = [
        {"label": "Hours vs budget",
         "value": f"{plan['hours_logged']:g} / {plan['hours_budget']:g}h",
         "tone": "good" if plan["hours_logged"] >= plan["hours_budget"] else ""},
        {"label": "On track / drifting",
         "value": f"{plan['items_on_track']} / {plan['items_drifting']}",
         "tone": "bad" if plan["items_drifting"] else ""},
    ]
    if plan.get("focus_item"):
        plan_rows.append({"label": "In focus", "value": plan["focus_item"], "tone": "good"})

    return {
        "period": period, "label": label, "start": lo, "end": hi,
        "sections": [
            {"module": "planner", "rows": plan_rows},
            {"module": "synapse", "rows": [
                {"label": "Papers added", "value": int(papers)},
                {"label": "Terms captured", "value": int(terms)},
                {"label": "Changes logged", "value": await logged("synapse")},
            ]},
            {"module": "pulse", "rows": [
                {"label": "Habit days", "value": int(habit_days)},
                {"label": "Workouts", "value": int(workouts)},
                {"label": "Recovery sessions", "value": int(recovery)},
            ]},
            {"module": "vision", "rows": [
                {"label": "Journal entries", "value": int(entries)},
                {"label": "Changes logged", "value": await logged("vision")},
            ]},
            {"module": "vault", "rows": [
                {"label": "Spent", "value": f"£{spent:,.0f}", "tone": "bad" if spent else ""},
                {"label": "Income", "value": f"£{income:,.0f}", "tone": "good" if income else ""},
                {"label": "Free cash", "value": f"£{income - spent:,.0f}",
                 "tone": "good" if income - spent >= 0 else "bad"},
            ]},
        ],
    }


# --------------------------------------------------------------------------- #
# Total size — how much disk the whole Mainframe occupies: the app itself
# (code + vendored .venv), every user file under ~/.mainframe (images, papers,
# wallpapers…), and the Neo4j store inside the Docker volume. Walking the tree
# takes a moment, so the result is cached for a minute — the home screen polls
# this on every ENTER.
# --------------------------------------------------------------------------- #
_size_cache: dict = {"at": 0.0, "data": None}


def _dir_size(root: Path) -> int:
    total = 0
    stack = [str(root)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


async def _graph_size() -> int | None:
    """Size of /data inside the Neo4j container; None if docker isn't reachable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "mainframe-neo4j", "du", "-sb", "/data",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=6)
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, asyncio.TimeoutError):
        return None


@router.get("/size")
async def total_size() -> dict:
    if _size_cache["data"] and time.monotonic() - _size_cache["at"] < 60:
        return _size_cache["data"]
    loop = asyncio.get_running_loop()
    app_b, data_b = await asyncio.gather(
        loop.run_in_executor(None, _dir_size, APP_DIR),
        loop.run_in_executor(None, _dir_size, MAINFRAME_HOME),
    )
    graph_b = await _graph_size()
    data = {
        "app_bytes": app_b,
        "files_bytes": data_b,
        "graph_bytes": graph_b,
        "total_bytes": app_b + data_b + (graph_b or 0),
        "graph_included": graph_b is not None,
    }
    _size_cache.update(at=time.monotonic(), data=data)
    return data


# --------------------------------------------------------------------------- #
# Preferences — one node, JSON blob. Shape is owned by the frontend, so adding
# a new setting never needs a backend change.
# --------------------------------------------------------------------------- #
@router.get("/prefs")
async def get_prefs() -> dict:
    rows = await run_read("MATCH (p:HomePrefs) RETURN p.data AS data LIMIT 1")
    if not rows or not rows[0]["data"]:
        return {}
    try:
        return json.loads(rows[0]["data"])
    except (TypeError, ValueError):
        return {}


@router.put("/prefs")
async def put_prefs(body: HomePrefsUpdate) -> dict:
    data = json.dumps(body.data or {})
    await run_write(
        "MERGE (p:HomePrefs {id: 'home'}) SET p.data = $data, p.updated_at = $now",
        data=data, now=datetime.now(timezone.utc).isoformat())
    return body.data or {}
