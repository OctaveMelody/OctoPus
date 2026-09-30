"""Shared-system denominator planning and coordinate projection."""

from __future__ import annotations

from fractions import Fraction
from math import fsum

from octopus.render.core.layout_types import LayoutEvent, PageMetrics
from octopus.render.layout_engine.grid.beat_grid import GridEventKey
from octopus.render.layout_engine.grid.shared_grid_policies import (
    synthetic_hidden_rest_pre_barline_release_index,
    uses_compound_tied_grace_beat_expiry,
    uses_widest_compound_lyric_denominator,
)
from octopus.render.layout_engine.hidden.hidden_streams import event_duration_fraction
from octopus.render.layout_engine.rows.projection import project_interval_prefix

from ....parser.ast import MusicTokenKind
from .crossing_union_widths import (
    compute_crossing_union_widths,
    union_grid_repositions_events,
)
from .dotted_tail_alignment import align_elevated_dotted_tail_subdivision
from .dsb_continuation_snap import snap_dsb_continuation_columns
from .dsb_continuation_widths import compute_dsb_continuation_widths
from .dsb_gap_reserves import apply_dsb_gap_reserves
from .dsb_multiblock_widths import hook_grid_rejected
from .grace_alignment import align_host_local_grace_measure_onsets
from .models import SharedProjectionPlan, SharedProjectionRequest
from .overlapping_dsb_widths import compute_overlapping_dsb_widths
from .shared_grace import (
    shared_grace_cursor_width,
    shared_grace_denominator_adjustment,
    shared_grace_timeline,
)
from .trailing_dsb import apply_trailing_dsb_sustain_reserve

SHARED_DSB_PLACEHOLDER_RESERVE = 45.0


def relative_origin_offset(left: float, metrics: PageMetrics) -> float:
    """Return the shared origin relative to the ordinary note origin."""

    return left - metrics.note_start_x


def build_shared_projection_plan(
    request: SharedProjectionRequest,
) -> SharedProjectionPlan | None:
    policy = request.policy
    rows = request.rows
    base_widths = apply_trailing_dsb_sustain_reserve(
        rows,
        request.reconciled_widths,
        profiles=request.profiles,
        lyric_text_by_voice=request.lyric_text_by_voice,
        time_sig=request.metrics.time_sig,
    )
    # The DSB gap reserves must run after the family-specific boundary
    # clearances (the second-ending continuation reserve in terminal policies
    # and the trailing-sustain reserve above) so their max() semantics never
    # double-count a barline gap that is already reserved.
    profiles, base_widths = apply_dsb_gap_reserves(
        rows,
        base_widths,
        request.profiles,
        four_beat_refinement_owned=policy.uses_four_beat_refinement_grid,
    )
    reconciled_widths = [
        _apply_shared_dsb_nested_tie_reserves(row, row_interval_widths)
        for row, row_interval_widths in zip(rows, base_widths, strict=True)
    ]
    # DSB continuation systems lay every visible row on the shared union
    # note-group column grid instead of the reconciled legacy widths (see
    # dsb_continuation_widths for the oracle-verified rules).  The overlapping
    # mixed-closure topology uses a separate source-derived column mapping,
    # but retains the legacy denominator so its compression scale remains
    # unchanged.
    legacy_reconciled_widths = reconciled_widths
    dsb_union_widths = compute_dsb_continuation_widths(rows)
    crossing_union_widths = (
        None if dsb_union_widths is not None else compute_crossing_union_widths(rows)
    )
    overlapping_widths = None
    if dsb_union_widths is not None:
        reconciled_widths = dsb_union_widths[0]
    else:
        overlapping_widths = compute_overlapping_dsb_widths(rows, reconciled_widths)
        if overlapping_widths is not None:
            reconciled_widths = overlapping_widths
    denominator_widths = (
        legacy_reconciled_widths
        if overlapping_widths is not None
        else reconciled_widths
    )
    uses_midrow_dsb_grid = dsb_union_widths is not None and dsb_union_widths[2]
    mixed_origin_authority_index = (
        next(index for index, row in enumerate(rows) if row[0].x != request.left)
        if policy.mixed_origin_four_voice_grid
        else None
    )
    leading_pickup_slot_width = (
        denominator_widths[mixed_origin_authority_index][0]
        if mixed_origin_authority_index is not None
        and reconciled_widths[mixed_origin_authority_index]
        else 0.0
    )
    uses_compound_tied_grace_expiry = uses_compound_tied_grace_beat_expiry(
        rows,
        uses_primary_lyric_parallel_grid=policy.uses_primary_lyric_parallel_grid,
        uses_compound_aligned_two_voice_lyric_grid=(
            policy.uses_compound_aligned_two_voice_lyric_grid
        ),
    )
    grace_timeline = shared_grace_timeline(
        rows,
        request.shared_grace_raw,
        tied_expiry_beat=Fraction(3, 2) if uses_compound_tied_grace_expiry else None,
    )
    fixed_grace_width = sum(reserve.width for reserve in grace_timeline)
    profile_denominators = tuple(
        fsum(
            (
                *denominator_row_widths,
                profile.terminal_width,
                profile.final_bar_width,
                profile.denominator_adjustment,
            )
        )
        for denominator_row_widths, profile in zip(
            denominator_widths, profiles, strict=True
        )
    )
    uses_widest_compound_denominator = uses_widest_compound_lyric_denominator(
        rows,
        profile_denominators,
        uses_primary_lyric_parallel_grid=policy.uses_primary_lyric_parallel_grid,
        uses_compound_aligned_two_voice_lyric_grid=(
            policy.uses_compound_aligned_two_voice_lyric_grid
        ),
    )
    denominator = (
        max(profile_denominators, default=0.0)
        if uses_widest_compound_denominator
        else profile_denominators[0]
        if (
            policy.uses_primary_modified_ending_grid
            or policy.uses_primary_parallel_voice_denominator
            or policy.uses_dominant_primary_lyric_grid
            or policy.uses_primary_lyric_parallel_grid
            or policy.uses_two_voice_tied_response_lyric_grid
        )
        else max(profile_denominators, default=0.0)
    )
    denominator -= shared_grace_denominator_adjustment(rows, request.shared_grace_raw)
    denominator -= leading_pickup_slot_width / 10.0
    denominator += request.shared_leading_accidental_reserve
    if policy.mixed_origin_four_voice_grid:
        denominator += SHARED_DSB_PLACEHOLDER_RESERVE * sum(
            item.block == "dsb-placeholder" for row in rows for item in row
        )
    if policy.primary_call_response_starts_with_two_rests:
        denominator -= 9.0
    if (
        policy.uses_compound_aligned_two_voice_lyric_grid
        and not grace_timeline
        and any(
            {index, index + 1} <= skip_indices
            and any(
                any(
                    request.lyric_text_by_voice.get(row[0].voice, {}).get(
                        (later.event.span.start.line, later.event.index), ()
                    )
                )
                for later in row[index + 2 :]
            )
            for row, skip_indices in zip(rows, request.skip_indices_by_row, strict=True)
            for index in skip_indices
        )
    ):
        denominator -= 9.0
    right = float(request.metrics.width - request.metrics.margin_right + 3)
    scale_numerator = right - request.left - fixed_grace_width
    if not uses_midrow_dsb_grid:
        scale_numerator += 14.0
    if dsb_union_widths is not None:
        denominator = dsb_union_widths[1]
        profile_denominators = (denominator,) * len(rows)
    elif crossing_union_widths is not None and union_grid_repositions_events(
        [tuple(widths) for widths in reconciled_widths],
        list(crossing_union_widths[0]),
        scale_numerator=scale_numerator,
        legacy_denominator=denominator,
        union_denominator=crossing_union_widths[1],
    ):
        reconciled_widths = list(crossing_union_widths[0])
        denominator = crossing_union_widths[1]
        profile_denominators = (denominator,) * len(rows)
    if denominator <= 0:
        return None
    right = float(request.metrics.width - request.metrics.margin_right + 3)
    scale = scale_numerator / denominator
    if policy.uses_shared_first_onset_grace_anchor:
        shared_anchor_offset = policy.first_onset_grace_anchor_width
    elif mixed_origin_authority_index is not None:
        shared_anchor_offset = leading_pickup_slot_width * scale / 2.0
    elif request.shared_leading_accidental_reserve:
        shared_anchor_offset = request.shared_leading_accidental_reserve * scale / 2.0
    else:
        shared_anchor_offset = 0.0
    if hook_grid_rejected(dsb_union_widths, rows, scale, shared_anchor_offset):
        # See hook_grid_rejected: a divergent hook offset keeps legacy widths.
        return None
    return SharedProjectionPlan(
        request=request,
        reconciled_widths=reconciled_widths,
        grace_timeline=grace_timeline,
        profile_denominators=profile_denominators,
        right=right,
        scale=scale,
        shared_anchor_offset=shared_anchor_offset,
        uses_measure_origin_spacing=(
            policy.uses_compact_four_voice_grid or request.left == 125.0
        ),
        dsb_union_grid=(
            dsb_union_widths is not None or overlapping_widths is not None
        ),
    )


def project_shared_system(plan: SharedProjectionPlan) -> None:
    if plan.grid_owned and plan.grid_projection is not None:
        _project_grid_owned_system(plan)
        _stamp_projection_scale(plan)
        return
    request = plan.request
    policy = request.policy
    rows = request.rows
    reconciled_widths = plan.reconciled_widths
    left = request.left
    right = plan.right
    scale = plan.scale
    shared_anchor_offset = plan.shared_anchor_offset
    uses_measure_origin_spacing = plan.uses_measure_origin_spacing
    shared_grace_timeline = plan.grace_timeline
    uses_compact_four_voice_grid = policy.uses_compact_four_voice_grid
    uses_single_lyric_aligned_slot_grid = policy.uses_single_lyric_aligned_slot_grid
    uses_primary_lyric_parallel_grid = policy.uses_primary_lyric_parallel_grid
    for row, row_interval_widths in zip(rows, reconciled_widths, strict=True):
        row[0].x = left + shared_anchor_offset
        measure_left = left + shared_anchor_offset
        measure_start = 0
        rhythmic_onset = Fraction()
        for index, item in enumerate(row[1:-1], start=1):
            rhythmic_onset += event_duration_fraction(row[index - 1].event)
            item.x = (
                project_interval_prefix(
                    row_interval_widths,
                    origin=measure_left,
                    scale=scale,
                    start=measure_start,
                    end=index,
                    summation=(
                        "compensated" if uses_compact_four_voice_grid else "legacy"
                    ),
                )
                if uses_measure_origin_spacing
                else project_interval_prefix(
                    row_interval_widths,
                    origin=left + shared_anchor_offset,
                    scale=scale,
                    start=0,
                    end=index,
                    summation="compensated",
                )
            )
            next_measure_left = item.x
            item.x += shared_grace_cursor_width(
                shared_grace_timeline,
                voice=row[0].voice,
                onset=rhythmic_onset,
                at_barline=item.event.kind == MusicTokenKind.BARLINE,
            )
            # Subdivision-closer reserve: a tied closer step gives back the
            # 3.6 units its accidental column reserved (unit-scale geometry;
            # the adjacent-float corrections that used to surround this branch
            # were retired under the 1e-6 acceptance rule, item 22).
            if (
                not uses_single_lyric_aligned_slot_grid
                and item.event.duration_slashes
                and ")" in item.event.code
                and (
                    row[index - 1].event.accidental is not None
                    and row[index - 1].event.duration_slashes
                    or uses_primary_lyric_parallel_grid
                    and any(
                        index < len(parallel_row)
                        and parallel_row[index - 1].event.accidental is not None
                        and parallel_row[index - 1].event.duration_slashes
                        for parallel_row in rows
                    )
                )
            ):
                item.x -= 3.6 * scale
            if (
                uses_measure_origin_spacing
                and item.event.kind == MusicTokenKind.BARLINE
            ):
                measure_left = next_measure_left
                measure_start = index
        row[-1].x = right
    if not plan.dsb_union_grid:
        # The union note-group grid already places every DSB-continuation row
        # on the shared columns; the legacy snap would re-fit them onto the
        # authority row's table and undo the pre-anchor placement.
        snap_dsb_continuation_columns(plan)
    align_host_local_grace_measure_onsets(plan)
    align_elevated_dotted_tail_subdivision(plan)
    _stamp_projection_scale(plan)


def _stamp_projection_scale(plan: SharedProjectionPlan) -> None:
    kind = "grid" if plan.grid_owned else "shared"
    for row in plan.request.rows:
        for item in row:
            item.projection_scale = plan.scale
            item.projection_kind = kind


def _grid_x_for_item(
    plan: SharedProjectionPlan,
    row: list[LayoutEvent],
    item: LayoutEvent,
    item_index: int,
) -> float | None:
    projection = plan.grid_projection
    if projection is None:
        return None
    if item.event.kind == MusicTokenKind.BARLINE:
        ordinal = sum(
            prior.event.kind == MusicTokenKind.BARLINE
            for prior in row[: item_index + 1]
        ) - 1
        if 0 <= ordinal < len(projection.barline_x_offsets):
            adjustment = (
                plan.dsb_shadow_grid.barline_adjustments[ordinal]
                if plan.dsb_shadow_grid is not None
                else Fraction()
            )
            return (
                plan.request.left
                + float(projection.barline_x_offsets[ordinal] + adjustment) * plan.scale
                + projection.barline_grace_shifts.get((item.voice, ordinal), 0)
            )
        return None
    key = GridEventKey.for_event(item.event, item.voice)
    override = (
        plan.dsb_shadow_grid.visible_event_offsets.get(key)
        if plan.dsb_shadow_grid is not None
        else None
    )
    if override is not None:
        return (
            plan.request.left
            + float(override) * plan.scale
            + projection.event_grace_shifts.get(key, 0)
        )
    offset = projection.event_x_offsets.get(key)
    if offset is None:
        return None
    adjustment = (
        plan.dsb_shadow_grid.visible_event_adjustments.get(key, Fraction())
        if plan.dsb_shadow_grid is not None
        else Fraction()
    )
    return (
        plan.request.left
        + float(offset + adjustment) * plan.scale
        + projection.event_grace_shifts.get(key, 0)
    )


def _project_grid_owned_system(plan: SharedProjectionPlan) -> None:
    for row in plan.request.rows:
        previous_x: float | None = None
        for item_index, item in enumerate(row):
            projected = _grid_x_for_item(plan, row, item, item_index)
            if projected is None:
                if item.event.kind == MusicTokenKind.GRACE_GROUP and previous_x is not None:
                    # Grace markers are invisible to the grid's x projection;
                    # they render relative to their host note.
                    projected = previous_x
                elif not (item.event.kind == MusicTokenKind.BARLINE and item_index == len(row) - 1):
                    # The only unmapped case proven in the corpus is a final barline
                    # whose ordinal exceeds the grid's measure count (cross-barline
                    # spans, Night-In-The-Desert p4); it is anchored to the system
                    # right edge below. Any other unmapped event means the grid width
                    # model lacks this event type — fail loudly instead of silently
                    # overlapping it with its predecessor.
                    raise RuntimeError(
                        "grid-owned system has an unmapped event "
                        f"(voice={item.voice}, kind={item.event.kind.value}, "
                        f"code={item.event.code!r}, index={item_index}); extend the shared "
                        "grid model instead of falling back to a predecessor position"
                    )
                else:
                    projected = plan.right
            item.x = projected
            item.style_x = projected
            previous_x = projected
        if row and row[-1].event.kind == MusicTokenKind.BARLINE:
            row[-1].x = plan.right
            row[-1].style_x = plan.right
        release_index = synthetic_hidden_rest_pre_barline_release_index(row)
        if release_index is not None:
            for item in row[release_index:-1]:
                item.x -= 7.0
                item.style_x = item.x


def _apply_shared_dsb_nested_tie_reserves(
    row: list[LayoutEvent], interval_widths: tuple[float, ...]
) -> tuple[float, ...]:
    if not any(item.block == "dsb-tail" for item in row):
        return interval_widths
    adjusted = list(interval_widths)
    for index, item in enumerate(row[:-1]):
        if index >= len(adjusted):
            break
        tie_roles = tuple(role for role in item.event.construct_roles if ":tie:" in role)
        next_tie_roles = tuple(
            role for role in row[index + 1].event.construct_roles if ":tie:" in role
        )
        if row[index + 1].block == "dsb-tail" and any(
            role.endswith(":start") for role in tie_roles
        ):
            adjusted[index] += 9.0
        elif len(tie_roles) >= 2 and (
            any(role.endswith(":start") for role in tie_roles)
            or sum(role.endswith(":end") for role in next_tie_roles) >= 2
        ):
            adjusted[index] += 3.6
    return tuple(adjusted)


__all__ = [
    "SharedProjectionPlan",
    "SharedProjectionRequest",
    "build_shared_projection_plan",
    "project_shared_system",
    "relative_origin_offset",
]
