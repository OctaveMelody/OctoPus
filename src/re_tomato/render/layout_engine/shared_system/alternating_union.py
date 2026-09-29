"""Duration-union policy for alternating lyric/rhythm four-voice systems."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..grid.union_grid import project_union_duration_grid
from ..hidden.hidden_streams import event_duration_fraction
from ..profiles import LegacyIntrinsicProfile
from ..rows.row_signatures import shared_measure_durations_match
from ..streams import first_meter


def apply_alternating_four_voice_policies(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    visible_lyric_rows: list[bool],
    time_sig: str,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    """Apply the duration-union and closing-reserve policies in order."""

    profiles, reconciled_widths = apply_alternating_four_voice_union(
        rows,
        profiles,
        reconciled_widths,
        visible_lyric_rows=visible_lyric_rows,
        time_sig=time_sig,
    )
    return profiles, apply_alternating_four_voice_tail_reserves(
        rows,
        reconciled_widths,
        visible_lyric_rows=visible_lyric_rows,
        time_sig=time_sig,
    )


def apply_alternating_four_voice_union(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    visible_lyric_rows: list[bool],
    time_sig: str,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    """Project one alternating four-voice family onto exact duration boundaries."""

    if not _matches_alternating_four_voice_union(
        rows,
        visible_lyric_rows=visible_lyric_rows,
        time_sig=time_sig,
    ):
        return profiles, reconciled_widths
    projected = [
        list(widths)
        for widths in project_union_duration_grid(rows, profiles, reconciled_widths)
    ]
    for row, widths in zip(rows, projected, strict=True):
        widths[_index_at_onset(row, Fraction(8), barline=True) - 1] += 3.6
        widths[_index_at_onset(row, Fraction(14), barline=True) - 1] -= 18.0
    for row, widths in zip(rows[2:], projected[2:], strict=True):
        tie_end = _index_at_onset(row, Fraction(11, 2))
        widths[tie_end - 1] -= 18.0
        widths[tie_end] += 18.0
    terminal_tie_end = _index_at_onset(rows[3], Fraction(31, 2))
    projected[3][terminal_tie_end - 1] -= 18.0
    return (
        [
            replace(
                profile,
                denominator_adjustment=profile.denominator_adjustment + 10.8,
            )
            for profile in profiles
        ],
        [tuple(widths) for widths in projected],
    )


def apply_alternating_four_voice_tail_reserves(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
    *,
    visible_lyric_rows: list[bool],
    time_sig: str,
) -> list[tuple[float, ...]]:
    """Apply reversible cursor reserves in the alternating closing system."""

    if not _matches_alternating_four_voice_tail(
        rows,
        visible_lyric_rows=visible_lyric_rows,
        time_sig=time_sig,
    ):
        return reconciled_widths
    projected = [list(widths) for widths in reconciled_widths]
    row = rows[0]
    slur = _index_at_onset(row, Fraction(9))
    closing_bar = _index_at_onset(row, Fraction(14), barline=True)
    _apply_cursor_targets(projected[0], {slur: 5, slur + 1: 0})
    _apply_cursor_targets(projected[0], {closing_bar: -4, closing_bar + 1: 0})

    row = rows[2]
    entry = _index_at_onset(row, Fraction(8))
    middle_bar = _index_at_onset(row, Fraction(10), barline=True)
    middle_event = _index_at_onset(row, Fraction(10))
    closing_bar = _index_at_onset(row, Fraction(14), barline=True)
    _apply_cursor_targets(
        projected[2],
        {
            entry: 1,
            entry + 1: -3,
            middle_bar: 1,
            middle_event: 5,
            middle_event + 1: 0,
        },
    )
    _apply_cursor_targets(projected[2], {closing_bar: -4, closing_bar + 1: 0})

    row = rows[3]
    entry = _index_at_onset(row, Fraction(8))
    middle_bar = _index_at_onset(row, Fraction(10), barline=True)
    middle_event = _index_at_onset(row, Fraction(10))
    closing_tie = _index_at_onset(row, Fraction(14))
    _apply_cursor_targets(
        projected[3],
        {
            entry: 1,
            entry + 1: -3,
            middle_bar: 2,
            middle_event: 1,
            middle_event + 1: 5,
            middle_event + 2: 0,
        },
    )
    _apply_cursor_targets(projected[3], {closing_tie: 4, closing_tie + 1: 0})
    return [tuple(widths) for widths in projected]


def _matches_alternating_four_voice_union(
    rows: list[list[LayoutEvent]],
    *,
    visible_lyric_rows: list[bool],
    time_sig: str,
) -> bool:
    if (
        first_meter(time_sig) != (2, 4)
        or len(rows) != 4
        or visible_lyric_rows != [True, False, True, False]
        or len({len(row) for row in rows}) == 1
        or not shared_measure_durations_match(rows)
        or any(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) != 8
            or row[0].event.kind == MusicTokenKind.BARLINE
            for row in rows
        )
    ):
        return False
    try:
        return (
            all(_index_at_onset(row, Fraction(8), barline=True) > 0 for row in rows)
            and all(_index_at_onset(row, Fraction(14), barline=True) > 0 for row in rows)
            and all(
                row[_index_at_onset(row, Fraction(11, 2))].event.code.endswith("/)")
                for row in rows[2:]
            )
            and rows[3][_index_at_onset(rows[3], Fraction(31, 2))]
            .event.code.endswith("/)")
        )
    except ValueError:
        return False


def _matches_alternating_four_voice_tail(
    rows: list[list[LayoutEvent]],
    *,
    visible_lyric_rows: list[bool],
    time_sig: str,
) -> bool:
    if (
        first_meter(time_sig) != (2, 4)
        or len(rows) != 4
        or visible_lyric_rows != [True, False, True, False]
        or not shared_measure_durations_match(rows)
        or any(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) != 9
            for row in rows
        )
    ):
        return False
    try:
        return (
            "(" in rows[0][_index_at_onset(rows[0], Fraction(9))].event.code
            and rows[2][_index_at_onset(rows[2], Fraction(9))].event.kind
            == MusicTokenKind.EXTENSION
            and rows[3][_index_at_onset(rows[3], Fraction(9))].event.kind
            == MusicTokenKind.EXTENSION
            and rows[3][_index_at_onset(rows[3], Fraction(14))]
            .event.code.endswith("(")
        )
    except ValueError:
        return False


def _apply_cursor_targets(widths: list[float], targets: dict[int, int]) -> None:
    previous_units = 0
    for index, units in sorted(targets.items()):
        widths[index - 1] += (units - previous_units) * 3.6
        previous_units = units


def _index_at_onset(
    row: list[LayoutEvent],
    target: Fraction,
    *,
    barline: bool = False,
) -> int:
    onset = Fraction()
    for index, item in enumerate(row):
        is_barline = item.event.kind == MusicTokenKind.BARLINE
        if onset == target and is_barline == barline:
            return index
        if not is_barline:
            onset += event_duration_fraction(item.event)
    raise ValueError(f"row has no {'barline' if barline else 'event'} at onset {target}")


__all__ = [
    "apply_alternating_four_voice_policies",
    "apply_alternating_four_voice_tail_reserves",
    "apply_alternating_four_voice_union",
]
