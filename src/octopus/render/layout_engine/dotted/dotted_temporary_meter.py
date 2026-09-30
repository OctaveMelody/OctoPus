"""Typed reserve policy for the temporary-meter dotted row family."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..keys import source_event_key
from ..signatures import (
    construct_role_signature,
    measure_durations,
    terminal_signature,
)
from ..streams import first_meter
from .dotted_policy_types import (
    SourceIntervalAdjustment,
    SourceIntervalRetention,
)


@dataclass(frozen=True, slots=True)
class DottedTemporaryMeterReserve:
    """Source-owned reserve transfer at a temporary-meter dotted row."""

    retentions: tuple[SourceIntervalRetention, ...]
    additions: tuple[SourceIntervalAdjustment, ...]
    expected_denominator: float
    final_denominator: float

    def __post_init__(self) -> None:
        if len(self.retentions) != 1 or len(self.additions) != 2:
            raise ValueError("temporary-meter dotted reserve has an invalid owner count")
        all_keys = tuple(item.event_key for item in (*self.retentions, *self.additions))
        if len(set(all_keys)) != len(all_keys):
            raise ValueError("temporary-meter dotted reserve keys must be unique")
        if not isfinite(self.expected_denominator) or not isfinite(self.final_denominator):
            raise ValueError("temporary-meter dotted denominators must be finite")
        if abs(self.expected_denominator - 862.8) > GEOMETRY_EPSILON:
            raise ValueError("temporary-meter dotted base denominator must be 862.8")
        if abs(self.final_denominator - 864.6) > GEOMETRY_EPSILON:
            raise ValueError("temporary-meter dotted final denominator must be 864.6")
        if abs(self.denominator_change - 1.8) > GEOMETRY_EPSILON:
            raise ValueError("temporary-meter dotted denominator change must be 1.8")
        expected_retentions = ((52.2, 43.2),)
        actual_retentions = tuple(
            (item.expected_width, item.retained_width) for item in self.retentions
        )
        if any(
            abs(actual - expected) > GEOMETRY_EPSILON
            for actual_pair, expected_pair in zip(
                actual_retentions, expected_retentions, strict=True
            )
            for actual, expected in zip(actual_pair, expected_pair, strict=True)
        ):
            raise ValueError(
                "temporary-meter dotted retention must measure 52.2 to 43.2"
            )
        expected_additions = ((27.0, 36.0), (23.4, 25.2))
        actual_additions = tuple(
            (item.expected_width, item.adjusted_width) for item in self.additions
        )
        if any(
            abs(actual - expected) > GEOMETRY_EPSILON
            for actual_pair, expected_pair in zip(
                actual_additions, expected_additions, strict=True
            )
            for actual, expected in zip(actual_pair, expected_pair, strict=True)
        ):
            raise ValueError(
                "temporary-meter dotted additions must measure 27.0 to 36.0 and "
                "23.4 to 25.2"
            )

    @property
    def denominator_change(self) -> float:
        return self.final_denominator - self.expected_denominator


def dotted_temporary_meter_reserve(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
    *,
    time_sig: str,
) -> DottedTemporaryMeterReserve | None:
    """Admit the unique 4/4 row with an internal 2/4 meter transition."""

    meter_markers = tuple(
        marker
        for item in row
        for marker in ("'p:2/4'", "'p:4/4'")
        if marker in item.event.code
    )
    marker_count = sum(item.event.code.count("'p:") for item in row)
    if (
        first_meter(time_sig) != (4, 4)
        or len(row) != 34
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
        )
        != (8, 13, 23, 33)
        or measure_durations(row) != (Fraction(4), Fraction(2), Fraction(4), Fraction(4))
        or row[-1].event.code != "|"
        or meter_markers != ("'p:2/4'", "'p:4/4'")
        or marker_count != 2
        or row[8].event.code != "|'p:2/4'"
        or row[13].event.code != "|z'p:4/4'"
    ):
        return None

    row_keys = {(item.event.span.start.line, item.event.index) for item in row}
    row_lyrics = {key: texts for key, texts in lyric_text_by_event.items() if key in row_keys}
    lyric_profiles = tuple(
        row_lyrics.get((item.event.span.start.line, item.event.index), ()) for item in row
    )
    if (
        not any(text for texts in lyric_profiles for text in texts)
        or any(len(texts) > 2 for texts in lyric_profiles)
    ):
        return None

    note = MusicTokenKind.NOTE
    if terminal_signature(row) != (
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
    ):
        return None

    temporary_closer = row[9].event
    if not (
        temporary_closer.kind == note
        and event_duration_fraction(temporary_closer) == Fraction(1)
        and "ykh" in temporary_closer.code
        and "tie:end" in construct_role_signature(row[9])
    ):
        return None
    if not (
        row[22].event.kind == note
        and event_duration_fraction(row[22].event) == Fraction(1, 4)
        and row[22].event.duration_slashes == 2
        and row[22].event.duration_dots == 0
    ):
        return None

    return DottedTemporaryMeterReserve(
        retentions=(SourceIntervalRetention(source_event_key(row[13]), 52.2, 43.2),),
        additions=(
            SourceIntervalAdjustment(source_event_key(row[9]), 27.0, 36.0),
            SourceIntervalAdjustment(source_event_key(row[22]), 23.4, 25.2),
        ),
        expected_denominator=862.8,
        final_denominator=864.6,
    )


def restored_meter_borrowed_cursor_indices(
    row: Sequence[LayoutEvent],
    *,
    time_sig: str,
) -> frozenset[int]:
    """Return restored-meter events that still carry the temporary borrowed reserve."""

    if (
        first_meter(time_sig) != (4, 4)
        or len(row) <= 34
        or tuple(event_duration_fraction(item.event) for item in row[:3])
        != (Fraction(1, 4), Fraction(3, 4), Fraction(1, 2))
        or not any(
            ":tie:" in role and role.endswith(":start")
            for role in row[1].event.construct_roles
        )
        or not any(
            ":tie:" in role and role.endswith(":end")
            for role in row[2].event.construct_roles
        )
    ):
        return frozenset()
    temporary = tuple(
        index for index, item in enumerate(row) if "'p:2/4'" in item.event.code
    )
    restored = tuple(
        index for index, item in enumerate(row) if "'p:4/4'" in item.event.code
    )
    if len(temporary) != 1 or len(restored) != 1 or temporary[0] >= restored[0]:
        return frozenset()
    onset = Fraction()
    borrowed: set[int] = set()
    for index in range(restored[0] + 1, len(row)):
        if onset >= 3 or row[index].event.kind == MusicTokenKind.BARLINE:
            break
        borrowed.add(index)
        onset += event_duration_fraction(row[index].event)
    return frozenset(borrowed)


__all__ = [
    "DottedTemporaryMeterReserve",
    "dotted_temporary_meter_reserve",
    "restored_meter_borrowed_cursor_indices",
]
