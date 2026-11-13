"""Wallpaper cache — turns a folder of full-size images into web-sized copies.

You drop images into `settings.wallpapers_source` (any depth). This module
mirrors each one into `settings.wallpapers_cache`, scaled so its long edge is at
most `wallpaper_max_px` and re-encoded as JPEG. A 2.9 MB desktop wallpaper comes
out around 200 KB, which matters when the home screen cycles through 30+ of them.

Two rules make it safe to re-run constantly:

  · **Originals are never touched.** Source files are only ever opened for read.
  · **The cache name carries a fingerprint** of the source path + mtime + size,
    so an unchanged file is skipped, an edited file gets a new name (and so
    beats browser caching for free), and a deleted source drops out on sweep.

Animated GIFs are copied through as-is rather than resized — flattening one to a
still frame would silently break the thing that makes it worth having.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from config import settings

log = logging.getLogger("mainframe.wallpapers")

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
# Folders inside the source tree that aren't wallpapers.
SKIP_DIRS = {"video", "videos", "sounds", "audio"}


def fingerprint(src: Path) -> str:
    st = src.stat()
    raw = f"{src}|{int(st.st_mtime)}|{st.st_size}".encode()
    return hashlib.sha1(raw).hexdigest()[:10]


def _slug(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in name.lower()]
    return "".join(keep).strip("-")[:48] or "wallpaper"


def _sources() -> list[Path]:
    root = settings.wallpapers_source
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        if any(part.lower() in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        out.append(p)
    return out


def is_animated(path: Path) -> bool:
    if path.suffix.lower() != ".gif":
        return False
    try:
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except (OSError, UnidentifiedImageError):
        return False


def build_web_copy(src: Path, dest: Path, max_px: int, quality: int) -> tuple[int, int] | None:
    """Write a web-sized copy of `src`. Returns (width, height), or None if unreadable.

    Shared with the module-card cache — same rules (originals read-only, animated
    GIFs copied rather than flattened, alpha composited onto the app background),
    only the target size and quality differ.
    """
    if is_animated(src):
        shutil.copy2(src, dest)
        try:
            with Image.open(dest) as im:
                return im.size
        except (OSError, UnidentifiedImageError):
            return None
    try:
        with Image.open(src) as im:
            # EXIF-rotated phone photos would otherwise come out sideways.
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            # Backgrounds sit on a dark page and never need alpha; flattening
            # onto the app's own background keeps transparent PNGs from turning
            # into black boxes.
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                flat = Image.new("RGB", im.size, (11, 15, 20))
                flat.paste(im, mask=im.split()[-1])
                im = flat
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
            return im.size
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        log.warning("image skipped (unreadable): %s — %s", src.name, exc)
        return None


def ensure_cache(force: bool = False) -> dict:
    """Sync cache → source. Cheap when nothing changed; safe to call often.

    Blocking (Pillow is CPU-bound) — call it via `asyncio.to_thread`.
    """
    cache = settings.wallpapers_cache
    cache.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    keep: set[str] = set()
    built = skipped = failed = 0

    for src in _sources():
        ext = ".gif" if is_animated(src) else ".jpg"
        name = f"{_slug(src.stem)}-{fingerprint(src)}{ext}"
        dest = cache / name
        keep.add(name)

        if force or not dest.exists():
            size = build_web_copy(src, dest, settings.wallpaper_max_px,
                                  settings.wallpaper_quality)
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

        items.append({
            "name": src.stem,
            "file": name,
            "url": f"/wallpaper-files/{name}",
            "width": w,
            "height": h,
            "bytes": dest.stat().st_size,
        })

    # Sweep copies whose source is gone or changed, so the cache can't grow
    # without bound as the folder is edited.
    removed = 0
    for stale in cache.iterdir():
        if stale.is_file() and stale.name not in keep:
            stale.unlink(missing_ok=True)
            removed += 1

    items.sort(key=lambda i: i["name"].lower())
    log.info("wallpapers: %d built, %d cached, %d failed, %d removed",
             built, skipped, failed, removed)
    return {"count": len(items), "built": built, "cached": skipped,
            "failed": failed, "removed": removed,
            "source": str(settings.wallpapers_source), "images": items}
