"""Exact canonical grid construction independent of coordinate projection."""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction

from ..profiles import MeasureGrid


def measure_grid_from_durations(
    measure_index: int,
    durations: Iterable[Fraction | None],
) -> MeasureGrid | None:
    """Build cumulative exact boundaries, or reject a missing/non-positive segment."""

    boundaries = [Fraction()]
    for duration in durations:
        if duration is None or duration <= 0:
            return None
        boundaries.append(boundaries[-1] + duration)
    return MeasureGrid(measure_index=measure_index, boundaries=tuple(boundaries))


__all__ = ["measure_grid_from_durations"]
