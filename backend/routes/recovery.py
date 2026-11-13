"""/api/pulse/recovery — the Recovery area of Pulse.

Log recovery/mindfulness sessions (meditation, breathing, forest bathing, …).
The session types are a config list you can extend or trim; each session records
a type, date, duration, how it felt and a note. Owned by the Pulse module; every
mutation hits the shared activity log. Loose cross-cutting thoughts still belong
in the Mainframe-level Mind Dump — this note field is per-session context.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (
    ProtocolCreate,
    ProtocolDayMark,
    ProtocolHabitCreate,
    ProtocolHabitUpdate,
    ProtocolRevise,
    ProtocolUpdate,
    RecoverySessionCreate,
    RecoveryTypeCreate,
)

router = APIRouter(prefix="/api/pulse/recovery", tags=["recovery"])

# Seed types on first read: (key, name, icon). A handful of common
# practices — all editable/removable from the UI.
_DEFAULT_TYPES = [
    ("meditation", "Meditation", "🧘"),
    ("breathing", "Breathing", "🌬️"),
    ("forest", "Forest Bathing", "🌲"),
    ("sauna", "Sauna", "♨️"),
    ("cold", "Cold Exposure", "🧊"),
    ("nap", "Nap", "😴"),
    ("yoganidra", "Yoga Nidra", "🌙"),
    ("walk", "Nature Walk", "🥾"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(node_var: str) -> str:
    return f"MERGE (mod:Module {{name: 'pulse'}}) MERGE ({node_var})-[:OWNED_BY]->(mod)"


# =========================================================================== #
# TYPES  (config list)
# =========================================================================== #
async def _seed_types() -> None:
    rows = await run_read("MATCH (t:RecoveryType) RETURN count(t) AS n")
    if rows and rows[0]["n"]:
        return
    for i, (key, name, icon) in enumerate(_DEFAULT_TYPES):
        await run_write(
            f"""
            MERGE (t:RecoveryType {{id: $id}})
            SET t.name = $name, t.icon = $icon, t.ord = $ord, t.custom = false
            WITH t {_own('t')}
            """,
            id=key, name=name, icon=icon, ord=i,
        )


@router.get("/types")
async def list_types() -> list[dict]:
    await _seed_types()
    rows = await run_read("MATCH (t:RecoveryType) RETURN t{.*} AS t ORDER BY t.ord, t.name")
    return [r["t"] for r in rows]


@router.post("/types", status_code=201)
async def add_type(body: RecoveryTypeCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name required")
    tid = str(uuid.uuid4())
    icon = (body.icon or "✨").strip() or "✨"
    rows = await run_write(
        f"""
        MATCH (x:RecoveryType) WITH coalesce(max(x.ord), -1) + 1 AS nextOrd
        CREATE (t:RecoveryType {{id: $id, name: $name, icon: $icon, ord: nextOrd, custom: true}})
        WITH t {_own('t')}
        RETURN t{{.*}} AS t
        """,
        id=tid, name=name, icon=icon,
    )
    await record("recovery", "type added", detail=name[:60])
    return rows[0]["t"]


@router.delete("/types/{tid}", status_code=204, response_class=Response)
async def del_type(tid: str) -> Response:
    # Detach the type but keep past sessions (they snapshot the type name).
    await run_write("MATCH (t:RecoveryType {id: $id}) DETACH DELETE t", id=tid)
    await record("recovery", "type removed", detail=tid)
    return Response(status_code=204)


# =========================================================================== #
# SESSIONS
# =========================================================================== #
@router.get("/sessions")
async def list_sessions(limit: int = 60) -> list[dict]:
    rows = await run_read(
        """
        MATCH (s:RecoverySession)
        RETURN s{.*} AS s
        ORDER BY s.date DESC, s.created_at DESC
        LIMIT $limit
        """,
        limit=max(1, min(limit, 500)),
    )
    return [r["s"] for r in rows]


@router.post("/sessions", status_code=201)
async def log_session(body: RecoverySessionCreate) -> dict:
    trows = await run_read(
        "MATCH (t:RecoveryType {id: $id}) RETURN t.name AS name, t.icon AS icon",
        id=body.type_id,
    )
    if not trows:
        raise HTTPException(404, "recovery type not found")
    type_name, type_icon = trows[0]["name"], trows[0]["icon"]
    sid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        MATCH (t:RecoveryType {{id: $type_id}})
        CREATE (s:RecoverySession {{
            id: $id, date: $date, type_id: $type_id, type_name: $type_name,
            type_icon: $type_icon, duration: $duration, feel: $feel, notes: $notes,
            created_at: $now
        }})
        CREATE (s)-[:OF_TYPE]->(t)
        WITH s {_own('s')}
        RETURN s{{.*}} AS s
        """,
        id=sid, date=body.date, type_id=body.type_id, type_name=type_name,
        type_icon=type_icon, duration=body.duration, feel=body.feel.strip(),
        notes=body.notes.strip(), now=_now(),
    )
    await record("recovery", "session logged", detail=f"{type_name} · {body.date} · {body.duration}min")
    return rows[0]["s"]


@router.delete("/sessions/{sid}", status_code=204, response_class=Response)
async def del_session(sid: str) -> Response:
    await run_write("MATCH (s:RecoverySession {id: $id}) DETACH DELETE s", id=sid)
    await record("recovery", "session deleted", detail=sid)
    return Response(status_code=204)


# =========================================================================== #
# STATS  (this week + streak + per-type)
# =========================================================================== #
@router.get("/stats")
async def stats() -> dict:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_start = monday.isoformat()

    week = await run_read(
        """
        MATCH (s:RecoverySession) WHERE s.date >= $start
        RETURN s.type_name AS type, s.type_icon AS icon, s.duration AS duration
        """,
        start=week_start,
    )
    sessions = len(week)
    minutes = sum(int(r["duration"] or 0) for r in week)
    by_type: dict[str, dict] = {}
    for r in week:
        t = r["type"] or "—"
        b = by_type.setdefault(t, {"type": t, "icon": r["icon"] or "✨", "count": 0, "minutes": 0})
        b["count"] += 1
        b["minutes"] += int(r["duration"] or 0)
    breakdown = sorted(by_type.values(), key=lambda x: -x["count"])

    # Streak: consecutive days back from today (or yesterday) with ≥1 session.
    days = await run_read("MATCH (s:RecoverySession) RETURN DISTINCT s.date AS d")
    logged = {r["d"][:10] for r in days if r["d"]}
    streak = 0
    cur = today
    if cur.isoformat() not in logged:
        cur = cur - timedelta(days=1)
    while cur.isoformat() in logged:
        streak += 1
        cur = cur - timedelta(days=1)

    total = await run_read(
        "MATCH (s:RecoverySession) RETURN count(s) AS n, sum(s.duration) AS mins"
    )
    return {
        "week_start": week_start,
        "week_sessions": sessions,
        "week_minutes": minutes,
        "streak": streak,
        "by_type": breakdown,
        "total_sessions": (total[0]["n"] if total else 0) or 0,
        "total_minutes": int((total[0]["mins"] if total else 0) or 0),
    }


# =========================================================================== #
# PROTOCOL — a versioned bundle of recovery habits with a reason
#
# (:RecoveryProtocol {version, why, started, ended, end_reason})-[:INCLUDES {since}]->(:Habit)
#
# The current protocol is the one with no `ended`. Revising closes it with a
# reason and opens the next version carrying the same habits, so the history
# line reads "v1 · meditation only, dropped: never happened · v2".
#
# Protocol habits are ordinary :Habit nodes (category 'recovery'), so the
# Habits tab lists them too. A day's state is DERIVED on every read, never
# stored: a habit with rule 'sessions' is done on any day with a recovery
# session whose type name is in its `rule_types`; any habit is also done on a
# day with a HabitLog level > 0 (a manual tick). A HabitLog with
# `exception: true` excuses the day — it counts neither for nor against.
# =========================================================================== #
def _norm(name: str) -> str:
    return " ".join(str(name or "").lower().split())


async def _current_protocol() -> dict | None:
    rows = await run_read(
        "MATCH (p:RecoveryProtocol) WHERE p.ended IS NULL "
        "RETURN p{.*} AS p ORDER BY p.version DESC LIMIT 1")
    return rows[0]["p"] if rows else None


async def _protocol_or_404() -> dict:
    p = await _current_protocol()
    if not p:
        raise HTTPException(404, "no recovery protocol yet")
    return p


def _day_states(h: dict, since: date, today: date, monday: date,
                session_days: dict[str, set[str]], logs: dict[str, dict]) -> list[dict]:
    """Mon–Sun of this week for one habit: done · exception · miss · today · future · before."""
    types = {_norm(t) for t in (h.get("rule_types") or [])}
    out = []
    for i in range(7):
        d = monday + timedelta(days=i)
        iso = d.isoformat()
        log = logs.get(iso) or {}
        if d < since:
            state = "before"
        elif log.get("exception"):
            state = "exception"
        elif (log.get("level") or 0) > 0 or (
                h.get("rule") == "sessions" and types & session_days.get(iso, set())):
            state = "done"
        elif d > today:
            state = "future"
        elif d == today:
            state = "today"            # still open; not a miss yet
        else:
            state = "miss"
        out.append({"date": iso, "state": state})
    return out


@router.get("/protocol")
async def get_protocol() -> dict:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    history = [r["p"] for r in await run_read(
        "MATCH (p:RecoveryProtocol) RETURN p{.*} AS p ORDER BY p.version")]
    cur = next((p for p in history if not p.get("ended")), None)
    if not cur:
        return {"current": None, "history": history}

    rows = await run_read(
        """
        MATCH (p:RecoveryProtocol {id: $pid})-[r:INCLUDES]->(h:Habit)
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog) WHERE l.date >= $mon AND l.date <= $sun
        RETURN h{.*} AS h, r.since AS since, collect(l{.*}) AS logs
        ORDER BY r.since, h.created_at
        """, pid=cur["id"], mon=monday.isoformat(),
        sun=(monday + timedelta(days=6)).isoformat())
    sess = await run_read(
        "MATCH (s:RecoverySession) WHERE s.date >= $mon AND s.date <= $sun "
        "RETURN s.date AS d, s.type_name AS t",
        mon=monday.isoformat(), sun=(monday + timedelta(days=6)).isoformat())
    session_days: dict[str, set[str]] = {}
    for r in sess:
        session_days.setdefault(str(r["d"])[:10], set()).add(_norm(r["t"]))

    habits, done_all, due_all = [], 0, 0
    for r in rows:
        h = r["h"]
        since = date.fromisoformat(str(r["since"] or cur["started"])[:10])
        logs = {str(l["date"])[:10]: l for l in r["logs"] if l.get("date")}
        week = _day_states(h, since, today, monday, session_days, logs)
        elapsed = [w for w in week if w["date"] <= today.isoformat() and w["state"] != "before"]
        exc = sum(w["state"] == "exception" for w in elapsed)
        done = sum(w["state"] == "done" for w in elapsed)
        due = len(elapsed) - exc
        done_all += done
        due_all += due
        habits.append({
            "id": h["id"], "name": h["name"], "icon": h.get("icon") or "",
            "rule": h.get("rule") or "tick", "rule_types": h.get("rule_types") or [],
            "tier": h.get("tier") or "main", "since": since.isoformat(),
            "week": week, "done": done, "due": due, "exceptions": exc,
        })
    started = date.fromisoformat(str(cur["started"])[:10])
    return {
        "current": {
            **cur, "habits": habits,
            "weeks_in": max(0, (today - started).days // 7),
            "adherence": round(100 * done_all / due_all) if due_all else None,
        },
        "history": history,
    }


@router.post("/protocol", status_code=201)
async def create_protocol(body: ProtocolCreate) -> dict:
    if await _current_protocol():
        raise HTTPException(409, "a protocol is already running; revise it instead")
    await run_write(
        f"""
        CREATE (p:RecoveryProtocol {{id: $id, version: 1, why: $why, started: $today,
                                     ended: null, end_reason: '', created_at: $now}})
        WITH p {_own('p')}
        """, id=str(uuid.uuid4()), why=body.why.strip(),
        today=date.today().isoformat(), now=_now())
    await record("recovery", "protocol started", detail="v1")
    return await get_protocol()


@router.patch("/protocol")
async def update_protocol(body: ProtocolUpdate) -> dict:
    p = await _protocol_or_404()
    if body.why is not None:
        await run_write("MATCH (p:RecoveryProtocol {id: $id}) SET p.why = $why",
                        id=p["id"], why=body.why.strip())
        await record("recovery", "protocol why edited", detail=f"v{p['version']}")
    return await get_protocol()


@router.post("/protocol/revise")
async def revise_protocol(body: ProtocolRevise) -> dict:
    """Close the current version and open the next one with the same habits."""
    p = await _protocol_or_404()
    today = date.today().isoformat()
    nid = str(uuid.uuid4())
    await run_write(
        f"""
        MATCH (old:RecoveryProtocol {{id: $old}})
        SET old.ended = $today, old.end_reason = $reason,
            old.habit_names = [(old)-[:INCLUDES]->(h:Habit) | h.name]
        CREATE (p:RecoveryProtocol {{id: $id, version: old.version + 1, why: $why,
                                     started: $today, ended: null, end_reason: '',
                                     created_at: $now}})
        WITH old, p
        OPTIONAL MATCH (old)-[r:INCLUDES]->(h:Habit)
        FOREACH (_ IN CASE WHEN h IS NULL THEN [] ELSE [1] END |
            MERGE (p)-[:INCLUDES {{since: r.since}}]->(h))
        WITH DISTINCT p {_own('p')}
        """, old=p["id"], id=nid, today=today, reason=body.end_reason.strip(),
        why=body.why.strip() or p.get("why") or "", now=_now())
    await record("recovery", "protocol revised", detail=f"v{p['version']} → v{p['version'] + 1}")
    return await get_protocol()


@router.post("/protocol/habits", status_code=201)
async def add_protocol_habit(body: ProtocolHabitCreate) -> dict:
    p = await _protocol_or_404()
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name required")
    if body.rule == "sessions" and not [t for t in body.rule_types if t.strip()]:
        raise HTTPException(422, "pick at least one session type, or make it a tick habit")
    hid = str(uuid.uuid4())
    await run_write(
        f"""
        MATCH (p:RecoveryProtocol {{id: $pid}})
        CREATE (h:Habit {{
            id: $id, name: $name, category: 'recovery', frequency: 'daily',
            target: null, tags: ['protocol'], main_notes: '', days_of_week: [],
            time_of_day: '', duration_mins: 0, active: true, created_at: $now,
            icon: $icon, rule: $rule, rule_types: $types, tier: $tier
        }})
        CREATE (p)-[:INCLUDES {{since: $today}}]->(h)
        WITH h {_own('h')}
        """, pid=p["id"], id=hid, name=name, icon=body.icon.strip(), rule=body.rule,
        types=[t.strip() for t in body.rule_types if t.strip()], tier=body.tier,
        today=date.today().isoformat(), now=_now())
    await record("recovery", "protocol habit added", detail=name[:60])
    return await get_protocol()


@router.patch("/protocol/habits/{hid}")
async def update_protocol_habit(hid: str, body: ProtocolHabitUpdate) -> dict:
    fields = body.model_dump(exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip()
        if not fields["name"]:
            raise HTTPException(422, "name required")
    if "rule_types" in fields:
        fields["rule_types"] = [t.strip() for t in fields["rule_types"] if t.strip()]
    if fields:
        sets = ", ".join(f"h.{k} = ${k}" for k in fields)
        rows = await run_write(f"MATCH (h:Habit {{id: $id}}) SET {sets} RETURN h.name AS n",
                               id=hid, **fields)
        if not rows:
            raise HTTPException(404, "habit not found")
        await record("recovery", "protocol habit updated", detail=", ".join(fields))
    return await get_protocol()


@router.delete("/protocol/habits/{hid}")
async def remove_protocol_habit(hid: str) -> dict:
    """Take a habit out of the current protocol. The habit itself stays in Habits."""
    p = await _protocol_or_404()
    await run_write(
        "MATCH (:RecoveryProtocol {id: $pid})-[r:INCLUDES]->(:Habit {id: $hid}) DELETE r",
        pid=p["id"], hid=hid)
    await record("recovery", "protocol habit removed", detail=hid)
    return await get_protocol()


@router.post("/protocol/habits/{hid}/day")
async def mark_protocol_day(hid: str, body: ProtocolDayMark) -> dict:
    """Tick a day done, excuse it, or clear the manual mark (derived done stays)."""
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    level, exc = {"done": (3, False), "exception": (0, True), "clear": (0, False)}[body.state]
    rows = await run_write(
        """
        MATCH (h:Habit {id: $hid})
        MERGE (h)-[:HAS_LOG]->(l:HabitLog {habit_id: $hid, date: $date})
          ON CREATE SET l.id = $id, l.time_spent = '', l.notes = '', l.feel = '', l.connections = ''
        SET l.level = $level, l.exception = $exc
        RETURN h.name AS n
        """, hid=hid, date=body.date, id=str(uuid.uuid4()), level=level, exc=exc)
    if not rows:
        raise HTTPException(404, "habit not found")
    await record("recovery", "protocol day " + body.state, detail=f"{rows[0]['n'][:40]} · {body.date}")
    return await get_protocol()
