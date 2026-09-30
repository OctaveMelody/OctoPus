"""Reserve meter-label widths across shared barline ordinals."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from octopus.parser.ast import MusicTokenKind
from octopus.render.layout_engine.beat_grid_engine.types import (
    METER_LABEL_WIDTH,
    GridEventKey,
    SharedGridRow,
)


def _apply_meter_label_shifts(
    rows: Sequence[SharedGridRow],
    event_x_offsets: dict[GridEventKey, Fraction],
    barline_x_offsets: list[Fraction],
) -> None:
    """Reserve label width after every meter-change barline.

    A ``|"p:X/Y"`` annotation changes the time signature; the reference draws
    no visible glyph for it but still reserves one within-beat step of width
    after the barline, pushing that event and everything after it to the right
    (oracle-verified 2026-08-23: As-Wished p2 rows 10-15 fit at exactly this
    width with sub-0.1px RMSE).  A time signature change applies to every
    voice, so the label width is global per barline ordinal: when any row
    declares a meter change at an ordinal, all rows reserve the width there,
    even rows whose own token at that barline is a plain ``|`` (As-Wished p2
    L80 vs L77).
    """
    meter_ordinals: set[int] = set()
    for row in rows:
        ordinal = -1
        for event in row.events:
            if event.kind == MusicTokenKind.BARLINE:
                ordinal += 1
                if "'p:" in (event.code or ""):
                    meter_ordinals.add(ordinal)
    event_labels: dict[GridEventKey, int] = {}
    barline_labels: dict[int, int] = {}
    for row in rows:
        ordinal = -1
        labels = 0
        for event in row.events:
            if event.kind == MusicTokenKind.BARLINE:
                ordinal += 1
                if labels:
                    barline_labels[ordinal] = max(barline_labels.get(ordinal, 0), labels)
                if ordinal in meter_ordinals:
                    labels += 1
            elif labels:
                key = GridEventKey.for_event(event, row.voice_index)
                event_labels[key] = max(event_labels.get(key, 0), labels)
    for key, count in event_labels.items():
        if key in event_x_offsets:
            event_x_offsets[key] += Fraction(METER_LABEL_WIDTH) * count
    for ordinal, count in barline_labels.items():
        if ordinal < len(barline_x_offsets):
            barline_x_offsets[ordinal] += Fraction(METER_LABEL_WIDTH) * count
