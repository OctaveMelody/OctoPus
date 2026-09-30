"""Shared-system dotted reserve classification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..keys import source_event_key
from ..signatures import construct_role_signature, measure_durations
from ..streams import first_meter
from .dotted_policy_types import (
    SharedDottedSystemReserve,
    SourceIntervalAdjustment,
)


def shared_dotted_system_reserve(
    rows: Sequence[Sequence[LayoutEvent]],
    lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], Sequence[str]]],
    *,
    time_sig: str,
) -> SharedDottedSystemReserve | None:
    """Admit the four-voice DSB row with two dotted interval owners."""

    structural_dsb_boundaries = tuple(
        item
        for row in rows
        for item in row
        if item.event.kind == MusicTokenKind.BARLINE and item.event.code == "|&dsb_a"
    )
    if (
        first_meter(time_sig) != (4, 4)
        or len(rows) != 4
        or tuple(len(row) for row in rows) != (37, 34, 34, 32)
        or len({item.event.span.start.line for row in rows for item in row}) != 4
        or any(measure_durations(row) != (Fraction(4),) * 4 for row in rows)
        or tuple(
            tuple(
                index
                for index, item in enumerate(row)
                if item.event.kind == MusicTokenKind.BARLINE
            )
            for row in rows
        )
        != ((8, 18, 28, 36), (8, 18, 24, 33), (8, 13, 22, 33), (8, 14, 23, 31))
        or any(row[-1].event.code != "|" for row in rows)
        or len(structural_dsb_boundaries) != 1
    ):
        return None

    primary = rows[0]
    if (
        primary[18].event.kind != MusicTokenKind.BARLINE
        or primary[18].event.code != "|&dsb_a"
        or tuple(
            index
            for index, item in enumerate(primary[:-1])
            if item.event.duration_dots
            and event_duration_fraction(item.event) == Fraction(3, 4)
            and item.event.duration_slashes == 1
        )
        != (16, 26)
        or primary[34].event.duration_dots != 1
        or event_duration_fraction(primary[34].event) != Fraction(3, 2)
        or primary[35].event.kind != MusicTokenKind.REST
        or event_duration_fraction(primary[35].event) != Fraction(1, 2)
        or tuple(
            index
            for index, item in enumerate(rows[1][:-1])
            if item.event.duration_dots
            and event_duration_fraction(item.event) == Fraction(3, 4)
        )
        != (16, 20)
        or tuple(
            index
            for index, item in enumerate(rows[3][:-1])
            if item.event.duration_dots
        )
        != (11, 29)
    ):
        return None
    if not all(
        "tie:end" in construct_role_signature(primary[index])
        and any(":modifier:" in role for role in primary[index].event.construct_roles)
        for index in (16, 26)
    ):
        return None
    row_local_lyric_voice_count = 0
    for row in rows:
        row_keys = {(item.event.span.start.line, item.event.index) for item in row}
        row_lyrics = lyric_text_by_voice.get(row[0].voice, {})
        if any(
            any(texts)
            for key, texts in row_lyrics.items()
            if key in row_keys
        ):
            row_local_lyric_voice_count += 1
    if row_local_lyric_voice_count < 2:
        return None

    return SharedDottedSystemReserve(
        retentions=(
            SourceIntervalAdjustment(source_event_key(primary[16]), 36.0, 27.0),
            SourceIntervalAdjustment(source_event_key(primary[26]), 36.0, 27.0),
            SourceIntervalAdjustment(source_event_key(primary[34]), 66.6, 36.0),
        ),
        additions=(
            SourceIntervalAdjustment(source_event_key(primary[18]), 25.2, 39.6),
            SourceIntervalAdjustment(source_event_key(primary[21]), 18.0, 27.0),
        ),
        denominator_event_key=source_event_key(rows[2][0]),
        expected_denominator=936.0,
        final_denominator=946.8,
    )


__all__ = ["shared_dotted_system_reserve"]
