"""Build brief 25, B3 (decision 8): docs/demo.png, the README's picture of `sr serve --demo` (the invented sample
tasks), taken by a clean headless Chrome over its DevTools protocol at 1440 x 900, twice the pixels. A plain PNG: only the
image's own chunks, no text or metadata chunk that could carry a name, a path or a date."""
import struct
from pathlib import Path

PNG = Path(__file__).resolve().parent.parent / "docs" / "demo.png"
IMAGE_ONLY = {"IHDR", "IDAT", "IEND", "PLTE", "sRGB", "gAMA", "cHRM", "pHYs"}


def _chunks(data):
    i, found = 8, []
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        found.append((data[i + 4:i + 8].decode("latin-1"), data[i + 8:i + 8 + n]))
        i += 12 + n
    return found


def test_the_screenshot_is_a_plain_png_of_the_page():
    data = PNG.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = _chunks(data)
    width, height = struct.unpack(">II", chunks[0][1][:8])
    assert chunks[0][0] == "IHDR" and (width, height) == (2880, 1800)
    assert {kind for kind, _ in chunks} <= IMAGE_ONLY
