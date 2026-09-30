"""Shared-measure discovery, slicing, and authority selection."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from .models import MeasureSlice


def measure_barline_indices(
    rows: Sequence[Sequence[LayoutEvent]],
) -> list[list[int]]:
    """Return each row's ordered barline positions."""
    return [
        [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        for row in rows
    ]


def iter_shared_measure_slices(
    bar_indices: Sequence[Sequence[int]],
    widths: Sequence[Sequence[float]],
) -> Iterator[list[MeasureSlice]]:
    """Yield per-measure row slices while advancing each row independently."""
    measure_starts = [0 for _row in bar_indices]
    for bar_ordinal in range(len(bar_indices[0])):
        slices: list[MeasureSlice] = []
        for voice_index, indices in enumerate(bar_indices):
            end = indices[bar_ordinal]
            start = measure_starts[voice_index]
            slices.append(MeasureSlice(start, end, tuple(widths[voice_index][start:end])))
            measure_starts[voice_index] = end
        yield slices


def select_target_measure_index(slices: Sequence[MeasureSlice]) -> int:
    """Select the row with the largest current width as the measure authority."""
    return max(range(len(slices)), key=lambda index: sum(slices[index].widths))


__all__ = [
    "iter_shared_measure_slices",
    "measure_barline_indices",
    "select_target_measure_index",
]
