"""Project exact shared columns into geometry keyed by source event identity."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from types import MappingProxyType

from re_tomato.parser.ast import MusicTokenKind
from re_tomato.render.layout_engine.beat_grid_engine.analysis import (
    _analyze_line_exact,
    _repartition_exact_lines,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _accidental_column_reserve,
    _annotation_widths,
    _barline_trailing_for_beat,
    _leading_width_fraction,
    _phantom_column_step_fraction,
    _trailing_or_overflow_fraction,
    _within_beat_spacing_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.grace import _grace_marker_shifts
from re_tomato.render.layout_engine.beat_grid_engine.meter import _apply_meter_label_shifts
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    BARLINE_GAP,
    PLAIN_NOTE_STEP,
    BeatShape,
    GridEventKey,
    SharedGridProjection,
    SharedGridRow,
    _ExactMeasure,
)


def project_shared_grid(
    rows: Sequence[SharedGridRow],
    *,
    majority_beat_shape: BeatShape | None = None,
) -> SharedGridProjection:
    """Project rows onto one event-keyed natural beat grid.

    The projection is a direct union of event columns.  Every note-like event
    gets an offset by :class:`GridEventKey`; no later lookup by row position or
    sorted x-coordinate is required.  Rows with different event densities,
    hidden rests, sustain events, or lyric widths therefore contribute their
    own columns to the same measure/beat union.
    """
    exact_lines = [
        _analyze_line_exact(row.events, row.lyric_text_by_event) for row in rows
    ]
    if majority_beat_shape is not None:
        exact_lines = _repartition_exact_lines(exact_lines, majority_beat_shape)
    def _zero_gap_code(code: str) -> bool:
        # ``|/`` normalizes to the ``|n`` barline code.  A meter-change label
        # (``|/"p:4/4"`` -> ``|n'p:4/4'``) keeps width in front of the first
        # note; every other attachment (labels, octave marks) does not.
        return code.startswith("|n") and "'p:" not in code

    leading_barlines = [
        next((e for e in row.events if e.kind == MusicTokenKind.BARLINE), None)
        for row in rows
    ]
    zero_gap_leading = bool(rows) and all(
        line
        and not line[0]
        and barline is not None
        and _zero_gap_code(barline.code or "")
        for line, barline in zip(exact_lines, leading_barlines, strict=True)
    )
    measure_count = max((len(line) for line in exact_lines), default=0)
    event_x_offsets: dict[GridEventKey, Fraction] = {}
    event_onsets: dict[GridEventKey, Fraction] = {}
    lyric_overflows: dict[GridEventKey, Fraction] = {}
    event_positions: dict[GridEventKey, tuple[int, int, int]] = {}
    barline_x_offsets: list[Fraction] = []
    measure_ranges: list[tuple[Fraction, Fraction]] = []
    measure_widths: list[Fraction] = []
    measure_start = Fraction(0, 1)

    for measure_index in range(measure_count):
        line_measures: list[_ExactMeasure] = [
            line[measure_index] if measure_index < len(line) else []
            for line in exact_lines
        ]
        beat_count = max((len(measure) for measure in line_measures), default=0)
        beat_starts: list[Fraction] = []
        beat_columns: list[list[Fraction]] = []
        next_start = Fraction(0, 1)
        last_column = Fraction(0, 1)
        for beat_index in range(beat_count):
            beat_starts.append(next_start)
            columns_items = [
                measure[beat_index] if beat_index < len(measure) else []
                for measure in line_measures
            ]
            item_count = max((len(items) for items in columns_items), default=0)
            columns: list[Fraction] = []
            if item_count:
                columns.append(
                    max(
                        (
                            _leading_width_fraction(item[0].event, True, None)
                            + _annotation_widths(item[0].event)[0]
                            for item in columns_items
                            if item
                        ),
                        default=Fraction(0, 1),
                    )
                )
                for item_index in range(1, item_count):
                    intra_row = max(
                        (
                            _within_beat_spacing_fraction(
                                items[item_index - 1], items[item_index]
                            )
                            for items in columns_items
                            if item_index < len(items)
                        ),
                        default=Fraction(0, 1),
                    )
                    # A row whose beat ends before this column still reserves the step
                    # into it: its syllable overflow pushes the shared column right.
                    # Oracle-verified 2026-08-23: base is the next column's target
                    # spacing and only the overflow applies (no dot trail).
                    phantom = max(
                        (
                            _phantom_column_step_fraction(
                                columns_items, item_index, items
                            )
                            for items in columns_items
                            if item_index == len(items) and items
                        ),
                        default=Fraction(0, 1),
                    )
                    columns.append(columns[-1] + max(intra_row, phantom))
            last_column = columns[-1] if columns else Fraction(0, 1)
            beat_columns.append(columns)
            own_reserves = [
                _accidental_column_reserve([items]) if items else Fraction(0, 1)
                for items in columns_items
            ]
            union_reserve = _accidental_column_reserve(columns_items)
            terminals = [
                # A row that stops short of the last shared column already spent its
                # trailing space on the phantom step above; only its own accidental
                # reserve remains.
                _trailing_or_overflow_fraction(
                    [item.event for item in items],
                    items[-1].overflow,
                    own_reserve,
                )
                if items and len(items) == item_count
                else own_reserve
                for items, own_reserve in zip(columns_items, own_reserves, strict=True)
            ]
            # Oracle probe I (2026-08-23): accidentals in different columns of
            # different full rows reserve per union column, so the beat's union
            # reserve can exceed every single row's own contribution.
            terminal = max(max(terminals, default=Fraction(0, 1)), union_reserve)
            candidates: list[Fraction] = []
            for items, trailing in zip(columns_items, terminals, strict=True):
                if not items:
                    continue
                column_index = min(len(items) - 1, len(columns) - 1)
                candidates.append(
                    columns[column_index]
                    + Fraction(PLAIN_NOTE_STEP)
                    + trailing
                )
            base = last_column + Fraction(PLAIN_NOTE_STEP) + terminal
            next_start += max(base, *candidates) if candidates else base

        for beat_index, beat_start in enumerate(beat_starts):
            columns = beat_columns[beat_index]
            for row_index, measure in enumerate(line_measures):
                if beat_index >= len(measure):
                    continue
                items = measure[beat_index]
                for item_index, item in enumerate(items):
                    column = columns[item_index] if item_index < len(columns) else last_column
                    x_offset = measure_start + beat_start + column
                    key = GridEventKey.for_event(item.event, rows[row_index].voice_index)
                    event_x_offsets[key] = x_offset
                    event_onsets[key] = item.onset
                    lyric_overflows[key] = item.overflow
                    event_positions[key] = (measure_index, beat_index, item_index)

        if beat_count:
            last_beat_item_count = max(
                (
                    len(measure[beat_count - 1])
                    for measure in line_measures
                    if beat_count - 1 < len(measure)
                ),
                default=0,
            )
            last_beat_columns = [
                measure[beat_count - 1]
                for measure in line_measures
                if beat_count - 1 < len(measure)
            ]
            barline_union_reserve = _accidental_column_reserve(last_beat_columns)
            bar_trailing_candidates = [
                _barline_trailing_for_beat(
                    items,
                    len(items) == last_beat_item_count,
                    _accidental_column_reserve([items]),
                )
                for items in last_beat_columns
            ]
            bar_trailing = max(bar_trailing_candidates + [barline_union_reserve])
            bar_relative = beat_starts[-1] + last_column + Fraction(BARLINE_GAP) + bar_trailing
        else:
            bar_relative = Fraction(0, 1)
        barline_x = measure_start + bar_relative
        barline_x_offsets.append(barline_x)
        measure_ranges.append((measure_start, barline_x))
        measure_widths.append(bar_relative)
        if not beat_count and zero_gap_leading:
            # A ``|/`` opening barline is zero-width: the following notes start
            # at the left edge, on top of the barline (see _analyze_line_exact).
            measure_start = barline_x
        else:
            measure_start = barline_x + Fraction(BARLINE_GAP)

    _apply_meter_label_shifts(rows, event_x_offsets, barline_x_offsets)

    natural_width = barline_x_offsets[-1] if barline_x_offsets else Fraction(0, 1)
    if all(line and not line[0] for line in exact_lines):
        # Oracle-verified 2026-08-23 (compressed leading-barline probes + NITD p4):
        # when every row opens with a barline, the reference's natural width is
        # 2.5 less than the geometric sum even though the rendered first gap stays
        # one full BARLINE_GAP. Only the compression scale changes; every offset
        # and the right-edge-anchored final barline are unaffected.
        natural_width -= Fraction(5, 2)
        if zero_gap_leading:
            # A zero-width ``|/`` opening barline tightens the natural width by
            # another 2.5 (oracle-verified 2026-08-23: As-Wished p2 L77-L84 —
            # every content event of all five rows fits within 0.15px at this
            # width; the one-gap NITD p4 model keeps the single 2.5).
            natural_width -= Fraction(5, 2)
    grace_shifts = _grace_marker_shifts(
        rows,
        exact_lines,
        event_positions,
        event_x_offsets,
        event_onsets,
        barline_x_offsets,
    )
    return SharedGridProjection(
        event_x_offsets=MappingProxyType(event_x_offsets),
        event_onsets=MappingProxyType(event_onsets),
        lyric_overflows=MappingProxyType(lyric_overflows),
        barline_x_offsets=tuple(barline_x_offsets),
        measure_ranges=tuple(measure_ranges),
        measure_widths=tuple(measure_widths),
        natural_width=natural_width,
        event_grace_shifts=MappingProxyType(grace_shifts[0]),
        barline_grace_shifts=grace_shifts[1],
        grace_reservation_total=grace_shifts[2],
        grace_left_delta=grace_shifts[3],
    )


# More explicit spelling for callers that want to make the event-keyed nature
# of the operation visible at the call site.
project_event_keyed_grid = project_shared_grid
