"""Compute floating natural layouts, measure widths, and compression scales."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from re_tomato.normalization.types import MusicEvent
from re_tomato.render.layout_engine.beat_grid_engine.analysis import analyze_line_with_lyric_text
from re_tomato.render.layout_engine.beat_grid_engine.spacing import (
    beat_barline_trailing,
    beat_terminal,
    leading_width,
    within_beat_spacing,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    BARLINE_GAP,
    FINAL_SYMBOL_WIDTH,
    PLAIN_NOTE_STEP,
    UNDERLINED_NOTE_STEP,
    BeatGridLayout,
    Line,
    Measure,
)


def natural_layout(lines: Sequence[Line]) -> BeatGridLayout:
    """Natural (uncompressed) layout of a group of analyzed lines.

    ``lines[line]`` is the line's measures (from :func:`analyze_line`). Returns
    the barline x offsets, the per-line note x offsets, and the final barline x
    offset, all measured from the group start (offset 0).
    """
    line_measures: list[Line] = [list(line) for line in lines]
    measure_count = max((len(m) for m in line_measures), default=0)
    measure_start = 0.0
    end_offset = 0.0
    bar_x_offsets: list[float] = []
    note_x_offsets: list[list[float]] = [[] for _ in line_measures]
    for measure_index in range(measure_count):
        line_beats: list[Measure] = [
            lm[measure_index] if measure_index < len(lm) else [] for lm in line_measures
        ]
        beat_count = max((len(b) for b in line_beats), default=0)
        beat_starts: list[float] = []
        next_start = 0.0
        last_column = 0.0
        beat_columns: list[list[float]] = []
        for beat_index in range(beat_count):
            beat_starts.append(next_start)
            columns_items = [
                lb[beat_index] if beat_index < len(lb) else [] for lb in line_beats
            ]
            item_count = max((len(c) for c in columns_items), default=0)
            columns: list[float] = []
            if item_count > 0:
                columns = [
                    max(
                        (leading_width(c[0][0], True, None) for c in columns_items if c),
                        default=0.0,
                    )
                ]
                for item_index in range(1, item_count):
                    step = max(
                        (
                            within_beat_spacing(
                                c[item_index - 1][0],
                                c[item_index][0],
                                c[item_index - 1][1],
                            )
                            for c in columns_items
                            if item_index < len(c)
                        ),
                        default=0.0,
                    )
                    columns.append(columns[item_index - 1] + step)
            last_column = columns[-1] if columns else 0.0
            beat_columns.append(columns)
            terminal = max(
                (beat_terminal([item[0] for item in c]) for c in columns_items),
                default=0.0,
            )
            candidates = []
            for c in columns_items:
                if not c:
                    continue
                column_index = min(len(c) - 1, len(columns) - 1)
                candidates.append(
                    columns[column_index]
                    + PLAIN_NOTE_STEP
                    + beat_terminal([item[0] for item in c])
                    + c[-1][1]
                )
            base = last_column + PLAIN_NOTE_STEP + terminal
            next_start += max(base, *candidates) if candidates else base
        for beat_index in range(beat_count):
            for line_index, lb in enumerate(line_beats):
                if beat_index < len(lb):
                    for item_index in range(len(lb[beat_index])):
                        column = (
                            beat_columns[beat_index][item_index]
                            if item_index < len(beat_columns[beat_index])
                            else last_column
                        )
                        note_x_offsets[line_index].append(
                            measure_start + beat_starts[beat_index] + column
                        )
        if beat_count == 0:
            bar_relative = 0.0
        else:
            bar_trailing = max(
                (
                    beat_barline_trailing(lb[beat_count - 1])
                    for lb in line_beats
                    if beat_count - 1 < len(lb)
                ),
                default=0.0,
            )
            bar_relative = beat_starts[-1] + last_column + BARLINE_GAP + bar_trailing
        bar_x = measure_start + bar_relative
        bar_x_offsets.append(bar_x)
        end_offset = bar_x
        measure_start = bar_x + BARLINE_GAP
    return BeatGridLayout(
        bar_x_offsets=tuple(bar_x_offsets),
        note_x_offsets=tuple(tuple(items) for items in note_x_offsets),
        end_offset=end_offset,
    )


def natural_measure_widths(layout: BeatGridLayout) -> tuple[float, ...]:
    """Return natural interval widths between successive beat-grid barlines."""
    if not layout.bar_x_offsets:
        return ()
    previous = 0.0
    widths: list[float] = []
    for bar_x in layout.bar_x_offsets:
        widths.append(bar_x - previous)
        previous = bar_x
    return tuple(widths)


def natural_measure_widths_for_lines(
    lines: Sequence[Sequence[MusicEvent]],
    lyric_text_by_line: Sequence[Mapping[tuple[int, int], Sequence[str]]],
) -> tuple[float, ...] | None:
    """Build natural shared-measure widths from normalized line associations.

    ``None`` means the lines do not expose one common measure topology.  The
    outer shared-system reconciler treats that as a near miss and leaves its
    existing family-specific policy in charge.
    """
    if len(lines) != len(lyric_text_by_line) or not lines:
        return None
    analyzed = [
        analyze_line_with_lyric_text(events, lyrics)
        for events, lyrics in zip(lines, lyric_text_by_line, strict=True)
    ]
    if not analyzed or len({len(line) for line in analyzed}) != 1:
        return None
    return natural_measure_widths(natural_layout(analyzed))


def compression_scale(available: float, natural_end_offset: float) -> float:
    """Scale that fits the natural layout into the available width.

    ``available`` is the usable width (right edge minus start). Mirrors the
    reference: ``scale = (available + 14) / (natural_end + 25)`` where 14 is
    ``FINAL_SYMBOL_WIDTH`` and 25 is ``UNDERLINED_NOTE_STEP``.
    """
    return (available + FINAL_SYMBOL_WIDTH) / (natural_end_offset + UNDERLINED_NOTE_STEP)
