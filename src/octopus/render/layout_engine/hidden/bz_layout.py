"""Complete, source-driven placement of temporary accompaniment streams."""

from __future__ import annotations

from fractions import Fraction

from octopus.normalization.types import MusicEvent, SemanticConstruct, SystemModel
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import LayoutEvent, PageMetrics
from octopus.render.core.layout_widths import MEASURE_GAP, NOTE_WIDTH
from octopus.render.layout_engine.visibility import is_visible_event

from .hidden_streams import event_duration_fraction, outer_bz_constructs


def bz_target_source_lines(
    visible_events: list[MusicEvent],
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
) -> frozenset[int]:
    """Find melody rows that need room above them for a BZ stream."""
    source = {event.index: event for event in events}
    result: set[int] = set()
    for block in outer_bz_constructs(constructs):
        hidden = [source[index] for index in block.event_indices if index in source]
        if not any(is_visible_event(event) and event.kind != MusicTokenKind.BARLINE
                   for event in hidden):
            continue
        measure_count = max(
            1, len(_measures([event for event in hidden if is_visible_event(event)]))
        )
        following = [
            event for event in visible_events
            if event.span.start.offset >= block.source_span.end.offset
        ]
        for measure in _measures(following)[:measure_count]:
            result.update(event.span.start.line for event in measure)
    return frozenset(result)


def layout_bz_events(
    block: SemanticConstruct,
    hidden: list[MusicEvent],
    laid_out: list[LayoutEvent],
    *,
    page_index: int,
    voice: int,
    metrics: PageMetrics,
) -> list[LayoutEvent]:
    """Retain every BZ event, preserving established complete-slot placement."""
    following = sorted(
        (
            item for item in laid_out
            if item.event.span.start.offset >= block.source_span.end.offset
        ),
        key=lambda item: (item.line, item.x, item.slot),
    )
    targets = _layout_measures(following)
    hidden_measures = _measures(hidden)
    if not targets or not hidden_measures:
        return []
    result: list[LayoutEvent] = []
    block_index = 0
    for index, target in enumerate(targets[:len(hidden_measures)]):
        # If the melody ends first, retain the remaining accompaniment on the
        # final available span. Such unequal measure counts need source review.
        measure = (
            [event for remaining in hidden_measures[index:] for event in remaining]
            if index == len(targets) - 1
            else hidden_measures[index]
        )
        notes = [event for event in measure if event.kind != MusicTokenKind.BARLINE]
        slots = [item for item in target if item.event.kind != MusicTokenKind.BARLINE]
        previous_target = targets[index - 1][-1] if index > 0 else None
        empty_left = (
            previous_target.x + MEASURE_GAP
            if previous_target is not None and previous_target.line == target[0].line
            else metrics.note_start_x
        )
        tail = next((item for item in target if item.event.kind == MusicTokenKind.BARLINE), None)
        legacy = (
            len(hidden_measures) == 1
            and bool(slots)
            and len(notes) <= len(slots)
            and all(item.line == slots[0].line for item in slots)
            and slots[0].event.span.start.line == block.source_span.end.line
            and slots[0].event.raw != "{bz-host-placeholder}"
        )
        if legacy:
            positions = [(item.x, item) for item in slots[:len(notes)]]
        else:
            positions = _duration_positions(measure, target, metrics, empty_left=empty_left)
        position_index = 0
        measure_start = len(result)
        for event in measure:
            block_index += int(event.kind != MusicTokenKind.BARLINE)
            if event.kind == MusicTokenKind.BARLINE and legacy:
                if tail is None:
                    continue
                x, anchor = tail.x, tail
            else:
                x, anchor = positions[position_index]
                position_index += 1
            item = LayoutEvent(
                event=event, x=x, y=anchor.y - 40.0, page_index=page_index,
                voice=voice, line=anchor.line, slot=anchor.slot,
                block="bz-hidden", block_index=block_index,
            )
            result.append(item)
        _assign_stream_slots(result[measure_start:], target, legacy=legacy)
    return result


def reproject_bz_events(
    system: SystemModel,
    laid_out: list[LayoutEvent],
    hidden_events: list[LayoutEvent],
    *,
    page_index: int,
    metrics: PageMetrics,
) -> None:
    """Update existing BZ objects after the final visible shared-grid passes."""
    for voice_index, voice in enumerate(system.voices):
        source = {event.index: event for event in voice.events}
        existing = {
            item.event.index: item for item in hidden_events
            if item.voice == voice_index and item.block == "bz-hidden"
        }
        for block in outer_bz_constructs(voice.constructs):
            events = [source[index] for index in block.event_indices if index in existing]
            projected = layout_bz_events(
                block, events, [item for item in laid_out if item.voice == voice_index],
                page_index=page_index, voice=voice_index, metrics=metrics,
            )
            for replacement in projected:
                item = existing[replacement.event.index]
                item.x, item.y = replacement.x, replacement.y
                item.line, item.slot = replacement.line, replacement.slot
                item.stream_slot = replacement.stream_slot


def _measures(events: list[MusicEvent]) -> list[list[MusicEvent]]:
    result: list[list[MusicEvent]] = []
    current: list[MusicEvent] = []
    for event in events:
        current.append(event)
        if event.kind == MusicTokenKind.BARLINE:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result


def _layout_measures(events: list[LayoutEvent]) -> list[list[LayoutEvent]]:
    result: list[list[LayoutEvent]] = []
    current: list[LayoutEvent] = []
    for index, item in enumerate(events):
        if item.event.kind == MusicTokenKind.BARLINE and item.event.index < 0:
            # A generated physical-row ending is not a source measure boundary.
            if index == len(events) - 1:
                current.append(item)
            continue
        current.append(item)
        if item.event.kind == MusicTokenKind.BARLINE:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result


def _duration_positions(
    events: list[MusicEvent], target: list[LayoutEvent], metrics: PageMetrics,
    *, empty_left: float,
) -> list[tuple[float, LayoutEvent]]:
    notes = [item for item in target if item.event.kind != MusicTokenKind.BARLINE]
    tail = next((item for item in target if item.event.kind == MusicTokenKind.BARLINE), None)
    if all(event.kind == MusicTokenKind.BARLINE for event in events):
        anchor = tail or target[-1]
        return [(anchor.x, anchor) for _event in events]
    bare_target = not notes
    if bare_target:
        notes = [target[0]]
    musical = [item for item in notes if item.block != "bz-placeholder"] or notes
    duration = sum((event_duration_fraction(event) for event in events), Fraction(0))
    target_duration = sum(
        (event_duration_fraction(item.event) for item in musical), Fraction(0)
    )
    if duration <= 0:
        duration = Fraction(len(events))
    if target_duration <= 0:
        target_duration = Fraction(1)
    right = tail.x if tail else min(
        float(metrics.width - metrics.margin_right + 3), notes[-1].x + NOTE_WIDTH
    )
    anchors: list[tuple[Fraction, float, LayoutEvent]] = []
    onset = Fraction(0)
    for item in musical:
        anchors.append((onset, item.x, item))
        onset += event_duration_fraction(item.event)
    if bare_target or all(item.event.raw == "{bz-host-placeholder}" for item in musical):
        left = empty_left if bare_target or musical[0].x >= right else musical[0].x
        left = max(metrics.note_start_x, min(left, right - NOTE_WIDTH))
        anchors = [(Fraction(0), left, musical[0])]
    anchors.append((target_duration, right, tail or notes[-1]))
    result: list[tuple[float, LayoutEvent]] = []
    onset = Fraction(0)
    for event in events:
        target_onset = onset * target_duration / duration
        if event.kind == MusicTokenKind.BARLINE and target_onset == target_duration and tail:
            result.append((tail.x, tail))
            continue
        segment = next(
            (index for index in range(len(anchors) - 1)
             if anchors[index + 1][0] > target_onset),
            len(anchors) - 2,
        )
        start, end = anchors[segment:segment + 2]
        width = end[0] - start[0]
        ratio = float((target_onset - start[0]) / width) if width > 0 else 0.0
        segment_right = (
            float(metrics.width - metrics.margin_right + 3)
            if end[2].line != start[2].line
            else end[1]
        )
        result.append((start[1] + ratio * (segment_right - start[1]), start[2]))
        onset += event_duration_fraction(event)
    return result


def _assign_stream_slots(
    hidden: list[LayoutEvent], target: list[LayoutEvent], *, legacy: bool,
) -> None:
    # Preserve the established one-quarter stream flush groups independently
    # from geometric interpolation and the renderer's explicit beam overrides.
    onset = Fraction(0)
    slots: list[tuple[Fraction, int]] = []
    for item in target:
        if item.event.kind != MusicTokenKind.BARLINE and item.block != "bz-placeholder":
            slots.append((onset, item.slot))
        if legacy or item.block != "bz-placeholder":
            onset += event_duration_fraction(item.event)
    group_slot: int | None = None
    bucket: int | None = None
    onset = Fraction(0)
    for item in hidden:
        if item.event.kind == MusicTokenKind.BARLINE:
            item.stream_slot = target[-1].slot
            group_slot, bucket = None, None
        else:
            current_bucket = int(onset // 1)
            if bucket != current_bucket:
                group_slot = next(
                    (slot for start, slot in slots if start >= onset),
                    slots[-1][1] if slots else item.slot,
                )
                bucket = current_bucket
            item.stream_slot = group_slot
        onset += event_duration_fraction(item.event)
