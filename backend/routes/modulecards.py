"""/api/module-cards — artwork for the home screen's module cards.

The listing rebuilds the cache on demand, which is a no-op for files already
sized. That's how a re-cropped or newly-dropped image appears: replace the file,
reload the page. `/rescan?force=1` re-encodes everything (e.g. after changing
`module_card_max_px`).

Which module a picture belongs to comes from its filename, so this route never
needs to know what the modules are — see modulecards.py.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

import modulecards as mc

router = APIRouter(prefix="/api/module-cards", tags=["module-cards"])


@router.get("")
async def list_module_cards() -> dict:
    return await asyncio.to_thread(mc.ensure_cache, False)


@router.post("/rescan")
async def rescan(force: bool = False) -> dict:
    return await asyncio.to_thread(mc.ensure_cache, force)
