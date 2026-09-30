"""Standalone mark and inline time-signature element construction."""

from __future__ import annotations

import re

from octopus.normalization.types import MusicEvent

from ...parser.ast import MusicTokenKind
from ..core.elements import RenderElement, SvgElement, _format_reference_number
from ..core.glyphs import get_decoration_glyph
from ..core.layout_types import GEOMETRY_EPSILON, LayoutEvent, LayoutMark, LayoutPage
from .accessories import decoration_placement, is_dynamic_decoration
from .primitives import attrs as _attrs
from .primitives import text_element as _text_element
from .primitives import use_element as _use_element


def _mark_elements(layout: LayoutPage) -> list[SvgElement]:
    elements: list[SvgElement] = []
    for mark in layout.marks:
        if mark.placement == "ending-label":
            continue
        if _inline_time_signature(mark) is not None:
            continue
        if _is_standalone_glyph_decoration_mark(mark):
            continue
        elements.extend(_mark_element(mark))
    return elements


def _standalone_decoration_marks_by_host(
    layout: LayoutPage,
) -> dict[tuple[int, int, int], tuple[LayoutMark, ...]]:
    grouped: dict[tuple[int, int, int], list[LayoutMark]] = {}
    for mark in layout.marks:
        if _is_standalone_glyph_decoration_mark(mark):
            grouped.setdefault((mark.host.voice, mark.host.line, mark.host.slot), []).append(mark)
    return {host_key: tuple(items) for host_key, items in grouped.items()}


def _mark_elements_by_host(
    layout: LayoutPage,
) -> dict[tuple[int, int, int], tuple[SvgElement, ...]]:
    grouped: dict[tuple[int, int, int], list[SvgElement]] = {}
    for mark in layout.marks:
        if mark.placement == "ending-label":
            continue
        if _inline_time_signature(mark) is not None:
            continue
        if _is_standalone_glyph_decoration_mark(mark):
            continue
        grouped.setdefault((mark.host.voice, mark.host.line, mark.host.slot), []).extend(
            _mark_element(mark)
        )
    return {host_key: tuple(items) for host_key, items in grouped.items()}


def _inline_time_signature_x(mark: LayoutMark, layout: LayoutPage) -> float:
    # Oracle-verified 2026-07 (150 labels, 14 pages): a leading meter barline
    # (code |n'p:X/Y') carries its fraction stack centered on the barline
    # itself, while a mid-system meter barline places the stack one
    # within-beat step (25 natural units) to the right of the barline, in
    # stretched space.  The legacy constant +20 px was only an accidental
    # approximation of 25 * 0.8.
    host = mark.host
    if (host.event.code or "").startswith("|n"):
        return host.x
    if host.projection_kind == "grid":
        # On the shared duration grid projection_scale is the exact geometric
        # ratio, so 25 * scale reproduces the reference even when the row's
        # post-barline gap deviates from the plain 60 (As-Wished-Choir S1).
        scale = host.projection_scale
        if scale is not None:
            return host.x + 25.0 * scale
    next_event = _next_row_event(layout, host)
    if next_event is not None:
        # The reference reserves one within-beat step (25) of meter-label
        # width after a mid-system meter barline on top of the plain 35
        # barline gap, so the following note sits 60 natural units away and
        # carries the row's geometric scale.  A &zkh-decorated follower adds
        # its own 12.5 lead-in (Flower-Not-Flower p1 row 3, Autumn-Cicada
        # p1 row 7: 72.5 in both).
        reserve = 60.0
        if any("zkh" in decoration for decoration in next_event.event.decorations):
            reserve += 12.5
        return host.x + (next_event.x - host.x) * (25.0 / reserve)
    scale = host.projection_scale
    if scale is None:
        return host.x + 20
    return host.x + 25.0 * scale


def _next_row_event(layout: LayoutPage, host: LayoutEvent) -> LayoutEvent | None:
    row = [
        item
        for item in layout.events
        if item.page_index == host.page_index and item.line == host.line
    ]
    for item in sorted(row, key=lambda candidate: candidate.x):
        if (
            item is not host
            and item.x > host.x + GEOMETRY_EPSILON
            and item.event.kind
            in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE, MusicTokenKind.REST}
        ):
            return item
    return None


def _is_standalone_glyph_decoration_mark(mark: LayoutMark) -> bool:
    if (
        mark.event.kind == MusicTokenKind.DECORATION
        and bool(mark.event.decorations)
        and mark.event.decorations[0] == "ykh"
    ):
        return True
    return (
        mark.event.kind == MusicTokenKind.DECORATION
        and bool(mark.event.decorations)
        and get_decoration_glyph(mark.event.decorations[0]) is not None
        and not is_dynamic_decoration(mark.event.decorations[0])
    )


def _inline_time_signature(mark: LayoutMark) -> tuple[str, str] | None:
    if mark.event.kind != MusicTokenKind.ANNOTATION:
        return None
    value = (mark.event.value or mark.event.raw.strip('"')).strip()
    match = re.fullmatch(r"p:(\d+)/(\d+)", value)
    return (match.group(1), match.group(2)) if match else None


def _inline_time_signature_elements(
    mark: LayoutMark,
    layout: LayoutPage,
) -> list[RenderElement]:
    signature = _inline_time_signature(mark)
    if signature is None:
        return []
    numerator, denominator = signature
    x = _inline_time_signature_x(mark, layout)
    y = mark.host.y
    elements: list[RenderElement] = []
    for digit in numerator:
        elements.append(
            RenderElement(
                glyph_id=f"linshi_paihao_shuzi_{digit}",
                code=None,
                time=None,
                audio=None,
                x=x,
                y=float(int(y - 10)),
                notepos=None,
                source_event_index=mark.host.event.index,
                layer="inline-time-signature",
                construct_ids=mark.event.construct_ids,
            )
        )
    elements.append(
        RenderElement(
            glyph_id="linshi_paihao_fenxian",
            code=None,
            time=None,
            audio=None,
            x=x,
            y=float(int(y)),
            notepos=None,
            source_event_index=mark.host.event.index,
            layer="inline-time-signature",
            construct_ids=mark.event.construct_ids,
        )
    )
    for digit in denominator:
        elements.append(
            RenderElement(
                glyph_id=f"linshi_paihao_shuzi_{digit}",
                code=None,
                time=None,
                audio=None,
                x=x,
                y=float(int(y + 10)),
                notepos=None,
                source_event_index=mark.host.event.index,
                layer="inline-time-signature",
                construct_ids=mark.event.construct_ids,
            )
        )
    return elements


def score_text_attrs(dy: float) -> tuple[tuple[str, str], ...]:
    """Return the reference style attributes for score text marks.

    Quoted score annotations and repeat-ending labels share the same SVG
    typography.  Keeping the attributes in one helper is important here:
    attribute order is part of the reference serialization, not merely a
    browser rendering detail.
    """

    return _attrs(
        ("dy", _format_reference_number(dy)),
        ("fill", "#303030"),
        ("font-size", "12"),
        ("font-family", "Microsoft YaHei"),
        ("xml:space", "preserve"),
    )


def score_text_clearance_levels(event: MusicEvent) -> int:
    """Return the upper-lane clearance required by a score-text host.

    One 8px lane is reserved for each positive octave marker.  Any host that
    participates in a tie or slur needs one additional lane so text attached
    to an inside or closing note does not touch the construct.  Dynamics only
    need opener clearance, so this deliberately extends their shared base
    policy for score text.
    """

    participates_in_upper_span = any(
        any(part in {"tie", "slur"} for part in role.split(":"))
        for role in event.construct_roles
    )
    return max(event.octave, 0) + int(participates_in_upper_span)


def _mark_element(mark: LayoutMark) -> list[SvgElement]:
    event = mark.event
    x = mark.host.x
    # Above-note labels use the reference's 24px optical clearance from the
    # host baseline on every page profile; the host row already carries the
    # page-specific vertical spacing.
    y = mark.host.y - 24
    if mark.placement == "ending-label":
        text = event.value or event.raw.strip('"')
        return [
            _text_element(
                x=_format_reference_number(x + 10),
                y=_format_reference_number(mark.host.y - 9),
                text=text,
                layer="mark",
                source_event_index=event.index,
                construct_ids=event.construct_ids,
                extra_attrs=_attrs(
                    ("text-anchor", "start"),
                    ("font-size", "12"),
                    ("data-construct", "ending-label"),
                ),
            )
        ]
    if event.kind == MusicTokenKind.DECORATION and event.decorations:
        decoration = event.decorations[0]
        host_decorations = tuple(
            dict.fromkeys((*mark.host.event.decorations, *event.decorations))
        )
        placement = decoration_placement(
            mark.host.event,
            decoration,
            decorations=host_decorations,
            starts_upper_span=mark.starts_upper_span,
        )
        if event.decorations[0] == "ykh":
            return [
                _use_element(
                    "kuohu_you",
                    x=_format_reference_number(mark.host.x),
                    y=int(mark.host.y) + placement.y_offset,
                    layer="decoration",
                    source_event_index=event.index,
                )
            ]
        glyph_id = get_decoration_glyph(event.decorations[0])
        if glyph_id:
            return [
                _use_element(
                    glyph_id,
                    x=_format_reference_number(x + placement.x_offset),
                    y=int(mark.host.y) + placement.y_offset,
                    layer="decoration",
                    source_event_index=event.index,
                    construct_ids=event.construct_ids,
                )
            ]
    text = event.value or event.raw.strip('"')
    clearance = score_text_clearance_levels(mark.host.event)
    return [
        _text_element(
            x=_format_reference_number(x - 6),
            y=_format_reference_number(y),
            text=text,
            layer="mark",
            source_event_index=event.index,
            construct_ids=event.construct_ids,
            extra_attrs=score_text_attrs(4.026 - 8 * clearance),
        )
    ]


__all__ = [
    "_inline_time_signature",
    "_inline_time_signature_elements",
    "_is_standalone_glyph_decoration_mark",
    "_mark_element",
    "_mark_elements",
    "_mark_elements_by_host",
    "score_text_attrs",
    "score_text_clearance_levels",
    "_standalone_decoration_marks_by_host",
]
