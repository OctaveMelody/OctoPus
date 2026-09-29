"""Pure visible-event selection and alignment-placeholder policies."""

from __future__ import annotations

from re_tomato.normalization.types import MusicEvent, SemanticConstruct
from re_tomato.render.layout_engine.hidden.hidden_streams import (
    with_bz_placeholders,
    with_dsb_placeholders,
)

from .visibility import is_visible_event


def visible_events_for_layout(
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
) -> list[MusicEvent]:
    visible_events = [event for event in events if is_visible_event(event)]
    suppressed_event_indices = {
        event_index
        for construct in constructs
        if construct.kind == "block" and construct.value in {None, "bz", "dsb"}
        for event_index in construct.event_indices
    }
    if suppressed_event_indices:
        visible_events = [
            event for event in visible_events if event.index not in suppressed_event_indices
        ]
    return with_alignment_placeholders(visible_events, events, constructs)


def with_alignment_placeholders(
    visible_events: list[MusicEvent],
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
) -> list[MusicEvent]:
    visible_events = with_bz_placeholders(visible_events, events, constructs)
    return with_dsb_placeholders(visible_events, events, constructs)


__all__ = ["visible_events_for_layout", "with_alignment_placeholders"]
