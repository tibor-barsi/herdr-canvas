"""Cut a rectangle out of a PNG without an imaging library (CHK-13).

The renderers hand over browser screenshots: 8-bit, not interlaced, grey, grey
with alpha, RGB or RGBA. That is all this module reads.
"""

from __future__ import annotations

import struct
import zlib
from itertools import accumulate

from agent_canvas.hub.sends import PNG_SIGNATURE

CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}
MAX_PIXELS = 12_000_000


def crop_png(data: bytes, x: int, y: int, width: int, height: int) -> bytes:
    """
    Return the part of a PNG inside a box.

    Parameters
    ----------
    data : bytes
        The PNG file content.
    x, y : int
        Top-left corner of the box in pixels.
    width, height : int
        Size of the box; it is clamped to the image.

    Returns
    -------
    bytes
        A PNG of the clamped box, without filtering.

    Raises
    ------
    ValueError
        If ``data`` is not a PNG this module reads, or the box misses the image.
    """
    image_width, image_height, channels, raw = _decode_header_and_data(data)
    left, top = max(0, x), max(0, y)
    right, bottom = min(image_width, x + width), min(image_height, y + height)
    if right <= left or bottom <= top:
        raise ValueError("the box lies outside the picture")
    rows = _unfilter(raw, image_width, bottom, channels)
    start, stop = left * channels, right * channels
    body = b"".join(b"\x00" + row[start:stop] for row in rows[top:bottom])
    return _encode(right - left, bottom - top, channels, body)


def _decode_header_and_data(data: bytes) -> tuple[int, int, int, bytes]:
    """Return width, height, channel count and the inflated scanline data."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG image")
    position, chunks, header = len(PNG_SIGNATURE), [], None
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
    if header is None or not chunks:
        raise ValueError("not a PNG image")
    width, height, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in CHANNELS or interlace != 0:
        raise ValueError("this PNG format cannot be cropped")
    if width * height > MAX_PIXELS:
        raise ValueError("the picture is too large to crop")
    return width, height, CHANNELS[colour], zlib.decompress(b"".join(chunks))


def _unfilter(raw: bytes, width: int, rows: int, channels: int) -> list[bytes]:
    """Undo the PNG scanline filters of the first ``rows`` rows."""
    stride = width * channels
    previous = bytes(stride)
    result: list[bytes] = []
    for index in range(rows):
        start = index * (stride + 1)
        kind = raw[start]
        line = raw[start + 1 : start + 1 + stride]
        if len(line) != stride:
            raise ValueError("the PNG data is truncated")
        if kind == 1:
            line = _sub(line, channels)
        elif kind == 2:
            line = bytes((a + b) & 255 for a, b in zip(line, previous, strict=True))
        elif kind == 3:
            line = _average(line, previous, channels)
        elif kind == 4:
            line = _paeth(line, previous, channels)
        elif kind != 0:
            raise ValueError("unknown PNG filter")
        result.append(line)
        previous = line
    return result


def _sub(line: bytes, channels: int) -> bytes:
    """Undo the Sub filter: a running sum along each channel."""
    out = bytearray(len(line))
    for channel in range(channels):
        out[channel::channels] = bytes(
            accumulate(line[channel::channels], lambda a, b: (a + b) & 255)
        )
    return bytes(out)


def _average(line: bytes, previous: bytes, channels: int) -> bytes:
    """Undo the Average filter."""
    out = bytearray(line)
    for i in range(len(out)):
        left = out[i - channels] if i >= channels else 0
        out[i] = (out[i] + (left + previous[i]) // 2) & 255
    return bytes(out)


def _paeth(line: bytes, previous: bytes, channels: int) -> bytes:
    """Undo the Paeth filter."""
    out = bytearray(line)
    for i in range(len(out)):
        left = out[i - channels] if i >= channels else 0
        up = previous[i]
        corner = previous[i - channels] if i >= channels else 0
        estimate = left + up - corner
        distance_left = abs(estimate - left)
        distance_up = abs(estimate - up)
        distance_corner = abs(estimate - corner)
        if distance_left <= distance_up and distance_left <= distance_corner:
            predictor = left
        elif distance_up <= distance_corner:
            predictor = up
        else:
            predictor = corner
        out[i] = (out[i] + predictor) & 255
    return bytes(out)


def _encode(width: int, height: int, channels: int, body: bytes) -> bytes:
    """Write scanlines (each with its filter byte) as a PNG file."""
    colour = {value: key for key, value in CHANNELS.items()}[channels]

    def chunk(kind: bytes, content: bytes) -> bytes:
        crc = zlib.crc32(kind + content) & 0xFFFFFFFF
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(body, 6))
        + chunk(b"IEND", b"")
    )
