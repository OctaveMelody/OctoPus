"""Strict duration-refinement projection across shared measure rows."""

from __future__ import annotations

from collections.abc import Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..duration_partition import (
    partition_shared_measure_widths_by_duration,
)
from ..profiles import LegacyIntrinsicProfile
from ..signatures import measure_duration_boundaries


def project_refined_shared_measure_widths(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
    reconciled_widths: Sequence[Sequence[float]],
) -> list[tuple[float, ...]]:
    """Use a coarser compatible row to project widths onto a strict refinement."""
    bar_indices = [
        [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        for row in rows
    ]
    projected_widths = [tuple(widths) for widths in reconciled_widths]
    for current_index, current_row in enumerate(rows):
        candidates: list[tuple[int, tuple[float, ...]]] = []
        for authority_index, authority_row in enumerate(rows):
            if (
                authority_index == current_index
                or len(profiles[authority_index].interval_widths)
                >= len(profiles[current_index].interval_widths)
                or len(bar_indices[authority_index]) != len(bar_indices[current_index])
            ):
                continue
            authority_start = 0
            current_start = 0
            projected: list[float] = []
            uses_strict_refinement = False
            for authority_end, current_end in zip(
                bar_indices[authority_index],
                bar_indices[current_index],
                strict=True,
            ):
                authority_items = authority_row[authority_start:authority_end]
                current_items = current_row[current_start:current_end]
                authority_boundaries = measure_duration_boundaries(authority_items)
                current_boundaries = measure_duration_boundaries(current_items)
                if (
                    authority_boundaries is None
                    or current_boundaries is None
                    or authority_boundaries[-1] != current_boundaries[-1]
                    or not set(authority_boundaries) <= set(current_boundaries)
                ):
                    break
                uses_strict_refinement |= set(authority_boundaries) < set(current_boundaries)
                replacement = partition_shared_measure_widths_by_duration(
                    list(
                        reconciled_widths[authority_index][
                            authority_start:authority_end
                        ]
                    ),
                    list(
                        profiles[current_index].interval_widths[
                            current_start:current_end
                        ]
                    ),
                    authority_items,
                    current_items,
                    allow_current_rests=True,
                    allow_partial_boundaries=True,
                )
                if replacement is None:
                    break
                projected.extend(replacement)
                authority_start = authority_end
                current_start = current_end
            else:
                if uses_strict_refinement:
                    candidates.append((len(authority_row), tuple(projected)))
        if candidates:
            projected_widths[current_index] = max(candidates, key=lambda item: item[0])[1]
    return projected_widths


__all__ = ["project_refined_shared_measure_widths"]
