"""/api/calendar — the Mainframe's calendar. A top-level service, not a module tab.

Why this isn't just another Google Calendar
-------------------------------------------
Google knows your *commitments*. The Mainframe already knows your *tasks*, the
*work you actually logged*, your habits, workouts and recovery. Putting them in
one grid is the point: a calendar that can show planned-vs-actual, and that has
enough context to say "Thursday afternoon is free and this is due Friday".

So a day here has three layers, and they are deliberately different things:

  * **events**  — commitments with a time. `:CalEvent`. Yours to edit, or
                  imported read-only from an .ics file.
  * **due**     — tasks whose `due_date` lands on that day. NOT copied into the
                  calendar: read live from `:Task`, so a due date can never
                  disagree with itself in two places.
  * **done**    — what actually happened: work sessions, workouts, habit logs.
                  Read-only here; the calendar reports, it doesn't own them.

Times follow the convention `:WorkSession` already set — a separate `date`
(YYYY-MM-DD) plus `HH:MM` `start`/`end`. Local time, no zone maths, because this
is a single-user app running on one machine and a timezone-aware store would be
cost with no benefit. The .ics importer converts into this on the way in.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import CalEventCreate, CalEventUpdate

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

KINDS = ["event", "block", "reminder"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _mins(hhmm: str) -> int | None:
    """'14:30' -> 870. Returns None for anything that isn't a real time."""
    if not hhmm or ":" not in hhmm:
        return None
    try:
        h, m = hhmm.split(":")[:2]
        h, m = int(h), int(m)
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def _hhmm(mins: int) -> str:
    mins = max(0, min(mins, 24 * 60))
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _duration(ev: dict) -> int:
    """Minutes an event occupies. An end before its start is treated as
    crossing midnight rather than as negative time."""
    s, e = _mins(ev.get("start", "")), _mins(ev.get("end", ""))
    if s is None or e is None:
        return 0
    return (e - s) if e >= s else (24 * 60 - s + e)


def _event_out(e: dict) -> dict:
    e = dict(e)
    e["duration_mins"] = _duration(e)
    e.setdefault("all_day", False)
    return e


# --------------------------------------------------------------------------- #
# Events — the only thing the calendar actually owns
# --------------------------------------------------------------------------- #
@router.get("/events")
async def list_events(from_: str | None = None, to: str | None = None,
                      limit: int = 2000) -> list[dict]:
    where, params = [], {"limit": max(1, min(limit, 5000))}
    if from_:
        # A multi-day event must still show on days inside its span, not only on
        # the day it began — so compare against its END. `coalesce` is not
        # enough here: end_date is stored as "" (not null) for single-day
        # events, and "" >= "2026-07-25" is false, which silently hid
        # everything. Neo4j has no "" -> null coercion; the CASE is required.
        where.append("(CASE WHEN coalesce(e.end_date,'') = '' THEN e.date "
                     "ELSE e.end_date END) >= $from")
        params["from"] = from_
    if to:
        where.append("e.date <= $to")
        params["to"] = to
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await run_read(
        f"""
        MATCH (e:CalEvent) {clause}
        RETURN e{{.*}} AS e
        ORDER BY e.date, coalesce(e.start, ''), e.title
        LIMIT $limit
        """,
        **params,
    )
    out = [_event_out(r["e"]) for r in rows]
    if from_ and to:
        out += await _repeats(from_, to, {e["id"] for e in out})
        out.sort(key=lambda e: (e.get("date") or "", e.get("start") or "", e.get("title") or ""))
    return out


async def _repeats(from_: str, to: str, seen: set[str]) -> list[dict]:
    """Every week of each weekly event that falls in [from_, to].

    Occurrences are computed, never stored: one :CalEvent is the series, so
    editing or deleting it changes every week at once. Each occurrence carries
    the series id plus its own date (`series_id`), and the first one, which is
    the stored node itself, is skipped when the plain query already found it.
    """
    rows = await run_read(
        """
        MATCH (e:CalEvent)
        WHERE e.repeat = 'weekly' AND e.date <= $to
          AND (coalesce(e.repeat_until, '') = '' OR e.repeat_until >= $from)
        RETURN e{.*} AS e
        """, **{"from": from_, "to": to})
    lo, hi = date.fromisoformat(from_), date.fromisoformat(to)
    out = []
    for r in rows:
        e = _event_out(r["e"])
        first = date.fromisoformat(e["date"][:10])
        until = date.fromisoformat(e["repeat_until"][:10]) if e.get("repeat_until") else hi
        d = first
        if d < lo:
            d = first + timedelta(days=((lo - first).days + 6) // 7 * 7)
        while d <= min(hi, until):
            if not (d == first and e["id"] in seen):
                out.append({**e, "date": d.isoformat(), "end_date": "",
                            "series_id": e["id"], "series_first": first.isoformat(),
                            "occurrence": d.isoformat()})
            d += timedelta(days=7)
    return out


@router.post("/events", status_code=201)
async def create_event(body: CalEventCreate) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "an event needs a title")
    if not body.date:
        raise HTTPException(400, "an event needs a date")
    props = {k: v for k, v in body.model_dump().items() if v is not None}
    task_id = props.pop("task_id", None)
    props.update({"id": str(uuid.uuid4()), "title": body.title.strip(),
                  "source": "mainframe", "created_at": _now()})
    keys = ", ".join(f"{k}: ${k}" for k in props)
    rows = await run_write(f"CREATE (e:CalEvent {{{keys}}}) RETURN e{{.*}} AS e", **props)
    if task_id:
        await _link_task(props["id"], task_id)
    await record("calendar", "event created", detail=body.title[:60], module=body.module or "")
    return _event_out(rows[0]["e"])


@router.put("/events/{eid}")
async def update_event(eid: str, body: CalEventUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    task_id = fields.pop("task_id", "__unset__")
    if not fields and task_id == "__unset__":
        raise HTTPException(400, "no fields to update")
    rows = []
    if fields:
        sets = ", ".join(f"e.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (e:CalEvent {{id:$id}}) SET {sets}, e.updated_at = $ts RETURN e{{.*}} AS e",
            id=eid, ts=_now(), **fields,
        )
        if not rows:
            raise HTTPException(404, "event not found")
    if task_id != "__unset__":
        await _link_task(eid, task_id)
    if not rows:
        rows = await run_read("MATCH (e:CalEvent {id:$id}) RETURN e{.*} AS e", id=eid)
        if not rows:
            raise HTTPException(404, "event not found")
    await record("calendar", "event updated", detail=", ".join(fields) or "task link")
    return _event_out(rows[0]["e"])


@router.delete("/events/{eid}", status_code=204, response_class=Response)
async def delete_event(eid: str) -> Response:
    await run_write("MATCH (e:CalEvent {id:$id}) DETACH DELETE e", id=eid)
    await record("calendar", "event deleted", detail=eid)
    return Response(status_code=204)


async def _link_task(eid: str, task_id: str | None) -> None:
    """Point an event at the task it's meant to advance — or unpoint it.

    One event plans at most one task, so the old edge always goes first.
    """
    await run_write("MATCH (:CalEvent {id:$id})-[r:PLANS]->() DELETE r", id=eid)
    if task_id:
        await run_write(
            "MATCH (e:CalEvent {id:$id}), (t:Task {id:$tid}) MERGE (e)-[:PLANS]->(t) "
            "SET e.task_id = $tid",
            id=eid, tid=task_id,
        )
    else:
        await run_write("MATCH (e:CalEvent {id:$id}) REMOVE e.task_id", id=eid)


# --------------------------------------------------------------------------- #
# The unified range feed — events + what's due + what actually happened
# --------------------------------------------------------------------------- #
@router.get("/range")
async def range_feed(from_: str, to: str) -> dict:
    """Everything the Mainframe knows about a span of days, keyed by date.

    Due dates and logged work are read live from `:Task` / `:WorkSession` rather
    than copied into calendar nodes. Copying would create two places for the
    same fact to live, and they would drift within a week.
    """
    events = await list_events(from_=from_, to=to)

    due = await run_read(
        """
        MATCH (t:Task)
        WHERE t.due_date >= $start AND t.due_date <= $end
        RETURN t{.id, .title, .due_date, .status, .priority, .horizon, .module,
                 .estimate_mins, .done_at} AS t
        ORDER BY t.due_date, t.priority
        """,
        start=from_, end=to,
    )

    work = await run_read(
        """
        MATCH (w:WorkSession)
        WHERE w.date >= $start AND w.date <= $end
        // :WorkSession stores `mins`/`what`/`ref_kind` — projecting `minutes`
        // and `title` silently returned nulls, so every logged block showed up
        // unlabelled and with no duration. Aliased rather than renamed so the
        // shape this endpoint has always published stays the same.
        RETURN w{.id, .date, .start, .end, minutes: w.mins,
                 title: coalesce(w.what, w.ref_title), kind: w.ref_kind,
                 .module, detail: w.focus} AS w
        ORDER BY w.date, coalesce(w.start,'')
        """,
        start=from_, end=to,
    )

    logged = await run_read(
        """
        CALL () {
          MATCH (x:Workout)  WHERE x.date >= $start AND x.date <= $end
          RETURN x.date AS date, 'workout' AS kind,
                 coalesce(x.name, x.type, 'Workout') AS label, x.id AS id
        UNION ALL
          MATCH (h:Habit)-[:HAS_LOG]->(x:HabitLog)
          WHERE x.date >= $start AND x.date <= $end
          RETURN x.date AS date, 'habit' AS kind, h.name AS label, x.id AS id
        UNION ALL
          MATCH (x:RecoverySession) WHERE x.date >= $start AND x.date <= $end
          RETURN x.date AS date, 'recovery' AS kind,
                 coalesce(x.type_name, 'Recovery') AS label, x.id AS id
        UNION ALL
          MATCH (x:StretchSession) WHERE x.date >= $start AND x.date <= $end
          RETURN x.date AS date, 'stretch' AS kind, 'Stretch' AS label, x.id AS id
        }
        RETURN date, kind, label, id ORDER BY date
        """,
        start=from_, end=to,
    )

    # Workouts, with their type and length. They have a date but no start
    # time yet, so the client puts them in the day's all-day strip.
    workouts = await run_read(
        """
        MATCH (x:Workout) WHERE x.date >= $start AND x.date <= $end
        RETURN x{.id, .date, .type, .name, duration: coalesce(x.duration_min, x.duration, 0),
                 .start} AS w
        ORDER BY x.date
        """, start=from_, end=to)

    # Inbox rows you've said you'll do on a day ("do on", optional time and
    # "takes"). Read live, never copied into :CalEvent, for the same reason as
    # due dates above; the client draws them as blocks that open the Inbox.
    planned = await run_read(
        """
        MATCH (t:Task)
        WHERE t.do_on >= $start AND t.do_on <= $end
          AND NOT coalesce(t.status, '') IN ['dropped', 'became']
        RETURN t{.id, .title, .kind, .status, .do_on, .do_at, .takes_min, module: coalesce(t.module, '')} AS t
        ORDER BY t.do_on, coalesce(t.do_at, '')
        """,
        start=from_, end=to,
    )

    return {
        "from": from_, "to": to,
        "events": events,
        "planned": [r["t"] for r in planned],
        "workouts": [r["w"] for r in workouts],
        "plan_blocks": await _plan_blocks(from_, to),
        "due": [r["t"] for r in due],
        "work": [r["w"] for r in work],
        "logged": [dict(r) for r in logged],
    }


async def _plan_blocks(from_: str, to: str) -> list[dict]:
    """The Planner's blocks for the span, in this calendar's shape.

    Read through the Planner's own payload rather than from :CalEvent: its
    auto-placed blocks are computed, never stored, and its stored ones keep a
    full ISO `start` where this calendar keeps date + HH:MM. Asking the Planner
    is the only way the two can't disagree. External (synced) events are left
    out; they already arrive here as ordinary events.
    """
    from routes import planner   # local: planner imports models this module also uses
    try:
        lo, hi = date.fromisoformat(from_), date.fromisoformat(to)
    except ValueError:
        return []
    mods = {r["id"]: (r["module"] or "") for r in await run_read(
        "MATCH (p:PlanItem) RETURN p.id AS id, p.module AS module")}
    out, seen = [], set()
    ws = lo - timedelta(days=lo.weekday())
    while ws <= hi:
        payload = await planner._calendar_payload("week", ws)
        for e in payload["events"]:
            if e.get("source") == "external" or e["id"] in seen or not e.get("start"):
                continue
            d = e["start"][:10]
            if not (from_ <= d <= to):
                continue
            seen.add(e["id"])
            out.append({"id": e["id"], "title": e["title"], "date": d,
                        "start": e["start"][11:16], "end": (e.get("end") or "")[11:16],
                        "category": e.get("category") or "", "source": e.get("source") or "",
                        "item_id": e.get("item_id"),
                        "module": mods.get(e.get("item_id") or "", "")})
        ws += timedelta(days=7)
    return out


# --------------------------------------------------------------------------- #
# Free/busy — the arithmetic every suggestion is built on
# --------------------------------------------------------------------------- #
DAY_START, DAY_END = 8 * 60, 22 * 60      # the window a suggestion may use


def _busy_blocks(events: list[dict], work: list[dict], day: str) -> list[tuple[int, int, str]]:
    """Everything already occupying that day, as (start, end, label) minutes.

    All-day events are NOT treated as busy: "a friend's birthday" blocks no time.
    Anything without a start time can't be placed on a clock, so it can't make
    a gap disappear either.
    """
    out: list[tuple[int, int, str]] = []
    for e in events:
        if e.get("date") != day or e.get("all_day"):
            continue
        s, en = _mins(e.get("start", "")), _mins(e.get("end", ""))
        if s is None:
            continue
        out.append((s, en if en is not None and en > s else s + 30, e.get("title", "event")))
    for w in work:
        if w.get("date") != day:
            continue
        s, en = _mins(w.get("start", "")), _mins(w.get("end", ""))
        if s is None:
            continue
        out.append((s, en if en is not None and en > s else s + 30,
                    w.get("title") or w.get("kind") or "work"))
    return sorted(out)


def _free_gaps(busy: list[tuple[int, int, str]],
               day_start: int = DAY_START, day_end: int = DAY_END,
               min_len: int = 30) -> list[tuple[int, int]]:
    """Invert the busy list into free gaps, merging overlaps as it goes."""
    gaps: list[tuple[int, int]] = []
    cursor = day_start
    for s, e, _label in busy:
        if e <= day_start or s >= day_end:
            continue
        s, e = max(s, day_start), min(e, day_end)
        if s - cursor >= min_len:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if day_end - cursor >= min_len:
        gaps.append((cursor, day_end))
    return gaps


# --------------------------------------------------------------------------- #
# .ics import — how Google Calendar gets in
# --------------------------------------------------------------------------- #
@router.get("/import/status")
async def import_status() -> dict:
    import icsimport
    d = icsimport.import_dir()
    d.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in d.glob("*.ics") if p.is_file())
    rows = await run_read(
        "MATCH (e:CalEvent) WHERE e.source = 'ics' "
        "RETURN e.calendar_name AS name, count(e) AS n ORDER BY n DESC"
    )
    return {
        "dir": str(d),
        "files": [{"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1),
                   "modified": datetime.fromtimestamp(p.stat().st_mtime)
                                       .isoformat(timespec="seconds")}
                  for p in files],
        "calendars": [{"name": r["name"] or "(unnamed)", "events": r["n"]} for r in rows],
        "imported": sum(r["n"] for r in rows),
    }


@router.post("/import")
async def import_ics() -> dict:
    """Re-read the import folder. Safe to call repeatedly — imported events are
    keyed on their .ics UID plus occurrence date, so re-importing updates in
    place rather than duplicating."""
    import icsimport
    summary = await icsimport.sync()
    await record("calendar", "calendar imported",
                 detail=f"{summary['imported']} events from {len(summary['files'])} file(s)",
                 trigger="system")
    return summary


@router.get("/suggestions")
async def suggestions(date_: str | None = None, days: int = 7) -> list[dict]:
    """Real-time suggestions, computed — never guessed.

    Every suggestion carries a `why` naming the numbers it came from, and an
    optional `action` the UI can turn into one click. That constraint is the
    design: a planner that can't show its working is one you stop trusting the
    first time it's wrong, and this one is also going to be the tool surface a
    voice agent drives later — so it has to return facts, not prose.

    Deliberately NOT an LLM. Nothing here can hallucinate a meeting.
    """
    start = date.fromisoformat(date_ or _today())
    span = max(1, min(days, 31))
    end = start + timedelta(days=span - 1)
    feed = await range_feed(from_=start.isoformat(), to=end.isoformat())

    out: list[dict] = []
    today = start.isoformat()

    # --- 1. Clashes. Two commitments at once is always worth saying first. ----
    by_day: dict[str, list[dict]] = {}
    for e in feed["events"]:
        if not e.get("all_day") and _mins(e.get("start", "")) is not None:
            by_day.setdefault(e["date"], []).append(e)
    for day, evs in sorted(by_day.items()):
        evs = sorted(evs, key=lambda x: _mins(x["start"]) or 0)
        for a, b in zip(evs, evs[1:]):
            a_end = (_mins(a.get("end", "")) or ((_mins(a["start"]) or 0) + 30))
            b_start = _mins(b["start"]) or 0
            if b_start < a_end:
                out.append({
                    "kind": "clash", "severity": "high", "date": day,
                    "title": f"“{a['title']}” overlaps “{b['title']}”",
                    "why": f"{a['start']}–{a.get('end') or '?'} runs into {b['start']} "
                           f"on {day} — {a_end - b_start} minutes of overlap.",
                    "event_ids": [a["id"], b["id"]],
                })

    # --- 2. Due today/tomorrow with no time set aside for it. ----------------
    planned_task_ids = {e.get("task_id") for e in feed["events"] if e.get("task_id")}
    open_due = [t for t in feed["due"]
                if t.get("status") != "done" and not t.get("done_at")]
    for t in open_due:
        if t["id"] in planned_task_ids:
            continue
        days_left = (date.fromisoformat(t["due_date"]) - start).days
        if days_left > 2:
            continue
        when = "today" if days_left == 0 else "tomorrow" if days_left == 1 else t["due_date"]
        out.append({
            "kind": "unplanned_due",
            "severity": "high" if days_left <= 0 else "medium",
            "date": t["due_date"], "task_id": t["id"],
            "title": f"“{t['title']}” is due {when} with no time booked",
            "why": f"Due {t['due_date']}, status {t.get('status') or 'open'}, and no "
                   f"calendar block points at it.",
            "action": {"type": "schedule_task", "task_id": t["id"]},
        })

    # --- 3. Free gaps big enough to be worth something. ----------------------
    #     Matched against what's actually due, so the suggestion is a plan and
    #     not just an observation that you have free time.
    unplanned = [t for t in open_due if t["id"] not in planned_task_ids]
    for offset in range(span):
        day = (start + timedelta(days=offset)).isoformat()
        busy = _busy_blocks(feed["events"], feed["work"], day)
        gaps = _free_gaps(busy, min_len=45)
        if not gaps:
            if offset == 0:
                out.append({
                    "kind": "full_day", "severity": "medium", "date": day,
                    "title": "Nothing free today between 08:00 and 22:00",
                    "why": f"{len(busy)} blocks fill the day "
                           f"({sum(e - s for s, e, _ in busy)} minutes booked).",
                })
            continue
        biggest = max(gaps, key=lambda g: g[1] - g[0])
        mins = biggest[1] - biggest[0]
        if mins < 60 or offset > 3:
            continue
        match = next((t for t in unplanned
                      if date.fromisoformat(t["due_date"]) >= date.fromisoformat(day)), None)
        s = {
            "kind": "free_block", "severity": "low", "date": day,
            "title": f"{_hhmm(biggest[0])}–{_hhmm(biggest[1])} is free — "
                     f"{mins // 60}h{mins % 60 or ''}",
            "why": f"{len(busy)} block(s) booked on {day}; this is the longest gap "
                   f"inside 08:00–22:00.",
        }
        if match:
            s["title"] += f" · “{match['title']}” is due {match['due_date']}"
            s["task_id"] = match["id"]
            s["action"] = {"type": "schedule_task", "task_id": match["id"],
                           "date": day, "start": _hhmm(biggest[0]),
                           "end": _hhmm(min(biggest[1], biggest[0] + 120))}
        out.append(s)

    # --- 4. Overdue. Read separately, because it's outside the window. -------
    overdue = await run_read(
        """
        MATCH (t:Task)
        WHERE t.due_date < $today AND coalesce(t.status,'') <> 'done' AND t.done_at IS NULL
        RETURN t{.id, .title, .due_date} AS t ORDER BY t.due_date LIMIT 5
        """,
        today=today,
    )
    for r in overdue:
        t = r["t"]
        late = (start - date.fromisoformat(t["due_date"])).days
        out.append({
            "kind": "overdue", "severity": "high", "date": t["due_date"], "task_id": t["id"],
            "title": f"“{t['title']}” is {late} day{'s' if late != 1 else ''} overdue",
            "why": f"Due {t['due_date']}, still open.",
            "action": {"type": "schedule_task", "task_id": t["id"]},
        })

    # --- 5. Neglect. What the Mainframe knows that a calendar can't. ---------
    week_ago = (start - timedelta(days=6)).isoformat()
    counts = await run_read(
        """
        CALL () {
          MATCH (x:Workout) WHERE x.date >= $start AND x.date <= $today
          RETURN 'workout' AS kind, count(x) AS n
        UNION ALL
          MATCH (x:RecoverySession) WHERE x.date >= $start AND x.date <= $today
          RETURN 'recovery' AS kind, count(x) AS n
        }
        RETURN kind, n
        """,
        start=week_ago, today=today,
    )
    tally = {r["kind"]: r["n"] for r in counts}
    if tally.get("workout", 0) >= 3 and tally.get("recovery", 0) == 0:
        out.append({
            "kind": "neglect", "severity": "low", "date": today,
            "title": "No recovery logged this week, against "
                     f"{tally['workout']} workouts",
            "why": f"{week_ago} → {today}: {tally['workout']} workouts, 0 recovery sessions.",
        })

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda s: (order.get(s["severity"], 3), s["date"]))
    return out


@router.get("/freebusy")
async def freebusy(date_: str | None = None) -> dict:
    """One day's busy blocks and the gaps between them."""
    d = date_ or _today()
    feed = await range_feed(from_=d, to=d)
    busy = _busy_blocks(feed["events"], feed["work"], d)
    gaps = _free_gaps(busy)
    return {
        "date": d,
        "busy": [{"start": _hhmm(s), "end": _hhmm(e), "label": lb, "mins": e - s}
                 for s, e, lb in busy],
        "free": [{"start": _hhmm(s), "end": _hhmm(e), "mins": e - s} for s, e in gaps],
        "free_mins": sum(e - s for s, e in gaps),
        "busy_mins": sum(e - s for s, e, _ in busy),
        "window": {"start": _hhmm(DAY_START), "end": _hhmm(DAY_END)},
    }
