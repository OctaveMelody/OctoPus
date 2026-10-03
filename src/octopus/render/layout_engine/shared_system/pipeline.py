"""Ordered shared-system layout pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from octopus.render.core.layout_types import LayoutEvent, PageMetrics
from octopus.render.layout_engine.grid.beat_grid import TIMED_KINDS
from octopus.render.layout_engine.grid.shared_grid_policies import (
    uses_compound_dual_verse_lyric_profile_grid,
    uses_compound_dual_verse_terminal_reserve_grid,
    uses_lyric_unequal_slot_duration_grid,
    uses_three_voice_dotted_primary_lyric_grid,
    uses_three_voice_interleaved_lyric_grid,
    uses_two_voice_single_lyric_event_swap_grid,
    uses_two_voice_terminal_duration_swap_grid,
)
from octopus.render.layout_engine.hidden.hidden_streams import (
    event_duration_fraction as duration_fraction,
)
from octopus.render.layout_engine.rows.sparse_projection import (
    project_sparse_leading_rows_from_continuation,
)

from ....parser.ast import MusicTokenKind
from ..profiles import LegacyIntrinsicProfile
from .alternating_union import apply_alternating_four_voice_policies
from .authority import SharedAuthorityState, build_shared_authority_state
from .dotted_policy import apply_shared_dotted_system_reserve
from .grid_projection_plans import (
    build_dsb_shadow_grid_projection_plan,
    build_grid_owned_projection_plan,
)
from .models import (
    LyricTextByVoice,
    SharedProjectionPolicy,
    SharedSystemAdmission,
    SharedSystemClassification,
    SharedSystemRequest,
)
from .phrase_patterns import apply_phrase_pattern_policies
from .phrase_transitions import apply_phrase_transition_policies
from .post_authority import apply_post_authority_reserves
from .preparation import prepare_shared_system
from .profile_building import SharedRawProfiles
from .profile_harmonization import prepare_shared_profiles
from .projection import (
    SharedProjectionPlan,
    SharedProjectionRequest,
    build_shared_projection_plan,
    project_shared_system,
    relative_origin_offset,
)
from .terminal import apply_terminal_reserve_policies


@dataclass(frozen=True, slots=True)
class SharedSystemPipelineRequest:
    system: SharedSystemRequest
    metrics: PageMetrics
    primary_system_verse_count: int = 0


def run_shared_system_pipeline(
    request: SharedSystemPipelineRequest,
) -> SharedProjectionPlan | None:
    """Run the full shared-system width pipeline for one multi-voice system.

    Order of stages (each stage may reshape row profiles/widths; REF parity depends
    on this exact sequence):

    1. ``prepare_shared_system`` — admission (is this system grid-eligible at all?)
       plus classification (which grid family it belongs to). Returns None when the
       system must fall back to per-voice legacy layout.
    2. Grid-owned fast path: some systems (e.g. beat-grid-union shapes) project from
       the measure grid directly and skip profile/authority work entirely.
    3. ``prepare_shared_profiles`` — build the raw intrinsic row profiles and the
       punctuation/skip index tables that later reserve policies consume.
    4. Authority state, dotted-system reserves, phrase-pattern policies, phrase
       transitions, post-authority reserves, terminal reserves, alternating four-voice
       policies — each a REF-decoded width adjustment (see the individual modules).
    5. ``build_shared_projection_plan`` — turn the final profiles/widths into the
       per-row x coordinates the SVG stage renders.

    Returns the projection plan, or None when admission rejected the system."""
    metrics = request.metrics
    left = request.system.left
    primary_system_verse_count = request.primary_system_verse_count
    prepared = prepare_shared_system(
        request.system,
        metrics=metrics,
        primary_system_verse_count=primary_system_verse_count,
    )
    if prepared is None:
        return None
    admission, classification = prepared
    rows = list(admission.rows)
    voice_rows = list(admission.voice_rows)
    lyric_text_by_voice = admission.lyric_text_by_voice
    grid_lyric_text_by_voice = (
        request.system.grid_lyric_text_by_voice or lyric_text_by_voice
    )
    shared_grace_raw = admission.grace_raw_by_voice
    mixed_origin_four_voice_grid = admission.mixed_origin_four_voice_grid
    uses_shared_first_onset_grace_anchor = admission.uses_shared_first_onset_grace_anchor
    first_onset_grace_anchor_width = admission.first_onset_grace_anchor_width
    uses_merged_four_row_grid = admission.uses_merged_four_row_grid
    uses_leading_two_voice_grid = admission.uses_leading_two_voice_grid
    visible_lyric_rows = list(classification.visible_lyric_rows)
    dual_verse_ascii_authority_indices = classification.dual_verse_ascii_authority_indices
    multi_voice_ascii_authority_indices = classification.multi_voice_ascii_authority_indices
    shared_leading_accidental_reserve = classification.shared_leading_accidental_reserve
    uses_unequal_slot_duration_grid = classification.uses_unequal_slot_duration_grid
    uses_two_voice_dual_verse_ascii_grid = classification.uses_two_voice_dual_verse_ascii_grid
    uses_multi_voice_ascii_mixed_rhythm_grid = (
        classification.uses_multi_voice_ascii_mixed_rhythm_grid
    )
    uses_multi_voice_heterogeneous_authority_grid = (
        classification.uses_multi_voice_heterogeneous_authority_grid
    )
    uses_primary_compound_beat_grid = classification.uses_primary_compound_beat_grid
    early_grid_plan = _try_early_grid_projection(
        rows=rows,
        hidden_events=tuple(request.system.hidden_events),
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
    )
    if early_grid_plan is not None:
        return early_grid_plan
    (
        profile_admission,
        lyric_text_by_voice,
        uses_compound_dual_verse_profile_grid,
        preserve_compound_dual_verse_terminal_reserve,
    ) = _prepare_compound_dual_verse_profile(
        admission,
        classification,
        rows=rows,
        visible_lyric_rows=visible_lyric_rows,
        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
    )
    (
        raw_profile_result,
        profiles,
        uses_single_lyric_rhythm_grid,
        authority_state,
    ) = _prepare_shared_authority(
        profile_admission,
        classification,
        rows=rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
        primary_system_verse_count=primary_system_verse_count,
        uses_unequal_slot_duration_grid=uses_unequal_slot_duration_grid,
        uses_multi_voice_heterogeneous_authority_grid=(
            uses_multi_voice_heterogeneous_authority_grid
        ),
        preserve_compound_dual_verse_terminal_reserve=(
            preserve_compound_dual_verse_terminal_reserve
        ),
    )
    profiles = authority_state.profiles
    reconciled_widths = authority_state.reconciled_widths
    skip_indices_by_row = list(raw_profile_result.skip_indices_by_row)
    uses_compact_four_voice_grid = raw_profile_result.policy.uses_compact_four_voice_grid
    uses_compound_aligned_two_voice_lyric_grid = (
        raw_profile_result.policy.uses_compound_aligned_two_voice_lyric_grid
    )
    profiles, reconciled_widths = apply_shared_dotted_system_reserve(
        rows,
        profiles,
        reconciled_widths,
        lyric_text_by_voice=lyric_text_by_voice,
        time_sig=metrics.time_sig,
    )
    visible_lyric_profile_indices = authority_state.visible_indices
    uses_primary_ascii_dual_verse_dsb_grid = (
        authority_state.uses_primary_ascii_dual_verse_dsb_grid
    )
    uses_primary_lyric_parallel_grid = authority_state.uses_primary_lyric_parallel_grid
    uses_multi_lyric_three_voice_grid = authority_state.uses_multi_lyric_three_voice_grid
    uses_three_authority_dotted_grid = authority_state.uses_three_authority_dotted_grid
    uses_two_authority_dotted_grid = authority_state.uses_two_authority_dotted_grid
    uses_one_authority_terminal_grid = authority_state.uses_one_authority_terminal_grid
    uses_primary_modified_ending_grid = authority_state.uses_primary_modified_ending_grid
    uses_primary_parallel_voice_denominator = (
        authority_state.uses_primary_parallel_voice_denominator
    )
    uses_four_beat_refinement_grid = authority_state.uses_four_beat_refinement_grid
    uses_dominant_primary_lyric_grid = authority_state.uses_dominant_primary_lyric_grid
    uses_lyricless_coarse_secondary_grid = (
        authority_state.uses_lyricless_coarse_secondary_grid
    )
    phrase_pattern_state = apply_phrase_pattern_policies(
        rows,
        profiles,
        reconciled_widths,
        left=left,
        visible_lyric_profile_indices=visible_lyric_profile_indices,
        lyric_text_by_voice=lyric_text_by_voice,
    )
    profiles = phrase_pattern_state.profiles
    reconciled_widths = phrase_pattern_state.reconciled_widths
    uses_two_voice_five_measure_lyric_grid = (
        phrase_pattern_state.uses_two_voice_five_measure_lyric_grid
    )
    uses_two_voice_call_response_lyric_grid = (
        phrase_pattern_state.uses_two_voice_call_response_lyric_grid
    )
    uses_two_voice_tied_response_lyric_grid = (
        phrase_pattern_state.uses_two_voice_tied_response_lyric_grid
    )
    primary_call_response_starts_with_two_rests = (
        phrase_pattern_state.primary_call_response_starts_with_two_rests
    )
    profiles, reconciled_widths = apply_phrase_transition_policies(
        rows,
        profiles,
        reconciled_widths,
        left=left,
        visible_lyric_profile_indices=visible_lyric_profile_indices,
        lyric_text_by_voice=lyric_text_by_voice,
        uses_two_voice_five_measure_lyric_grid=uses_two_voice_five_measure_lyric_grid,
        uses_two_voice_call_response_lyric_grid=uses_two_voice_call_response_lyric_grid,
        uses_two_voice_tied_response_lyric_grid=uses_two_voice_tied_response_lyric_grid,
    )
    profiles, reconciled_widths, uses_single_lyric_aligned_slot_grid = (
        apply_post_authority_reserves(
            rows,
            profiles,
            list(raw_profile_result.profiles),
            reconciled_widths,
            metrics=metrics,
            left=left,
            lyric_text_by_voice={
                voice: dict(text_by_event)
                for voice, text_by_event in lyric_text_by_voice.items()
            },
            visible_lyric_rows=visible_lyric_rows,
            visible_lyric_profile_indices=visible_lyric_profile_indices,
            dual_verse_ascii_authority_indices=dual_verse_ascii_authority_indices,
            multi_voice_ascii_authority_indices=multi_voice_ascii_authority_indices,
            uses_primary_compound_beat_grid=uses_primary_compound_beat_grid,
            uses_primary_lyric_parallel_grid=uses_primary_lyric_parallel_grid,
            uses_five_measure_shared_grid=raw_profile_result.policy.uses_five_measure_grid,
            uses_compact_four_voice_grid=raw_profile_result.policy.uses_compact_four_voice_grid,
            uses_single_lyric_rhythm_grid=uses_single_lyric_rhythm_grid,
            uses_two_voice_dual_verse_ascii_grid=uses_two_voice_dual_verse_ascii_grid,
            uses_multi_voice_ascii_mixed_rhythm_grid=(
                uses_multi_voice_ascii_mixed_rhythm_grid
            ),
            uses_primary_ascii_dual_verse_dsb_grid=(
                uses_primary_ascii_dual_verse_dsb_grid
            ),
            uses_compound_aligned_two_voice_lyric_grid=(
                uses_compound_aligned_two_voice_lyric_grid
            ),
            uses_compound_dual_verse_lyric_profile_grid=(
                uses_compound_dual_verse_profile_grid
            ),
        )
    )
    profiles, reconciled_widths = apply_terminal_reserve_policies(
        rows,
        profiles,
        list(raw_profile_result.profiles),
        reconciled_widths,
        visible_lyric_profile_indices=visible_lyric_profile_indices,
        uses_two_authority_dotted_grid=uses_two_authority_dotted_grid,
        uses_one_authority_terminal_grid=uses_one_authority_terminal_grid,
        uses_merged_four_row_grid=uses_merged_four_row_grid,
        uses_compact_four_voice_grid=raw_profile_result.policy.uses_compact_four_voice_grid,
    )
    profiles, reconciled_widths = apply_alternating_four_voice_policies(
        rows, profiles, reconciled_widths,
        visible_lyric_rows=visible_lyric_rows, time_sig=metrics.time_sig,
    )
    shared_projection_plan = build_shared_projection_plan(
        SharedProjectionRequest(
            rows=rows,
            profiles=profiles,
            reconciled_widths=reconciled_widths,
            metrics=metrics,
            left=left,
            origin_offset=relative_origin_offset(left, metrics),
            lyric_text_by_voice=lyric_text_by_voice,
            shared_grace_raw=shared_grace_raw,
            skip_indices_by_row=skip_indices_by_row,
            shared_leading_accidental_reserve=shared_leading_accidental_reserve,
            policy=SharedProjectionPolicy(
                mixed_origin_four_voice_grid=mixed_origin_four_voice_grid,
                uses_primary_modified_ending_grid=uses_primary_modified_ending_grid,
                uses_primary_parallel_voice_denominator=(
                    uses_primary_parallel_voice_denominator
                ),
                uses_dominant_primary_lyric_grid=uses_dominant_primary_lyric_grid,
                uses_primary_lyric_parallel_grid=uses_primary_lyric_parallel_grid,
                uses_two_voice_tied_response_lyric_grid=(
                    uses_two_voice_tied_response_lyric_grid
                ),
                primary_call_response_starts_with_two_rests=(
                    primary_call_response_starts_with_two_rests
                ),
                uses_compound_aligned_two_voice_lyric_grid=(
                    uses_compound_aligned_two_voice_lyric_grid
                ),
                uses_compact_four_voice_grid=uses_compact_four_voice_grid,
                uses_shared_first_onset_grace_anchor=uses_shared_first_onset_grace_anchor,
                first_onset_grace_anchor_width=first_onset_grace_anchor_width,
                uses_multi_lyric_three_voice_grid=uses_multi_lyric_three_voice_grid,
                uses_three_authority_dotted_grid=uses_three_authority_dotted_grid,
                uses_two_voice_five_measure_lyric_grid=(
                    uses_two_voice_five_measure_lyric_grid
                ),
                uses_primary_compound_beat_grid=uses_primary_compound_beat_grid,
                uses_four_beat_refinement_grid=uses_four_beat_refinement_grid,
                uses_lyricless_coarse_secondary_grid=uses_lyricless_coarse_secondary_grid,
                uses_single_lyric_aligned_slot_grid=uses_single_lyric_aligned_slot_grid,
            ),
        )
    )
    if shared_projection_plan is None:
        return None
    project_shared_system(shared_projection_plan)
    if uses_leading_two_voice_grid:
        _project_sparse_leading_rows(
            voice_rows, metrics=metrics, left=left, lyric_text_by_voice=lyric_text_by_voice
        )
    return shared_projection_plan


def _prepare_compound_dual_verse_profile(
    admission: SharedSystemAdmission,
    classification: SharedSystemClassification,
    *,
    rows: list[list[LayoutEvent]],
    visible_lyric_rows: list[bool],
    grid_lyric_text_by_voice: LyricTextByVoice,
) -> tuple[SharedSystemAdmission, LyricTextByVoice, bool, bool]:
    uses_profile = uses_compound_dual_verse_lyric_profile_grid(
        rows,
        visible_lyric_rows,
        uses_primary_dual_verse_compound_grid=(
            classification.uses_primary_dual_verse_compound_grid
        ),
        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
    )
    profile_lyrics = (
        {
            row[0].voice: grid_lyric_text_by_voice.get(row[0].voice, {})
            for row in rows
        }
        if uses_profile
        else admission.lyric_text_by_voice
    )
    profile_admission = (
        replace(admission, lyric_text_by_voice=profile_lyrics)
        if uses_profile
        else admission
    )
    preserve_terminal = uses_compound_dual_verse_terminal_reserve_grid(
        rows,
        uses_compound_dual_verse_lyric_profile_grid=uses_profile,
    )
    return (
        profile_admission,
        profile_admission.lyric_text_by_voice,
        uses_profile,
        preserve_terminal,
    )


def _prepare_shared_authority(
    admission: SharedSystemAdmission,
    classification: SharedSystemClassification,
    *,
    rows: list[list[LayoutEvent]],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    primary_system_verse_count: int,
    uses_unequal_slot_duration_grid: bool,
    uses_multi_voice_heterogeneous_authority_grid: bool,
    preserve_compound_dual_verse_terminal_reserve: bool,
) -> tuple[SharedRawProfiles, list[LegacyIntrinsicProfile], bool, SharedAuthorityState]:
    raw_profile_result, profiles, uses_single_lyric_rhythm_grid = prepare_shared_profiles(
        admission,
        classification,
        metrics=metrics,
        left=left,
    )
    authority_state = build_shared_authority_state(
        rows,
        profiles,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
        primary_system_verse_count=primary_system_verse_count,
        punctuation_indices_by_row=list(raw_profile_result.punctuation_indices_by_row),
        terminal_punctuation_by_row=list(raw_profile_result.terminal_punctuation_by_row),
        skip_indices_by_row=list(raw_profile_result.skip_indices_by_row),
        skip_connector_indices_by_row=list(raw_profile_result.skip_connector_indices_by_row),
        uses_single_lyric_rhythm_grid=uses_single_lyric_rhythm_grid,
        uses_shifted_voice_grid=raw_profile_result.policy.uses_shifted_voice_grid,
        uses_compact_four_voice_grid=raw_profile_result.policy.uses_compact_four_voice_grid,
        uses_unequal_slot_duration_grid=uses_unequal_slot_duration_grid,
        uses_multi_voice_heterogeneous_authority_grid=(
            uses_multi_voice_heterogeneous_authority_grid
        ),
        preserve_compound_dual_verse_terminal_reserve=(
            preserve_compound_dual_verse_terminal_reserve
        ),
    )
    return raw_profile_result, profiles, uses_single_lyric_rhythm_grid, authority_state


def _project_sparse_leading_rows(
    voice_rows: list[list[list[LayoutEvent]]],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
) -> None:
    project_sparse_leading_rows_from_continuation(
        voice_rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice={
            voice: dict(text_by_event)
            for voice, text_by_event in lyric_text_by_voice.items()
        },
    )


def _try_early_grid_projection(
    *,
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    grid_lyric_text_by_voice: LyricTextByVoice,
) -> SharedProjectionPlan | None:
    dsb_plan = _try_dsb_shadow_grid_projection(
        rows=rows,
        hidden_events=hidden_events,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
    )
    if dsb_plan is not None:
        return dsb_plan
    return _try_grid_owned_projection(
        rows=rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=grid_lyric_text_by_voice,
    )


def _try_grid_owned_projection(
    *,
    rows: list[list[LayoutEvent]],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
) -> SharedProjectionPlan | None:
    """Enroll and project the group on the shared duration grid when eligible."""

    if not _eligible_for_grid_owned_projection(
        rows, left=left, time_sig=metrics.time_sig
    ):
        return None
    if len(rows) == 2:
        visible_lyric_rows = tuple(
            any(
                bool(text)
                for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
                for text in texts
            )
            for row in rows
        )
        if not (
            uses_lyric_unequal_slot_duration_grid(rows, visible_lyric_rows)
            or uses_two_voice_single_lyric_event_swap_grid(rows, visible_lyric_rows)
            or uses_two_voice_terminal_duration_swap_grid(rows, visible_lyric_rows)
        ):
            return None
    elif len(rows) == 3:
        if not (
            uses_three_voice_interleaved_lyric_grid(rows, lyric_text_by_voice)
            or uses_three_voice_dotted_primary_lyric_grid(rows, lyric_text_by_voice)
        ):
            return None
    plan = build_grid_owned_projection_plan(
        rows=rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
    )
    if plan is None:
        return None
    project_shared_system(plan)
    return plan


def _try_dsb_shadow_grid_projection(
    *,
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    grid_lyric_text_by_voice: LyricTextByVoice,
) -> SharedProjectionPlan | None:
    """Enroll the complete one-measure visible-plus-shadow DSB family."""
    plan = build_dsb_shadow_grid_projection_plan(
        rows=rows,
        hidden_events=hidden_events,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
    )
    if plan is None:
        return None
    project_shared_system(plan)
    return plan


def _eligible_for_grid_owned_projection(
    rows: list[list[LayoutEvent]],
    *,
    left: float,
    time_sig: str = "",
) -> bool:
    """Return whether the shared duration grid can own this group's visible x.

    Layout-selection rule (user-confirmed 2026-08-23): multi-voice systems are
    laid out on shared duration-grid columns rather than per-row intrinsic
    projection, regardless of decorations, construct roles, barline variants,
    hidden rests, parenthesized spans (including cross-barline ones), or
    annotations. Hidden rests are first-class grid items and span/annotation
    tokens are invisible to the x projection (see beat_grid.py).
    The remaining guards are structural safety, not layout style: a complete
    two-, three-, or four-voice group sharing one left edge and one uniform barline
    topology, with no unpaired hidden-block (DSB) events whose synthetic
    alignment topology is not yet paired into the event-keyed grid. Three-row
    groups are further filtered by a semantic lyric-owner policy at the call
    site; the guard itself deliberately does not infer lyric ownership.
    """

    if len(rows) < 2 or any(not row for row in rows):
        return False
    if len({row[0].voice for row in rows}) != len(rows):
        return False
    # The legacy per-row layout already shifts a row whose first note carries
    # an unquoted grace marker right by its reservation; the grid model moves
    # the whole system's left edge instead, so both starting positions are
    # admissible (oracle-verified 2026-08-23, Looking-Back p3 L93-L98).
    for row in rows:
        first = row[0]
        if first.x != left and first.x != left + first.event.grace_reservation:
            return False
    # Parenthesis span markers and annotations are invisible to the grid's x
    # projection (_analyze_line_exact skips non-timed kinds); they never occupy
    # a column, so they do not disqualify a group. Oracle-verified 2026-08-23
    # on As-Wished-Choir p1: the reference lays out such systems on the shared
    # duration grid exactly as if the span/annotation tokens were absent.
    allowed = {
        MusicTokenKind.BARLINE,
        *TIMED_KINDS,
        MusicTokenKind.SPAN_START,
        MusicTokenKind.SPAN_END,
        MusicTokenKind.ANNOTATION,
        # Attached grace markers are invisible to the grid's x projection
        # (they render relative to their host note); they never occupy a
        # column, so they do not disqualify a group.
        MusicTokenKind.GRACE_GROUP,
    }
    if any(
        item.event.kind not in allowed
        for row in rows
        for item in row
    ):
        return False
    bar_counts = {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row)
        for row in rows
    }
    if len(bar_counts) != 1 or min(bar_counts) < 2:
        return False
    # BZ is an overlay above the existing melody; its closing barline remains
    # an ordinary grid boundary. DSB placeholders retain separate topology.
    if any(item.block not in {None, "bz-tail"} for row in rows for item in row):
        return False
    # Cross-barline parenthesized spans and rest-only (pickup) measures were
    # once proven catastrophically outside the grid width model (Night-In-The-
    # Desert p2/p3: 116-130 px barline drift). That catastrophe was an artifact
    # of the pre-B0-3a5 width model; with phantom-column steps, the
    # accidental-aware max, and per-accidental terminal reserves in place the
    # reference's grid layout is reproduced exactly there (NITD p2 note-exact,
    # p3 313 -> 35 residuals) and on As-Wished-Choir p1 / Edelweiss-Choir p2.
    # The guard was therefore retired 2026-08-23 (whole-corpus A/B: +1,509
    # tags, zero semantic regressions).
    if len(rows) >= 4:
        return True
    full_measure = _full_measure_beats(time_sig)
    if full_measure is None:
        return False
    return all(_first_measure_beats(row) == full_measure for row in rows)


def _full_measure_beats(time_sig: str) -> Fraction | None:
    """One full measure's length in quarter-note beats, or None if unknown."""
    try:
        numerator_s, denominator_s = time_sig.split("/")
        numerator, denominator = int(numerator_s), int(denominator_s)
    except (ValueError, AttributeError):
        return None
    if denominator == 0:
        return None
    return Fraction(numerator * 4, denominator)


def _first_measure_beats(row: list[LayoutEvent]) -> Fraction:
    """Timed duration (quarter beats) before the row's first barline."""
    total = Fraction(0, 1)
    for item in row:
        if item.event.kind == MusicTokenKind.BARLINE:
            break
        total += duration_fraction(item.event)
    return total


__all__ = ["SharedSystemPipelineRequest", "run_shared_system_pipeline"]
