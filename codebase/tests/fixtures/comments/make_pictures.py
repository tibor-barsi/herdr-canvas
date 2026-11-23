"""Write the large test pictures (no Pillow needed): ``make_pictures.py OUTDIR``.

``photo-4000x3000.png`` is a horizontal gray ramp. ``huge-10000x6000.png`` (60
megapixels, over the viewer's 50 megapixel limit) and ``edge-8000x6000.png`` (48
megapixels, under it) are 1-bit stripes, so every file stays small.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def gray_png(width: int, height: int, depth: int) -> bytes:
    """Return a gray PNG of ``depth`` 8 or 1 whose rows all repeat one pattern."""
    if depth == 8:
        row = bytes(x * 255 // (width - 1) for x in range(width))
    else:
        row = bytes((0xF0 if (i // 4) % 2 else 0x0F) for i in range((width + 7) // 8))
    raw = (b"\x00" + row) * height
    header = struct.pack(">IIBBBBB", width, height, depth, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def main(out: Path) -> None:
    """Write the pictures into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "photo-4000x3000.png").write_bytes(gray_png(4000, 3000, 8))
    (out / "huge-10000x6000.png").write_bytes(gray_png(10000, 6000, 1))
    (out / "edge-8000x6000.png").write_bytes(gray_png(8000, 6000, 1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
