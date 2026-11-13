"""/api/log — the activity log (read + export).

Writes happen everywhere via activity.record(); this route reads them back,
filters by category, groups by day, and exports JSON.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import settings
from db import run_read

router = APIRouter(prefix="/api/log", tags=["log"])


@router.get("")
async def get_log(
    category: str | None = None,
    module: str | None = None,
    trigger: str | None = None,
    limit: int = 500,
) -> list[dict]:
    clauses = []
    params: dict = {"limit": limit}
    if category:
        clauses.append("l.category = $category")
        params["category"] = category
    if module:
        clauses.append("l.module = $module")
        params["module"] = module
    if trigger:
        clauses.append("l.trigger = $trigger")
        params["trigger"] = trigger
    cypher = "MATCH (l:ChangeEvent)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    cypher += " RETURN l ORDER BY l.ts DESC LIMIT $limit"
    rows = await run_read(cypher, **params)
    return [dict(r["l"]) for r in rows]


@router.get("/by-day")
async def get_log_by_day(
    category: str | None = None,
    module: str | None = None,
    trigger: str | None = None,
    limit: int = 1000,
) -> dict:
    """Group entries by calendar day for the timeline view."""
    entries = await get_log(
        category=category, module=module, trigger=trigger, limit=limit
    )
    grouped: dict[str, list] = defaultdict(list)
    for e in entries:
        day = (e.get("ts") or "")[:10] or "unknown"
        grouped[day].append(e)
    return dict(grouped)


@router.get("/categories")
async def categories() -> list[dict]:
    rows = await run_read(
        "MATCH (l:ChangeEvent) RETURN l.category AS category, count(*) AS n ORDER BY n DESC"
    )
    return rows


@router.get("/facets")
async def facets() -> dict:
    """Distinct values + counts for every filter dimension (for UI dropdowns)."""
    cats = await run_read(
        "MATCH (l:ChangeEvent) RETURN l.category AS value, count(*) AS n ORDER BY n DESC"
    )
    mods = await run_read(
        "MATCH (l:ChangeEvent) RETURN coalesce(l.module,'synapse') AS value, count(*) AS n ORDER BY n DESC"
    )
    trigs = await run_read(
        "MATCH (l:ChangeEvent) RETURN coalesce(l.trigger,'manual') AS value, count(*) AS n ORDER BY n DESC"
    )
    return {"category": cats, "module": mods, "trigger": trigs}


@router.get("/export")
async def export_log() -> JSONResponse:
    """Export the full log as JSON (also written to ~/.mainframe/exports)."""
    entries = await get_log(limit=100000)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = settings.exports_dir / f"activity-log-{stamp}.json"
    out_path.write_text(json.dumps(entries, indent=2))
    return JSONResponse(
        {"count": len(entries), "saved_to": str(out_path), "entries": entries}
    )
