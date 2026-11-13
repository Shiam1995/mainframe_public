"""/api/gratitude — the Gratitude tab (from the gratitude design mock-up).

    (:Gratitude {id, text, period, date, time, created_at})
        period  year | month | week | day — which table the row was written in
        date    YYYY-MM-DD the row belongs to; a period table shows the rows
                whose date falls inside the year / month / week / day on screen
        time    HH:MM, day rows only
    (:Excited {id, text, when, enjoyed, enjoyed_at, created_at})
        `when` is a YYYY-MM-DD picked from the calendar (or blank); the list is
        sorted soonest first. Ticking it stamps `enjoyed_at`; the stamp is the
        date it happened, so it is set here, never typed.

ONE NODE PER ROW, so the random banner can draw from every period at once and
nothing has to parse a blob of text.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from activity import record
from db import run_read, run_write

router = APIRouter(prefix="/api/gratitude", tags=["gratitude"])

PERIODS = ("year", "month", "week", "day")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounds(period: str, anchor: date) -> tuple[date, date]:
    """Inclusive [start, end] of the period that contains `anchor`.
    Weeks start on Monday, like the Phases sprint weeks."""
    if period == "year":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    if period == "month":
        nxt = date(anchor.year + (anchor.month == 12), anchor.month % 12 + 1, 1)
        return date(anchor.year, anchor.month, 1), nxt - timedelta(days=1)
    if period == "week":
        mon = anchor - timedelta(days=anchor.weekday())
        return mon, mon + timedelta(days=6)
    return anchor, anchor


async def _week_label(mon: date) -> str:
    """'w2 · 2 nov' — the week number inside whichever phase covers this
    week, or just the Monday when no phase does."""
    rows = await run_read(
        """
        MATCH (p:Phase) WHERE p.start <= $d AND p.end >= $d
        RETURN p.start AS start ORDER BY p.status = 'active' DESC, p.start DESC LIMIT 1
        """, d=mon.isoformat())
    day = f"{mon.day} {mon.strftime('%b').lower()}"
    if rows and rows[0].get("start"):
        start = date.fromisoformat(str(rows[0]["start"])[:10])
        return f"w{(mon - start).days // 7 + 1} · {day}"
    return f"w/c {day}"


def _parse(d: str | None) -> date:
    if not d:
        return date.today()
    try:
        return date.fromisoformat(d[:10])
    except ValueError as exc:
        raise HTTPException(400, f"bad date {d!r}") from exc


# ── period tables ───────────────────────────────────────────────


@router.get("/period/{period}")
async def period_rows(period: str, at: str | None = None) -> dict:
    """The rows of one period table, for the period containing `at`
    (default today), plus the label and the anchors either side."""
    if period not in PERIODS:
        raise HTTPException(400, "period is year, month, week or day")
    anchor = _parse(at)
    start, end = _bounds(period, anchor)
    rows = await run_read(
        """
        MATCH (g:Gratitude {period: $period})
        WHERE g.date >= $s AND g.date <= $e
        RETURN g{.*} AS g ORDER BY g.date, coalesce(g.time, ''), g.created_at
        """, period=period, s=start.isoformat(), e=end.isoformat())
    if period == "year":
        label = str(start.year)
    elif period == "month":
        label = start.strftime("%b %Y").lower()
    elif period == "week":
        label = await _week_label(start)
    else:
        label = start.strftime("%a ").lower() + f"{start.day} {start.strftime('%b').lower()}"
    return {
        "period": period, "label": label,
        "start": start.isoformat(), "end": end.isoformat(),
        "prev": (start - timedelta(days=1)).isoformat(),
        "next": (end + timedelta(days=1)).isoformat(),
        "is_current": start <= date.today() <= end,
        "rows": [r["g"] for r in rows],
    }


class GratitudeCreate(BaseModel):
    period: str
    text: str = ""
    date: str | None = None
    time: str | None = None


class GratitudeUpdate(BaseModel):
    text: str | None = None
    date: str | None = None
    time: str | None = None


@router.post("", status_code=201)
async def add_gratitude(body: GratitudeCreate) -> dict:
    if body.period not in PERIODS:
        raise HTTPException(400, "period is year, month, week or day")
    d = _parse(body.date).isoformat()
    t = (body.time or "") if body.period == "day" else ""
    gid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (g:Gratitude {id: $id, text: $text, period: $period, date: $date,
                             time: $time, created_at: $now})
        RETURN g{.*} AS g
        """, id=gid, text=(body.text or "").strip(), period=body.period,
        date=d, time=t, now=_now())
    if body.text and body.text.strip():
        await record("gratitude", "grateful for", detail=body.text.strip()[:70],
                     entity_id=gid, module="mainframe")
    return rows[0]["g"]


@router.patch("/{gid}")
async def update_gratitude(gid: str, patch: GratitudeUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if "text" in fields:
        fields["text"] = fields["text"].strip()
    if "date" in fields:
        fields["date"] = _parse(fields["date"]).isoformat()
    if not fields:
        raise HTTPException(400, "nothing to update")
    sets = ", ".join(f"g.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (g:Gratitude {{id: $id}}) SET {sets} RETURN g{{.*}} AS g",
        id=gid, **fields)
    if not rows:
        raise HTTPException(404, "no such gratitude row")
    return rows[0]["g"]


@router.delete("/{gid}", status_code=204, response_class=Response)
async def delete_gratitude(gid: str) -> Response:
    await run_write("MATCH (g:Gratitude {id: $id}) DETACH DELETE g", id=gid)
    return Response(status_code=204)


@router.get("/random")
async def random_gratitude() -> dict:
    """One row from any period, for the banner. Empty dict when there are none."""
    rows = await run_read(
        """
        MATCH (g:Gratitude) WHERE trim(coalesce(g.text, '')) <> ''
        WITH g ORDER BY rand() LIMIT 1
        RETURN g{.*} AS g
        """)
    return rows[0]["g"] if rows else {}


# ── excited for → enjoyed ───────────────────────────────────────


class ExcitedCreate(BaseModel):
    text: str
    when: str = ""


class ExcitedUpdate(BaseModel):
    text: str | None = None
    when: str | None = None
    enjoyed: bool | None = None


@router.get("/excited")
async def list_excited() -> dict:
    rows = await run_read(
        "MATCH (x:Excited) RETURN x{.*} AS x ORDER BY x.created_at")
    items = [r["x"] for r in rows]

    def soonest(x: dict) -> tuple:
        # Picked dates first, soonest first; undated (or old free-text) after.
        w = str(x.get("when") or "")
        dated = len(w) == 10 and w[4] == "-" and w[7] == "-"
        return (0, w) if dated else (1, x.get("created_at") or "")

    return {
        "excited": sorted([x for x in items if not x.get("enjoyed")], key=soonest),
        # Newest-enjoyed first: the list reads as what just happened.
        "enjoyed": sorted([x for x in items if x.get("enjoyed")],
                          key=lambda x: x.get("enjoyed_at") or "", reverse=True),
    }


@router.post("/excited", status_code=201)
async def add_excited(body: ExcitedCreate) -> dict:
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "excited for what?")
    xid = str(uuid.uuid4())
    rows = await run_write(
        """
        CREATE (x:Excited {id: $id, text: $text, when: $when, enjoyed: false,
                           enjoyed_at: '', created_at: $now})
        RETURN x{.*} AS x
        """, id=xid, text=text, when=(body.when or "").strip(), now=_now())
    return rows[0]["x"]


@router.patch("/excited/{xid}")
async def update_excited(xid: str, patch: ExcitedUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "nothing to update")
    # Ticking stamps the day it happened; unticking clears it.
    if fields.get("enjoyed") is True:
        fields["enjoyed_at"] = date.today().isoformat()
    elif fields.get("enjoyed") is False:
        fields["enjoyed_at"] = ""
    sets = ", ".join(f"x.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (x:Excited {{id: $id}}) SET {sets} RETURN x{{.*}} AS x",
        id=xid, **fields)
    if not rows:
        raise HTTPException(404, "no such row")
    x = rows[0]["x"]
    if fields.get("enjoyed"):
        await record("gratitude", "enjoyed", detail=x.get("text", "")[:70],
                     entity_id=xid, module="mainframe")
    return x


@router.delete("/excited/{xid}", status_code=204, response_class=Response)
async def delete_excited(xid: str) -> Response:
    await run_write("MATCH (x:Excited {id: $id}) DETACH DELETE x", id=xid)
    return Response(status_code=204)
