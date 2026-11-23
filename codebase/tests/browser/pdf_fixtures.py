"""Generated PDF fixtures for the PDF viewer tests (VIEW-04, VIEW-05), no extra dependency."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
from io import BytesIO


def assemble(objects: list[bytes], trailer: bytes = b"") -> bytes:
    """
    Join numbered object bodies into a PDF file with a classic cross-reference table.

    Parameters
    ----------
    objects : list[bytes]
        Bodies of objects 1, 2, ...; object 1 must be the catalog.
    trailer : bytes
        Further entries of the trailer dictionary.

    Returns
    -------
    bytes
        The file.
    """
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R %s >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        trailer,
        xref,
    )
    return bytes(out)


def stream(content: bytes, extra: bytes = b"") -> bytes:
    """Return a stream object body holding ``content``."""
    return (
        b"<< /Length %d %s >>\nstream\n" % (len(content), extra)
        + content
        + b"\nendstream"
    )


def escape(text: str) -> str:
    """Escape ``text`` for a PDF literal string."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(
    pages: int = 3,
    tag: str = "",
    width: int = 595,
    height: int = 842,
    first: int = 1,
    lines: int = 30,
) -> bytes:
    """
    Build a PDF of Helvetica text pages (the standard fonts, not embedded).

    Page ``n`` has the title ``Page n of N`` and lines ``Line i of page n: ...``;
    ``tag`` is appended to every line so a rewritten version can be told apart;
    ``first`` is the number printed on the first page (0 moves every text one page on);
    ``lines`` is the number of text lines on a page (more than fit are below the page).
    """
    objects: list[bytes] = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for number in range(1, pages + 1):
        n = number + first - 1
        content = [f"BT /F1 22 Tf 56 {height - 62} Td (Page {n} of {pages}{tag}) Tj ET"]
        for i in range(1, lines + 1):
            text = f"Line {i} of page {n}: the quick brown fox jumps over the lazy dog{tag}"
            content.append(
                f"BT /F1 10 Tf 56 {height - 100 - i * 17} Td ({escape(text)}) Tj ET"
            )
        objects.append(stream("\n".join(content).encode("latin-1")))
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>" % (width, height, len(objects))
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Count %d /Kids [%s] >>" % (
        pages,
        b" ".join(b"%d 0 R" % k for k in kids),
    )
    return assemble(objects)


def script_pdf() -> bytes:
    """Build a PDF with an open-action script and a form field with key and format scripts."""
    open_action = b'<< /S /JavaScript /JS (app.alert\\("open action ran"\\);) >>'
    field = (
        b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (probe) /Rect [56 600 300 630] "
        b"/DA (/F1 12 Tf 0 g) /V (x) /AA << /K << /S /JavaScript "
        b'/JS (app.alert\\("field ran"\\);) >> /F << /S /JavaScript '
        b'/JS (app.alert\\("format ran"\\);) >> >> >>'
    )
    content = b"BT /F1 20 Tf 56 760 Td (Script fixture) Tj ET"
    return assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R /OpenAction 6 0 R /AcroForm << /Fields [7 0 R] "
            b"/DR << /Font << /F1 3 0 R >> >> /DA (/F1 0 Tf 0 g) >> >>",
            b"<< /Type /Pages /Count 1 /Kids [5 0 R] >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            stream(content),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> /Annots [7 0 R] >>",
            open_action,
            field,
        ]
    )


def cjk_pdf() -> bytes:
    """Build a PDF whose text is Japanese through the predefined CMap ``UniJIS-UCS2-H``."""
    content = b"BT /F1 24 Tf 56 760 Td <3042304430463048304A> Tj ET"
    return assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            stream(content),
            b"<< /Type /Font /Subtype /Type0 /BaseFont /MS-Gothic /Encoding /UniJIS-UCS2-H "
            b"/DescendantFonts [6 0 R] >>",
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /MS-Gothic /CIDSystemInfo "
            b"<< /Registry (Adobe) /Ordering (Japan1) /Supplement 2 >> /FontDescriptor 7 0 R >>",
            b"<< /Type /FontDescriptor /FontName /MS-Gothic /Flags 4 /FontBBox [0 -137 1000 859] "
            b"/ItalicAngle 0 /Ascent 859 /Descent -137 /CapHeight 700 /StemV 80 >>",
        ]
    )


def box_font() -> bytes:
    """Build a TrueType font whose only glyph, ``A``, is a filled box (fontTools)."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({65: "A"})
    box = TTGlyphPen(None)
    box.moveTo((100, 0))
    box.lineTo((100, 700))
    box.lineTo((600, 700))
    box.lineTo((600, 0))
    box.closePath()
    empty = TTGlyphPen(None)
    builder.setupGlyf({".notdef": empty.glyph(), "A": box.glyph()})
    builder.setupHorizontalMetrics({".notdef": (500, 0), "A": (700, 100)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "BoxFont", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    out = BytesIO()
    builder.save(out)
    return out.getvalue()


def font_pdf() -> bytes:
    """Build a PDF that draws ``AAAA`` at 100 pt (box glyphs) with an embedded font."""
    font = box_font()
    content = b"BT /F1 100 Tf 100 700 Td (AAAA) Tj ET"
    return assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            stream(content),
            b"<< /Type /Font /Subtype /TrueType /BaseFont /BoxFont /FirstChar 65 /LastChar 65 "
            b"/Widths [700] /FontDescriptor 6 0 R /Encoding /WinAnsiEncoding >>",
            b"<< /Type /FontDescriptor /FontName /BoxFont /Flags 32 /FontBBox [0 0 700 700] "
            b"/ItalicAngle 0 /Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 /FontFile2 7 0 R >>",
            stream(font, b"/Length1 %d" % len(font)),
        ]
    )


def image_pdf() -> bytes:
    """Build a PDF with a 2 x 1 pixel image (red, blue) drawn 200 x 100 pt at (100, 600)."""
    content = b"q 200 0 0 100 100 600 cm /Im1 Do Q"
    pixels = bytes([255, 0, 0, 0, 0, 255])
    return assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
            stream(content),
            stream(
                pixels,
                b"/Type /XObject /Subtype /Image /Width 2 /Height 1 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8",
            ),
        ]
    )


_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key: bytes, data: bytes) -> bytes:
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) % 256
        box[i], box[j] = box[j], box[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + box[i]) % 256
        box[i], box[j] = box[j], box[i]
        out.append(byte ^ box[(box[i] + box[j]) % 256])
    return bytes(out)


def encrypted_pdf(password: str = "secret") -> bytes:
    """
    Build a one-page PDF encrypted with the standard handler (RC4, 40 bit).

    The user password is ``password``, so opening it without one fails.
    """
    user = (password.encode() + _PAD)[:32]
    owner = hashlib.md5((b"owner" + _PAD)[:32]).digest()[:5]
    o_entry = _rc4(owner, user)
    permissions = (-4).to_bytes(4, "little", signed=True)
    file_id = b"agent-canvas-fixt"
    key = hashlib.md5(user + o_entry + permissions + file_id).digest()[:5]
    u_entry = _rc4(key, _PAD)
    content_key = hashlib.md5(key + (4).to_bytes(3, "little") + b"\0\0").digest()[:10]
    content = _rc4(content_key, b"BT /F1 20 Tf 56 760 Td (Secret page) Tj ET")
    encrypt = b"<< /Filter /Standard /V 1 /R 2 /O <%s> /U <%s> /P -4 >>" % (
        o_entry.hex().encode(),
        u_entry.hex().encode(),
    )
    ident = file_id.hex().encode()
    return assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [5 0 R] >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            stream(content),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>",
            encrypt,
        ],
        trailer=b"/Encrypt 6 0 R /ID [<%s> <%s>]" % (ident, ident),
    )
