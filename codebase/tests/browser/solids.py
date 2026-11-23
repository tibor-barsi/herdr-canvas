"""Small generated fixtures for the heavy blocks: cube STL, cube STEP, PNG (M10)."""

from __future__ import annotations

import struct
import zlib

# Corner k of the cube has x = k & 1, y = (k >> 1) & 1, z = (k >> 2) & 1.
# Each face lists its four corners counter-clockwise seen from outside, plus the
# outward normal.
FACES = (
    ((0, 2, 6, 4), (-1, 0, 0)),
    ((1, 5, 7, 3), (1, 0, 0)),
    ((0, 4, 5, 1), (0, -1, 0)),
    ((2, 3, 7, 6), (0, 1, 0)),
    ((0, 1, 3, 2), (0, 0, -1)),
    ((4, 6, 7, 5), (0, 0, 1)),
)


def corner(index: int, size: float) -> tuple[float, float, float]:
    """Return corner ``index`` of the cube spanning 0..``size`` on every axis."""
    return (
        size * (index & 1),
        size * ((index >> 1) & 1),
        size * ((index >> 2) & 1),
    )


def cube_stl(size: float = 10.0) -> str:
    """Return an ASCII STL of the cube with 12 triangles."""
    lines = ["solid cube"]
    for quad, normal in FACES:
        for triangle in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])):
            lines.append("facet normal {} {} {}".format(*normal))
            lines.append(" outer loop")
            lines += ["  vertex {} {} {}".format(*corner(i, size)) for i in triangle]
            lines += [" endloop", "endfacet"]
    lines.append("endsolid cube")
    return "\n".join(lines) + "\n"


class _Step:
    """Collects numbered STEP entities."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str) -> int:
        """Append ``#n = text;`` and return n."""
        number = len(self.lines) + 1
        self.lines.append(f"#{number} = {text};")
        return number


def _vector(step: _Step, direction: tuple[float, float, float]) -> int:
    d = step.add("DIRECTION('',({},{},{}))".format(*map(float, direction)))
    return step.add(f"VECTOR('',#{d},1.)")


def cube_step(size: float = 10.0) -> str:
    """Return a STEP (AP214) file with one cube solid spanning 0..``size``."""
    step = _Step()
    points = [
        step.add("CARTESIAN_POINT('',({},{},{}))".format(*corner(i, size)))
        for i in range(8)
    ]
    vertices = [step.add(f"VERTEX_POINT('',#{p})") for p in points]
    edges: dict[tuple[int, int], int] = {}

    def edge(a: int, b: int) -> tuple[int, bool]:
        """Return the EDGE_CURVE between corners a and b and its sense."""
        key = (min(a, b), max(a, b))
        if key not in edges:
            lo, hi = key
            start, end = corner(lo, size), corner(hi, size)
            delta = tuple((e - s) / size for s, e in zip(start, end, strict=True))
            vector = _vector(step, delta)
            line = step.add(f"LINE('',#{points[lo]},#{vector})")
            edges[key] = step.add(
                f"EDGE_CURVE('',#{vertices[lo]},#{vertices[hi]},#{line},.T.)"
            )
        return edges[key], a < b

    faces = []
    for quad, normal in FACES:
        oriented = []
        for k in range(4):
            a, b = quad[k], quad[(k + 1) % 4]
            curve, forward = edge(a, b)
            flag = ".T." if forward else ".F."
            oriented.append(step.add(f"ORIENTED_EDGE('',*,*,#{curve},{flag})"))
        loop = step.add(
            "EDGE_LOOP('',({}))".format(",".join(f"#{o}" for o in oriented))
        )
        bound = step.add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
        origin = step.add(
            "CARTESIAN_POINT('',({},{},{}))".format(*corner(quad[0], size))
        )
        axis = step.add("DIRECTION('',({},{},{}))".format(*map(float, normal)))
        along = [
            (q - p) / size
            for p, q in zip(corner(quad[0], size), corner(quad[1], size), strict=True)
        ]
        reference = step.add("DIRECTION('',({},{},{}))".format(*along))
        placement = step.add(f"AXIS2_PLACEMENT_3D('',#{origin},#{axis},#{reference})")
        plane = step.add(f"PLANE('',#{placement})")
        faces.append(step.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)"))
    shell = step.add("CLOSED_SHELL('',({}))".format(",".join(f"#{f}" for f in faces)))
    solid = step.add(f"MANIFOLD_SOLID_BREP('cube',#{shell})")
    unit_length = step.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    unit_angle = step.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    unit_solid = step.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    uncertainty = step.add(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{unit_length},"
        "'distance_accuracy_value','')"
    )
    context = step.add(
        "( GEOMETRIC_REPRESENTATION_CONTEXT(3) "
        f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncertainty})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{unit_length},#{unit_angle},#{unit_solid})) "
        "REPRESENTATION_CONTEXT('','3D') )"
    )
    representation = step.add(
        f"ADVANCED_BREP_SHAPE_REPRESENTATION('cube',(#{solid}),#{context})"
    )
    app = step.add("APPLICATION_CONTEXT('automotive design')")
    step.add(
        "APPLICATION_PROTOCOL_DEFINITION("
        f"'international standard','automotive_design',2000,#{app})"
    )
    pcontext = step.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    product = step.add(f"PRODUCT('cube','cube','',(#{pcontext}))")
    formation = step.add(f"PRODUCT_DEFINITION_FORMATION('','',#{product})")
    dcontext = step.add(
        f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')"
    )
    definition = step.add(f"PRODUCT_DEFINITION('design','',#{formation},#{dcontext})")
    shape = step.add(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
    step.add(f"SHAPE_DEFINITION_REPRESENTATION(#{shape},#{representation})")
    header = (
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('cube'),'2;1');\n"
        "FILE_NAME('cube.step','2026-01-01T00:00:00',(''),(''),'','','');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\n"
        "ENDSEC;\nDATA;\n"
    )
    return header + "\n".join(step.lines) + "\nENDSEC;\nEND-ISO-10303-21;\n"


def png(width: int, height: int, pixel) -> bytes:  # noqa: ANN001
    """Return an RGB PNG whose pixel (x, y) is ``pixel(x, y)`` (an RGB tuple)."""
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height)
    )

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
