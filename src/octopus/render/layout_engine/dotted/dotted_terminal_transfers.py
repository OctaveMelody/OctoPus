"""Typed dotted-row policies that exchange interval and terminal ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..keys import SourceEventKey, source_event_key
from ..signatures import (
    construct_role_signature,
    event_signature,
    measure_durations,
)


@dataclass(frozen=True, slots=True)
class LyriclessDottedTerminalTransfer:
    """Stable interval owners and conserved terminal release for one row."""

    reserve_event_keys: tuple[SourceEventKey, SourceEventKey]
    reserve_width: float = 9.0
    terminal_release: float = 18.0

    def __post_init__(self) -> None:
        if len(set(self.reserve_event_keys)) != 2:
            raise ValueError("dotted terminal reserve keys must be unique")
        if self.reserve_width <= 0 or self.terminal_release <= 0:
            raise ValueError("dotted terminal transfer widths must be positive")
        if self.terminal_release != len(self.reserve_event_keys) * self.reserve_width:
            raise ValueError("dotted terminal transfer must conserve total width")


def lyricless_dotted_terminal_transfer(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> LyriclessDottedTerminalTransfer | None:
    """Classify the three-measure lyricless row with two internal dotted owners."""

    if (
        len(row) != 40
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        != (10, 24, 39)
        or measure_durations(row) != (Fraction(4),) * 3
        or "zkh" not in row[0].event.decorations
    ):
        return None

    if any(
        text
        for item in row
        for text in lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
    ):
        return None

    dotted_positions = tuple(
        index
        for index, item in enumerate(row)
        if item.event.kind == MusicTokenKind.NOTE
        and event_duration_fraction(item.event) == Fraction(3, 4)
        and item.event.duration_dots == 1
        and item.event.duration_slashes == 1
    )
    if dotted_positions != (8, 19, 33):
        return None

    role_positions = tuple(
        (index, construct_role_signature(item))
        for index, item in enumerate(row)
        if item.event.construct_roles
    )
    if role_positions != (
        (3, ("tie:start",)),
        (4, ("tie:end",)),
        (6, ("tie:start",)),
        (7, ("tie:end",)),
        (14, ("tie:start",)),
        (15, ("tie:end",)),
        (17, ("tie:start",)),
        (18, ("tie:end",)),
        (19, ("tie:start",)),
        (20, ("tie:end",)),
        (28, ("tie:start",)),
        (29, ("tie:end",)),
        (34, ("tie:start",)),
        (35, ("tie:end",)),
    ):
        return None

    return LyriclessDottedTerminalTransfer(
        reserve_event_keys=(
            source_event_key(row[dotted_positions[0]]),
            source_event_key(row[dotted_positions[1]]),
        )
    )


def dotted_lyric_terminal_release_indices(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> tuple[int, ...]:
    """Return dotted lyric intervals paired with reduced terminal ownership."""

    if (
        len(row) != 28
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        != (10, 17, 27)
        or measure_durations(row) != (Fraction(4),) * 3
    ):
        return ()

    lyric_profiles = tuple(
        lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
        for item in row
    )
    if (
        max((len(texts) for texts in lyric_profiles), default=0) != 1
        or any(len(texts) > 1 for texts in lyric_profiles)
    ):
        return ()

    note = MusicTokenKind.NOTE
    barline = MusicTokenKind.BARLINE
    expected_signature = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 3), 0, 1, 1, 0),
        (note, Fraction(1, 3), 0, 1, 0, 0),
        (note, Fraction(1, 3), 0, 1, 0, 1),
        (barline, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 1, 0),
        (note, Fraction(1), 0, 0, 0, 1),
        (MusicTokenKind.EXTENSION, Fraction(1), 0, 0, 0, 0),
        (MusicTokenKind.REST, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (barline, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1), 0, 0, 0, 1),
        (barline, Fraction(), 0, 0, 0, 0),
    )
    if tuple(event_signature(item) for item in row) != expected_signature:
        return ()

    reserve_indices = tuple(
        index
        for index, item in enumerate(row[:-1])
        if item.event.kind == note
        and event_duration_fraction(item.event) == Fraction(3, 4)
        and item.event.duration_dots == 1
        and item.event.duration_slashes == 1
        and any(lyric_profiles[index])
    )
    return reserve_indices if reserve_indices == (1, 6, 12, 19) else ()


__all__ = [
    "LyriclessDottedTerminalTransfer",
    "dotted_lyric_terminal_release_indices",
    "lyricless_dotted_terminal_transfer",
]
