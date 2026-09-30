"""Custom-content SVG element construction."""

from __future__ import annotations

import re

from octopus.normalization.types import ScoreModel
from octopus.render.core.elements import SvgElement

_PAGE_BREAK_RE = re.compile(r"\[fenye\]", re.IGNORECASE)


def _empty_custom_group() -> SvgElement:
    return SvgElement(
        tag="g",
        layer="custom",
        source_event_index=None,
        attrs=(("id", "custom"),),
        synthetic=True,
    )


def safe_custom_elements(_model: ScoreModel, _page_index: int) -> list[SvgElement]:
    """Return only an inert placeholder for the explicit safe export."""
    return [_empty_custom_group()]


def custom_elements(model: ScoreModel, page_index: int) -> list[SvgElement]:
    # The first page preserves the multi-line template for a whitespace-only
    # custom section; empty continuation sections use the normal bare group.
    if not model.custom_code or (page_index > 0 and not model.custom_code.strip()):
        return [_empty_custom_group()]
    custom_pages = _PAGE_BREAK_RE.split(model.custom_code)
    custom_code = (
        custom_pages[page_index].strip() if page_index < len(custom_pages) else ""
    )
    if page_index > 0 and not custom_code:
        return [_empty_custom_group()]
    return [
        SvgElement(
            tag="raw",
            layer="custom",
            source_event_index=None,
            text=f'<g id="custom">\n{custom_code}\n</g>',
            synthetic=True,
        )
    ]


__all__ = ["custom_elements", "safe_custom_elements"]
