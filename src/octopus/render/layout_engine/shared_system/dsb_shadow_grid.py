"""Event-keyed union projection for complete one-measure DSB shadows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout_engine.grid.beat_grid import (
    GridEventKey,
    SharedGridProjection,
    SharedGridRow,
    project_shared_grid,
)

from ....parser.ast import MusicTokenKind
from .models import DsbShadowGridProjection

DSB_BOUNDARY_RESERVE = Fraction(20)
MIXED_CLOSE_CARRY = Fraction(25, 2)
HIDDEN_ACCIDENTAL_RELEASE = Fraction(5)
MIXED_PLACEHOLDER_AFTER_HIDDEN = Fraction(5)


@dataclass(frozen=True, slots=True)
class _MixedBlockSpec:
    owner: tuple[int, int]
    owner_row: list[LayoutEvent]
    hidden: tuple[LayoutEvent, ...]
    anchor_index: int
    anchor_ordinal: int
    close_ordinal: int
    hidden_bar_count: int
    ends_at_barline: bool


def build_complete_midrow_dsb_shadow_grid(
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
) -> DsbShadowGridProjection | None:
    """Build the complete visible-plus-shadow union when eligible."""
    if len(rows) < 2 or any(not row for row in rows):
        return None
    row_by_owner = {(row[0].voice, row[0].line): row for row in rows}
    if len(row_by_owner) != len(rows):
        return None
    barline_count = {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row)
        for row in rows
    }
    if len(barline_count) != 1 or min(barline_count, default=0) < 3:
        return None
    if any(item.event.grace_reservation for row in rows for item in row):
        return None
    hidden_groups: dict[tuple[int, int, tuple[str, ...]], list[LayoutEvent]] = defaultdict(list)
    for item in hidden_events:
        owner = (item.voice, item.line)
        block_ids = tuple(
            construct_id
            for construct_id in item.event.construct_ids
            if ":block:" in construct_id
        )
        if (
            owner in row_by_owner
            and item.block == "dsb-hidden"
            and item.event.index >= 0
            and block_ids
        ):
            hidden_groups[(*owner, block_ids)].append(item)
    if not hidden_groups:
        return None
    groups_by_owner: dict[tuple[int, int], list[list[LayoutEvent]]] = defaultdict(list)
    for (voice, line, _block_ids), items in hidden_groups.items():
        groups_by_owner[(voice, line)].append(
            sorted(items, key=lambda item: item.event.span.start.offset)
        )

    visible_grid_rows = tuple(
        SharedGridRow(row[0].voice, tuple(item.event for item in row), {})
        for row in rows
    )
    shadow_specs: list[
        tuple[SharedGridRow, tuple[int, int], tuple[LayoutEvent, ...]]
    ] = []
    anchor_ordinals: set[int] = set()
    close_ordinals: set[int] = set()
    next_shadow_voice = max(row.voice_index for row in visible_grid_rows) + 1
    final_barline_ordinal = next(iter(barline_count)) - 1
    for owner, owner_row in row_by_owner.items():
        owner_groups = sorted(
            groups_by_owner.get(owner, []),
            key=lambda items: items[0].event.span.start.offset,
        )
        anchors = [
            index
            for index, item in enumerate(owner_row)
            if item.event.kind == MusicTokenKind.BARLINE
            and "&dsb_a" in (item.event.code or "")
        ]
        if len(owner_groups) != len(anchors):
            return None
        for anchor_index, hidden_group in zip(anchors, owner_groups, strict=True):
            hidden_barlines = [
                item
                for item in hidden_group
                if item.event.kind == MusicTokenKind.BARLINE
            ]
            if len(hidden_barlines) != 1 or hidden_group[-1] is not hidden_barlines[0]:
                return None
            anchor_ordinal = (
                sum(
                    item.event.kind == MusicTokenKind.BARLINE
                    for item in owner_row[: anchor_index + 1]
                )
                - 1
            )
            close_ordinal = anchor_ordinal + 1
            if close_ordinal >= final_barline_ordinal:
                return None
            anchor = owner_row[anchor_index]
            if anchor_index > 0 or not (anchor.event.code or "").startswith("|n"):
                anchor_ordinals.add(anchor_ordinal)
            close_ordinals.add(close_ordinal)
            shadow_events = (
                *(item.event for item in owner_row[: anchor_index + 1]),
                *(item.event for item in hidden_group),
            )
            shadow_specs.append(
                (
                    SharedGridRow(next_shadow_voice, shadow_events, {}),
                    owner,
                    tuple(hidden_group),
                )
            )
            next_shadow_voice += 1
    projection = project_shared_grid(
        (*visible_grid_rows, *(spec[0] for spec in shadow_specs))
    )
    if not projection.barline_x_offsets:
        return None

    visible_event_adjustments: dict[GridEventKey, Fraction] = {}
    for grid_row, row in zip(visible_grid_rows, rows, strict=True):
        barline_ordinal = -1
        for item in row:
            is_barline = item.event.kind == MusicTokenKind.BARLINE
            if is_barline:
                barline_ordinal += 1
                continue
            key = GridEventKey.for_event(item.event, grid_row.voice_index)
            visible_event_adjustments[key] = _boundary_adjustment(
                barline_ordinal,
                after_current_barline=True,
                anchor_ordinals=anchor_ordinals,
                close_ordinals=close_ordinals,
            )
    barline_adjustments = tuple(
        _boundary_adjustment(
            ordinal,
            after_current_barline=False,
            anchor_ordinals=anchor_ordinals,
            close_ordinals=close_ordinals,
        )
        for ordinal in range(len(projection.barline_x_offsets))
    )
    visible_accidental_offsets = _visible_accidental_offsets(visible_grid_rows, projection)
    hidden_event_offsets = _hidden_offsets(
        shadow_specs,
        projection=projection,
        anchor_ordinals=anchor_ordinals,
        close_ordinals=close_ordinals,
        visible_accidental_offsets=visible_accidental_offsets,
    )
    total_reserve = DSB_BOUNDARY_RESERVE * (
        len(anchor_ordinals) + len(close_ordinals)
    )
    return DsbShadowGridProjection(
        projection=projection,
        visible_event_adjustments=MappingProxyType(visible_event_adjustments),
        barline_adjustments=barline_adjustments,
        hidden_event_offsets=MappingProxyType(hidden_event_offsets),
        total_reserve=total_reserve,
    )


def build_coherent_mixed_dsb_shadow_grid(
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
) -> DsbShadowGridProjection | None:
    """Build the mixed union when unequal blocks share one close boundary."""
    topology = _mixed_block_topology(rows, hidden_events)
    if topology is None:
        return None
    visible_rows, block_specs, final_barline_ordinal = topology
    common_close = block_specs[0].close_ordinal
    anchor_ordinals = {
        spec.anchor_ordinal
        for spec in block_specs
        if spec.anchor_index > 0
        or not (spec.owner_row[spec.anchor_index].event.code or "").startswith("|n")
    }
    if not anchor_ordinals:
        return None
    next_shadow_voice = max(row.voice_index for row in visible_rows) + 1
    shadow_specs: list[tuple[SharedGridRow, _MixedBlockSpec]] = []
    for spec in block_specs:
        shadow = SharedGridRow(
            next_shadow_voice,
            (
                *(item.event for item in spec.owner_row[: spec.anchor_index + 1]),
                *(item.event for item in spec.hidden),
            ),
            {},
        )
        shadow_specs.append((shadow, spec))
        next_shadow_voice += 1

    projection = project_shared_grid(
        (*visible_rows, *(shadow for shadow, _spec in shadow_specs))
    )
    if not projection.barline_x_offsets:
        return None
    def adjustment(barline_ordinal: int, *, after_current_barline: bool) -> Fraction:
        return _mixed_boundary_adjustment(
            barline_ordinal,
            after_current_barline=after_current_barline,
            anchor_ordinals=anchor_ordinals,
            common_close=common_close,
            final_barline_ordinal=final_barline_ordinal,
        )

    visible_event_adjustments: dict[GridEventKey, Fraction] = {}
    for grid_row, row in zip(visible_rows, rows, strict=True):
        barline_ordinal = -1
        for item in row:
            if item.event.kind == MusicTokenKind.BARLINE:
                barline_ordinal += 1
                continue
            key = GridEventKey.for_event(item.event, grid_row.voice_index)
            visible_event_adjustments[key] = adjustment(
                barline_ordinal,
                after_current_barline=True,
            )
    barline_adjustments = tuple(
        adjustment(ordinal, after_current_barline=False)
        for ordinal in range(len(projection.barline_x_offsets))
    )
    hidden_event_offsets, hidden_event_right_pins = _mixed_hidden_offsets(
        shadow_specs,
        projection=projection,
        adjustment=adjustment,
        visible_accidental_offsets=_visible_accidental_offsets(visible_rows, projection),
        final_barline_ordinal=final_barline_ordinal,
    )
    visible_event_offsets = _mixed_placeholder_offsets(
        rows,
        block_specs,
        hidden_event_offsets,
    )
    if visible_event_offsets is None:
        return None
    total_reserve = (
        DSB_BOUNDARY_RESERVE * len(anchor_ordinals)
        if common_close == final_barline_ordinal
        else MIXED_CLOSE_CARRY
    )
    return DsbShadowGridProjection(
        projection=projection,
        visible_event_adjustments=MappingProxyType(visible_event_adjustments),
        barline_adjustments=barline_adjustments,
        hidden_event_offsets=MappingProxyType(hidden_event_offsets),
        total_reserve=total_reserve,
        hidden_event_right_pins=frozenset(hidden_event_right_pins),
        visible_event_offsets=MappingProxyType(visible_event_offsets),
    )


def _mixed_block_topology(
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
) -> tuple[tuple[SharedGridRow, ...], tuple[_MixedBlockSpec, ...], int] | None:
    if len(rows) < 2 or any(not row for row in rows):
        return None
    row_by_owner = {(row[0].voice, row[0].line): row for row in rows}
    if len(row_by_owner) != len(rows):
        return None
    barline_counts = {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row)
        for row in rows
    }
    if len(barline_counts) != 1 or min(barline_counts, default=0) < 3:
        return None
    if any(item.event.grace_reservation for row in rows for item in row):
        return None

    hidden_groups: dict[tuple[int, int, tuple[str, ...]], list[LayoutEvent]] = defaultdict(list)
    for item in hidden_events:
        owner = (item.voice, item.line)
        block_ids = tuple(
            construct_id
            for construct_id in item.event.construct_ids
            if ":block:" in construct_id
        )
        if (
            owner in row_by_owner
            and item.block == "dsb-hidden"
            and item.event.index >= 0
            and block_ids
        ):
            hidden_groups[(*owner, block_ids)].append(item)
    groups_by_owner: dict[tuple[int, int], list[tuple[LayoutEvent, ...]]] = defaultdict(list)
    for (voice, line, _block_ids), items in hidden_groups.items():
        groups_by_owner[(voice, line)].append(
            tuple(sorted(items, key=lambda item: item.event.span.start.offset))
        )

    final_barline_ordinal = next(iter(barline_counts)) - 1
    specs: list[_MixedBlockSpec] = []
    for owner, owner_row in row_by_owner.items():
        owner_groups = sorted(
            groups_by_owner.get(owner, []),
            key=lambda items: items[0].event.span.start.offset,
        )
        anchors = [
            index
            for index, item in enumerate(owner_row)
            if item.event.kind == MusicTokenKind.BARLINE
            and "&dsb_a" in (item.event.code or "")
        ]
        if len(owner_groups) != len(anchors):
            return None
        for anchor_index, hidden_group in zip(anchors, owner_groups, strict=True):
            hidden_bar_count = sum(
                item.event.kind == MusicTokenKind.BARLINE for item in hidden_group
            )
            if hidden_bar_count == 0:
                return None
            anchor_ordinal = (
                sum(
                    item.event.kind == MusicTokenKind.BARLINE
                    for item in owner_row[: anchor_index + 1]
                )
                - 1
            )
            ends_at_barline = hidden_group[-1].event.kind == MusicTokenKind.BARLINE
            close_ordinal = (
                anchor_ordinal + hidden_bar_count + (0 if ends_at_barline else 1)
            )
            if close_ordinal > final_barline_ordinal:
                return None
            specs.append(
                _MixedBlockSpec(
                    owner=owner,
                    owner_row=owner_row,
                    hidden=hidden_group,
                    anchor_index=anchor_index,
                    anchor_ordinal=anchor_ordinal,
                    close_ordinal=close_ordinal,
                    hidden_bar_count=hidden_bar_count,
                    ends_at_barline=ends_at_barline,
                )
            )

    hidden_bar_counts = {spec.hidden_bar_count for spec in specs}
    if (
        len(specs) < 2
        or len(hidden_bar_counts) < 2
        or max(hidden_bar_counts, default=0) < 2
        or len({spec.close_ordinal for spec in specs}) != 1
    ):
        return None
    visible_rows = tuple(
        SharedGridRow(row[0].voice, tuple(item.event for item in row), {})
        for row in rows
    )
    return visible_rows, tuple(specs), final_barline_ordinal


def _mixed_hidden_offsets(
    shadow_specs: list[tuple[SharedGridRow, _MixedBlockSpec]],
    *,
    projection: SharedGridProjection,
    adjustment: Callable[..., Fraction],
    visible_accidental_offsets: frozenset[Fraction],
    final_barline_ordinal: int,
) -> tuple[dict[tuple[int, int, int], Fraction], set[tuple[int, int, int]]]:
    result: dict[tuple[int, int, int], Fraction] = {}
    right_pins: set[tuple[int, int, int]] = set()
    for shadow, spec in shadow_specs:
        barline_ordinal = -1
        hidden_indices = {item.event.index for item in spec.hidden}
        hidden_by_index = {item.event.index: item for item in spec.hidden}
        previous_stream_slot: int | None = None
        hidden_accidental_release = False
        for event in shadow.events:
            key = (spec.owner[0], spec.owner[1], event.index)
            if event.kind == MusicTokenKind.BARLINE:
                barline_ordinal += 1
                if event.index not in hidden_indices:
                    previous_stream_slot = None
                    hidden_accidental_release = False
                    continue
                if barline_ordinal == final_barline_ordinal:
                    right_pins.add(key)
                else:
                    result[key] = projection.barline_x_offsets[barline_ordinal] + adjustment(
                        barline_ordinal,
                        after_current_barline=False,
                    )
                previous_stream_slot = None
                hidden_accidental_release = False
                continue
            if event.index not in hidden_indices:
                continue
            hidden_item = hidden_by_index[event.index]
            event_key = GridEventKey.for_event(event, shadow.voice_index)
            natural_offset = projection.event_x_offsets[event_key]
            offset = natural_offset + adjustment(
                barline_ordinal,
                after_current_barline=True,
            )
            hidden_accidental_release = event.accidental is None and (
                natural_offset in visible_accidental_offsets
                or hidden_accidental_release
                and hidden_item.stream_slot == previous_stream_slot
            )
            offset -= HIDDEN_ACCIDENTAL_RELEASE if hidden_accidental_release else 0
            if event.kind == MusicTokenKind.EXTENSION:
                hidden_accidental_release = False
            result[key] = offset
            previous_stream_slot = hidden_item.stream_slot
    return result, right_pins


def _mixed_placeholder_offsets(
    rows: list[list[LayoutEvent]],
    block_specs: tuple[_MixedBlockSpec, ...],
    hidden_event_offsets: dict[tuple[int, int, int], Fraction],
) -> dict[GridEventKey, Fraction] | None:
    result: dict[GridEventKey, Fraction] = {}
    for spec in block_specs:
        placeholders = [
            candidate
            for row in rows
            if row is spec.owner_row
            for candidate in row
            if candidate.block == "dsb-placeholder"
        ]
        if not placeholders:
            continue
        if len(placeholders) > 1:
            return None
        final_hidden_nonbar = next(
            item
            for item in reversed(spec.hidden)
            if item.event.kind != MusicTokenKind.BARLINE
        )
        hidden_offset = hidden_event_offsets.get(
            (spec.owner[0], spec.owner[1], final_hidden_nonbar.event.index)
        )
        if hidden_offset is None:
            return None
        for placeholder in placeholders:
            result[GridEventKey.for_event(placeholder.event, placeholder.voice)] = (
                hidden_offset + MIXED_PLACEHOLDER_AFTER_HIDDEN
            )
    return result


def _mixed_boundary_adjustment(
    barline_ordinal: int,
    *,
    after_current_barline: bool,
    anchor_ordinals: set[int],
    common_close: int,
    final_barline_ordinal: int,
) -> Fraction:
    if common_close < final_barline_ordinal and barline_ordinal >= common_close:
        return MIXED_CLOSE_CARRY
    anchors = sum(
        anchor < barline_ordinal
        or after_current_barline and anchor == barline_ordinal
        for anchor in anchor_ordinals
    )
    return DSB_BOUNDARY_RESERVE * anchors


def _visible_accidental_offsets(
    rows: tuple[SharedGridRow, ...], projection: SharedGridProjection
) -> frozenset[Fraction]:
    return frozenset(
        projection.event_x_offsets[GridEventKey.for_event(event, row.voice_index)]
        for row in rows
        for event in row.events
        if event.accidental is not None
    )


def _hidden_offsets(
    shadow_specs: list[
        tuple[SharedGridRow, tuple[int, int], tuple[LayoutEvent, ...]]
    ],
    *,
    projection: SharedGridProjection,
    anchor_ordinals: set[int],
    close_ordinals: set[int],
    visible_accidental_offsets: frozenset[Fraction] = frozenset(),
) -> dict[tuple[int, int, int], Fraction]:
    result: dict[tuple[int, int, int], Fraction] = {}
    for shadow, (voice, line), items in shadow_specs:
        barline_ordinal = -1
        hidden_indices = {item.event.index for item in items}
        hidden_by_index = {item.event.index: item for item in items}
        first_hidden_event = items[0].event
        previous_stream_slot: int | None = None
        hidden_accidental_release = False
        for event_index, event in enumerate(shadow.events):
            if event.kind == MusicTokenKind.BARLINE:
                barline_ordinal += 1
                if event.index in hidden_indices:
                    result[(voice, line, event.index)] = (
                        projection.barline_x_offsets[barline_ordinal]
                        + _boundary_adjustment(
                            barline_ordinal,
                            after_current_barline=False,
                            anchor_ordinals=anchor_ordinals,
                            close_ordinals=close_ordinals,
                        )
                    )
                previous_stream_slot = None
                hidden_accidental_release = False
                continue
            if event.index not in hidden_indices:
                continue
            hidden_item = hidden_by_index[event.index]
            key = GridEventKey.for_event(event, shadow.voice_index)
            adjustment = _boundary_adjustment(
                barline_ordinal,
                after_current_barline=True,
                anchor_ordinals=anchor_ordinals,
                close_ordinals=close_ordinals,
            )
            previous = shadow.events[event_index - 1] if event_index > 0 else None
            if (
                event is first_hidden_event
                and previous is not None
                and previous.kind == MusicTokenKind.BARLINE
                and (previous.code or "").startswith("|n")
            ):
                result[(voice, line, event.index)] = (
                    projection.barline_x_offsets[barline_ordinal]
                    + _boundary_adjustment(
                        barline_ordinal,
                        after_current_barline=False,
                        anchor_ordinals=anchor_ordinals,
                        close_ordinals=close_ordinals,
                    )
                )
            else:
                natural_offset = projection.event_x_offsets[key]
                offset = natural_offset + adjustment
                hidden_accidental_release = event.accidental is None and (
                    natural_offset in visible_accidental_offsets
                    or hidden_accidental_release
                    and hidden_item.stream_slot == previous_stream_slot
                )
                offset -= HIDDEN_ACCIDENTAL_RELEASE if hidden_accidental_release else 0
                if event.kind == MusicTokenKind.EXTENSION:
                    hidden_accidental_release = False
                result[(voice, line, event.index)] = offset
            previous_stream_slot = hidden_item.stream_slot
    return result


def _boundary_adjustment(
    barline_ordinal: int,
    *,
    after_current_barline: bool,
    anchor_ordinals: set[int],
    close_ordinals: set[int],
) -> Fraction:
    anchors = sum(
        anchor < barline_ordinal
        or after_current_barline and anchor == barline_ordinal
        for anchor in anchor_ordinals
    )
    closes = sum(close <= barline_ordinal for close in close_ordinals)
    return DSB_BOUNDARY_RESERVE * (anchors + closes)


__all__ = [
    "DSB_BOUNDARY_RESERVE",
    "MIXED_CLOSE_CARRY",
    "HIDDEN_ACCIDENTAL_RELEASE",
    "MIXED_PLACEHOLDER_AFTER_HIDDEN",
    "build_coherent_mixed_dsb_shadow_grid",
    "build_complete_midrow_dsb_shadow_grid",
]
