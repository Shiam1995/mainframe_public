"""/api/wallpapers — the home screen's slideshow source.

Mainframe-level rather than home-specific: the boot screen already looks for
wallpapers, and any module could want the same pool later.

The listing rebuilds the cache on demand. That's a no-op for files already
sized, so hitting this endpoint is how newly-dropped images appear — no restart,
no rescan button needed (though `/rescan?force=1` exists to re-encode
everything, e.g. after changing the size or quality setting).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

import wallpapers as wp

router = APIRouter(prefix="/api/wallpapers", tags=["wallpapers"])


@router.get("")
async def list_wallpapers() -> dict:
    return await asyncio.to_thread(wp.ensure_cache, False)


@router.post("/rescan")
async def rescan(force: bool = False) -> dict:
    return await asyncio.to_thread(wp.ensure_cache, force)
