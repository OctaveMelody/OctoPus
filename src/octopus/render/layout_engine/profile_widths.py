"""Stateful shared-width profile reconciliation policies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction

from ...parser.ast import MusicTokenKind
from ..core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from .hidden.hidden_streams import event_duration_fraction
from .profiles import LegacyIntrinsicProfile
from .reserves.interval_reserves import transfer_terminal_reserve_excess
from .rows.row_signatures import (
    shared_measure_durations_match,
    shared_row_rhythm_signature,
)


def share_matching_measure_profile_widths(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
) -> list[LegacyIntrinsicProfile]:
    profile_widths = [list(profile.interval_widths) for profile in profiles]
    bar_indices = [
        [index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE]
        for row in rows
    ]
    measure_starts = [0 for _row in rows]
    for bar_ordinal in range(min((len(indices) for indices in bar_indices), default=0)):
        measure_signatures: list[tuple[object, ...]] = []
        slices: list[tuple[int, int]] = []
        for voice_index, row in enumerate(rows):
            start = measure_starts[voice_index]
            end = bar_indices[voice_index][bar_ordinal]
            profile_end = min(end, len(profile_widths[voice_index]))
            slices.append((start, profile_end))
            measure_signatures.append(shared_row_rhythm_signature(row[start:profile_end]))
            measure_starts[voice_index] = end
        for signature in set(measure_signatures):
            matching = [
                index for index, value in enumerate(measure_signatures) if value == signature
            ]
            lengths = {slices[index][1] - slices[index][0] for index in matching}
            if len(matching) < 2 or len(lengths) != 1:
                continue
            width_count = lengths.pop()
            maxima = [
                max(profile_widths[index][slices[index][0] + offset] for index in matching)
                for offset in range(width_count)
            ]
            for index in matching:
                start, end = slices[index]
                profile_widths[index][start:end] = maxima
    return [
        replace(profile, interval_widths=tuple(widths))
        for profile, widths in zip(profiles, profile_widths, strict=True)
    ]


def merge_shared_onset_reserves(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
    *,
    matching_durations_only: bool = False,
) -> list[LegacyIntrinsicProfile]:
    widths = [list(profile.interval_widths) for profile in profiles]
    bar_indices = [
        [index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE]
        for row in rows
    ]
    measure_starts = [0 for _row in rows]
    for bar_ordinal in range(min((len(indices) for indices in bar_indices), default=0)):
        events_by_onset: dict[Fraction, list[tuple[int, int, LayoutEvent]]] = {}
        current_starts: list[int] = []
        for voice_index, row in enumerate(rows):
            start = measure_starts[voice_index]
            current_starts.append(start)
            end = bar_indices[voice_index][bar_ordinal]
            measure_starts[voice_index] = end
            content_start = start + int(row[start].event.kind == MusicTokenKind.BARLINE)
            onset = Fraction()
            for index in range(content_start, end):
                if index < len(widths[voice_index]):
                    events_by_onset.setdefault(onset, []).append(
                        (voice_index, index, row[index])
                    )
                onset += event_duration_fraction(row[index].event)
        for participants in events_by_onset.values():
            if len(participants) < 2:
                continue
            if matching_durations_only and len(
                {event_duration_fraction(item.event) for _voice, _index, item in participants}
            ) != 1:
                continue
            if any(item.event.accidental is not None for _voice, _index, item in participants):
                leading = [
                    (voice_index, index - 1)
                    for voice_index, index, _item in participants
                    if index > current_starts[voice_index]
                ]
                if leading:
                    shared_width = max(widths[voice][index] for voice, index in leading)
                    for voice, index in leading:
                        widths[voice][index] = shared_width
                continue
            shared_width = max(widths[voice][index] for voice, index, _item in participants)
            for voice, index, _item in participants:
                widths[voice][index] = shared_width
    return [
        replace(profile, interval_widths=tuple(items))
        for profile, items in zip(profiles, widths, strict=True)
    ]


def reconcile_parallel_repeat_ending_widths(
    rows: Sequence[Sequence[LayoutEvent]],
    widths: Sequence[tuple[float, ...]],
    *,
    visible_lyric_profile_indices: Sequence[int],
) -> list[tuple[float, ...]]:
    if (
        len(rows) != 4
        or len(visible_lyric_profile_indices) != 2
        or len({len(row) for row in rows}) != 1
    ):
        return list(widths)
    bar_indices = [
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    ]
    if len(set(bar_indices)) != 1:
        return list(widths)
    labeled_rows = [
        row
        for row in rows
        if any("['1'" in item.event.code for item in row)
        and any("['2'" in item.event.code for item in row)
    ]
    authority_index = next(
        (
            index
            for index in visible_lyric_profile_indices
            if not any("['" in item.event.code for item in rows[index])
        ),
        None,
    )
    if len(labeled_rows) != 1 or authority_index is None:
        return list(widths)
    first_ending_index = next(
        index for index, item in enumerate(labeled_rows[0]) if "['1'" in item.event.code
    )
    authority_widths = list(widths[authority_index])
    for index in range(first_ending_index, len(authority_widths) - 1):
        if (
            rows[authority_index][index + 1].event.code.startswith("|y")
            and any("['2'" in item.event.code for item in labeled_rows[0][index + 1 :])
        ):
            authority_widths[index] = max(authority_widths[index], 34.2)
    return [
        (*row_widths[:first_ending_index], *authority_widths[first_ending_index:])
        for row_widths in widths
    ]


def transfer_non_partitioned_terminal_reserves(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
    widths: Sequence[tuple[float, ...]],
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    if (
        len(rows) < 2
        or len({len(row) for row in rows}) != 1
        or not shared_measure_durations_match(rows)
        or len(profiles) != len(rows)
        or len(widths) != len(rows)
        or any(len(row) < 2 for row in rows)
    ):
        return list(profiles), list(widths)
    terminal_events = [row[-2].event for row in rows]
    uses_hidden_terminal = all(
        row[-1].event.kind == MusicTokenKind.BARLINE
        and event.kind == MusicTokenKind.HIDDEN_REST
        for row, event in zip(rows, terminal_events, strict=True)
    )
    # A pair-close continuation into a repeat barline keeps its full terminal
    # reserve: the only corpus system with this shape (Me-And-My-Country p2
    # sys4) shows the reference terminal zone at 52.2 with the plain 36 pair
    # step, i.e. no excess transfer out of the terminal.
    if not uses_hidden_terminal:
        return list(profiles), list(widths)
    adjusted_profiles = list(profiles)
    adjusted_widths = [list(row_widths) for row_widths in widths]
    for index, profile in enumerate(profiles):
        excess = profile.raw_terminal_width - profile.terminal_width
        if excess <= GEOMETRY_EPSILON or not adjusted_widths[index]:
            continue
        transfer = transfer_terminal_reserve_excess(
            tuple(adjusted_widths[index]),
            raw_terminal_reserve=profile.raw_terminal_width,
            terminal_reserve=profile.terminal_width,
        )
        adjusted_widths[index] = list(transfer.interval_widths)
        adjusted_profiles[index] = replace(profile, terminal_width=transfer.terminal_reserve)
    return adjusted_profiles, [tuple(row_widths) for row_widths in adjusted_widths]


__all__ = [
    "merge_shared_onset_reserves",
    "reconcile_parallel_repeat_ending_widths",
    "share_matching_measure_profile_widths",
    "transfer_non_partitioned_terminal_reserves",
]
