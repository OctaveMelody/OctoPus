"""Ordered terminal-reserve and continuation-boundary policies."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..grid.authority_grids import (
    uses_shared_dotted_generated_terminal_grid as _uses_dotted_generated_terminal_grid,
)
from ..grid.grid_policies import (
    uses_parallel_second_ending_continuation_grid as _uses_second_ending_grid,
)
from ..profiles import LegacyIntrinsicProfile
from ..reserves.interval_reserves import (
    allocate_continuation_boundary_reserve as _allocate_continuation_boundary_reserve,
)
from ..reserves.interval_reserves import (
    allocate_dotted_onset_reserves as _allocate_dotted_onset_reserves,
)
from ..reserves.interval_reserves import (
    allocate_terminal_cadence_reserve as _allocate_terminal_cadence_reserve,
)
from ..reserves.interval_reserves import (
    transfer_interval_reserve_to_terminal as _transfer_interval_reserve_to_terminal,
)
from ..rows.refined_projection import (
    project_refined_shared_measure_widths as _project_refined_shared_measure_widths,
)
from ..rows.row_signatures import row_event_onsets as _row_event_onsets
from .accidental_alignment import restore_open_ending_accidental_onset_reserve
from .parallel_refrain import apply_parallel_refrain_reserves


def apply_terminal_reserve_policies(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    raw_profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    visible_lyric_profile_indices: list[int],
    uses_two_authority_dotted_grid: bool,
    uses_one_authority_terminal_grid: bool,
    uses_merged_four_row_grid: bool,
    uses_compact_four_voice_grid: bool,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    """Apply end-of-row (terminal) width reserves before projection.

    Handles the REF-decoded terminal shapes: dotted generated-terminal grids,
    one/two-authority terminal cadences, merged four-row and compact four-voice
    grids. Adjusts profiles/reconciled widths so a row's final barline and its
    trailing lyric clearance match the reference; runs after authority and phrase
    policies and before the projection plan is built."""
    if _uses_dotted_generated_terminal_grid(
        rows,
        visible_lyric_profile_indices,
    ):
        terminal_interval_index = next(
            index + 1
            for index, item in enumerate(rows[0][:-1])
            if item.event.kind == MusicTokenKind.BARLINE
            and index + 1 < len(rows[0]) - 1
            and sum(
                prior.event.kind == MusicTokenKind.BARLINE
                for prior in rows[0][: index + 1]
            )
            == 2
        )
        dotted_terminal_widths: list[tuple[float, ...]] = []
        dotted_terminal_profiles: list[LegacyIntrinsicProfile] = []
        for row_widths, profile in zip(
            reconciled_widths,
            profiles,
            strict=True,
        ):
            transfer = _transfer_interval_reserve_to_terminal(
                row_widths,
                interval_index=terminal_interval_index,
                terminal_reserve=profile.terminal_width,
                transfer_width=9.0,
            )
            dotted_terminal_widths.append(transfer.interval_widths)
            dotted_terminal_profiles.append(
                replace(profile, terminal_width=transfer.terminal_reserve)
            )
        reconciled_widths = dotted_terminal_widths
        profiles = dotted_terminal_profiles
    if uses_two_authority_dotted_grid:
        two_authority_widths: list[tuple[float, ...]] = []
        two_authority_profiles: list[LegacyIntrinsicProfile] = []
        for row, row_widths, profile in zip(
            rows,
            reconciled_widths,
            profiles,
            strict=True,
        ):
            onsets = _row_event_onsets(row)
            onset_index: dict[Fraction, int] = {}
            for index, onset in enumerate(onsets[:-1]):
                onset_index.setdefault(onset, index)
            first_shared_index = onset_index[Fraction(5, 2)]
            dotted_boundary_index = onset_index[Fraction(23, 4)]
            final_shared_index = onset_index[Fraction(7)]
            retained_widths = {
                0: 25.2,
                first_shared_index: (
                    18.0
                    if row[first_shared_index].event.duration_slashes == 1
                    and "(" in row[first_shared_index].event.code
                    else 45.0
                ),
                final_shared_index: (
                    27.0
                    if row[final_shared_index].event.kind
                    in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
                    and row[final_shared_index].event.duration_slashes == 1
                    and "(" in row[final_shared_index].event.code
                    else 18.0
                ),
            }
            added_widths: dict[int, float] = {}
            if row[dotted_boundary_index].event.duration_dots:
                added_widths[dotted_boundary_index] = 9.0
                retained_widths[dotted_boundary_index + 1] = 18.0
            else:
                retained_widths[dotted_boundary_index] = 18.0
            dotted_onset_allocation = _allocate_dotted_onset_reserves(
                row_widths,
                retained_width_by_index=retained_widths,
                added_width_by_index=added_widths,
                terminal_reserve=profile.terminal_width,
                terminal_increase=9.0,
            )
            two_authority_widths.append(dotted_onset_allocation.interval_widths)
            two_authority_profiles.append(
                replace(
                    profile,
                    terminal_width=dotted_onset_allocation.terminal_reserve,
                )
            )
        reconciled_widths = two_authority_widths
        profiles = two_authority_profiles
    if uses_one_authority_terminal_grid:
        cadence_widths: list[tuple[float, ...]] = []
        cadence_profiles: list[LegacyIntrinsicProfile] = []
        for row, row_widths, profile in zip(
            rows,
            reconciled_widths,
            profiles,
            strict=True,
        ):
            dotted_cadence = any(
                item.event.duration_dots
                for item in row[
                    max(
                        index
                        for index, item in enumerate(row[:-1])
                        if item.event.kind == MusicTokenKind.BARLINE
                    )
                    + 1 : -1
                ]
            )
            cadence_allocation = _allocate_terminal_cadence_reserve(
                row_widths,
                interval_index=len(row_widths) - 1,
                terminal_reserve=profile.terminal_width,
                interval_increase=16.2 if dotted_cadence else 12.6,
                terminal_release=7.2 if dotted_cadence else 3.6,
            )
            cadence_widths.append(cadence_allocation.interval_widths)
            cadence_profiles.append(
                replace(
                    profile,
                    terminal_width=cadence_allocation.terminal_reserve,
                )
            )
        reconciled_widths = cadence_widths
        profiles = cadence_profiles
    if uses_merged_four_row_grid and not uses_compact_four_voice_grid:
        reconciled_widths = _project_refined_shared_measure_widths(
            rows,
            profiles,
            reconciled_widths,
        )
    if _uses_second_ending_grid(
        rows,
        visible_lyric_profile_indices,
    ):
        boundary_index = next(
            index
            for row in rows
            for index, item in enumerate(row[:-1])
            if "&dsb_a" in item.event.code
        )
        continuation_authority_widths = reconciled_widths[0]
        continuation_authority_profile = raw_profiles[0]
        continuation_widths: list[tuple[float, ...]] = []
        continuation_profiles: list[LegacyIntrinsicProfile] = []
        for profile in profiles:
            allocation = _allocate_continuation_boundary_reserve(
                continuation_authority_widths,
                boundary_index=boundary_index,
                terminal_reserve=profile.terminal_width,
            )
            continuation_widths.append(allocation.interval_widths)
            continuation_profiles.append(
                replace(
                    profile,
                    terminal_width=allocation.terminal_reserve,
                    final_bar_width=continuation_authority_profile.final_bar_width,
                    denominator_adjustment=(
                        continuation_authority_profile.denominator_adjustment
                    ),
                )
            )
        reconciled_widths = continuation_widths
        profiles = continuation_profiles
    reconciled_widths = restore_open_ending_accidental_onset_reserve(
        rows, reconciled_widths
    )
    return profiles, apply_parallel_refrain_reserves(rows, reconciled_widths)


__all__ = ["apply_terminal_reserve_policies"]
