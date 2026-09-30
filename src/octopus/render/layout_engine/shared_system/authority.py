"""Shared lyric-authority classification and base width reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent, PageMetrics
from ..grid.authority_grids import (
    uses_one_authority_generated_terminal_cadence_grid,
    uses_three_authority_dotted_generated_terminal_grid,
    uses_two_authority_dotted_generated_terminal_grid,
)
from ..grid.shared_grid_policies import (
    uses_dominant_primary_lyric_grid,
    uses_four_beat_refinement_grid,
    uses_primary_modified_ending_grid,
    uses_primary_parallel_voice_denominator_grid,
    uses_primary_spanning_hook_grid,
)
from ..grid.union_grid import project_union_duration_grid
from ..hidden.hidden_streams import event_duration_fraction
from ..profile_widths import (
    merge_shared_onset_reserves,
    reconcile_parallel_repeat_ending_widths,
    transfer_non_partitioned_terminal_reserves,
)
from ..profiles import LegacyIntrinsicProfile
from ..rows.primary_projection import project_primary_profile_widths
from ..rows.row_signatures import (
    shared_measure_durations_match,
    shared_row_rhythm_signature,
)
from ..rows.sparse_projection import (
    project_sparse_hidden_measure_widths,
)
from ..shared_measure.reconciliation import reconcile_shared_measure_widths
from ..streams import uses_compound_meter
from .models import LyricTextByVoice


@dataclass(frozen=True)
class SharedAuthorityState:
    profiles: list[LegacyIntrinsicProfile]
    reconciled_widths: list[tuple[float, ...]]
    visible_indices: list[int]
    visible_voice_count: int
    uses_primary_ascii_dual_verse_dsb_grid: bool
    uses_primary_lyric_parallel_grid: bool
    uses_multi_lyric_three_voice_grid: bool
    uses_three_authority_dotted_grid: bool
    uses_two_authority_dotted_grid: bool
    uses_one_authority_terminal_grid: bool
    uses_primary_modified_ending_grid: bool
    uses_primary_spanning_hook_grid: bool
    uses_primary_parallel_voice_denominator: bool
    uses_four_beat_refinement_grid: bool
    uses_dominant_primary_lyric_grid: bool
    uses_lyricless_coarse_secondary_grid: bool


def build_shared_authority_state(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    primary_system_verse_count: int,
    punctuation_indices_by_row: list[frozenset[int]],
    terminal_punctuation_by_row: list[bool],
    skip_indices_by_row: list[frozenset[int]],
    skip_connector_indices_by_row: list[frozenset[int]],
    uses_single_lyric_rhythm_grid: bool,
    uses_shifted_voice_grid: bool,
    uses_compact_four_voice_grid: bool,
    uses_unequal_slot_duration_grid: bool,
    uses_multi_voice_heterogeneous_authority_grid: bool,
    preserve_compound_dual_verse_terminal_reserve: bool,
) -> SharedAuthorityState:
    """Build the shared authority state: which rows own the grid's widths.

    Determines the visible (lyric-carrying) row indices and the per-row authority
    assignments under each grid family flag (single-lyric-rhythm, shifted voice,
    compact four-voice, unequal slot durations, heterogeneous authority). The
    authority state decides which row's profile drives each shared column; every
    branch is REF-decoded (see docs/rules/SVG_GEN_RULES.md for the policy record)."""
    visible_indices = [
        index
        for index, row in enumerate(rows)
        if any(
            text
            for item in row
            for text in lyric_text_by_voice.get(row[0].voice, {}).get(
                (item.event.span.start.line, item.event.index), ()
            )
        )
    ]
    uses_ascii_dsb = (
        visible_indices == [0]
        and primary_system_verse_count >= 2
        and any("&dsb_a" in item.event.code for row in rows for item in row)
        and any(
            len(texts) >= 2 and any(texts[:-1]) and not texts[-1]
            for texts in lyric_text_by_voice.get(rows[0][0].voice, {}).values()
        )
        and all(
            character.isascii() or character.isspace()
            for lyric_text in lyric_text_by_voice.values()
            for texts in lyric_text.values()
            for text in texts
            for character in text
        )
    )
    uses_primary_parallel = (
        visible_indices == [0]
        and len(rows) >= 2
        and len({shared_row_rhythm_signature(row) for row in rows}) == 1
        and (
            uses_compound_meter(metrics.time_sig)
            or uses_ascii_dsb
            or any(
                "(" in item.event.code
                and ")" in row[index + 1].event.code
                and text.startswith("　")
                for row in rows
                for index, item in enumerate(row[:-1])
                for text in lyric_text_by_voice.get(row[0].voice, {}).get(
                    (item.event.span.start.line, item.event.index), ()
                )
            )
        )
    )
    uses_multi_lyric_three = (
        len(rows) == 3
        and len(visible_indices) >= 2
        and shared_measure_durations_match(rows)
    )
    uses_three_dotted = uses_three_authority_dotted_generated_terminal_grid(
        rows, visible_indices
    )
    uses_two_dotted = uses_two_authority_dotted_generated_terminal_grid(rows, visible_indices)
    uses_one_terminal = uses_one_authority_generated_terminal_cadence_grid(
        rows, visible_indices
    )
    uses_shifted_onset = (
        len(rows) == 2
        and left == 125.0
        and visible_indices == [0, 1]
        and shared_measure_durations_match(rows)
        and len(
            {
                tuple(
                    index
                    for index, item in enumerate(row)
                    if item.event.kind == MusicTokenKind.BARLINE
                )
                for row in rows
            }
        )
        > 1
    )
    uses_modified = uses_primary_modified_ending_grid(rows, visible_indices)
    uses_spanning = uses_primary_spanning_hook_grid(rows, visible_indices)
    uses_primary_denominator = uses_primary_parallel_voice_denominator_grid(
        rows, visible_indices
    )
    uses_four_beat = uses_four_beat_refinement_grid(rows)
    uses_dominant = uses_dominant_primary_lyric_grid(
        rows, visible_indices, lyric_text_by_voice
    )
    if uses_spanning:
        primary_widths = list(profiles[0].interval_widths)
        final_bar_index = max(
            (
                index
                for index, item in enumerate(rows[0][:-1])
                if item.event.kind == MusicTokenKind.BARLINE
            ),
            default=0,
        )
        if primary_widths:
            primary_widths[min(final_bar_index, len(primary_widths) - 1)] += 9.0
        profiles[0] = replace(profiles[0], interval_widths=tuple(primary_widths))
    if uses_multi_lyric_three:
        profiles = merge_shared_onset_reserves(
            rows, profiles, matching_durations_only=uses_three_dotted
        )
    elif uses_shifted_onset:
        profiles = merge_shared_onset_reserves(rows, profiles, matching_durations_only=True)
    dominant_widths = project_primary_profile_widths(rows, profiles) if uses_dominant else None
    reconciled = (
        dominant_widths
        if dominant_widths is not None
        else [profile.interval_widths for profile in profiles]
        if uses_single_lyric_rhythm_grid
        else reconcile_shared_measure_widths(
            rows,
            profiles,
            punctuation_indices_by_row=punctuation_indices_by_row,
            terminal_punctuation_by_row=terminal_punctuation_by_row,
            skip_indices_by_row=skip_indices_by_row,
            skip_connector_indices_by_row=skip_connector_indices_by_row,
            uses_shifted_voice_grid=uses_shifted_voice_grid,
            uses_compact_four_voice_grid=uses_compact_four_voice_grid,
            uses_primary_spanning_hook_grid=uses_spanning,
            uses_primary_parallel_voice_denominator=uses_primary_denominator,
            allows_partial_boundaries=uses_multi_lyric_three or uses_modified or uses_spanning,
            allows_shorter_measure_projection=len(rows) == 3 and left == 105.0,
        )
    )

    if not preserve_compound_dual_verse_terminal_reserve:
        profiles, reconciled = transfer_non_partitioned_terminal_reserves(
            rows, profiles, reconciled
        )
    reconciled = project_sparse_hidden_measure_widths(rows, reconciled)
    if uses_unequal_slot_duration_grid:
        reconciled = project_union_duration_grid(rows, profiles, reconciled)
    if uses_multi_voice_heterogeneous_authority_grid:
        _transfer_heterogeneous_terminal_tie(rows, reconciled, visible_indices)
    reconciled = reconcile_parallel_repeat_ending_widths(
        rows, reconciled, visible_lyric_profile_indices=visible_indices
    )
    return SharedAuthorityState(
        profiles=profiles,
        reconciled_widths=reconciled,
        visible_indices=visible_indices,
        visible_voice_count=len(visible_indices),
        uses_primary_ascii_dual_verse_dsb_grid=uses_ascii_dsb,
        uses_primary_lyric_parallel_grid=uses_primary_parallel,
        uses_multi_lyric_three_voice_grid=uses_multi_lyric_three,
        uses_three_authority_dotted_grid=uses_three_dotted,
        uses_two_authority_dotted_grid=uses_two_dotted,
        uses_one_authority_terminal_grid=uses_one_terminal,
        uses_primary_modified_ending_grid=uses_modified,
        uses_primary_spanning_hook_grid=uses_spanning,
        uses_primary_parallel_voice_denominator=uses_primary_denominator,
        uses_four_beat_refinement_grid=uses_four_beat,
        uses_dominant_primary_lyric_grid=uses_dominant,
        uses_lyricless_coarse_secondary_grid=uses_dominant and not visible_indices,
    )


def _transfer_heterogeneous_terminal_tie(
    rows: list[list[LayoutEvent]],
    reconciled: list[tuple[float, ...]],
    visible_indices: list[int],
) -> None:
    authority_index = visible_indices[0]
    authority_row = rows[authority_index]
    authority_bars = [
        index
        for index, item in enumerate(authority_row)
        if item.event.kind == MusicTokenKind.BARLINE
    ]
    if len(authority_bars) < 2:
        return
    authority_start, authority_end = authority_bars[-2] + 1, authority_bars[-1]
    authority_ties = [
        index
        for index in range(authority_start, authority_end - 1)
        if "(" in authority_row[index].event.code
        and ")" in authority_row[index + 1].event.code
    ]
    for voice_index, row in enumerate(rows):
        if voice_index == authority_index:
            continue
        bars = [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        if len(bars) < 2:
            continue
        for index in range(bars[-2] + 1, bars[-1] - 1):
            if "(" not in row[index].event.code or ")" not in row[index + 1].event.code:
                continue
            authority_tie = next(
                (
                    candidate
                    for candidate in authority_ties
                    if event_duration_fraction(authority_row[candidate].event)
                    < event_duration_fraction(row[index].event)
                    and event_duration_fraction(authority_row[candidate + 1].event)
                    == event_duration_fraction(row[index + 1].event)
                ),
                None,
            )
            if authority_tie is None:
                continue
            reserve = reconciled[authority_index][authority_tie - 1]
            adjusted = list(reconciled[voice_index])
            if reserve > 0 and adjusted[index] >= reserve:
                adjusted[index] -= reserve
                adjusted[index + 1] += reserve
                reconciled[voice_index] = tuple(adjusted)
            break


__all__ = ["SharedAuthorityState", "build_shared_authority_state"]
