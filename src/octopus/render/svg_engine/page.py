"""Page-level SVG assembly with injected rendering stages."""

from __future__ import annotations

from collections.abc import Callable

from octopus.normalization.types import ScoreModel
from octopus.render.core.elements import SvgElement
from octopus.render.core.layout_types import LayoutPage

from .primitives import text_element
from .types import GraceRenderPlan


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
        footer_style = (("font-family", "Arial"), ("font-size", "12"), ("fill", "#1b1b1b"))
        y = metrics.height - 12
        positions = {
            "left": (max(12, metrics.margin_left), "start"),
            "center": (metrics.width / 2, "middle"),
            "right": (metrics.width - max(12, metrics.margin_right), "end"),
        }
        number_position = metrics.footer_page_number_position
        show_number = metrics.footer_page_number in ("number", "total")
        if metrics.footer_credit and metrics.footer_credit_text:
            position = metrics.footer_credit_position
            x, anchor = positions[position]
            elements.append(
                text_element(
                    x=x,
                    y=y - 16 if show_number and position == number_position else y,
                    text=metrics.footer_credit_text,
                    layer="footer",
                    synthetic=True,
                    extra_attrs=(*footer_style, ("text-anchor", anchor)),
                )
            )
        if show_number:
            number = str(page_index + 1)
            if metrics.footer_page_number == "total":
                number += f"/{len(model.pages)}"
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
