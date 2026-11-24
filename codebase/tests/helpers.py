"""Path constants shared by tests."""

from __future__ import annotations

from pathlib import Path

from agent_canvas.drafts import draft_name_for, session_tag

CODEBASE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = CODEBASE_DIR.parent
PLUGIN_DIR = REPO_DIR / "plugin"
PACKAGE_DIR = CODEBASE_DIR / "src" / "agent_canvas"
VENDOR_DIR = PACKAGE_DIR / "static" / "vendor"
FIXTURE_DIR = CODEBASE_DIR / "tests" / "browser" / "fixtures"


def own_draft(session_id: str, name: str = "page") -> str:
    """Return the file name of the session's own draft of ``name`` (POOL-11)."""
    return draft_name_for(name, session_tag(session_id))


def raw_get(port: int, path: str, host: str | None = None, method: str = "GET"):
    """
    Send an HTTP request with an unnormalised path and return (status, headers, body).

    HTTP client libraries collapse ``..`` segments; the traversal tests need
    the server to see them as written.
    """
    import socket

    host = f"localhost:{port}" if host is None else host
    request = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request.encode())
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers, body


def decode_png(data: bytes) -> tuple[int, int, list[list[tuple[int, int, int, int]]]]:
    """
    Decode an 8-bit RGB or RGBA non-interlaced PNG to ``(width, height, rows)``.

    Each row is a list of ``(r, g, b, a)`` tuples. Enough for the browser's own
    PNG output; avoids an imaging dependency in the tests.
    """
    import struct
    import zlib

    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    position, chunks, header = 8, [], None
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
    width, height, depth, colour, _, _, interlace = header
    assert depth == 8 and colour in (2, 6) and interlace == 0, header
    channels = 4 if colour == 6 else 3
    stride = width * channels
    raw = zlib.decompress(b"".join(chunks))
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 255
            elif filter_type == 2:
                line[i] = (line[i] + up) & 255
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif filter_type == 4:
                estimate = left + up - corner
                distances = [abs(estimate - v) for v in (left, up, corner)]
                best = (left, up, corner)[distances.index(min(distances))]
                line[i] = (line[i] + best) & 255
        previous = line
        pixels = []
        for x in range(width):
            pixel = tuple(line[x * channels : x * channels + channels])
            pixels.append(pixel if channels == 4 else (*pixel, 255))
        rows.append(pixels)
    return width, height, rows


def solid_png(
    width: int, height: int, rgb: tuple[int, int, int] = (200, 30, 30)
) -> bytes:
    """Return a valid RGB PNG of one colour (stand-in for a browser screenshot)."""
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    row = b"\x00" + bytes(rgb) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )
