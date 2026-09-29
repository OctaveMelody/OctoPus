"""Union note-group column widths for DSB continuation systems.

When one voice carries a ``{dsb}`` block, the visible rows of the system are
laid on a shared grid of beat-onset columns instead of independent row
widths.  Two shapes are supported: trailing blocks that run to the row's
final barline (As-Wished - Choir p1/p2) and mid-row blocks that close early
(As-Wished - Choir p3 system 1).  This module dispatches between the two and
converts the per-zone column grids into per-row interval widths.
"""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from .dsb_gap_reserves import _barline_event_indices
from .dsb_midrow_widths import (
    _MIDROW_FINAL_SCALE,
    _midrow_block_zone_ordinals,
    _midrow_zone_terminal,
    _model_segment_midrow,
    dsb_midrow_context,
)
from .dsb_multiblock_widths import compute_dsb_multiblock_widths
from .dsb_trailing_widths import _model_segment, dsb_continuation_context
from .dsb_union_common import (
    _DENOMINATOR_EXTRA,
    _DSB_ZONE_GAP,
    _PLACED_KINDS,
    _TERMINAL_GAP,
)


def compute_dsb_continuation_widths(
    rows: list[list[LayoutEvent]],
) -> tuple[list[tuple[float, ...]], float, bool] | None:
    """Return (per-row interval widths, denominator, mid_row) on the union grid.

    Widths are natural units between consecutive events of each row; the final
    barline is pinned separately by the projection loop. ``mid_row`` marks
    systems whose DSB block ends before the row's final barline: they scale
    with ``(right - left) / denominator`` (no +14 note-origin offset and no
    trailing +18 underlined step). Returns ``None`` when the segment content
    falls outside the verified shapes so the caller keeps the legacy widths.
    """
    context = dsb_continuation_context(rows)
    if context is not None:
        _, anchor_ordinal = context
        outcome = _compute_union_widths(
            rows,
            # The block zone is the segment after the anchor barline.
            block_zone_ordinals={anchor_ordinal + 1},
            mid_row=False,
        )
        if outcome is not None:
            widths, denominator = outcome
            return [tuple(widths) for widths in widths], denominator + _DENOMINATOR_EXTRA, False
    elif dsb_midrow_context(rows):
        block_zone_ordinals = _midrow_block_zone_ordinals(rows)
        if block_zone_ordinals is not None:
            outcome = _compute_union_widths(
                rows,
                block_zone_ordinals=block_zone_ordinals,
                mid_row=True,
            )
            if outcome is not None:
                widths, denominator = outcome
                return [tuple(widths) for widths in widths], denominator, True
    # Multi-block systems (several {dsb} regions at once, or a block of two
    # or more measures stacking fragment rows) model their own shared grid;
    # shapes outside that cohort keep the legacy widths.
    return compute_dsb_multiblock_widths(rows)


def _compute_union_widths(
    rows: list[list[LayoutEvent]],
    *,
    block_zone_ordinals: set[int],
    mid_row: bool,
) -> tuple[list[list[float]], float] | None:
    """Build the union grid zone by zone and convert it to row widths."""
    barline_count = len(_barline_event_indices(rows[0]))

    segments_by_row: list[list[list[int]]] = []
    for row in rows:
        bars = _barline_event_indices(row)
        segments: list[list[int]] = []
        start = 0
        for bar_index in bars:
            segments.append(list(range(start, bar_index)))
            start = bar_index + 1
        segments_by_row.append(segments)

    # Mid-row systems keep their leading barline as a layout event, so the
    # segment before it is empty and the real zones start at ordinal 1.
    zone_ordinals = (
        list(range(1, barline_count)) if mid_row else list(range(barline_count))
    )

    dsb_tail_final = False
    if mid_row:
        # A block region that runs to the piece's end marks the anchor row's
        # final barline with the dsb-tail identity (oracle-verified 2026-08-26
        # on As-Wished - Choir p3 system 2: its two-measure blocks close with
        # the plain 25.2 terminal instead of the DSB gap).
        for row in rows:
            if any("&dsb_a" in (item.event.code or "") for item in row) and (
                row[-1].block == "dsb-tail"
            ):
                dsb_tail_final = True
                break

    assigned: dict[tuple[int, int], float] = {}
    zone_info: dict[int, tuple[list[float], float, float]] = {}
    outcome: tuple[float, float | list[float]] | None
    for position, ordinal in enumerate(zone_ordinals):
        if mid_row:
            outcome = _model_segment_midrow(
                rows,
                segments_by_row,
                ordinal,
                is_first=position == 0,
                is_block_zone=ordinal in block_zone_ordinals,
                assigned=assigned,
            )
        else:
            outcome = _model_segment(
                rows,
                segments_by_row,
                ordinal,
                is_first=position == 0,
                is_dsb_zone=ordinal in block_zone_ordinals,
                assigned=assigned,
            )
        if outcome is None:
            return None
        last_column, leading_gaps = outcome
        if not isinstance(leading_gaps, list):
            # The trailing model returns one shared gap for the whole zone.
            leading_gaps = [leading_gaps] * len(rows)
        terminal = (
            _midrow_zone_terminal(ordinal in block_zone_ordinals, dsb_tail_final)
            if mid_row
            else _TERMINAL_GAP
        )
        zone_info[ordinal] = (leading_gaps, last_column, terminal)

    widths_by_row = _row_widths(rows, segments_by_row, assigned, zone_info)
    if widths_by_row is None:
        return None
    if mid_row:
        # Fitted natural total: c x (widest row span + one DSB zone gap),
        # where a row's span is its non-final zone widths plus its final zone
        # span (leading gap + last column).  The scale k = (right - left) /
        # total then makes every row's final zone absorb exactly the slack to
        # its page edge, since each row accumulates its own leading gaps.
        nonfinal_spans = _nonfinal_span(zone_info, zone_ordinals)
        final_gaps, final_column, _ = zone_info[zone_ordinals[-1]]
        total = float(
            _MIDROW_FINAL_SCALE
            * (
                max(
                    nonfinal + gap + final_column
                    for nonfinal, gap in zip(nonfinal_spans, final_gaps, strict=True)
                )
                + _DSB_ZONE_GAP
            )
        )
    else:
        total = 0.0
        for ordinal in zone_ordinals:
            leading_gaps, last_column, terminal = zone_info[ordinal]
            total += leading_gaps[0] + last_column + terminal
    return widths_by_row, total


def _nonfinal_span(
    zone_info: dict[int, tuple[list[float], float, float]],
    zone_ordinals: list[int],
) -> list[float]:
    """Per-row sum of non-final zone widths (leading gap + last column + terminal)."""
    spans = [0.0] * len(next(iter(zone_info.values()))[0])
    for position, ordinal in enumerate(zone_ordinals):
        if position == len(zone_ordinals) - 1:
            continue
        leading_gaps, last_column, terminal = zone_info[ordinal]
        for row_index, lead in enumerate(leading_gaps):
            spans[row_index] += lead + last_column + terminal
    return spans


def _row_widths(
    rows: list[list[LayoutEvent]],
    segments_by_row: list[list[list[int]]],
    assigned: dict[tuple[int, int], float],
    zone_info: dict[int, tuple[list[float], float, float]],
) -> list[list[float]] | None:
    """Convert zone-relative x positions into per-row interval widths.

    Rows whose first event is the leading barline (mid-row systems) start
    their width chain at that barline, so the first zone's leading gap becomes
    a real interval; rows starting on a note (trailing systems) anchor there
    instead and emit no leading interval.  Leading gaps are per-row: mid-row
    zone 1 clears each row's own meter label while every other zone shares one
    gap, so each row accumulates its own offset into the shared columns.
    """
    widths_by_row: list[list[float]] = []
    last_ordinal = max(zone_info)
    for row_index, row in enumerate(rows):
        widths: list[float] = []
        offset = 0.0
        previous_x: float | None = (
            0.0 if row[0].event.kind == MusicTokenKind.BARLINE else None
        )
        for ordinal, segment in enumerate(segments_by_row[row_index]):
            if not segment:
                # Note-anchored (trailing) rows never had empty segments on
                # the union grid; only a mid-row leading barline may leave
                # segment 0 empty.
                if previous_x is None or ordinal != 0:
                    return None
                continue
            info = zone_info.get(ordinal)
            if info is None:
                return None
            leading_gaps, last_column, terminal = info
            leading_gap = leading_gaps[row_index]
            for event_index in segment:
                item = row[event_index]
                if item.event.kind not in _PLACED_KINDS:
                    return None
                x = assigned[(row_index, event_index)] + offset + leading_gap
                if previous_x is not None:
                    widths.append(x - previous_x)
                previous_x = x
            if ordinal != last_ordinal:
                if previous_x is None:
                    return None
                segment_end = offset + leading_gap + last_column + terminal
                widths.append(segment_end - previous_x)
                previous_x = segment_end
            offset += leading_gap + last_column + terminal
        widths_by_row.append(widths)
    return widths_by_row


__all__ = [
    "compute_dsb_continuation_widths",
    "dsb_continuation_context",
]
