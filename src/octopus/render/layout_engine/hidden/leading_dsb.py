"""Source-onset projection for temporary voices beginning a music row."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fractions import Fraction

from octopus.normalization.types import MusicEvent, SemanticConstruct, SystemModel
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import LayoutEvent
from octopus.render.core.source_timing import (
    duration_fraction,
    project_source_onset,
    source_onsets,
)
from octopus.render.layout_engine.spacing.system_spacing import DSB_INCOMING_CLEARANCE


def is_leading_dsb_construct(
    construct: SemanticConstruct,
    visible_events: Iterable[MusicEvent],
    constructs: Sequence[SemanticConstruct],
) -> bool:
    """A sole row-leading block has no preceding main-stream musical anchor.

    Nested block ownership remains on the established layout path. An outer
    block includes its children's events, so treating both as independent
    leading streams would duplicate notes and advance their onsets twice.
    """
    return (
        construct.kind == "block"
        and construct.value in {None, "dsb"}
        and construct.source_span.start.line == construct.source_span.end.line
        and not any(
            other.kind == "block" and other is not construct
            and set(other.event_indices).intersection(construct.event_indices)
            for other in constructs
        )
        and not any(
            event.span.start.line == construct.source_span.start.line
            and event.span.start.offset < construct.source_span.start.offset
            for event in visible_events
        )
    )


def leading_dsb_targets(
    construct: SemanticConstruct, laid_out: Sequence[LayoutEvent]
) -> list[LayoutEvent]:
    """Return only written host events, excluding legacy spacing placeholders."""
    return sorted(
        (
            item for item in laid_out
            if item.event.index >= 0
            and item.event.span.start.line == construct.source_span.end.line
            and item.event.span.start.offset >= construct.source_span.end.offset
        ),
        key=lambda item: item.event.span.start.offset,
    )


def layout_leading_dsb_events(
    construct: SemanticConstruct,
    hidden_events: Sequence[MusicEvent],
    laid_out: Sequence[LayoutEvent],
    *,
    page_index: int,
    voice: int,
) -> list[LayoutEvent]:
    targets = leading_dsb_targets(construct, laid_out)
    if not targets:
        return []
    timeline = source_onsets(targets)
    onset = Fraction()
    result: list[LayoutEvent] = []
    for event in hidden_events:
        x, target, exact = project_source_onset(onset, event.kind, timeline)
        result.append(LayoutEvent(
            event=event,
            x=x,
            y=targets[0].y - DSB_INCOMING_CLEARANCE,
            page_index=page_index,
            voice=voice,
            line=target.line,
            slot=target.slot,
            block="dsb-hidden",
            stream_slot=target.slot,
            onset_slot=target.slot if exact else None,
            onset_aligned=exact,
        ))
        onset += duration_fraction(event)
    return result


def lower_leading_dsb_targets(
    construct: SemanticConstruct,
    hidden_events: Sequence[MusicEvent],
    laid_out: Sequence[LayoutEvent],
    shifted_items: set[int],
) -> None:
    """Lower the covered source interval; an unfinished measure adds no time."""
    duration = sum((duration_fraction(event) for event in hidden_events), Fraction())
    closes_on_barline = bool(hidden_events) and hidden_events[-1].kind == MusicTokenKind.BARLINE
    targets = leading_dsb_targets(construct, laid_out)
    for onset, item in source_onsets(targets):
        # An unfinished upper stream does not take ownership of the host's
        # terminal separator, including when its written duration exceeds
        # that shorter host row. Keep the established main-row separator.
        if (
            item is targets[-1]
            and item.event.kind == MusicTokenKind.BARLINE
            and not closes_on_barline
        ):
            continue
        if onset < duration or (
            closes_on_barline and onset == duration and item.event.kind == MusicTokenKind.BARLINE
        ):
            if id(item) not in shifted_items:
                item.y += DSB_INCOMING_CLEARANCE
                shifted_items.add(id(item))


def reproject_leading_dsb_events(
    system: SystemModel,
    laid_out: Sequence[LayoutEvent],
    hidden_events: Sequence[LayoutEvent],
) -> None:
    """Follow finalized host columns after shared and legacy row projection."""
    for voice_index, voice in enumerate(system.voices):
        visible = [item for item in laid_out if item.voice == voice_index]
        for construct in voice.constructs:
            if not is_leading_dsb_construct(
                construct, (item.event for item in visible), voice.constructs
            ):
                continue
            targets = leading_dsb_targets(construct, visible)
            if not targets:
                continue
            indices = frozenset(construct.event_indices)
            items = sorted(
                (item for item in hidden_events
                 if item.voice == voice_index and item.event.index in indices
                 and item.event.span.start.line == construct.source_span.start.line),
                key=lambda item: item.event.span.start.offset,
            )
            timeline = source_onsets(targets)
            onset = Fraction()
            for item in items:
                x, target, exact = project_source_onset(onset, item.event.kind, timeline)
                item.x = x
                item.style_x = x
                item.stream_slot = target.slot
                item.onset_slot = target.slot if exact else None
                item.onset_aligned = exact
                item.projection_kind = target.projection_kind
                item.projection_scale = target.projection_scale
                onset += duration_fraction(item.event)
