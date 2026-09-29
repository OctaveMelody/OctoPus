"""Carry lyric row ownership and lay out standalone empty lyric spacers."""

from __future__ import annotations

from re_tomato.normalization.types import SystemModel
from re_tomato.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
)
from re_tomato.render.layout_engine.lyrics.lyrics import (
    _append_empty_lyric_placeholders,
    _lyric_consumable_events,
)


def _layout_empty_standalone_lyric_spacers(
    layout: LayoutPage,
    system: SystemModel,
    previous_events: list[LayoutEvent],
) -> None:
    lyric_lines = tuple(
        sorted(
            (lyric for voice in system.voices for lyric in voice.lyrics),
            key=lambda lyric: lyric.span.start.offset,
        )
    )
    if not lyric_lines or any(lyric.tokens for lyric in lyric_lines) or not previous_events:
        return

    verse = _next_lyric_verse(layout, previous_events)
    consumable_events = _lyric_consumable_events(previous_events)
    bottom_row_y = max((event.y for event in previous_events), default=0.0)
    for _lyric_line in lyric_lines:
        _append_empty_lyric_placeholders(
            layout, consumable_events, verse, bottom_row_y
        )
        verse += 1


def _next_lyric_verse(layout: LayoutPage, events: list[LayoutEvent]) -> int:
    cipos_values = {event.address.notepos for event in events}
    return (
        max(
            (
                lyric.verse
                for lyric in layout.lyrics
                if lyric.cipos in cipos_values
            ),
            default=0,
        )
        + 1
    )


def _last_visible_row_lyric_events(
    layout: LayoutPage,
    system_line_start: int,
    system_rows: int,
) -> list[LayoutEvent]:
    system_events = [
        event
        for event in layout.events
        if system_line_start <= event.line < system_line_start + system_rows
    ]
    if not system_events:
        return []
    last_line = max(event.line for event in system_events)
    return [event for event in system_events if event.line == last_line]
