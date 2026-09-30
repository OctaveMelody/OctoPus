"""Hidden projection adjustments for the overlapping-DSB topology."""

from __future__ import annotations

from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout_engine.hidden.hidden_streams import hidden_dsb_stream_groups

from ....parser.ast import MusicTokenKind
from ..streams import dsb_stream_beat_unit
from .overlapping_dsb_widths import overlapping_dsb_topology
from .projection import SharedProjectionPlan

_INTRINSIC_ACCIDENTAL_RESERVE = 3.6


def apply_overlapping_dsb_hidden_accidental_release(
    items: list[LayoutEvent],
    *,
    plan: SharedProjectionPlan,
    visible_row: list[LayoutEvent],
) -> None:
    """Release a visible accidental reserve from an overlapping hidden group."""

    topology = overlapping_dsb_topology(plan.request.rows)
    if topology is None or not items:
        return
    owner = (items[0].voice, items[0].line)
    long_owner = plan.request.rows[topology.long_owner_index]
    if owner != (long_owner[0].voice, long_owner[0].line):
        return

    target_accidentals = {
        item.slot: item.event.accidental is not None
        for item in visible_row
        if item.event.kind != MusicTokenKind.BARLINE
    }
    group_unit = dsb_stream_beat_unit(plan.request.metrics.time_sig)
    for measure in _measure_groups(items):
        for stream_group in hidden_dsb_stream_groups(measure, group_unit=group_unit):
            group = list(stream_group.items)
            if not group or group[0].stream_slot is None:
                continue
            shared_owns_reserve = target_accidentals.get(group[0].stream_slot, False)
            hidden_owns_reserve = any(
                item.event.accidental is not None for item in group
            )
            ownership_delta = int(hidden_owns_reserve) - int(shared_owns_reserve)
            if ownership_delta == 0:
                continue
            if ownership_delta < 0 and plan.dsb_union_grid:
                # The grid-owned projection already moved a hidden group back
                # one reserve when its visible slot owns the accidental.
                continue
            delta = ownership_delta * _INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
            for item in group:
                item.x += delta
                item.style_x = item.x


def _measure_groups(items: list[LayoutEvent]) -> list[list[LayoutEvent]]:
    groups: list[list[LayoutEvent]] = []
    current: list[LayoutEvent] = []
    for item in items:
        current.append(item)
        if item.event.kind == MusicTokenKind.BARLINE:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


__all__ = ["apply_overlapping_dsb_hidden_accidental_release"]
