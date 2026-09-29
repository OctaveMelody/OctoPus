"""Source-shape classifiers for shared measure grids."""

from __future__ import annotations

from collections.abc import Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..signatures import grid_event_signature


def uses_shifted_voice_measure_grid(rows: Sequence[Sequence[LayoutEvent]]) -> bool:
    """Return whether two voices share a grid offset by one leading measure."""

    if len(rows) != 2:
        return False

    signatures: list[list[tuple[object, ...]]] = []
    for row in rows:
        measures: list[tuple[object, ...]] = []
        current: list[object] = []
        for item in row:
            if item.event.kind == MusicTokenKind.BARLINE:
                measures.append(tuple(current))
                current = []
            else:
                current.append(grid_event_signature(item))
        signatures.append(measures)
    return (
        len(signatures[0]) >= 8
        and len(signatures[1]) >= 8
        and signatures[0][:3] == signatures[1][1:4]
    )


__all__ = ["uses_shifted_voice_measure_grid"]
