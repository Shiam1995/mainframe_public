"""Module-card artwork — one image per module on the home screen.

You drop images into `settings.module_cards_source` named after the module key:
`synapse.jpg`, `pulse.jpeg`, `vision.png`, `vault.webp`. **The filename is the
wiring** — nothing here holds a list of modules, so adding a fifth module later
means adding a fifth file, not editing this file.

Same contract as the wallpaper cache, and it shares that resizer:

  · **Originals are never touched** — only ever opened for read.
  · **The cache name carries a fingerprint** of path + mtime + size, so an
    unchanged file is skipped, a re-cropped one gets a new name (which beats
    browser caching for free), and a deleted one is swept.

Cards are small and fixed-size, so these are cached much smaller than a
wallpaper — a 380 KB source comes out around 60 KB.
"""
from __future__ import annotations

import logging

from PIL import Image, UnidentifiedImageError

import wallpapers as wp
from config import settings

log = logging.getLogger("mainframe.modulecards")

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _key(stem: str) -> str:
    """Filename stem → module key. Tolerates `Synapse`, `synapse-2`, `PULSE `."""
    cleaned = "".join(c for c in stem.strip().lower() if c.isalnum() or c in "-_")
    return cleaned.split("-")[0].split("_")[0]


def ensure_cache(force: bool = False) -> dict:
    """Sync cache → source, returning {module_key: card}. Safe to call often.

    Blocking (Pillow is CPU-bound) — call it via `asyncio.to_thread`.
    """
    src_dir = settings.module_cards_source
    cache = settings.module_cards_cache
    cache.mkdir(parents=True, exist_ok=True)

    cards: dict[str, dict] = {}
    keep: set[str] = set()
    built = skipped = failed = 0

    sources = sorted(p for p in src_dir.glob("*")
                     if p.is_file() and p.suffix.lower() in EXTS) if src_dir.exists() else []

    for src in sources:
        key = _key(src.stem)
        if not key:
            continue
        if key in cards:
            # Two files claiming the same module: first wins, but say so rather
            # than silently picking one.
            log.warning("module-card: ignoring %s — '%s' already taken", src.name, key)
            continue

        animated = wp.is_animated(src)
        ext = ".gif" if animated else ".jpg"
        name = f"{key}-{wp.fingerprint(src)}{ext}"
        dest = cache / name
        keep.add(name)

        if force or not dest.exists():
            size = wp.build_web_copy(src, dest, settings.module_card_max_px,
                                     settings.module_card_quality)
            if size is None:
                failed += 1
                keep.discard(name)
                continue
            built += 1
            w, h = size
        else:
            skipped += 1
            try:
                with Image.open(dest) as im:
                    w, h = im.size
            except (OSError, UnidentifiedImageError):
                w = h = 0

        cards[key] = {
            "module": key,
            "file": name,
            "url": f"/module-card-files/{name}",
            "source": src.name,
            "width": w,
            "height": h,
            "bytes": dest.stat().st_size,
        }

    removed = 0
    for stale in cache.iterdir():
        if stale.is_file() and stale.name not in keep:
            stale.unlink(missing_ok=True)
            removed += 1

    log.info("module cards: %d built, %d cached, %d failed, %d removed",
             built, skipped, failed, removed)
    return {"count": len(cards), "built": built, "cached": skipped,
            "failed": failed, "removed": removed,
            "source": str(src_dir), "source_exists": src_dir.exists(),
            "cards": cards}
