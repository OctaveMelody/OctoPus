"""JPG export for the 1.14.0 ``export.jpg`` op (protocol PROTOCOL.md §5).

Renders the requested revision to standalone SVG pages through the SAME
pipeline as ``render`` (shared :func:`pdf_export.render_all_pages`) and
rasterizes each page with **resvg** (the industry-standard Rust SVG renderer,
via the pure-wheel ``resvg-py`` package) into a JPEG encoded by Pillow.

Tool decision (2026-09-22, evidence in IMPLEMENTATION_PLAN.md): resvg-py +
Pillow — full-corpus sweep of all 105 reference pages renders 104/105
directly; the one failure is the known malformed-quote page (see
:func:`_repair_code_attr_quotes`), which the targeted repair fixes and which
the repair provably does NOT touch on any other corpus page. Fidelity vs an
independent ground truth: 0.25% pixel diff on a normal page, 2.90% on the
repaired one (both within the ~3% rasterizer baseline measured for the PDF
line). Release resvg export loads only the pinned bundled font files and skips
system fonts. Reference export retains the normal system-font resolution.


Output shape: one JPEG per page (the website's JPG export shape), zoom 2.0
(1000×1415 user units → 2000×2830 px ≈ A4 at ~203 DPI), quality 90,
composited onto white (the page background rect is already white; the
composite only guards against any alpha).

The resvg-py/Pillow imports are deliberately lazy (inside :func:`build_jpgs`),
so non-export operations do not load these export libraries. They remain required
installation dependencies in ``pyproject.toml`` and are included in release workers.
"""

from __future__ import annotations

import io
import re
from typing import Any

from ui.engine.font_profile import raster_font_options

#: Rasterization scale: 2× the SVG root (1000 user units wide → 2000 px),
#: ≈ A4 at ~203 DPI — print/sharing quality without bloating file size.
_EXPORT_ZOOM = 2.0

#: JPEG quality for the export (Pillow scale 0-95).
_JPEG_QUALITY = 90

#: Bare-ampersand escape — same rule as the frontend's ``escapeBareAmpersands``
#: and the PDF line: attribute values are never rendered, so this is
#: semantics-preserving; it just makes the SVG well-formed for strict XML
#: consumers (usvg rejects a bare ``&`` in an attribute).
_BARE_AMPERSAND = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#[xX][0-9a-fA-F]+);)")

#: Targeted well-formedness repair for ONE upstream serializer quirk (evidence
#: 2026-09-22, corpus-wide): the site embedded raw code text containing
#: unescaped ``"`` directly into a ``code="..."`` attribute value, e.g.
#: ``code="5."（男）""`` — the value closes early and the trailing bytes parse
#: as garbage (strict XML parsers reject the page). The intended value is
#: ``5."（男）"``. Pattern: ``code="A"TEXT""`` where TEXT touches both quotes
#: (no whitespace before it, no ``<``/``>``/``"`` inside) — a well-formed
#: attribute list always has whitespace after a closing quote, so the pattern
#: cannot fire on valid markup. Verified corpus-wide: fires on exactly 1/105
#: reference pages. Attribute values are metadata (resvg ignores custom
#: attributes), so the merge is rendering-neutral.
_CODE_ATTR_QUOTE_REPAIR = re.compile(r'(code="[^"]*)"(?P<mid>[^<>"\s][^<>]*?)""(?=\s)')


def _well_form(svg: str) -> str:
    """Make one rendered page parseable by strict XML (usvg).

    Two independent, both semantics-preserving steps: bare-ampersand escape
    (every page — the reference style mixes raw ``&`` in ``code`` attributes)
    and the targeted quote repair (exactly one corpus page today).
    """
    svg = _BARE_AMPERSAND.sub("&amp;", svg)
    return _CODE_ATTR_QUOTE_REPAIR.sub(r'\1&quot;\g<mid>&quot;"', svg)


def build_jpgs(
    code: str,
    custom_code: str,
    page_config: dict[str, Any],
    name: str,
    source_key: str | None = None,
    display_name: str | None = None,
) -> tuple[bytes, ...]:
    """Render the revision and rasterize every page to JPEG bytes.

    Returns one JPEG ``bytes`` per page, in page order. Raises ``ValueError``
    when the code parses to zero pages; any pipeline/conversion exception
    propagates so the op handler can map it to a descriptive error.
    """
    # Lazy: keep ui.engine.ops importable without the export dependencies.
    import resvg_py  # type: ignore[import-untyped]
    from PIL import Image  # type: ignore[import-untyped]

    from ui.engine.pdf_export import render_all_pages

    pages = render_all_pages(code, custom_code, page_config, name, source_key, display_name)
    jpegs: list[bytes] = []
    for svg in pages:
        png = resvg_py.svg_to_bytes(
            svg_string=_well_form(svg), zoom=_EXPORT_ZOOM, **raster_font_options()
        )
        opened = Image.open(io.BytesIO(png))
        if opened.mode != "RGB":
            # Composite any alpha onto white before JPEG (lossy, no alpha).
            background = Image.new("RGB", opened.size, (255, 255, 255))
            background.paste(opened, mask=opened.convert("RGBA").split()[-1])
        else:
            background = opened
        out = io.BytesIO()
        background.save(out, format="JPEG", quality=_JPEG_QUALITY)
        jpegs.append(out.getvalue())
    return tuple(jpegs)
