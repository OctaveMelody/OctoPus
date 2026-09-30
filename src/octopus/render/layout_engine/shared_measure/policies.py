"""Shared-measure policy normalization and reserve arithmetic."""

from __future__ import annotations

from collections.abc import Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..width_partition import is_terminal_non_ykh_reserve_event
from .models import MeasureSlice, SharedMeasurePolicies


def normalize_shared_measure_policies(
    row_count: int,
    punctuation_indices_by_row: Sequence[frozenset[int]] | None,
    terminal_punctuation_by_row: Sequence[bool] | None,
    skip_indices_by_row: Sequence[frozenset[int]] | None,
    skip_connector_indices_by_row: Sequence[frozenset[int]] | None,
) -> SharedMeasurePolicies:
    """Materialize optional policy vectors with the historical empty defaults."""
    return SharedMeasurePolicies(
        punctuation_indices_by_row=tuple(
            punctuation_indices_by_row or [frozenset()] * row_count
        ),
        terminal_punctuation_by_row=tuple(
            terminal_punctuation_by_row or [False] * row_count
        ),
        skip_indices_by_row=tuple(skip_indices_by_row or [frozenset()] * row_count),
        skip_connector_indices_by_row=tuple(
            skip_connector_indices_by_row or [frozenset()] * row_count
        ),
    )


def find_punctuation_reserve(
    slices: Sequence[MeasureSlice],
    target_index: int,
    punctuation_indices_by_row: Sequence[frozenset[int]],
    skip_connector_indices_by_row: Sequence[frozenset[int]],
) -> tuple[int | None, int | None]:
    """Find the punctuation voice and target interval eligible for an 18px reserve."""
    punctuation_voice = next(
        (
            voice_index
            for voice_index, measure_slice in enumerate(slices)
            if measure_slice.end - 1 in punctuation_indices_by_row[voice_index]
        ),
        None,
    )
    if punctuation_voice is None or punctuation_voice == target_index:
        return punctuation_voice, None
    target_start = slices[target_index].start
    target_end = slices[target_index].end
    reserve_index = next(
        (
            index
            for index in skip_connector_indices_by_row[target_index]
            if target_start <= index < target_end
        ),
        None,
    )
    return punctuation_voice, reserve_index


def apply_target_connector_reserve(
    target_slice: MeasureSlice,
    target_widths: Sequence[float],
    reserve_index: int | None,
    *,
    reserve_width: float = 18.0,
) -> tuple[list[float], MeasureSlice]:
    """Apply a connector reserve and return the updated widths and refreshed slice."""
    updated = list(target_widths)
    if reserve_index is not None:
        updated[reserve_index] += reserve_width
    return updated, MeasureSlice(
        target_slice.start,
        target_slice.end,
        tuple(updated[target_slice.start : target_slice.end]),
    )


def target_total_and_deficit(
    target_widths: Sequence[float],
    current_widths: Sequence[float],
) -> tuple[float, float]:
    """Return the target total and current row's deficit against it."""
    target_total = sum(target_widths)
    return target_total, target_total - sum(current_widths)


def allocate_shared_measure_deficit(
    current_widths: Sequence[float],
    deficit: float,
    *,
    chunk_width: float = 18.0,
) -> list[float]:
    """Allocate a positive deficit from right to left, retaining any residual at the end."""
    replacement = list(current_widths)
    remaining = deficit
    for index in range(len(replacement) - 1, -1, -1):
        addition = min(chunk_width, remaining)
        replacement[index] += addition
        remaining -= addition
        if remaining <= GEOMETRY_EPSILON:
            break
    if remaining > GEOMETRY_EPSILON and replacement:
        replacement[-1] += remaining
    return replacement


def transfer_terminal_cap_excess(
    replacement: Sequence[float],
    current_content: Sequence[LayoutEvent],
    target_content: Sequence[LayoutEvent],
    *,
    raw_terminal_width: float,
) -> list[float]:
    """Move terminal excess into the preceding interval when the terminal is capped."""
    adjusted = list(replacement)
    if (
        len(current_content) == len(target_content) + 1
        and len(adjusted) >= 2
        and is_terminal_non_ykh_reserve_event(current_content[-1].event)
    ):
        terminal_excess = adjusted[-1] - raw_terminal_width
        if terminal_excess > GEOMETRY_EPSILON:
            adjusted[-2] += terminal_excess
            adjusted[-1] = raw_terminal_width
    return adjusted


def release_partial_boundary_reserves(
    replacement: Sequence[float],
    row: Sequence[LayoutEvent],
    *,
    start: int,
    end: int,
) -> list[float]:
    """Move 18px from a dotted interval to its following slashed interval at a barline."""
    adjusted = list(replacement)
    for item_offset, item in enumerate(row[start : end - 1]):
        if (
            item.event.duration_dots
            and not item.event.duration_slashes
            and row[start + item_offset + 1].event.duration_slashes
            and row[start + item_offset + 2].event.kind == MusicTokenKind.BARLINE
            and item_offset + 1 < len(adjusted)
            and adjusted[item_offset] >= 18.0
        ):
            adjusted[item_offset] -= 18.0
            adjusted[item_offset + 1] += 18.0
    return adjusted


__all__ = [
    "allocate_shared_measure_deficit",
    "apply_target_connector_reserve",
    "find_punctuation_reserve",
    "normalize_shared_measure_policies",
    "release_partial_boundary_reserves",
    "target_total_and_deficit",
    "transfer_terminal_cap_excess",
]
