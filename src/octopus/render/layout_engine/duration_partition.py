"""Exact duration-boundary mapping for shared layout measures."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent
from .grid.grids import measure_grid_from_durations
from .hidden.hidden_streams import event_duration_fraction
from .width_partition import partition_shared_measure_widths_by_partial_boundaries


def partition_shared_measure_widths_by_duration(
    target_widths: Sequence[float],
    current_widths: Sequence[float],
    target_items: Sequence[LayoutEvent],
    current_items: Sequence[LayoutEvent],
    *,
    allow_current_rests: bool = False,
    allow_partial_boundaries: bool = False,
    prefer_leading_deficit: bool = False,
    allow_shorter_current: bool = False,
) -> list[float] | None:
    """Partition a shared measure's widths across rows by duration profile.

    Matches target and current row items (optionally allowing rests, partial
    boundaries, leading deficits, or shorter current rows per the flags) and splits
    the target widths proportionally; returns None when no valid partition exists."""
    target_width_values = list(target_widths)
    current_width_values = list(current_widths)
    target_item_values = list(target_items)
    current_item_values = list(current_items)
    target_starts_with_bar = bool(target_item_values) and (
        target_item_values[0].event.kind == MusicTokenKind.BARLINE
    )
    current_starts_with_bar = bool(current_item_values) and (
        current_item_values[0].event.kind == MusicTokenKind.BARLINE
    )
    if target_starts_with_bar != current_starts_with_bar:
        return None

    prefix_widths: list[float] = []
    if target_starts_with_bar:
        prefix_widths.append(target_width_values[0])
        target_width_values = target_width_values[1:]
        current_width_values = current_width_values[1:]
        target_item_values = target_item_values[1:]
        current_item_values = current_item_values[1:]

    supports_paired_extension_mapping = (
        len(target_item_values) == 6
        and len(current_item_values) == 4
        and all(item.event.kind == MusicTokenKind.NOTE for item in target_item_values)
        and tuple(item.event.kind for item in current_item_values)
        == (
            MusicTokenKind.NOTE,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.NOTE,
            MusicTokenKind.EXTENSION,
        )
    )
    supports_four_beat_refinement = (
        len(target_item_values) == 6
        and len(current_item_values) == 4
        and all(event_duration_fraction(item.event) == 1 for item in current_item_values)
        and sum(
            (event_duration_fraction(item.event) for item in target_item_values),
            Fraction(),
        )
        == 4
        and all(
            item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.EXTENSION}
            for item in target_item_values
        )
    )
    if (
        len(target_item_values) < len(current_item_values) + 3
        and not supports_paired_extension_mapping
        and not supports_four_beat_refinement
        and not allow_partial_boundaries
    ):
        return None
    allowed_kinds = {MusicTokenKind.NOTE, MusicTokenKind.EXTENSION}
    if allow_current_rests:
        allowed_kinds.update({MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST})
    if any(item.event.kind not in allowed_kinds for item in target_item_values) or any(
        item.event.kind not in allowed_kinds for item in current_item_values
    ):
        return None
    terminal_interval_omitted = (
        len(target_width_values) == len(target_item_values) - 1
        and len(current_width_values) == len(current_item_values) - 1
    )
    if not terminal_interval_omitted and (
        len(target_width_values) != len(target_item_values)
        or len(current_width_values) != len(current_item_values)
    ):
        return None

    def duration_value(item: LayoutEvent) -> Fraction | None:
        duration = item.event.duration
        if duration is not None:
            return Fraction(duration.numerator, duration.denominator)
        if item.event.kind == MusicTokenKind.EXTENSION:
            return Fraction(1)
        return None

    target_grid = measure_grid_from_durations(
        0,
        (duration_value(item) for item in target_item_values),
    )
    current_grid = measure_grid_from_durations(
        0,
        (duration_value(item) for item in current_item_values),
    )
    if target_grid is None or current_grid is None:
        return None
    target_boundaries = list(target_grid.boundaries)
    current_boundaries = list(current_grid.boundaries)
    if target_boundaries[-1] != current_boundaries[-1]:
        if not (allow_shorter_current and current_boundaries[-1] < target_boundaries[-1]):
            return None
        mapped_boundaries: list[int] = []
        for current_boundary in current_boundaries:
            minimum_index = mapped_boundaries[-1] + 1 if mapped_boundaries else 0
            mapped_boundaries.append(
                next(
                    (
                        index
                        for index, boundary in enumerate(target_boundaries)
                        if index >= minimum_index and boundary >= current_boundary
                    ),
                    len(target_boundaries) - 1,
                )
            )
        mapped_boundaries[-1] = len(target_boundaries) - 1
        mapped_pairs = zip(mapped_boundaries, mapped_boundaries[1:], strict=False)
        if terminal_interval_omitted:
            mapped_pairs = zip(
                mapped_boundaries[: len(current_width_values)],
                mapped_boundaries[1 : len(current_width_values) + 1],
                strict=True,
            )
        mapped_replacement = [
            sum(target_width_values[start:end], 0.0)
            for start, end in mapped_pairs
        ]
        return [*prefix_widths, *mapped_replacement] if all(mapped_replacement) else None

    target_index_by_boundary = {
        boundary: index for index, boundary in enumerate(target_boundaries)
    }
    try:
        mapped_boundaries = [
            target_index_by_boundary[boundary] for boundary in current_boundaries
        ]
    except KeyError:
        if not allow_partial_boundaries:
            return None
        replacement = partition_shared_measure_widths_by_partial_boundaries(
            target_width_values,
            current_width_values,
            target_boundaries,
            current_boundaries,
            prefer_leading_deficit=prefer_leading_deficit,
        )
        if replacement is None:
            return None
        return [*prefix_widths, *replacement]
    mapped_pairs = zip(mapped_boundaries, mapped_boundaries[1:], strict=False)
    if terminal_interval_omitted:
        mapped_pairs = zip(
            mapped_boundaries[: len(current_width_values)],
            mapped_boundaries[1 : len(current_width_values) + 1],
            strict=True,
        )
    return [
        *prefix_widths,
        *(sum(target_width_values[start:end]) for start, end in mapped_pairs),
    ]


__all__ = ["partition_shared_measure_widths_by_duration"]
