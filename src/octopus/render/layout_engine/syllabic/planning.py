"""Build the immutable projection plan for one syllabic row."""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ..duration_groups import duration_group_positions as _duration_group_positions
from ..intrinsic.builder import (
    _is_compact_latin_bilingual_profile,
    _uses_cjk_dual_verse_four_four_grid,
)
from ..intrinsic.terminal import uses_compact_terminal_lyric_run as _uses_compact_terminal_lyric_run
from ..streams import meter_beat_duration as _meter_beat_duration
from .grace import build_syllabic_grace_state
from .models import (
    SyllabicGracePlan,
    SyllabicProjectionFlags,
    SyllabicProjectionPlan,
    SyllabicReservePlan,
    SyllabicRowRequest,
)
from .profile import build_syllabic_profile_state


def build_syllabic_projection_plan(
    request: SyllabicRowRequest,
    style_positions: tuple[float, ...],
) -> SyllabicProjectionPlan | None:
    """Build the syllabic projection plan: per-event x positions for one row.

    Sequence: profile state → grace state (None aborts the plan) → width
    reconciliation against the requested scale/raggedness → final x assignment with
    barline anchoring. The plan is what the SVG stage renders, so its arithmetic is
    pinned to REF output at 1e-6 tolerance."""
    row = request.row
    metrics = request.metrics
    left = request.left
    right = request.right
    lyric_text_by_event = request.lyric_text_by_event
    requested_scale = request.requested_scale
    ragged = request.ragged
    grace_host_indices = request.grace_host_indices
    profile_state = build_syllabic_profile_state(request)
    grace_state = build_syllabic_grace_state(request, profile_state)
    if grace_state is None:
        return None
    profile = profile_state.profile
    intrinsic_width = grace_state.intrinsic_width
    fixed_grace_width = grace_state.fixed_width
    leading_accidental_reserve = grace_state.leading_accidental_reserve
    grace_width_by_position = grace_state.width_by_position
    fixed_lyric_connector_positions = grace_state.fixed_lyric_connector_positions
    uses_compound_meter = profile_state.uses_compound_meter
    distributed_width = right - left + 14.0 - fixed_grace_width
    if requested_scale is None:
        uses_local_scale = True
        scale = distributed_width / intrinsic_width
    else:
        uses_local_scale = False
        scale = requested_scale
    bz_overlay_positions = frozenset(
        index for index, item in enumerate(row[:-1]) if item.block == "bz-placeholder"
    )
    if (
        ragged
        and left
        + (sum(profile.interval_widths) + profile.raw_terminal_width) * scale
        + fixed_grace_width
        > right
    ):
        return None
    leading_width = (
        9.0
        if "zkh" in row[0].event.decorations
        else leading_accidental_reserve / 2.0
    )
    row[0].x = left + leading_width * scale + grace_width_by_position.get(0, 0.0)
    row[0].style_x = style_positions[0]
    uses_ascii_lyrics = sum(
        sum(char.isascii() for char in text) >= 3
        for item in row
        for text in lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
        if text
    ) >= 2
    uses_compact_latin_bilingual_profile = _is_compact_latin_bilingual_profile(
        metrics,
        lyric_text_by_event,
    )
    uses_cjk_dual_verse_four_four_grid = _uses_cjk_dual_verse_four_four_grid(
        metrics,
        lyric_text_by_event,
    )
    uses_compact_terminal_lyric_run = (
        not uses_compound_meter
        and _uses_compact_terminal_lyric_run(
            row,
            lyric_text_by_event,
        )
    )
    first_sounded_event = next(
        (
            item.event
            for item in row
            if item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        ),
        None,
    )
    uses_dotted_open_extension_tail = bool(
        first_sounded_event is not None
        and first_sounded_event.duration_dots
        and row[-2].event.kind == MusicTokenKind.EXTENSION
    )
    uses_second_ending_grace_spacing = (
        row[0].event.code.startswith("|n['2'")
        and bool(grace_host_indices)
    )
    uses_special_leading_grid = (
        bool(row[0].event.decorations)
        or "(" in row[0].event.code
        or row[0].event.code.startswith(("|n", "|z"))
        or row[0].event.kind == MusicTokenKind.HIDDEN_REST
    )
    duration_group_members, duration_group_terminals = _duration_group_positions(
        row,
        beat_duration=_meter_beat_duration(request.metrics.time_sig),
    )
    first_row_bar_index = next(
        (
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ),
        -1,
    )
    uses_low_pickup_parenthesized_ending_grid = (
        row[0].event.pitch == 6
        and row[0].event.octave < 0
        and row[0].event.duration_slashes == 1
        and row[-1].event.code == "|"
        and sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 5
        and any(
            item.event.code.endswith("//)")
            and "(/" in row[position + 1].event.code
            for position, item in enumerate(row[:-1])
        )
    )
    uses_iterative_spacing = uses_ascii_lyrics or (
        any("bc" in item.event.decorations for item in row)
        and any("zkh" in item.event.decorations for item in row)
        and any("ykh" in item.event.decorations for item in row)
    ) or uses_second_ending_grace_spacing
    return SyllabicProjectionPlan(
        request=request,
        reserves=SyllabicReservePlan(
            profile=profile,
            intrinsic_width=intrinsic_width,
            leading_accidental_reserve=leading_accidental_reserve,
            dotted_hook_positions=grace_state.dotted_hook_positions,
            dsb_anchor_positions=grace_state.dsb_anchor_positions,
            fixed_lyric_connector_positions=fixed_lyric_connector_positions,
            bz_overlay_positions=bz_overlay_positions,
            subdivided_tie_release_index=profile_state.subdivided_tie_release_index,
            dual_verse_middle_bar_reserve_index=(
                profile_state.dual_verse_middle_bar_reserve_index
            ),
            dotted_lyric_terminal_release_indices=(
                profile_state.dotted_lyric_terminal_release_indices
            ),
            leading_first_ending_sentinel_release_index=(
                profile_state.leading_first_ending_sentinel_release_index
            ),
        ),
        grace=SyllabicGracePlan(
            width_by_position=grace_width_by_position,
            expiry_by_position=grace_state.expiry_by_position,
            replacement_by_position=grace_state.replacement_by_position,
            rhythmic_onsets=grace_state.rhythmic_onsets,
            fixed_width=fixed_grace_width,
        ),
        flags=SyllabicProjectionFlags(
            uses_ascii_lyrics=uses_ascii_lyrics,
            uses_cjk_dual_verse_four_four_grid=uses_cjk_dual_verse_four_four_grid,
            uses_compact_latin_bilingual_profile=uses_compact_latin_bilingual_profile,
            uses_compact_terminal_lyric_run=uses_compact_terminal_lyric_run,
            uses_compound_meter=uses_compound_meter,
            uses_dotted_open_extension_tail=uses_dotted_open_extension_tail,
            uses_iterative_spacing=uses_iterative_spacing,
            uses_local_scale=uses_local_scale,
            uses_low_pickup_parenthesized_ending_grid=uses_low_pickup_parenthesized_ending_grid,
            uses_second_ending_grace_spacing=uses_second_ending_grace_spacing,
            uses_special_leading_grid=uses_special_leading_grid,
        ),
        style_positions=tuple(style_positions),
        distributed_width=distributed_width,
        leading_width=leading_width,
        scale=scale,
        row_lyric_verse_count=grace_state.row_lyric_verse_count,
        duration_group_members=duration_group_members,
        duration_group_terminals=duration_group_terminals,
        first_row_bar_index=first_row_bar_index,
    )


__all__ = ["build_syllabic_projection_plan"]
