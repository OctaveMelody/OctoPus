"""Post-authority reserve sharing before terminal reconciliation."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from re_tomato.render.layout_engine.grid.shared_grid_policies import (
    uses_compound_tied_grace_beat_expiry as _uses_compound_tied_grace_beat_expiry,
)
from re_tomato.render.layout_engine.grid.shared_grid_policies import (
    uses_single_lyric_compound_grid as _uses_single_lyric_compound_grid,
)
from re_tomato.render.layout_engine.grid.shared_grid_policies import (
    uses_two_voice_four_measure_compound_event_swap_grid,
)
from re_tomato.render.layout_engine.rows.row_signatures import (
    shared_row_rhythm_signature as _shared_row_rhythm_signature,
)
from re_tomato.render.layout_engine.rows.sparse_onsets import (
    align_sparse_compound_measure_onsets as _align_sparse_compound_measure_onsets,
)

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent, PageMetrics
from ..hidden.hidden_streams import event_duration_fraction
from ..intrinsic.builder import (
    _has_fullwidth_trailing_punctuation,
)
from ..intrinsic.builder import (
    build_legacy_intrinsic_profile as _legacy_intrinsic_profile,
)
from ..intrinsic.widths import _inside_dsb_block
from ..lyrics.lyric_authority import (
    reconcile_single_lyric_authority_grid as _reconcile_single_lyric_authority_grid,
)
from ..profiles import LegacyIntrinsicProfile
from ..reserves.five_measure_reserves import (
    apply_five_measure_shared_reserves as _apply_five_measure_shared_reserves,
)
from .models import LyricTextByVoice


def apply_post_authority_reserves(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    raw_profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    visible_lyric_rows: list[bool],
    visible_lyric_profile_indices: list[int],
    dual_verse_ascii_authority_indices: tuple[int, ...],
    multi_voice_ascii_authority_indices: tuple[int, ...],
    uses_primary_compound_beat_grid: bool,
    uses_primary_lyric_parallel_grid: bool,
    uses_five_measure_shared_grid: bool,
    uses_compact_four_voice_grid: bool,
    uses_single_lyric_rhythm_grid: bool,
    uses_two_voice_dual_verse_ascii_grid: bool,
    uses_multi_voice_ascii_mixed_rhythm_grid: bool,
    uses_primary_ascii_dual_verse_dsb_grid: bool,
    uses_compound_aligned_two_voice_lyric_grid: bool,
    uses_compound_dual_verse_lyric_profile_grid: bool,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]], bool]:
    if (
        uses_primary_compound_beat_grid
        and not uses_two_voice_four_measure_compound_event_swap_grid(
            rows, visible_lyric_rows
        )
    ):
        reconciled_widths = _align_sparse_compound_measure_onsets(
            rows,
            reconciled_widths,
        )
    if uses_primary_lyric_parallel_grid:
        reconciled_widths = [profiles[0].interval_widths for _row in rows]
    if uses_five_measure_shared_grid:
        reconciled_widths = _apply_five_measure_shared_reserves(
            rows,
            profiles,
            reconciled_widths,
            lyric_text_by_voice=lyric_text_by_voice,
            has_fullwidth_trailing_punctuation=_has_fullwidth_trailing_punctuation,
        )
    if (
        uses_compact_four_voice_grid
        and len(visible_lyric_profile_indices) == 1
        and not uses_single_lyric_rhythm_grid
    ):
        reconciled_widths = _reconcile_single_lyric_authority_grid(
            rows,
            raw_profiles,
            lyric_profile_index=visible_lyric_profile_indices[0],
            lyric_text_by_event=lyric_text_by_voice.get(
                rows[visible_lyric_profile_indices[0]][0].voice,
                {},
            ),
        ) or reconciled_widths

    aligned_bar_slots = {
        tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        for row in rows
    }
    uses_single_lyric_aligned_slot_grid = (
        len(rows) >= 3
        and len(visible_lyric_profile_indices) == 1
        and len({len(row) for row in rows}) == 1
        and len(aligned_bar_slots) == 1
        and len({_shared_row_rhythm_signature(row) for row in rows}) == len(rows)
    )
    if uses_single_lyric_aligned_slot_grid:
        authority_index = visible_lyric_profile_indices[0]
        authority_widths = list(raw_profiles[authority_index].interval_widths)
        for row, profile in zip(rows, raw_profiles, strict=True):
            for index, item in enumerate(row[: len(authority_widths)]):
                if item.event.accidental is not None and index > 0:
                    authority_widths[index - 1] = max(
                        authority_widths[index - 1],
                        profile.interval_widths[index - 1],
                    )
                extra_tie_openers = item.event.code.count("(") - 1
                if extra_tie_openers > 0:
                    authority_widths[index] += 3.6 * extra_tie_openers
        _apply_aligned_tie_reserves(
            rows,
            profiles,
            authority_widths,
            authority_index=authority_index,
        )
        reconciled_widths = [tuple(authority_widths) for _row in rows]
    if uses_two_voice_dual_verse_ascii_grid:
        authority_index = dual_verse_ascii_authority_indices[0]
        authority_row = rows[authority_index]
        authority_lyrics = dict(lyric_text_by_voice.get(authority_row[0].voice, {}))
        compact_profile = _legacy_intrinsic_profile(
            authority_row,
            metrics=metrics,
            left=left,
            lyric_text_by_event=authority_lyrics,
            compact_latin_bilingual=True,
        )
        full_profile = _legacy_intrinsic_profile(
            authority_row,
            metrics=metrics,
            left=left,
            lyric_text_by_event=authority_lyrics,
            compact_latin_bilingual=False,
        )
        authority_widths = list(compact_profile.interval_widths)
        first_bar_index = next(
            index
            for index, item in enumerate(authority_row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        for index, item in enumerate(authority_row[: len(authority_widths)]):
            if (
                index + 1 == first_bar_index
            ):
                authority_widths[index] = max(
                    authority_widths[index],
                    full_profile.interval_widths[index],
                )
            if "&dsb_a" in item.event.code:
                authority_widths[index] += 14.4
        denominator_adjustment = compact_profile.denominator_adjustment
        if (
            len(authority_row) >= 3
            and authority_row[-2].event.kind == MusicTokenKind.HIDDEN_REST
            and authority_row[-2].event.index < 0
            and authority_row[-1].block == "dsb-tail"
        ):
            authority_widths[-1] = min(authority_widths[-1], 18.0)
            denominator_adjustment -= compact_profile.terminal_width
        reconciled_widths = [tuple(authority_widths) for _row in rows]
        profiles = [
            replace(
                profile,
                terminal_width=compact_profile.terminal_width,
                final_bar_width=compact_profile.final_bar_width,
                denominator_adjustment=denominator_adjustment,
            )
            for profile in profiles
        ]
    if uses_multi_voice_ascii_mixed_rhythm_grid:
        authority_index = multi_voice_ascii_authority_indices[0]
        authority_profile = raw_profiles[authority_index]
        reconciled_widths = [
            authority_profile.interval_widths
            for _row in rows
        ]
        profiles = [
            replace(
                profile,
                terminal_width=18.0,
                final_bar_width=authority_profile.final_bar_width,
                denominator_adjustment=authority_profile.denominator_adjustment,
            )
            for profile in profiles
        ]
    if uses_primary_ascii_dual_verse_dsb_grid:
        authority_profile = raw_profiles[0]
        reconciled_widths = [authority_profile.interval_widths for _row in rows]
        profiles = [
            replace(
                profile,
                terminal_width=authority_profile.terminal_width,
                final_bar_width=authority_profile.final_bar_width,
                denominator_adjustment=authority_profile.denominator_adjustment,
            )
            for profile in profiles
        ]
    if uses_compound_aligned_two_voice_lyric_grid:
        uses_compound_tied_grace_expiry = _uses_compound_tied_grace_beat_expiry(
            rows,
            uses_primary_lyric_parallel_grid=uses_primary_lyric_parallel_grid,
            uses_compound_aligned_two_voice_lyric_grid=(
                uses_compound_aligned_two_voice_lyric_grid
            ),
        )
        adjusted_profiles = [
            _redistribute_compound_dotted_pair_reserves(
                row,
                replace(profile, interval_widths=row_interval_widths),
                preserve_terminal_tied_subdivision_reserve=(
                    uses_compound_tied_grace_expiry
                ),
                allow_terminal_parenthesized_transfer=(
                    _uses_single_lyric_compound_grid(rows, visible_lyric_rows)
                    and len(metrics.time_sig.split()) > 1
                    and not uses_compound_dual_verse_lyric_profile_grid
                ),
            )
            for row, profile, row_interval_widths in zip(
                rows,
                profiles,
                reconciled_widths,
                strict=True,
            )
        ]
        reconciled_widths = [profile.interval_widths for profile in adjusted_profiles]
        profiles = [
            replace(profile, terminal_width=adjusted.terminal_width)
            for profile, adjusted in zip(profiles, adjusted_profiles, strict=True)
        ]
    reconciled_widths, profiles = _apply_dsb_ghost_substep_reserves(
        rows,
        profiles,
        reconciled_widths,
    )
    return profiles, reconciled_widths, uses_single_lyric_aligned_slot_grid


def _apply_dsb_ghost_substep_reserves(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
) -> tuple[list[tuple[float, ...]], list[LegacyIntrinsicProfile]]:
    """Clamp the step into a DSB-closing empty placeholder to one substep.

    Oracle-verified on Hulunbuir p3 (both mid-row-DSB systems, both files):
    the reference sits the synthetic closing ghost exactly 18 natural units
    after the fragment's last note instead of carrying that note's base step
    plus accidental reserve.  The suppressed width is carried to the row's
    denominator adjustment so the system total — and therefore every other
    column and the scale — is preserved; only the closing cluster moves.
    Rows whose grid policy already owns this clamp (the dual-verse ascii
    branch above) see delta zero and are untouched.
    """
    for row_index, row in enumerate(rows):
        widths = list(reconciled_widths[row_index])
        carry = 0.0
        for index in range(min(len(widths), len(row) - 2)):
            next_item = row[index + 1]
            if (
                next_item.event.kind == MusicTokenKind.HIDDEN_REST
                and next_item.event.index < 0
                and _inside_dsb_block(row, index + 1)
            ):
                delta = widths[index] - 18.0
                if delta > 0.0:
                    widths[index] = 18.0
                    carry += delta
        if carry > 0.0:
            reconciled_widths[row_index] = tuple(widths)
            profiles[row_index] = replace(
                profiles[row_index],
                denominator_adjustment=profiles[row_index].denominator_adjustment
                + carry,
            )
    return reconciled_widths, profiles


def _apply_aligned_tie_reserves(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    authority_widths: list[float],
    *,
    authority_index: int,
) -> None:
    """Preserve parallel tie ownership in a single-lyric aligned-slot grid."""

    for index in range(min(len(authority_widths), *(len(row) - 1 for row in rows))):
        tie_starters = tuple(
            row_index
            for row_index, row in enumerate(rows)
            if _event_starts_construct(row[index], "tie")
        )
        if len(tie_starters) == len(rows):
            intrinsic_width = max(profile.interval_widths[index] for profile in profiles)
            authority_widths[index] = max(authority_widths[index], intrinsic_width)
        elif (
            len(tie_starters) == len(rows) - 1
            and authority_index not in tie_starters
            and _event_starts_construct(rows[authority_index][index], "slur")
        ):
            authority_widths[index] += 9.0


def _event_starts_construct(item: LayoutEvent, construct: str) -> bool:
    return any(
        f":{construct}:" in role and role.endswith(":start")
        for role in item.event.construct_roles
    )


def _uses_terminal_tied_subdivision_reserve(row: list[LayoutEvent]) -> bool:
    """Recognize a tied beat followed by two untied half-beat subdivisions."""
    if len(row) < 5:
        return False
    first, second, third, fourth, closing = row[-5:]
    return (
        event_duration_fraction(first.event) == Fraction(1)
        and "~" in first.event.code
        and event_duration_fraction(second.event) == Fraction(1, 2)
        and event_duration_fraction(third.event) == Fraction(1)
        and "~" not in third.event.code
        and event_duration_fraction(fourth.event) == Fraction(1, 2)
        and closing.event.kind == MusicTokenKind.BARLINE
    )


def _redistribute_compound_dotted_pair_reserves(
    row: list[LayoutEvent],
    profile: LegacyIntrinsicProfile,
    *,
    preserve_terminal_tied_subdivision_reserve: bool = False,
    allow_terminal_parenthesized_transfer: bool = False,
) -> LegacyIntrinsicProfile:
    """Move 27.0 units from a wide dotted-pair successor cell to its opener.

    For each adjacent pair of three-half-beat (3/2) events followed by a
    barline, when the successor gap is at least 45.0 wider than the opener's,
    the opener gains 27.0 and the successor (or the terminal width, when the
    pair ends the row) loses it — the reference keeps dotted pairs visually
    tight in compound-aligned two-voice lyric grids.
    """
    interval_widths = list(profile.interval_widths)
    terminal_width = profile.terminal_width
    for index, item in enumerate(row[:-2]):
        following = row[index + 1]
        if (
            event_duration_fraction(item.event) != Fraction(3, 2)
            or event_duration_fraction(following.event) != Fraction(3, 2)
            or row[index + 2].event.kind != MusicTokenKind.BARLINE
            or index >= len(interval_widths)
        ):
            continue
        opening_width = interval_widths[index]
        if index + 1 < len(interval_widths):
            if interval_widths[index + 1] - opening_width < 45.0:
                continue
            interval_widths[index] += 27.0
            interval_widths[index + 1] -= 27.0
        elif terminal_width - opening_width >= 45.0:
            interval_widths[index] += 27.0
            terminal_width -= 27.0
    # A tied whole beat followed by two half-beat subdivisions leaves the
    # reference renderer's final reserve on the terminal side when the second
    # subdivision is not itself tied.  Keep this structural transfer confined
    # to a terminal measure so ordinary compound rows retain their profile.
    terminal_index = len(row) - 5
    if (
        not preserve_terminal_tied_subdivision_reserve
        and
        terminal_index + 1 < len(interval_widths)
        and _uses_terminal_tied_subdivision_reserve(row)
    ):
        interval_widths[terminal_index + 1] = max(
            interval_widths[terminal_index + 1] - 3.6,
            0.0,
        )
        terminal_width += 3.6
    for index in range(1, len(row) - 2):
        if (
            allow_terminal_parenthesized_transfer
            and
            row[index - 1].event.kind == MusicTokenKind.BARLINE
            and event_duration_fraction(row[index].event) == Fraction(3, 2)
            and event_duration_fraction(row[index + 1].event) == Fraction(3, 2)
            and "(" in row[index].event.code
            and ")" in row[index + 1].event.code
            and index + 2 == len(row) - 1
            and index - 1 < len(interval_widths)
            and terminal_width >= 27.0
            and (
                sum(item.event.kind == MusicTokenKind.BARLINE for item in row) >= 6
                or row[-1].event.code == "|y"
            )
        ):
            interval_widths[index - 1] += 27.0
            terminal_width -= 27.0
            break
    return replace(
        profile,
        interval_widths=tuple(interval_widths),
        terminal_width=terminal_width,
    )


__all__ = ["apply_post_authority_reserves"]
