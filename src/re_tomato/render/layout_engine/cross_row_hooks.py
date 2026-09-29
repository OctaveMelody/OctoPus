"""Cross-row hook ownership planning for voice-row justification."""

from __future__ import annotations

from dataclasses import dataclass

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent


@dataclass(frozen=True)
class CrossRowHookPlan:
    lyricless_rows: frozenset[int]
    width_adjustments: dict[int, float]
    lyric_to_lyricless_adjustments: dict[int, float]
    lyric_to_lyricless_openers: frozenset[int]
    uses_lyricless_cursor: bool


def plan_cross_row_hooks(
    rows: list[list[LayoutEvent]],
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
) -> CrossRowHookPlan:
    lyricless_rows: set[int] = set()
    width_adjustments: dict[int, float] = {}
    lyric_to_lyricless_adjustments: dict[int, float] = {}
    lyric_to_lyricless_openers: set[int] = set()
    for start_index, start_row in enumerate(rows):
        if not any("zkh" in item.event.decorations for item in start_row):
            continue
        if any("ykh" in item.event.decorations for item in start_row):
            continue
        end_index = _closing_row_index(rows, start_index)
        if end_index is None:
            continue
        span_rows = rows[start_index : end_index + 1]
        span_has_lyrics = any(_row_has_lyrics(row, lyric_text_by_event) for row in span_rows)
        opener_has_lyrics = _row_has_lyrics(start_row, lyric_text_by_event)
        closer_has_lyrics = _row_has_lyrics(rows[end_index], lyric_text_by_event)
        closer_is_extension = any(
            "ykh" in item.event.decorations
            and item.event.kind in {MusicTokenKind.EXTENSION, MusicTokenKind.HIDDEN_REST}
            for item in rows[end_index]
        )
        if not span_has_lyrics:
            lyricless_rows.update(range(start_index, end_index + 1))
        elif opener_has_lyrics:
            lyricless_rows.update(
                index
                for index in range(start_index, end_index + 1)
                if not _row_has_lyrics(rows[index], lyric_text_by_event)
            )
        if _uses_undivided_width_transfer(start_row, opener_has_lyrics):
            width_adjustments[start_index] = 9.0
            width_adjustments[end_index] = -9.0
        elif opener_has_lyrics and not closer_has_lyrics and closer_is_extension:
            lyric_to_lyricless_openers.add(start_index)
            lyric_to_lyricless_adjustments[end_index] = -9.0

    return CrossRowHookPlan(
        lyricless_rows=frozenset(lyricless_rows),
        width_adjustments=width_adjustments,
        lyric_to_lyricless_adjustments=lyric_to_lyricless_adjustments,
        lyric_to_lyricless_openers=frozenset(lyric_to_lyricless_openers),
        uses_lyricless_cursor=_uses_lyricless_cross_row_cursor(rows, lyric_text_by_event),
    )


def _closing_row_index(rows: list[list[LayoutEvent]], start_index: int) -> int | None:
    return next(
        (
            index
            for index in range(start_index + 1, len(rows))
            if any("ykh" in item.event.decorations for item in rows[index])
        ),
        None,
    )


def _row_has_lyrics(
    row: list[LayoutEvent],
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
) -> bool:
    return any(
        text
        for item in row
        for text in lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
    )


def _uses_undivided_width_transfer(
    start_row: list[LayoutEvent],
    opener_has_lyrics: bool,
) -> bool:
    opener = start_row[0].event
    return (
        not opener_has_lyrics
        and "zkh" in opener.decorations
        and not opener.duration_slashes
        and "(" in opener.code
        and opener.octave > 0
    )


def _uses_lyricless_cross_row_cursor(
    rows: list[list[LayoutEvent]],
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
) -> bool:
    return (
        len(rows) > 1
        and bool(rows[0])
        and bool(rows[0][0].event.duration_slashes)
        and "zkh" in rows[0][0].event.decorations
        and any(
            "ykh" in item.event.decorations
            for later_row in rows[1:]
            for item in later_row
        )
        and not any(text for texts in lyric_text_by_event.values() for text in texts)
    )
