"""Semantic reserve ownership for hidden-rest dotted rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from octopus.render.core.layout_types import LayoutEvent

from ...parser.ast import MusicTokenKind
from .keys import SourceEventKey, source_event_key

_SOUNDED = {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}


@dataclass(frozen=True, slots=True)
class HiddenSentinelDottedTerminalCorrection:
    """Reserve owners around a hidden-rest tie and a terminal dotted tie."""

    reserve_event_keys: tuple[SourceEventKey, SourceEventKey, SourceEventKey]

    def __post_init__(self) -> None:
        if len(set(self.reserve_event_keys)) != 3:
            raise ValueError("hidden-rest dotted reserve keys must be unique")


def hidden_sentinel_dotted_terminal_reserve_indices(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> HiddenSentinelDottedTerminalCorrection | None:
    """Find lyric owners around a hidden-rest tie and final-measure dotted tie.

    Selection uses only the local construct topology and lyric ownership. Pitch,
    literal code, row length, event positions, and source identity do not select it.
    """
    if (
        len(row) < 4
        or row[-1].event.kind != MusicTokenKind.BARLINE
        or len({item.event.span.start.line for item in row}) != 1
    ):
        return None

    sentinels = [
        index for index, item in enumerate(row)
        if item.event.kind == MusicTokenKind.HIDDEN_REST
    ]
    bars = [
        index for index, item in enumerate(row)
        if item.event.kind == MusicTokenKind.BARLINE
    ]
    if len(sentinels) != 1 or len(bars) < 2:
        return None

    def has_lyric(item: LayoutEvent) -> bool:
        return bool(
            lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index),
                (),
            )
        )

    def roles(item: LayoutEvent, role: str) -> set[str]:
        return {
            value.rsplit(":", 1)[0]
            for value in item.event.construct_roles
            if ":tie:" in value and value.endswith(f":{role}")
        }

    sentinel = sentinels[0]
    release_index, transfer_index = sentinel + 1, sentinel + 2
    if transfer_index >= len(row):
        return None
    release, transfer = row[release_index], row[transfer_index]
    tie_ids = roles(transfer, "start")
    if (
        release.event.kind not in _SOUNDED
        or transfer.event.kind not in _SOUNDED
        or not tie_ids
        or not has_lyric(release)
        or not has_lyric(transfer)
        or not any(tie_ids & roles(item, "end") for item in row[transfer_index + 1 :])
    ):
        return None

    last_measure_start = bars[-2] + 1
    dotted_ties = [
        index
        for index in range(last_measure_start, bars[-1])
        if row[index].event.duration_dots > 0
        and roles(row[index], "start")
        and has_lyric(row[index])
        and any(
            roles(row[index], "start") & roles(later, "end")
            for later in row[index + 1 : bars[-1]]
        )
    ]
    if len(dotted_ties) != 1:
        return None

    return HiddenSentinelDottedTerminalCorrection(
        reserve_event_keys=(
            source_event_key(release),
            source_event_key(transfer),
            source_event_key(row[dotted_ties[0]]),
        ),
    )


__all__ = [
    "HiddenSentinelDottedTerminalCorrection",
    "hidden_sentinel_dotted_terminal_reserve_indices",
]
