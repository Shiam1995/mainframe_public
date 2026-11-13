"""The barcode scanner: does a photographed packet come back as the right digits?

Two things are worth pinning down. The decoder must read a barcode out of an
image that looks like a photo rather than a clean render — rotated, padded,
JPEG-mangled — and `variants()` must expand a decoded GTIN into every spelling
the catalogue holds it under, or a product that is demonstrably there is missed.
"""
import io

import pytest

import barcodescan

pytestmark = pytest.mark.skipif(not barcodescan.available(),
                                reason="zxing-cpp not installed")


def _photo(code: str, fmt: str = "EAN13") -> bytes:
    """A rendered barcode roughed up to resemble something a camera produced."""
    import numpy as np
    import zxingcpp
    from PIL import Image, ImageOps

    bc = zxingcpp.create_barcode(code, getattr(zxingcpp.BarcodeFormat, fmt))
    img = Image.fromarray(np.array(zxingcpp.write_barcode_to_image(bc, scale=4),
                                   copy=False)).convert("L")
    img = ImageOps.expand(img, border=90, fill=255)      # quiet zone + packaging
    img = img.rotate(-6, expand=True, fillcolor=255)     # held at an angle
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)                    # camera compression
    return buf.getvalue()


def test_reads_a_rotated_compressed_photo():
    found = barcodescan.decode(_photo("4006381333931"))
    assert [f["code"] for f in found] == ["4006381333931"]
    assert found[0]["format"] == "EAN-13"


def test_a_photo_of_nothing_is_not_an_error():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (400, 300), 200).save(buf, "JPEG")
    assert barcodescan.decode(buf.getvalue()) == []


def test_variants_cover_the_paddings_the_catalogue_uses():
    # Open Food Facts pads to 13, USDA Branded keeps 12 or 14 — one product,
    # three spellings, and a scan hands over whichever the label carries.
    v = barcodescan.variants("012345678905")
    assert "012345678905" in v and "0012345678905" in v and "00012345678905" in v


def test_upce_is_expanded_to_upca():
    # The canonical GS1 example: 04252614 compresses 042100005264.
    assert "042100005264" in barcodescan.variants("04252614")


def test_junk_in_no_codes_out():
    assert barcodescan.variants("") == []
    assert barcodescan.variants("no digits here") == []
