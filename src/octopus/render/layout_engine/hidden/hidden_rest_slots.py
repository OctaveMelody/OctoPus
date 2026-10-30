"""Hidden-rest slot compatibility reconciliation."""

from __future__ import annotations

from fractions import Fraction

from ....normalization.types import MusicEvent, SystemModel, VoiceModel
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
    event_duration_fraction,
)
from .hidden_streams import (
    hidden_rest_placeholder_event as _hidden_rest_placeholder_event,
)


def reconcile_hidden_rest_slots(
    layout_events: list[LayoutEvent],
    laid_out: list[LayoutEvent],
    tail_barlines: list[LayoutEvent],
    *,
    system: SystemModel | None = None,
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
            if not _needs_hidden_rest_before_barline(row, index, system):
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
    system: SystemModel | None = None,
) -> bool:
    previous = row[barline_index - 1]
    if previous.event.kind == MusicTokenKind.HIDDEN_REST:
        return False
    if _is_bz_placeholder_event(previous.event):
        return False
    if system is not None and _needs_hidden_rest_for_sustain_alignment(
        system, row, barline_index
    ):
        return True
    return _hidden_rest_slot_signature(row, barline_index) in _HIDDEN_REST_ROW_SIGNATURES


def _needs_hidden_rest_for_sustain_alignment(
    system: SystemModel,
    row: list[LayoutEvent],
    barline_index: int,
) -> bool:
    target = row[barline_index]
    if target.event.index < 0:
        return False
    source_line = target.event.span.start.line
    if not 0 <= target.voice < len(system.voices):
        return False
    current_voice = system.voices[target.voice]
    source_voice = current_voice.voice
    current_measures = _source_measures(current_voice, source_line)
    measure_index = next(
        (
            index
            for index, (_events, barline) in enumerate(current_measures)
            if barline.index == target.event.index
        ),
        None,
    )
    if measure_index is None or measure_index == 0:
        return False
    if any(
        item.event.kind == MusicTokenKind.HIDDEN_REST or item.block is not None
        for item in row[: barline_index + 1]
    ):
        return False

    current_region = current_measures[: measure_index + 1]
    current_events = current_measures[measure_index][0]
    if _region_has_hidden_or_block(current_voice, current_region):
        return False
    previous_durations = tuple(
        _measure_duration(events) for events, _barline in current_measures[:measure_index]
    )
    current_duration = _measure_duration(current_events)
    matching_groups = [
        group
        for group in system.voice_groups
        if group.is_multi_voice
        and any(
            address.voice == source_voice and address.source_line == source_line
            for address in group.rows
        )
    ]
    if len(matching_groups) != 1:
        return False

    group = matching_groups[0]
    eligible_siblings: list[tuple[Fraction, tuple[MusicEvent, ...]]] = []
    for address in group.rows:
        if address.voice == source_voice:
            continue
        sibling_voice = next(
            (voice for voice in system.voices if voice.voice == address.voice), None
        )
        if sibling_voice is None:
            continue
        sibling_measures = _source_measures(sibling_voice, address.source_line)
        if len(sibling_measures) <= measure_index:
            continue
        sibling_region = sibling_measures[: measure_index + 1]
        sibling_events = sibling_measures[measure_index][0]
        if _region_has_hidden_or_block(sibling_voice, sibling_region):
            continue
        if tuple(
            _measure_duration(events)
            for events, _barline in sibling_measures[:measure_index]
        ) != previous_durations:
            continue
        eligible_siblings.append((_measure_duration(sibling_events), sibling_events))

    if not eligible_siblings:
        return False
    maximum_duration = max(duration for duration, _events in eligible_siblings)
    maximum_siblings = [
        events for duration, events in eligible_siblings if duration == maximum_duration
    ]
    if maximum_duration - current_duration == Fraction(1):
        if len(group.rows) == 2:
            current_timed = tuple(
                event
                for event in current_events
                if event_duration_fraction(event) > 0
            )
            sibling_timed = tuple(
                tuple(
                    event
                    for event in events
                    if event_duration_fraction(event) > 0
                )
                for _duration, events in eligible_siblings
            )
            if (
                len(current_timed) == 1
                and current_timed[0].kind in {MusicTokenKind.NOTE, MusicTokenKind.REST}
                and all(
                    len(events) == 1
                    and events[0].kind in {MusicTokenKind.NOTE, MusicTokenKind.REST}
                    for events in sibling_timed
                )
            ):
                return False
        return True
    return any(
        _has_terminal_held_prefix_and_slashed_sibling_tail(
            current_events,
            events,
            previous_durations,
        )
        for events in maximum_siblings
    )


def _source_measures(
    voice: VoiceModel,
    source_line: int,
) -> list[tuple[tuple[MusicEvent, ...], MusicEvent]]:
    measures: list[tuple[tuple[MusicEvent, ...], MusicEvent]] = []
    current: list[MusicEvent] = []
    for event in voice.events:
        if event.span.start.line != source_line:
            continue
        if event.kind == MusicTokenKind.BARLINE:
            measures.append((tuple(current), event))
            current = []
        else:
            current.append(event)
    return measures


def _measure_duration(events: tuple[MusicEvent, ...]) -> Fraction:
    return sum((event_duration_fraction(event) for event in events), Fraction())


def _region_has_hidden_or_block(
    voice: VoiceModel,
    measures: list[tuple[tuple[MusicEvent, ...], MusicEvent]],
) -> bool:
    events = [event for measure, barline in measures for event in (*measure, barline)]
    indexes = {event.index for event in events}
    return any(event.kind == MusicTokenKind.HIDDEN_REST for event in events) or any(
        construct.kind == "block" and indexes.intersection(construct.event_indices)
        for construct in voice.constructs
    )


def _has_terminal_held_prefix_and_slashed_sibling_tail(
    current_events: tuple[MusicEvent, ...],
    sibling_events: tuple[MusicEvent, ...],
    preceding_durations: tuple[Fraction, ...],
) -> bool:
    current_timed = [
        event for event in current_events if event_duration_fraction(event) > 0
    ]
    if (
        len(current_timed) < 3
        or current_timed[0].kind != MusicTokenKind.NOTE
        or current_timed[-1].kind != MusicTokenKind.REST
        or event_duration_fraction(current_timed[-1]) != 1
        or not all(event.kind == MusicTokenKind.EXTENSION for event in current_timed[1:-1])
    ):
        return False
    current_end = sum(preceding_durations, Fraction()) + _measure_duration(current_events)
    if current_end.denominator != 1:
        return False

    ignored_decoration_kinds = {
        MusicTokenKind.ANNOTATION,
        MusicTokenKind.DECORATION,
    }
    current_prefix = [
        event for event in current_events if event.kind not in ignored_decoration_kinds
    ]
    sibling_sequence = [
        event for event in sibling_events if event.kind not in ignored_decoration_kinds
    ]
    prefix_size = len(current_prefix)
    if len(sibling_sequence) <= prefix_size:
        return False
    if tuple(
        (event.kind, event_duration_fraction(event)) for event in sibling_sequence[:prefix_size]
    ) != tuple(
        (event.kind, event_duration_fraction(event)) for event in current_prefix
    ):
        return False

    tail = sibling_sequence[prefix_size:]
    if any(
        event.kind != MusicTokenKind.NOTE or event.duration_slashes == 0
        for event in tail
    ):
        return False
    tail_duration = sum(
        (event_duration_fraction(event) for event in tail), Fraction()
    )
    return 0 < tail_duration < 1


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
