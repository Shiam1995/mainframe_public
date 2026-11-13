"""/api/activity/heatmap — data for the GitHub-style contribution grid.

A day square carries three independent signals:

  colour  — how much WORK was logged that day (sum of :WorkSession minutes).
            More time → darker.
  border  — at least one session that day was on a project flagged
            `contributes` ("add to the contributions").
  star    — at least one session that day was a push.

Raw :ChangeEvent counts (every mutation the app writes) are still returned as
`counts`, but they no longer drive the colour — they're shown in the tooltip so
the app-activity history isn't lost. Manual per-day colour overrides live as
:HeatCell nodes and still win over everything.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from db import run_read, run_write
from models import HeatCellUpdate
from routes.work import day_summary

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("/heatmap")
async def heatmap(days: int = 371) -> dict:
    """Per-day counts. `days <= 0` means all history — the week/month/year zoom
    levels of the contribution grid span further back than a single year."""
    params: dict = {}
    window = ""
    if days > 0:
        params["since"] = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        window = "WHERE l.ts >= $since"
    count_rows = await run_read(
        f"""
        MATCH (l:ChangeEvent)
        {window}
        RETURN substring(l.ts, 0, 10) AS day, count(*) AS n
        """,
        **params,
    )
    counts = {r["day"]: r["n"] for r in count_rows if r["day"]}
    override_rows = await run_read("MATCH (c:HeatCell) RETURN c.date AS date, c.color AS color")
    overrides = {r["date"]: r["color"] for r in override_rows if r["color"]}
    days = await day_summary()
    return {
        "counts": counts,     # raw app mutations — tooltip only, no longer the colour
        "days": days,         # {date: {mins, sessions, pushed, contributed, modules}}
        "overrides": overrides,
        # earliest day we hold anything for — the left edge of the scrollable range
        "first": min([*counts, *overrides, *days], default=None),
        "today": datetime.now(timezone.utc).date().isoformat(),
    }


@router.post("/heatmap/cell")
async def set_cell(body: HeatCellUpdate) -> dict:
    if body.color:
        await run_write(
            "MERGE (c:HeatCell {date: $date}) SET c.color = $color",
            date=body.date, color=body.color,
        )
        return {"date": body.date, "color": body.color}
    # empty colour → clear the override
    await run_write("MATCH (c:HeatCell {date: $date}) DELETE c", date=body.date)
    return {"date": body.date, "color": None}
