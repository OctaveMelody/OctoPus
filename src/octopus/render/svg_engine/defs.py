"""Definition ordering and serialization for SVG pages."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from re import Pattern

from ..core.elements import SvgElement

_SELF_CLOSING_GLYPH_ELEMENT = re.compile(r'<([a-z]+)([^>]*?)\s*/>')


def _compact_defs_xml(xml: str) -> str:
    """Rewrite self-closing glyph elements to the compact build's explicit close.

    The compact reference tool build serializes defs leaf elements as
    ``<path ...></path>`` instead of ``<path ... />`` when the caller chooses
    the compact serialization profile.
    """

    return _SELF_CLOSING_GLYPH_ELEMENT.sub(r'<\1\2></\1>', xml)


def render_defs(
    body_elements: list[SvgElement],
    extra_defs: tuple[str, ...] = (),
    *,
    available_defs: Mapping[str, str],
    extra_defs_by_id: Callable[[tuple[str, ...]], Mapping[str, str]],
    glyph_refs: Callable[[str], tuple[str, ...]],
    grace_composite_re: Pattern[str],
    include_catalog_graces: bool = True,
    compact_profile: bool = False,
) -> str:
    """Emit referenced definitions in first-use order with support dependencies first."""
    if compact_profile:
        spaced_extra_defs_by_id = extra_defs_by_id

        def compact_extra_defs_by_id(defs: tuple[str, ...]) -> Mapping[str, str]:
            return {
                glyph_id: _compact_defs_xml(xml)
                for glyph_id, xml in spaced_extra_defs_by_id(defs).items()
            }

        available_defs = {
            glyph_id: _compact_defs_xml(xml) for glyph_id, xml in available_defs.items()
        }
        extra_defs_by_id = compact_extra_defs_by_id
    definitions = dict(available_defs)
    if not include_catalog_graces:
        definitions = {
            glyph_id: xml
            for glyph_id, xml in definitions.items()
            if not grace_composite_re.fullmatch(glyph_id)
        }
    definitions.update(extra_defs_by_id(extra_defs))

    emitted: set[str] = set()
    ordered_defs: list[str] = []
    queued_composites: list[str] = []

    def append_supports(glyph_id: str) -> None:
        xml = definitions.get(glyph_id)
        if xml is None:
            return
        for ref in glyph_refs(xml):
            if ref in emitted or ref not in definitions:
                continue
            append_supports(ref)
            emitted.add(ref)
            ordered_defs.append(definitions[ref])

    for element in body_elements:
        glyph_id = element.glyph_id
        if glyph_id is None or glyph_id in emitted or glyph_id not in definitions:
            continue
        if grace_composite_re.fullmatch(glyph_id):
            append_supports(glyph_id)
            emitted.add(glyph_id)
            queued_composites.append(glyph_id)
            continue
        emitted.add(glyph_id)
        ordered_defs.append(definitions[glyph_id])

    ordered_defs.extend(definitions[glyph_id] for glyph_id in queued_composites)
    return "<defs>\n" + "".join(ordered_defs) + "</defs>"


__all__ = ["_compact_defs_xml", "render_defs"]
