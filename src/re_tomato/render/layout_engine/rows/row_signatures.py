"""Pure row rhythm, onset, and lyric-host signature policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction


def row_event_has_lyric(
    row: Sequence[LayoutEvent],
    index: int,
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> bool:
    item = row[index]
    return bool(lyric_text_by_event.get((item.event.span.start.line, item.event.index), ()))


def row_event_onsets(row: Sequence[LayoutEvent]) -> tuple[Fraction, ...]:
    onset = Fraction()
    result: list[Fraction] = []
    for item in row:
        result.append(onset)
        if item.event.kind != MusicTokenKind.BARLINE:
            onset += event_duration_fraction(item.event)
    return tuple(result)


def shared_row_rhythm_signature(row: Sequence[LayoutEvent]) -> tuple[object, ...]:
    return tuple(
        (
            (
                "pitched-or-extension"
                if item.event.kind
                in {
                    MusicTokenKind.NOTE,
                    MusicTokenKind.RHYTHM_NOTE,
                    MusicTokenKind.EXTENSION,
                }
                else item.event.kind
            ),
            event_duration_fraction(item.event),
            item.event.duration_dots,
            item.event.duration_slashes,
            item.event.code.count("("),
            item.event.code.count(")"),
        )
        for item in row
    )


def shared_measure_durations_match(
    rows: Sequence[Sequence[LayoutEvent]],
    *,
    ignore_dsb_placeholders: bool = False,
) -> bool:
    durations_by_row: list[list[Fraction]] = []
    for row in rows:
        durations: list[Fraction] = []
        current = Fraction()
        for item in row:
            if ignore_dsb_placeholders and item.block == "dsb-placeholder":
                continue
            if item.event.kind == MusicTokenKind.BARLINE:
                durations.append(current)
                current = Fraction()
            else:
                current += event_duration_fraction(item.event)
        durations_by_row.append(durations)
    return bool(durations_by_row) and all(
        durations == durations_by_row[0] for durations in durations_by_row[1:]
    )


__all__ = [
    "row_event_has_lyric",
    "row_event_onsets",
    "shared_measure_durations_match",
    "shared_row_rhythm_signature",
]
