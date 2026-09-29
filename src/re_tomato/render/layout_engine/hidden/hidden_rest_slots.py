"""Hidden-rest slot compatibility reconciliation."""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ...core.layout_widths import REST_WIDTH
from ..visibility import (
    is_bz_placeholder_event as _is_bz_placeholder_event,
)
from .hidden_rest_signatures import (
    _HIDDEN_REST_ROW_SIGNATURES,
    event_shape,
)
from .hidden_streams import (
    hidden_rest_placeholder_event as _hidden_rest_placeholder_event,
)


def reconcile_hidden_rest_slots(
    layout_events: list[LayoutEvent],
    laid_out: list[LayoutEvent],
    tail_barlines: list[LayoutEvent],
) -> None:
    row_events: dict[tuple[int, int, int], list[LayoutEvent]] = {}
    for item in [*laid_out, *tail_barlines]:
        row_events.setdefault((item.page_index, item.voice, item.line), []).append(item)

    layout_indexes = {id(item): index for index, item in enumerate(layout_events)}
    placeholder_index = -200000
    for row in row_events.values():
        row.sort(key=lambda item: item.slot)
        index = 1
        while index < len(row):
            item = row[index]
            if item.event.kind != MusicTokenKind.BARLINE:
                index += 1
                continue
            if not _needs_hidden_rest_before_barline(row, index):
                index += 1
                continue

            row_tail = index == len(row) - 1
            placeholder = LayoutEvent(
                event=_hidden_rest_placeholder_event(item.event, placeholder_index),
                x=item.x - REST_WIDTH if row_tail else item.x,
                y=item.y,
                page_index=item.page_index,
                voice=item.voice,
                line=item.line,
                slot=item.slot,
                block=item.block,
            )
            placeholder_index -= 1
            row.insert(index, placeholder)
            layout_index = layout_indexes[id(item)]
            layout_events.insert(layout_index, placeholder)
            for event_id, event_layout_index in layout_indexes.items():
                if event_layout_index >= layout_index:
                    layout_indexes[event_id] = event_layout_index + 1
            layout_indexes[id(placeholder)] = layout_index

            for shifted in row[index + 1 :]:
                shifted.slot += 1
            index += 2


def _needs_hidden_rest_before_barline(
    row: list[LayoutEvent],
    barline_index: int,
) -> bool:
    previous = row[barline_index - 1]
    if previous.event.kind == MusicTokenKind.HIDDEN_REST:
        return False
    if _is_bz_placeholder_event(previous.event):
        return False
    return _hidden_rest_slot_signature(row, barline_index) in _HIDDEN_REST_ROW_SIGNATURES


def _hidden_rest_slot_signature(
    row: list[LayoutEvent],
    barline_index: int,
) -> tuple[int, tuple[str, ...]]:
    barline_ordinal = sum(
        1 for item in row[: barline_index + 1] if item.event.kind == MusicTokenKind.BARLINE
    )
    return barline_ordinal, _row_slot_signature_shapes(row)


def _row_slot_signature_shapes(row: list[LayoutEvent]) -> tuple[str, ...]:
    return tuple(
        event_shape(item.event)
        for item in row
        if not (item.event.index < 0 and item.event.kind == MusicTokenKind.HIDDEN_REST)
    )


__all__ = ["reconcile_hidden_rest_slots"]
