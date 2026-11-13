"""/api/vault/recurring and /api/reminders — money that repeats, and nudges.

Two features that turn out to be one: a subscription you forget to cancel and a
date you forget to act on fail the same way. So a :Recurring carries the rule
("£9.99 on the 1st, monthly") and the app derives the nudge from it, rather
than asking you to keep a separate list of dates in your head.

The important distinction: a :Recurring is a **commitment**, not a payment.
Marking it paid mints a real :Transaction and rolls `next_due` forward, so the
transaction ledger remains the only record of what actually left the account.
A one-off (`cadence: "once"`) simply goes inactive instead of rolling.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (RecurringCreate, RecurringPay, RecurringUpdate,
                    ReminderCreate, ReminderUpdate, TransactionCreate)
from routes.vault import _create_tx

router = APIRouter(tags=["recurring"])

CADENCES = {"once", "weekly", "fortnightly", "4weekly", "monthly", "quarterly", "yearly"}
LIVE_STATUSES = {"active", "trial"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    return datetime.now().date()


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat((d or "")[:10])
    except ValueError:
        return None


def advance(d: date, cadence: str, anchor_day: int | None = None) -> date:
    """The next due date after `d`.

    Month arithmetic clamps to the end of the month, so a subscription billed
    on the 31st lands on the 28th in February instead of skipping a month.

    `anchor_day` is the day it's *really* billed on, and it matters: clamping
    from the previous date alone is a one-way ratchet — 31 Jan → 28 Feb → 28
    Mar → 28 Apr, and the subscription silently moves three days earlier
    forever. Anchored, it recovers: 31 Jan → 28 Feb → 31 Mar → 30 Apr.
    """
    if cadence == "weekly":
        return d + timedelta(days=7)
    if cadence == "fortnightly":
        return d + timedelta(days=14)
    if cadence == "4weekly":
        return d + timedelta(days=28)
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(cadence)
    if not months:
        return d
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    day = anchor_day or d.day
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def first_due_from_start(start: str, cadence: str) -> str:
    """No renewal date given: the first billing on or after today, counted on
    from the start date. A one-off just ends on its start date."""
    d = _parse(start)
    if not d:
        return ""
    if cadence == "once":
        return d.isoformat()
    d, guard, anchor = advance(d, cadence, d.day), 0, d.day
    while d < _today() and guard < 600:
        d, guard = advance(d, cadence, anchor), guard + 1
    return d.isoformat()


def _shape(node: dict) -> dict:
    r = dict(node)
    due = _parse(r.get("next_due"))
    r["days_until"] = (due - _today()).days if due else None
    r["overdue"] = bool(due and due < _today() and r.get("active", True))
    return r


# --------------------------------------------------------------------------- #
# Recurring payments
# --------------------------------------------------------------------------- #
@router.get("/api/vault/recurring")
async def list_recurring(include_inactive: bool = True) -> list[dict]:
    cypher = "MATCH (r:Recurring)"
    if not include_inactive:
        cypher += " WHERE r.active"
    cypher += " RETURN r ORDER BY r.active DESC, coalesce(r.next_due, '9999') ASC"
    return [_shape(row["r"]) for row in await run_read(cypher)]


@router.get("/api/vault/recurring/summary")
async def recurring_summary() -> dict:
    """What these commitments cost per month and per year, plus what's due soon.

    Cadences are normalised to a monthly figure so a yearly domain renewal and
    a weekly coffee subscription can be compared honestly.
    """
    rows = [_shape(r["r"]) for r in await run_read("MATCH (r:Recurring) RETURN r")]
    live = [r for r in rows if r.get("active", True)]
    per_month = {"weekly": 52 / 12, "fortnightly": 26 / 12, "4weekly": 13 / 12, "monthly": 1,
                 "quarterly": 1 / 3, "yearly": 1 / 12, "once": 0}
    monthly = sum((r.get("amount") or 0) * per_month.get(r.get("cadence"), 0) for r in live)
    soon = sorted(
        (r for r in live if r["days_until"] is not None and r["days_until"] <= 30),
        key=lambda r: r["days_until"])
    return {
        "count": len(live),
        "monthly": round(monthly, 2),
        "yearly": round(monthly * 12, 2),
        "due_soon": soon[:12],
        "overdue": [r for r in live if r["overdue"]],
        "one_offs": [r for r in live if r.get("cadence") == "once"],
    }


@router.post("/api/vault/recurring", status_code=201)
async def create_recurring(body: RecurringCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "give it a name")
    rid = str(uuid.uuid4())
    props = body.model_dump()
    props.update(name=body.name.strip(), amount=float(props["amount"]),
                 remind_days_before=int(props["remind_days_before"]))
    # A status other than the default is the subscriptions tab speaking: it
    # decides whether this is live. Otherwise `active` stands as sent.
    if "status" in body.model_fields_set:
        props["active"] = props["status"] in LIVE_STATUSES
    elif not props["active"]:
        props["status"] = "paused"
    if not props["next_due"] and props["start"]:
        props["next_due"] = first_due_from_start(props["start"], props["cadence"])
    due = _parse(props["next_due"])
    props.update(id=rid, anchor_day=due.day if due else 0, created_at=_now(),
                 paid_count=0, last_paid="")
    rows = await run_write("CREATE (r:Recurring) SET r = $props RETURN r", props=props)
    await record("transaction", "recurring added", detail=body.name[:70],
                 module="vault", entity_id=rid)
    return _shape(rows[0]["r"])


@router.patch("/api/vault/recurring/{rid}")
async def update_recurring(rid: str, patch: RecurringUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "status" in fields:
        fields["active"] = fields["status"] in LIVE_STATUSES
    elif "active" in fields:
        # Toggled from the Recurring strip — keep the subscriptions tab's
        # status in step (a trial switched back on is just active).
        fields["status"] = "active" if fields["active"] else "paused"
    if fields.get("next_due") == "" and fields.get("start"):
        fields["next_due"] = first_due_from_start(
            fields["start"], fields.get("cadence") or "monthly")
    # Setting the due date by hand says "this is the day it bills" — re-anchor,
    # or the next roll-forward would snap back to the old day.
    if "next_due" in fields:
        moved = _parse(fields["next_due"])
        if moved:
            fields["anchor_day"] = moved.day
    sets = ", ".join(f"r.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (r:Recurring {{id: $id}}) SET {sets} RETURN r", id=rid, **fields)
    if not rows:
        raise HTTPException(404, "not found")
    await record("transaction", "recurring updated", detail=", ".join(fields),
                 module="vault", entity_id=rid)
    return _shape(rows[0]["r"])


@router.delete("/api/vault/recurring/{rid}", status_code=204, response_class=Response)
async def delete_recurring(rid: str) -> Response:
    await run_write("MATCH (r:Recurring {id: $id}) DETACH DELETE r", id=rid)
    await record("transaction", "recurring deleted", detail=rid, module="vault")
    return Response(status_code=204)


@router.post("/api/vault/recurring/{rid}/pay", status_code=201)
async def pay_recurring(rid: str, body: RecurringPay) -> dict:
    """Record that it went out: a real transaction, then roll the date forward."""
    rows = await run_read("MATCH (r:Recurring {id: $id}) RETURN r", id=rid)
    if not rows:
        raise HTTPException(404, "not found")
    r = dict(rows[0]["r"])

    when = body.date or r.get("next_due") or _today().isoformat()
    amount = body.amount if body.amount is not None else (r.get("amount") or 0)
    tid = await _create_tx(TransactionCreate(
        date=when,
        description=r.get("name", "recurring payment"),
        amount=float(amount),
        type="expense",
        category=r.get("category") or "Subscriptions",
        account_id=r.get("account_id"),
        notes=(body.note or r.get("notes") or ""),
        tags=["recurring"],
    ))

    due = _parse(when) or _today()
    cadence = r.get("cadence") or "monthly"
    if cadence == "once":
        # A one-off has done its job; keep it for the record, but stop nagging.
        await run_write(
            "MATCH (r:Recurring {id: $id}) SET r.active = false, r.next_due = '', "
            "r.last_paid = $when, r.paid_count = coalesce(r.paid_count, 0) + 1",
            id=rid, when=when)
    else:
        await run_write(
            "MATCH (r:Recurring {id: $id}) SET r.next_due = $next, r.last_paid = $when, "
            "r.paid_count = coalesce(r.paid_count, 0) + 1",
            id=rid,
            next=advance(due, cadence, int(r.get('anchor_day') or 0) or None).isoformat(),
            when=when)

    await record("transaction", "recurring paid",
                 detail=f"{r.get('name', '')[:40]} · {amount}", module="vault",
                 entity_id=rid)
    out = await run_read("MATCH (r:Recurring {id: $id}) RETURN r", id=rid)
    return {"transaction_id": tid, "recurring": _shape(out[0]["r"])}


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #
@router.get("/api/reminders")
async def list_reminders(include_done: bool = False) -> list[dict]:
    cypher = "MATCH (r:Reminder)"
    if not include_done:
        cypher += " WHERE NOT coalesce(r.done, false)"
    cypher += " RETURN r ORDER BY r.due ASC"
    out = []
    for row in await run_read(cypher):
        r = dict(row["r"])
        due = _parse(r.get("due"))
        r["days_until"] = (due - _today()).days if due else None
        out.append(r)
    return out


@router.get("/api/reminders/due")
async def due_now() -> dict:
    """What to show when the app opens: reminders that have landed, plus the
    payments about to leave. Deliberately one call — the on-open panel should
    never be the reason the app feels slow."""
    today = _today()
    reminders = [r for r in await list_reminders() if r["days_until"] is not None
                 and r["days_until"] <= 0]
    payments = []
    for r in [_shape(x["r"]) for x in await run_read("MATCH (r:Recurring) RETURN r")]:
        if not r.get("active", True) or r["days_until"] is None:
            continue
        if r["days_until"] <= int(r.get("remind_days_before") or 0):
            payments.append(r)
    payments.sort(key=lambda r: r["days_until"])
    return {"date": today.isoformat(), "reminders": reminders, "payments": payments,
            "total": len(reminders) + len(payments)}


@router.post("/api/reminders", status_code=201)
async def create_reminder(body: ReminderCreate) -> dict:
    if not body.message.strip():
        raise HTTPException(400, "what should the reminder say?")
    if not _parse(body.due):
        raise HTTPException(400, "give it a due date (YYYY-MM-DD)")
    rid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (r:Reminder {
            id: $id, message: $message, due: $due, done: false,
            ref_kind: $ref_kind, ref_id: $ref_id, ref_title: $ref_title,
            repeat: $repeat, created_at: $now
        })
        RETURN r
        """,
        id=rid, message=body.message.strip(), due=body.due[:10],
        ref_kind=body.ref_kind, ref_id=body.ref_id, ref_title=body.ref_title,
        repeat=body.repeat, now=_now(),
    )
    await record("reminder", "set", detail=body.message[:70], entity_id=rid)
    return dict(rows[0]["r"])


@router.patch("/api/reminders/{rid}")
async def update_reminder(rid: str, patch: ReminderUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")

    # Completing a repeating reminder doesn't end it — it moves it on.
    if fields.get("done"):
        rows = await run_read("MATCH (r:Reminder {id: $id}) RETURN r", id=rid)
        if rows:
            cur = dict(rows[0]["r"])
            repeat = cur.get("repeat") or "once"
            due = _parse(cur.get("due"))
            if repeat != "once" and due:
                fields["done"] = False
                fields["due"] = advance(due, repeat).isoformat()

    sets = ", ".join(f"r.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (r:Reminder {{id: $id}}) SET {sets} RETURN r", id=rid, **fields)
    if not rows:
        raise HTTPException(404, "not found")
    await record("reminder", "updated", detail=", ".join(fields), entity_id=rid)
    return dict(rows[0]["r"])


@router.delete("/api/reminders/{rid}", status_code=204, response_class=Response)
async def delete_reminder(rid: str) -> Response:
    await run_write("MATCH (r:Reminder {id: $id}) DETACH DELETE r", id=rid)
    await record("reminder", "deleted", detail=rid)
    return Response(status_code=204)
