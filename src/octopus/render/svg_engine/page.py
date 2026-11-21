"""Page-level SVG assembly with injected rendering stages."""

from __future__ import annotations

from collections.abc import Callable

from octopus.normalization.types import ScoreModel
from octopus.render.core.elements import SvgElement
from octopus.render.core.layout_types import LayoutPage

from .primitives import text_element
from .types import GraceRenderPlan


def _roman_number(number: int) -> str:
    parts = []
    for value, symbol in (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
        (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
        (5, "V"), (4, "IV"), (1, "I"),
    ):
        count, number = divmod(number, value)
        parts.append(symbol * count)
    return "".join(parts)


def render_page_body_elements(
    model: ScoreModel,
    layout: LayoutPage,
    page_index: int,
    grace_plan: GraceRenderPlan,
    *,
    header_elements: Callable[[LayoutPage], list[SvgElement]],
    score_stream_elements: Callable[[LayoutPage, GraceRenderPlan], list[SvgElement]],
    custom_elements: Callable[[ScoreModel, int], list[SvgElement]],
) -> list[SvgElement]:
    """Assemble one page body while leaving individual stages injectable."""
    elements = [
        SvgElement(
            tag="rect",
            layer="background",
            source_event_index=None,
            attrs=(
                ("x", "0"),
                ("y", "0"),
                ("height", "100%"),
                ("width", "100%"),
                ("fill", "#ffffff"),
            ),
            synthetic=True,
        )
    ]
    if page_index == 0:
        elements.extend(header_elements(layout))
    elements.extend(score_stream_elements(layout, grace_plan))
    elements.extend(custom_elements(model, page_index))
    metrics = layout.metrics
    if metrics.has_footer:
        font_size = 12
        footer_style = (("font-family", "Arial"), ("font-size", str(font_size)), ("fill", "#1b1b1b"))
        y = metrics.height - 12
        positions = {
            "left": (max(12, metrics.margin_left), "start"),
            "center": (metrics.width / 2, "middle"),
            "right": (metrics.width - max(12, metrics.margin_right), "end"),
        }
        number_position = metrics.footer_page_number_position
        show_number = metrics.has_page_number
        if metrics.footer_credit and metrics.footer_credit_text:
            position = metrics.footer_credit_position
            if show_number and position == number_position:
                position = "right" if number_position == "left" else "left"
            x, anchor = positions[position]
            # Leave room for wide fallback glyphs even with extreme saved margins.
            clearance = 12 + 2 * font_size * len(metrics.footer_credit_text)
            if position == "left":
                x = min(x, metrics.width - clearance)
            elif position == "right":
                x = max(x, clearance)
            elements.append(
                text_element(
                    x=x,
                    y=y - 16 if show_number else y,
                    text=metrics.footer_credit_text,
                    layer="footer",
                    synthetic=True,
                    extra_attrs=(*footer_style, ("text-anchor", anchor)),
                )
            )
        if show_number:
            style = metrics.footer_page_number
            format_number = _roman_number if style in ("roman", "roman_total") else str
            number = format_number(page_index + 1)
            if style in ("total", "roman_total"):
                number += f"/{format_number(len(model.pages))}"
            x, anchor = positions[number_position]
            elements.append(
                text_element(
                    x=x,
                    y=y,
                    text=number,
                    layer="footer",
                    synthetic=True,
                    extra_attrs=(*footer_style, ("text-anchor", anchor)),
                )
            )
    return elements


__all__ = ["render_page_body_elements"]
