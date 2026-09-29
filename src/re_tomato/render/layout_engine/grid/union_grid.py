"""Projection of unequal row slots onto one exact duration-boundary union."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..profiles import LegacyIntrinsicProfile


def project_union_duration_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
    widths: Sequence[tuple[float, ...]],
) -> list[tuple[float, ...]]:
    """Project unequal event slots onto the union of their duration boundaries."""
    bar_indices = [
        [index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE]
        for row in rows
    ]
    if not bar_indices or len({len(indices) for indices in bar_indices}) != 1:
        return list(widths)

    def interval_width(profile: LegacyIntrinsicProfile, index: int) -> float:
        if index < len(profile.interval_widths):
            return profile.interval_widths[index]
        return profile.terminal_width

    projected = [list(items) for items in widths]
    starts = [0] * len(rows)
    for measure_ordinal in range(len(bar_indices[0])):
        slices: list[tuple[int, int, int, list[tuple[Fraction, Fraction, int]]]] = []
        boundaries: set[Fraction] = set()
        for row_index, row in enumerate(rows):
            start = starts[row_index]
            end = bar_indices[row_index][measure_ordinal]
            starts[row_index] = end
            content_start = start + int(row[start].event.kind == MusicTokenKind.BARLINE)
            timed: list[tuple[Fraction, Fraction, int]] = []
            onset = Fraction()
            for index in range(content_start, end):
                duration = event_duration_fraction(row[index].event)
                if duration <= 0:
                    return list(widths)
                timed.append((onset, onset + duration, index))
                boundaries.update((onset, onset + duration))
                onset += duration
            slices.append((start, end, content_start, timed))
        ordered_boundaries = sorted(boundaries)
        if len(ordered_boundaries) < 2:
            return list(widths)
        canonical: list[float] = []
        for left_boundary, right_boundary in zip(
            ordered_boundaries,
            ordered_boundaries[1:],
            strict=False,
        ):
            exact = [
                interval_width(profiles[row_index], index)
                for row_index, (_start, _end, _content_start, timed) in enumerate(slices)
                for event_start, event_end, index in timed
                if event_start == left_boundary and event_end == right_boundary
            ]
            spanning = [
                interval_width(profiles[row_index], index)
                for row_index, (_start, _end, _content_start, timed) in enumerate(slices)
                for event_start, event_end, index in timed
                if event_start <= left_boundary and right_boundary <= event_end
            ]
            candidates = exact or spanning
            if not candidates:
                return list(widths)
            canonical.append(max(candidates))

        for row_index, (start, end, content_start, timed) in enumerate(slices):
            replacement: list[float] = []
            if start < content_start:
                replacement.append(
                    max(
                        interval_width(profiles[index], row_slice[0])
                        for index, row_slice in enumerate(slices)
                    )
                )
            for event_start, event_end, _index in timed:
                replacement.append(
                    sum(
                        canonical[offset]
                        for offset, (left_boundary, right_boundary) in enumerate(
                            zip(
                                ordered_boundaries,
                                ordered_boundaries[1:],
                                strict=False,
                            )
                        )
                        if event_start <= left_boundary and right_boundary <= event_end
                    )
                )
            expected_count = min(end, len(projected[row_index])) - start
            if measure_ordinal == len(bar_indices[0]) - 1 and replacement:
                replacement = replacement[:-1]
            if len(replacement) != expected_count:
                return list(widths)
            projected[row_index][start : start + expected_count] = replacement
    return [tuple(items) for items in projected]


__all__ = ["project_union_duration_grid"]
