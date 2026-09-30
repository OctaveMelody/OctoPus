"""Hairpin and duration-line SVG geometry."""

from __future__ import annotations

from octopus.render.core.elements import SvgElement
from octopus.render.core.layout_types import LayoutEvent, LayoutHairpinMark, LayoutPage

from ...parser.ast import MusicTokenKind
from .constructs import _line_element


def hairpin_line_elements(layout: LayoutPage) -> list[SvgElement]:
    """Build hairpin wedges in source row order.

    A ``<`` or ``>`` in an event's raw opens a hairpin that ends at the next
    event whose code carries a ``!`` mark (``-!``, ``0!``, ``8!``; barlines
    excluded) in the same row — corpus census 2026-08-28: all 152 openers are
    bang-terminated, none bracket-paired.  The wedge runs continuously from
    opener.x − 7 to terminator.x + 7 (oracle probes H1–H8 plus the Hulunbuir
    and China-In-The-Lights references), with the vertex on the opener side
    for ``<`` and on the terminator side for ``>``.

    A standalone ``<``/``>`` modifier token that attaches after an event (the
    paren-close forms ``(3' 2')<`` and ``(6, - | 6,)>``) opens a hairpin from
    its host note with the same geometry — corpus census: exactly six such
    openers, on Edelweiss p2 ×4, Looking-Back p4 and Wait-For-My-Dear.
    """

    elements: list[SvgElement] = []
    by_row: dict[tuple[int, int], list[LayoutEvent]] = {}
    detached_by_row: dict[tuple[int, int], list[LayoutHairpinMark]] = {}
    for item in layout.events:
        by_row.setdefault((item.voice, item.line), []).append(item)
    for mark in layout.hairpin_marks:
        detached_by_row.setdefault((mark.host.voice, mark.host.line), []).append(mark)

    for row_key, unsorted_row in by_row.items():
        row = sorted(unsorted_row, key=lambda event: (event.slot, event.x, event.event.index))
        detached = sorted(
            detached_by_row.get(row_key, ()),
            key=lambda mark: (mark.host.slot, mark.host.x, mark.host.event.index),
        )
        detached_index = 0
        legacy_stack: list[LayoutEvent] = []
        previous: LayoutEvent | None = None
        for row_index, item in enumerate(row):
            while (
                detached_index < len(detached)
                and detached[detached_index].host.event.index == item.event.index
            ):
                mark = detached[detached_index]
                terminator = _next_hairpin_terminator(row, row_index)
                elements.extend(detached_hairpin_lines(mark, terminator=terminator))
                detached_index += 1
            raw = item.event.raw
            if "<" not in raw and ">" not in raw:
                continue
            terminator = _next_hairpin_terminator(row, row_index)
            if terminator is not None:
                opener = "<" if "<" in raw else ">"
                elements.extend(
                    hairpin_wedge_lines(
                        item,
                        item.x - 7,
                        item.y - _hairpin_vertex_offset(item),
                        terminator.x + 7,
                        open_right=opener == "<",
                    )
                )
            else:
                for _ in range(raw.count("<")):
                    legacy_stack.append(item)
                for _ in range(raw.count(">")):
                    if legacy_stack:
                        elements.extend(matched_hairpin_lines(legacy_stack.pop(), item))
                    else:
                        elements.extend(unmatched_hairpin_lines(previous or item, item))
            previous = item
        for start in legacy_stack:
            elements.extend(unmatched_hairpin_lines(start, start))
        while detached_index < len(detached):
            elements.extend(detached_hairpin_lines(detached[detached_index]))
            detached_index += 1
    return elements


def _next_hairpin_terminator(
    row: list[LayoutEvent],
    start_index: int,
) -> LayoutEvent | None:
    for item in row[start_index + 1 :]:
        if "!" in (item.event.code or "") and item.event.kind != MusicTokenKind.BARLINE:
            return item
    return None


def matched_hairpin_lines(start: LayoutEvent, end: LayoutEvent) -> list[SvgElement]:
    x1 = start.x + 16
    x2 = max(end.x - 6, x1 + 24)
    midpoint = (x1 + x2) / 2
    y = min(start.y, end.y) - 36
    return [
        *hairpin_wedge_lines(start, x1, y, midpoint, open_right=True),
        *hairpin_wedge_lines(start, midpoint + 18, y, x2, open_right=False),
    ]


def unmatched_hairpin_lines(start: LayoutEvent, end: LayoutEvent) -> list[SvgElement]:
    x1 = min(start.x, end.x) + 12
    x2 = max(start.x, end.x) + 42
    y = min(start.y, end.y) - 36
    return hairpin_wedge_lines(start, x1, y, x2, open_right=">" not in end.event.raw)


def _hairpin_vertex_offset(item: LayoutEvent) -> float:
    """Pixels above the opener note that the hairpin vertex sits.

    Oracle probes 2026-08-28 (F1–F5, D1–D6): a plain opener sits at −30; a
    high-octave mark and an opening tie/slur parenthesis each clear one more
    lane (+8); a ``&yc`` mark or double accent clears +10; a single accent
    clears +5.  Low-octave commas do not move the vertex (probe F3).
    """

    event = item.event
    offset = 30.0
    if getattr(event, "octave", 0) and event.octave > 0:
        offset += 8
    # The anchor note sits under an overhead tie/slur arc whenever its code
    # carries a paren — an opening ``(`` for raw-attached openers, or either
    # paren for the standalone-modifier forms that close on the host
    # (oracle probes P1–P8).  One lane total, even when both appear.
    code = event.code or ""
    if "(" in code or ")" in code:
        offset += 8
    if "yc" in tuple(getattr(event, "decorations", ()) or ()) or "++" in code:
        offset += 10
    elif "+" in code:
        offset += 5
    return offset


def detached_hairpin_lines(
    mark: LayoutHairpinMark,
    *,
    terminator: LayoutEvent | None = None,
) -> list[SvgElement]:
    """Render a source modifier whose neighboring semantic boundary is explicit."""

    host = mark.host
    x1 = host.x - 7
    boundary = terminator or mark.boundary
    x2 = boundary.x + 7
    y = host.y - _hairpin_vertex_offset(host)
    return hairpin_wedge_lines(host, x1, y, x2, open_right=mark.direction == "<")


def hairpin_wedge_lines(
    source: LayoutEvent,
    x1: float,
    y: float,
    x2: float,
    *,
    open_right: bool,
) -> list[SvgElement]:
    if open_right:
        upper = (x1, y, x2, y + 5)
        lower = (x1, y, x2, y - 5)
    else:
        upper = (x1, y + 5, x2, y)
        lower = (x1, y - 5, x2, y)
    return [
        _line_element(
            x1=upper[0],
            y1=upper[1],
            x2=upper[2],
            y2=upper[3],
            source_event_index=source.event.index,
            construct_ids=source.event.construct_ids,
            data_construct="hairpin",
        ),
        _line_element(
            x1=lower[0],
            y1=lower[1],
            x2=lower[2],
            y2=lower[3],
            source_event_index=source.event.index,
            construct_ids=source.event.construct_ids,
            data_construct="hairpin",
        ),
    ]


__all__ = [
    "hairpin_line_elements",
    "hairpin_wedge_lines",
    "detached_hairpin_lines",
    "matched_hairpin_lines",
    "unmatched_hairpin_lines",
]
