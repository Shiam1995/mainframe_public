"""The assistant's face — cached at the sizes the UI actually uses.

Drop any image into `~/mAInframe/AI_assistant/` and it becomes the assistant's
avatar: the launcher button, and the icon beside each thing it says. Same shape
as the wallpaper and module-card caches — **the source file is only ever read**,
never modified, and the cached copies live under `~/.mainframe/`.

Why cache at all: the source is 1264×1264 and 252 KB, and it is drawn at 44px on
the launcher and 26px beside each reply. Serving the original would download a
quarter of a megabyte to paint a thumbnail, every reload — the same waste the
image system is already criticised for elsewhere in this app.

The cache filename carries a fingerprint of the source (path, mtime, size), so
replacing the picture produces a new name — which busts the browser cache for
free — and an unchanged file is skipped entirely.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger("synapse.avatar")

# The sizes the UI asks for. Retina-doubled, so a 44px button gets 88 real
# pixels and doesn't look soft on a high-DPI screen.
SIZES = {"launch": 128, "chip": 64}
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _paths():
    from config import settings
    return (Path(settings.assistant_avatar_source).expanduser(),
            Path(settings.assistant_avatar_cache).expanduser())


def source_file() -> Path | None:
    """The chosen picture. If several are present, the newest wins — so dropping
    a new one in replaces the old without deleting anything."""
    src, _cache = _paths()
    if not src.is_dir():
        return None
    files = [p for p in src.iterdir() if p.is_file() and p.suffix.lower() in EXTS]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _fingerprint(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:10]


def ensure_cache(force: bool = False) -> dict:
    """Build the cached sizes if needed. Cheap to call on every request."""
    src_file = source_file()
    _src_dir, cache = _paths()
    cache.mkdir(parents=True, exist_ok=True)
    if not src_file:
        return {"ok": False, "reason": "no image in the AI_assistant folder",
                "source_dir": str(_paths()[0])}

    fp = _fingerprint(src_file)
    out: dict[str, str] = {}
    try:
        from PIL import Image
    except ImportError:
        return {"ok": False, "reason": "Pillow not installed"}

    for key, px in SIZES.items():
        name = f"{key}-{fp}.png"
        dest = cache / name
        if force or not dest.is_file():
            with Image.open(src_file) as im:
                im = im.convert("RGBA")
                # Square-crop from the centre first: the avatar is drawn in a
                # circle, and a non-square source would otherwise be squashed.
                w, h = im.size
                side = min(w, h)
                im = im.crop(((w - side) // 2, (h - side) // 2,
                              (w + side) // 2, (h + side) // 2))
                im = im.resize((px, px), Image.LANCZOS)
                im.save(dest, "PNG", optimize=True)
            log.info("assistant avatar cached: %s", name)
        out[key] = f"/assistant-files/{name}"

    # Sweep older fingerprints so replacing the picture doesn't leave a pile.
    for old in cache.glob("*.png"):
        if fp not in old.name:
            old.unlink(missing_ok=True)

    return {"ok": True, "source": src_file.name, "sizes": out,
            "source_dir": str(_paths()[0])}
