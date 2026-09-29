"""Candidate selection and early rejection for shared-system layout."""

from __future__ import annotations

from types import MappingProxyType

from ....parser.ast import MusicTokenKind
from ..profiles import SystemAnchorProfile
from ..rows.row_signatures import (
    shared_measure_durations_match,
    shared_row_rhythm_signature,
)
from .models import SharedSystemAdmission, SharedSystemRequest


def admit_shared_system(request: SharedSystemRequest) -> SharedSystemAdmission | None:
    """Decide whether a system may use the shared (grid-owned) layout at all.

    Groups events into per-voice rows, then rejects systems that cannot be aligned
    on one measure grid — most importantly voices that carry lyric text but no music
    events of their own (their lyrics have no row to align against). Lyric-only
    voices with *empty* metadata are tolerated. Returns the admission record (rows,
    voice rows, grace/anchor flags) plus a None classification on rejection; the
    caller falls back to per-voice legacy layout in that case."""
    rows_by_voice: dict[int, dict[int, list]] = {}
    for item in request.events:
        rows_by_voice.setdefault(item.voice, {}).setdefault(item.line, []).append(item)
    active_voices = set(rows_by_voice)
    # Lyric-only voices (no music events) can carry empty lyric metadata; only
    # absent voices that actually carry lyric text block the shared grid, since
    # those lyrics cannot be aligned without a music row of their own.
    absent_lyric_voices = {
        voice
        for voice in (set(request.lyric_text_by_voice) - active_voices)
        if any(
            text for texts in request.lyric_text_by_voice[voice].values() for text in texts
        )
    }
    if absent_lyric_voices:
        return None
    candidate_rows = [
        list(row) for voice_rows in rows_by_voice.values() for row in voice_rows.values()
    ]
    candidate_bar_counts = {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row)
        for row in candidate_rows
    }
    allows_absent_lyric_metadata = (
        len(candidate_rows) == 3
        and len(candidate_bar_counts) == 1
        and min(candidate_bar_counts, default=0) >= 2
        and not shared_measure_durations_match(candidate_rows)
    ) or (
        len(candidate_rows) == 4
        and len(candidate_bar_counts) == 1
        and min(candidate_bar_counts, default=0) >= 2
        and shared_measure_durations_match(candidate_rows)
        and len({len(row) for row in candidate_rows}) == 1
    )
    allows_two_voice_unequal_slot_grid = (
        request.system_row_count == 2
        and len(candidate_rows) == 2
        and len({len(row) for row in candidate_rows}) > 1
        and len(candidate_bar_counts) == 1
        and min(candidate_bar_counts, default=0) >= 2
        and len({row[0].x for row in candidate_rows}) == 1
        and shared_measure_durations_match(candidate_rows)
        and not any(
            text
            for text_map in request.lyric_text_by_voice.values()
            for text in text_map.values()
        )
    )
    if absent_lyric_voices and not allows_absent_lyric_metadata:
        return None
    lyric_text_by_voice = {
        voice: text
        for voice, text in request.lyric_text_by_voice.items()
        if voice in active_voices
    }
    lyric_gap_by_voice = {
        voice: gaps
        for voice, gaps in request.lyric_gap_by_voice.items()
        if voice in active_voices
    }
    uses_mixed_note_origins = any(
        row[0].x != request.left
        for voice_rows in rows_by_voice.values()
        for row in voice_rows.values()
    )
    common_origin_rows_by_voice = {
        voice: voice_rows
        for voice, voice_rows in rows_by_voice.items()
        if all(row[0].x == request.left for row in voice_rows.values())
    }
    common_origin_has_lyric_authority = any(
        voice in common_origin_rows_by_voice
        and any(text for texts in lyric_text.values() for text in texts)
        for voice, lyric_text in lyric_text_by_voice.items()
    )
    all_candidate_rows = [
        row for voice_rows in rows_by_voice.values() for row in voice_rows.values()
    ]
    bar_counts = {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row)
        for row in all_candidate_rows
    }
    visible_lyric_row_count = sum(
        any(
            text
            for item in row
            for text in lyric_text_by_voice.get(voice, {}).get(
                (item.event.span.start.line, item.event.index), ()
            )
        )
        for voice, voice_rows in rows_by_voice.items()
        for row in voice_rows.values()
    )
    is_four_single_row_system = (
        len(rows_by_voice) == 4
        and len(all_candidate_rows) == 4
        and all(len(voice_rows) == 1 for voice_rows in rows_by_voice.values())
        and len(bar_counts) == 1
        and min(bar_counts, default=0) >= 2
    )
    mixed_origin_four_voice_grid = (
        uses_mixed_note_origins
        and is_four_single_row_system
        and sum(row[0].x != request.left for row in all_candidate_rows) == 1
        and all_candidate_rows[0][0].x != request.left
        and shared_measure_durations_match(all_candidate_rows, ignore_dsb_placeholders=True)
        and visible_lyric_row_count >= 1
    )
    anchor_profile = SystemAnchorProfile(
        left=request.left,
        row_origins=tuple(row[0].x for row in all_candidate_rows),
        first_onset_grace_widths=tuple(
            7.0
            * sum(
                character in "1234567"
                for character in request.grace_raw_by_voice.get(row[0].voice, {}).get(
                    row[0].event.index, ""
                )
            )
            for row in all_candidate_rows
        ),
    )
    first_onset_grace_anchor_width = anchor_profile.shared_first_onset_grace_width
    uses_shared_first_onset_grace_anchor = (
        uses_mixed_note_origins
        and first_onset_grace_anchor_width > 0.0
        and is_four_single_row_system
        and shared_measure_durations_match(all_candidate_rows)
        and visible_lyric_row_count >= 1
    )
    if (
        uses_mixed_note_origins
        and common_origin_has_lyric_authority
        and not (mixed_origin_four_voice_grid or uses_shared_first_onset_grace_anchor)
    ):
        rows_by_voice = common_origin_rows_by_voice
        lyric_text_by_voice = {
            voice: text for voice, text in lyric_text_by_voice.items() if voice in rows_by_voice
        }
        lyric_gap_by_voice = {
            voice: gaps for voice, gaps in lyric_gap_by_voice.items() if voice in rows_by_voice
        }
    if not set(lyric_text_by_voice) <= set(rows_by_voice):
        return None
    voice_rows = [list(rows_by_voice[voice].values()) for voice in sorted(rows_by_voice)]
    uses_merged_four_row_grid = False
    uses_leading_two_voice_grid = False
    if any(len(rows) != 1 for rows in voice_rows):
        leading_rows = [rows[0] for rows in voice_rows if rows]
        system_rows = [row for rows in voice_rows for row in rows]
        uses_merged_four_row_grid = (
            len(system_rows) == 4
            and sorted(len(rows) for rows in voice_rows) == [1, 1, 2]
            and shared_measure_durations_match(system_rows)
        )
        uses_leading_two_voice_grid = (
            len(voice_rows) == 2
            and sorted(len(rows) for rows in voice_rows) == [1, 2]
            and len(leading_rows) == 2
            and shared_measure_durations_match(leading_rows)
        )
        if not (uses_merged_four_row_grid or uses_leading_two_voice_grid):
            return None
        rows = system_rows if uses_merged_four_row_grid else leading_rows
    else:
        rows = [rows[0] for rows in voice_rows]
    if (
        uses_mixed_note_origins
        and not uses_shared_first_onset_grace_anchor
        and len({shared_row_rhythm_signature(row) for row in rows}) == 1
        and not any("'p:" in item.event.code for row in rows for item in row)
    ):
        return None
    frozen_lyric_text = MappingProxyType(
        {
            voice: MappingProxyType(dict(text_by_event))
            for voice, text_by_event in lyric_text_by_voice.items()
        }
    )
    frozen_lyric_gaps = MappingProxyType(
        {
            voice: MappingProxyType(dict(gap_by_event))
            for voice, gap_by_event in lyric_gap_by_voice.items()
        }
    )
    frozen_graces = MappingProxyType(
        {
            voice: MappingProxyType(dict(raw_by_event))
            for voice, raw_by_event in request.grace_raw_by_voice.items()
        }
    )
    return SharedSystemAdmission(
        rows=tuple(rows),
        voice_rows=tuple(voice_rows),
        lyric_text_by_voice=frozen_lyric_text,
        lyric_gap_by_voice=frozen_lyric_gaps,
        grace_raw_by_voice=frozen_graces,
        allows_two_voice_unequal_slot_grid=allows_two_voice_unequal_slot_grid,
        uses_mixed_note_origins=uses_mixed_note_origins,
        mixed_origin_four_voice_grid=mixed_origin_four_voice_grid,
        uses_shared_first_onset_grace_anchor=uses_shared_first_onset_grace_anchor,
        first_onset_grace_anchor_width=first_onset_grace_anchor_width,
        uses_merged_four_row_grid=uses_merged_four_row_grid,
        uses_leading_two_voice_grid=uses_leading_two_voice_grid,
    )


__all__ = ["admit_shared_system"]
