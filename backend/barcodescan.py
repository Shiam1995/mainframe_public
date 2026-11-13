"""Read a barcode out of a photograph — the scanner the catalogue never had.

Why this exists
---------------
`:CatalogFood` already holds ~4.0M products carrying a barcode, 2.2M of them
Open Food Facts entries off British supermarket shelves. Until now the only way
to reach one of them by code was to *type thirteen digits*, which is exactly the
kind of thing a phone camera should be doing. Point it at the back of a bag of
crisps and the packet identifies itself.

Local-first, like everything else
---------------------------------
Decoding is `zxing-cpp` — a self-contained C++ wheel, no system libraries, no
network, no cloud vision API. The photo never leaves the machine: it is decoded
in memory and dropped. Nothing is written to disk unless the caller saves it.

Notes that cost time to discover
--------------------------------
  * **Phone photos carry EXIF orientation.** A packet photographed in portrait
    arrives rotated 90°, and while zxing will try rotations itself, honouring
    EXIF first is both faster and more reliable on a soft-focus frame.
  * **The same product has several legal spellings of its code.** A UK EAN-13 is
    stored by Open Food Facts zero-padded to 13; USDA Branded holds the same
    GTIN as 12 (UPC-A) or 14 (ITF-14/case code). So a decoded code is expanded
    into every equivalent form before the graph is asked — see `variants()`.
  * **UPC-E is a compressed UPC-A**, and zxing hands back the eight compressed
    digits. Nothing in the catalogue is stored that way, so it is expanded here.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger("synapse.barcodescan")

# Phone cameras produce 4000px frames; a barcode is legible far below that and
# the decode cost is quadratic in pixels. 1600 keeps a 40mm barcode at ~300px
# wide, which is comfortably more than the ~2px-per-module zxing wants.
MAX_EDGE = 1600


def available() -> bool:
    """False when the wheel isn't installed — the API says so rather than 500s."""
    try:
        import zxingcpp  # noqa: F401
        return True
    except Exception:
        return False


def _prepare(data: bytes):
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)          # portrait photos arrive rotated
    img = img.convert("L")                      # zxing reads luminance anyway
    if max(img.size) > MAX_EDGE:
        scale = MAX_EDGE / max(img.size)
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))), Image.LANCZOS)
    return img


def decode(data: bytes) -> list[dict]:
    """Every barcode found in one image, best-first. Empty list is normal —
    a frame that catches the packet mid-blur simply has nothing in it."""
    import zxingcpp

    img = _prepare(data)
    # Retail symbologies plus the two that turn up on outer packaging. Naming
    # them rather than scanning for all ~30 formats keeps a live camera loop at
    # a few tens of milliseconds a frame.
    formats = (zxingcpp.BarcodeFormat.AllRetail,
               zxingcpp.BarcodeFormat.ITF,
               zxingcpp.BarcodeFormat.Code128)
    found: list[dict] = []
    seen: set[str] = set()
    for opts in ({}, {"binarizer": zxingcpp.Binarizer.GlobalHistogram}):
        # Second pass only if the first found nothing: local-average binarising
        # is better on uneven lighting, global histogram on a flat glossy pack
        # where the whole frame is one exposure.
        if found:
            break
        try:
            results = zxingcpp.read_barcodes(img, formats=formats, **opts)
        except Exception as exc:                # a corrupt upload, not a miss
            log.warning("barcode decode failed: %s", exc)
            return []
        for r in results:
            text = (r.text or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            found.append({"code": text, "format": str(r.format), "valid": bool(r.valid)})
    return found


# --------------------------------------------------------------------------- #
# One product, several legal codes
# --------------------------------------------------------------------------- #
def _upce_to_upca(code: str) -> str | None:
    """Expand a compressed UPC-E to its full UPC-A. Returns None if it isn't one.

    The last digit of the six-digit payload decides where the squeezed-out zeros
    go — the standard GS1 expansion, unchanged since 1973."""
    c = code.zfill(8) if len(code) in (6, 7) else code
    if len(c) != 8 or not c.isdigit():
        return None
    number_system, body, check = c[0], c[1:7], c[7]
    if number_system not in ("0", "1"):
        return None
    d, last = body[:5], body[5]
    if last in ("0", "1", "2"):
        mfr, item = d[:2] + last + "00", "00" + d[2:5]
    elif last == "3":
        mfr, item = d[:3] + "00", "000" + d[3:5]
    elif last == "4":
        mfr, item = d[:4] + "0", "0000" + d[4]
    else:
        mfr, item = d, "0000" + last
    return f"{number_system}{mfr}{item}{check}"


def variants(code: str) -> list[str]:
    """Every spelling of a GTIN this catalogue might be holding, best-first.

    Open Food Facts pads to 13, USDA Branded stores 12 or 14, and both drop or
    keep leading zeros inconsistently. Asking for one form finds a product that
    is definitely there under another — this is the difference between a scan
    that works and a scan that shrugs."""
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if not digits:
        return []
    out: list[str] = []

    def add(v: str) -> None:
        if v and v not in out:
            out.append(v)

    add(digits)
    bare = digits.lstrip("0") or digits
    if len(bare) <= 12:                       # UPC-A/EAN-13/ITF-14 zero padding
        for width in (12, 13, 14):
            if len(bare) <= width:
                add(bare.zfill(width))
    add(bare)
    if len(digits) == 8:
        add(digits.zfill(13))                 # a genuine EAN-8, padded
        expanded = _upce_to_upca(digits)
        if expanded:
            add(expanded)
            add(expanded.zfill(13))
    return out
