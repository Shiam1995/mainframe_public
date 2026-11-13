"""/api/pulse — the Pulse module: habits, experiments, routines, medical, meds.

Self-contained module of Mainframe. All nodes are owned by (:Module {name:"pulse"})
and every mutation writes to the shared activity log via activity.record(), so
Pulse events show up in the Mainframe activity/heatmap alongside every other module.
Medical + medication sections are config lists (below), not hardcoded per-section.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from activity import record
from config import settings
from db import run_read, run_write
from models import (
    ExperimentDayUpdate,
    ExperimentCreate, ExperimentUpdate, HabitAreaFields, HabitCreate, HabitLogCreate, HabitNoteCreate,
    HabitUpdate, MedEntryCreate, MedEntryUpdate, MedicalEntryCreate, MedicalEntryUpdate,
    RoutineCreate, RoutineNoteCreate, RoutineStepCreate, RoutineUpdate, StepLogCreate,
    SubHabitCreate,
)

router = APIRouter(prefix="/api/pulse", tags=["pulse"])

# Section keys — config-driven so new sections need no code changes.
MEDICAL_SECTIONS = [
    "history", "conditions", "symptoms", "pain", "allergies", "surgeries",
    "hospital", "vaccinations", "blood", "imaging", "family",
]
MED_SECTIONS = [
    "current", "dose", "schedule", "adherence", "side-effects", "prn",
    "supplements", "previous", "effectiveness",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(node_var: str) -> str:
    """Cypher snippet to attach a node to the Pulse module."""
    return f"MERGE (mod:Module {{name: 'pulse'}}) MERGE ({node_var})-[:OWNED_BY]->(mod)"


# =========================================================================== #
# HABITS
# =========================================================================== #
async def _habit(hid: str) -> dict:
    rows = await run_read(
        """
        MATCH (h:Habit {id: $id})
        OPTIONAL MATCH (h)-[:HAS_SUB]->(s:SubHabit)
        WITH h, s ORDER BY s.name
        WITH h, collect(s{.*}) AS subs
        OPTIONAL MATCH (h)-[:HAS_NOTE]->(n:HabitNote)
        WITH h, subs, n ORDER BY n.date DESC
        WITH h, subs, collect(n{.*}) AS notes
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog)
        RETURN h{.*} AS habit, subs, notes, collect(l{.*}) AS logs
        """,
        id=hid,
    )
    if not rows:
        raise HTTPException(404, "habit not found")
    h = rows[0]["habit"]
    h["subs"] = [s for s in rows[0]["subs"] if s.get("id")]
    h["notes"] = [n for n in rows[0]["notes"] if n.get("id")]
    h["logs"] = [l for l in rows[0]["logs"] if l.get("id")]
    return h


@router.get("/habits")
async def list_habits() -> list[dict]:
    rows = await run_read("MATCH (h:Habit) RETURN h.id AS id ORDER BY h.created_at DESC")
    return [await _habit(r["id"]) for r in rows]


@router.get("/habits/trends")
async def habit_trends(weeks: int = 12) -> dict:
    """Per-habit completion analytics for a 'Trends' view over ALL habits:
    a weekly done-count series, current + longest streak, and 30/90-day rates."""
    weeks = max(4, min(weeks, 52))
    today = date.today()
    week0 = today - timedelta(days=today.weekday())          # Monday of this week
    week_starts = [week0 - timedelta(weeks=(weeks - 1 - i)) for i in range(weeks)]

    rows = await run_read(
        """
        MATCH (h:Habit)
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog)
        WITH h, collect(l{.date, .level}) AS logs
        RETURN h{.*} AS habit, logs
        ORDER BY h.created_at DESC
        """
    )
    out = []
    for r in rows:
        h = r["habit"]
        done = set()
        for l in r["logs"]:
            d = (l.get("date") or "")[:10]
            if d and (l.get("level") or 0) > 0:
                done.add(d)
        # weekly done-counts
        weekly = []
        for ws in week_starts:
            c = sum(1 for n in range(7) if (ws + timedelta(days=n)).isoformat() in done)
            weekly.append({"week": ws.isoformat(), "count": c})
        # current streak (today or yesterday back)
        cur = today if today.isoformat() in done else today - timedelta(days=1)
        streak = 0
        while cur.isoformat() in done:
            streak += 1
            cur -= timedelta(days=1)
        # longest streak across all logged days
        longest, run, prev = 0, 0, None
        for d in sorted(done):
            dd = date.fromisoformat(d)
            run = run + 1 if prev and (dd - prev).days == 1 else 1
            longest = max(longest, run)
            prev = dd
        rate = lambda n: round(100 * sum(1 for k in range(n) if (today - timedelta(days=k)).isoformat() in done) / n)
        out.append({
            "id": h["id"], "name": h["name"], "category": h.get("category", ""),
            "frequency": h.get("frequency", ""), "active": h.get("active", True),
            "streak": streak, "longest": longest, "total": len(done),
            "rate30": rate(30), "rate90": rate(90), "weekly": weekly,
        })
    return {"weeks": [ws.isoformat() for ws in week_starts], "habits": out}


# --------------------------------------------------------------------------- #
# Active Tracking — labelled month/week buckets + reports
# --------------------------------------------------------------------------- #
_LEVEL_LABELS = {0: "none", 1: "Barely", 2: "Okay", 3: "Good", 4: "Crushed it"}
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _parse_minutes(text: str) -> int:
    """Best-effort minutes out of free-text time_spent ("45", "30 min", "1h 20m").

    Unparseable entries count as 0 and are tallied separately so a report can
    say how much of its time total is trustworthy.
    """
    import re

    s = (text or "").strip().lower()
    if not s:
        return 0
    total = 0
    hit = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h(?:rs?|ours?)?|m(?:ins?|inutes?)?)\b", s):
        total += float(num) * (60 if unit.startswith("h") else 1)
        hit = True
    if not hit:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*[:.]\s*(\d{1,2})$", s)   # 1:30
        if m:
            return int(float(m.group(1)) * 60 + int(m.group(2)))
        m = re.match(r"^(\d+(?:\.\d+)?)$", s)                       # bare number = minutes
        if m:
            return int(float(m.group(1)))
        return 0
    return int(total)


def _month_periods(end: date, n: int) -> list[dict]:
    """The n calendar months ending with end's month, oldest first."""
    out = []
    y, m = end.year, end.month
    for _ in range(n):
        first = date(y, m, 1)
        last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
        out.append({
            "id": f"{y:04d}-{m:02d}",
            "label": f"{_MONTHS[m - 1]} {y}",
            "short": f"{_MONTHS[m - 1][:3]} {y}",
            "start": first.isoformat(), "end": last.isoformat(),
        })
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _week_periods(end: date, n: int) -> list[dict]:
    """The n ISO weeks (Mon–Sun) ending with end's week, oldest first."""
    this_mon = end - timedelta(days=end.weekday())
    out = []
    for i in range(n):
        mon = this_mon - timedelta(weeks=(n - 1 - i))
        sun = mon + timedelta(days=6)
        iso_y, iso_w, _ = mon.isocalendar()
        same_month = mon.month == sun.month
        span = (f"{mon.day}–{sun.day} {_MONTHS[sun.month - 1][:3]}" if same_month
                else f"{mon.day} {_MONTHS[mon.month - 1][:3]} – {sun.day} {_MONTHS[sun.month - 1][:3]}")
        out.append({
            "id": f"{iso_y:04d}-W{iso_w:02d}",
            "label": f"Wk {iso_w} · {span}",
            "short": f"Wk {iso_w}",
            "start": mon.isoformat(), "end": sun.isoformat(),
        })
    return out


def _year_periods(end: date, n: int) -> list[dict]:
    """The n calendar years ending with end's year, oldest first."""
    return [{
        "id": str(y), "label": str(y), "short": str(y),
        "start": date(y, 1, 1).isoformat(), "end": date(y, 12, 31).isoformat(),
    } for y in range(end.year - n + 1, end.year + 1)]


def _bucket_stats(entries: list[dict], p: dict, today: date) -> dict:
    """Aggregate one habit's logs inside one labelled period."""
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    days = (end - start).days + 1
    elapsed = max(0, min(end, today).toordinal() - start.toordinal() + 1) if start <= today else 0
    done = sorted({e["date"] for e in entries if (e.get("level") or 0) > 0})
    levels = {str(k): 0 for k in range(1, 5)}
    for e in entries:
        lv = e.get("level") or 0
        if lv:
            levels[str(lv)] += 1
    minutes = sum(_parse_minutes(e.get("time_spent", "")) for e in entries)
    untimed = sum(1 for e in entries if (e.get("time_spent") or "").strip()
                  and not _parse_minutes(e.get("time_spent", "")))
    best, run, prev = 0, 0, None
    for d in done:
        dd = date.fromisoformat(d)
        run = run + 1 if prev and (dd - prev).days == 1 else 1
        best = max(best, run)
        prev = dd
    lv_sum = sum((e.get("level") or 0) for e in entries if (e.get("level") or 0) > 0)
    return {
        "period_id": p["id"], "period_label": p["label"],
        "period_start": p["start"], "period_end": p["end"],
        "days": days, "elapsed_days": elapsed,
        "logged_days": len(done),
        "rate": round(100 * len(done) / elapsed) if elapsed else 0,
        "avg_level": round(lv_sum / len(done), 2) if done else 0,
        "levels": levels, "minutes": minutes, "untimed_entries": untimed,
        "best_streak": best,
        "entries": sorted(entries, key=lambda e: e["date"]),
    }


async def _tracking_report(period: str, periods: int, end: str | None,
                           habit_id: str | None, active_only: bool) -> dict:
    if period not in ("month", "week", "year"):
        raise HTTPException(400, "period must be 'month', 'week' or 'year'")
    periods = max(1, min(periods, {"month": 24, "week": 53, "year": 10}[period]))
    today = date.today()
    anchor = date.fromisoformat(end) if end else today
    buckets = ({"month": _month_periods, "week": _week_periods, "year": _year_periods}
               [period](anchor, periods))
    lo, hi = buckets[0]["start"], buckets[-1]["end"]

    rows = await run_read(
        """
        MATCH (h:Habit)
        WHERE ($hid IS NULL OR h.id = $hid)
          AND ($active_only = false OR coalesce(h.active, true) = true)
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog)
        WHERE l.date >= $lo AND l.date <= $hi
        WITH h, collect(l{.date, .level, .time_spent, .notes, .feel, .connections}) AS logs
        RETURN h{.id, .name, .category, .frequency, .active} AS habit, logs
        ORDER BY h.created_at DESC
        """,
        hid=habit_id, active_only=active_only, lo=lo, hi=hi,
    )

    # Current streaks come from ALL logs, not just the window, so a streak that
    # started before the range isn't truncated by it.
    srows = await run_read(
        "MATCH (h:Habit)-[:HAS_LOG]->(l:HabitLog) WHERE coalesce(l.level, 0) > 0 "
        "RETURN h.id AS id, collect(l.date) AS dates"
    )
    streaks: dict[str, int] = {}
    for sr in srows:
        done = {(d or "")[:10] for d in sr["dates"]}
        cur = today if today.isoformat() in done else today - timedelta(days=1)
        n = 0
        while cur.isoformat() in done:
            n += 1
            cur -= timedelta(days=1)
        streaks[sr["id"]] = n

    habits, out_rows, summary = [], [], []
    for r in rows:
        h = r["habit"]
        habits.append(h)
        logs = [dict(l) for l in r["logs"] if l.get("date")]
        for l in logs:
            l["date"] = l["date"][:10]
            l["level_label"] = _LEVEL_LABELS.get(l.get("level") or 0, "")
        for p in buckets:
            inside = [l for l in logs if p["start"] <= l["date"] <= p["end"]]
            st = _bucket_stats(inside, p, today)
            st.update(habit_id=h["id"], habit_name=h["name"], category=h.get("category", ""))
            out_rows.append(st)
        whole = _bucket_stats(logs, {"id": "all", "label": "All", "start": lo, "end": hi}, today)
        whole.pop("entries")
        whole.update(habit_id=h["id"], habit_name=h["name"], category=h.get("category", ""),
                     current_streak=streaks.get(h["id"], 0))
        summary.append(whole)

    return {
        "period": period, "generated_at": _now(),
        "range": {"start": lo, "end": hi, "today": today.isoformat()},
        "periods": buckets, "habits": habits, "rows": out_rows, "summary": summary,
    }


@router.get("/tracking/report")
async def tracking_report(period: str = "month", periods: int = 6, end: str | None = None,
                          habit_id: str | None = None, active_only: bool = True) -> dict:
    """Habit logs bucketed into labelled months, ISO weeks or calendar years,
    with per-bucket stats — the data behind the Active Tracking grids and its
    reports."""
    return await _tracking_report(period, periods, end, habit_id, active_only)


def _fmt_mins(m: int) -> str:
    if not m:
        return "—"
    return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"


def _report_markdown(rep: dict) -> str:
    L: list[str] = []
    word = {"month": "Monthly", "week": "Weekly", "year": "Yearly"}[rep["period"]]
    L.append("# Pulse — Active Tracking Report")
    L.append("")
    L.append(f"_{word} · {rep['range']['start']} → {rep['range']['end']} · "
             f"generated {rep['generated_at'][:10]}_")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append("| Habit | Logged | Elapsed | Rate | Avg level | Time | Best streak |")
    L.append("|---|---|---|---|---|---|---|")
    for s in rep["summary"]:
        L.append(f"| {s['habit_name']} | {s['logged_days']} | {s['elapsed_days']} | "
                 f"{s['rate']}% | {s['avg_level'] or '—'} | {_fmt_mins(s['minutes'])} | "
                 f"{s['best_streak']} |")
    by_period: dict[str, list[dict]] = {}
    for r in rep["rows"]:
        by_period.setdefault(r["period_id"], []).append(r)
    for p in reversed(rep["periods"]):          # newest period first
        rws = by_period.get(p["id"], [])
        L += ["", f"## {p['label']}", "", f"_{p['start']} → {p['end']}_", ""]
        if not any(r["logged_days"] for r in rws):
            L.append("_No logs in this period._")
            continue
        for r in rws:
            if not r["logged_days"]:
                continue
            lv = r["levels"]
            L.append(f"### {r['habit_name']}")
            L.append("")
            L.append(f"- **{r['logged_days']}/{r['elapsed_days']} days logged ({r['rate']}%)** · "
                     f"avg level {r['avg_level']} · {_fmt_mins(r['minutes'])} · "
                     f"best streak {r['best_streak']}")
            L.append(f"- Levels — Barely {lv['1']} · Okay {lv['2']} · Good {lv['3']} · "
                     f"Crushed it {lv['4']}")
            if r["untimed_entries"]:
                L.append(f"- _{r['untimed_entries']} entr"
                         f"{'y' if r['untimed_entries'] == 1 else 'ies'} had unparseable time._")
            L.append("")
            L.append("| Date | Level | Time | What happened | Felt | Connections |")
            L.append("|---|---|---|---|---|---|")
            for e in r["entries"]:
                cells = [e["date"], e.get("level_label", ""), e.get("time_spent", "") or "—",
                         e.get("notes", "") or "", e.get("feel", "") or "",
                         e.get("connections", "") or ""]
                L.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
            L.append("")
    return "\n".join(L) + "\n"


_CSV_COLS = ["period_id", "period_label", "period_start", "period_end", "habit_id",
             "habit_name", "category", "date", "level", "level_label", "time_spent",
             "minutes", "notes", "feel", "connections"]


@router.get("/tracking/report/export")
async def export_tracking_report(format: str = "md", period: str = "month", periods: int = 6,
                                 end: str | None = None, habit_id: str | None = None,
                                 active_only: bool = True) -> Response:
    """Download the tracking report as Markdown, CSV (one row per log entry) or
    JSON. A copy is written to the exports dir, same as the other exporters."""
    import csv
    import io
    import json

    rep = await _tracking_report(period, periods, end, habit_id, active_only)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"pulse-tracking-{period}-{stamp}"

    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=_CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rep["rows"]:
            for e in r["entries"]:
                w.writerow({
                    **{k: r[k] for k in ("period_id", "period_label", "period_start", "period_end")},
                    "habit_id": r["habit_id"], "habit_name": r["habit_name"], "category": r["category"],
                    "date": e["date"], "level": e.get("level") or 0, "level_label": e.get("level_label", ""),
                    "time_spent": e.get("time_spent", ""), "minutes": _parse_minutes(e.get("time_spent", "")),
                    "notes": e.get("notes", ""), "feel": e.get("feel", ""), "connections": e.get("connections", ""),
                })
        data = buf.getvalue()
        (settings.exports_dir / f"{base}.csv").write_text(data)
        await record("tracking", "report exported", detail=f"csv · {period} × {periods}", module="pulse")
        return Response(data, media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={base}.csv"})

    if format == "json":
        data = json.dumps(rep, indent=2)
        (settings.exports_dir / f"{base}.json").write_text(data)
        await record("tracking", "report exported", detail=f"json · {period} × {periods}", module="pulse")
        return Response(data, media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename={base}.json"})

    data = _report_markdown(rep)
    (settings.exports_dir / f"{base}.md").write_text(data)
    await record("tracking", "report exported", detail=f"markdown · {period} × {periods}", module="pulse")
    return Response(data, media_type="text/markdown",
                    headers={"Content-Disposition": f"attachment; filename={base}.md"})


@router.post("/habits", status_code=201)
async def create_habit(body: HabitCreate) -> dict:
    hid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (h:Habit {{
            id: $id, name: $name, category: $category, frequency: $frequency,
            target: $target, tags: $tags, main_notes: $main_notes,
            days_of_week: $dow, time_of_day: $tod, duration_mins: $dmins,
            active: true, created_at: $now
        }})
        WITH h {_own('h')}
        """,
        id=hid, name=body.name.strip(), category=body.category, frequency=body.frequency,
        target=body.target, tags=body.tags, main_notes=body.main_notes, now=_now(),
        dow=body.days_of_week, tod=body.time_of_day, dmins=body.duration_mins,
    )
    # the areas-view fields (area, tier, source, …) only land when they're sent
    extra = HabitAreaFields(**body.model_dump(include=set(HabitAreaFields.model_fields))) \
        .model_dump(exclude_none=True)
    if extra.get("tier") == "experimental" and not extra.get("trial_start"):
        extra["trial_start"] = date.today().isoformat()
    if extra:
        sets = ", ".join(f"h.{k} = ${k}" for k in extra)
        await run_write(f"MATCH (h:Habit {{id: $id}}) SET {sets}", id=hid, **extra)
    await record("habit", "created", detail=body.name[:70])
    return await _habit(hid)


@router.put("/habits/{hid}")
async def update_habit(hid: str, patch: HabitUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if fields.get("tier") == "experimental" and "trial_start" not in fields:
        cur = await run_read("MATCH (h:Habit {id: $id}) RETURN h.tier AS t", id=hid)
        if cur and cur[0]["t"] != "experimental":
            fields["trial_start"] = date.today().isoformat()     # a new trial starts now
    if fields:
        sets = ", ".join(f"h.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (h:Habit {{id: $id}}) SET {sets} RETURN h", id=hid, **fields)
        if not rows:
            raise HTTPException(404, "habit not found")
        await record("habit", "updated", detail=", ".join(fields))
    return await _habit(hid)


@router.delete("/habits/{hid}", status_code=204, response_class=Response)
async def delete_habit(hid: str) -> Response:
    await run_write(
        """
        MATCH (h:Habit {id: $id})
        OPTIONAL MATCH (h)-[:HAS_SUB]->(s:SubHabit)
        OPTIONAL MATCH (h)-[:HAS_NOTE]->(n:HabitNote)
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog)
        DETACH DELETE s, n, l, h
        """,
        id=hid,
    )
    await record("habit", "deleted", detail=hid)
    return Response(status_code=204)


@router.post("/habits/{hid}/subs", status_code=201)
async def add_sub(hid: str, body: SubHabitCreate) -> dict:
    await run_write(
        "MATCH (h:Habit {id: $id}) CREATE (h)-[:HAS_SUB]->(:SubHabit {id: $sid, name: $name, done: false})",
        id=hid, sid=str(uuid.uuid4()), name=body.name.strip(),
    )
    await record("habit", "sub-habit added", detail=body.name[:60])
    return await _habit(hid)


@router.delete("/habits/{hid}/subs/{sid}", status_code=204, response_class=Response)
async def del_sub(hid: str, sid: str) -> Response:
    await run_write("MATCH (s:SubHabit {id: $sid}) DETACH DELETE s", sid=sid)
    await record("habit", "sub-habit removed", detail=sid)
    return Response(status_code=204)


@router.post("/habits/{hid}/notes", status_code=201)
async def add_habit_note(hid: str, body: HabitNoteCreate) -> dict:
    await run_write(
        "MATCH (h:Habit {id: $id}) CREATE (h)-[:HAS_NOTE]->(:HabitNote {id: $nid, text: $text, date: $date})",
        id=hid, nid=str(uuid.uuid4()), text=body.text, date=body.date or _now(),
    )
    await record("habit", "note added", detail=body.text[:60])
    return await _habit(hid)


@router.get("/habits/{hid}/logs")
async def get_logs(hid: str) -> list[dict]:
    rows = await run_read(
        "MATCH (:Habit {id: $id})-[:HAS_LOG]->(l:HabitLog) RETURN l{.*} AS l ORDER BY l.date", id=hid
    )
    return [r["l"] for r in rows]


@router.post("/habits/{hid}/logs", status_code=201)
async def log_day(hid: str, body: HabitLogCreate) -> dict:
    ctx = await run_read("MATCH (h:Habit {id: $id}) RETURN h.name AS name", id=hid)
    if not ctx:
        raise HTTPException(404, "habit not found")
    # one log per (habit, date) — upsert
    await run_write(
        """
        MATCH (h:Habit {id: $hid})
        MERGE (h)-[:HAS_LOG]->(l:HabitLog {habit_id: $hid, date: $date})
          ON CREATE SET l.id = $id
        SET l.level = $level, l.time_spent = $time, l.notes = $notes,
            l.feel = $feel, l.connections = $conn
        """,
        hid=hid, id=str(uuid.uuid4()), date=body.date, level=body.level,
        time=body.time_spent, notes=body.notes, feel=body.feel, conn=body.connections,
    )
    await record("habit", "day logged", detail=f"{ctx[0]['name'][:40]} · {body.date} · L{body.level}")
    return await _habit(hid)


# =========================================================================== #
# EXPERIMENTS
# =========================================================================== #
async def _experiment(eid: str) -> dict:
    rows = await run_read("MATCH (e:Experiment {id: $id}) RETURN e{.*} AS e", id=eid)
    if not rows:
        raise HTTPException(404, "experiment not found")
    e = rows[0]["e"]
    e.setdefault("days_done", [])
    return e


@router.get("/experiments")
async def list_experiments() -> list[dict]:
    rows = await run_read("MATCH (e:Experiment) RETURN e{.*} AS e ORDER BY e.created_at DESC")
    out = []
    for r in rows:
        e = r["e"]; e.setdefault("days_done", []); out.append(e)
    return out


@router.post("/experiments", status_code=201)
async def create_experiment(body: ExperimentCreate) -> dict:
    eid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (e:Experiment {{
            id: $id, name: $name, days: $days, unit: $unit, start_date: $start, hypothesis: $hyp,
            conclusion: '', status: 'active', days_done: [], created_at: $now
        }})
        WITH e {_own('e')}
        """,
        id=eid, unit=body.unit, name=body.name.strip(), days=body.days * (7 if body.unit == "weeks" else 1),
        start=body.start_date, hyp=body.hypothesis, now=_now(),
    )
    await record("experiment", "created",
                 detail=f"{body.name[:50]} ({body.days} {body.unit})")
    return await _experiment(eid)


@router.put("/experiments/{eid}")
async def update_experiment(eid: str, patch: ExperimentUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    # a duration typed in weeks is stored as its day count
    if fields.get("days") is not None and fields.get("unit") == "weeks":
        fields["days"] = fields["days"] * 7
    if fields:
        sets = ", ".join(f"e.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (e:Experiment {{id: $id}}) SET {sets} RETURN e", id=eid, **fields)
        if not rows:
            raise HTTPException(404, "experiment not found")
        verb = "completed" if fields.get("status") == "completed" else "updated"
        await record("experiment", verb, detail=", ".join(fields))
    return await _experiment(eid)


@router.get("/experiments/{eid}/days")
async def experiment_days(eid: str) -> list[dict]:
    """Every day of the run, each one a journal entry rather than a checkbox.

    Days that haven't been written yet come back as empty rows, so the UI
    always has the full span to render — day 1 to day N with real dates.
    """
    rows = await run_read(
        "MATCH (e:Experiment {id: $id}) RETURN e.days AS days, e.start_date AS start", id=eid)
    if not rows:
        raise HTTPException(404, "experiment not found")
    total = int(rows[0]["days"] or 0)
    try:
        start = datetime.fromisoformat((rows[0]["start"] or "")[:10]).date()
    except ValueError:
        start = datetime.now(timezone.utc).date()
    written = {
        r["day"]: r["d"]
        for r in await run_read(
            "MATCH (:Experiment {id: $id})-[:HAS_DAY]->(d:ExperimentDay) "
            "RETURN d.day AS day, d{.*} AS d", id=eid)
    }
    out = []
    for n in range(1, total + 1):
        d = written.get(n) or {}
        out.append({
            "day": n,
            "date": (start + timedelta(days=n - 1)).isoformat(),
            "notes": d.get("notes", ""),
            "what_happened": d.get("what_happened", ""),
            "adherence": d.get("adherence"),
            "feel": d.get("feel", ""),
            "done": bool(d.get("done", False)),
            "written": bool(d),
        })
    return out


@router.put("/experiments/{eid}/days/{day}")
async def set_experiment_day(eid: str, day: int, patch: ExperimentDayUpdate) -> dict:
    """Write (or rewrite) one day's journal entry."""
    ctx = await run_read("MATCH (e:Experiment {id: $id}) RETURN e.days AS days, e.name AS name", id=eid)
    if not ctx:
        raise HTTPException(404, "experiment not found")
    if day < 1 or day > int(ctx[0]["days"] or 0):
        raise HTTPException(400, f"day must be between 1 and {ctx[0]['days']}")
    data = patch.model_dump()
    # writing anything counts the day as done unless you say otherwise
    if data.get("done") is None:
        data["done"] = bool((data.get("what_happened") or "").strip()
                            or (data.get("notes") or "").strip())
    rows = await run_write(
        """
        MATCH (e:Experiment {id: $eid})
        MERGE (e)-[:HAS_DAY]->(d:ExperimentDay {experiment_id: $eid, day: $day})
          ON CREATE SET d.id = $did, d.created_at = $now
        SET d.notes = $notes, d.what_happened = $what, d.adherence = $adh,
            d.feel = $feel, d.done = $done, d.updated_at = $now
        RETURN d{.*} AS d
        """,
        eid=eid, day=day, did=str(uuid.uuid4()), now=_now(),
        notes=data["notes"], what=data["what_happened"], adh=data["adherence"],
        feel=data["feel"], done=data["done"],
    )
    await record("experiment", f"day {day} logged", detail=ctx[0]["name"][:50])
    return rows[0]["d"]


@router.get("/calendar")
async def calendar(start: str, end: str) -> list[dict]:
    """Habits and routines resolved into dated occurrences.

    This is the shape a calendar module needs: one entry per thing per day it
    should happen, already expanded from the schedule. Kept read-only and
    source-agnostic so the calendar never has to know how habits differ from
    routines.
    """
    try:
        d0 = datetime.fromisoformat(start[:10]).date()
        d1 = datetime.fromisoformat(end[:10]).date()
    except ValueError:
        raise HTTPException(400, "start and end must be YYYY-MM-DD")
    if d1 < d0:
        raise HTTPException(400, "end is before start")
    if (d1 - d0).days > 366:
        raise HTTPException(400, "range capped at one year")

    rows = await run_read(
        """
        MATCH (h:Habit) WHERE coalesce(h.active, true)
        RETURN 'habit' AS kind, h.id AS id, h.name AS name, h.category AS category,
               coalesce(h.days_of_week, []) AS dow, coalesce(h.time_of_day, '') AS time,
               coalesce(h.duration_mins, 0) AS mins, h.frequency AS frequency,
               null AS start_date, null AS end_date
        UNION ALL
        MATCH (r:Routine) WHERE coalesce(r.status, 'active') = 'active'
        RETURN 'routine' AS kind, r.id AS id, r.name AS name, r.category AS category,
               coalesce(r.days_of_week, []) AS dow, coalesce(r.time_of_day, '') AS time,
               coalesce(r.duration_mins, 0) AS mins, null AS frequency,
               r.start_date AS start_date, null AS end_date
        """
    )
    out = []
    span = (d1 - d0).days + 1
    for i in range(span):
        day = d0 + timedelta(days=i)
        for r in rows:
            dow = [int(x) for x in (r["dow"] or [])]
            # no explicit days set -> a daily habit lands every day; anything
            # else stays off the calendar until it's been scheduled
            if dow:
                if day.weekday() not in dow:
                    continue
            elif r["kind"] != "habit" or r["frequency"] != "daily":
                continue
            if r["start_date"] and day.isoformat() < r["start_date"][:10]:
                continue
            out.append({
                "date": day.isoformat(), "kind": r["kind"], "id": r["id"],
                "name": r["name"], "category": r["category"],
                "time_of_day": r["time"] or None, "duration_mins": r["mins"] or 0,
            })
    out.sort(key=lambda x: (x["date"], x["time_of_day"] or "99:99", x["name"]))
    return out


@router.delete("/experiments/{eid}", status_code=204, response_class=Response)
async def delete_experiment(eid: str) -> Response:
    await run_write("MATCH (e:Experiment {id: $id}) DETACH DELETE e", id=eid)
    await record("experiment", "deleted", detail=eid)
    return Response(status_code=204)


# =========================================================================== #
# ROUTINES
# =========================================================================== #
async def _routine(rid: str) -> dict:
    rows = await run_read(
        """
        MATCH (r:Routine {id: $id})
        OPTIONAL MATCH (r)-[:HAS_STEP]->(st:RoutineStep)
        OPTIONAL MATCH (st)-[:HAS_LOG]->(sl:StepLog)
        WITH r, st, sl ORDER BY sl.date DESC
        WITH r, st, collect(sl{.*}) AS slogs
        WITH r, collect(CASE WHEN st IS NULL THEN null ELSE {id: st.id, name: st.name, logs: slogs} END) AS steps
        OPTIONAL MATCH (r)-[:HAS_NOTE]->(n:RoutineNote)
        WITH r, steps, n ORDER BY n.date DESC
        RETURN r{.*} AS routine, steps, collect(n{.*}) AS notes
        """,
        id=rid,
    )
    if not rows:
        raise HTTPException(404, "routine not found")
    r = rows[0]["routine"]
    r["steps"] = [s for s in rows[0]["steps"] if s]
    r["notes"] = [n for n in rows[0]["notes"] if n.get("id")]
    return r


@router.get("/routines")
async def list_routines() -> list[dict]:
    rows = await run_read("MATCH (r:Routine) RETURN r.id AS id ORDER BY r.created_at DESC")
    return [await _routine(row["id"]) for row in rows]


@router.post("/routines", status_code=201)
async def create_routine(body: RoutineCreate) -> dict:
    rid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (r:Routine {{
            id: $id, name: $name, duration: $duration, unit: $unit, category: $category,
            main_notes: $main_notes, status: 'active', created_at: $now,
            days_of_week: $dow, time_of_day: $tod, duration_mins: $dmins, start_date: $start
        }})
        WITH r {_own('r')}
        """,
        id=rid, name=body.name.strip(), duration=body.duration, unit=body.unit,
        dow=body.days_of_week, tod=body.time_of_day, dmins=body.duration_mins,
        start=body.start_date,
        category=body.category, main_notes=body.main_notes, now=_now(),
    )
    await record("routine", "created", detail=body.name[:70])
    return await _routine(rid)


@router.put("/routines/{rid}")
async def update_routine(rid: str, patch: RoutineUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if fields:
        sets = ", ".join(f"r.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (r:Routine {{id: $id}}) SET {sets} RETURN r", id=rid, **fields)
        if not rows:
            raise HTTPException(404, "routine not found")
        await record("routine", "updated", detail=", ".join(fields))
    return await _routine(rid)


@router.delete("/routines/{rid}", status_code=204, response_class=Response)
async def delete_routine(rid: str) -> Response:
    await run_write(
        """
        MATCH (r:Routine {id: $id})
        OPTIONAL MATCH (r)-[:HAS_STEP]->(st:RoutineStep)
        OPTIONAL MATCH (st)-[:HAS_LOG]->(sl:StepLog)
        OPTIONAL MATCH (r)-[:HAS_NOTE]->(n:RoutineNote)
        DETACH DELETE sl, st, n, r
        """,
        id=rid,
    )
    await record("routine", "deleted", detail=rid)
    return Response(status_code=204)


@router.post("/routines/{rid}/steps", status_code=201)
async def add_step(rid: str, body: RoutineStepCreate) -> dict:
    await run_write(
        "MATCH (r:Routine {id: $id}) CREATE (r)-[:HAS_STEP]->(:RoutineStep {id: $sid, name: $name})",
        id=rid, sid=str(uuid.uuid4()), name=body.name.strip(),
    )
    await record("routine", "step added", detail=body.name[:60])
    return await _routine(rid)


@router.delete("/routines/{rid}/steps/{sid}", status_code=204, response_class=Response)
async def del_step(rid: str, sid: str) -> Response:
    await run_write(
        "MATCH (st:RoutineStep {id: $sid}) OPTIONAL MATCH (st)-[:HAS_LOG]->(sl:StepLog) DETACH DELETE sl, st",
        sid=sid,
    )
    await record("routine", "step removed", detail=sid)
    return Response(status_code=204)


@router.post("/routines/{rid}/steps/{sid}/logs", status_code=201)
async def log_step(rid: str, sid: str, body: StepLogCreate) -> dict:
    rows = await run_write(
        "MATCH (st:RoutineStep {id: $sid}) CREATE (st)-[:HAS_LOG]->(:StepLog {id: $lid, date: $date, time: $time, note: $note}) RETURN st.name AS name",
        sid=sid, lid=str(uuid.uuid4()), date=body.date or _now(), time=body.time, note=body.note,
    )
    if not rows:
        raise HTTPException(404, "step not found")
    await record("routine", "step logged", detail=f"{rows[0]['name'][:40]} · {body.time}")
    return await _routine(rid)


@router.post("/routines/{rid}/notes", status_code=201)
async def add_routine_note(rid: str, body: RoutineNoteCreate) -> dict:
    await run_write(
        "MATCH (r:Routine {id: $id}) CREATE (r)-[:HAS_NOTE]->(:RoutineNote {id: $nid, text: $text, date: $date})",
        id=rid, nid=str(uuid.uuid4()), text=body.text, date=_now(),
    )
    await record("routine", "note added", detail=body.text[:60])
    return await _routine(rid)


# =========================================================================== #
# MEDICAL  (section-scoped, config-driven)
# =========================================================================== #
def _check_section(section: str, allowed: list[str]) -> None:
    if section not in allowed:
        raise HTTPException(404, f"unknown section '{section}'")


@router.get("/medical/{section}")
async def list_medical(section: str) -> list[dict]:
    _check_section(section, MEDICAL_SECTIONS)
    rows = await run_read(
        "MATCH (m:MedicalEntry {section: $s}) RETURN m{.*} AS m ORDER BY m.date DESC", s=section
    )
    return [r["m"] for r in rows]


@router.post("/medical/{section}", status_code=201)
async def add_medical(section: str, body: MedicalEntryCreate) -> dict:
    _check_section(section, MEDICAL_SECTIONS)
    mid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (m:MedicalEntry {{
            id: $id, section: $s, title: $title, date: $date, details: $details,
            severity: $severity, tags: $tags, notes: $notes, links: $links,
            file_path: '', created_at: $now
        }})
        WITH m {_own('m')}
        RETURN m{{.*}} AS m
        """,
        id=mid, s=section, title=body.title.strip(), date=body.date, details=body.details,
        severity=body.severity, tags=body.tags, notes=body.notes, links=body.links, now=_now(),
    )
    await record("medical", "entry added", detail=f"{section}: {body.title[:50]}")
    return rows[0]["m"]


@router.put("/medical/{section}/{mid}")
async def update_medical(section: str, mid: str, patch: MedicalEntryUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"m.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (m:MedicalEntry {{id: $id}}) SET {sets} RETURN m{{.*}} AS m", id=mid, **fields)
    if not rows:
        raise HTTPException(404, "entry not found")
    await record("medical", "entry updated", detail=", ".join(fields))
    return rows[0]["m"]


@router.delete("/medical/{section}/{mid}", status_code=204, response_class=Response)
async def delete_medical(section: str, mid: str) -> Response:
    rows = await run_read("MATCH (m:MedicalEntry {id: $id}) RETURN m.file_path AS fp", id=mid)
    if rows and rows[0]["fp"]:
        Path(rows[0]["fp"]).unlink(missing_ok=True)
    await run_write("MATCH (m:MedicalEntry {id: $id}) DETACH DELETE m", id=mid)
    await record("medical", "entry deleted", detail=mid)
    return Response(status_code=204)


@router.post("/medical/{section}/{mid}/upload", status_code=201)
async def upload_medical_file(section: str, mid: str, file: UploadFile = File(...)) -> dict:
    _check_section(section, MEDICAL_SECTIONS)
    name = os.path.basename(file.filename or "file")
    ext = Path(name).suffix.lower()
    if ext not in {".pdf", ".jpg", ".jpeg", ".png"}:
        raise HTTPException(400, "only PDF, JPG, PNG allowed")
    sec_dir = settings.pulse_medical_dir / section
    sec_dir.mkdir(parents=True, exist_ok=True)
    dest = sec_dir / f"{mid}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    rows = await run_write(
        "MATCH (m:MedicalEntry {id: $id}) SET m.file_path = $fp, m.file_name = $fn RETURN m{.*} AS m",
        id=mid, fp=str(dest), fn=name,
    )
    if not rows:
        raise HTTPException(404, "entry not found")
    await record("medical", "file uploaded", detail=name)
    return rows[0]["m"]


@router.get("/medical/{section}/{mid}/file")
async def get_medical_file(section: str, mid: str) -> FileResponse:
    rows = await run_read("MATCH (m:MedicalEntry {id: $id}) RETURN m.file_path AS fp, m.file_name AS fn", id=mid)
    if not rows or not rows[0]["fp"] or not Path(rows[0]["fp"]).exists():
        raise HTTPException(404, "no file")
    return FileResponse(rows[0]["fp"], filename=rows[0]["fn"] or "file")


# =========================================================================== #
# MEDICATIONS  (section-scoped, config-driven)
# =========================================================================== #
@router.get("/meds/{section}")
async def list_meds(section: str) -> list[dict]:
    _check_section(section, MED_SECTIONS)
    rows = await run_read(
        "MATCH (m:MedEntry {section: $s}) RETURN m{.*} AS m ORDER BY m.date DESC", s=section
    )
    return [r["m"] for r in rows]


@router.post("/meds/{section}", status_code=201)
async def add_med(section: str, body: MedEntryCreate) -> dict:
    _check_section(section, MED_SECTIONS)
    mid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (m:MedEntry {{
            id: $id, section: $s, name: $name, date: $date, details: $details,
            dose: $dose, frequency: $frequency, status: $status, notes: $notes,
            tags: $tags, created_at: $now
        }})
        WITH m {_own('m')}
        RETURN m{{.*}} AS m
        """,
        id=mid, s=section, name=body.name.strip(), date=body.date, details=body.details,
        dose=body.dose, frequency=body.frequency, status=body.status, notes=body.notes,
        tags=body.tags, now=_now(),
    )
    await record("medication", "entry added", detail=f"{section}: {body.name[:50]}")
    return rows[0]["m"]


@router.put("/meds/{section}/{mid}")
async def update_med(section: str, mid: str, patch: MedEntryUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"m.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (m:MedEntry {{id: $id}}) SET {sets} RETURN m{{.*}} AS m", id=mid, **fields)
    if not rows:
        raise HTTPException(404, "entry not found")
    await record("medication", "entry updated", detail=", ".join(fields))
    return rows[0]["m"]


@router.delete("/meds/{section}/{mid}", status_code=204, response_class=Response)
async def delete_med(section: str, mid: str) -> Response:
    await run_write("MATCH (m:MedEntry {id: $id}) DETACH DELETE m", id=mid)
    await record("medication", "entry deleted", detail=mid)
    return Response(status_code=204)


@router.get("/sections")
async def sections() -> dict:
    """Expose the config section lists (frontend maps keys → icon/label)."""
    return {"medical": MEDICAL_SECTIONS, "meds": MED_SECTIONS}
