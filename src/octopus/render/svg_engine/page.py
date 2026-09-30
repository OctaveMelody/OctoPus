"""Page-level SVG assembly with injected rendering stages."""

from __future__ import annotations

from collections.abc import Callable

from octopus.normalization.types import ScoreModel
from octopus.render.core.elements import SvgElement
from octopus.render.core.layout_types import LayoutPage

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
    return elements


__all__ = ["render_page_body_elements"]
