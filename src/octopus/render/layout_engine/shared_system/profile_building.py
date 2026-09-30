"""Raw intrinsic-profile construction for admitted shared rows."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent, PageMetrics
from ..grid.grid_classifiers import uses_shifted_voice_measure_grid
from ..grid.shared_grid_policies import uses_single_lyric_compound_grid
from ..hidden.hidden_streams import event_duration_fraction
from ..intrinsic.builder import (
    _has_fullwidth_trailing_punctuation,
    build_legacy_intrinsic_profile,
)
from ..profiles import LegacyIntrinsicProfile
from ..reserves.compound_reserves import (
    apply_compound_beat_boundary_reserves,
)
from ..rows.row_signatures import (
    shared_measure_durations_match,
    shared_row_rhythm_signature,
)
from ..streams import uses_compound_meter
from .models import LyricGapByVoice, LyricTextByVoice

_ACCIDENTAL_RESERVE = 3.6


@dataclass(frozen=True)
class SharedRawProfilePolicy:
    row_count: int
    uses_five_measure_grid: bool
    uses_shifted_voice_grid: bool
    uses_compact_four_voice_grid: bool
    uses_parallel_two_voice_lyric_grid: bool
    uses_compound_aligned_two_voice_lyric_grid: bool
    uses_primary_compound_beat_grid: bool
    uses_primary_dual_verse_compound_grid: bool
    uses_directive_origin_grid: bool
    uses_mixed_note_origins: bool


@dataclass(frozen=True)
class SharedRawProfiles:
    profiles: tuple[LegacyIntrinsicProfile, ...]
    punctuation_indices_by_row: tuple[frozenset[int], ...]
    terminal_punctuation_by_row: tuple[bool, ...]
    skip_indices_by_row: tuple[frozenset[int], ...]
    skip_connector_indices_by_row: tuple[frozenset[int], ...]
    policy: SharedRawProfilePolicy


def build_shared_raw_profiles(
    rows: list[list[LayoutEvent]],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    lyric_gap_by_voice: LyricGapByVoice,
    visible_lyric_rows: list[bool],
    uses_primary_compound_beat_grid: bool,
    uses_primary_dual_verse_compound_grid: bool,
    uses_directive_origin_grid: bool,
    uses_mixed_note_origins: bool,
) -> SharedRawProfiles:
    policy = _classify_raw_profile_policy(
        rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
        visible_lyric_rows=visible_lyric_rows,
        uses_primary_compound_beat_grid=uses_primary_compound_beat_grid,
        uses_primary_dual_verse_compound_grid=uses_primary_dual_verse_compound_grid,
        uses_directive_origin_grid=uses_directive_origin_grid,
        uses_mixed_note_origins=uses_mixed_note_origins,
    )
    profiles: list[LegacyIntrinsicProfile] = []
    punctuation: list[frozenset[int]] = []
    terminal_punctuation: list[bool] = []
    skips: list[frozenset[int]] = []
    connector_skips: list[frozenset[int]] = []
    # Rows that share barline columns with sibling rows keep the plain
    # note-to-barline step under dynamic/ornament marks (oracle probes E1-E3);
    # single-row syllabic layouts use the base model instead (full 27.0 unless
    # a rest precedes the decorated note).
    shares_barline_columns = len(rows) > 1
    for row_index, row in enumerate(rows):
        result = _build_row_profile(
            row,
            metrics=metrics,
            left=left,
            lyric_text_by_event=dict(lyric_text_by_voice.get(row[0].voice, {})),
            lyric_gap_by_event=dict(lyric_gap_by_voice.get(row[0].voice, {})),
            policy=policy,
            is_primary=row_index == 0,
            shares_barline_columns=shares_barline_columns,
        )
        profiles.append(result[0])
        punctuation.append(result[1])
        terminal_punctuation.append(result[2])
        skips.append(result[3])
        connector_skips.append(result[4])
    return SharedRawProfiles(
        profiles=tuple(profiles),
        punctuation_indices_by_row=tuple(punctuation),
        terminal_punctuation_by_row=tuple(terminal_punctuation),
        skip_indices_by_row=tuple(skips),
        skip_connector_indices_by_row=tuple(connector_skips),
        policy=policy,
    )


def _classify_raw_profile_policy(
    rows: list[list[LayoutEvent]],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    visible_lyric_rows: list[bool],
    uses_primary_compound_beat_grid: bool,
    uses_primary_dual_verse_compound_grid: bool,
    uses_directive_origin_grid: bool,
    uses_mixed_note_origins: bool,
) -> SharedRawProfilePolicy:
    uses_five_measure_grid = len(rows) >= 4 and all(
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row) >= 5
        and row[-1].event.code == "|"
        for row in rows
    )
    uses_parallel_two_voice_lyric_grid = (
        len(rows) == 2
        and len({shared_row_rhythm_signature(row) for row in rows}) == 1
        and all(
            any(
                text
                for item in row
                for text in lyric_text_by_voice.get(row[0].voice, {}).get(
                    (item.event.span.start.line, item.event.index), ()
                )
            )
            for row in rows
        )
    )
    uses_compound_aligned_two_voice_lyric_grid = (
        len(rows) == 2
        and uses_compound_meter(metrics.time_sig)
        and shared_measure_durations_match(rows)
        and (
            all(
                any(
                    text
                    for item in row
                    for text in lyric_text_by_voice.get(row[0].voice, {}).get(
                        (item.event.span.start.line, item.event.index), ()
                    )
                )
                for row in rows
            )
            or uses_single_lyric_compound_grid(rows, visible_lyric_rows)
        )
    )
    return SharedRawProfilePolicy(
        row_count=len(rows),
        uses_five_measure_grid=uses_five_measure_grid,
        uses_shifted_voice_grid=uses_shifted_voice_measure_grid(rows),
        uses_compact_four_voice_grid=len(rows) == 4 and left == 83.0,
        uses_parallel_two_voice_lyric_grid=uses_parallel_two_voice_lyric_grid,
        uses_compound_aligned_two_voice_lyric_grid=uses_compound_aligned_two_voice_lyric_grid,
        uses_primary_compound_beat_grid=uses_primary_compound_beat_grid,
        uses_primary_dual_verse_compound_grid=uses_primary_dual_verse_compound_grid,
        uses_directive_origin_grid=uses_directive_origin_grid,
        uses_mixed_note_origins=uses_mixed_note_origins,
    )


def _build_row_profile(
    row: list[LayoutEvent],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
    lyric_gap_by_event: dict[tuple[int, int], int],
    policy: SharedRawProfilePolicy,
    is_primary: bool,
    shares_barline_columns: bool = False,
) -> tuple[LegacyIntrinsicProfile, frozenset[int], bool, frozenset[int], frozenset[int]]:
    profile = build_legacy_intrinsic_profile(
        row,
        metrics=metrics,
        left=left,
        lyric_text_by_event=lyric_text_by_event,
        shares_barline_columns=shares_barline_columns,
    )
    if policy.uses_primary_compound_beat_grid and is_primary:
        profile = apply_compound_beat_boundary_reserves(row, profile)
    interval_widths = list(profile.interval_widths)
    if policy.uses_primary_dual_verse_compound_grid and not is_primary:
        _apply_dual_verse_compound_accidental_tail_reserve(row, interval_widths)
    for index, item in enumerate(row[1:-2], start=1):
        if (
            item.event.accidental == "#"
            and item.event.duration_slashes == 1
            and row[index - 1].event.pitch == 3
            and row[index - 1].event.duration_slashes == 1
            and row[index + 1].event.pitch == 3
            and row[index + 1].event.duration_slashes == 1
        ):
            interval_widths[index] -= 3.6
            interval_widths[index + 1] += 3.6
    punctuation_indices: set[int] = set()
    skip_indices: set[int] = set()
    skip_connector_indices: set[int] = set()
    aligned_punctuation_transfer = 0.0
    for index in range(len(interval_widths)):
        texts = lyric_text_by_event.get(
            (row[index].event.span.start.line, row[index].event.index), ()
        )
        previous_texts = (
            lyric_text_by_event.get(
                (row[index - 1].event.span.start.line, row[index - 1].event.index), ()
            )
            if index > 0
            else ()
        )
        next_texts = lyric_text_by_event.get(
            (row[index + 1].event.span.start.line, row[index + 1].event.index), ()
        )
        if (
            policy.uses_primary_dual_verse_compound_grid
            and row[index].event.duration_dots
            and row[index].event.duration_slashes == 1
            and "~" in row[index].event.code
            and row[index + 1].event.duration_slashes == 2
            and row[index + 2].event.kind == MusicTokenKind.BARLINE
            and interval_widths[index] == 18.0
        ):
            interval_widths[index] += 9.0
            if aligned_punctuation_transfer >= 9.0:
                aligned_punctuation_transfer -= 9.0
        if (
            policy.uses_primary_dual_verse_compound_grid
            and _has_two_cjk_extension_lyric(row[index].event.code, texts)
            and interval_widths[index] > 40.0
        ):
            interval_widths[index] = 40.0
        comma_text = next((text for text in texts if text.endswith(",")), None)
        if policy.uses_compact_four_voice_grid and comma_text is not None:
            interval_widths[index] -= 12.0 if len(comma_text.removesuffix(",")) < 3 else 10.0
        if texts and not any(texts):
            skip_indices.add(index)
        if (
            (
                policy.uses_compact_four_voice_grid
                or policy.row_count == 3 and left == 105.0
                or policy.uses_directive_origin_grid
            )
            and texts
            and row[index].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and row[index].event.duration_dots
            and row[index].event.duration_slashes
        ):
            if (
                (
                    _has_fullwidth_trailing_punctuation(texts)
                    or ")" in row[index].event.code
                    and _has_fullwidth_trailing_punctuation(previous_texts)
                )
                and index + 1 < len(interval_widths)
            ):
                interval_widths[index] += 3.6
                interval_widths[index + 1] += 3.6
            else:
                interval_widths[index] += 9.0
        _apply_compact_and_shifted_reserves(
            row,
            index=index,
            texts=texts,
            next_texts=next_texts,
            lyric_gap_by_event=lyric_gap_by_event,
            interval_widths=interval_widths,
            punctuation_indices=punctuation_indices,
            policy=policy,
        )
        if (
            row[index + 1].event.kind == MusicTokenKind.BARLINE
            and _has_fullwidth_trailing_punctuation(texts)
            and not (
                policy.uses_parallel_two_voice_lyric_grid
                or policy.uses_compound_aligned_two_voice_lyric_grid
                or policy.uses_primary_dual_verse_compound_grid
            )
        ):
            interval_widths[index] += 18.0
            punctuation_indices.add(index)
        elif (
            row[index + 1].event.kind == MusicTokenKind.BARLINE
            and _has_fullwidth_trailing_punctuation(texts)
            and policy.uses_primary_dual_verse_compound_grid
        ):
            aligned_punctuation_transfer += 18.0
        if (
            texts
            and not any(texts)
            and row[index].event.code.endswith("//)")
            and "(//" in row[index + 1].event.code
            and row[index].event.octave == row[index + 1].event.octave
        ):
            skip_connector_indices.add(index)
    terminal_texts = lyric_text_by_event.get(
        (row[-2].event.span.start.line, row[-2].event.index), ()
    )
    profile = replace(
        profile,
        interval_widths=tuple(interval_widths),
        terminal_width=(
            18.0
            if _has_fullwidth_trailing_punctuation(terminal_texts)
            else 36.0
            if policy.uses_compact_four_voice_grid
            and policy.uses_five_measure_grid
            and row[-2].event.kind == MusicTokenKind.EXTENSION
            and any(
                lyric_text_by_event.get(
                    (row[-3].event.span.start.line, row[-3].event.index), ()
                )
            )
            else profile.terminal_width
        ),
        denominator_adjustment=profile.denominator_adjustment + aligned_punctuation_transfer,
    )
    return (
        profile,
        frozenset(punctuation_indices),
        _has_fullwidth_trailing_punctuation(terminal_texts),
        frozenset(skip_indices),
        frozenset(skip_connector_indices),
    )


def _apply_dual_verse_compound_accidental_tail_reserve(
    row: list[LayoutEvent],
    interval_widths: list[float],
) -> None:
    """Keep an accidental reserve after a dotted continuation tail.

    In the dual-verse compound owner, a one-slash accidental followed by a
    dotted one-slash continuation and a two-slash close keeps its trailing
    reserve at the close of that source group.  The secondary row contributes
    the reserve to the shared profile when the primary row has no accidental.
    """
    for index, item in enumerate(row[:-3]):
        following = row[index + 1].event
        continuation = row[index + 2].event
        if (
            item.event.accidental is not None
            and item.event.duration_slashes == 1
            and "~" in item.event.code
            and following.duration_dots
            and following.duration_slashes == 1
            and "~" in following.code
            and continuation.duration_slashes == 2
            and row[index + 3].event.kind == MusicTokenKind.BARLINE
            and item.event.pitch == following.pitch == continuation.pitch
            and index + 2 < len(interval_widths)
        ):
            interval_widths[index + 2] += _ACCIDENTAL_RESERVE


def _has_two_cjk_extension_lyric(code: str, texts: tuple[str, ...]) -> bool:
    return "~" in code and any(
        len(text) == 2
        and all(unicodedata.east_asian_width(character) in {"W", "F"} for character in text)
        for text in texts
    )


def _apply_compact_and_shifted_reserves(
    row: list[LayoutEvent],
    *,
    index: int,
    texts: tuple[str, ...],
    next_texts: tuple[str, ...],
    lyric_gap_by_event: dict[tuple[int, int], int],
    interval_widths: list[float],
    punctuation_indices: set[int],
    policy: SharedRawProfilePolicy,
) -> None:
    item = row[index]
    if (
        policy.uses_compact_four_voice_grid
        and policy.uses_five_measure_grid
        and any(texts)
        and any(not character.isascii() for text in texts for character in text)
        and item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and event_duration_fraction(item.event) == 1
        and row[index + 1].event.kind
        in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST, MusicTokenKind.EXTENSION}
    ):
        interval_widths[index] = max(
            interval_widths[index],
            45.0 if row[index + 1].event.kind == MusicTokenKind.EXTENSION else 63.0,
        )
    if (
        policy.uses_compact_four_voice_grid
        and policy.uses_five_measure_grid
        and texts
        and not any(texts)
        and ")" in item.event.code
        and row[index + 1].event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
    ):
        interval_widths[index] = (
            36.0 if item.event.duration_dots else 27.0
        ) if policy.uses_mixed_note_origins else max(interval_widths[index], 45.0)
    if (
        policy.uses_compact_four_voice_grid
        and policy.uses_five_measure_grid
        and texts
        and not any(texts)
        and ")" in item.event.code
        and any(
            lyric_gap_by_event.get((later.event.span.start.line, later.event.index), 0) >= 3
            for later in row[index + 1 : index + 3]
        )
    ):
        interval_widths[index] = max(interval_widths[index], 27.0)
    if (
        policy.uses_shifted_voice_grid
        and texts
        and not any(texts)
        and index > 0
        and row[index + 1].event.kind == MusicTokenKind.BARLINE
        and ")" in item.event.code
        and "(" in row[index - 1].event.code
    ):
        interval_widths[index] += 18.0
    if (
        (policy.uses_shifted_voice_grid or policy.uses_compact_four_voice_grid)
        and texts
        and not any(texts)
        and ")" in item.event.code
        and index > 0
        and row[index - 1].event.kind == MusicTokenKind.BARLINE
        and (
            row[index + 1].event.kind != MusicTokenKind.EXTENSION
            or sum(
                later.event.kind == MusicTokenKind.BARLINE for later in row[index + 1 :]
            )
            >= 2
        )
    ):
        interval_widths[index] += 9.0
    if (
        policy.uses_shifted_voice_grid
        and _has_fullwidth_trailing_punctuation(texts)
        and next_texts
        and not any(next_texts)
        and index + 1 < len(interval_widths)
        and index + 2 < len(row)
        and row[index + 2].event.kind == MusicTokenKind.BARLINE
    ):
        interval_widths[index + 1] += 18.0
        punctuation_indices.add(index + 1)


__all__ = ["SharedRawProfilePolicy", "SharedRawProfiles", "build_shared_raw_profiles"]
