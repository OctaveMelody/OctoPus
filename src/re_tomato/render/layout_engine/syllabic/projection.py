"""Ordered coordinate projection for one planned syllabic row."""

from __future__ import annotations

from math import fsum

from .event_corrections import apply_semantic_corrections
from .models import SyllabicProjectionPlan, SyllabicProjectionState


def project_syllabic_row(plan: SyllabicProjectionPlan) -> None:
    row = plan.request.row
    state = SyllabicProjectionState(
        iterative_x=row[0].x,
        expired_grace_positions=set(),
    )
    for index, item in enumerate(row[1:-1], start=1):
        _advance_cursor(plan, state, index)
        _project_base_event(plan, state, index)
        apply_semantic_corrections(plan, state, index)
        item.style_x = plan.style_positions[index]
    _project_terminal(plan)
    for item in row:
        item.projection_scale = plan.scale
        item.projection_kind = "syllabic"


def _advance_cursor(
    plan: SyllabicProjectionPlan,
    state: SyllabicProjectionState,
    index: int,
) -> None:
    reserves = plan.reserves
    grace = plan.grace
    state.iterative_x += reserves.profile.interval_widths[index - 1] * plan.scale
    if index - 1 in reserves.fixed_lyric_connector_positions:
        state.iterative_x += 9.0 * plan.scale
    if index in reserves.dotted_hook_positions:
        state.iterative_x += 9.0 * plan.scale
    if index in reserves.dsb_anchor_positions:
        state.iterative_x += 14.4 * plan.scale
    if index in reserves.bz_overlay_positions:
        state.iterative_x -= 9.0 * plan.scale
    state.iterative_x += grace.width_by_position.get(index, 0.0)
    newly_expired = {
        position
        for position in grace.width_by_position
        if position not in state.expired_grace_positions
        and (
            position in grace.expiry_by_position
            and grace.rhythmic_onsets[index] >= grace.expiry_by_position[position]
            or grace.replacement_by_position.get(position) == index
        )
    }
    state.iterative_x -= sum(grace.width_by_position[position] for position in newly_expired)
    state.expired_grace_positions.update(newly_expired)


def _project_base_event(
    plan: SyllabicProjectionPlan,
    state: SyllabicProjectionState,
    index: int,
) -> None:
    request = plan.request
    reserves = plan.reserves
    row = request.row
    item = row[index]
    prefix_width = fsum(reserves.profile.interval_widths[:index])
    grace_width = plan.grace.cursor_width(index, len(row))
    connector_width = 9.0 * plan.scale * sum(
        position < index for position in reserves.fixed_lyric_connector_positions
    )
    dotted_width = 9.0 * plan.scale * sum(
        position <= index for position in reserves.dotted_hook_positions
    )
    dsb_width = 14.4 * plan.scale * sum(
        position <= index for position in reserves.dsb_anchor_positions
    )
    bz_width = 9.0 * plan.scale * sum(
        position <= index for position in reserves.bz_overlay_positions
    )
    if plan.flags.uses_iterative_spacing:
        # The iterative cursor is the row's x model here; no adjacent-float
        # tie-breaks (1e-6 acceptance rule, owner decision 2026-09-07).
        item.x = state.iterative_x
        return
    scaled_prefix = (
        (plan.leading_width + prefix_width)
        * plan.distributed_width
        / reserves.intrinsic_width
        if plan.flags.uses_local_scale
        else (plan.leading_width + prefix_width) * plan.scale
    )
    item.x = (
        request.left
        + scaled_prefix
        + grace_width
        + connector_width
        + dotted_width
        + dsb_width
        - bz_width
    )


def _project_terminal(plan: SyllabicProjectionPlan) -> None:
    request = plan.request
    profile = plan.reserves.profile
    request.row[-1].x = (
        request.left
        + (
            plan.leading_width
            + fsum(profile.interval_widths)
            + profile.raw_terminal_width
        )
        * plan.scale
        if request.ragged
        else request.right
    )
    request.row[-1].style_x = plan.style_positions[-1]


__all__ = ["project_syllabic_row"]
