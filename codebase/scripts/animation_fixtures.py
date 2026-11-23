"""
Write the animation fixtures: 20 PNG frames, a WebM and an MP4 (needs ffmpeg).

Frame ``i`` is a teal picture with a red bar from the left edge, ``8 * (i + 1)`` px
wide, so a pixel row tells which frame is on screen. The MP4 is only for early
check 19. Run: ``uv run python scripts/animation_fixtures.py``.
"""

from __future__ import annotations

import struct
import subprocess
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "animation"
WIDTH, HEIGHT, FRAMES, FPS = 160, 90, 20, 10
TEAL, RED = (42, 157, 143), (229, 72, 77)


def png(width: int, height: int, pixel) -> bytes:  # noqa: ANN001
    """Encode an RGB picture; ``pixel(x, y)`` gives the colour."""
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for index in range(FRAMES):
        bar = 8 * (index + 1)
        (OUT / f"frame-{index:02d}.png").write_bytes(
            png(WIDTH, HEIGHT, lambda x, y, bar=bar: RED if x < bar else TEAL)
        )
    for codec, name in (("libvpx", "bars.webm"), ("libx264", "bars.mp4")):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
             "-i", str(OUT / "frame-%02d.png"), "-c:v", codec, "-b:v", "200k",
             "-pix_fmt", "yuv420p", "-an", str(OUT / name)],
            check=True,
        )  # fmt: skip


if __name__ == "__main__":
    main()
