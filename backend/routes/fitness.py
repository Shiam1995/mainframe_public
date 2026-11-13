"""/api/pulse/fitness — the Fitness sub-module of Pulse.

Workouts, training cycles, goals, body map, daily activity metrics, stretching.
All nodes are owned by (:Module {name:"pulse"}) and every mutation writes to the
shared Mainframe activity log. Config-driven activity metrics; body map is a set
of clickable regions. (Video form-checker is future — schema leaves room.)
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (
    FitnessBaselineSet,
    CardioUpdate,
    CardioCreate,
    ActivityConfigUpdate, ActivityLogCreate, BodyDayNoteUpdate, BodyDayUpdate,
    BodyDayAllClear, BodyDayCarry, BodyDayEntrySet, BodyIssueCreate, BodyIssuePatch, BodyIssueUpdateCreate, BodyIssuesToDay,
    BodyNoteCreate, BodyStateUpdate, CycleCreate, CycleUpdate, GoalCreate, GoalUpdate,
    MaxIn, ProgramDaySet, StretchCreate, WorkoutCreate, WorkoutUpdate,
)

router = APIRouter(prefix="/api/pulse/fitness", tags=["fitness"])

METRIC_KEYS = ["steps", "walking", "running", "cycling", "swimming", "standing", "sedentary", "exercise", "intensity", "calories"]
DEFAULT_TRACKED = ["steps", "walking", "running", "exercise", "calories"]

# Workout type → muscle groups worked (for the Day Review).
MUSCLE_MAP = {
    "Push": ["Chest", "Shoulders", "Triceps"],
    "Pull": ["Back", "Biceps", "Rear Delts"],
    "Legs": ["Quads", "Hamstrings", "Glutes", "Calves"],
    "Upper": ["Chest", "Back", "Shoulders", "Arms"],
    "Lower": ["Quads", "Hamstrings", "Glutes", "Calves"],
    "Full Body": ["Chest", "Back", "Legs", "Shoulders", "Arms", "Core"],
    "Cardio": ["Cardio", "Legs"],
    "HIIT": ["Full Body", "Cardio"],
    "Sport": ["Full Body"],
    "Other": [],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(var: str) -> str:
    return f"MERGE (mod:Module {{name: 'pulse'}}) MERGE ({var})-[:OWNED_BY]->(mod)"


def _end_date(start_date: str, weeks: int) -> str:
    """Last day of a cycle: start + weeks*7 - 1. Derived on every read, never
    stored, so changing weeks or start can't leave a stale end behind."""
    try:
        return (date.fromisoformat(start_date[:10]) + timedelta(days=int(weeks) * 7 - 1)).isoformat()
    except Exception:  # noqa: BLE001
        return ""


def _current_week(start_date: str, weeks: int) -> int:
    try:
        start = date.fromisoformat(start_date[:10])
        diff = (date.today() - start).days
        if diff < 0:
            return 0
        return min(weeks, diff // 7 + 1)
    except Exception:  # noqa: BLE001
        return 0


def _week_of(start_date: str, weeks: int, on: str) -> int:
    """Which week of a cycle a date falls in, 1-based; 0 outside the cycle."""
    try:
        diff = (date.fromisoformat(on[:10]) - date.fromisoformat(start_date[:10])).days
    except Exception:  # noqa: BLE001
        return 0
    if diff < 0 or (weeks and diff >= int(weeks) * 7):
        return 0
    return diff // 7 + 1


def _mins(a: str, b: str) -> int:
    """Minutes from HH:MM to HH:MM, across midnight; 0 when either is unset."""
    def m(t: str):
        try:
            h, mi = (t or "").split(":")
            return int(h) * 60 + int(mi)
        except ValueError:
            return None
    x, y = m(a), m(b)
    if x is None or y is None:
        return 0
    return y - x if y >= x else y + 1440 - x


def ex_key(name: str) -> str:
    """One exercise however it was typed: "Squats", "squat", "Back squat."
    Same rule as exKey in fitness-logworkout.js — keep the two in step."""
    words = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words)


# =========================================================================== #
# WORKOUTS
# =========================================================================== #
# One projection for every workout read: the cycle, the program day, and the
# timed blocks ride along (subqueries, so blocks and exercises don't multiply).
_WORKOUT_RETURN = """
        OPTIONAL MATCH (w)-[:IN_CYCLE]->(c:Cycle)
        OPTIONAL MATCH (w)-[:ON_DAY]->(d:ProgramDay)
        OPTIONAL MATCH (w)-[:HAS_EXERCISE]->(e:Exercise)
        WITH w, c, d, collect(e{.*}) AS exercises
        RETURN w{.*, cycle_id: c.id, cycle_name: c.name, program_day_id: d.id,
                 program_day: d.day, program_day_label: d.label,
                 blocks: COLLECT { MATCH (w)-[:HAS_BLOCK]->(b:WorkoutBlock) RETURN b{.*} ORDER BY b.idx },
                 maxes_set: COLLECT { MATCH (w)-[:SET_MAX]->(m:LiftMax) RETURN m{.*} },
                 cardio: COLLECT { MATCH (w)-[:HAS_CARDIO]->(k:CardioSession) RETURN k{.*} ORDER BY k.from, k.created_at }} AS w,
               exercises
"""


async def _workout(wid: str) -> dict:
    rows = await run_read("MATCH (w:Workout {id: $id})" + _WORKOUT_RETURN, id=wid)
    if not rows:
        raise HTTPException(404, "workout not found")
    w = rows[0]["w"]
    w["exercises"] = [e for e in rows[0]["exercises"] if e.get("id")]
    w["cardio"] = [_shape_cardio(k) for k in w.get("cardio") or []]
    return w


def _pack_workouts(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        w = r["w"]; w["exercises"] = [e for e in r["exercises"] if e.get("id")]
        w["cardio"] = [_shape_cardio(k) for k in w.get("cardio") or []]
        out.append(w)
    return out


@router.get("/workouts")
async def list_workouts(q: str | None = None, type: str | None = None) -> list[dict]:
    rows = await run_read(
        "MATCH (w:Workout)" + _WORKOUT_RETURN + "ORDER BY w.date DESC"
    )
    items = _pack_workouts(rows)
    if type:
        items = [w for w in items if w.get("type") == type]
    if q:
        ql = q.lower()
        # Notes are + rows on the workout now; search them alongside the old text.
        row_txt = {r["id"]: r["t"] for r in await run_read(
            "MATCH (r:Row)-[:ON]->(w:Workout) RETURN w.id AS id, reduce(s = '', x IN collect(r.text) | s + ' ' + x) AS t")}
        items = [w for w in items if ql in (w.get("type", "").lower() + " " + (w.get("notes") or "").lower() + " " + row_txt.get(w["id"], "").lower()
                                            + " " + " ".join(e.get("name", "") for e in w["exercises"]).lower())]
    return items


async def _fill_workout(wid: str, body: WorkoutCreate) -> None:
    """Everything hanging off a workout: exercises, timed blocks, cardio, the
    program links, new maxes. Create writes it once; replace clears it first."""
    for ex in body.exercises:
        await run_write(
            "MATCH (w:Workout {id: $wid}) CREATE (w)-[:HAS_EXERCISE]->(:Exercise {id: $eid, name: $name, detail: $detail})",
            wid=wid, eid=str(uuid.uuid4()), name=ex.name, detail=ex.detail,
        )
    # The program day names its cycle; an explicit cycle_id only matters
    # without a day. The week is where the workout's date falls in the cycle.
    cycle_id = body.cycle_id
    if body.program_day_id:
        rows = await run_write(
            """
            MATCH (w:Workout {id: $wid}), (d:ProgramDay {id: $did})-[:DAY_OF]->(c:Cycle)
            MERGE (w)-[:ON_DAY]->(d)
            RETURN c.id AS cid, c.start_date AS start
            """, wid=wid, did=body.program_day_id)
        if rows:
            cycle_id = rows[0]["cid"]
    if cycle_id:
        rows = await run_write(
            "MATCH (w:Workout {id: $wid}),(c:Cycle {id: $cid}) MERGE (w)-[:IN_CYCLE]->(c) RETURN c.start_date AS start, c.weeks AS weeks",
            wid=wid, cid=cycle_id)
        if rows:
            week = _week_of(rows[0]["start"] or "", rows[0]["weeks"] or 0, body.date)
            if week:
                await run_write("MATCH (w:Workout {id: $wid}) SET w.program_week = $week", wid=wid, week=week)
    extra = {k: v for k, v in (("fatigue_before", body.fatigue_before), ("warmup_min", body.warmup_min)) if v is not None}
    if extra:
        sets = ", ".join(f"w.{k} = ${k}" for k in extra)
        await run_write(f"MATCH (w:Workout {{id: $wid}}) SET {sets}", wid=wid, **extra)
    if body.blocks:
        await run_write(
            """
            MATCH (w:Workout {id: $wid})
            UNWIND $blocks AS b
            CREATE (w)-[:HAS_BLOCK]->(:WorkoutBlock {
                id: b.id, idx: b.idx, kind: b.kind, from: b.from, to: b.to, minutes: b.minutes,
                exercise: b.exercise, key: b.key, reps: b.reps, kg: b.kg, rpe: b.rpe, raw: b.raw, group: b.group
            })
            """,
            wid=wid,
            blocks=[{"id": str(uuid.uuid4()), "idx": i, "kind": b.kind, "from": b.from_, "to": b.to,
                     "minutes": _mins(b.from_, b.to), "exercise": b.exercise.strip(), "key": ex_key(b.exercise),
                     "reps": b.reps, "kg": b.kg, "rpe": b.rpe, "raw": b.raw, "group": b.group}
                    for i, b in enumerate(body.blocks)],
        )
    for m in body.confirmed_maxes:
        await _add_max(m, date_=body.date, source="workout", wid=wid)
    for k in body.cardio:
        await _insert_cardio(CardioCreate(date=body.date, type=k.type, distance_km=k.distance_km,
                                          duration_mins=_mins(k.from_, k.to), avg_hr=k.avg_hr,
                                          perceived_effort=k.perceived_effort, notes=k.notes,
                                          style=k.style, sets=k.sets),
                             workout_id=wid, from_=k.from_, to=k.to)


@router.post("/workouts", status_code=201)
async def create_workout(body: WorkoutCreate) -> dict:
    wid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (w:Workout {{
            id: $id, date: $date, type: $type, duration: $duration, intensity: $intensity,
            interrupted: $interrupted, notes: $notes, created_at: $now
        }})
        WITH w {_own('w')}
        """,
        id=wid, date=body.date, type=body.type, duration=body.duration, intensity=body.intensity,
        interrupted=body.interrupted, notes=body.notes, now=_now(),
    )
    await _fill_workout(wid, body)
    await record("fitness", "workout logged", detail=_workout_detail(body), module="pulse")
    return await _workout(wid)


@router.put("/workouts/{wid}/replace")
async def replace_workout(wid: str, body: WorkoutCreate) -> dict:
    """Save an edited workout from the Log form: same id (so its images stay),
    fields overwritten, rows and cardio rewritten, program links redrawn.
    Maxes it set before are kept; newly ticked ones are added."""
    rows = await run_write(
        """
        MATCH (w:Workout {id: $id})
        SET w.date = $date, w.type = $type, w.duration = $duration, w.intensity = $intensity,
            w.interrupted = $interrupted, w.notes = coalesce($notes, w.notes), w.fatigue_before = $fatigue,
            w.warmup_min = $warmup, w.updated_at = $now
        REMOVE w.program_week
        WITH w
        OPTIONAL MATCH (w)-[r:IN_CYCLE|ON_DAY]->() DELETE r
        WITH DISTINCT w
        OPTIONAL MATCH (w)-[:HAS_EXERCISE|HAS_BLOCK|HAS_CARDIO]->(x) DETACH DELETE x
        RETURN count(DISTINCT w) AS n
        """,
        id=wid, date=body.date, type=body.type, duration=body.duration, intensity=body.intensity,
        # Notes are + rows now (routes/rows.py); the Log form sends none, and an
        # empty one must not wipe the old text the row migration left in place.
        interrupted=body.interrupted, notes=body.notes or None, fatigue=body.fatigue_before,
        warmup=body.warmup_min, now=_now(),
    )
    if not rows or not rows[0]["n"]:
        raise HTTPException(404, "workout not found")
    await _fill_workout(wid, body)
    await record("fitness", "workout edited", detail=_workout_detail(body), module="pulse")
    return await _workout(wid)


def _workout_detail(body: WorkoutCreate) -> str:
    n_ex = len([b for b in body.blocks if b.kind == "exercise"]) or len(body.exercises)
    unit = ("set" if n_ex == 1 else "sets") if body.blocks else "ex"
    detail = " · ".join([body.type] + ([f"{n_ex} {unit}"] if n_ex or not body.cardio else []) + [f"{body.duration}min"])
    if body.cardio:
        def one(k):
            bits = [k.type, (k.style or "").upper(), f"{k.sets} sets" if k.style == "hiit" and k.sets else "",
                    f"{k.distance_km:g}km" if k.distance_km else ""]
            return " ".join(b for b in bits if b)
        detail += " · cardio: " + ", ".join(one(k) for k in body.cardio)
    if body.confirmed_maxes:
        detail += " · new max: " + ", ".join(f"{m.exercise} {m.kg:g}kg" for m in body.confirmed_maxes)
    return detail


@router.put("/workouts/{wid}")
async def update_workout(wid: str, patch: WorkoutUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if fields:
        sets = ", ".join(f"w.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (w:Workout {{id: $id}}) SET {sets} RETURN w", id=wid, **fields)
        if not rows:
            raise HTTPException(404, "workout not found")
        await record("fitness", "workout updated", detail=", ".join(fields), module="pulse")
    return await _workout(wid)


@router.delete("/workouts/{wid}", status_code=204, response_class=Response)
async def delete_workout(wid: str) -> Response:
    # A max recorded from this workout goes with it: its evidence is gone. So
    # does its cardio, which was logged as part of it.
    await run_write(
        """
        MATCH (w:Workout {id: $id})
        OPTIONAL MATCH (w)-[:HAS_EXERCISE]->(e:Exercise)
        OPTIONAL MATCH (w)-[:HAS_BLOCK]->(b:WorkoutBlock)
        OPTIONAL MATCH (w)-[:SET_MAX]->(m:LiftMax)
        OPTIONAL MATCH (w)-[:HAS_CARDIO]->(k:CardioSession)
        DETACH DELETE e, b, m, k, w
        """, id=wid)
    await record("fitness", "workout deleted", detail=wid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# CYCLES
# =========================================================================== #
async def _cycle(cid: str) -> dict:
    rows = await run_read("MATCH (c:Cycle {id: $id}) RETURN c{.*} AS c", id=cid)
    if not rows:
        raise HTTPException(404, "cycle not found")
    c = rows[0]["c"]; c.setdefault("weeks_done", []); c["current_week"] = _current_week(c.get("start_date", ""), c.get("weeks", 0)); c["end_date"] = _end_date(c.get("start_date", ""), c.get("weeks", 0))
    await _with_week_log([c])
    return c


async def _with_week_log(cycles: list[dict]) -> None:
    """Attach each cycle's logged workouts by week, and the weeks they finish.

    Derived on every read, never stored: `week_workouts` groups the cycle's
    workouts by program week, and `weeks_auto` lists the weeks whose workouts
    cover every training day of the cycle. A cycle with no days can't finish
    a week this way, so ticking it by hand (`weeks_done`) stays the fallback.
    """
    if not cycles:
        return
    rows = await run_read(
        """
        MATCH (w:Workout)-[:IN_CYCLE]->(c:Cycle) WHERE c.id IN $ids AND w.program_week IS NOT NULL
        OPTIONAL MATCH (w)-[:ON_DAY]->(d:ProgramDay)
        RETURN c.id AS cid, w.program_week AS week, w.id AS id, w.date AS date, w.type AS type,
               d.id AS day_id, d.day AS day, d.label AS label
        ORDER BY w.date, w.created_at
        """, ids=[c["id"] for c in cycles])
    days = await run_read(
        """
        MATCH (d:ProgramDay)-[:DAY_OF]->(c:Cycle) WHERE c.id IN $ids
        RETURN c.id AS cid, collect(d.id) AS days
        """, ids=[c["id"] for c in cycles])
    need = {r["cid"]: set(r["days"]) for r in days}
    for c in cycles:
        by_week: dict[int, list[dict]] = {}
        for r in rows:
            if r["cid"] == c["id"]:
                by_week.setdefault(int(r["week"]), []).append(
                    {k: r[k] for k in ("id", "date", "type", "day_id", "day", "label")})
        want = need.get(c["id"]) or set()
        c["week_workouts"] = {str(w): ws for w, ws in sorted(by_week.items())}
        c["weeks_auto"] = sorted(
            w for w, ws in by_week.items()
            if want and want <= {x["day_id"] for x in ws if x["day_id"]})


@router.get("/cycles")
async def list_cycles() -> list[dict]:
    rows = await run_read("MATCH (c:Cycle) RETURN c{.*} AS c ORDER BY c.created_at DESC")
    out = []
    for r in rows:
        c = r["c"]; c.setdefault("weeks_done", []); c["current_week"] = _current_week(c.get("start_date", ""), c.get("weeks", 0)); c["end_date"] = _end_date(c.get("start_date", ""), c.get("weeks", 0)); out.append(c)
    await _with_week_log(out)
    return out


@router.post("/cycles", status_code=201)
async def create_cycle(body: CycleCreate) -> dict:
    cid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (c:Cycle {{
            id: $id, name: $name, weeks: $weeks, start_date: $start, phase: $phase,
            goals: $goals, notes: $notes, status: 'active', weeks_done: [], created_at: $now
        }})
        WITH c {_own('c')}
        """,
        id=cid, name=body.name.strip(), weeks=body.weeks, start=body.start_date,
        phase=body.phase, goals=body.goals, notes=body.notes, now=_now(),
    )
    await record("fitness", "cycle created", detail=f"{body.name[:50]} ({body.weeks}w)", module="pulse")
    return await _cycle(cid)


@router.put("/cycles/{cid}")
async def update_cycle(cid: str, patch: CycleUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if fields:
        sets = ", ".join(f"c.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (c:Cycle {{id: $id}}) SET {sets} RETURN c", id=cid, **fields)
        if not rows:
            raise HTTPException(404, "cycle not found")
        verb = "completed" if fields.get("status") == "completed" else "week toggled" if "weeks_done" in fields else "updated"
        await record("fitness", "cycle " + verb, detail=", ".join(fields), module="pulse")
    return await _cycle(cid)


@router.delete("/cycles/{cid}", status_code=204, response_class=Response)
async def delete_cycle(cid: str) -> Response:
    # Its days and their prescriptions go too; workouts stay, unlinked.
    await run_write(
        """
        MATCH (c:Cycle {id: $id})
        OPTIONAL MATCH (d:ProgramDay)-[:DAY_OF]->(c)
        OPTIONAL MATCH (p:Prescription)-[:PRESCRIBED_ON]->(d)
        DETACH DELETE p, d, c
        """, id=cid)
    await record("fitness", "cycle deleted", detail=cid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# PROGRAM DAYS — a cycle's training days, repeated every week of it
# =========================================================================== #
# (:ProgramDay {day, label})-[:DAY_OF]->(:Cycle)
# (:Prescription {idx, exercise, key, sets, reps, pct_max, notes})-[:PRESCRIBED_ON]->(:ProgramDay)
async def _days(cid: str) -> list[dict]:
    rows = await run_read(
        """
        MATCH (d:ProgramDay)-[:DAY_OF]->(:Cycle {id: $cid})
        RETURN d{.*, prescriptions: COLLECT {
            MATCH (p:Prescription)-[:PRESCRIBED_ON]->(d) RETURN p{.*} ORDER BY p.idx }} AS d
        ORDER BY d.day, d.created_at
        """, cid=cid)
    return [r["d"] for r in rows]


async def _write_prescriptions(did: str, body: ProgramDaySet) -> None:
    await run_write("MATCH (p:Prescription)-[:PRESCRIBED_ON]->(:ProgramDay {id: $did}) DETACH DELETE p", did=did)
    rows = [{"id": str(uuid.uuid4()), "idx": i, "exercise": p.exercise.strip(), "key": ex_key(p.exercise),
             "sets": p.sets, "reps": p.reps, "pct_max": p.pct_max, "notes": p.notes}
            for i, p in enumerate(body.prescriptions) if p.exercise.strip()]
    if rows:
        await run_write(
            """
            MATCH (d:ProgramDay {id: $did})
            UNWIND $rows AS r
            CREATE (:Prescription {id: r.id, idx: r.idx, exercise: r.exercise, key: r.key,
                                   sets: r.sets, reps: r.reps, pct_max: r.pct_max, notes: r.notes})-[:PRESCRIBED_ON]->(d)
            """, did=did, rows=rows)


@router.get("/cycles/{cid}/days")
async def list_days(cid: str) -> list[dict]:
    return await _days(cid)


@router.post("/cycles/{cid}/days", status_code=201)
async def create_day(cid: str, body: ProgramDaySet) -> dict:
    did = str(uuid.uuid4())
    rows = await run_write(
        f"""
        MATCH (c:Cycle {{id: $cid}})
        CREATE (d:ProgramDay {{id: $id, day: $day, label: $label, created_at: $now}})-[:DAY_OF]->(c)
        WITH d {_own('d')}
        RETURN d.id AS id
        """, cid=cid, id=did, day=body.day, label=body.label.strip(), now=_now())
    if not rows:
        raise HTTPException(404, "cycle not found")
    await _write_prescriptions(did, body)
    await record("fitness", "program day added", detail=f"day {body.day} {body.label}".strip(), module="pulse")
    return next(d for d in await _days(cid) if d["id"] == did)


@router.put("/days/{did}")
async def update_day(did: str, body: ProgramDaySet) -> dict:
    rows = await run_write(
        "MATCH (d:ProgramDay {id: $id})-[:DAY_OF]->(c:Cycle) SET d.day = $day, d.label = $label RETURN c.id AS cid",
        id=did, day=body.day, label=body.label.strip())
    if not rows:
        raise HTTPException(404, "program day not found")
    await _write_prescriptions(did, body)
    await record("fitness", "program day updated", detail=f"day {body.day} {body.label}".strip(), module="pulse")
    return next(d for d in await _days(rows[0]["cid"]) if d["id"] == did)


@router.delete("/days/{did}", status_code=204, response_class=Response)
async def delete_day(did: str) -> Response:
    # Workouts logged against it keep their cycle and week, lose the day link.
    await run_write(
        """
        MATCH (d:ProgramDay {id: $id})
        OPTIONAL MATCH (p:Prescription)-[:PRESCRIBED_ON]->(d)
        DETACH DELETE p, d
        """, id=did)
    await record("fitness", "program day deleted", detail=did, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# MAXES — one (:LiftMax) per record; the current max is the latest per exercise
# =========================================================================== #
async def _add_max(m: MaxIn, date_: str | None, source: str, wid: str | None = None) -> dict:
    mid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (m:LiftMax {{id: $id, exercise: $exercise, key: $key, kg: $kg, reps: $reps,
                            from_kg: $from_kg, from_reps: $from_reps, date: $date,
                            source: $source, created_at: $now}})
        WITH m {_own('m')}
        WITH m OPTIONAL MATCH (w:Workout {{id: $wid}})
        FOREACH (_ IN CASE WHEN w IS NULL THEN [] ELSE [1] END | MERGE (w)-[:SET_MAX]->(m))
        RETURN m{{.*}} AS m
        """,
        id=mid, exercise=m.exercise.strip(), key=ex_key(m.exercise), kg=m.kg, reps=m.reps,
        from_kg=m.from_kg, from_reps=m.from_reps, date=(date_ or m.date or date.today().isoformat())[:10],
        source=source, now=_now(), wid=wid or "")
    return rows[0]["m"]


async def _current_maxes() -> list[dict]:
    rows = await run_read(
        """
        MATCH (m:LiftMax)
        WITH m ORDER BY m.date DESC, m.created_at DESC
        WITH m.key AS key, collect(m{.*}) AS history
        RETURN history[0] AS m, history[1..] AS previous
        ORDER BY m.exercise
        """)
    return [{**r["m"], "previous": r["previous"]} for r in rows]


@router.get("/maxes")
async def list_maxes() -> list[dict]:
    return await _current_maxes()


@router.post("/maxes", status_code=201)
async def add_max(body: MaxIn) -> dict:
    m = await _add_max(body, date_=body.date, source="manual")
    await record("fitness", "max set", detail=f"{m['exercise']} {m['kg']:g}kg", module="pulse")
    return m


@router.delete("/maxes/{mid}", status_code=204, response_class=Response)
async def delete_max(mid: str) -> Response:
    # The record before it, if any, becomes current again.
    await run_write("MATCH (m:LiftMax {id: $id}) DETACH DELETE m", id=mid)
    await record("fitness", "max deleted", detail=mid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# TODAY — the Log workout form's context: program, today's day, maxes
# =========================================================================== #
@router.get("/today")
async def today(cycle_id: str | None = None) -> dict:
    """Which program and day the next workout is.

    Program: the cycle asked for, else the active cycle whose span holds
    today (newest first), else the newest active one. Day: the one after the
    last day logged this week, wrapping; day 1 when nothing's logged this week.
    """
    cycles = await list_cycles()
    maxes = {m["exercise"]: {"kg": m["kg"], "reps": m.get("reps"), "date": m.get("date")} for m in await _current_maxes()}
    picker = [{"id": c["id"], "name": c["name"], "status": c.get("status"), "weeks": c.get("weeks"),
               "current_week": c.get("current_week")} for c in cycles]
    none = {"program": None, "day": None, "prescriptions": [], "maxes": maxes, "days": [], "cycles": picker}

    if cycle_id:
        prog = next((c for c in cycles if c["id"] == cycle_id), None)
    else:
        active = [c for c in cycles if c.get("status") == "active"]
        prog = next((c for c in active if c.get("current_week")), None) or (active[0] if active else None)
    if not prog:
        return none

    week = prog.get("current_week") or 1
    days = await _days(prog["id"])
    for d in days:
        d["week"] = week
    day = None
    if days:
        last = await run_read(
            """
            MATCH (w:Workout)-[:ON_DAY]->(d:ProgramDay)-[:DAY_OF]->(:Cycle {id: $cid})
            WHERE w.program_week = $week
            RETURN d.id AS did ORDER BY w.date DESC, w.created_at DESC LIMIT 1
            """, cid=prog["id"], week=week)
        idx = next((i for i, d in enumerate(days) if last and d["id"] == last[0]["did"]), None)
        day = days[(idx + 1) % len(days)] if idx is not None else days[0]
    return {
        "program": {"id": prog["id"], "name": prog["name"], "phase": prog.get("phase"),
                    "weeks": prog.get("weeks"), "current_week": prog.get("current_week")},
        "week": week,
        "day": day,
        "prescriptions": day["prescriptions"] if day else [],
        "maxes": maxes,
        "days": days,
        "cycles": picker,
    }


# =========================================================================== #
# GOALS
# =========================================================================== #
@router.get("/goals")
async def list_goals() -> list[dict]:
    rows = await run_read("MATCH (g:Goal) WHERE NOT g:PoolGoal "
                          "RETURN g{.*} AS g ORDER BY g.created_at DESC")
    return [r["g"] for r in rows]


@router.post("/goals", status_code=201)
async def create_goal(body: GoalCreate) -> dict:
    gid = str(uuid.uuid4())
    rows = await run_write(
        f"CREATE (g:Goal {{id: $id, text: $text, current: $current, target: $target, created_at: $now}}) WITH g {_own('g')} RETURN g{{.*}} AS g",
        id=gid, text=body.text.strip(), current=body.current, target=body.target, now=_now(),
    )
    await record("fitness", "goal added", detail=body.text[:60], module="pulse")
    return rows[0]["g"]


@router.put("/goals/{gid}")
async def update_goal(gid: str, patch: GoalUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields")
    sets = ", ".join(f"g.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (g:Goal {{id: $id}}) SET {sets} RETURN g{{.*}} AS g", id=gid, **fields)
    if not rows:
        raise HTTPException(404, "goal not found")
    await record("fitness", "goal updated", detail=", ".join(fields), module="pulse")
    return rows[0]["g"]


@router.delete("/goals/{gid}", status_code=204, response_class=Response)
async def delete_goal(gid: str) -> Response:
    await run_write("MATCH (g:Goal {id: $id}) DETACH DELETE g", id=gid)
    await record("fitness", "goal deleted", detail=gid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# BODY MAP
# =========================================================================== #
@router.get("/body")
async def get_body() -> dict:
    states = await run_read("MATCH (b:BodyState) WHERE coalesce(b.state,'') <> '' RETURN b.region AS region, b.state AS state")
    notes = await run_read("MATCH (n:BodyNote) RETURN n{.*} AS n ORDER BY n.date DESC")
    return {"points": {s["region"]: s["state"] for s in states}, "notes": [n["n"] for n in notes]}


@router.put("/body/{region}")
async def set_body(region: str, patch: BodyStateUpdate) -> dict:
    await run_write(
        f"""
        MERGE (b:BodyState {{region: $region}})
          ON CREATE SET b.id = $id
        SET b.state = $state, b.date = $now
        WITH b {_own('b')}
        """,
        region=region, id=str(uuid.uuid4()), state=patch.state, now=_now(),
    )
    # history
    await run_write(
        "CREATE (:BodyStateLog {id: $id, region: $region, state: $state, date: $now})",
        id=str(uuid.uuid4()), region=region, state=patch.state, now=_now(),
    )
    await record("fitness", "body region changed", detail=f"{region} → {patch.state or 'clear'}", module="pulse")
    return {"region": region, "state": patch.state}


@router.post("/body/notes", status_code=201)
async def add_body_note(body: BodyNoteCreate) -> dict:
    rows = await run_write(
        f"CREATE (n:BodyNote {{id: $id, text: $text, date: $now}}) WITH n {_own('n')} RETURN n{{.*}} AS n",
        id=str(uuid.uuid4()), text=body.text, now=_now(),
    )
    await record("fitness", "body note added", detail=body.text[:60], module="pulse")
    return rows[0]["n"]


@router.get("/body/history")
async def body_history() -> list[dict]:
    rows = await run_read("MATCH (l:BodyStateLog) RETURN l{.*} AS l ORDER BY l.date DESC LIMIT 200")
    return [r["l"] for r in rows]


# =========================================================================== #
# BODY ISSUES — a flagged problem that lives across days until closed
# =========================================================================== #
# Flag soreness/pain on a region and it becomes an issue: it keeps colouring
# the body map (by severity, 1–5) until closed, and carries its own timeline
# of updates — re-score the severity or add a note as the thing evolves.
#
# The legacy :BodyState stays in sync with the OPEN issues (kind of the most
# recent one, '' when none), because the day review and the pulse scores read
# it; "soreness" maps to the old "pain" bucket there.

_LEGACY_KIND = {"soreness": "pain", "pain": "pain",
                "tight": "tight", "imbalance": "imbalance"}


async def _sync_body_state(region: str) -> None:
    rows = await run_read(
        "MATCH (i:BodyIssue {region: $r, status: 'open'}) "
        "RETURN i.kind AS kind ORDER BY i.opened_at DESC LIMIT 1", r=region)
    state = _LEGACY_KIND.get(rows[0]["kind"], "pain") if rows else ""
    await run_write(
        f"""
        MERGE (b:BodyState {{region: $region}})
          ON CREATE SET b.id = $id
        SET b.state = $state, b.date = $now
        WITH b {_own('b')}
        """,
        region=region, id=str(uuid.uuid4()), state=state, now=_now())


async def _issue(iid: str) -> dict:
    rows = await run_read(
        """
        MATCH (i:BodyIssue {id: $id})
        OPTIONAL MATCH (i)-[:HAS_UPDATE]->(u:BodyIssueUpdate)
        WITH i, u ORDER BY u.ts
        WITH i, collect(u{.*}) AS updates
        RETURN i{.*, updates: updates} AS i
        """, id=iid)
    if not rows:
        raise HTTPException(404, "issue not found")
    return rows[0]["i"]


@router.get("/body/issues")
async def body_issues(status: str = "all") -> list[dict]:
    where = "" if status == "all" else "WHERE i.status = $status"
    rows = await run_read(
        f"""
        MATCH (i:BodyIssue) {where}
        OPTIONAL MATCH (i)-[:HAS_UPDATE]->(u:BodyIssueUpdate)
        WITH i, u ORDER BY u.ts
        WITH i, collect(u{{.*}}) AS updates
        RETURN i{{.*, updates: updates}} AS i
        ORDER BY i.status DESC, i.opened_at DESC
        """, status=status)
    return [r["i"] for r in rows]


@router.post("/body/issues", status_code=201)
async def create_body_issue(body: BodyIssueCreate) -> dict:
    iid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (i:BodyIssue {{id: $id, region: $region, kind: $kind,
                              severity: $sev, status: 'open',
                              opened_at: $now, closed_at: ''}})
        WITH i {_own('i')}
        CREATE (i)-[:HAS_UPDATE]->(:BodyIssueUpdate
            {{id: $uid, ts: $now, severity: $sev, note: $note}})
        """,
        id=iid, uid=str(uuid.uuid4()), region=body.region, kind=body.kind,
        sev=body.severity, note=body.note, now=_now())
    await _sync_body_state(body.region)
    await record("fitness", "issue flagged",
                 detail=f"{body.region} · {body.kind} · severity {body.severity}",
                 module="pulse", entity_id=iid)
    return await _issue(iid)


@router.post("/body/issues/{iid}/updates", status_code=201)
async def add_issue_update(iid: str, body: BodyIssueUpdateCreate) -> dict:
    if body.severity is None and not body.note.strip():
        raise HTTPException(400, "an update needs a severity or a note")
    rows = await run_write(
        """
        MATCH (i:BodyIssue {id: $iid})
        CREATE (i)-[:HAS_UPDATE]->(:BodyIssueUpdate
            {id: $uid, ts: $now, severity: $sev, note: $note})
        SET i.severity = coalesce($sev, i.severity)
        RETURN i.region AS region
        """,
        iid=iid, uid=str(uuid.uuid4()), now=_now(),
        sev=body.severity, note=body.note.strip())
    if not rows:
        raise HTTPException(404, "issue not found")
    await record("fitness", "issue update",
                 detail=f"{rows[0]['region']}"
                        + (f" · severity {body.severity}" if body.severity else "")
                        + (f" · {body.note.strip()[:50]}" if body.note.strip() else ""),
                 module="pulse", entity_id=iid)
    return await _issue(iid)


@router.patch("/body/issues/{iid}")
async def patch_body_issue(iid: str, patch: BodyIssuePatch) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if fields.get("status") == "closed":
        fields["closed_at"] = _now()
    elif fields.get("status") == "open":
        fields["closed_at"] = ""
    sets = ", ".join(f"i.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (i:BodyIssue {{id: $id}}) SET {sets} RETURN i.region AS region",
        id=iid, **fields)
    if not rows:
        raise HTTPException(404, "issue not found")
    await _sync_body_state(rows[0]["region"])
    if "status" in fields:
        await record("fitness",
                     "issue closed" if fields["status"] == "closed" else "issue reopened",
                     detail=rows[0]["region"], module="pulse", entity_id=iid)
    return await _issue(iid)


@router.delete("/body/issues/{iid}", status_code=204, response_class=Response)
async def delete_body_issue(iid: str) -> Response:
    rows = await run_read("MATCH (i:BodyIssue {id: $id}) RETURN i.region AS region", id=iid)
    await run_write(
        """
        MATCH (i:BodyIssue {id: $id})
        OPTIONAL MATCH (i)-[:HAS_UPDATE]->(u:BodyIssueUpdate)
        DETACH DELETE i, u
        """, id=iid)
    if rows:
        await _sync_body_state(rows[0]["region"])
    await record("fitness", "issue deleted", detail=iid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# DAY REVIEW — muscle-group focus for a day + a per-day body map
# =========================================================================== #
@router.get("/day-review")
async def day_review(date: str) -> dict:
    """Aggregate one day: its workouts, the muscle groups worked, the per-day
    body-map key points, and a day note."""
    wrows = await run_read(
        """
        MATCH (w:Workout) WHERE w.date STARTS WITH $date
        OPTIONAL MATCH (w)-[:HAS_EXERCISE]->(e:Exercise)
        RETURN w{.*} AS w, collect(e{.*}) AS exercises
        ORDER BY w.created_at
        """,
        date=date,
    )
    workouts = _pack_workouts(wrows)
    muscles: list[str] = []
    for w in workouts:
        for m in MUSCLE_MAP.get(w.get("type", ""), []):
            if m not in muscles:
                muscles.append(m)
    entries = await _day_entries(date)
    note = await run_read("MATCH (n:BodyDayNote {date: $date}) RETURN n.text AS text", date=date)
    return {
        "date": date, "workouts": workouts, "muscle_groups": muscles,
        # Same snapshot as the Body Map, coloured the same way (sev1…sev5).
        "body_points": {e["region"]: "sev" + str(e["severity"]) for e in entries},
        "body_entries": entries,
        "note": note[0]["text"] if note else "",
    }


@router.put("/day-body/{region}")
async def set_day_body(region: str, body: BodyDayUpdate) -> dict:
    # Old one-click cycle (pain → imbalance → tight → clear). Kept so it still
    # writes a proper day entry: kind from the state, severity kept or 3.
    await run_write(
        f"""
        MERGE (b:BodyDayState {{region: $region, date: $date}})
          ON CREATE SET b.id = $id
        SET b.state = $state, b.kind = CASE WHEN $state = '' THEN null ELSE $state END,
            b.severity = CASE WHEN $state = '' THEN null ELSE coalesce(b.severity, 3) END,
            b.updated_at = $now
        WITH b {_own('b')}
        """,
        region=region, date=body.date, id=str(uuid.uuid4()), state=body.state, now=_now(),
    )
    await record("fitness", "day body logged", detail=f"{body.date} · {region} → {body.state or 'clear'}", module="pulse")
    return {"region": region, "date": body.date, "state": body.state}


@router.put("/day-note")
async def set_day_note(body: BodyDayNoteUpdate) -> dict:
    await run_write(
        f"MERGE (n:BodyDayNote {{date: $date}}) ON CREATE SET n.id = $id SET n.text = $text WITH n {_own('n')}",
        date=body.date, id=str(uuid.uuid4()), text=body.text,
    )
    return {"date": body.date, "text": body.text}


# =========================================================================== #
# BODY DAYS — a snapshot a day: what hurts today, how bad, a note
# =========================================================================== #
# One (:BodyDayState {date, region}) per region per day, with kind, severity
# 1–5 and a note. Nothing carries forward by itself: a new day starts empty
# and "carry over" copies the last logged day so you only edit what changed.
# The Body Map, the Day Review and the dashboard's pain count all read these.
# "All clear" (checked, nothing wrong) is `all_clear` on the day's
# (:BodyDayNote {date}); logging any region that day unsets it.
# `state` is the old three-way bucket, kept filled for anything still on it.
_ENTRY = """coalesce(b.kind, b.state, '') <> ''"""


def _entry(b: dict) -> dict:
    kind = b.get("kind") or b.get("state") or "soreness"
    return {"region": b["region"], "kind": kind, "severity": b.get("severity") or 3,
            "note": b.get("note") or "", "updated_at": b.get("updated_at") or ""}


async def _day_entries(d: str) -> list[dict]:
    rows = await run_read(
        f"MATCH (b:BodyDayState {{date: $d}}) WHERE {_ENTRY} RETURN b{{.*}} AS b ORDER BY b.severity DESC, b.region",
        d=d)
    return [_entry(r["b"]) for r in rows]


async def _body_day(d: str) -> dict:
    note = await run_read("MATCH (n:BodyDayNote {date: $d}) RETURN n.text AS text, n.all_clear AS all_clear", d=d)
    prev = await run_read(
        f"MATCH (b:BodyDayState) WHERE b.date < $d AND {_ENTRY} "
        "RETURN b.date AS date, count(b) AS n ORDER BY date DESC LIMIT 1", d=d)
    return {"date": d, "entries": await _day_entries(d), "note": (note[0]["text"] or "") if note else "",
            "all_clear": bool(note and note[0]["all_clear"]),
            "prev": {"date": prev[0]["date"], "count": prev[0]["n"]} if prev else None}


async def _unset_all_clear(d: str) -> None:
    await run_write("MATCH (n:BodyDayNote {date: $d}) SET n.all_clear = false", d=d)


def _check_date(d: str) -> str:
    try:
        return date.fromisoformat(d[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")


@router.get("/body/days")
async def body_days(limit: int = 120) -> list[dict]:
    """Every day with a snapshot or a day note, newest first."""
    rows = await run_read(
        f"""
        MATCH (b:BodyDayState) WHERE {_ENTRY}
        WITH b.date AS date, collect(b{{.*}}) AS entries
        RETURN date, entries ORDER BY date DESC LIMIT $limit
        """, limit=limit)
    note_rows = await run_read(
        "MATCH (n:BodyDayNote) WHERE coalesce(n.text,'') <> '' OR n.all_clear "
        "RETURN n.date AS date, coalesce(n.text,'') AS text, coalesce(n.all_clear,false) AS all_clear")
    notes = {r["date"]: r for r in note_rows}
    days = {r["date"]: sorted((_entry(b) for b in r["entries"]), key=lambda e: (-e["severity"], e["region"]))
            for r in rows}
    out = [{"date": d, "entries": days.get(d, []), "note": notes[d]["text"] if d in notes else "",
            "all_clear": bool(d in notes and notes[d]["all_clear"] and not days.get(d))}
           for d in sorted(set(days) | set(notes), reverse=True)]
    return out[:limit]


@router.get("/body/days/{d}")
async def body_day(d: str) -> dict:
    return await _body_day(_check_date(d))


@router.put("/body/days/{d}/all-clear")
async def set_body_all_clear(d: str, body: BodyDayAllClear) -> dict:
    """Checked and fine: marks the day and removes anything logged on it."""
    d = _check_date(d)
    if body.all_clear:
        await run_write(f"MATCH (b:BodyDayState {{date: $d}}) DETACH DELETE b", d=d)
    await run_write(
        f"MERGE (n:BodyDayNote {{date: $d}}) ON CREATE SET n.id = $id, n.text = '' "
        f"SET n.all_clear = $v WITH n {_own('n')}",
        d=d, id=str(uuid.uuid4()), v=body.all_clear)
    await record("fitness", "body all clear" if body.all_clear else "body all clear undone", detail=d, module="pulse")
    return await _body_day(d)


@router.put("/body/days/{d}/{region}")
async def set_body_day_entry(d: str, region: str, body: BodyDayEntrySet) -> dict:
    d = _check_date(d)
    await run_write(
        f"""
        MERGE (b:BodyDayState {{region: $region, date: $d}})
          ON CREATE SET b.id = $id
        SET b.kind = $kind, b.severity = $sev, b.note = $note, b.state = $state, b.updated_at = $now
        WITH b {_own('b')}
        """,
        region=region, d=d, id=str(uuid.uuid4()), kind=body.kind, sev=body.severity,
        note=body.note.strip(), state=_LEGACY_KIND.get(body.kind, "pain"), now=_now())
    await _unset_all_clear(d)
    await record("fitness", "body day logged",
                 detail=f"{d} · {region} · {body.kind} {body.severity}", module="pulse")
    return await _body_day(d)


@router.delete("/body/days/{d}/{region}")
async def clear_body_day_entry(d: str, region: str) -> dict:
    d = _check_date(d)
    await run_write("MATCH (b:BodyDayState {region: $region, date: $d}) DETACH DELETE b", region=region, d=d)
    await record("fitness", "body day cleared", detail=f"{d} · {region}", module="pulse")
    return await _body_day(d)


@router.post("/body/days/{d}/carry")
async def carry_body_day(d: str, body: BodyDayCarry) -> dict:
    """Start a day from another: copy its entries, leave regions already set."""
    d, src = _check_date(d), _check_date(body.from_date)
    rows = await run_write(
        f"""
        MATCH (s:BodyDayState {{date: $src}}) WHERE {_ENTRY.replace('b.', 's.')}
          AND NOT EXISTS {{ MATCH (t:BodyDayState {{date: $d, region: s.region}}) WHERE {_ENTRY.replace('b.', 't.')} }}
        OPTIONAL MATCH (old:BodyDayState {{date: $d, region: s.region}})
        DETACH DELETE old
        WITH DISTINCT s
        CREATE (b:BodyDayState {{id: randomUUID(), date: $d, region: s.region,
                                 kind: coalesce(s.kind, s.state), severity: coalesce(s.severity, 3),
                                 note: coalesce(s.note, ''), state: coalesce(s.state, 'pain'),
                                 carried_from: $src, updated_at: $now}})
        WITH b {_own('b')}
        RETURN count(b) AS n
        """, d=d, src=src, now=_now())
    n = rows[0]["n"] if rows else 0
    if n:
        await _unset_all_clear(d)
    await record("fitness", "body day carried", detail=f"{src} → {d} · {n}", module="pulse")
    return await _body_day(d)


@router.post("/body/issues/to-day")
async def issues_to_day(body: BodyIssuesToDay) -> dict:
    """The old always-on map's open issues become entries on one day (their
    latest severity and note), and are closed unless asked not to."""
    d = _check_date(body.date)
    issues = await body_issues("open")
    for i in issues:
        last_note = next((u.get("note") for u in reversed(i.get("updates") or []) if u.get("note")), "")
        await run_write(
            f"""
            MERGE (b:BodyDayState {{region: $region, date: $d}})
              ON CREATE SET b.id = $id, b.kind = $kind, b.severity = $sev, b.note = $note,
                            b.state = $state, b.updated_at = $now
            WITH b {_own('b')}
            """,
            region=i["region"], d=d, id=str(uuid.uuid4()), kind=i["kind"], sev=i.get("severity") or 3,
            note=last_note, state=_LEGACY_KIND.get(i["kind"], "pain"), now=_now())
        if body.close:
            await patch_body_issue(i["id"], BodyIssuePatch(status="closed"))
    if issues:
        await _unset_all_clear(d)
    await record("fitness", "issues moved to day", detail=f"{len(issues)} → {d}", module="pulse")
    return await _body_day(d)


# =========================================================================== #
# ACTIVITY (daily movement metrics)
# =========================================================================== #
async def _tracked() -> list[str]:
    rows = await run_read("MATCH (c:FitnessConfig {id: 'activity'}) RETURN c.tracked AS tracked")
    if rows and rows[0]["tracked"]:
        return rows[0]["tracked"]
    return DEFAULT_TRACKED


@router.get("/activity/config")
async def get_activity_config() -> dict:
    return {"metrics": METRIC_KEYS, "tracked": await _tracked()}


@router.put("/activity/config")
async def set_activity_config(body: ActivityConfigUpdate) -> dict:
    tracked = [m for m in body.tracked if m in METRIC_KEYS]
    await run_write(
        f"MERGE (c:FitnessConfig {{id: 'activity'}}) SET c.tracked = $tracked WITH c {_own('c')}",
        tracked=tracked,
    )
    return {"tracked": tracked}


@router.get("/activity")
async def list_activity() -> list[dict]:
    rows = await run_read("MATCH (a:ActivityLog) RETURN a{.*} AS a ORDER BY a.date DESC")
    return [r["a"] for r in rows]


@router.post("/activity", status_code=201)
async def log_activity(body: ActivityLogCreate) -> dict:
    data = body.model_dump()
    aid = str(uuid.uuid4())
    props = {"id": aid, "date": data.get("date"), "notes": data.get("notes", ""), "created_at": _now()}
    for k in METRIC_KEYS:
        if k in data and data[k] is not None:
            try:
                props[k] = int(data[k])
            except (TypeError, ValueError):
                pass
    sets = ", ".join(f"{k}: ${k}" for k in props)
    rows = await run_write(f"CREATE (a:ActivityLog {{{sets}}}) WITH a {_own('a')} RETURN a{{.*}} AS a", **props)
    await record("fitness", "activity logged", detail=data.get("date", ""), module="pulse")
    return rows[0]["a"]


@router.delete("/activity/{aid}", status_code=204, response_class=Response)
async def delete_activity(aid: str) -> Response:
    await run_write("MATCH (a:ActivityLog {id: $id}) DETACH DELETE a", id=aid)
    await record("fitness", "activity deleted", detail=aid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# STRETCHING
# =========================================================================== #
@router.get("/stretching")
async def list_stretch() -> list[dict]:
    rows = await run_read("MATCH (s:StretchSession) RETURN s{.*} AS s ORDER BY s.date DESC")
    return [r["s"] for r in rows]


@router.post("/stretching", status_code=201)
async def log_stretch(body: StretchCreate) -> dict:
    sid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (s:StretchSession {{id: $id, date: $date, duration: $duration, stretches: $stretches,
            focus: $focus, notes: $notes, created_at: $now}})
        WITH s {_own('s')} RETURN s{{.*}} AS s
        """,
        id=sid, date=body.date, duration=body.duration, stretches=body.stretches,
        focus=body.focus, notes=body.notes, now=_now(),
    )
    await record("fitness", "stretch session logged", detail=f"{body.date} · {len(body.stretches)} stretches", module="pulse")
    return rows[0]["s"]


@router.delete("/stretching/{sid}", status_code=204, response_class=Response)
async def delete_stretch(sid: str) -> Response:
    await run_write("MATCH (s:StretchSession {id: $id}) DETACH DELETE s", id=sid)
    await record("fitness", "stretch deleted", detail=sid, module="pulse")
    return Response(status_code=204)


# =========================================================================== #
# DASHBOARD (aggregate)
# =========================================================================== #
@router.get("/dashboard")
async def dashboard() -> dict:
    total_w = (await run_read("MATCH (w:Workout) RETURN count(w) AS n"))[0]["n"]
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    this_week = (await run_read("MATCH (w:Workout) WHERE w.date >= $d RETURN count(w) AS n", d=week_ago))[0]["n"]
    total_min = (await run_read("MATCH (w:Workout) RETURN sum(coalesce(w.duration,0)) AS m"))[0]["m"] or 0
    stretch_n = (await run_read("MATCH (s:StretchSession) RETURN count(s) AS n"))[0]["n"]
    # The latest body snapshot (today, or the last day you logged one).
    last = await run_read(f"MATCH (b:BodyDayState) WHERE b.date <= $t AND {_ENTRY} RETURN max(b.date) AS d",
                          t=date.today().isoformat())
    body = await _day_entries(last[0]["d"]) if last and last[0]["d"] else []
    pain = sum(1 for e in body if e["kind"] in ("pain", "soreness"))
    imbalance = sum(1 for e in body if e["kind"] == "imbalance")
    cycles = await list_cycles()
    active_cycle = next((c for c in cycles if c.get("status") == "active"), None)
    recent = _pack_workouts(await run_read(
        "MATCH (w:Workout) OPTIONAL MATCH (w)-[:HAS_EXERCISE]->(e:Exercise) RETURN w{.*} AS w, collect(e{.*}) AS exercises ORDER BY w.date DESC LIMIT 5"
    ))
    goals = await list_goals()
    return {
        "stats": {
            "total_workouts": total_w, "this_week": this_week,
            "total_hours": round(total_min / 60, 1), "stretch_sessions": stretch_n,
            "pain_points": pain, "imbalance": imbalance,
        },
        "active_cycle": active_cycle, "recent_workouts": recent, "goals": goals,
    }


# --------------------------------------------------------------------------- #
# Cardio — its own section, kept apart from strength workouts. Sets and reps
# say nothing useful about a run; distance, pace, heart rate and zones do.
# --------------------------------------------------------------------------- #
def _shape_cardio(c: dict) -> dict:
    """Pace is always derived, never stored — it can't drift out of step."""
    dist = c.get("distance_km") or 0
    mins = c.get("duration_mins") or 0
    c["pace_min_per_km"] = round(mins / dist, 2) if dist and mins else None
    c["speed_kmh"] = round(dist / (mins / 60), 2) if dist and mins else None
    z = c.get("zones") or [0, 0, 0, 0, 0]
    c["zones"] = list(z) + [0] * (5 - len(z))
    c["zone_total_mins"] = sum(c["zones"])
    return c


@router.get("/cardio")
async def list_cardio(start: str | None = None, end: str | None = None) -> list[dict]:
    where, params = [], {}
    if start:
        where.append("c.date >= $start"); params["start"] = start
    if end:
        where.append("c.date <= $end"); params["end"] = end
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await run_read(
        f"MATCH (c:CardioSession) {clause} RETURN c{{.*}} AS c ORDER BY c.date DESC, c.created_at DESC",
        **params,
    )
    return [_shape_cardio(r["c"]) for r in rows]


async def _insert_cardio(body: CardioCreate, workout_id: str | None = None,
                         from_: str = "", to: str = "") -> dict:
    """One (:CardioSession). From the Log workout form it also carries its
    from/to and hangs off the workout: (w)-[:HAS_CARDIO]->(c)."""
    d = body.model_dump()
    if d.get("style") != "hiit":
        d["sets"] = None          # sets only mean something for intervals
    d["id"] = str(uuid.uuid4())
    d["created_at"] = _now()
    d["zones"] = (list(d.get("zones") or []) + [0] * 5)[:5]
    rows = await run_write(
        """
        CREATE (c:CardioSession {
            id: $id, date: $date, type: $type, distance_km: $distance_km,
            duration_mins: $duration_mins, avg_hr: $avg_hr, max_hr: $max_hr,
            zones: $zones, perceived_effort: $perceived_effort, route: $route,
            notes: $notes, style: $style, sets: $sets, created_at: $created_at
        })
        WITH c OPTIONAL MATCH (w:Workout {id: $wid})
        FOREACH (_ IN CASE WHEN w IS NULL THEN [] ELSE [1] END |
            SET c.from = $t_from, c.to = $t_to, c.workout_id = w.id
            MERGE (w)-[:HAS_CARDIO]->(c))
        RETURN c{.*} AS c
        """,
        **d, wid=workout_id or "", t_from=from_, t_to=to,
    )
    return _shape_cardio(rows[0]["c"])


@router.post("/cardio", status_code=201)
async def create_cardio(body: CardioCreate) -> dict:
    c = await _insert_cardio(body)
    await record("fitness", "cardio logged",
                 detail=f"{body.type} · {body.distance_km}km · {body.duration_mins}m")
    return c


@router.put("/cardio/{cid}")
async def update_cardio(cid: str, patch: CardioUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "zones" in fields:
        fields["zones"] = (list(fields["zones"]) + [0] * 5)[:5]
    if fields.get("style") == "liss":
        fields["sets"] = None     # SET to null removes it: LISS has no sets
    sets = ", ".join(f"c.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (c:CardioSession {{id: $id}}) SET {sets} RETURN c{{.*}} AS c", id=cid, **fields)
    if not rows:
        raise HTTPException(404, "cardio session not found")
    await record("fitness", "cardio updated", detail=", ".join(fields))
    return _shape_cardio(rows[0]["c"])


@router.delete("/cardio/{cid}", status_code=204, response_class=Response)
async def delete_cardio(cid: str) -> Response:
    await run_write("MATCH (c:CardioSession {id: $id}) DETACH DELETE c", id=cid)
    await record("fitness", "cardio deleted", detail=cid)
    return Response(status_code=204)


@router.get("/cardio/summary")
async def cardio_summary() -> dict:
    rows = await run_read("MATCH (c:CardioSession) RETURN c{.*} AS c")
    sessions = [_shape_cardio(r["c"]) for r in rows]
    dist = sum(s.get("distance_km") or 0 for s in sessions)
    mins = sum(s.get("duration_mins") or 0 for s in sessions)
    zones = [0] * 5
    for s in sessions:
        for i, v in enumerate(s["zones"][:5]):
            zones[i] += v or 0
    by_type: dict[str, dict] = {}
    for s in sessions:
        t = by_type.setdefault(s.get("type") or "other", {"sessions": 0, "km": 0.0, "mins": 0})
        t["sessions"] += 1
        t["km"] += s.get("distance_km") or 0
        t["mins"] += s.get("duration_mins") or 0
    return {
        "sessions": len(sessions),
        "total_km": round(dist, 2),
        "total_mins": mins,
        "avg_pace": round(mins / dist, 2) if dist else None,
        "zones": zones,
        "by_type": by_type,
    }


# --------------------------------------------------------------------------- #
# Fitness baseline test — the fixed reference every Benchmark compares against
# --------------------------------------------------------------------------- #
@router.get("/baseline-test")
async def get_baseline_test() -> dict:
    rows = await run_read(
        "MATCH (b:FitnessBaseline) RETURN b{.*} AS b ORDER BY coalesce(b.is_reference, false) DESC, b.date DESC")
    tests = [r["b"] for r in rows]
    ref = next((t for t in tests if t.get("is_reference")), tests[0] if tests else None)
    return {"reference": ref, "all": tests}


@router.put("/baseline-test")
async def set_baseline_test(body: FitnessBaselineSet) -> dict:
    """Record the starting point. Marked as the reference by default — exactly
    one baseline holds that flag, so Benchmark always has a single origin."""
    d = {k: v for k, v in body.model_dump().items() if v is not None}
    d["date"] = d.get("date") or datetime.now(timezone.utc).date().isoformat()
    bid = "baseline:" + d["date"]
    d["id"] = bid
    sets = ", ".join(f"b.{k} = ${k}" for k in d if k != "id")
    await run_write("MATCH (b:FitnessBaseline) SET b.is_reference = false")
    rows = await run_write(
        f"MERGE (b:FitnessBaseline {{id: $id}}) SET {sets}, b.is_reference = true RETURN b{{.*}} AS b",
        **d,
    )
    await record("fitness", "baseline test recorded", detail=d["date"])
    return rows[0]["b"]


@router.get("/baseline-test/compare")
async def compare_to_baseline() -> dict:
    """Every later benchmark measured against the reference baseline.

    Delta is signed against the metric's direction — for `run_5k_mins` and
    `resting_hr` lower is better, so an improvement shows as a positive gain.
    """
    base = await get_baseline_test()
    ref = base["reference"]
    if not ref:
        return {"reference": None, "metrics": [], "note": "No baseline test recorded yet."}
    LOWER_IS_BETTER = {"run_5k_mins", "resting_hr", "body_fat_pct", "waist_cm"}
    # weight and body measurements have no universal "better" — cutting and
    # bulking pull opposite ways — so report the change without judging it
    NEUTRAL = {"weight_kg", "height_cm", "chest_cm", "arm_cm", "thigh_cm"}
    latest = await run_read(
        "MATCH (b:FitnessBaseline) WHERE coalesce(b.is_reference, false) = false "
        "RETURN b{.*} AS b ORDER BY b.date DESC LIMIT 1")
    now = latest[0]["b"] if latest else None
    metrics = []
    for k, v in ref.items():
        if k in {"id", "date", "is_reference", "notes"} or not isinstance(v, (int, float)):
            continue
        cur = (now or {}).get(k)
        delta = None if cur is None else round(cur - v, 2)
        gain = None if delta is None else (-delta if k in LOWER_IS_BETTER else delta)
        metrics.append({
            "metric": k, "baseline": v, "current": cur, "delta": delta,
            "improved": None if (gain is None or k in NEUTRAL) else gain > 0,
            "lower_is_better": k in LOWER_IS_BETTER,
            "neutral": k in NEUTRAL,
        })
    return {"reference": ref, "compared_to": now, "metrics": metrics}
