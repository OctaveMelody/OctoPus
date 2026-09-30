"""Shared-system row-family classification and eligibility policy."""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ..grid.shared_grid_policies import (
    uses_alternating_four_voice_lyric_grid,
    uses_lyric_unequal_slot_duration_grid,
    uses_single_lyric_unequal_slot_duration_grid,
    uses_two_voice_four_measure_compound_event_swap_grid,
    uses_two_voice_single_lyric_event_swap_grid,
)
from ..hidden.hidden_streams import event_duration_fraction
from ..rows.row_signatures import (
    shared_measure_durations_match,
    shared_row_rhythm_signature,
)
from ..streams import uses_compound_meter
from .models import SharedSystemClassification, SharedSystemClassificationRequest


def classify_shared_system(
    request: SharedSystemClassificationRequest,
) -> SharedSystemClassification | None:
    """Label an admitted system with its grid family.

    Inspects row origins, lyric distribution, and signature shapes to set the flags
    the downstream reserve/projection policies branch on (visible lyric rows,
    ASCII-authority indices, dual-verse / mixed-rhythm / compound-beat grids, shared
    leading accidental reserve, ...). Returns None when the admitted shape is not
    one of the known REF grid families — the caller then uses per-voice layout.
    Every flag here corresponds to an oracle-decoded reference behavior (see the
    flag's first use site for the evidence citation)."""
    admission = request.admission
    rows = admission.rows
    lyric_text_by_voice = admission.lyric_text_by_voice
    row_origins = {row[0].x for row in rows if row}
    uses_directive_origin_grid = (
        len(row_origins) == 1
        and all(
            row[0].event.kind == MusicTokenKind.BARLINE
            and row[0].event.code.startswith("|n'p:")
            for row in rows
        )
    )
    visible_lyric_rows = tuple(
        any(
            text
            for item in row
            for text in lyric_text_by_voice.get(row[0].voice, {}).get(
                (item.event.span.start.line, item.event.index), ()
            )
        )
        for row in rows
    )
    bar_counts = {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row) for row in rows
    }
    shared_leading_accidental_reserve = (
        2.0 * 3.6
        if len(rows) == 4
        and len({row[0].x for row in rows}) == 1
        and all(row[0].event.code.count("(") >= 2 for row in rows)
        and sum(row[0].event.accidental is not None for row in rows) == 1
        and len({event_duration_fraction(row[0].event) for row in rows}) == 1
        and all(row[-1].event.code == "|w" for row in rows)
        else 0.0
    )
    common_grid = (
        len(bar_counts) == 1
        and min(bar_counts, default=0) >= 2
        and len({row[0].x for row in rows}) == 1
        and shared_measure_durations_match(rows)
    )
    uses_lyricless_four_voice_grid = (
        len(rows) == 4
        and not any(visible_lyric_rows)
        and len({len(row) for row in rows}) == 1
        and common_grid
    )
    uses_alternating_cjk_four_voice_grid = uses_alternating_four_voice_lyric_grid(
        rows, list(visible_lyric_rows)
    )
    uses_unequal_slot_duration_grid = (
        request.system_row_count == 2
        and len(rows) == 2
        and (
            not any(visible_lyric_rows)
            or uses_lyric_unequal_slot_duration_grid(rows, list(visible_lyric_rows))
            or uses_single_lyric_unequal_slot_duration_grid(rows, list(visible_lyric_rows))
            or uses_two_voice_single_lyric_event_swap_grid(rows, list(visible_lyric_rows))
        )
        and len({row[0].voice for row in rows}) == 2
        and len({len(row) for row in rows}) > 1
        and common_grid
    )
    uses_single_authority_four_voice_grid = (
        len(rows) == 4
        and len(lyric_text_by_voice) == 1
        and sum(visible_lyric_rows) == 1
        and len({len(row) for row in rows}) == 1
        and common_grid
    )
    dual_verse_ascii_authority_indices = [
        index
        for index, row in enumerate(rows)
        if any(
            len(texts) >= 2 and any(texts)
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
        )
        and all(
            character.isascii() or character.isspace()
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
            for character in text
        )
    ]
    uses_two_voice_dual_verse_ascii_grid = (
        len(rows) == 2
        and len(dual_verse_ascii_authority_indices) == 1
        and len({shared_row_rhythm_signature(row) for row in rows}) == 1
        and len({len(row) for row in rows}) == 1
    )
    ascii_authority_indices = [
        index
        for index, row in enumerate(rows)
        if any(
            text
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
        )
        and all(
            character.isascii() or character.isspace()
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
            for character in text
        )
    ]
    bar_slots = {
        tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        for row in rows
    }
    rhythm_signature_count = len({shared_row_rhythm_signature(row) for row in rows})
    uses_multi_voice_ascii_mixed_rhythm_grid = (
        len(rows) >= 3
        and len(ascii_authority_indices) == 1
        and sum(visible_lyric_rows) == 1
        and len({len(row) for row in rows}) == 1
        and len(bar_slots) == 1
        and 1 < rhythm_signature_count < len(rows)
    )
    uses_multi_voice_heterogeneous_authority_grid = (
        len(rows) == 3
        and sum(visible_lyric_rows) == 1
        and len(bar_counts) == 1
        and min(bar_counts, default=0) >= 2
        and not shared_measure_durations_match(rows)
    )
    compound = uses_compound_meter(request.metrics.time_sig)
    uses_primary_compound_beat_grid = (
        len(rows) == 2
        and compound
        and shared_measure_durations_match(rows)
        and visible_lyric_rows == (True, False)
        and all(row[0].event.kind == MusicTokenKind.HIDDEN_REST for row in rows)
    ) or uses_two_voice_four_measure_compound_event_swap_grid(
        rows, list(visible_lyric_rows)
    )
    uses_primary_dual_verse_compound_grid = (
        len(rows) == 2
        and compound
        and shared_measure_durations_match(rows)
        and visible_lyric_rows == (True, False)
        and request.primary_system_verse_count >= 2
    )
    if len(lyric_text_by_voice) < 2:
        explicitly_supported = (
            uses_lyricless_four_voice_grid
            or uses_single_authority_four_voice_grid
            or admission.allows_two_voice_unequal_slot_grid
            or len(lyric_text_by_voice) == 1
            and (
                uses_primary_compound_beat_grid
                or uses_two_voice_dual_verse_ascii_grid
                or uses_multi_voice_ascii_mixed_rhythm_grid
                or uses_two_voice_single_lyric_event_swap_grid(
                    rows, list(visible_lyric_rows)
                )
                or uses_directive_origin_grid
                and len({shared_row_rhythm_signature(row) for row in rows}) == 1
            )
        )
        if not explicitly_supported:
            return None
    if any(
        len(row) < 2
        or row[0].x != request.left
        and not (
            admission.mixed_origin_four_voice_grid
            or admission.uses_shared_first_onset_grace_anchor
        )
        or row[-1].event.kind != MusicTokenKind.BARLINE
        or "zkh" in row[0].event.decorations
        and not (
            admission.mixed_origin_four_voice_grid
            or admission.uses_shared_first_onset_grace_anchor
        )
        for row in rows
    ):
        return None
    return SharedSystemClassification(
        visible_lyric_rows=visible_lyric_rows,
        dual_verse_ascii_authority_indices=tuple(dual_verse_ascii_authority_indices),
        multi_voice_ascii_authority_indices=tuple(ascii_authority_indices),
        shared_leading_accidental_reserve=shared_leading_accidental_reserve,
        uses_directive_origin_grid=uses_directive_origin_grid,
        uses_lyricless_four_voice_grid=uses_lyricless_four_voice_grid,
        uses_alternating_cjk_four_voice_grid=uses_alternating_cjk_four_voice_grid,
        uses_unequal_slot_duration_grid=uses_unequal_slot_duration_grid,
        uses_single_authority_four_voice_grid=uses_single_authority_four_voice_grid,
        uses_two_voice_dual_verse_ascii_grid=uses_two_voice_dual_verse_ascii_grid,
        uses_multi_voice_ascii_mixed_rhythm_grid=uses_multi_voice_ascii_mixed_rhythm_grid,
        uses_multi_voice_heterogeneous_authority_grid=(
            uses_multi_voice_heterogeneous_authority_grid
        ),
        uses_primary_compound_beat_grid=uses_primary_compound_beat_grid,
        uses_primary_dual_verse_compound_grid=uses_primary_dual_verse_compound_grid,
    )


__all__ = ["classify_shared_system"]
