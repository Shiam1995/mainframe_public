"""/api/planner — long-running study/build items with weekly hour budgets.

Mainframe-level service (PLANNER_SPEC v2): the tab lives in Synapse but the
storage and routes belong to no module. Items carry a total-hours estimate, a
weekly budget, and a priority order; real work lands as :Session nodes (timer
or manual) and everything downstream — velocity, projected finishes, deficits,
weekly reports — is DERIVED from sessions, never stored on the item.

v2 adds the second surface. One item list, seen two ways:
  · Budget  — "what fits before the horizon, and in what order?" A capacity
    (h/wk) times a horizon (weeks) gives a supply; items are funded top-down
    in priority order until supply runs out. That cutline is the whole point.
  · Calendar — "when does it happen?" Funded study/build/paper items AUTO-PLACE
    into the slot template; fixed/fitness/event items are HAND-PLACED.

Hard rules from the spec:
  · at most ONE open session system-wide (switching focus closes the old one)
  · items with sessions are never hard-deleted — they become "dropped"
  · WeeklyReport payloads are frozen JSON; live edits never mutate a past report
  · the planner is a plan, not a to-do list — checkbox work stays in Tasks,
    linked via [:REALISED_BY]
  · auto-placed blocks are NEVER stored. They are recomputed on every read from
    PlanItems + slot template + day blocks, so they cannot drift from the
    budget. Only hand-placed and externally-synced blocks are :CalEvent rows.
  · auto-placement never overlaps a manual/external event — manual wins the slot.

Known v2 limitation, per spec §4: a blocked-off day's intended work is NOT
carried forward. Redistribution needs the live-calendar reflow engine (§9),
which is deliberately deferred; only the /week deficit contract exists now.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Response

from activity import record
from db import run_read, run_write
from models import (
    PlanCompleteBody,
    PlanDayBlockCreate,
    PlanEventCreate,
    PlanEventUpdate,
    PlanFocusStop,
    PlanItemCreate,
    PlanItemUpdate,
    PlanLinkCreate,
    PlanNoteCreate,
    PlannerSettingsUpdate,
    PlanReorder,
    PlanSessionManual,
    PlanSessionUpdate,
)

log = logging.getLogger("synapse.planner")
router = APIRouter(prefix="/api/planner", tags=["planner"])

DEFAULT_CAPACITY = 20.0
DEFAULT_DAY_BOUNDS = {"start": "06:00", "end": "22:00"}

# Categories whose work is scheduled FOR the user by the auto-placement engine.
# Everything else (fixed commitments, gym, one-off events) is hand-placed.
AUTO_CATEGORIES = frozenset({"study", "build", "paper"})

# The starting weekly rhythm: three open slots a day, 19.25h/wk, which sits
# just under the default 20h capacity. The user edits this in Budget settings;
# it is a template for WHEN work can happen, not seeded plan data.
DEFAULT_SLOTS = [
    {"dow": d, "start": s, "length_min": n}
    for d in range(7)
    for s, n in (("11:15", 45), ("14:00", 60), ("18:30", 60))
]

# Auto-placement granularity. A gap smaller than this between manual events is
# not worth walking to, so the engine leaves it empty rather than emitting a
# sliver block. Matches the composer's 15-minute snap.
MIN_BLOCK_MIN = 15


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())          # Monday


def _sdate(iso: str | None) -> date | None:
    """Date part of an ISO datetime/date string."""
    if not iso:
        return None
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Derived values (spec §3) — computed from sessions, never stored
# --------------------------------------------------------------------------- #
def _hours_in_week(sessions: list[dict], ws: date) -> float:
    we = ws + timedelta(days=6)
    mins = sum(
        s.get("minutes") or 0
        for s in sessions
        if (d := _sdate(s.get("start"))) and ws <= d <= we
    )
    return mins / 60.0


def _derived(item: dict, sessions: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    cur_ws = _week_start(today)
    hours_logged = sum(s.get("minutes") or 0 for s in sessions) / 60.0
    hours_this_week = _hours_in_week(sessions, cur_ws)

    # velocity: rolling mean over the last 4 FULL weeks; null until 2 full
    # weeks of data exist. A "full week" is a completed Mon–Sun window on or
    # after the week of the first session.
    velocity = None
    firsts = [d for s in sessions if (d := _sdate(s.get("start")))]
    if firsts:
        first_ws = _week_start(min(firsts))
        full_weeks = (cur_ws - first_ws).days // 7          # completed weeks
        if full_weeks >= 2:
            n = min(4, full_weeks)
            wins = [cur_ws - timedelta(weeks=k) for k in range(1, n + 1)]
            velocity = round(sum(_hours_in_week(sessions, w) for w in wins) / n, 2)

    def _finish(rate: float | None) -> str | None:
        if not rate or rate <= 0:
            return None
        start = _sdate(item.get("start_date")) or today
        remaining = max(0.0, (item.get("total_hours") or 0) - hours_logged)
        return (start + timedelta(weeks=math.ceil(remaining / rate))).isoformat()

    hpw = item.get("hours_per_week") or 0
    return {
        "hours_logged": round(hours_logged, 2),
        "hours_this_week": round(hours_this_week, 2),
        "velocity": velocity,
        "projected_finish_budget": _finish(hpw),
        "projected_finish_velocity": _finish(velocity),
        "deficit_this_week": round(max(0.0, hpw - hours_this_week), 2),
    }


async def _sessions_by_item(item_ids: list[str] | None = None) -> dict[str, list[dict]]:
    where = "WHERE p.id IN $ids" if item_ids is not None else ""
    rows = await run_read(
        f"""
        MATCH (s:Session)-[:FOR]->(p:PlanItem) {where}
        WITH p, s ORDER BY s.start
        RETURN p.id AS id, collect(s{{.*}}) AS sessions
        """,
        ids=item_ids,
    )
    return {r["id"]: r["sessions"] for r in rows}


async def _last_report_finishes(before_week: date | None = None) -> dict[str, str]:
    """item id → projected_finish_velocity as frozen in the most recent report."""
    where = "WHERE r.week_start < $wk" if before_week else ""
    rows = await run_read(
        f"MATCH (r:WeeklyReport) {where} RETURN r.payload AS payload "
        "ORDER BY r.week_start DESC LIMIT 1",
        wk=before_week.isoformat() if before_week else None,
    )
    if not rows or not rows[0]["payload"]:
        return {}
    try:
        payload = json.loads(rows[0]["payload"])
    except (TypeError, ValueError):
        return {}
    return {
        i["id"]: i.get("projected_finish_velocity")
        for i in payload.get("items", [])
        if i.get("projected_finish_velocity")
    }


def _drift_days(current: str | None, previous: str | None) -> int | None:
    """Days the velocity finish moved since the last report (+ = later)."""
    if not current or not previous:
        return None
    return ((_sdate(current) or date.today()) - (_sdate(previous) or date.today())).days


# --------------------------------------------------------------------------- #
# Settings: capacity, horizon and the slot template (spec §2 :SlotTemplate)
#
# v1 already owned a :PlannerSettings singleton holding `capacity`. The slot
# template lives on that same node rather than a second settings node, so
# capacity keeps exactly one source of truth — a forked settings node would let
# the Budget supply and the Calendar's placement disagree, which is the one
# inconsistency the two-surface model cannot tolerate.
# --------------------------------------------------------------------------- #
def _hhmm(s: str, fallback: int = 0) -> int:
    """'HH:MM' → minutes past midnight."""
    try:
        h, m = str(s).split(":")[:2]
        v = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return fallback
    return v if 0 <= v <= 24 * 60 else fallback


def _mmhh(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _default_horizon(today: date | None = None) -> date:
    """31 December of the current year — the spec's working horizon."""
    return date((today or date.today()).year, 12, 31)


def _clean_slots(raw: object, bounds: dict) -> list[dict]:
    """Keep only slots that are well-formed and fit inside the day bounds.

    A slot that starts before the day opens or runs past when it closes would
    place blocks the calendar grid cannot draw, so it is clipped or dropped
    here rather than producing invisible work.
    """
    lo, hi = _hhmm(bounds["start"], 360), _hhmm(bounds["end"], 1320)
    out: list[dict] = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        try:
            dow = int(s.get("dow"))
            length = int(s.get("length_min"))
        except (TypeError, ValueError):
            continue
        start = _hhmm(s.get("start"), -1)
        if not (0 <= dow <= 6) or length <= 0 or start < 0:
            continue
        start = max(start, lo)
        length = min(length, hi - start)
        if length < MIN_BLOCK_MIN:
            continue
        out.append({"dow": dow, "start": _mmhh(start), "length_min": length})
    # template order is the fill order: earliest day, then earliest time
    out.sort(key=lambda s: (s["dow"], _hhmm(s["start"])))
    return out


async def _get_settings() -> dict:
    rows = await run_read(
        "MATCH (s:PlannerSettings) RETURN s{.*} AS s ORDER BY s.id LIMIT 1")
    node = rows[0]["s"] if rows else {}

    cap = node.get("capacity")
    capacity = float(cap) if cap is not None else DEFAULT_CAPACITY

    horizon = _sdate(node.get("horizon_date")) or _default_horizon()

    tpl: dict = {}
    if node.get("template"):
        try:
            tpl = json.loads(node["template"])
        except (TypeError, ValueError):
            log.warning("planner slot template is not valid JSON; using defaults")
    bounds = tpl.get("day_bounds") if isinstance(tpl.get("day_bounds"), dict) else {}
    bounds = {
        "start": bounds.get("start") or DEFAULT_DAY_BOUNDS["start"],
        "end": bounds.get("end") or DEFAULT_DAY_BOUNDS["end"],
    }
    slots = _clean_slots(tpl.get("slots"), bounds) if "slots" in tpl else None
    if slots is None:
        slots = _clean_slots(DEFAULT_SLOTS, bounds)

    return {
        "capacity_per_week": capacity,
        "capacity": capacity,               # v1 field name, kept for the topbar
        "horizon_date": horizon.isoformat(),
        "day_bounds": bounds,
        "slots": slots,
        "slot_hours_per_week": round(
            sum(s["length_min"] for s in slots) / 60.0, 2),
    }


async def _get_capacity() -> float:
    return (await _get_settings())["capacity_per_week"]


def _estimate(low: float | None, high: float | None,
              total: float | None) -> tuple[float | None, float | None, float]:
    """Resolve the low/high range and the planning total.

    The range is optional. When both ends are given the total defaults to the
    midpoint, and a total outside the range is refused — the budget would be
    funding a number the estimate itself rules out.
    """
    for v, n in ((low, "lower"), (high, "upper")):
        if v is not None and v <= 0:
            raise HTTPException(400, f"{n} estimate must be greater than 0")
    if low is not None and high is not None and low > high:
        raise HTTPException(400, "lower estimate cannot exceed the upper estimate")
    if total is None:
        if low is not None and high is not None:
            total = round((low + high) / 2, 2)
        else:
            total = high if high is not None else low
    if total is None or total <= 0:
        raise HTTPException(400, "total hours (or a low/high estimate) is required")
    if low is not None and high is not None and not (low <= total <= high):
        raise HTTPException(400, "total hours must sit inside the low–high estimate")
    return low, high, float(total)


async def _item_or_404(item_id: str) -> dict:
    rows = await run_read("MATCH (p:PlanItem {id: $id}) RETURN p{.*} AS p", id=item_id)
    if not rows:
        raise HTTPException(404, "plan item not found")
    return rows[0]["p"]


async def _close_open_session(note: str = "") -> dict | None:
    """Close the (at most one) open session; returns it or None."""
    rows = await run_write(
        """
        MATCH (s:Session)-[:FOR]->(p:PlanItem) WHERE s.end IS NULL
        SET s.end = $now,
            s.minutes = toInteger(duration.between(datetime(s.start), datetime($now)).seconds / 60),
            s.note = CASE WHEN $note <> '' THEN $note ELSE s.note END
        RETURN s{.*} AS session, p.name AS item_name, p.id AS item_id
        """,
        now=_now(), note=note,
    )
    return rows[0] if rows else None


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.get("/settings")
async def get_settings() -> dict:
    return await _get_settings()


@router.patch("/settings")
async def patch_settings(body: PlannerSettingsUpdate) -> dict:
    """Partial update — the Budget sliders send one field at a time."""
    cur = await _get_settings()
    capacity = body.capacity_per_week if body.capacity_per_week is not None else body.capacity
    if capacity is not None and capacity <= 0:
        raise HTTPException(400, "capacity must be greater than 0")

    bounds = body.day_bounds.model_dump() if body.day_bounds else cur["day_bounds"]
    if _hhmm(bounds["end"], 1320) <= _hhmm(bounds["start"], 360):
        raise HTTPException(400, "day bounds must end after they start")

    slots = cur["slots"]
    if body.slots is not None:
        slots = _clean_slots([s.model_dump() for s in body.slots], bounds)
    elif body.day_bounds is not None:
        slots = _clean_slots(slots, bounds)      # re-clip to the new window

    horizon = body.horizon_date or _sdate(cur["horizon_date"]) or _default_horizon()
    if horizon <= date.today():
        raise HTTPException(400, "horizon must be in the future")

    await run_write(
        """
        MERGE (s:PlannerSettings {id: 'planner'})
        SET s.capacity = $c, s.horizon_date = $h, s.template = $t
        """,
        c=float(capacity if capacity is not None else cur["capacity_per_week"]),
        h=horizon.isoformat(),
        t=json.dumps({"day_bounds": bounds, "slots": slots}),
    )
    changed = [k for k, v in (("capacity", capacity), ("horizon", body.horizon_date),
                              ("slots", body.slots), ("day bounds", body.day_bounds))
               if v is not None]
    await record("planner", "settings updated", detail=", ".join(changed) or "no-op")
    return await _get_settings()


# --------------------------------------------------------------------------- #
# Budget: the funding cutline (spec §3)
#
# Supply is capacity × weeks-to-horizon. Walk the items in priority order and
# spend that supply top-down; whatever the supply does not reach is deferred.
# Nothing here is stored — funding is recomputed on every read, so reordering
# an item re-funds the whole list for free.
# --------------------------------------------------------------------------- #
def _weeks_to_horizon(horizon: date, today: date | None = None) -> float:
    return max(0.0, (horizon - (today or date.today())).days / 7.0)


def _funding_pass(items: list[dict], settings: dict,
                  today: date | None = None) -> dict:
    """items MUST already be in priority order. Returns the full budget view."""
    horizon = _sdate(settings["horizon_date"]) or _default_horizon(today)
    weeks = _weeks_to_horizon(horizon, today)
    supply = settings["capacity_per_week"] * weeks
    horizon_label = horizon.strftime("%b %Y")

    remaining = supply
    per_item: dict[str, dict] = {}
    fully = partial = deferred = 0
    for it in items:
        total = float(it.get("total_hours") or 0)
        funded = max(0.0, min(remaining, total))
        remaining -= funded
        if funded >= total and total > 0:
            chip, state = f"fits by {horizon_label}", "funded"
            fully += 1
        elif funded > 0:
            chip, state = "partial", "partial"
            partial += 1
        else:
            chip, state = "deferred", "deferred"
            deferred += 1
        per_item[it["id"]] = {
            "funded_hours": round(funded, 2),
            "total_hours": round(total, 2),
            "funding_chip": chip,
            "funding_state": state,
        }

    return {
        "capacity_per_week": settings["capacity_per_week"],
        "horizon_date": horizon.isoformat(),
        "weeks_to_horizon": round(weeks, 1),
        "supply_hours": round(supply, 2),
        "used_hours": round(supply - remaining, 2),
        "remaining_hours": round(remaining, 2),
        "summary": {"funded": fully, "partial": partial, "deferred": deferred},
        "items": per_item,
    }


async def _plannable_items() -> list[dict]:
    """Items that compete for supply, in priority order (done/dropped are out)."""
    rows = await run_read(
        "MATCH (p:PlanItem) WHERE p.status IN ['active', 'queued'] "
        "RETURN p{.*} AS p ORDER BY p.priority")
    return [r["p"] for r in rows]


@router.get("/budget")
async def get_budget() -> dict:
    settings = await _get_settings()
    items = await _plannable_items()
    budget = _funding_pass(items, settings)
    budget["rows"] = [
        {"id": i["id"], "name": i["name"], "category": i.get("category") or "study",
         "priority": i.get("priority"), "marker": i.get("marker") or "none",
         "placement": i.get("placement") or "auto",
         "day_pref": i.get("day_pref") or "any",
         "hours_low": i.get("hours_low"), "hours_high": i.get("hours_high"),
         "hours_per_week": i.get("hours_per_week") or 0,
         "status": i.get("status"), **budget["items"][i["id"]]}
        for i in items
    ]
    return budget


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
@router.get("/items")
async def list_items(status: str | None = None) -> list[dict]:
    where = "WHERE p.status = $status" if status else ""
    rows = await run_read(
        f"MATCH (p:PlanItem) {where} RETURN p{{.*}} AS p ORDER BY p.priority",
        status=status,
    )
    items = [r["p"] for r in rows]
    sess = await _sessions_by_item([i["id"] for i in items]) if items else {}
    prev = await _last_report_finishes()
    # funding always walks the full plannable list in priority order, not the
    # filtered view, so a status filter cannot silently move the cutline
    funding = _funding_pass(await _plannable_items(), await _get_settings())["items"]
    out = []
    for i in items:
        d = _derived(i, sess.get(i["id"], []))
        d["drift_days"] = _drift_days(d["projected_finish_velocity"], prev.get(i["id"]))
        d["session_count"] = len(sess.get(i["id"], []))
        out.append({**i, **d, **funding.get(i["id"], {})})
    return out


@router.post("/items", status_code=201)
async def create_item(body: PlanItemCreate) -> dict:
    pid = str(uuid.uuid4())
    rows = await run_read("MATCH (p:PlanItem) RETURN coalesce(max(p.priority), -1) AS m")
    start = (body.start_date or date.today()).isoformat()
    low, high, total = _estimate(body.hours_low, body.hours_high, body.total_hours)
    # category drives the default: study/build/paper are scheduled for you,
    # fixed/fitness/event are placed by hand (spec §2)
    placement = body.placement or (
        "auto" if body.category in AUTO_CATEGORIES else "manual")
    await run_write(
        """
        CREATE (p:PlanItem {
            id: $id, name: $name, description: $description, module: $module,
            category: $category, placement: $placement, marker: $marker,
            total_hours: $total_hours, hours_low: $hours_low,
            hours_high: $hours_high, reasoning: $reasoning, day_pref: $day_pref,
            hours_per_week: $hours_per_week, start_date: $start_date, priority: $priority, status: 'active',
            created_at: $now, completed_at: null
        })
        """,
        id=pid, name=body.name.strip(), description=body.description,
        module=body.module, category=body.category, placement=placement,
        marker=body.marker, total_hours=total, hours_low=low, hours_high=high,
        reasoning=body.reasoning.strip(), day_pref=body.day_pref,
        hours_per_week=body.hours_per_week, start_date=start,
        priority=int(rows[0]["m"]) + 1, now=_now(),
    )
    await record("planner", "item created", detail=body.name[:70], entity_id=pid)
    item = await _item_or_404(pid)
    return {**item, **_derived(item, [])}


@router.patch("/items/{item_id}")
async def update_item(item_id: str, patch: PlanItemUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if "start_date" in fields:
        fields["start_date"] = fields["start_date"].isoformat()
    est = {"hours_low", "hours_high", "total_hours"} & patch.model_fields_set
    if est:
        # an explicit null clears a range end; anything not sent keeps its
        # stored value, and the result is validated as a whole
        cur = await _item_or_404(item_id)
        pick = lambda k: getattr(patch, k) if k in est else cur.get(k)
        total = pick("total_hours")
        if "total_hours" not in est and pick("hours_low") is not None \
                and pick("hours_high") is not None:
            total = None                    # range changed alone → re-centre
        low, high, total = _estimate(pick("hours_low"), pick("hours_high"), total)
        fields.update(hours_low=low, hours_high=high, total_hours=total)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"p.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (p:PlanItem {{id: $id}}) SET {sets} RETURN p{{.*}} AS p",
        id=item_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "plan item not found")
    await record("planner", "item updated",
                 detail=", ".join(fields), entity_id=item_id)
    item = rows[0]["p"]
    sess = (await _sessions_by_item([item_id])).get(item_id, [])
    return {**item, **_derived(item, sess)}


@router.post("/items/reorder")
async def reorder_items(body: PlanReorder) -> dict:
    for pos, pid in enumerate(body.ids):
        await run_write(
            "MATCH (p:PlanItem {id: $id}) SET p.priority = $pos", id=pid, pos=pos)
    await record("planner", "items reordered", detail=f"{len(body.ids)} items")
    return {"ok": True}


@router.post("/items/{item_id}/complete")
async def complete_item(item_id: str, body: PlanCompleteBody) -> dict:
    item = await _item_or_404(item_id)
    await run_write(
        "MATCH (p:PlanItem {id: $id}) SET p.status = 'done', p.completed_at = $now",
        id=item_id, now=_now(),
    )
    # the single conclusion note (spec: session_close origin pattern)
    if body.note.strip():
        await run_write(
            """
            MATCH (p:PlanItem {id: $id})
            CREATE (n:PlanNote {id: $nid, text: $text, created_at: $now,
                                origin: 'session_close'})-[:ON]->(p)
            """,
            id=item_id, nid=str(uuid.uuid4()), text=body.note.strip(), now=_now(),
        )
    await record("planner", "item completed", detail=item["name"][:70], entity_id=item_id)
    return await _item_or_404(item_id)


@router.delete("/items/{item_id}")
async def delete_item(item_id: str) -> dict:
    item = await _item_or_404(item_id)
    rows = await run_read(
        "MATCH (:Session)-[:FOR]->(p:PlanItem {id: $id}) RETURN count(*) AS n", id=item_id)
    if rows and rows[0]["n"] > 0:
        # never hard-delete a worked item — sessions stay queryable
        await run_write(
            "MATCH (p:PlanItem {id: $id}) SET p.status = 'dropped'", id=item_id)
        await record("planner", "item dropped", detail=item["name"][:70], entity_id=item_id)
        return {"deleted": False, "dropped": True}
    await run_write(
        """
        MATCH (p:PlanItem {id: $id})
        OPTIONAL MATCH (n:PlanNote)-[:ON]->(p)
        DETACH DELETE n, p
        """,
        id=item_id,
    )
    await record("planner", "item deleted", detail=item["name"][:70], entity_id=item_id)
    return {"deleted": True, "dropped": False}


@router.get("/items/{item_id}")
async def get_item(item_id: str) -> dict:
    """Full detail for the Focus view: sessions, notes, links, sparkline."""
    item = await _item_or_404(item_id)
    sess = (await _sessions_by_item([item_id])).get(item_id, [])
    notes = await run_read(
        """
        MATCH (n:PlanNote)-[:ON]->(:PlanItem {id: $id})
        RETURN n{.*} AS n ORDER BY n.created_at DESC
        """,
        id=item_id,
    )
    links = await run_read(
        """
        MATCH (p:PlanItem {id: $id})
        OPTIONAL MATCH (p)-[:REALISED_BY]->(t:Task)
        OPTIONAL MATCH (p)-[:LINKS_TO]->(pa:Paper)
        OPTIONAL MATCH (p)-[:LINKS_TO]->(v:Video)
        RETURN collect(DISTINCT t{.id, .title, .done}) AS tasks,
               collect(DISTINCT pa{.id, .title}) AS papers,
               collect(DISTINCT v{.id, .title}) AS videos
        """,
        id=item_id,
    )
    d = _derived(item, sess)
    prev = await _last_report_finishes()
    d["drift_days"] = _drift_days(d["projected_finish_velocity"], prev.get(item_id))
    # 12-week sparkline of logged hours, oldest → newest, current week last
    cur_ws = _week_start(date.today())
    spark = [
        {"week_start": (cur_ws - timedelta(weeks=k)).isoformat(),
         "hours": round(_hours_in_week(sess, cur_ws - timedelta(weeks=k)), 2)}
        for k in range(11, -1, -1)
    ]
    lk = links[0] if links else {"tasks": [], "papers": [], "videos": []}
    return {
        **item, **d,
        "sessions": sorted(sess, key=lambda s: s.get("start") or "", reverse=True),
        "notes": [r["n"] for r in notes],
        "links": {
            "tasks": [t for t in lk["tasks"] if t and t.get("id")],
            "papers": [p for p in lk["papers"] if p and p.get("id")],
            "videos": [v for v in lk["videos"] if v and v.get("id")],
        },
        "sparkline": spark,
    }


# --------------------------------------------------------------------------- #
# Links — REALISED_BY tasks, LINKS_TO papers/videos (never duplicated data)
# --------------------------------------------------------------------------- #
_LINK = {
    "task": ("Task", "REALISED_BY"),
    "paper": ("Paper", "LINKS_TO"),
    "video": ("Video", "LINKS_TO"),
}


@router.post("/items/{item_id}/links", status_code=201)
async def add_link(item_id: str, body: PlanLinkCreate) -> dict:
    await _item_or_404(item_id)
    label, rel = _LINK[body.kind]
    rows = await run_write(
        f"""
        MATCH (p:PlanItem {{id: $id}}), (t:{label} {{id: $tid}})
        MERGE (p)-[:{rel}]->(t)
        RETURN t.title AS title
        """,
        id=item_id, tid=body.target_id,
    )
    if not rows:
        raise HTTPException(404, f"{body.kind} not found")
    await record("planner", "link added", detail=f"{body.kind}: {rows[0]['title'] or ''}"[:70],
                 entity_id=item_id)
    return {"ok": True}


@router.delete("/items/{item_id}/links/{kind}/{target_id}", status_code=204,
               response_class=Response)
async def remove_link(item_id: str, kind: str, target_id: str) -> Response:
    if kind not in _LINK:
        raise HTTPException(400, "kind must be task, paper or video")
    label, rel = _LINK[kind]
    await run_write(
        f"MATCH (:PlanItem {{id: $id}})-[r:{rel}]->(:{label} {{id: $tid}}) DELETE r",
        id=item_id, tid=target_id,
    )
    await record("planner", "link removed", detail=kind, entity_id=item_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Sessions — timer with the single-open-session rule, plus manual entry
# --------------------------------------------------------------------------- #
@router.get("/focus")
async def get_focus() -> dict:
    rows = await run_read(
        """
        MATCH (s:Session)-[:FOR]->(p:PlanItem) WHERE s.end IS NULL
        RETURN s{.*} AS session, p{.id, .name, .module} AS item LIMIT 1
        """
    )
    if not rows:
        return {"session": None, "item": None}
    return {"session": rows[0]["session"], "item": rows[0]["item"]}


@router.post("/focus/{item_id}/start")
async def start_focus(item_id: str) -> dict:
    item = await _item_or_404(item_id)
    closed = await _close_open_session()          # switching = one action
    sid = str(uuid.uuid4())
    await run_write(
        """
        MATCH (p:PlanItem {id: $pid})
        CREATE (s:Session {id: $id, start: $now, end: null, minutes: null,
                           source: 'timer', note: ''})-[:FOR]->(p)
        """,
        pid=item_id, id=sid, now=_now(),
    )
    await record("planner", "focus started", detail=item["name"][:70], entity_id=item_id)
    return {
        "session": {"id": sid, "start": _now(), "source": "timer"},
        "item": {"id": item["id"], "name": item["name"], "module": item.get("module")},
        "closed_previous": closed["session"] if closed else None,
    }


@router.post("/focus/stop")
async def stop_focus(body: PlanFocusStop) -> dict:
    closed = await _close_open_session(note=body.note.strip())
    if not closed:
        return {"session": None}
    await record("planner", "focus stopped",
                 detail=f"{closed['item_name']} · {closed['session'].get('minutes')}m"[:70],
                 entity_id=closed["item_id"])
    return {"session": closed["session"], "item_id": closed["item_id"]}


@router.post("/items/{item_id}/sessions", status_code=201)
async def add_manual_session(item_id: str, body: PlanSessionManual) -> dict:
    item = await _item_or_404(item_id)
    if body.minutes <= 0:
        raise HTTPException(400, "minutes must be positive")
    sid = str(uuid.uuid4())
    start = body.start.astimezone(timezone.utc)
    await run_write(
        """
        MATCH (p:PlanItem {id: $pid})
        CREATE (s:Session {id: $id, start: $start, end: $end, minutes: $minutes,
                           source: 'manual', note: $note})-[:FOR]->(p)
        """,
        pid=item_id, id=sid, start=start.isoformat(),
        end=(start + timedelta(minutes=body.minutes)).isoformat(),
        minutes=body.minutes, note=body.note,
    )
    await record("planner", "session logged",
                 detail=f"{item['name']} · {body.minutes}m"[:70], entity_id=item_id)
    rows = await run_read("MATCH (s:Session {id: $id}) RETURN s{.*} AS s", id=sid)
    return rows[0]["s"]


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, patch: PlanSessionUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"s.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (s:Session {{id: $id}}) SET {sets} RETURN s{{.*}} AS s",
        id=session_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "session not found")
    await record("planner", "session edited", detail=", ".join(fields), entity_id=session_id)
    return rows[0]["s"]


@router.delete("/sessions/{session_id}", status_code=204, response_class=Response)
async def delete_session(session_id: str) -> Response:
    await run_write("MATCH (s:Session {id: $id}) DETACH DELETE s", id=session_id)
    await record("planner", "session deleted", detail=session_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Notes — quick capture; no [:ON] relationship = inbox
# --------------------------------------------------------------------------- #
@router.post("/notes", status_code=201)
async def create_note(body: PlanNoteCreate) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "note needs text")
    nid = str(uuid.uuid4())
    if body.item_id:
        await _item_or_404(body.item_id)
        await run_write(
            """
            MATCH (p:PlanItem {id: $pid})
            CREATE (n:PlanNote {id: $id, text: $text, created_at: $now,
                                origin: $origin})-[:ON]->(p)
            """,
            pid=body.item_id, id=nid, text=body.text.strip(), now=_now(), origin=body.origin,
        )
    else:
        await run_write(
            "CREATE (:PlanNote {id: $id, text: $text, created_at: $now, origin: $origin})",
            id=nid, text=body.text.strip(), now=_now(), origin=body.origin,
        )
    await record("planner", "note added",
                 detail=body.text[:70], entity_id=body.item_id or nid)
    return {"id": nid, "text": body.text.strip(), "origin": body.origin,
            "item_id": body.item_id, "inbox": body.item_id is None}


@router.get("/notes/inbox")
async def inbox_notes() -> list[dict]:
    rows = await run_read(
        """
        MATCH (n:PlanNote) WHERE NOT (n)-[:ON]->(:PlanItem)
        RETURN n{.*} AS n ORDER BY n.created_at DESC
        """
    )
    return [r["n"] for r in rows]


@router.post("/notes/{note_id}/attach/{item_id}")
async def attach_note(note_id: str, item_id: str) -> dict:
    await _item_or_404(item_id)
    rows = await run_write(
        """
        MATCH (n:PlanNote {id: $nid}), (p:PlanItem {id: $pid})
        OPTIONAL MATCH (n)-[old:ON]->(:PlanItem)
        DELETE old
        MERGE (n)-[:ON]->(p)
        RETURN n{.*} AS n
        """,
        nid=note_id, pid=item_id,
    )
    if not rows:
        raise HTTPException(404, "note not found")
    await record("planner", "note attached", detail=note_id, entity_id=item_id)
    return rows[0]["n"]


@router.delete("/notes/{note_id}", status_code=204, response_class=Response)
async def delete_note(note_id: str) -> Response:
    await run_write("MATCH (n:PlanNote {id: $id}) DETACH DELETE n", id=note_id)
    await record("planner", "note deleted", detail=note_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Calendar surface (spec §4, §5)
#
# Two kinds of block share one grid:
#   · stored   — :CalEvent rows, hand-placed in the composer or synced from an
#                external calendar. These own their time absolutely.
#   · auto     — study/build/paper work, COMPUTED here on every read from the
#                funded budget + slot template + day blocks. Never stored, so
#                it can never disagree with the Budget view.
# --------------------------------------------------------------------------- #
def _dt(d: date, minutes: int) -> datetime:
    return datetime.combine(d, time(minutes // 60, minutes % 60))


def _pdt(v: object) -> datetime | None:
    """Parse a stored ISO datetime string (naive local, as written)."""
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def _blocked_days(lo: date, hi: date) -> dict[str, str]:
    rows = await run_read(
        "MATCH (d:DayBlock) WHERE d.date >= $lo AND d.date <= $hi RETURN d{.*} AS d",
        lo=lo.isoformat(), hi=hi.isoformat(),
    )
    return {r["d"]["date"]: r["d"].get("reason") or "" for r in rows}


async def _stored_events(lo: date, hi: date) -> list[dict]:
    """Manual + external events overlapping [lo, hi]. Hidden ones stay hidden.

    ISO-8601 strings sort lexicographically, so a string range scan on
    e.start is a correct (and index-backed) overlap test here.
    """
    rows = await run_read(
        """
        MATCH (e:CalEvent)
        WHERE e.start < $hi AND e.end > $lo AND coalesce(e.hidden, false) = false
        RETURN e{.*} AS e ORDER BY e.start
        """,
        lo=lo.isoformat(), hi=(hi + timedelta(days=1)).isoformat(),
    )
    return [r["e"] for r in rows]


def _free_segments(win_start: datetime, win_end: datetime,
                   busy: list[tuple[datetime, datetime]]) -> list[list[datetime]]:
    """The slot window with every busy interval punched out of it."""
    segs = [[win_start, win_end]]
    for b0, b1 in busy:
        nxt: list[list[datetime]] = []
        for s0, s1 in segs:
            if b1 <= s0 or b0 >= s1:          # no overlap
                nxt.append([s0, s1])
                continue
            if b0 > s0:
                nxt.append([s0, min(b0, s1)])
            if b1 < s1:
                nxt.append([max(b1, s0), s1])
        segs = nxt
    return [s for s in segs
            if (s[1] - s[0]).total_seconds() / 60 >= MIN_BLOCK_MIN]


def _auto_blocks_for_week(items: list[dict], funding: dict, settings: dict,
                          week_start: date, blocked: dict[str, str],
                          stored: list[dict]) -> list[dict]:
    """Deterministic priority-ordered fill of one week's open slots (spec §4).

    Same inputs always yield the same blocks — nothing here reads a clock or a
    stored placement, which is what lets these be recomputed rather than saved.
    """
    slots = []
    for s in settings["slots"]:
        d = week_start + timedelta(days=s["dow"])
        if d.isoformat() in blocked:          # a blocked day offers no slots
            continue
        st = _dt(d, _hhmm(s["start"]))
        slots.append((st, st + timedelta(minutes=s["length_min"])))

    # manual/external events win their time before any auto work is placed
    busy = []
    for e in stored:
        a, b = _pdt(e.get("start")), _pdt(e.get("end"))
        if a and b and b > a:
            busy.append((a, b))
    free = [_free_segments(a, b, busy) for a, b in slots]
    # day_pref filters which slots an item may use. A weekend item whose hours
    # don't fit Sat–Sun stays short rather than spilling into the week.
    weekend = [a.weekday() >= 5 for a, _ in slots]
    allow = {"any": lambda w: True, "weekday": lambda w: not w,
             "weekend": lambda w: w}

    blocks: list[dict] = []
    for it in items:
        if (it.get("placement") or "auto") != "auto" or it.get("status") != "active":
            continue
        need = int(round(float(it.get("hours_per_week") or 0) * 60))
        # an unfunded item is below the cutline: it gets no calendar time
        if need <= 0 or funding.get(it["id"], {}).get("funded_hours", 0) <= 0:
            continue
        ok = allow.get(it.get("day_pref") or "any", allow["any"])
        for segs, wknd in zip(free, weekend):
            if need <= 0:
                break
            if not ok(wknd):
                continue
            k = 0
            while k < len(segs) and need > 0:
                s0, s1 = segs[k]
                avail = int((s1 - s0).total_seconds() // 60)
                if avail < MIN_BLOCK_MIN:
                    k += 1
                    continue
                take = min(avail, need)
                end = s0 + timedelta(minutes=take)
                blocks.append({
                    "id": f"auto:{it['id']}:{s0.isoformat(timespec='minutes')}",
                    "title": it["name"],
                    "start": s0.isoformat(timespec="minutes"),
                    "end": end.isoformat(timespec="minutes"),
                    "category": it.get("category") or "study",
                    "marker": it.get("marker") or "none",
                    "source": "auto",
                    "item_id": it["id"],
                    "minutes": take,
                })
                need -= take
                segs[k] = [end, s1]
    return blocks


async def _calendar_payload(view: str, anchor: date) -> dict:
    if view == "day":
        lo = hi = anchor
        month_lo = month_hi = anchor
    elif view == "month":
        month_lo = anchor.replace(day=1)
        nxt = (month_lo + timedelta(days=32)).replace(day=1)
        month_hi = nxt - timedelta(days=1)
        lo = _week_start(month_lo)                       # Monday-first grid
        hi = _week_start(month_hi) + timedelta(days=6)
    else:                                                # week
        lo = _week_start(anchor)
        hi = lo + timedelta(days=6)
        month_lo, month_hi = lo, hi

    settings = await _get_settings()
    items = await _plannable_items()
    funding = _funding_pass(items, settings)["items"]
    blocked = await _blocked_days(lo, hi)
    stored = await _stored_events(lo, hi)

    auto: list[dict] = []
    ws = _week_start(lo)
    while ws <= hi:
        week_stored = [
            e for e in stored
            if (a := _pdt(e.get("start"))) and ws <= a.date() <= ws + timedelta(days=6)
        ]
        auto += _auto_blocks_for_week(
            items, funding, settings, ws, blocked, week_stored)
        ws += timedelta(days=7)
    auto = [b for b in auto if lo <= date.fromisoformat(b["start"][:10]) <= hi]

    events = [
        {"id": e["id"], "title": e.get("title") or "",
         "start": e.get("start"), "end": e.get("end"),
         "category": e.get("category") or "event",
         "marker": e.get("marker") or "none",
         "source": e.get("source") or "manual",
         "external_id": e.get("external_id"),
         "item_id": e.get("item_id"),
         "minutes": int(((_pdt(e.get("end")) or _pdt(e.get("start")) or datetime.now())
                         - (_pdt(e.get("start")) or datetime.now())).total_seconds() // 60)}
        for e in stored
    ] + auto
    events.sort(key=lambda e: e["start"] or "")

    # Snapshot panel (spec §5): what the visible range actually holds
    span_weeks = ((hi - lo).days + 1) / 7.0
    placed = sum(e["minutes"] for e in events
                 if e["category"] in AUTO_CATEGORIES) / 60.0
    return {
        "view": view,
        "date": anchor.isoformat(),
        "range_start": lo.isoformat(),
        "range_end": hi.isoformat(),
        "month_start": month_lo.isoformat(),
        "month_end": month_hi.isoformat(),
        "day_bounds": settings["day_bounds"],
        "events": events,
        "blocked": blocked,
        "snapshot": {
            "hours_placed": round(placed, 2),
            "capacity_target": round(settings["capacity_per_week"] * span_weeks, 2),
            "days_blocked": len(blocked),
            "priority_count": sum(1 for e in events if e["marker"] == "priority"),
            "important_count": sum(1 for e in events if e["marker"] == "important"),
        },
    }


@router.get("/calendar")
async def get_calendar(view: str = "week",
                       date_: str | None = Query(None, alias="date")) -> dict:
    if view not in ("day", "week", "month"):
        raise HTTPException(400, "view must be day, week or month")
    try:
        anchor = date.fromisoformat(date_) if date_ else date.today()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD") from None
    return await _calendar_payload(view, anchor)


# --------------------------------------------------------------------------- #
# Hand-placed events — the only calendar blocks that are stored rows
# --------------------------------------------------------------------------- #
@router.post("/events", status_code=201)
async def create_event(body: PlanEventCreate) -> dict:
    if body.end <= body.start:
        raise HTTPException(400, "event must end after it starts")
    if body.item_id:
        await _item_or_404(body.item_id)
    eid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (e:CalEvent {
            id: $id, title: $title, start: $start, end: $end,
            category: $category, marker: $marker, source: 'manual',
            external_id: null, item_id: $item_id, hidden: false,
            created_at: $now
        })
        """,
        id=eid, title=body.title.strip(), category=body.category,
        marker=body.marker, item_id=body.item_id, now=_now(),
        start=body.start.replace(tzinfo=None).isoformat(timespec="minutes"),
        end=body.end.replace(tzinfo=None).isoformat(timespec="minutes"),
    )
    if body.item_id:
        await run_write(
            """
            MATCH (e:CalEvent {id: $eid}), (p:PlanItem {id: $pid})
            MERGE (e)-[:REALISES]->(p)
            """,
            eid=eid, pid=body.item_id,
        )
    await record("planner", "event placed", detail=body.title[:70], entity_id=eid)
    rows = await run_read("MATCH (e:CalEvent {id: $id}) RETURN e{.*} AS e", id=eid)
    return rows[0]["e"]


@router.patch("/events/{event_id}")
async def update_event(event_id: str, patch: PlanEventUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    for k in ("start", "end"):
        if k in fields:
            fields[k] = fields[k].replace(tzinfo=None).isoformat(timespec="minutes")
    rows = await run_read(
        "MATCH (e:CalEvent {id: $id}) RETURN e{.*} AS e", id=event_id)
    if not rows:
        raise HTTPException(404, "event not found")
    merged = {**rows[0]["e"], **fields}
    if (merged.get("end") or "") <= (merged.get("start") or ""):
        raise HTTPException(400, "event must end after it starts")
    sets = ", ".join(f"e.{k} = ${k}" for k in fields)
    out = await run_write(
        f"MATCH (e:CalEvent {{id: $id}}) SET {sets} RETURN e{{.*}} AS e",
        id=event_id, **fields,
    )
    await record("planner", "event updated", detail=", ".join(fields), entity_id=event_id)
    return out[0]["e"]


@router.delete("/events/{event_id}")
async def delete_event(event_id: str) -> dict:
    rows = await run_read(
        "MATCH (e:CalEvent {id: $id}) RETURN e{.*} AS e", id=event_id)
    if not rows:
        raise HTTPException(404, "event not found")
    if (rows[0]["e"].get("source") or "manual") == "external":
        # an external event is the remote calendar's row, not ours to destroy —
        # hide it locally and let the next sync decide (spec §9)
        await run_write(
            "MATCH (e:CalEvent {id: $id}) SET e.hidden = true", id=event_id)
        await record("planner", "external event hidden", entity_id=event_id)
        return {"deleted": False, "hidden": True}
    await run_write("MATCH (e:CalEvent {id: $id}) DETACH DELETE e", id=event_id)
    await record("planner", "event deleted",
                 detail=(rows[0]["e"].get("title") or "")[:70], entity_id=event_id)
    return {"deleted": True, "hidden": False}


# --------------------------------------------------------------------------- #
# Day block-off — distinct from per-item scheduling: it removes the day's
# slots from auto-placement entirely (spec §4). v2 does NOT carry the lost
# work forward; that needs the reflow engine in §9.
# --------------------------------------------------------------------------- #
def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD") from None


@router.post("/dayblocks/{day}", status_code=201)
async def block_day(day: str, body: PlanDayBlockCreate) -> dict:
    d = _parse_day(day)
    await run_write(
        "MERGE (b:DayBlock {date: $d}) SET b.reason = $reason",
        d=d.isoformat(), reason=body.reason.strip(),
    )
    await record("planner", "day blocked off", detail=d.isoformat())
    return {"date": d.isoformat(), "reason": body.reason.strip(), "blocked": True}


@router.delete("/dayblocks/{day}")
async def unblock_day(day: str) -> dict:
    d = _parse_day(day)
    await run_write("MATCH (b:DayBlock {date: $d}) DELETE b", d=d.isoformat())
    await record("planner", "day un-blocked", detail=d.isoformat())
    return {"date": d.isoformat(), "blocked": False}


# --------------------------------------------------------------------------- #
# Week deficits — the contract the future reflow engine (spec §9) consumes
# --------------------------------------------------------------------------- #
@router.get("/week")
async def week_deficits(date_: str | None = Query(None, alias="date")) -> dict:
    """Per active item: budget, logged and deficit for the week containing
    `date` (default today). The contract the future calendar module consumes."""
    try:
        d = date.fromisoformat(date_) if date_ else date.today()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    ws = _week_start(d)
    rows = await run_read(
        "MATCH (p:PlanItem {status: 'active'}) RETURN p{.*} AS p ORDER BY p.priority")
    items = [r["p"] for r in rows]
    sess = await _sessions_by_item([i["id"] for i in items]) if items else {}
    out = []
    for i in items:
        logged = _hours_in_week(sess.get(i["id"], []), ws)
        hpw = i.get("hours_per_week") or 0
        out.append({
            "id": i["id"], "name": i["name"], "priority": i.get("priority"),
            "hours_per_week": hpw, "hours_this_week": round(logged, 2),
            "deficit_this_week": round(max(0.0, hpw - logged), 2),
        })
    return {"week_start": ws.isoformat(), "items": out}


# --------------------------------------------------------------------------- #
# Weekly reports — frozen JSON payloads, same rule as Decomposition snapshots
# --------------------------------------------------------------------------- #
async def _generate_report() -> dict:
    """Generate (idempotent per week_start) the report for the current week."""
    ws = _week_start(date.today())
    existing = await run_read(
        "MATCH (r:WeeklyReport {week_start: $ws}) RETURN r{.*} AS r", ws=ws.isoformat())
    if existing:
        return existing[0]["r"]

    rows = await run_read(
        "MATCH (p:PlanItem) WHERE p.status IN ['active', 'queued'] "
        "RETURN p{.*} AS p ORDER BY p.priority")
    items = [r["p"] for r in rows]
    sess = await _sessions_by_item([i["id"] for i in items]) if items else {}
    prev = await _last_report_finishes(before_week=ws)

    payload_items, total_logged, total_budget = [], 0.0, 0.0
    week_notes = []
    for i in items:
        s = sess.get(i["id"], [])
        d = _derived(i, s)
        logged = _hours_in_week(s, ws)
        total_logged += logged
        total_budget += i.get("hours_per_week") or 0
        payload_items.append({
            "id": i["id"], "name": i["name"],
            "budget": i.get("hours_per_week"), "logged": round(logged, 2),
            "velocity": d["velocity"],
            "projected_finish_budget": d["projected_finish_budget"],
            "projected_finish_velocity": d["projected_finish_velocity"],
            "drift_days": _drift_days(d["projected_finish_velocity"], prev.get(i["id"])),
        })
        notes = await run_read(
            """
            MATCH (n:PlanNote)-[:ON]->(:PlanItem {id: $id})
            WHERE n.created_at >= $lo AND n.created_at <= $hi
            RETURN n{.*} AS n ORDER BY n.created_at
            """,
            id=i["id"], lo=ws.isoformat(),
            hi=(ws + timedelta(days=6)).isoformat() + "￿",
        )
        week_notes += [{"item": i["name"], "text": r["n"]["text"],
                        "created_at": r["n"]["created_at"]} for r in notes]

    payload = {
        "week_start": ws.isoformat(),
        "capacity": await _get_capacity(),
        "items": payload_items,
        "totals": {"budget": round(total_budget, 2), "logged": round(total_logged, 2)},
        "notes": week_notes,
    }
    rid = str(uuid.uuid4())
    now = _now()
    await run_write(
        """
        CREATE (:WeeklyReport {id: $id, week_start: $ws, generated_at: $now,
                               payload: $payload})
        """,
        id=rid, ws=ws.isoformat(), now=now, payload=json.dumps(payload),
    )
    await record("planner", "weekly report generated", detail=ws.isoformat(), entity_id=rid)
    return {"id": rid, "week_start": ws.isoformat(), "generated_at": now,
            "payload": json.dumps(payload)}


@router.get("/reports")
async def list_reports() -> list[dict]:
    rows = await run_read(
        "MATCH (r:WeeklyReport) RETURN r{.id, .week_start, .generated_at} AS r "
        "ORDER BY r.week_start DESC")
    return [r["r"] for r in rows]


@router.get("/reports/{report_id}")
async def get_report(report_id: str) -> dict:
    rows = await run_read(
        "MATCH (r:WeeklyReport {id: $id}) RETURN r{.*} AS r", id=report_id)
    if not rows:
        raise HTTPException(404, "report not found")
    r = rows[0]["r"]
    try:
        r["payload"] = json.loads(r["payload"])
    except (TypeError, ValueError):
        r["payload"] = {}
    return r


@router.post("/reports/generate", status_code=201)
async def generate_report() -> dict:
    r = await _generate_report()
    try:
        r["payload"] = json.loads(r["payload"])
    except (TypeError, ValueError):
        pass
    return r


# --------------------------------------------------------------------------- #
# Snapshot — feeds the home screen bar
# --------------------------------------------------------------------------- #
@router.get("/snapshot")
async def planner_snapshot(range: str = "weekly") -> dict:
    if range not in ("daily", "weekly", "monthly"):
        raise HTTPException(400, "range must be daily, weekly or monthly")
    today = date.today()
    if range == "daily":
        lo, hi = today, today
    elif range == "monthly":
        lo, hi = today.replace(day=1), today
    else:
        lo = _week_start(today)
        hi = lo + timedelta(days=6)

    rows = await run_read(
        "MATCH (p:PlanItem {status: 'active'}) RETURN p{.*} AS p")
    items = [r["p"] for r in rows]
    sess = await _sessions_by_item([i["id"] for i in items]) if items else {}
    prev = await _last_report_finishes()

    logged = 0.0
    budget = 0.0
    on_track, drifting = 0, 0
    days = (hi - lo).days + 1
    for i in items:
        s = sess.get(i["id"], [])
        logged += sum(
            (x.get("minutes") or 0)
            for x in s
            if (d := _sdate(x.get("start"))) and lo <= d <= hi
        ) / 60.0
        budget += (i.get("hours_per_week") or 0) * days / 7.0
        d = _derived(i, s)
        drift = _drift_days(d["projected_finish_velocity"], prev.get(i["id"]))
        if drift is not None and drift > 7:
            drifting += 1
        else:
            on_track += 1

    focus = await get_focus()
    return {
        "range": range,
        "hours_logged": round(logged, 2),
        "hours_budget": round(budget, 2),
        "items_on_track": on_track,
        "items_drifting": drifting,
        "focus_item": focus["item"]["name"] if focus["item"] else None,
    }


# --------------------------------------------------------------------------- #
# Scheduler — Friday 16:00 weekly report, checked every 10 minutes
# --------------------------------------------------------------------------- #
async def _report_scheduler() -> None:
    while True:
        try:
            now = datetime.now()
            if now.weekday() == 4 and now.time() >= time(16, 0):
                await _generate_report()          # idempotent per week_start
        except Exception:                          # noqa: BLE001 — keep the loop alive
            log.exception("planner report scheduler tick failed")
        await asyncio.sleep(600)


def start_scheduler() -> asyncio.Task:
    return asyncio.create_task(_report_scheduler())
