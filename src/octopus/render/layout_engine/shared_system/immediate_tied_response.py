"""Reserve ownership for immediate dotted-tie response phrases."""

from __future__ import annotations

from dataclasses import replace

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..profiles import LegacyIntrinsicProfile
from ..reserves.interval_reserves import (
    add_interval_reserve,
    transfer_interval_reserve_to_terminal,
)
from .models import LyricTextByVoice


def apply_immediate_dotted_tie_response_reserves(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    lyric_text_by_voice: LyricTextByVoice,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    """Allocate the shared response onset and trailing slur reserves."""

    if not uses_immediate_dotted_tie_response(rows, lyric_text_by_voice):
        return profiles, reconciled_widths
    adjusted_profiles = list(profiles)
    adjusted_widths: list[tuple[float, ...]] = []
    for voice_index, (row, widths) in enumerate(
        zip(rows, reconciled_widths, strict=True)
    ):
        pattern_index = _response_pattern_indices(row)[0]
        allocation = add_interval_reserve(
            widths,
            interval_index=pattern_index + 2,
            added_width=9.0,
        )
        row_widths = allocation.interval_widths
        if _has_extension_led_terminal_slur(row):
            transfer = transfer_interval_reserve_to_terminal(
                row_widths,
                interval_index=len(row) - 3,
                terminal_reserve=adjusted_profiles[voice_index].terminal_width,
                transfer_width=18.0,
            )
            row_widths = transfer.interval_widths
            adjusted_profiles[voice_index] = replace(
                adjusted_profiles[voice_index],
                terminal_width=transfer.terminal_reserve,
            )
        adjusted_widths.append(row_widths)
    return adjusted_profiles, adjusted_widths


def uses_immediate_dotted_tie_response(
    rows: list[list[LayoutEvent]],
    lyric_text_by_voice: LyricTextByVoice,
) -> bool:
    """Return whether both unequal lyric rows use the immediate response shape."""

    return (
        len(rows) == 2
        and len({len(row) for row in rows}) > 1
        and all(lyric_text_by_voice.get(row[0].voice) for row in rows)
        and all(
            row[-1].event.code == "|"
            and sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 5
            and len(_response_pattern_indices(row)) == 1
            for row in rows
        )
    )


def _response_pattern_indices(row: list[LayoutEvent]) -> list[int]:
    return [
        index
        for index in range(len(row) - 3)
        if "(" in row[index].event.code
        and row[index].event.duration_dots == 1
        and row[index].event.duration_slashes == 0
        and ")" in row[index + 1].event.code
        and row[index + 2].event.kind
        in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
        and row[index + 2].event.duration_slashes == 1
        and "(" in row[index + 3].event.code
        and row[index + 3].event.duration_slashes == 2
    ]


def _has_extension_led_terminal_slur(row: list[LayoutEvent]) -> bool:
    return (
        row[-4].event.kind == MusicTokenKind.EXTENSION
        and "(" in row[-3].event.code
        and row[-3].event.duration_slashes == 1
        and ")" in row[-2].event.code
        and row[-2].event.duration_slashes == 1
    )


__all__ = [
    "apply_immediate_dotted_tie_response_reserves",
    "uses_immediate_dotted_tie_response",
]
