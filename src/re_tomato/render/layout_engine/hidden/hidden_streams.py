"""Hidden-stream placeholder construction for aligned layout voices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from re_tomato.normalization.types import MusicEvent, SemanticConstruct
from re_tomato.parser.ast import MusicTokenKind
from re_tomato.render.core.layout_types import LayoutEvent, _SyntheticIndexAllocator
from re_tomato.render.layout_engine.visibility import (
    is_bz_placeholder_event,
    is_dsb_placeholder_event,
    is_visible_event,
)

BZ_PLACEHOLDER_INDEX_START = -100000


@dataclass(frozen=True)
class BlockTailIdentity:
    dsb_tail_barline_indices: frozenset[int]
    dsb_tail_advance_indices: frozenset[int]
    dsb_placeholder_barline_indices: frozenset[int]
    dsb_generated_tail_reference_indices: frozenset[int]
    bz_tail_barline_indices: frozenset[int]

    def block_for_event(self, event: MusicEvent) -> str | None:
        if is_bz_placeholder_event(event):
            return "bz-placeholder"
        if is_dsb_placeholder_event(event):
            return "dsb-placeholder"
        if event.index in self.dsb_tail_barline_indices:
            return "dsb-tail"
        return None

    def advances_slot(self, event: MusicEvent) -> bool:
        if event.index in self.bz_tail_barline_indices:
            return False
        return (
            event.index not in self.dsb_tail_barline_indices
            or event.index in self.dsb_tail_advance_indices
        )

    def is_dsb_generated_tail_reference(self, event: MusicEvent) -> bool:
        return event.index in self.dsb_generated_tail_reference_indices


def hidden_rest_placeholder_event(reference: MusicEvent, index: int) -> MusicEvent:
    return MusicEvent(
        index=index,
        kind=MusicTokenKind.HIDDEN_REST,
        raw="8",
        span=reference.span,
        code="8",
        source_code="8",
        render_code="8",
        pitch=8,
        time="0",
        audio="",
    )


def empty_alignment_placeholder_event(
    reference: MusicEvent,
    index: int,
    raw: str,
) -> MusicEvent:
    return MusicEvent(
        index=index,
        kind=MusicTokenKind.HIDDEN_REST,
        raw=raw,
        span=reference.span,
        code="",
        source_code="",
        render_code="",
        pitch=None,
        time="1",
        audio="",
    )


def bz_placeholder_event(reference: MusicEvent, index: int) -> MusicEvent:
    return empty_alignment_placeholder_event(reference, index, "{bz-placeholder}")


def with_bz_placeholders(
    visible_events: list[MusicEvent],
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
) -> list[MusicEvent]:
    placeholders_after: dict[int, int] = {}
    source_by_index = {event.index: event for event in events}
    for construct in constructs:
        if (
            construct.kind != "block"
            or construct.value != "bz"
            or construct.end_event_index is None
        ):
            continue
        hidden_count = sum(
            1
            for event_index in construct.event_indices
            if (event := source_by_index.get(event_index)) is not None
            and is_visible_event(event)
            and event.kind != MusicTokenKind.BARLINE
        )
        placeholder_count = hidden_count // 2
        if placeholder_count == 0:
            continue
        following_events = [
            event
            for event in visible_events
            if event.index > construct.end_event_index
            and event.span.start.line == construct.source_span.end.line
            and event.kind != MusicTokenKind.BARLINE
        ]
        for event in following_events[:placeholder_count]:
            placeholders_after[event.index] = placeholders_after.get(event.index, 0) + 1

    if not placeholders_after:
        return visible_events

    result: list[MusicEvent] = []
    placeholder_indices = _SyntheticIndexAllocator(BZ_PLACEHOLDER_INDEX_START)
    for event in visible_events:
        result.append(event)
        for _ in range(placeholders_after.get(event.index, 0)):
            result.append(bz_placeholder_event(event, placeholder_indices.take()))
    return result


def block_tail_identity(
    visible_events: list[MusicEvent],
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
) -> BlockTailIdentity:
    source_by_index = {event.index: event for event in events}
    dsb_tail_indices: set[int] = set()
    dsb_advance_indices: set[int] = set()
    dsb_placeholder_indices: set[int] = set()
    dsb_generated_reference_indices: set[int] = set()
    bz_tail_indices = bz_tail_barline_indices(visible_events, constructs)

    for construct in constructs:
        if (
            construct.kind != "block"
            or construct.value not in {None, "dsb"}
            or construct.end_event_index is None
        ):
            continue
        suppressed_barline_count = suppressed_barline_count_for(construct, source_by_index)
        following_barlines = following_barlines_after_construct(visible_events, construct)

        if suppressed_barline_count == 0:
            following_source_barlines = following_barlines_after_construct(list(events), construct)
            if not following_source_barlines:
                dsb_generated_reference_indices.update(
                    dsb_generated_tail_reference_indices(visible_events, construct)
                )
            continue

        for event in following_barlines[:suppressed_barline_count]:
            dsb_tail_indices.add(event.index)
            if construct.value == "dsb" and suppressed_barline_count == 1:
                dsb_advance_indices.add(event.index)

        if dsb_has_trailing_segment(construct, source_by_index):
            implicit_tail = event_after_explicit_dsb_tail_barlines(
                following_barlines,
                suppressed_barline_count,
            )
            if implicit_tail is not None:
                dsb_tail_indices.add(implicit_tail.index)
                dsb_advance_indices.add(implicit_tail.index)
                dsb_placeholder_indices.add(implicit_tail.index)

    return BlockTailIdentity(
        dsb_tail_barline_indices=frozenset(dsb_tail_indices),
        dsb_tail_advance_indices=frozenset(dsb_advance_indices),
        dsb_placeholder_barline_indices=frozenset(dsb_placeholder_indices),
        dsb_generated_tail_reference_indices=frozenset(dsb_generated_reference_indices),
        bz_tail_barline_indices=frozenset(bz_tail_indices),
    )


def suppressed_barline_count_for(
    construct: SemanticConstruct,
    source_by_index: dict[int, MusicEvent],
) -> int:
    return sum(
        1
        for event_index in construct.event_indices
        if (event := source_by_index.get(event_index)) is not None
        and event.kind == MusicTokenKind.BARLINE
    )


def following_barlines_after_construct(
    visible_events: list[MusicEvent],
    construct: SemanticConstruct,
) -> list[MusicEvent]:
    if construct.end_event_index is None:
        return []
    return [
        event
        for event in visible_events
        if event.index > construct.end_event_index
        and event.span.start.line == construct.source_span.end.line
        and event.kind == MusicTokenKind.BARLINE
    ]


def dsb_generated_tail_reference_indices(
    visible_events: list[MusicEvent],
    construct: SemanticConstruct,
) -> set[int]:
    if construct.end_event_index is None:
        return set()
    trailing_visible_events = [
        event
        for event in visible_events
        if event.index > construct.end_event_index
        and event.span.start.line == construct.source_span.end.line
        and event.kind != MusicTokenKind.BARLINE
    ]
    return {event.index for event in trailing_visible_events}


def dsb_has_trailing_segment(
    construct: SemanticConstruct,
    source_by_index: dict[int, MusicEvent],
) -> bool:
    construct_events = [
        event
        for event_index in construct.event_indices
        if (event := source_by_index.get(event_index)) is not None and is_visible_event(event)
    ]
    last_barline_position = next(
        (
            position
            for position in range(len(construct_events) - 1, -1, -1)
            if construct_events[position].kind == MusicTokenKind.BARLINE
        ),
        None,
    )
    if last_barline_position is None:
        return False
    return any(
        event.kind != MusicTokenKind.BARLINE
        for event in construct_events[last_barline_position + 1 :]
    )


def event_after_explicit_dsb_tail_barlines(
    following_barlines: list[MusicEvent],
    suppressed_barline_count: int,
) -> MusicEvent | None:
    if len(following_barlines) <= suppressed_barline_count:
        return None
    return following_barlines[suppressed_barline_count]


def bz_tail_barline_indices(
    visible_events: list[MusicEvent],
    constructs: tuple[SemanticConstruct, ...],
) -> set[int]:
    tail_indices: set[int] = set()
    for construct in constructs:
        if (
            construct.kind != "block"
            or construct.value != "bz"
            or construct.end_event_index is None
        ):
            continue
        tail = next(
            (
                event
                for event in visible_events
                if event.index > construct.end_event_index
                and event.span.start.line == construct.source_span.end.line
                and event.kind == MusicTokenKind.BARLINE
            ),
            None,
        )
        if tail is not None:
            tail_indices.add(tail.index)
    return tail_indices


def generated_tail_barline(reference: MusicEvent) -> MusicEvent:
    return MusicEvent(
        index=-1,
        kind=MusicTokenKind.BARLINE,
        raw="|/",
        span=reference.span,
        code="|w",
        time="0",
        audio="",
    )


def with_dsb_placeholders(
    visible_events: list[MusicEvent],
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
) -> list[MusicEvent]:
    tail_identity = block_tail_identity(visible_events, events, constructs)
    placeholders_before = tail_identity.dsb_placeholder_barline_indices
    if not placeholders_before:
        return visible_events

    result: list[MusicEvent] = []
    placeholder_indices = _SyntheticIndexAllocator(-150000)
    for event in visible_events:
        if event.index in placeholders_before:
            result.append(
                empty_alignment_placeholder_event(
                    event,
                    placeholder_indices.take(),
                    "{dsb-placeholder}",
                )
            )
        result.append(event)
    return result


@dataclass(frozen=True)
class HiddenDsbStreamGroup:
    onset: Fraction
    items: tuple[LayoutEvent, ...]


def event_duration_fraction(event: MusicEvent) -> Fraction:
    if event.duration is not None:
        return Fraction(event.duration.numerator, event.duration.denominator)
    if event.time in {None, ""}:
        return Fraction(0, 1)
    return Fraction(str(event.time))


def hidden_dsb_stream_groups(
    hidden_measure: list[LayoutEvent],
    *,
    group_unit: Fraction,
) -> list[HiddenDsbStreamGroup]:
    groups: list[HiddenDsbStreamGroup] = []
    onset = Fraction(0, 1)
    group_onset = onset
    group_items: list[LayoutEvent] = []
    group_duration = Fraction(0, 1)
    non_barline_events = [
        item for item in hidden_measure if item.event.kind != MusicTokenKind.BARLINE
    ]
    for index, item in enumerate(non_barline_events):
        duration = event_duration_fraction(item.event)
        if not group_items:
            group_onset = onset
        group_items.append(item)
        group_duration += duration
        onset += duration

        next_item = (
            non_barline_events[index + 1] if index + 1 < len(non_barline_events) else None
        )
        if next_item is None or ends_hidden_dsb_stream_group(
            item,
            next_item,
            group_duration,
            group_unit=group_unit,
        ):
            groups.append(HiddenDsbStreamGroup(group_onset, tuple(group_items)))
            group_items = []
            group_duration = Fraction(0, 1)
    return groups


def ends_hidden_dsb_stream_group(
    item: LayoutEvent,
    next_item: LayoutEvent,
    group_duration: Fraction,
    *,
    group_unit: Fraction,
) -> bool:
    next_duration = event_duration_fraction(next_item.event)
    if continues_same_slur_group(item, next_item) and group_duration + next_duration <= 1:
        return False
    if group_duration >= group_unit:
        return True
    if starts_slur_group(next_item):
        return True
    return next_duration >= 1


def continues_same_slur_group(item: LayoutEvent, next_item: LayoutEvent) -> bool:
    item_slurs = {
        role.rsplit(":", 1)[0]
        for role in item.event.construct_roles
        if ":slur:" in role and role.endswith(":start")
    }
    next_slurs = {
        role.rsplit(":", 1)[0]
        for role in next_item.event.construct_roles
        if ":slur:" in role and role.endswith(":end")
    }
    return bool(item_slurs.intersection(next_slurs))


def starts_slur_group(item: LayoutEvent) -> bool:
    return any(":slur:" in role and role.endswith(":start") for role in item.event.construct_roles)


def target_slots_by_onset(target_measure: list[LayoutEvent]) -> list[tuple[Fraction, int]]:
    result: list[tuple[Fraction, int]] = []
    onset = Fraction(0, 1)
    for item in target_measure:
        if item.event.kind == MusicTokenKind.BARLINE:
            onset += event_duration_fraction(item.event)
            continue
        if item.block in {"bz-placeholder", "dsb-placeholder"}:
            onset += event_duration_fraction(item.event)
            continue
        result.append((onset, item.slot))
        onset += event_duration_fraction(item.event)
    return result


def target_slot_at_or_after_onset(
    target_slots_by_onset: list[tuple[Fraction, int]],
    onset: Fraction,
    *,
    default: int,
) -> int:
    for target_onset, slot in target_slots_by_onset:
        if target_onset >= onset:
            return slot
    if target_slots_by_onset:
        return target_slots_by_onset[-1][1]
    return default


def append_hidden_dsb_tail_barline_if_needed(
    hidden_measure: list[LayoutEvent],
    target_measure: list[LayoutEvent],
    *,
    page_index: int,
    voice: int,
) -> None:
    if not hidden_measure or hidden_measure[-1].event.kind == MusicTokenKind.BARLINE:
        return
    target_barline = next(
        (item for item in target_measure if item.event.kind == MusicTokenKind.BARLINE),
        None,
    )
    if (
        target_barline is None
        or target_barline.block != "dsb-tail"
        or target_barline.event.index >= 0
    ):
        return
    hidden_measure.append(
        LayoutEvent(
            event=generated_tail_barline(hidden_measure[-1].event),
            x=target_barline.x,
            y=target_barline.y - 28.0,
            page_index=page_index,
            voice=voice,
            line=target_barline.line,
            slot=target_barline.slot,
            block="dsb-hidden-tail",
            stream_slot=target_barline.slot,
        )
    )


def assign_hidden_dsb_stream_slots(
    hidden_measure: list[LayoutEvent],
    target_measure: list[LayoutEvent],
    *,
    beat_unit: Fraction,
    target_slot_by_beat_bucket: Callable[..., dict[int, int]],
    duration_bucket: Callable[[Fraction, Fraction], int],
) -> None:
    target_slots = target_slots_by_onset(target_measure)
    target_barline = next(
        (item for item in target_measure if item.event.kind == MusicTokenKind.BARLINE),
        None,
    )
    for group in hidden_dsb_stream_groups(hidden_measure, group_unit=beat_unit):
        group_slot = target_slot_at_or_after_onset(
            target_slots,
            group.onset,
            default=group.items[0].slot,
        )
        for item in group.items:
            item.stream_slot = group_slot
    for item in hidden_measure:
        if item.event.kind == MusicTokenKind.BARLINE:
            item.stream_slot = target_barline.slot if target_barline is not None else item.slot
            if (
                target_barline is not None
                and target_barline.block == "dsb-tail"
                and target_barline.event.index < 0
            ):
                item.block = "dsb-hidden-tail"
    _assign_exact_onset_slots(hidden_measure, target_measure)


def _assign_exact_onset_slots(
    hidden_measure: list[LayoutEvent], target_measure: list[LayoutEvent]
) -> None:
    """Pair hidden events with visible columns when rational rhythm matches."""
    hidden_items = [
        item for item in hidden_measure
        if item.event.kind != MusicTokenKind.BARLINE
        and item.block not in {"bz-placeholder", "dsb-placeholder"}
    ]
    target_items = [
        item for item in target_measure
        if item.event.kind != MusicTokenKind.BARLINE
        and item.block not in {"bz-placeholder", "dsb-placeholder"}
    ]
    if len(hidden_items) != len(target_items):
        return
    # The first enrolled cohort is the temporary-note-group topology carrying
    # explicit continuation marks.  Other exact-rhythm DSB rows remain on the
    # legacy beam-group projection until their shared-grid behavior is audited.
    if not any("~" in item.event.raw for item in hidden_items + target_items):
        return
    hidden_durations = tuple(event_duration_fraction(item.event) for item in hidden_items)
    target_durations = tuple(event_duration_fraction(item.event) for item in target_items)
    if hidden_durations != target_durations:
        return
    for hidden_item, target_item in zip(hidden_items, target_items, strict=True):
        hidden_item.onset_slot = target_item.slot
        hidden_item.onset_aligned = True
        hidden_item.x = target_item.x
    hidden_barlines = [item for item in hidden_measure if item.event.kind == MusicTokenKind.BARLINE]
    target_barlines = [item for item in target_measure if item.event.kind == MusicTokenKind.BARLINE]
    for hidden_barline, target_barline in zip(hidden_barlines, target_barlines, strict=False):
        hidden_barline.onset_slot = target_barline.slot
        hidden_barline.onset_aligned = True
        hidden_barline.x = target_barline.x


def measure_aligned_hidden_dsb_events(
    construct: SemanticConstruct,
    hidden_block_events: list[MusicEvent],
    laid_out: list[LayoutEvent],
    *,
    page_index: int,
    voice: int,
    beat_unit: Fraction,
    split_events_into_measures: Callable[[list[MusicEvent]], list[list[MusicEvent]]],
    following_visible_measures: Callable[
        [SemanticConstruct, list[LayoutEvent]], list[list[LayoutEvent]]
    ],
    natural_hidden_measure_layout: Callable[..., list[LayoutEvent]],
    justify_hidden_measure: Callable[[list[LayoutEvent], float, float], None],
    target_slot_by_beat_bucket: Callable[..., dict[int, int]],
    duration_bucket: Callable[[Fraction, Fraction], int],
) -> list[LayoutEvent]:
    hidden_measures = split_events_into_measures(hidden_block_events)
    if not hidden_measures:
        return []
    target_measures = following_visible_measures(construct, laid_out)
    if len(target_measures) < len(hidden_measures):
        return []

    hidden_events: list[LayoutEvent] = []
    for hidden_measure, target_measure in zip(hidden_measures, target_measures, strict=False):
        first_target = target_measure[0]
        last_target = target_measure[-1]
        target_width = last_target.x - first_target.x
        if target_width <= 0:
            return []
        measure_items = natural_hidden_measure_layout(
            hidden_measure,
            first_target,
            page_index=page_index,
            voice=voice,
        )
        natural_width = measure_items[-1].x - measure_items[0].x
        if natural_width <= 0:
            return []
        justify_hidden_measure(measure_items, first_target.x, target_width)
        append_hidden_dsb_tail_barline_if_needed(
            measure_items,
            target_measure,
            page_index=page_index,
            voice=voice,
        )
        assign_hidden_dsb_stream_slots(
            measure_items,
            target_measure,
            beat_unit=beat_unit,
            target_slot_by_beat_bucket=target_slot_by_beat_bucket,
            duration_bucket=duration_bucket,
        )
        _snap_hidden_dsb_measure_to_target(measure_items, target_measure, beat_unit)
        hidden_events.extend(measure_items)
    return hidden_events


def _snap_hidden_dsb_measure_to_target(
    hidden_measure: list[LayoutEvent],
    target_measure: list[LayoutEvent],
    beat_unit: Fraction,
) -> None:
    """Snap measure-aligned DSB overlays to their assigned visible onsets."""

    # Beamed streams have meaningful intra-group cursor geometry; their
    # existing duration projection remains the safe fallback until a pinned
    # reference topology enrolls them.  Unbeamed groups expose one onset per
    # stream slot and can be translated as a whole.
    if any(
        item.event.kind != MusicTokenKind.BARLINE and item.event.duration_slashes
        for item in hidden_measure
    ):
        return

    target_by_slot = {
        item.slot: item
        for item in target_measure
        if item.event.kind != MusicTokenKind.BARLINE
    }
    target_barline = next(
        (item for item in target_measure if item.event.kind == MusicTokenKind.BARLINE),
        None,
    )
    for stream_group in hidden_dsb_stream_groups(hidden_measure, group_unit=beat_unit):
        group = list(stream_group.items)
        if not group:
            continue
        target = (
            target_by_slot.get(group[0].stream_slot)
            if group[0].stream_slot is not None
            else None
        )
        if target is not None:
            delta = target.x - group[0].x
            for grouped_item in group:
                grouped_item.x += delta
    for item in hidden_measure:
        if item.event.kind == MusicTokenKind.BARLINE and target_barline is not None:
            item.x = target_barline.x
