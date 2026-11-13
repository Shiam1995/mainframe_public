"""/api/pulse/scores — a few named scores instead of ten tabs of numbers.

Borrowed from how a consumer health app frames things: rather than showing you
every metric it holds, it rolls them into a handful of named domains, each with
one number, a colour band, and a sentence saying what it means. You read the
strip in two seconds and only go deeper when a band is off.

Pulse has ten tabs — benchmark, habits, tracking, experiments, routines,
fitness, nutrition, recovery, medical, medications. That's a filing cabinet,
not a dashboard. These four scores sit above it.

Two rules this module holds to, and they are the whole point:

  * **No data is not zero.** A domain you've never logged reports `null` with
    the band "none", never a red 0%. Scoring silence as failure is how a
    dashboard teaches you to ignore it.
  * **Every score says how it was calculated.** `basis` is returned with each
    one, because a number you can't interrogate is a number you stop trusting.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter

from db import run_read

router = APIRouter(prefix="/api/pulse", tags=["pulse-scores"])

WINDOW = 14          # days — long enough to smooth a bad week, short enough to react

# What "doing enough" looks like per fortnight. Round numbers on purpose: these
# are reference points for a personal dashboard, not clinical targets.
TARGETS = {
    "recovery_mins": 150,
    "workouts": 8,
}


def _days() -> list[str]:
    today = datetime.now().date()
    return [(today - timedelta(days=i)).isoformat() for i in range(WINDOW - 1, -1, -1)]


def _band(pct: float | None) -> str:
    if pct is None:
        return "none"
    if pct >= 75:
        return "good"
    if pct >= 45:
        return "ok"
    return "attention"


def _score(key: str, label: str, pct: float | None, basis: str,
           says: dict[str, str], series: list[float]) -> dict:
    band = _band(pct)
    return {
        "key": key,
        "label": label,
        "value": None if pct is None else round(pct),
        "band": band,
        "basis": basis,
        # The sentence is the point. A number without an interpretation just
        # moves the thinking onto you every time you look at it.
        "says": says.get(band, ""),
        "series": series,
    }


@router.get("/scores")
async def scores() -> dict:
    days = _days()
    first = days[0]

    # --- consistency: did the habits you set actually happen? ---
    habit_rows = await run_read(
        "MATCH (l:HabitLog) WHERE l.date >= $first RETURN l.date AS d, count(*) AS n",
        first=first)
    by_day = {r["d"]: r["n"] for r in habit_rows}
    tracked = await run_read(
        "MATCH (h:Habit) WHERE coalesce(h.active, true) RETURN count(h) AS n")
    habit_count = tracked[0]["n"] if tracked else 0
    logged_days = len([d for d in days if by_day.get(d)])
    consistency = (logged_days / WINDOW * 100) if habit_count else None

    # --- recovery: minutes of deliberate rest ---
    rec_rows = await run_read(
        "MATCH (s:RecoverySession) WHERE s.date >= $first "
        "RETURN s.date AS d, sum(coalesce(s.duration, 0)) AS mins", first=first)
    rec_by_day = {r["d"]: (r["mins"] or 0) for r in rec_rows}
    rec_total = sum(rec_by_day.values())
    recovery = min(100.0, rec_total / TARGETS["recovery_mins"] * 100) if rec_rows else None

    # --- movement: did you train ---
    w_rows = await run_read(
        "MATCH (w:Workout) WHERE w.date >= $first RETURN w.date AS d, count(*) AS n",
        first=first)
    w_by_day = {r["d"]: r["n"] for r in w_rows}
    w_total = sum(w_by_day.values())
    movement = min(100.0, w_total / TARGETS["workouts"] * 100) if w_rows else None

    # --- fuel: days you actually logged what you ate ---
    f_rows = await run_read(
        "MATCH (f:FoodLog) WHERE f.date >= $first RETURN f.date AS d, count(*) AS n",
        first=first)
    f_by_day = {r["d"]: r["n"] for r in f_rows}
    f_days = len([d for d in days if f_by_day.get(d)])
    fuel = (f_days / WINDOW * 100) if f_rows else None

    out = [
        _score("consistency", "Consistency", consistency,
               f"{logged_days} of the last {WINDOW} days had a habit logged"
               f" · {habit_count} habit(s) tracked",
               {"good": "You're showing up. Most days are getting logged.",
                "ok": "Patchy — about half the days are landing.",
                "attention": "Habits have mostly stopped. Worth cutting the list down.",
                "none": "No habits tracked yet."},
               [float(by_day.get(d, 0)) for d in days]),
        _score("recovery", "Recovery", recovery,
               f"{int(rec_total)} min of recovery in {WINDOW} days"
               f" (target {TARGETS['recovery_mins']})",
               {"good": "Well rested — you're taking recovery as seriously as the work.",
                "ok": "Some rest, but under what you set as the mark.",
                "attention": "Very little deliberate recovery lately.",
                "none": "No recovery sessions logged."},
               [float(rec_by_day.get(d, 0)) for d in days]),
        _score("movement", "Movement", movement,
               f"{w_total} workout(s) in {WINDOW} days (target {TARGETS['workouts']})",
               {"good": "Training is consistent.",
                "ok": "Moving, but less often than you intended.",
                "attention": "Training has dropped off.",
                "none": "No workouts logged."},
               [float(w_by_day.get(d, 0)) for d in days]),
        _score("fuel", "Fuel", fuel,
               f"{f_days} of {WINDOW} days had food logged",
               {"good": "You know what you've been eating.",
                "ok": "Logging some days, missing others.",
                "attention": "Barely logging food — the nutrition data can't say much.",
                "none": "No food logged yet."},
               [float(f_by_day.get(d, 0)) for d in days]),
    ]

    live = [s for s in out if s["value"] is not None]
    return {
        "window_days": WINDOW,
        "from": first,
        "scores": out,
        # An overall number only when there's something real behind it.
        "overall": round(sum(s["value"] for s in live) / len(live)) if live else None,
        "tracked": len(live),
    }
