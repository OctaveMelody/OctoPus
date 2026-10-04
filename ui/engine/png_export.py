"""Lossless page exports through the same SVG/font pipeline as PDF and JPEG."""

from __future__ import annotations

import io
import math
from typing import Any

from ui.engine.font_profile import raster_font_options

MAX_PAGE_PIXELS = 40_000_000
MAX_BATCH_PIXELS = 200_000_000
MAX_EXPORT_BYTES = 64 * 1024 * 1024


def rasterize_pages(pages: tuple[str, ...], *, dpi: int = 96) -> tuple[bytes, ...]:
    """Return white-background PNG pages at standard screen or print resolution."""
    import resvg_py  # type: ignore[import-untyped]
    from PIL import Image

    from .desktop_protocol import _sanitize_export_svg_xml

    if type(dpi) is not int or dpi not in (96, 300):
        raise ValueError("PNG resolution must be 96 or 300 DPI")
    if not pages or len(pages) > 200:
        raise ValueError("export requires between 1 and 200 pages")
    import xml.etree.ElementTree as ET

    outputs: list[bytes] = []
    pixel_total = byte_total = 0
    for source_svg in pages:
        svg = _sanitize_export_svg_xml(source_svg)
        root = ET.fromstring(svg)
        # Renderer pages always have unitless positive intrinsic dimensions.
        width, height = float(root.attrib["width"]), float(root.attrib["height"])
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            raise ValueError("export page has invalid dimensions")
        page_pixels = math.ceil(width * dpi / 96) * math.ceil(height * dpi / 96)
        if not 0 < page_pixels <= MAX_PAGE_PIXELS:
            raise ValueError("export page exceeds the raster pixel limit")
        pixel_total += page_pixels
        if pixel_total > MAX_BATCH_PIXELS:
            raise ValueError("export exceeds the batch pixel limit")
        png = resvg_py.svg_to_bytes(svg_string=svg, zoom=dpi / 96,
                                   **raster_font_options())
        with Image.open(io.BytesIO(png)) as image:
            rgba = image.convert("RGBA")
            white = Image.new("RGBA", rgba.size, "white")
            white.alpha_composite(rgba)
            out = io.BytesIO()
            white.convert("RGB").save(out, format="PNG", dpi=(dpi, dpi))
        data = out.getvalue()
        byte_total += len(data)
        if byte_total > MAX_EXPORT_BYTES:
            raise ValueError("export exceeds the byte limit")
        outputs.append(data)
    return tuple(outputs)


def build_pngs(code: str, custom_code: str, page_config: dict[str, Any], name: str,
               source_key: str | None = None, display_name: str | None = None,
               *, dpi: int = 96) -> tuple[bytes, ...]:
    from .pdf_export import render_all_pages

    return rasterize_pages(render_all_pages(code, custom_code, page_config, name,
                                           source_key, display_name), dpi=dpi)
