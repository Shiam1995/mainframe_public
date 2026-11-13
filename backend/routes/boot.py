"""/api/synapse/boot — data for the CRT boot screen (UPDATE_SPEC #9).

The boot screen is a pure-frontend animation; this endpoint feeds it the *real*
things it displays: live system checks and optional wallpaper/sound assets the user has dropped into
~/.mainframe/synapse/{wallpapers,sounds}/. Preferences (skip/mute) live in the
existing settings.yaml under a `boot:` section.
"""
from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter

import llm
from config import CONFIG_FILE, settings
from db import run_read, verify_connectivity

router = APIRouter(prefix="/api/synapse/boot", tags=["boot"])
log = logging.getLogger("synapse.boot")

# What we'll serve back as a browser-loadable asset URL, by extension.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}


def _first_asset(directory, exts: set[str], url_prefix: str) -> str | None:
    """Return a served URL for the first matching file in `directory`, or None."""
    try:
        if not directory.exists():
            return None
        for p in sorted(directory.iterdir()):
            if p.is_file() and p.suffix.lower() in exts:
                return f"{url_prefix}/{p.name}"
    except Exception as exc:  # noqa: BLE001
        log.warning("boot asset scan failed for %s: %s", directory, exc)
    return None


def _boot_prefs() -> dict:
    """Read the `boot:` section of settings.yaml (skip / mute). Never crashes."""
    prefs = {"skip": False, "mute": False}
    try:
        if CONFIG_FILE.exists():
            data = yaml.safe_load(CONFIG_FILE.read_text()) or {}
            section = data.get("boot") or {}
            if isinstance(section, dict):
                prefs["skip"] = bool(section.get("skip", False))
                prefs["mute"] = bool(section.get("mute", False))
    except Exception:  # noqa: BLE001
        pass
    return prefs


@router.get("/config")
async def boot_config() -> dict:
    """Everything the boot screen needs in one call."""
    neo4j_ok = await verify_connectivity()
    llm_status = await llm.status()
    checks = [
        {"label": "neo4j graph store", "path": settings.neo4j_uri, "ok": neo4j_ok},
        {
            "label": "local llm",
            "path": f"{llm_status.get('provider', '?')} · {llm_status.get('ollama_model', '')}".strip(" ·"),
            "ok": llm_status.get("effective") in ("ollama", "heuristic"),
        },
        {"label": "modules", "path": "synapse · pulse · vision · vault", "ok": True},
        {"label": "store", "path": str(settings.papers_originals.parent), "ok": True},
    ]
    # The food catalogue is permanent reference data, so the boot screen states
    # whether it's actually mounted — an empty catalogue should be visible, not
    # something you discover mid-meal.
    try:
        import foodcatalog
        n = await foodcatalog.count()
        checks.append({"label": "food catalogue",
                       "path": f"usda · open food facts · cofid — {n:,} foods" if n
                               else "not imported",
                       "ok": n > 0})
    except Exception:
        checks.append({"label": "food catalogue", "path": "unavailable", "ok": False})
    return {
        "app": settings.app_name,
        "checks": checks,
        "wallpaper": _first_asset(settings.boot_wallpapers, _IMAGE_EXTS, "/boot-assets/wallpapers"),
        "sound": _first_asset(settings.boot_sounds, _AUDIO_EXTS, "/boot-assets/sounds"),
        "prefs": _boot_prefs(),
    }
