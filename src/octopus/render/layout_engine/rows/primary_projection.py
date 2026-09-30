"""Primary-profile width projection across parallel layout rows."""

from __future__ import annotations

from collections.abc import Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..duration_partition import (
    partition_shared_measure_widths_by_duration,
)
from ..profiles import LegacyIntrinsicProfile


def project_primary_profile_widths(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
) -> list[tuple[float, ...]] | None:
    """Project the primary row's measure widths onto secondary voice profiles."""
    bar_indices = [
        [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        for row in rows
    ]
    if not bar_indices or len({len(indices) for indices in bar_indices}) != 1:
        return None

    authority_row = rows[0]
    authority_widths = profiles[0].interval_widths
    result = [authority_widths]
    for voice_index, row in enumerate(rows[1:], start=1):
        projected = list(profiles[voice_index].interval_widths)
        authority_start = 0
        current_start = 0
        for authority_end, current_end in zip(
            bar_indices[0],
            bar_indices[voice_index],
            strict=True,
        ):
            authority_measure_widths = list(
                authority_widths[authority_start:authority_end]
            )
            current_measure_widths = projected[current_start:current_end]
            current_measure = row[current_start:current_end]
            replacement = (
                authority_measure_widths
                if (
                    current_measure
                    and current_measure[-1].event.kind == MusicTokenKind.HIDDEN_REST
                    and len(authority_measure_widths) == len(current_measure_widths)
                )
                else partition_shared_measure_widths_by_duration(
                    authority_measure_widths,
                    current_measure_widths,
                    authority_row[authority_start:authority_end],
                    current_measure,
                    allow_current_rests=True,
                    allow_partial_boundaries=True,
                )
            )
            if replacement is None:
                return None
            projected[current_start:current_end] = replacement
            authority_start = authority_end
            current_start = current_end
        result.append(tuple(projected))
    return result


__all__ = ["project_primary_profile_widths"]
