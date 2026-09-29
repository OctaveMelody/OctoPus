"""Row/measure parsing for multi-block DSB continuation systems.

The first half of the shared-grid model in ``dsb_multiblock_widths``: split
each visible row into measures, decide which are stacked continuation
fragments, and map every measure onto a grid column.  Returns None / False
outside the verified cohort so the caller keeps the legacy widths.
"""

from __future__ import annotations

from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_gap_reserves import _barline_event_indices

_PLACED_KINDS = (
    MusicTokenKind.NOTE,
    MusicTokenKind.RHYTHM_NOTE,
    MusicTokenKind.EXTENSION,
    MusicTokenKind.REST,
    MusicTokenKind.HIDDEN_REST,
)


class _Measure:
    """One measure of one row, mapped onto a grid column."""

    __slots__ = ("col", "events", "onsets", "fragment")

    def __init__(self) -> None:
        self.col: int = 0
        self.events: list[LayoutEvent] = []
        self.onsets: list[Fraction] = []
        # None for the main segment; "continuation" when stacked on a fragment
        # row inside the DSB region (the block content itself is hidden).
        self.fragment: str | None = None


def _measure_onsets(measure_events: list[LayoutEvent]) -> list[Fraction] | None:
    """Beat onset of every placed event (from the measure start).

    Extension dashes anchor where the sustained beat begins; anything else
    advances by its own duration.  A hidden rest occupies one full beat slot:
    a row-leading ``8`` pushes the visible content one beat out (Hulunbuir
    [100]: first notes at the integer step after the origin null glyph).
    """
    onsets: list[Fraction] = []
    cursor = Fraction()
    for item in measure_events:
        event = item.event
        if event.kind == MusicTokenKind.EXTENSION:
            if not onsets:
                return None
            onsets.append(cursor)
            continue
        onsets.append(cursor)
        if event.kind == MusicTokenKind.HIDDEN_REST:
            cursor += 1
            continue
        cursor += event_duration_fraction(event)
    return onsets


def _row_measures(row: list[LayoutEvent]) -> tuple[list[_Measure], int, int, bool, bool] | None:
    """Split a row into measures.

    Returns (measures, pre, n_dsb, anchored, leading): ``pre`` counts the
    measures before the in-row DSB region (for an anchored row, everything up
    to and including the measure closed by the anchor barline — the region
    may be mid-row, Hulunbuir [100] Q2/Q3); ``n_dsb`` counts the region's
    dsb-tail measures (0 when the row ends at its anchor — post-block measures
    then arrive on stacked continuation rows).  Returns None outside the
    verified cohort.
    """
    leading = row[0].event.kind == MusicTokenKind.BARLINE
    body_start = 1 if leading else 0
    if row[-1].event.kind != MusicTokenKind.BARLINE:
        return None
    bars = [index for index in _barline_event_indices(row) if index >= body_start]
    anchor_ordinal = -1
    for position, bar_index in enumerate(bars):
        if "&dsb_a" in (row[bar_index].event.code or ""):
            anchor_ordinal = position
            break
    # The leading barline may carry the anchor: a voice whose block starts at
    # the first measure keeps it on that origin barline.
    anchored_at_origin = leading and "&dsb_a" in (row[0].event.code or "")
    tail_ordinals = [
        position for position, bar_index in enumerate(bars) if row[bar_index].block == "dsb-tail"
    ]
    n_dsb = len(tail_ordinals) if (anchor_ordinal >= 0 or anchored_at_origin) else 0
    if anchor_ordinal >= 0 and not anchored_at_origin:
        # An anchored row either opens a non-empty in-row DSB region or ends
        # exactly at its anchor (post-block measures then live on continuation
        # rows, whose barlines carry the dsb-tail marks).
        if tail_ordinals and min(tail_ordinals) <= anchor_ordinal:
            return None
        if not tail_ordinals and bars[anchor_ordinal] != len(row) - 1:
            return None

    measures: list[_Measure] = []
    start = body_start
    for bar_index in bars:
        segment = list(range(start, bar_index))
        start = bar_index + 1
        if not segment:
            continue
        if len({row[i].y for i in segment}) > 1:
            return None
        measure = _Measure()
        measure.events = [row[i] for i in segment]
        events = measure.events
        if any(item.event.kind not in _PLACED_KINDS for item in events):
            return None
        onsets = _measure_onsets(events)
        if onsets is None or onsets[0] != 0:
            return None
        measure.onsets = onsets
        measures.append(measure)
    # A voice whose whole content is block material keeps a degenerate main
    # row (the leading barline only); its measures live on continuation rows.
    if not measures and not (leading or anchored_at_origin):
        return None
    # The main segment is the y of the row's first note; later y values are
    # stacked fragments (the {dsb} block content itself is hidden).
    main_y = next(
        (row[i].y for i in range(body_start, len(row))
         if row[i].event.kind != MusicTokenKind.BARLINE),
        row[0].y,
    )
    for measure in measures:
        if measure.events[0].y != main_y:
            measure.fragment = "continuation"
    # Hidden rests are in scope only as the row's leading null glyph or a
    # measure's trailing ghost marker; hidden beats inside a measure's content
    # (notes following them) are outside the verified cohort.
    for position, item in enumerate(row):
        if item.event.kind != MusicTokenKind.HIDDEN_REST or position == 0:
            continue
        measure_end = next((bar for bar in bars if bar > position), len(row) - 1)
        if position != measure_end - 1:
            return None
    anchored = anchor_ordinal >= 0 or anchored_at_origin
    if anchored_at_origin:
        pre = 0
    elif anchored:
        pre = anchor_ordinal + 1
        if pre > len(measures):
            return None
    else:
        pre = 0
    return measures, pre, n_dsb, anchored, leading


def _column_map(measures: list[_Measure], pre: int, n_dsb: int, grid_cols: int) -> bool:
    """Assign each measure to a grid column; False when the shape is unknown."""
    if pre == 0 and n_dsb == 0:
        if len(measures) != grid_cols:
            return False
        for position, measure in enumerate(measures):
            measure.col = position
        return True
    if pre + n_dsb > grid_cols:
        return False
    capacity = grid_cols - pre - n_dsb
    post = measures[pre + n_dsb :]
    visible_post = [m for m in post if m.fragment is None]
    hidden_post = [m for m in post if m.fragment is not None]
    if len(visible_post) > capacity or len(hidden_post) > n_dsb:
        return False
    for position, measure in enumerate(measures[: pre + n_dsb]):
        measure.col = position
    # Hidden post measures stack from the block-start column; visible post
    # measures take the right-hand columns in order.
    for offset, measure in enumerate(hidden_post):
        measure.col = pre + offset
    for offset, measure in enumerate(visible_post):
        measure.col = pre + n_dsb + offset
    return True


__all__ = ["_Measure", "_column_map", "_measure_onsets", "_row_measures"]
