"""Source-derived shared generated-terminal grid classifiers."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..signatures import measure_durations, terminal_signature


def uses_shared_dotted_generated_terminal_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    if (
        len(rows) != 3
        or tuple(visible_lyric_profile_indices) != (1,)
        or any(len(row) != 19 or row[-1].event.code != "|w" for row in rows)
    ):
        return False
    bar_indices = {
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    }
    if bar_indices != {(1, 11, 18)}:
        return False
    expected = (
        (MusicTokenKind.NOTE, 0, 1, 0, 0),
        (MusicTokenKind.NOTE, 0, 2, 0, 0),
        (MusicTokenKind.NOTE, 0, 2, 1, 0),
        (MusicTokenKind.NOTE, 0, 2, 0, 1),
        (MusicTokenKind.NOTE, 1, 1, 0, 0),
        (MusicTokenKind.NOTE, 1, 0, 0, 0),
    )
    return all(
        tuple(
            (
                item.event.kind,
                item.event.duration_dots,
                item.event.duration_slashes,
                item.event.code.count("("),
                item.event.code.count(")"),
            )
            for item in row[12:18]
        )
        == expected
        for row in rows
    )


def uses_three_authority_dotted_generated_terminal_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    if (
        len(rows) != 3
        or tuple(visible_lyric_profile_indices) != (0, 1, 2)
        or sorted(len(row) for row in rows) != [18, 19, 21]
        or any(not row or row[-1].event.code != "|w" for row in rows)
    ):
        return False
    bar_indices = tuple(
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    )
    if bar_indices != ((1, 12, 18), (1, 9, 17), (1, 12, 20)):
        return False
    if [measure_durations(row) for row in rows] != [
        (Fraction(1, 4), Fraction(4), Fraction(7, 2)),
    ] * 3:
        return False
    short_terminal = (
        (MusicTokenKind.NOTE, Fraction(1, 4), 0, 2, 0, 0),
        (MusicTokenKind.NOTE, Fraction(3, 4), 1, 1, 1, 0),
        (MusicTokenKind.NOTE, Fraction(1), 0, 0, 0, 1),
        (MusicTokenKind.EXTENSION, Fraction(1), 0, 0, 0, 0),
        (MusicTokenKind.REST, Fraction(1, 2), 0, 1, 0, 0),
    )
    long_terminal = (
        (MusicTokenKind.NOTE, Fraction(1, 4), 0, 2, 0, 0),
        (MusicTokenKind.NOTE, Fraction(3, 4), 1, 1, 1, 0),
        (MusicTokenKind.NOTE, Fraction(1, 2), 0, 1, 0, 1),
        (MusicTokenKind.NOTE, Fraction(1, 4), 0, 2, 1, 0),
        (MusicTokenKind.NOTE, Fraction(1, 4), 0, 2, 0, 1),
        (MusicTokenKind.NOTE, Fraction(1), 0, 0, 0, 0),
        (MusicTokenKind.REST, Fraction(1, 2), 0, 1, 0, 0),
    )
    return [terminal_signature(row) for row in rows] == [
        short_terminal,
        long_terminal,
        long_terminal,
    ]


def uses_two_authority_dotted_generated_terminal_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    if (
        len(rows) != 3
        or tuple(visible_lyric_profile_indices) != (0, 1)
        or tuple(len(row) for row in rows) != (22, 20, 20)
        or any(not row or row[-1].event.code != "|w" for row in rows)
    ):
        return False
    bars = tuple(
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    )
    if bars != ((1, 11, 21), (1, 10, 19), (1, 9, 19)):
        return False
    if [measure_durations(row) for row in rows] != [
        (Fraction(1, 2), Fraction(4), Fraction(15, 4)),
    ] * 3:
        return False
    note = MusicTokenKind.NOTE
    hidden = MusicTokenKind.HIDDEN_REST
    primary = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (note, Fraction(3, 4), 1, 1, 0, 1),
    )
    secondary = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (note, Fraction(3, 4), 1, 1, 0, 1),
    )
    tertiary = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (hidden, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (note, Fraction(3, 4), 1, 1, 0, 1),
    )
    return [terminal_signature(row) for row in rows] == [primary, secondary, tertiary]


def uses_one_authority_generated_terminal_cadence_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    if (
        len(rows) != 3
        or tuple(visible_lyric_profile_indices) != (1,)
        or tuple(len(row) for row in rows) != (18, 18, 20)
        or any(not row or row[-1].event.code != "|w" for row in rows)
    ):
        return False
    bars = tuple(
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    )
    if bars != ((2, 12, 17), (2, 12, 17), (2, 12, 19)):
        return False
    if [measure_durations(row) for row in rows] != [
        (Fraction(1, 2), Fraction(4), Fraction(7, 2)),
    ] * 3:
        return False
    note = MusicTokenKind.NOTE
    ordinary = (
        (note, Fraction(1), 0, 0, 0, 0),
        (MusicTokenKind.EXTENSION, Fraction(1), 0, 0, 0, 0),
        (MusicTokenKind.EXTENSION, Fraction(1), 0, 0, 0, 0),
        (MusicTokenKind.REST, Fraction(1, 2), 0, 1, 0, 0),
    )
    dotted = (
        (note, Fraction(1), 0, 0, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(3, 4), 1, 1, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
    )
    return [terminal_signature(row) for row in rows] == [ordinary, ordinary, dotted]


__all__ = [
    "uses_one_authority_generated_terminal_cadence_grid",
    "uses_shared_dotted_generated_terminal_grid",
    "uses_three_authority_dotted_generated_terminal_grid",
    "uses_two_authority_dotted_generated_terminal_grid",
]
