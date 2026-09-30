"""Event, hidden-event, accessory, and audio SVG stream rendering."""

from __future__ import annotations

from ...parser.ast import MusicTokenKind
from ..core.elements import RenderElement, SvgElement
from ..core.layout_types import LayoutEvent, LayoutMark, LayoutPage
from .accessories import event_accessory_item_elements as _event_accessory_item_elements
from .event_policy import effective_event_audio as _effective_event_audio
from .event_policy import event_glyph_id as _event_glyph_id
from .event_policy import event_render_code as _event_render_code
from .event_policy import is_hidden_block_endpoint_barline as _is_hidden_block_endpoint_barline
from .event_policy import is_suppressed_dsb_hidden_slur_rest as _is_suppressed_dsb_hidden_slur_rest
from .event_policy import (
    previous_hidden_event_on_source_line as _previous_hidden_event_on_source_line,
)
from .event_policy import (
    previous_visible_musical_by_layout_event as _previous_visible_musical_by_layout_event,
)
from .marks import (
    _inline_time_signature,
    _inline_time_signature_elements,
    _is_standalone_glyph_decoration_mark,
    _mark_element,
)


def _render_event_elements(layout: LayoutPage) -> list[RenderElement]:
    elements: list[RenderElement] = []
    previous_musical_by_event_id = _previous_visible_musical_by_layout_event(layout)
    marks_by_host = {
        (mark.host.voice, mark.host.line, mark.host.slot): mark
        for mark in layout.marks
        if _inline_time_signature(mark) is not None
    }
    for item in layout.events:
        elements.extend(
            _event_item_elements(
                layout,
                item,
                marks_by_host,
                previous_musical_by_event_id,
            )
        )
    for item in layout.hidden_events:
        elements.extend(
            _event_item_elements(
                layout,
                item,
                marks_by_host,
                previous_musical_by_event_id,
            )
        )
    return elements


def _event_item_elements(
    layout: LayoutPage,
    item: LayoutEvent,
    marks_by_host: dict[tuple[int, int, int], LayoutMark],
    previous_musical_by_event_id: dict[int, LayoutEvent | None],
) -> list[RenderElement]:
    event = item.event
    if _is_suppressed_dsb_hidden_slur_rest(layout, item):
        return []
    if event.kind not in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.BARLINE,
        MusicTokenKind.EXTENSION,
    }:
        return []
    elements: list[RenderElement] = []
    element = _render_event_element(layout, item, previous_musical_by_event_id)
    if element is not None:
        elements.append(element)
    if item.block == "bz" and item.block_index > 0 and item.block_index % 2 == 0:
        elements.append(_render_bz_placeholder_element(item))
    mark = marks_by_host.get((item.voice, item.line, item.slot))
    if mark is not None:
        elements.extend(_inline_time_signature_elements(mark, layout))
    return elements




def _event_accessory_elements(layout: LayoutPage) -> list[SvgElement]:
    decoration_marks_by_host: dict[tuple[int, int, int], list[LayoutMark]] = {}
    for mark in layout.marks:
        if _is_standalone_glyph_decoration_mark(mark):
            decoration_marks_by_host.setdefault(
                (mark.host.voice, mark.host.line, mark.host.slot), []
            ).append(mark)

    elements: list[SvgElement] = []
    for item in layout.events:
        elements.extend(_event_accessory_item_elements(item, item.event, include_decorations=False))
        for mark in decoration_marks_by_host.get((item.voice, item.line, item.slot), []):
            elements.extend(_mark_element(mark))
    return elements




def _event_decoration_elements(layout: LayoutPage) -> list[SvgElement]:
    elements: list[SvgElement] = []
    for item in layout.events:
        elements.extend(_event_accessory_item_elements(item, item.event, include_decorations=True))
    return elements


def _render_event_element(
    layout: LayoutPage,
    item: LayoutEvent,
    previous_musical_by_event_id: dict[int, LayoutEvent | None],
) -> RenderElement | None:
    event = item.event
    glyph_id = _event_glyph_id(layout, item)
    if glyph_id is None:
        return None
    if item.block == "bz" and event.kind == MusicTokenKind.BARLINE:
        return RenderElement(
            glyph_id=glyph_id,
            code=None,
            time=None,
            audio=None,
            x=item.x,
            y=float(int(item.y)),
            notepos=None,
            source_event_index=event.index if event.index >= 0 else None,
            layer="event",
            construct_ids=event.construct_ids,
            synthetic=event.index < 0,
        )
    if item.block == "bz-tail" and event.kind == MusicTokenKind.BARLINE:
        return RenderElement(
            glyph_id=glyph_id,
            code=None,
            time=None,
            audio=None,
            x=item.x,
            y=float(int(item.y)),
            notepos=item.address.notepos,
            source_event_index=event.index if event.index >= 0 else None,
            layer="event",
            construct_ids=event.construct_ids,
            synthetic=event.index < 0,
        )
    if item.block == "dsb-tail" and event.kind == MusicTokenKind.BARLINE:
        # DSB-region barlines serialize without the code attribute (the
        # reference keeps code="" only on bz placeholder notes; all 285
        # dsb-tail/hidden barline uses across the corpus omit it).
        return RenderElement(
            glyph_id=glyph_id,
            code=None,
            time=None,
            audio=None,
            x=item.x,
            y=float(int(item.y)),
            notepos=item.address.notepos,
            source_event_index=event.index if event.index >= 0 else None,
            layer="event",
            construct_ids=event.construct_ids,
            synthetic=event.index < 0,
        )
    if (
        item.block in {"bz-hidden", "dsb-hidden", "dsb-hidden-tail"}
        and event.kind == MusicTokenKind.BARLINE
    ):
        if _visible_tail_for_hidden_block_endpoint(layout, item) is not None:
            return None
        return RenderElement(
            glyph_id=glyph_id,
            code=None,
            time=None,
            audio=None,
            x=item.x,
            y=float(int(item.y)),
            notepos=None,
            source_event_index=event.index if event.index >= 0 else None,
            layer="event",
            construct_ids=event.construct_ids,
            synthetic=event.index < 0,
        )
    notepos = (
        f"{item.page_index}__"
        if item.block in {"bz-hidden", "dsb-hidden", "dsb-hidden-tail"}
        else item.address.notepos
    )
    code: str | None = _event_render_code(layout, item)
    if event.kind == MusicTokenKind.BARLINE and code == "":
        code = None
    audio = _effective_event_audio(layout, item, previous_musical_by_event_id)
    return RenderElement(
        glyph_id=glyph_id,
        code=code,
        time=event.time,
        audio=audio,
        x=item.x,
        y=float(int(item.y)),
        notepos=notepos,
        source_event_index=event.index if event.index >= 0 else None,
        layer="event",
        construct_ids=event.construct_ids,
        synthetic=event.index < 0,
    )


def _render_bz_placeholder_element(item: LayoutEvent) -> RenderElement:
    return RenderElement(
        glyph_id="shuzi_b_",
        code="",
        time="1",
        audio="",
        x=item.x,
        y=float(int(item.y + 40)),
        notepos="placeholder",
        source_event_index=item.event.index if item.event.index >= 0 else None,
        layer="bz-placeholder",
        construct_ids=item.event.construct_ids,
        synthetic=True,
    )

def _visible_tail_for_hidden_block_endpoint(
    layout: LayoutPage,
    hidden_endpoint: LayoutEvent,
) -> LayoutEvent | None:
    if not _is_hidden_block_endpoint_barline(layout, hidden_endpoint):
        return None
    hidden_construct_ids = set(hidden_endpoint.event.construct_ids)
    hidden_barline_count = sum(
        1
        for item in layout.hidden_events
        if item.block in {"dsb-hidden", "dsb-hidden-tail"}
        and item.event.kind == MusicTokenKind.BARLINE
        and hidden_construct_ids.intersection(item.event.construct_ids)
    )
    if hidden_barline_count != 1:
        return None
    return next(
        (
            item
            for item in layout.events
            if item.event.kind == MusicTokenKind.BARLINE
            and item.line == hidden_endpoint.line
            and item.slot == hidden_endpoint.stream_slot
        ),
        None,
    )


__all__ = [
    "_event_accessory_elements",
    "_event_decoration_elements",
    "_event_item_elements",
    "_is_hidden_block_endpoint_barline",
    "_previous_hidden_event_on_source_line",
    "_previous_visible_musical_by_layout_event",
    "_render_event_elements",
    "_visible_tail_for_hidden_block_endpoint",
]
