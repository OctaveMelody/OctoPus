"""Ordered SVG document assembly.

The renderer deliberately keeps the reference order as data.  Passes append
already-built fragments; no pass is allowed to reorder elements by coordinates.
This gives the large compatibility facade a small, testable document boundary
while preserving the legacy serializer byte-for-byte.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ..core.elements import SvgElement


@dataclass(frozen=True, slots=True)
class RenderPass:
    """One named, ordered document pass."""

    name: str
    fragments: Callable[[], Iterable[str]]


def run_ordered_passes(passes: Sequence[RenderPass]) -> list[str]:
    """Run passes in declaration order and discard empty fragments only."""

    result: list[str] = []
    for render_pass in passes:
        if not render_pass.name:
            raise ValueError("render pass names must be non-empty")
        result.extend(fragment for fragment in render_pass.fragments() if fragment)
    return result


def render_svg_document(
    *,
    width: float,
    height: float,
    background: SvgElement,
    definitions: str,
    score_elements: Sequence[SvgElement],
    serialize: Callable[[SvgElement], str],
) -> str:
    """Serialize one page using the fixed reference document pass order."""

    root = (
        f'<svg width="{width}" height="{height}" version="1.1" '
        f'viewBox="0 0 {width} {height}" encoding="UTF-8" '
        'xmlns="http://www.w3.org/2000/svg">'
    )
    parts = run_ordered_passes(
        (
            RenderPass("root", lambda: (root,)),
            RenderPass("background", lambda: (serialize(background),)),
            RenderPass("definitions", lambda: (definitions,)),
            RenderPass("score", lambda: (serialize(element) for element in score_elements)),
        )
    )
    # The reference puts the page background and ``defs`` directly after the
    # opening ``svg`` tag; every score element starts on its own line, and
    # the closing ``svg`` tag is appended directly to the last element with
    # no separating newline.
    prefix = "".join(parts[:3])
    suffix = parts[3:]
    if not suffix:
        return prefix + "</svg>"
    return prefix + "\n" + "\n".join(suffix) + "</svg>"


__all__ = ["RenderPass", "render_svg_document", "run_ordered_passes"]
