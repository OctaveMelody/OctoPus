"""Pure source-row measurement and oversized-line splitting policies."""

from __future__ import annotations

from collections.abc import Sequence

from re_tomato.normalization.types import MusicEvent
from re_tomato.parser.ast import MusicTokenKind
from re_tomato.render.core.layout_widths import (
    BARLINE_EXTRA_GAP,
    MEASURE_GAP,
    _is_zero_space_barline,
    compute_event_width,
)

OVERSIZED_ROW_WIDTH_THRESHOLD = 2.5


def measure_width(events: Sequence[MusicEvent], previous_barline: bool) -> float:
    width = 0.0
    prev_was_barline = previous_barline
    for event in events:
        if event.kind == MusicTokenKind.BARLINE and not _is_zero_space_barline(event):
            width += MEASURE_GAP if prev_was_barline else BARLINE_EXTRA_GAP
        width += compute_event_width(event)
        if event.kind == MusicTokenKind.BARLINE and not _is_zero_space_barline(event):
            width += MEASURE_GAP
        prev_was_barline = event.kind == MusicTokenKind.BARLINE
    return width


def split_oversized_source_line(
    events: Sequence[MusicEvent],
    available_width: float,
) -> list[list[MusicEvent]]:
    source_events = list(events)
    if (
        measure_width(source_events, False)
        <= available_width * OVERSIZED_ROW_WIDTH_THRESHOLD
    ):
        return [source_events]
    chunks: list[list[MusicEvent]] = []
    current: list[MusicEvent] = []
    for event in source_events:
        candidate_width = measure_width((*current, event), previous_barline=False)
        if current and candidate_width > available_width:
            chunks.append(current)
            current = []
        current.append(event)
        current_width = measure_width(current, previous_barline=False)
        # A barline carries both leading and trailing measure gaps.  Account
        # for those gaps when deciding whether this event starts a new chunk.
        if event.kind == MusicTokenKind.BARLINE and current_width > available_width:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


__all__ = [
    "OVERSIZED_ROW_WIDTH_THRESHOLD",
    "measure_width",
    "split_oversized_source_line",
]
