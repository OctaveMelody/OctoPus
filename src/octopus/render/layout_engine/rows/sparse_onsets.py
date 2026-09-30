"""Sparse compound-measure onset alignment policies."""

from __future__ import annotations

from collections.abc import Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent


def align_sparse_compound_measure_onsets(
    rows: Sequence[Sequence[LayoutEvent]],
    reconciled_widths: Sequence[Sequence[float]],
) -> list[tuple[float, ...]]:
    """Move a shared reserve from a sparse voice's barline to its first onset."""
    if len(rows) < 2:
        return [tuple(widths) for widths in reconciled_widths]
    adjusted = [list(widths) for widths in reconciled_widths]
    primary = rows[0]
    primary_bars = [
        index
        for index, item in enumerate(primary)
        if item.event.kind == MusicTokenKind.BARLINE
    ]
    for voice_index, row in enumerate(rows[1:], start=1):
        bars = [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        for primary_bar, bar in zip(primary_bars[:-1], bars[:-1], strict=False):
            primary_first = primary_bar + 1
            first = bar + 1
            if (
                primary_first >= len(primary)
                or first + 1 >= len(row)
                or first >= len(adjusted[voice_index])
                or bar >= len(adjusted[voice_index])
                or not primary[primary_first].event.duration_slashes
                or not row[first].event.duration_dots
                or row[first].event.duration_slashes
                or adjusted[voice_index][bar] < 18.0
            ):
                continue
            adjusted[voice_index][bar] -= 18.0
            adjusted[voice_index][first] += 18.0
    return [tuple(widths) for widths in adjusted]


__all__ = ["align_sparse_compound_measure_onsets"]
