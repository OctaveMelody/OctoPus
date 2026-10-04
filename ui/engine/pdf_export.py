"""PDF export for the 1.13.0 ``export.pdf`` op (protocol PROTOCOL.md §5).

Renders the requested document revision to standalone SVG pages through the
SAME pipeline as ``render`` (``_source_document`` identity +
``render_score_model_pages``), converts each page with svglib into a
reportlab drawing, and assembles one multi-page vector PDF. Text stays real
PDF text (selectable/printable). Release exports register pinned bundled TrueType
faces explicitly; reference exports retain svglib's host font resolution and
the platform-aware CJK candidate table.

Tool decision (2026-09-22, evidence in IMPLEMENTATION_PLAN.md): svglib +
reportlab over cairosvg — both render all corpus pages with equivalent
fidelity (median 0.06% pixel diff across 104 shared pages), but svglib is
pure wheels (no native system library), so the same code path works in the
DEB, AppImage, and Windows .exe bundles without vendoring libcairo; it also
tolerates the one upstream reference page whose ``code`` attribute carries
raw ``"`` bytes (strict-XML cairosvg rejects that page).

The svglib/reportlab imports are deliberately lazy (inside the functions), so
non-export operations do not load these export libraries. They remain required
installation dependencies in ``pyproject.toml`` and are included in release
workers. :func:`render_all_pages` is the shared
identity + render setup used by BOTH export formats (this module's PDF and
:mod:`ui.engine.jpg_export`'s JPG), so the two ops cannot drift from
``render`` or from each other.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path
from typing import Any

from ui.engine.font_profile import apply_pdf_font_fallbacks, apply_svg_fonts, register_pdf_fonts

#: Bare-ampersand escape — the same rule as the frontend's
#: ``escapeBareAmpersands`` (R10a export hygiene). Attribute values are never
#: rendered, so this is semantics-preserving; it just makes the SVG
#: well-formed for strict XML consumers.
_BARE_AMPERSAND = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#[xX][0-9a-fA-F]+);)")

#: font-family value as written in the rendered SVGs (attribute, not CSS).
_FONT_FAMILY_ATTR = re.compile(r'font-family="([^"]+)"')

#: Platform-aware CJK candidates for families that have no fontconfig path on
#: Windows. These are environment facts (standard OS font locations), not
#: corpus special-casing: any document using these families benefits. The
#: entries are tried in order; the first existing file wins.
_CJK_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "microsoft yahei": (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        "/usr/share/fonts/truetype/msyh/msyh.ttc",
        "/usr/share/fonts/msyh/msyh.ttc",
    ),
    "simhei": (
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/truetype/simhei/simhei.ttf",
    ),
}


def _escape_bare_ampersands(svg: str) -> str:
    return _BARE_AMPERSAND.sub("&amp;", svg)


def _families_used(pages: tuple[str, ...]) -> set[str]:
    """Distinct font-family values across the rendered pages (general scan)."""
    families: set[str] = set()
    for page in pages:
        families.update(_FONT_FAMILY_ATTR.findall(page))
    return families


def _register_cjk_fallbacks(families: set[str]) -> None:
    """Seed reportlab's font registry on platforms without fontconfig.

    svglib's own chain (standard fonts → local file → fc-match) already
    resolves everything on Linux; this only matters where ``fc-match`` does
    not exist (Windows/macOS). Registration is best-effort: a missing file is
    skipped and svglib falls back to its default font for that family.
    """
    if sys.platform == "linux":
        return
    try:
        from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
        from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - exercised only without deps
        return
    for family in families:
        if family.casefold() in {"simhei", "simsun", "kaiti", "microsoft yahei", "fangsong"}:
            # These matching system faces are registered by the shared font policy.
            continue
        candidates = _CJK_FONT_CANDIDATES.get(family.lower())
        if candidates is None:
            continue
        for candidate in candidates:
            if not Path(candidate).is_file():
                continue
            internal = f"octopusCjk-{family.replace(' ', '')}"
            try:
                pdfmetrics.registerFont(TTFont(internal, candidate))
            except Exception:  # unreadable/corrupt font file: skip to next
                continue
            # Map svglib's family lookup (its global map, used by svg2rlg)
            # onto the registered face.
            from svglib.fonts import get_global_font_map  # type: ignore[import-untyped]

            font_map = get_global_font_map()
            font_map._map[internal] = {
                "svg_family": family,
                "svg_weight": "normal",
                "svg_style": "normal",
                "rlgFont": internal,
                "exact": True,
            }
            font_map._family_index[family.lower()] = family
            break


def render_all_pages(
    code: str,
    custom_code: str,
    page_config: dict[str, Any],
    name: str,
    source_key: str | None = None,
    display_name: str | None = None,
) -> tuple[str, ...]:
    """Render EVERY page of the revision to standalone SVG strings.

    Shared by both export formats (PDF 1.13.0, JPG 1.14.0): one definition of
    the identity + render pipeline setup, so the two ops cannot drift from
    ``render`` or from each other. Raises ``ValueError`` when the code parses
    to zero pages; any pipeline exception propagates so the op handler can
    map it to a descriptive error.
    """
    # Lazy: keep ui.engine.ops importable without the export dependencies.
    from octopus.jps import JpsDocument, jps_key, repair_mojibake
    from octopus.model.model_normalize import normalize_document
    from octopus.parser.grammar import parse_document
    from octopus.render.svg import render_score_model_pages

    path = Path(name if name.lower().endswith(".jps") else f"{name}.jps")
    repaired_code, repaired = repair_mojibake(code)
    source = JpsDocument(
        path=path, key=source_key if source_key is not None else jps_key(path.name),
        code=repaired_code, original_code=code, custom_code=custom_code,
        page_config=dict(page_config),
        record={"name": display_name if display_name is not None else name},
        json_wrapped=True, encoding_repaired=repaired,
    )
    model = normalize_document(parse_document(source), source=source)
    pages = render_score_model_pages(model, list(range(len(model.pages))))
    if not pages:
        raise ValueError("the document renders no pages — nothing to export")
    return tuple(apply_svg_fonts(page, page_config.get("_font_sources")) for page in pages)


def build_pdf(
    code: str,
    custom_code: str,
    page_config: dict[str, Any],
    name: str,
    source_key: str | None = None,
    display_name: str | None = None,
) -> tuple[bytes, int]:
    """Render the document revision and assemble it into one PDF.

    Returns ``(pdf_bytes, page_count)``. Raises ``ValueError`` when the code
    parses to zero pages (nothing to export); any pipeline exception
    propagates so the op handler can map it to a descriptive error.
    """
    pages = render_all_pages(code, custom_code, page_config, name, source_key, display_name)
    return build_pdf_pages(pages)


def build_pdf_pages(pages: tuple[str, ...]) -> tuple[bytes, int]:
    """Assemble rendered pages into one vector PDF (also used by batch export)."""
    from reportlab.pdfgen import canvas as pdf_canvas  # type: ignore[import-untyped]
    from svglib.svglib import svg2rlg  # type: ignore[import-untyped]

    if not pages or len(pages) > 200:
        raise ValueError("PDF export requires between 1 and 200 pages")
    from .desktop_protocol import _sanitize_export_svg_xml

    pages = tuple(apply_pdf_font_fallbacks(page) for page in pages)
    register_pdf_fonts()
    _register_cjk_fallbacks(_families_used(pages))

    out = io.BytesIO()
    canvas = pdf_canvas.Canvas(out)
    for svg in pages:
        drawing = svg2rlg(io.BytesIO(_sanitize_export_svg_xml(svg).encode("utf-8")))
        if drawing is None:  # pragma: no cover - defensive; svglib signals via exceptions
            raise ValueError("SVG conversion failed for a page")
        canvas.setPageSize((float(drawing.width), float(drawing.height)))
        canvas.saveState()
        drawing.drawOn(canvas, 0, 0)
        canvas.restoreState()
        canvas.showPage()
    canvas.save()
    return out.getvalue(), len(pages)
