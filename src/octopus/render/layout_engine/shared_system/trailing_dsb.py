"""Trailing DSB response reserve reconciliation."""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..profiles import LegacyIntrinsicProfile
from ..streams import first_meter
from .models import LyricTextByVoice

TRAILING_DSB_ANCHOR_RESERVE = 14.4


def apply_trailing_dsb_sustain_reserve(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
    *,
    profiles: list[LegacyIntrinsicProfile],
    lyric_text_by_voice: LyricTextByVoice,
    time_sig: str,
) -> list[tuple[float, ...]]:
    """Insert the extension-owned reserve before a trailing DSB response.

    A plain two-measure temporary DSB sustain contributes a 14.4-unit reserve
    after its anchor. The 3/4 family owns that reserve alone and it is
    music-driven: every lyric arrangement of the same four-voice system
    (adjacent or interleaved verses) keeps it, so no lyric-row condition
    applies there. In the 2/4 interleaved-lyric family, the lyricless DSB row
    also preserves its two-sided accidental reserve before the response.
    """

    meter = first_meter(time_sig)
    if meter not in {(2, 4), (3, 4)} or len(rows) != 4:
        return reconciled_widths
    lyric_rows = tuple(
        any(
            text
            for item in row
            for text in lyric_text_by_voice.get(row[0].voice, {}).get(
                (item.event.span.start.line, item.event.index), ()
            )
        )
        for row in rows
    )
    candidates: list[tuple[int, int]] = []
    for row_index, row in enumerate(rows):
        anchors = [
            index for index, item in enumerate(row) if "&dsb_a" in item.event.code
        ]
        if len(anchors) != 1:
            continue
        anchor = anchors[0]
        measures = _measure_suffix(row[anchor + 1 :])
        if len(measures) != 2 or not all(
            _is_plain_dsb_sustain_measure(measure, beats=meter[0])
            for measure in measures
        ):
            continue
        candidates.append((row_index, anchor))
    if len(candidates) != 1:
        return reconciled_widths
    dsb_row_index, anchor = candidates[0]
    if any(anchor >= len(widths) for widths in reconciled_widths):
        return reconciled_widths
    adjusted = [list(widths) for widths in reconciled_widths]
    if meter != (3, 4):
        if lyric_rows != (True, False, True, False):
            return reconciled_widths
        if not _restore_interleaved_dsb_accidental_reserve(
            rows[dsb_row_index],
            adjusted,
            profiles[dsb_row_index].interval_widths,
            dsb_row_index=dsb_row_index,
            anchor=anchor,
        ):
            return reconciled_widths
    for row_widths in adjusted:
        row_widths[anchor] += TRAILING_DSB_ANCHOR_RESERVE
    return [tuple(widths) for widths in adjusted]


def _restore_interleaved_dsb_accidental_reserve(
    dsb_row: list[LayoutEvent],
    adjusted_widths: list[list[float]],
    intrinsic_widths: tuple[float, ...],
    *,
    dsb_row_index: int,
    anchor: int,
) -> bool:
    candidates = [
        index
        for index, item in enumerate(dsb_row[:anchor])
        if index > 0
        and index + 2 < len(dsb_row)
        and item.event.accidental is not None
        and item.event.duration_slashes == 0
        and dsb_row[index + 1].event.pitch == item.event.pitch
        and dsb_row[index + 1].event.accidental is None
        and dsb_row[index + 2].event.kind == MusicTokenKind.BARLINE
    ]
    if len(candidates) != 1:
        return False
    accidental_index = candidates[0]
    if any(accidental_index + 1 >= len(widths) for widths in adjusted_widths):
        return False
    dsb_widths = adjusted_widths[dsb_row_index]
    leading_delta = intrinsic_widths[accidental_index - 1] - dsb_widths[accidental_index - 1]
    shared_excess = dsb_widths[accidental_index] - intrinsic_widths[accidental_index]
    if leading_delta <= 0 or shared_excess <= 0:
        return False
    for widths in adjusted_widths:
        widths[accidental_index - 1] += leading_delta
        widths[accidental_index] -= shared_excess
        widths[accidental_index + 1] += leading_delta + shared_excess
    return True


def _measure_suffix(items: list[LayoutEvent]) -> list[list[LayoutEvent]]:
    measures: list[list[LayoutEvent]] = []
    current: list[LayoutEvent] = []
    for item in items:
        current.append(item)
        if item.event.kind == MusicTokenKind.BARLINE:
            measures.append(current)
            current = []
    if current:
        measures.append(current)
    return measures


def _is_plain_dsb_sustain_measure(
    measure: list[LayoutEvent], *, beats: int
) -> bool:
    return (
        len(measure) == beats + 1
        and measure[0].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and all(item.event.kind == MusicTokenKind.EXTENSION for item in measure[1:beats])
        and measure[beats].event.kind == MusicTokenKind.BARLINE
        and measure[beats].block == "dsb-tail"
    )


__all__ = ["apply_trailing_dsb_sustain_reserve"]
