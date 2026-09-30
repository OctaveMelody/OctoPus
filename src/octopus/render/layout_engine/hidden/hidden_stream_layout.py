"""Hidden BZ/DSB stream layout coordination."""

from __future__ import annotations

from fractions import Fraction
from math import fsum

from octopus.normalization.types import MusicEvent, SemanticConstruct
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import LayoutEvent, PageMetrics
from octopus.render.core.layout_widths import NOTE_WIDTH, event_duration_weight
from octopus.render.layout_engine.constructs import first_barline_after as _first_barline_after
from octopus.render.layout_engine.intrinsic.builder import build_legacy_intrinsic_profile
from octopus.render.layout_engine.rows.row_projection import (
    justify_measure_by_duration as _justify_measure_by_duration,
)
from octopus.render.layout_engine.rows.row_projection import (
    split_row_into_measures as _split_row_into_measures,
)
from octopus.render.layout_engine.spacing.system_spacing import DSB_INCOMING_CLEARANCE
from octopus.render.layout_engine.streams import (
    duration_bucket as _duration_bucket,
)
from octopus.render.layout_engine.streams import (
    split_events_into_measures as _split_events_into_measures,
)
from octopus.render.layout_engine.visibility import is_visible_event as _is_visible_event

from .hidden_streams import (
    event_duration_fraction as _event_duration_fraction,
)
from .hidden_streams import (
    measure_aligned_hidden_dsb_events as _measure_aligned_hidden_dsb_events_impl,
)
from .hidden_streams import (
    target_slot_at_or_after_onset as _target_slot_at_or_after_onset,
)
from .hidden_streams import (
    target_slots_by_onset as _target_slots_by_onset,
)


def hidden_dsb_events_for_layout(
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
    laid_out: list[LayoutEvent],
    *,
    page_index: int,
    voice: int,
    beat_unit: Fraction,
    metrics: PageMetrics,
) -> list[LayoutEvent]:
    source_by_index = {event.index: event for event in events}
    visible_by_index = {item.event.index: item for item in laid_out}
    hidden_events: list[LayoutEvent] = []
    for construct in constructs:
        if construct.kind != "block" or construct.value not in {None, "bz", "dsb"}:
            continue
        hidden_block_events = [
            event
            for event_index in construct.event_indices
            if (event := source_by_index.get(event_index)) is not None
            and event.index not in visible_by_index
            and _is_visible_event(event)
        ]
        construct_events = [
            event for event in hidden_block_events if event.kind != MusicTokenKind.BARLINE
        ]
        if not construct_events:
            continue

        if construct.value == "bz":
            tail = _first_barline_after(construct.end_event_index, laid_out)
            placement_events = [
                item
                for item in laid_out
                if item.event.span.start.line == construct.source_span.end.line
                and item.event.span.start.offset >= construct.source_span.end.offset
                and (tail is None or item.x < tail.x)
                and item.event.kind != MusicTokenKind.BARLINE
            ]
            bz_events: list[LayoutEvent] = []
            for block_index, (event, placement) in enumerate(
                zip(construct_events, placement_events, strict=False),
                start=1,
            ):
                bz_events.append(
                    LayoutEvent(
                        event=event,
                        x=placement.x,
                        y=placement.y - 40.0,
                        page_index=page_index,
                        voice=voice,
                        line=placement.line,
                        slot=placement.slot,
                        block="bz-hidden",
                        block_index=block_index,
                    )
            )
            if tail is not None:
                hidden_barline = next(
                    (
                        event
                        for event in hidden_block_events
                        if event.kind == MusicTokenKind.BARLINE
                    ),
                    None,
                )
                if hidden_barline is not None:
                    bz_events.append(
                        LayoutEvent(
                            event=hidden_barline,
                            x=tail.x,
                            y=tail.y - 40.0,
                            page_index=page_index,
                            voice=voice,
                            line=tail.line,
                            slot=tail.slot,
                            block="bz-hidden",
                            block_index=len(construct_events) + 1,
                        )
                    )
            _assign_hidden_bz_stream_slots(
                bz_events,
                [*placement_events, *([tail] if tail is not None else [])],
            )
            hidden_events.extend(bz_events)
            continue

        measure_aligned_events = _measure_aligned_hidden_dsb_events(
            construct,
            hidden_block_events,
            laid_out,
            page_index=page_index,
            voice=voice,
            beat_unit=beat_unit,
            metrics=metrics,
        )
        if measure_aligned_events:
            hidden_events.extend(measure_aligned_events)
            continue

        anchor = _previous_visible_event(construct.start_event_index, construct, laid_out)
        tail = _first_barline_after(construct.end_event_index, laid_out)
        if tail is None:
            tail = _synthetic_tail_after_construct(construct, laid_out)
        if anchor is None or tail is None or tail.x <= anchor.x:
            continue

        hidden_weights = [
            event_duration_weight(
                LayoutEvent(
                    event=event,
                    x=0.0,
                    y=anchor.y,
                    page_index=page_index,
                    voice=voice,
                    line=anchor.line,
                    slot=0,
                )
            )
            for event in construct_events
        ]
        placement_weights = [event_duration_weight(anchor), *hidden_weights[:-1]]
        total_weight = sum(placement_weights) + hidden_weights[-1]
        if total_weight <= 0:
            continue

        x = anchor.x
        unit = (tail.x - anchor.x) / total_weight
        for event, weight in zip(construct_events, placement_weights, strict=True):
            x += weight * unit
            hidden_events.append(
                LayoutEvent(
                    event=event,
                    x=x,
                    y=anchor.y - 28.0,
                    page_index=page_index,
                    voice=voice,
                    line=anchor.line,
                    slot=anchor.slot,
                    block="dsb-hidden",
                )
            )
    return hidden_events


def lower_aligned_visible_dsb_targets(
    events: tuple[MusicEvent, ...],
    constructs: tuple[SemanticConstruct, ...],
    laid_out: list[LayoutEvent],
    generated_tails: list[LayoutEvent],
) -> None:
    """Lower visible measures paired with an already-positioned upper DSB stream."""

    source_by_index = {event.index: event for event in events}
    shifted_items: set[int] = set()
    for construct in constructs:
        if construct.kind != "block" or construct.value not in {None, "dsb"}:
            continue
        hidden_block_events = [
            event
            for event_index in construct.event_indices
            if (event := source_by_index.get(event_index)) is not None
            and _is_visible_event(event)
        ]
        if not any(
            event.kind != MusicTokenKind.BARLINE for event in hidden_block_events
        ):
            continue
        hidden_measures = _split_events_into_measures(hidden_block_events)
        target_measures = _following_visible_measures_after_construct(construct, laid_out)
        if len(target_measures) < len(hidden_measures):
            continue
        for hidden_measure, target_measure in zip(
            hidden_measures,
            target_measures,
            strict=False,
        ):
            for item in target_measure:
                identity = id(item)
                if identity in shifted_items:
                    continue
                if (
                    item.event.kind == MusicTokenKind.BARLINE
                    and construct.value == "dsb"
                    and (
                        len(hidden_measures) == 1
                        or hidden_measure[-1].kind != MusicTokenKind.BARLINE
                    )
                ):
                    continue
                item.y += DSB_INCOMING_CLEARANCE
                shifted_items.add(identity)
        if hidden_measures[-1][-1].kind != MusicTokenKind.BARLINE:
            for item in generated_tails:
                identity = id(item)
                if (
                    identity in shifted_items
                    or item.block not in {"dsb-placeholder", "dsb-tail"}
                    or item.event.index >= 0
                    or item.event.span.start.line != construct.source_span.end.line
                ):
                    continue
                item.y += DSB_INCOMING_CLEARANCE
                shifted_items.add(identity)


def _measure_aligned_hidden_dsb_events(
    construct: SemanticConstruct,
    hidden_block_events: list[MusicEvent],
    laid_out: list[LayoutEvent],
    *,
    page_index: int,
    voice: int,
    beat_unit: Fraction,
    metrics: PageMetrics,
) -> list[LayoutEvent]:
    def justify_hidden_measure(
        items: list[LayoutEvent], left: float, target_width: float
    ) -> None:
        _justify_hidden_measure(
            items,
            left,
            target_width,
            metrics=metrics,
        )

    return _measure_aligned_hidden_dsb_events_impl(
        construct,
        hidden_block_events,
        laid_out,
        page_index=page_index,
        voice=voice,
        beat_unit=beat_unit,
        split_events_into_measures=_split_events_into_measures,
        following_visible_measures=_following_visible_measures_after_construct,
        natural_hidden_measure_layout=_natural_hidden_measure_layout,
        justify_hidden_measure=justify_hidden_measure,
        target_slot_by_beat_bucket=_target_slot_by_beat_bucket,
        duration_bucket=_duration_bucket,
    )


def _justify_hidden_measure(
    items: list[LayoutEvent],
    left: float,
    target_width: float,
    *,
    metrics: PageMetrics,
) -> None:
    """Project a hidden measure, excluding a suppressed leading sentinel."""

    natural_width = items[-1].x - items[0].x
    if natural_width <= 0:
        return
    if _has_suppressed_leading_sentinel(items):
        profile = build_legacy_intrinsic_profile(
            items,
            metrics=metrics,
            left=left,
            lyric_text_by_event={},
        )
        visible_intervals = profile.interval_widths[1:]
        denominator = fsum(
            (
                *visible_intervals,
                profile.terminal_width,
                profile.final_bar_width,
                profile.denominator_adjustment,
            )
        )
        if len(visible_intervals) == len(items) - 3 and denominator > 0:
            scale = (target_width + 14.0) / denominator
            items[0].x = left
            items[1].x = left
            cursor = left
            for item, width in zip(items[2:-1], visible_intervals, strict=True):
                cursor += width * scale
                item.x = cursor
            items[-1].x = left + target_width
            return
    _justify_measure_by_duration(items, left, target_width / natural_width)


def _has_suppressed_leading_sentinel(items: list[LayoutEvent]) -> bool:
    if len(items) < 4:
        return False
    first, second = items[:2]
    return (
        first.event.kind == MusicTokenKind.HIDDEN_REST
        and first.event.code.startswith("8")
        and second.event.kind == MusicTokenKind.NOTE
        and (
            any(
                ":slur:" in role and role.endswith(":start")
                for role in (*first.event.construct_roles, *second.event.construct_roles)
            )
            or "(" in second.event.code
        )
    )


def _assign_hidden_bz_stream_slots(
    hidden_events: list[LayoutEvent],
    target_measure: list[LayoutEvent],
) -> None:
    # Notes sharing one beat bucket form a single stream group: the whole
    # group flushes ahead of the first visible event at or after its onset.
    # Per-note bucket lookup instead interleaved a beamed pair with its
    # visible twins (corpus census 2026-08-28: Azalea's second bz beam pair
    # must sit before the slot-13 extension, not between it and the next
    # placeholder).
    target_slots = _target_slots_by_onset(target_measure)
    target_barline = next(
        (item for item in target_measure if item.event.kind == MusicTokenKind.BARLINE),
        None,
    )
    onset = Fraction(0, 1)
    group: list[LayoutEvent] = []
    group_onset = Fraction(0, 1)
    group_bucket: int | None = None

    def flush_group() -> None:
        nonlocal group, group_bucket
        if not group:
            return
        slot = _target_slot_at_or_after_onset(
            target_slots, group_onset, default=group[0].slot
        )
        for item in group:
            item.stream_slot = slot
        group = []
        group_bucket = None

    for item in hidden_events:
        if item.event.kind == MusicTokenKind.BARLINE:
            flush_group()
            item.stream_slot = target_barline.slot if target_barline is not None else item.slot
            onset += _event_duration_fraction(item.event)
            continue
        bucket = _duration_bucket(onset, Fraction(1, 1))
        if group_bucket is not None and bucket != group_bucket:
            flush_group()
        if group_bucket is None:
            group_onset = onset
            group_bucket = bucket
        group.append(item)
        onset += _event_duration_fraction(item.event)
    flush_group()


def _target_slot_by_beat_bucket(
    target_measure: list[LayoutEvent],
    *,
    beat_unit: Fraction,
    include_placeholders: bool = True,
) -> dict[int, int]:
    result: dict[int, int] = {}
    onset = Fraction(0, 1)
    for item in target_measure:
        if item.event.kind == MusicTokenKind.BARLINE:
            onset += _event_duration_fraction(item.event)
            continue
        if not include_placeholders and item.block in {"bz-placeholder", "dsb-placeholder"}:
            onset += _event_duration_fraction(item.event)
            continue
        bucket = _duration_bucket(onset, beat_unit)
        result.setdefault(bucket, item.slot)
        onset += _event_duration_fraction(item.event)
    return result


def _following_visible_measures_after_construct(
    construct: SemanticConstruct,
    laid_out: list[LayoutEvent],
) -> list[list[LayoutEvent]]:
    if construct.end_event_index is None:
        return []
    following = [
        item
        for item in laid_out
        if (
            item.event.index > construct.end_event_index
            or (item.event.index < 0 and item.block in {"dsb-placeholder", "dsb-tail"})
            or (item.event.index < 0 and item.event.kind == MusicTokenKind.BARLINE)
        )
        and item.event.span.start.line == construct.source_span.end.line
        and item.event.span.start.offset >= construct.source_span.end.offset
    ]
    return [measure for measure in _split_row_into_measures(following) if measure]


def _natural_hidden_measure_layout(
    events: list[MusicEvent],
    target: LayoutEvent,
    *,
    page_index: int,
    voice: int,
) -> list[LayoutEvent]:
    items: list[LayoutEvent] = []
    x = 0.0
    for event in events:
        items.append(
            LayoutEvent(
                event=event,
                x=x,
                y=target.y - 28.0,
                page_index=page_index,
                voice=voice,
                line=target.line,
                slot=target.slot,
                block="dsb-hidden",
            )
        )
        x += event_duration_weight(items[-1])
    return items


def _synthetic_tail_after_construct(
    construct: SemanticConstruct,
    laid_out: list[LayoutEvent],
) -> LayoutEvent | None:
    if construct.end_event_index is None:
        return None
    placement_events = [
        item
        for item in laid_out
        if item.event.index > construct.end_event_index
        and item.event.span.start.line == construct.source_span.end.line
        and item.event.span.start.offset >= construct.source_span.end.offset
        and item.event.kind != MusicTokenKind.BARLINE
    ]
    if not placement_events:
        return None
    last = placement_events[-1]
    return LayoutEvent(
        event=last.event,
        x=last.x + NOTE_WIDTH,
        y=last.y,
        page_index=last.page_index,
        voice=last.voice,
        line=last.line,
        slot=last.slot,
    )


def _tail_layout_event(
    *,
    event: MusicEvent,
    x: float,
    y: float,
    page_index: int,
    voice: int,
    line: int,
    slot: int,
    block: str | None,
) -> LayoutEvent:
    return LayoutEvent(
        event=event,
        x=x,
        y=y,
        page_index=page_index,
        voice=voice,
        line=line,
        slot=slot,
        block=block,
    )


def _previous_visible_event(
    event_index: int | None,
    construct: SemanticConstruct,
    laid_out: list[LayoutEvent],
) -> LayoutEvent | None:
    if event_index is None:
        return None
    candidates = [
        item
        for item in laid_out
        if item.event.index >= 0
        and item.event.index < event_index
        and item.event.span.start.line == construct.source_span.start.line
        and item.event.span.start.offset < construct.source_span.start.offset
    ]
    return candidates[-1] if candidates else None


__all__ = [
    "_tail_layout_event",
    "hidden_dsb_events_for_layout",
    "lower_aligned_visible_dsb_targets",
]
