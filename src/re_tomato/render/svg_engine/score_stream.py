"""Emit visible score events, accessories, lyrics, and duration lines."""

from __future__ import annotations

from typing import Literal

from re_tomato.render.core.elements import SvgElement
from re_tomato.render.core.layout_types import LayoutEvent, LayoutPage

from ...parser.ast import MusicTokenKind
from ..duration import duration_line_elements as _duration_line_elements
from .accessories import (
    event_augmentation_dot_item_elements as _event_augmentation_dot_item_elements,
)
from .accessories import (
    event_decoration_item_elements as _event_decoration_item_elements,
)
from .accessories import (
    event_deferred_accidental_item_elements as _event_deferred_accidental_item_elements,
)
from .accessories import (
    event_dynamic_decoration_item_elements as _event_dynamic_decoration_item_elements,
)
from .accessories import (
    event_pitch_accessory_item_elements as _event_pitch_accessory_item_elements,
)
from .construct_stream import (
    _block_construct_elements_by_event,
    _early_construct_elements,
    _late_construct_elements,
    _late_ending_construct_elements,
)
from .duration_lines import hairpin_line_elements as _hairpin_line_elements
from .event_stream import _event_item_elements, _previous_visible_musical_by_layout_event
from .graces import _grace_elements_by_host
from .lyrics import lyrics_by_host as _lyrics_by_host
from .marks import (
    _inline_time_signature,
    _mark_element,
    _mark_elements_by_host,
    _standalone_decoration_marks_by_host,
)
from .types import GraceRenderPlan

_HIDDEN_VISUAL_ACCESSORY_BLOCKS = frozenset(
    {"bz-hidden", "dsb-hidden", "dsb-hidden-tail"}
)


def _score_stream_elements(
    layout: LayoutPage,
    grace_plan: GraceRenderPlan,
    *,
    accessory_order: Literal["legacy", "visual"] = "visual",
) -> list[SvgElement]:
    elements: list[SvgElement] = []
    lyrics_by_host = _lyrics_by_host(layout)
    decoration_marks_by_host = _standalone_decoration_marks_by_host(layout)
    local_marks_by_host = _mark_elements_by_host(layout)
    graces_by_host = _grace_elements_by_host(grace_plan)
    block_constructs_after_event = _block_construct_elements_by_event(layout, placement="after")
    block_constructs_before_event = _block_construct_elements_by_event(layout, placement="before")
    previous_musical_by_event_id = _previous_visible_musical_by_layout_event(layout)
    marks_by_host = {
        (mark.host.voice, mark.host.line, mark.host.slot): mark
        for mark in layout.marks
        if _inline_time_signature(mark) is not None
    }
    emitted_lyric_hosts: set[tuple[int, int, int]] = set()
    event_order = {id(item): index for index, item in enumerate(layout.events)}
    hidden_by_line: dict[int, list[LayoutEvent]] = {}
    for item in layout.hidden_events:
        if item.block not in {"bz-hidden", "dsb-hidden", "dsb-hidden-tail"}:
            continue
        hidden_by_line.setdefault(item.line, []).append(item)
    for line_events in hidden_by_line.values():
        line_events.sort(key=_hidden_stream_sort_key)
    emitted_hidden_event_ids: set[int] = set()

    def emit_hidden_events(hidden_items: list[LayoutEvent]) -> None:
        for hidden_item in hidden_items:
            emitted_hidden_event_ids.add(id(hidden_item))
            elements.extend(block_constructs_before_event.get(id(hidden_item), ()))
            hidden_event_elements = _event_item_elements(
                layout,
                hidden_item,
                marks_by_host,
                previous_musical_by_event_id,
            )
            elements.extend(hidden_event_elements)
            after_event_elements = list(block_constructs_after_event.get(id(hidden_item), ()))
            elements.extend(after_event_elements)

    for item in sorted(
        layout.events,
        key=lambda item: (item.line, item.slot, item.voice, event_order[id(item)]),
    ):
        host_key = (item.voice, item.line, item.slot)
        line_hidden = hidden_by_line.get(item.line, [])
        ready_hidden = [
            hidden_item
            for hidden_item in line_hidden
            if id(hidden_item) not in emitted_hidden_event_ids
            and _hidden_event_ready_for_stream(hidden_item, item)
        ]
        ready_hidden = _extend_ready_bz_hidden_group(
            line_hidden,
            ready_hidden,
            emitted_hidden_event_ids,
        )
        emit_hidden_events(ready_hidden)
        elements.extend(block_constructs_before_event.get(id(item), ()))
        event_elements = _event_item_elements(
            layout,
            item,
            marks_by_host,
            previous_musical_by_event_id,
        )
        elements.extend(event_elements)
        after_event_elements = list(block_constructs_after_event.get(id(item), ()))
        elements.extend(after_event_elements)
        if host_key not in emitted_lyric_hosts:
            elements.extend(lyrics_by_host.get(host_key, ()))
            emitted_lyric_hosts.add(host_key)
    emit_hidden_events(
        [item for item in layout.hidden_events if id(item) not in emitted_hidden_event_ids]
    )

    ordered_events = sorted(
        layout.events,
        key=lambda item: (item.line, item.slot, item.voice, event_order[id(item)]),
    )
    elements.extend(_early_construct_elements(layout))
    elements.extend(_duration_line_elements(layout))
    if accessory_order == "legacy":
        accessory_items = [
            (item, False, index) for index, item in enumerate(ordered_events)
        ] + [
            (item, True, index) for index, item in enumerate(layout.hidden_events)
        ]
    else:
        visible_accessory_items = [
            (item, False, index) for index, item in enumerate(ordered_events)
        ]
        hidden_accessory_items = [
            (item, True, index) for index, item in enumerate(layout.hidden_events)
            if item.block in _HIDDEN_VISUAL_ACCESSORY_BLOCKS
        ]
        hidden_accessory_items.sort(key=_accessory_stream_sort_key)
        accessory_items = _merge_hidden_visual_items(
            visible_accessory_items,
            hidden_accessory_items,
        )
        accessory_items.extend(
            (item, True, index)
            for index, item in enumerate(layout.hidden_events)
            if item.block not in _HIDDEN_VISUAL_ACCESSORY_BLOCKS
        )
    for item, is_hidden, _index in accessory_items:
        if is_hidden:
            elements.extend(_event_pitch_accessory_item_elements(item, item.event))
            elements.extend(_event_decoration_item_elements(item, item.event, phase="opening"))
            elements.extend(_event_augmentation_dot_item_elements(item, item.event))
            elements.extend(_event_decoration_item_elements(item, item.event, phase="deferred"))
            elements.extend(_event_deferred_accidental_item_elements(item, item.event))
            continue
        host_key = (item.voice, item.line, item.slot)
        for pass_elements in (
            _event_pitch_accessory_item_elements(item, item.event),
            _event_decoration_item_elements(item, item.event, phase="opening"),
            _event_augmentation_dot_item_elements(item, item.event),
        ):
            elements.extend(pass_elements)
        for mark in decoration_marks_by_host.get(host_key, ()):
            elements.extend(_mark_element(mark))
        for pass_elements in (
            _event_decoration_item_elements(item, item.event, phase="deferred"),
            _event_deferred_accidental_item_elements(item, item.event),
            list(graces_by_host.get(host_key, ())),
        ):
            elements.extend(pass_elements)
    elements.extend(_late_construct_elements(layout))
    visible_dynamic_items = [
        (item, False, index) for index, item in enumerate(ordered_events)
    ]
    hidden_dynamic_items = [
        (item, True, index)
        for index, item in enumerate(layout.hidden_events)
        if item.block in _HIDDEN_VISUAL_ACCESSORY_BLOCKS
    ]
    hidden_dynamic_items.sort(key=_accessory_stream_sort_key)
    dynamic_items = _merge_hidden_visual_items(
        visible_dynamic_items,
        hidden_dynamic_items,
    )
    dynamic_items.extend(
        (item, True, index)
        for index, item in enumerate(layout.hidden_events)
        if item.block not in _HIDDEN_VISUAL_ACCESSORY_BLOCKS
    )
    for item, _is_hidden, _index in dynamic_items:
        host_key = (item.voice, item.line, item.slot)
        if not _is_hidden:
            elements.extend(local_marks_by_host.get(host_key, ()))
        elements.extend(_event_dynamic_decoration_item_elements(item, item.event))
    elements.extend(_late_ending_construct_elements(layout))
    # Hairpins close the body: the reference emits every wedge after all late
    # dynamics, marks, and ending fragments (verified on CITL p2, Edelweiss
    # All p1 and Hulunbuir p4 — the last hairpin line is the final body
    # element before the custom group).
    elements.extend(_hairpin_line_elements(layout))
    return elements


def _hidden_stream_sort_key(item: LayoutEvent) -> tuple[int, float, float, int]:
    if item.stream_slot is not None:
        return (item.stream_slot, item.x, item.y, item.event.index)
    return (10_000_000, item.x, item.y, item.event.index)


def _extend_ready_bz_hidden_group(
    line_events: list[LayoutEvent],
    ready_hidden: list[LayoutEvent],
    emitted_hidden_event_ids: set[int],
) -> list[LayoutEvent]:
    """Keep a ready BZ musical segment contiguous before its visible twin."""

    ready_bz = [
        item
        for item in ready_hidden
        if item.block == "bz-hidden" and item.event.kind != MusicTokenKind.BARLINE
    ]
    if not ready_bz:
        return ready_hidden
    has_emitted_bz_segment = any(
        item.block == "bz-hidden"
        and item.event.kind != MusicTokenKind.BARLINE
        and id(item) in emitted_hidden_event_ids
        for item in line_events
    )
    if not has_emitted_bz_segment:
        return ready_hidden
    first_ready_index = min(line_events.index(item) for item in ready_bz)
    extended = list(ready_hidden)
    ready_ids = {id(item) for item in extended}
    for hidden_item in line_events[first_ready_index + 1 :]:
        if hidden_item.block != "bz-hidden":
            break
        if hidden_item.event.kind == MusicTokenKind.BARLINE:
            break
        hidden_id = id(hidden_item)
        if hidden_id not in emitted_hidden_event_ids and hidden_id not in ready_ids:
            extended.append(hidden_item)
            ready_ids.add(hidden_id)
    return extended


def _accessory_stream_sort_key(
    item: tuple[LayoutEvent, bool, int],
) -> tuple[float, float, int, int, int, int, int]:
    event, is_hidden, ordinal = item
    stream_position = (
        event.stream_slot if is_hidden and event.stream_slot is not None else event.slot
    )
    return (
        event.y,
        event.x,
        int(not is_hidden),
        event.line,
        stream_position,
        event.voice,
        ordinal,
    )


def _merge_hidden_visual_items(
    visible_items: list[tuple[LayoutEvent, bool, int]],
    hidden_items: list[tuple[LayoutEvent, bool, int]],
) -> list[tuple[LayoutEvent, bool, int]]:
    """Interleave hidden visual-row items without reordering visible source rows."""

    merged: list[tuple[LayoutEvent, bool, int]] = []
    hidden_index = 0
    for visible_item in visible_items:
        visible_key = _accessory_stream_sort_key(visible_item)
        while (
            hidden_index < len(hidden_items)
            and _accessory_stream_sort_key(hidden_items[hidden_index]) <= visible_key
        ):
            merged.append(hidden_items[hidden_index])
            hidden_index += 1
        merged.append(visible_item)
    merged.extend(hidden_items[hidden_index:])
    return merged


def _hidden_event_ready_for_stream(hidden_item: LayoutEvent, visible_item: LayoutEvent) -> bool:
    if hidden_item.stream_slot is not None:
        if hidden_item.event.kind == MusicTokenKind.BARLINE:
            return (
                visible_item.event.kind == MusicTokenKind.BARLINE
                and hidden_item.stream_slot <= visible_item.slot
            )
        return hidden_item.stream_slot <= visible_item.slot
    return hidden_item.x <= visible_item.x
