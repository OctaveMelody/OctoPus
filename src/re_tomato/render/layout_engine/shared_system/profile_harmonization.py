"""Ordered authority selection and profile-width harmonization."""

from __future__ import annotations

from dataclasses import replace

from ...core.layout_types import LayoutEvent, PageMetrics
from ..intrinsic.builder import _has_single_cjk_lyric_anchor, build_legacy_intrinsic_profile
from ..profile_widths import share_matching_measure_profile_widths
from ..profiles import LegacyIntrinsicProfile
from ..rows.row_signatures import shared_row_rhythm_signature
from .models import LyricTextByVoice, SharedSystemAdmission, SharedSystemClassification
from .profile_building import SharedRawProfiles, build_shared_raw_profiles


def prepare_shared_profiles(
    admission: SharedSystemAdmission,
    classification: SharedSystemClassification,
    *,
    metrics: PageMetrics,
    left: float,
) -> tuple[SharedRawProfiles, list[LegacyIntrinsicProfile], bool]:
    rows = list(admission.rows)
    raw = build_shared_raw_profiles(
        rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=admission.lyric_text_by_voice,
        lyric_gap_by_voice=admission.lyric_gap_by_voice,
        visible_lyric_rows=list(classification.visible_lyric_rows),
        uses_primary_compound_beat_grid=classification.uses_primary_compound_beat_grid,
        uses_primary_dual_verse_compound_grid=(
            classification.uses_primary_dual_verse_compound_grid
        ),
        uses_directive_origin_grid=classification.uses_directive_origin_grid,
        uses_mixed_note_origins=admission.uses_mixed_note_origins,
    )
    profiles = list(raw.profiles)
    profiles, uses_single_lyric_rhythm_grid = harmonize_shared_profiles(
        rows,
        profiles,
        list(profiles),
        metrics=metrics,
        left=left,
        lyric_text_by_voice=admission.lyric_text_by_voice,
        visible_lyric_rows=list(classification.visible_lyric_rows),
        uses_alternating_cjk_four_voice_grid=(
            classification.uses_alternating_cjk_four_voice_grid
        ),
        uses_multi_voice_heterogeneous_authority_grid=(
            classification.uses_multi_voice_heterogeneous_authority_grid
        ),
        mixed_origin_four_voice_grid=admission.mixed_origin_four_voice_grid,
        uses_compact_four_voice_grid=raw.policy.uses_compact_four_voice_grid,
        uses_parallel_two_voice_lyric_grid=raw.policy.uses_parallel_two_voice_lyric_grid,
    )
    return raw, profiles, uses_single_lyric_rhythm_grid


def harmonize_shared_profiles(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    raw_profiles: list[LegacyIntrinsicProfile],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    visible_lyric_rows: list[bool],
    uses_alternating_cjk_four_voice_grid: bool,
    uses_multi_voice_heterogeneous_authority_grid: bool,
    mixed_origin_four_voice_grid: bool,
    uses_compact_four_voice_grid: bool,
    uses_parallel_two_voice_lyric_grid: bool,
) -> tuple[list[LegacyIntrinsicProfile], bool]:
    if uses_alternating_cjk_four_voice_grid:
        _add_cjk_authority_reserves(
            rows, profiles, metrics=metrics, lyric_text_by_voice=lyric_text_by_voice
        )
    if uses_multi_voice_heterogeneous_authority_grid:
        authority_index = next(
            index for index, visible in enumerate(visible_lyric_rows) if visible
        )
        profiles[authority_index] = _compact_authority_profile(
            rows[authority_index],
            raw_profiles[authority_index],
            metrics=metrics,
            left=left,
        )
    mixed_origin_authority_index = (
        next(index for index, row in enumerate(rows) if row[0].x != left)
        if mixed_origin_four_voice_grid
        else None
    )
    if mixed_origin_authority_index is not None:
        profiles[mixed_origin_authority_index] = _compact_authority_profile(
            rows[mixed_origin_authority_index],
            raw_profiles[mixed_origin_authority_index],
            metrics=metrics,
            left=left,
        )
    uses_single_lyric_rhythm_grid = False
    if uses_compact_four_voice_grid:
        profiles, uses_single_lyric_rhythm_grid = _harmonize_compact_rhythm_profiles(
            rows,
            profiles,
            lyric_text_by_voice=lyric_text_by_voice,
        )
    profiles = share_matching_measure_profile_widths(rows, profiles)
    if mixed_origin_authority_index is not None:
        profiles[mixed_origin_authority_index] = _compact_authority_profile(
            rows[mixed_origin_authority_index],
            raw_profiles[mixed_origin_authority_index],
            metrics=metrics,
            left=left,
        )
    if uses_parallel_two_voice_lyric_grid:
        _transfer_parallel_accidental_excess(rows, profiles, raw_profiles)
    return profiles, uses_single_lyric_rhythm_grid


def _add_cjk_authority_reserves(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    *,
    metrics: PageMetrics,
    lyric_text_by_voice: LyricTextByVoice,
) -> None:
    for index, row in enumerate(rows):
        lyric_text_by_event = lyric_text_by_voice.get(row[0].voice, {})
        if not any(lyric_text_by_event.values()):
            continue
        interval_widths = list(profiles[index].interval_widths)
        for event_index, item in enumerate(row[:-1]):
            texts = lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index), ()
            )
            if _has_single_cjk_lyric_anchor(texts) and event_index < len(interval_widths):
                interval_widths[event_index] += metrics.lyric_size / 2.0
        profiles[index] = replace(profiles[index], interval_widths=tuple(interval_widths))


def _compact_authority_profile(
    row: list[LayoutEvent],
    raw_profile: LegacyIntrinsicProfile,
    *,
    metrics: PageMetrics,
    left: float,
) -> LegacyIntrinsicProfile:
    compact = build_legacy_intrinsic_profile(
        row, metrics=metrics, left=left, lyric_text_by_event={}
    )
    lyric_reserve = sum(raw_profile.interval_widths) - sum(compact.interval_widths)
    compact_widths = list(compact.interval_widths)
    if compact_widths and lyric_reserve > 0:
        compact_widths[-1] += lyric_reserve
    return replace(compact, interval_widths=tuple(compact_widths))


def _harmonize_compact_rhythm_profiles(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    *,
    lyric_text_by_voice: LyricTextByVoice,
) -> tuple[list[LegacyIntrinsicProfile], bool]:
    signatures = [shared_row_rhythm_signature(row) for row in rows]
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
    uses_single_lyric_rhythm_grid = len(visible_indices) == 1 and len(set(signatures)) == 1
    single_widths = (
        _single_lyric_accidental_widths(rows, profiles, visible_indices[0])
        if uses_single_lyric_rhythm_grid
        else None
    )
    for signature in set(signatures):
        matching = [index for index, value in enumerate(signatures) if value == signature]
        if len(matching) < 2:
            continue
        lyric_profile_index = next(
            (index for index in visible_indices if index in matching), None
        )
        shared_widths = (
            profiles[lyric_profile_index].interval_widths
            if lyric_profile_index is not None and len(visible_indices) == 1
            else tuple(
                max(profiles[index].interval_widths[position] for index in matching)
                for position in range(len(profiles[matching[0]].interval_widths))
            )
        )
        for index in matching:
            profiles[index] = replace(profiles[index], interval_widths=shared_widths)
    if single_widths is not None:
        profiles = [
            replace(profile, interval_widths=single_widths, terminal_width=18.0)
            for profile in profiles
        ]
    return profiles, uses_single_lyric_rhythm_grid


def _single_lyric_accidental_widths(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    lyric_index: int,
) -> tuple[float, ...]:
    widths = list(profiles[lyric_index].interval_widths)
    lyric_row = rows[lyric_index]
    suppressed: set[int] = set()
    for index, item in enumerate(lyric_row[:-2]):
        if item.event.accidental != "$":
            continue
        trailing = (
            index + 1
            if item.event.duration_slashes
            and index + 1 < len(lyric_row) - 1
            and "(" in lyric_row[index + 1].event.code
            else index
        )
        widths[trailing] -= 3.6
        suppressed.add(trailing)
    reserve_positions: set[int] = set()
    for row in rows:
        for index, item in enumerate(row[:-1]):
            if index == 0 or item.event.accidental is None:
                continue
            reserve_positions.add(index - 1)
            if item.event.accidental == "$":
                continue
            trailing = (
                index + 1
                if item.event.duration_slashes
                and index + 1 < len(row) - 1
                and "(" in row[index + 1].event.code
                else index
            )
            if trailing not in suppressed:
                reserve_positions.add(trailing)
    for position in reserve_positions:
        widths[position] = max(profile.interval_widths[position] for profile in profiles)
    return tuple(widths)


def _transfer_parallel_accidental_excess(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    raw_profiles: list[LegacyIntrinsicProfile],
) -> None:
    for voice_index, row in enumerate(rows):
        adjusted = list(profiles[voice_index].interval_widths)
        for index, item in enumerate(row[:-2]):
            if (
                item.event.accidental is None
                and any(
                    other_row[index].event.accidental is not None
                    and other_row[index].event.duration_slashes
                    for other_index, other_row in enumerate(rows)
                    if other_index != voice_index and index < len(other_row)
                )
                and index + 1 < len(adjusted)
            ):
                trailing_excess = adjusted[index] - raw_profiles[voice_index].interval_widths[index]
                if trailing_excess > 0:
                    adjusted[index] -= trailing_excess
                    adjusted[index + 1] += trailing_excess
        profiles[voice_index] = replace(
            profiles[voice_index], interval_widths=tuple(adjusted)
        )


__all__ = ["harmonize_shared_profiles", "prepare_shared_profiles"]
