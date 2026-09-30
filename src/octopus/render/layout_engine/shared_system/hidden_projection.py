"""Project hidden DSB rows against the final visible shared-system grid."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction, hidden_dsb_stream_groups
from ..intrinsic.builder import build_legacy_intrinsic_profile
from ..streams import dsb_stream_beat_unit, first_meter
from .dsb_gap_reserves import two_owner_trailing_dsb_topology
from .overlapping_dsb_hidden import apply_overlapping_dsb_hidden_accidental_release
from .projection import SharedProjectionPlan

_INTRINSIC_ACCIDENTAL_RESERVE = 3.6
_NATURAL_LEADING_GAP = 25.2


def reproject_hidden_dsb_events(
    hidden_events: Iterable[LayoutEvent],
    plans: Mapping[tuple[int, int], SharedProjectionPlan],
) -> None:
    """Reproject DSB-only X coordinates after all visible shared passes.

    Hidden DSB rows use a legacy intrinsic, lyric-free profile; groups anchor
    on their assigned visible stream slots (first group of every measure, all
    groups in un-beamed measures, beamed groups in mixed ones) and later
    un-beamed groups continue from the intrinsic cursor.  Operates only on DSB
    blocks; BZ placement and Y coordinates stay untouched.
    """
    grouped: dict[tuple[tuple[str, ...], int, int], list[LayoutEvent]] = defaultdict(list)
    for item in hidden_events:
        if item.block not in {"dsb-hidden", "dsb-hidden-tail"}:
            continue
        plan_key = (item.voice, item.line)
        if plan_key not in plans:
            continue
        grouped[(_block_identity(item), item.voice, item.line)].append(item)
    for (construct_id, voice, line), items in grouped.items():
        del construct_id  # The identity is part of the grouping key by design.
        plan = plans[(voice, line)]
        visible_row = _visible_row(plan, voice=voice, line=line)
        if visible_row is None:
            continue
        if _project_dsb_shadow_grid(items, plan=plan):
            continue
        if (
            plan.request.policy.uses_four_beat_refinement_grid
            and not plan.dsb_union_grid
        ):
            # This refinement owns the visible row's terminal spacing, but its
            # DSB overlay stays a legacy intrinsic stream in the reference
            # output; snapping it to visible slots collapses the overlay onto
            # the wrong columns (notably the second As-Wished page).  The
            # union note-group grid owns those overlays instead.
            continue
        if _project_exact_onset_cohort(items, plan=plan, visible_row=visible_row):
            continue
        if plan.grid_owned:
            _project_grid_owned_hidden(items, plan=plan, visible_row=visible_row)
            continue
        target_by_slot = {
            item.slot: item for item in visible_row
            if item.event.kind != MusicTokenKind.BARLINE
        }
        target_barline_by_slot = {
            item.slot: item for item in visible_row
            if item.event.kind == MusicTokenKind.BARLINE
        }
        target_barlines = [
            item for item in visible_row if item.event.kind == MusicTokenKind.BARLINE
        ]
        ordered = sorted(items, key=lambda item: (item.slot, item.x, item.event.index))
        cursor = ordered[0].x if ordered else 0.0
        previous_barline_x: float | None = None
        for measure in _measure_groups(ordered):
            cursor = _project_measure(
                measure,
                plan=plan,
                cursor=cursor,
                target_by_slot=target_by_slot,
                target_barline_by_slot=target_barline_by_slot,
                target_barlines=target_barlines,
                previous_barline_x=previous_barline_x,
            )
            if measure and measure[-1].event.kind == MusicTokenKind.BARLINE:
                previous_barline_x = measure[-1].x
        _apply_two_owner_hidden_accidental_release(items, plan=plan)
        apply_overlapping_dsb_hidden_accidental_release(
            items,
            plan=plan,
            visible_row=visible_row,
        )


def _apply_two_owner_hidden_accidental_release(
    items: list[LayoutEvent],
    *,
    plan: SharedProjectionPlan,
) -> None:
    """Release a shared first-column accidental from a second hidden owner."""

    topology = two_owner_trailing_dsb_topology(plan.request.rows)
    if topology is None or not items:
        return
    owner = (items[0].voice, items[0].line)
    owner_keys = {
        (plan.request.rows[index][0].voice, plan.request.rows[index][0].line)
        for index in topology.owner_indices
    }
    if owner not in owner_keys:
        return
    shared_accidental = any(
        first is not None and first.event.accidental is not None
        for index in topology.owner_indices
        for first in (
            next(
                (
                    item
                    for item in plan.request.rows[index][topology.anchor_index + 1 :]
                    if item.event.kind != MusicTokenKind.BARLINE
                ),
                None,
            ),
        )
    )
    first = next(
        (item for item in items if item.event.kind != MusicTokenKind.BARLINE),
        None,
    )
    if not shared_accidental or first is None or first.event.accidental is not None:
        return
    reserve = _INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
    visible_row = next(
        (
            row
            for row in plan.request.rows
            if row and (row[0].voice, row[0].line) == owner
        ),
        None,
    )
    target = next(
        (
            item
            for item in visible_row or ()
            if item.event.kind != MusicTokenKind.BARLINE
            and item.slot == first.stream_slot
        ),
        None,
    )
    if target is not None and abs((target.x - first.x) - reserve) <= GEOMETRY_EPSILON:
        return
    first.x -= reserve
    first.style_x = first.x


def _project_dsb_shadow_grid(
    items: list[LayoutEvent],
    *,
    plan: SharedProjectionPlan,
) -> bool:
    """Place a complete hidden block from its shadow-participant offsets."""
    shadow_grid = plan.dsb_shadow_grid
    if shadow_grid is None:
        return False
    placements: list[Fraction | None] = []
    for item in items:
        key = (item.voice, item.line, item.event.index)
        if key in shadow_grid.hidden_event_right_pins:
            placements.append(None)
            continue
        offset = shadow_grid.hidden_event_offsets.get(key)
        if offset is None:
            return False
        placements.append(offset)
    for item, offset in zip(items, placements, strict=True):
        item.x = (
            plan.right
            if offset is None
            else plan.request.left + float(offset) * plan.scale
        )
        item.style_x = item.x
    return True


def _project_grid_owned_hidden(
    items: list[LayoutEvent],
    *,
    plan: SharedProjectionPlan,
    visible_row: list[LayoutEvent],
) -> None:
    """Place DSB overlay events on the finalized event-keyed visible grid.

    Hidden streams are overlays, not a second intrinsic row: their stream
    slots give the exact shared-grid column, and barline overlays use the
    paired visible measure boundary.
    """
    target_by_slot = {
        item.slot: item for item in visible_row
        if item.event.kind != MusicTokenKind.BARLINE
    }
    target_barlines = [
        item for item in visible_row if item.event.kind == MusicTokenKind.BARLINE
    ]
    ordered = sorted(items, key=lambda item: (item.slot, item.event.index))
    if any(item.onset_aligned for item in ordered):
        _project_exact_onsets(ordered, target_by_slot, target_barlines)
        return
    barline_index = 0
    index = 0
    while index < len(ordered):
        item = ordered[index]
        target = None
        if item.event.kind == MusicTokenKind.BARLINE:
            if item.stream_slot is not None:
                target = next(
                    (c for c in target_barlines if c.slot == item.stream_slot),
                    None,
                )
            if target is None and barline_index < len(target_barlines):
                target = target_barlines[barline_index]
            barline_index += 1
            if target is not None:
                item.x = target.x
            index += 1
            continue
        slot = item.stream_slot
        end = index + 1
        while end < len(ordered) and ordered[end].stream_slot == slot:
            end += 1
        target = target_by_slot.get(slot) if slot is not None else None
        if target is not None:
            delta = target.x - item.x
            for grouped_item in ordered[index:end]:
                grouped_item.x += delta
        index = end


def _column_opens_with_accidental(plan: SharedProjectionPlan, previous_barline_x: float) -> bool:
    """True when any visible row opens the column after ``previous_barline_x``
    with an accidental (the reserve that inflates that column's lead)."""
    barlines = sorted(
        {item.x for row in plan.request.rows for item in row
         if item.event.kind == MusicTokenKind.BARLINE}
    )
    upper = next((x for x in barlines if x > previous_barline_x), float("inf"))
    for row in plan.request.rows:
        first_note_seen = False
        for item in row:
            if item.event.kind == MusicTokenKind.BARLINE:
                first_note_seen = False
                continue
            if not previous_barline_x < item.x < upper or first_note_seen:
                continue
            first_note_seen = True
            if item.event.accidental is not None:
                return True
    return False


def _visible_accidental_at(plan: SharedProjectionPlan, x: float) -> bool:
    """Whether a visible event carrying an accidental sits at ``x``.

    The shared grid inflates such a position by one accidental reserve for
    every row snapping into the beat; hidden groups without their own
    accidental anchor one reserve earlier (Hulunbuir [100] c3: the stacked
    block rows keep 84.6 while the visible 4# sits at 88.2).
    """
    return any(
        item.event.accidental is not None and abs(item.x - x) <= 0.5
        for row in plan.request.rows
        for item in row
    )


def _visible_row(plan: SharedProjectionPlan, *, voice: int, line: int) -> list[LayoutEvent] | None:
    for row in plan.request.rows:
        if row and row[0].voice == voice and row[0].line == line:
            return row
    return None


def _block_identity(item: LayoutEvent) -> tuple[str, ...]:
    identity = tuple(
        construct_id
        for construct_id in item.event.construct_ids
        if ":block:" in construct_id
    )
    return identity or (item.block or "dsb-hidden",)


def _project_exact_onset_cohort(
    items: list[LayoutEvent],
    *,
    plan: SharedProjectionPlan,
    visible_row: list[LayoutEvent],
) -> bool:
    """Project the pinned exact-rhythm compound lyric DSB topology.

    The hidden streams in this semantic family share the visible suffix's
    measure-local rhythm, but grouped cursor projection can assign multiple
    events to one visible stream slot.  Pairing complete measures by exact
    Fraction durations preserves every onset, including subdivisions inside
    one stream group; any mismatch falls back to the legacy projection.
    """
    if not (
        first_meter(plan.request.metrics.time_sig) == (6, 8)
        and plan.request.policy.uses_primary_lyric_parallel_grid
        and plan.request.policy.uses_compound_aligned_two_voice_lyric_grid
    ):
        return False
    ordered = sorted(items, key=lambda item: (item.slot, item.x, item.event.index))
    first_hidden = next(
        (item for item in ordered
         if item.event.kind != MusicTokenKind.BARLINE and item.stream_slot is not None),
        None,
    )
    if first_hidden is None:
        return False
    target_start = next(
        (index for index, item in enumerate(visible_row)
         if item.event.kind != MusicTokenKind.BARLINE
         and item.slot == first_hidden.stream_slot),
        None,
    )
    if target_start is None:
        return False
    hidden_measures = _measure_groups(ordered)
    target_measures = _measure_groups(visible_row[target_start:])
    if len(hidden_measures) != len(target_measures):
        return False
    timed_pairs: list[tuple[list[LayoutEvent], list[LayoutEvent]]] = []
    barline_pairs: list[tuple[list[LayoutEvent], list[LayoutEvent]]] = []
    for hidden_measure, target_measure in zip(
        hidden_measures, target_measures, strict=True
    ):
        hidden_timed = [
            item for item in hidden_measure if item.event.kind != MusicTokenKind.BARLINE
        ]
        target_timed = [
            item for item in target_measure if item.event.kind != MusicTokenKind.BARLINE
        ]
        if len(hidden_timed) != len(target_timed):
            return False
        if tuple(event_duration_fraction(item.event) for item in hidden_timed) != tuple(
            event_duration_fraction(item.event) for item in target_timed
        ):
            return False
        hidden_barlines = [
            item for item in hidden_measure if item.event.kind == MusicTokenKind.BARLINE
        ]
        target_barlines = [
            item for item in target_measure if item.event.kind == MusicTokenKind.BARLINE
        ]
        if len(hidden_barlines) != len(target_barlines):
            return False
        timed_pairs.append((hidden_timed, target_timed))
        barline_pairs.append((hidden_barlines, target_barlines))
    for hidden_timed, target_timed in timed_pairs:
        for hidden_item, target_item in zip(hidden_timed, target_timed, strict=True):
            hidden_item.onset_slot = target_item.slot
            hidden_item.onset_aligned = True
            hidden_item.x = target_item.x
    _apply_exact_onset_accidental_reserves(hidden_measures, plan=plan)
    for hidden_barlines, target_barlines in barline_pairs:
        for hidden_barline, target_barline in zip(
            hidden_barlines, target_barlines, strict=True
        ):
            hidden_barline.onset_slot = target_barline.slot
            hidden_barline.onset_aligned = True
            hidden_barline.x = target_barline.x
    return True


def _apply_exact_onset_accidental_reserves(
    hidden_measures: list[list[LayoutEvent]],
    *,
    plan: SharedProjectionPlan,
) -> None:
    """Preserve the hidden stream's accidental reserve ownership.

    An exact-rhythm hidden overlay can differ from its shared compound group
    by one accidental reserve (group without the shared accidental starts
    earlier; hidden-only accidental starts later); apply only that difference
    after exact onset pairing.
    """
    group_unit = dsb_stream_beat_unit(plan.request.metrics.time_sig)
    for measure in hidden_measures:
        for stream_group in hidden_dsb_stream_groups(measure, group_unit=group_unit):
            group = list(stream_group.items)
            onset_slots = {
                item.onset_slot for item in group if item.onset_slot is not None
            }
            if not onset_slots:
                continue
            hidden_owns_reserve = any(
                item.event.accidental is not None for item in group
            )
            shared_owns_reserve = any(
                item.slot in onset_slots and item.event.accidental is not None
                for row in plan.request.rows for item in row
            )
            ownership_delta = int(hidden_owns_reserve) - int(shared_owns_reserve)
            if ownership_delta == 0:
                continue
            delta = ownership_delta * _INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
            for item in group:
                item.x += delta


def _ghost_clears_bare_zone_start(
    measure: list[LayoutEvent],
    plan: SharedProjectionPlan,
) -> bool:
    """Whether the ghost row opens its zone without the accidental addend.

    The visible union grid inflates a zone's first column by the accidental
    unit when any row opens it with an accidental; a hidden measure without
    that accidental starts one reserve earlier (As-Wished - Choir p3: ghost
    first notes at the bare anchor while lower rows carry the +3.6 addend).
    """
    first_group = next(
        (list(group.items) for group in hidden_dsb_stream_groups(
            measure,
            group_unit=dsb_stream_beat_unit(plan.request.metrics.time_sig),
        ) if group.items),
        None,
    )
    if not first_group or first_group[0].stream_slot is None:
        return False
    if any(item.event.accidental is not None for item in first_group):
        return False
    return any(
        item.slot == first_group[0].stream_slot
        and item.event.accidental is not None
        for row in plan.request.rows
        for item in row
    )


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


def _project_measure(
    measure: list[LayoutEvent],
    *,
    plan: SharedProjectionPlan,
    cursor: float,
    target_by_slot: Mapping[int, LayoutEvent],
    target_barline_by_slot: Mapping[int, LayoutEvent],
    target_barlines: list[LayoutEvent],
    previous_barline_x: float | None = None,
) -> float:
    """Project one hidden-row measure onto the shared grid; returns the new cursor x.

    Onset-aligned measures snap to authoritative target slots/barlines; measure-aligned
    lyric-free rows keep slot-snapped positions plus the ghost-origin shift only (a rebuilt
    intrinsic cursor would reintroduce DSB drift). Both branches are REF-decoded."""
    if any(item.onset_aligned for item in measure):
        _project_exact_onsets(measure, target_by_slot, target_barlines)
        return max((item.x for item in measure), default=cursor)
    if measure and all(
        item.event.kind == MusicTokenKind.BARLINE or item.stream_slot is not None
        for item in measure
    ) and not any(
        item.event.kind != MusicTokenKind.BARLINE and item.event.duration_slashes
        for item in measure
    ):
        ghost_origin_shift = (
            -_INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
            if (
                plan.dsb_union_grid
                and previous_barline_x is None
                and _ghost_clears_bare_zone_start(measure, plan)
            )
            else 0.0
        )
        for group_index, stream_group in enumerate(
            hidden_dsb_stream_groups(
                measure,
                group_unit=dsb_stream_beat_unit(plan.request.metrics.time_sig),
            )
        ):
            group = list(stream_group.items)
            if not group:
                continue
            target = (
                target_by_slot.get(group[0].stream_slot)
                if group[0].stream_slot is not None
                else None
            )
            if target is not None:
                delta = target.x - group[0].x + (
                    ghost_origin_shift if group_index == 0 else 0.0
                )
                if (
                    plan.dsb_union_grid
                    and group_index == 0
                    and previous_barline_x is not None
                    and _column_opens_with_accidental(plan, previous_barline_x)
                ):
                    first_timed = next(
                        (item.event for item in group if item.event.kind != MusicTokenKind.BARLINE),
                        None,
                    )
                    if first_timed is None or first_timed.accidental is None:
                        # The visible column opens with an accidental reserve
                        # this hidden measure does not carry; anchor at the
                        # barline plus the unshifted natural lead ([92] c3:
                        # visible rows step from 28.8, the hidden row keeps 25.2).
                        delta = previous_barline_x + _NATURAL_LEADING_GAP * plan.scale - group[0].x
                elif (
                    plan.dsb_union_grid
                    and group_index > 0
                    and not any(item.event.accidental is not None for item in group)
                    and _visible_accidental_at(plan, target.x)
                ):
                    # The shared beat position carries an accidental reserve
                    # this hidden group does not own; anchor one reserve early.
                    delta -= _INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
                for item in group:
                    item.x += delta
        for item in measure:
            if item.event.kind != MusicTokenKind.BARLINE:
                continue
            target = (
                target_barline_by_slot.get(item.stream_slot)
                if item.stream_slot is not None else None
            ) or (target_barlines[-1] if target_barlines else None)
            if target is not None:
                item.x = target.x
        return next(
            (item.x for item in reversed(measure)
             if item.event.kind == MusicTokenKind.BARLINE),
            cursor,
        )
    if len(measure) == 1:
        item = measure[0]
        target = (
            target_barline_by_slot.get(item.stream_slot)
            if item.event.kind == MusicTokenKind.BARLINE and item.stream_slot is not None
            else None
        )
        if target is not None:
            item.x = target.x
            return target.x
        item.x = cursor
        return cursor
    profile = build_legacy_intrinsic_profile(
        measure,
        metrics=plan.request.metrics,
        left=plan.request.left,
        lyric_text_by_event={},
    )
    profile_index_by_event = {id(item): index for index, item in enumerate(measure)}
    stream_groups = hidden_dsb_stream_groups(
        measure,
        group_unit=dsb_stream_beat_unit(plan.request.metrics.time_sig),
    )
    measure_is_unbeamed = not any(
        item.event.duration_slashes > 0
        for stream_group in stream_groups
        for item in stream_group.items
    )
    for group_index, stream_group in enumerate(stream_groups):
        group = list(stream_group.items)
        stream_slot = group[0].stream_slot
        first_timed = next(
            (item.event for item in group if item.event.kind != MusicTokenKind.BARLINE),
            None,
        )
        if (
            _should_anchor_group(group, group_index=group_index,
                                 measure_is_unbeamed=measure_is_unbeamed)
            and stream_slot is not None
        ):
            target = target_by_slot.get(stream_slot)
            if target is not None:
                cursor = target.x
                if (
                    plan.dsb_union_grid
                    and group_index == 0
                    and previous_barline_x is None
                    and _ghost_clears_bare_zone_start(measure, plan)
                ):
                    # Ghost rows clear the zone's barline without the
                    # accidental addend that inflates the visible column.
                    cursor -= _INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
                elif (
                    plan.dsb_union_grid
                    and group_index > 0
                    and not any(item.event.accidental is not None for item in group)
                    and _visible_accidental_at(plan, target.x)
                ):
                    # The shared beat position carries an accidental reserve
                    # this hidden group does not own; anchor one reserve early.
                    cursor -= _INTRINSIC_ACCIDENTAL_RESERVE * plan.scale
            if (
                plan.dsb_union_grid
                and group_index == 0
                and previous_barline_x is not None
            ):
                # The shared visible grid may open the measure wider than the
                # hidden measure's own natural gap (zone-start columns) or with
                # an accidental reserve it does not carry; anchor at the barline
                # plus the wider lead, stripping the accidental inflation when
                # the column's extra comes from one ([100] c1 keeps the 39.6
                # zone lead; [108] c4 / [92] c3 keep the bare 25.2).
                gap = _NATURAL_LEADING_GAP + (
                    _INTRINSIC_ACCIDENTAL_RESERVE
                    if first_timed is not None and first_timed.accidental is not None
                    else 0.0
                )
                visible_target = (
                    target_by_slot.get(group[0].stream_slot)
                    if group[0].stream_slot is not None
                    else None
                )
                if visible_target is not None:
                    visible_lead = (visible_target.x - previous_barline_x) / plan.scale
                    if _column_opens_with_accidental(plan, previous_barline_x):
                        visible_lead -= _INTRINSIC_ACCIDENTAL_RESERVE
                    gap = max(gap, visible_lead)
                cursor = previous_barline_x + gap * plan.scale
        for item in group:
            index = profile_index_by_event[id(item)]
            item.x = cursor
            if index < len(profile.interval_widths):
                cursor += profile.interval_widths[index] * plan.scale
            else:
                cursor += profile.terminal_width * plan.scale
    for item in measure:
        if item.event.kind != MusicTokenKind.BARLINE:
            continue
        target = (target_barline_by_slot.get(item.stream_slot)
                  if item.stream_slot is not None else None)
        if target is None and target_barlines:
            target = target_barlines[-1]
        if target is not None:
            item.x = target.x
            cursor = target.x
        else:
            item.x = cursor
    return cursor


def _project_exact_onsets(
    measure: list[LayoutEvent],
    target_by_slot: Mapping[int, LayoutEvent],
    target_barlines: list[LayoutEvent],
) -> None:
    """Project event-level onset pairs without collapsing beam subdivisions."""
    for item in measure:
        if item.onset_slot is None:
            continue
        target = target_by_slot.get(item.onset_slot)
        if item.event.kind == MusicTokenKind.BARLINE:
            target = next(
                (bar for bar in target_barlines if bar.slot == item.onset_slot),
                target_barlines[-1] if target_barlines else None,
            )
        if target is not None:
            item.x = target.x


def _should_anchor_group(
    group: list[LayoutEvent],
    *,
    group_index: int,
    measure_is_unbeamed: bool,
) -> bool:
    """Return whether a hidden group should reset to its visible stream slot.

    A measure origin must always come from the finalized visible grid.  In an
    all-unbeamed measure every group has a direct visible onset; a mixed
    measure only promotes its first group and groups carrying duration slashes
    (preserving intrinsic spacing for later un-beamed groups, whose position
    is not represented by a separate beam onset).
    """

    return (
        measure_is_unbeamed
        or group_index == 0
        or any(item.event.duration_slashes > 0 for item in group)
    )

__all__ = ["reproject_hidden_dsb_events"]
