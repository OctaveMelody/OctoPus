"""Compound-meter beat-boundary reserve adjustments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..profiles import LegacyIntrinsicProfile


def apply_compound_beat_boundary_reserves(
    row: Sequence[LayoutEvent],
    profile: LegacyIntrinsicProfile,
    *,
    borrows_following_reserve: bool = False,
    keeps_pickup_reserve: bool = False,
) -> LegacyIntrinsicProfile:
    widths = list(profile.interval_widths)
    internal_temporary_meter_indices = [
        index
        for index, item in enumerate(row[1:-1], start=1)
        if "'p:" in item.event.code
    ]
    if len(internal_temporary_meter_indices) >= 2:
        widths[internal_temporary_meter_indices[0]] -= 9.0
    if (
        len(row) > 1
        and row[0].event.kind == MusicTokenKind.BARLINE
        and "zkh" in row[1].event.decorations
        and widths
        and widths[0] == 43.2
    ):
        widths[0] -= 9.0
    beat = Fraction(3, 2)
    elapsed = Fraction()
    internal_beat_positions: list[int] = []
    for index, item in enumerate(row[:-2]):
        if item.event.kind == MusicTokenKind.BARLINE:
            elapsed = Fraction()
            continue
        elapsed += event_duration_fraction(item.event)
        next_is_barline = row[index + 1].event.kind == MusicTokenKind.BARLINE
        if next_is_barline and item.event.duration_dots and widths[index] == 25.2:
            widths[index] += 9.0
        elif not next_is_barline and elapsed > 0 and elapsed % beat == 0:
            reserve_index = (
                index - 1
                if index > 0
                and item.event.duration_slashes >= 2
                and row[index - 1].event.duration_dots
                else index
            )
            internal_beat_positions.append(reserve_index)
            if widths[reserve_index] == 18.0:
                widths[reserve_index] += 9.0
                if (
                    borrows_following_reserve
                    and reserve_index + 1 < len(widths)
                    and widths[reserve_index + 1] == 27.0
                ):
                    widths[reserve_index + 1] -= 9.0

    hook_opener_index = next(
        (index for index, item in enumerate(row[:-1]) if "zkh" in item.event.decorations),
        None,
    )
    if hook_opener_index is not None and internal_beat_positions:
        hook_beat_position = next(
            (position for position in internal_beat_positions if position >= hook_opener_index),
            None,
        )
        first_bar_index = next(
            (
                index
                for index, item in enumerate(row)
                if index > hook_opener_index and item.event.kind == MusicTokenKind.BARLINE
            ),
            None,
        )
        if (
            first_bar_index is not None
            and hook_beat_position is not None
            and (not keeps_pickup_reserve or first_bar_index > hook_opener_index + 1)
            # Beat-based duration grouping already carries the left-hook
            # reserve at the beat boundary (36.0 = 27.0 terminal + 9.0 hook);
            # transferring again would double-count it.
            and widths[hook_beat_position] != 36.0
        ):
            widths[hook_beat_position] += 9.0
            widths[first_bar_index - 1] -= 9.0
    return replace(profile, interval_widths=tuple(widths))


__all__ = ["apply_compound_beat_boundary_reserves"]
