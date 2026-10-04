"""Shared SVG preparation and well-formedness checks for export paths."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

from octopus.font_profile import apply_svg_fonts
from octopus.jps import JpsDocument
from octopus.normalization.pipeline import normalize_document
from octopus.normalization.types import ScoreModel
from octopus.parser.grammar import parse_document
from octopus.render.svg import render_score_model
from octopus.render.svg_preview import add_safe_custom_markup

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XML_AMPERSAND_RE = re.compile(r"&(?:(?:amp|lt|gt|quot|apos);|#(?:[0-9]+|x[0-9A-Fa-f]+);)?")
_RAW_CODE_ATTRIBUTE_RE = re.compile(
    r'(<use\b[^>]*?\bcode=")(.*)(?=" '
    r'(?:data-diaohao="true" )?xmlns:xlink="http://www\.w3\.org/1999/xlink")'
)


def render_score_pages(
    model: ScoreModel,
    page_config: dict[str, Any],
) -> tuple[list[str], bool]:
    """Render all safe-source SVG pages, add approved custom markup, and apply fonts."""
    pages = render_score_model(model, export_mode="safe-source")
    pages, custom_markup_omitted = add_safe_custom_markup(model, pages)
    sources = page_config.get("_font_sources")
    pages = [apply_svg_fonts(page, sources) for page in pages]
    return pages, custom_markup_omitted


def normalize_source(source: JpsDocument) -> ScoreModel:
    """Normalize one source document for shared worker and batch export paths."""
    return normalize_document(parse_document(source), source=source)


def sanitize_export_svg_xml(svg: str) -> str:
    """Escape legacy serializer quirks and invalid XML characters before export."""
    svg = _RAW_CODE_ATTRIBUTE_RE.sub(
        lambda match: match.group(1) + html.escape(match.group(2), quote=True),
        svg,
    )

    def escape(match: re.Match[str]) -> str:
        entity = match.group()
        if entity == "&":
            return "&amp;"
        if entity.startswith("&#"):
            digits = entity[3:-1] if entity.startswith("&#x") else entity[2:-1]
            try:
                codepoint = int(digits, 16 if entity.startswith("&#x") else 10)
            except ValueError:
                return "&amp;" + entity[1:]
            if codepoint not in {0x9, 0xA, 0xD} and not (
                0x20 <= codepoint <= 0xD7FF
                or 0xE000 <= codepoint <= 0xFFFD
                or 0x10000 <= codepoint <= 0x10FFFF
            ):
                return "&amp;" + entity[1:]
        return entity

    return _XML_AMPERSAND_RE.sub(escape, svg)


def sanitize_export_pages(pages: tuple[str, ...]) -> tuple[str, ...]:
    """Sanitize and validate SVG pages before a file export."""
    result: list[str] = []
    for page_index, source_svg in enumerate(pages, start=1):
        svg = sanitize_export_svg_xml(source_svg)
        try:
            root = ET.fromstring(svg)
        except ET.ParseError as exc:
            raise ValueError(f"export page {page_index} is not well-formed XML") from exc
        if root.tag != f"{{{SVG_NAMESPACE}}}svg":
            raise ValueError(f"export page {page_index} has no SVG root element")
        result.append(svg)
    return tuple(result)
