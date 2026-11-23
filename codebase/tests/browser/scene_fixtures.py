"""Generated files for the canvas-scene tests: binary STL, GLB, a two-solid STEP."""

# ruff: noqa: E501  (long JavaScript snippets and section rules)

from __future__ import annotations

import json
import math
import re
import struct

from .solids import cube_step


def _facet(a, b, c) -> bytes:  # noqa: ANN001
    """One binary STL triangle with its geometric normal."""
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]
    length = math.sqrt(sum(x * x for x in n)) or 1.0
    return struct.pack("<12fH", *(x / length for x in n), *a, *b, *c, 0)


def _stl(triangles: list[bytes]) -> bytes:
    return (
        b"scene test".ljust(80, b" ")
        + struct.pack("<I", len(triangles))
        + b"".join(triangles)
    )


def box_stl(origin=(0.0, 0.0, 0.0), size=(10.0, 10.0, 10.0)) -> bytes:  # noqa: ANN001
    """A binary STL box (12 triangles, outward winding) at ``origin``."""
    x0, y0, z0 = origin
    x1, y1, z1 = (origin[i] + size[i] for i in range(3))
    p = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [
        (0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
        (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5),
    ]  # fmt: skip
    triangles = []
    for a, b, c, d in quads:
        triangles += [_facet(p[a], p[b], p[c]), _facet(p[a], p[c], p[d])]
    return _stl(triangles)


def torus_stl(
    centre=(0.0, 0.0, 0.0),
    major: float = 30.0,
    minor: float = 10.0,
    around: int = 300,
    tube: int = 150,
) -> bytes:  # noqa: ANN001
    """A binary STL torus of ``2 * around * tube`` triangles (90 000 by default)."""

    def point(i: int, j: int):  # noqa: ANN202
        u = 2 * math.pi * (i % around) / around
        v = 2 * math.pi * (j % tube) / tube
        r = major + minor * math.cos(v)
        return (
            centre[0] + r * math.cos(u), centre[1] + r * math.sin(u),
            centre[2] + minor * math.sin(v),
        )  # fmt: skip

    triangles = []
    for i in range(around):
        for j in range(tube):
            a, b, c, d = (
                point(i, j),
                point(i + 1, j),
                point(i + 1, j + 1),
                point(i, j + 1),
            )
            triangles += [_facet(a, b, c), _facet(a, c, d)]
    return _stl(triangles)


def glb_cube(size: float = 10.0, colour=(0.9, 0.1, 0.1)) -> bytes:  # noqa: ANN001
    """A GLB with one coloured cube spanning 0..``size`` (glTF is Y-up)."""
    corners = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    positions = b"".join(struct.pack("<3f", *(c * size for c in p)) for p in corners)
    indices = [
        0, 2, 1, 1, 2, 3, 4, 5, 6, 5, 7, 6, 0, 1, 4, 1, 5, 4,
        2, 6, 3, 3, 6, 7, 0, 4, 2, 2, 4, 6, 1, 3, 5, 3, 7, 5,
    ]  # fmt: skip
    index_bytes = struct.pack("<36H", *indices)
    blob = positions + index_bytes
    document = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [*colour, 1.0]}}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(index_bytes)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": [0, 0, 0], "max": [size, size, size]},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }  # fmt: skip
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(text) + 8 + len(blob)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(text), b"JSON") + text
        + struct.pack("<I4s", len(blob), b"BIN\0") + blob
    )  # fmt: skip


def two_solid_step() -> str:
    """A STEP file with two separate products, named ``left`` and ``right``."""
    first = cube_step(10.0).replace("'cube'", "'left'")
    second = cube_step(6.0).replace("'cube'", "'right'")
    count = len(re.findall(r"^#\d+ =", first, re.M))
    shifted = re.sub(r"#(\d+)", lambda m: f"#{int(m.group(1)) + count}", second)
    body = shifted.split("DATA;\n", 1)[1].rsplit("ENDSEC;", 1)[0]
    return first.replace("ENDSEC;\nEND-ISO", body + "ENDSEC;\nEND-ISO")
