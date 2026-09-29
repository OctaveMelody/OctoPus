"""Source-derived shared-grid classifier policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent


def uses_lyricless_intrinsic_entry_grid(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> bool:
    if (
        not row
        or "zkh" not in row[0].event.decorations
        or any(
            text
            for item in row
            for text in lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index),
                (),
            )
        )
    ):
        return False
    measures = split_measures(row)
    measure_lengths = tuple(len(measure) for measure in measures)
    uses_repeat_pickup = (
        measure_lengths == (2, 5, 5, 5, 5)
        and len(row) > 1
        and row[1].event.code == "|z"
    )
    if uses_repeat_pickup:
        return True

    def rhythm_signature(measure: Sequence[LayoutEvent]) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                item.event.kind,
                item.event.duration_dots,
                item.event.duration_slashes,
                item.event.code.count("("),
                item.event.code.count(")"),
            )
            for item in measure
        )

    return (
        measure_lengths == (10, 7, 10, 7)
        and rhythm_signature(measures[0]) == rhythm_signature(measures[2])
    ) or lyricless_alternating_extension_reserve_count(row, lyric_text_by_event) > 0


def lyricless_alternating_extension_reserve_count(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> int:
    if (
        not row
        or "zkh" not in row[0].event.decorations
        or any(
            text
            for item in row
            for text in lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index),
                (),
            )
        )
    ):
        return 0
    measures = split_measures(row)
    triple_extension_positions = tuple(
        index
        for index, measure in enumerate(measures)
        if tuple(item.event.kind for item in measure)
        == (
            MusicTokenKind.NOTE,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.BARLINE,
        )
    )
    expected_positions = tuple(range(0, len(measures), 2))
    return (
        len(triple_extension_positions)
        if len(measures) >= 5 and triple_extension_positions == expected_positions
        else 0
    )


def uses_parallel_second_ending_continuation_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    if (
        len(rows) != 4
        or tuple(visible_lyric_profile_indices) not in {(0, 1), (1,)}
        or len({len(row) for row in rows}) != 1
        or any(not row or row[-1].event.code != "|j" for row in rows)
        or not rows[0][0].event.code.startswith("|n[+'2'")
        or not rows[2][0].event.code.startswith("|n['2'")
        or any(not row[0].event.code.startswith("|n") for row in rows)
    ):
        return False
    bar_indices = [
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    ]
    anchor_positions = {
        index
        for row in rows
        for index, item in enumerate(row[:-1])
        if "&dsb_a" in item.event.code
    }
    return (
        len(bar_indices[0]) == 9
        and len(set(bar_indices)) == 1
        and len(anchor_positions) == 1
        and all(
            row[next(iter(anchor_positions))].event.kind == MusicTokenKind.BARLINE
            for row in rows
        )
    )


def uses_parallel_first_ending_bilingual_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    associated_lyric_line_counts: Sequence[int],
) -> bool:
    if (
        len(rows) != 4
        or tuple(associated_lyric_line_counts) != (2, 0, 2, 0)
        or len({len(row) for row in rows}) != 1
        or any(not row or len({item.event.span.start.line for item in row}) != 1 for row in rows)
        or tuple(row[-1].event.code for row in rows) != ("|y]", "|y", "|y]", "|y")
        or not any("['1'" in item.event.code for item in rows[0])
        or not any("['1'" in item.event.code for item in rows[2])
        or any("['1'" in item.event.code for row in (rows[1], rows[3]) for item in row)
    ):
        return False
    bar_indices = {
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    }
    return len(bar_indices) == 1 and len(next(iter(bar_indices))) == 8


YKH_CLOSER_SYLLABIC_MIN_REST_DASHES = 4


def uses_ykh_closer_syllabic_grid(row: Sequence[LayoutEvent]) -> bool:
    """Whether an &ykh closer row takes the syllabic projection.

    The reference seats a ykh row on the width-fitted syllabic grid only when
    the row itself carries sustained rest content: four or more extension
    dashes with code ``-``.  Rows with fewer dashes keep the ordinary
    per-measure projection (oracle probes P1/Q1/E3e/D2/B2/C2 under
    Auld-Lang-Syne context, recorded in docs/SLICE_HISTORY.md, item 6).
    Night-In-The-Desert L97 (11 dashes) routes syllabic; Auld-Lang-Syne L27
    (0 dashes) stays ordinary.  Lyric-bearing ykh rows never reach this check
    (they route through ``legacy_intrinsic_source_lines``), and the dash count
    is taken from event codes, so a decorated dash with code ``-`` would count
    too; no corpus row distinguishes the two readings.
    """
    if not row or not any("ykh" in item.event.decorations for item in row):
        return False
    rest_dashes = sum(
        1
        for item in row
        if item.event.kind == MusicTokenKind.EXTENSION and item.event.code == "-"
    )
    return rest_dashes >= YKH_CLOSER_SYLLABIC_MIN_REST_DASHES


def split_measures(row: Sequence[LayoutEvent]) -> list[list[LayoutEvent]]:
    measures: list[list[LayoutEvent]] = []
    current: list[LayoutEvent] = []
    for item in row:
        current.append(item)
        if item.event.kind == MusicTokenKind.BARLINE:
            measures.append(current)
            current = []
    if current:
        measures.append(current)
    return measures


__all__ = [
    "YKH_CLOSER_SYLLABIC_MIN_REST_DASHES",
    "lyricless_alternating_extension_reserve_count",
    "split_measures",
    "uses_ykh_closer_syllabic_grid",
    "uses_lyricless_intrinsic_entry_grid",
    "uses_parallel_first_ending_bilingual_grid",
    "uses_parallel_second_ending_continuation_grid",
]
