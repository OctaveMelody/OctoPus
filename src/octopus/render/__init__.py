"""Lazy public rendering facade.

Importing a focused render submodule must not load the complete layout and SVG engines.
The mapping below keeps the existing convenience imports available on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "SerializationProfile": ("svg_engine.serialize", "SerializationProfile"),
    "duration_line_elements": ("duration", "duration_line_elements"),
    "duration_source_groups": ("duration", "duration_source_groups"),
    "event_to_glyph_id": ("core.glyphs", "event_to_glyph_id"),
    "layout_page": ("layout", "layout_page"),
    "LayoutEvent": ("layout", "LayoutEvent"),
    "LayoutPage": ("layout", "LayoutPage"),
    "LayoutVoiceBrace": ("layout", "LayoutVoiceBrace"),
    "load_all_glyphs": ("core.glyphs", "load_all_glyphs"),
    "load_glyph": ("core.glyphs", "load_glyph"),
    "MAX_DURATION_LINE_LEVEL": ("duration", "MAX_DURATION_LINE_LEVEL"),
    "note_glyph_id": ("core.glyphs", "note_glyph_id"),
    "page_metrics": ("layout", "page_metrics"),
    "RenderElement": ("core.elements", "RenderElement"),
    "SvgElement": ("core.elements", "SvgElement"),
    "render_jps": ("svg", "render_jps"),
    "render_page_body_elements": ("svg", "render_page_body_elements"),
    "render_page_elements": ("svg", "render_page_elements"),
    "render_score_model": ("svg", "render_score_model"),
    "render_score_model_pages": ("svg", "render_score_model_pages"),
    "render_score_model_page_with_layout": ("svg", "render_score_model_page_with_layout"),
    "render_score_model_to_html": ("svg", "render_score_model_to_html"),
}

__all__ = [
    "SerializationProfile",
    "duration_line_elements",
    "duration_source_groups",
    "event_to_glyph_id",
    "layout_page",
    "LayoutEvent",
    "LayoutPage",
    "LayoutVoiceBrace",
    "load_all_glyphs",
    "load_glyph",
    "MAX_DURATION_LINE_LEVEL",
    "note_glyph_id",
    "page_metrics",
    "RenderElement",
    "SvgElement",
    "render_jps",
    "render_page_body_elements",
    "render_page_elements",
    "render_score_model",
    "render_score_model_pages",
    "render_score_model_page_with_layout",
    "render_score_model_to_html",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(f".{module_name}", __name__), attribute_name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from octopus.render.core.elements import RenderElement, SvgElement
    from octopus.render.core.glyphs import (
        event_to_glyph_id,
        load_all_glyphs,
        load_glyph,
        note_glyph_id,
    )

    from .duration import MAX_DURATION_LINE_LEVEL, duration_line_elements, duration_source_groups
    from .layout import LayoutEvent, LayoutPage, LayoutVoiceBrace, layout_page, page_metrics
    from .svg import (
        render_jps,
        render_page_body_elements,
        render_page_elements,
        render_score_model,
        render_score_model_page_with_layout,
        render_score_model_pages,
        render_score_model_to_html,
    )
    from .svg_engine.serialize import SerializationProfile
