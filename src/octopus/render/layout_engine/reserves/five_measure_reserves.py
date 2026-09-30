"""Five-measure lyric-punctuation reserve allocation policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..profiles import LegacyIntrinsicProfile


def apply_five_measure_shared_reserves(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
    reconciled_widths: Sequence[Sequence[float]],
    *,
    lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], tuple[str, ...]]],
    has_fullwidth_trailing_punctuation: Callable[[tuple[str, ...]], bool],
) -> list[tuple[float, ...]]:
    """Allocate punctuation reserves for the recognized five-measure row shape."""
    widths = [list(items) for items in reconciled_widths]
    bar_indices = [
        [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        for row in rows
    ]
    punctuation_measures: set[int] = set()
    visible_lyrics_by_voice = [
        any(
            text
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
        )
        for row in rows
    ]
    measure_starts = [0 for _row in rows]
    for measure_ordinal in range(len(bar_indices[0])):
        for voice_index, row in enumerate(rows):
            start = measure_starts[voice_index]
            end = bar_indices[voice_index][measure_ordinal]
            measure_starts[voice_index] = end
            if end - start < 2:
                continue
            extension = row[end - 1]
            host = row[end - 2]
            texts = lyric_text_by_voice.get(row[0].voice, {}).get(
                (host.event.span.start.line, host.event.index),
                (),
            )
            if (
                extension.event.kind == MusicTokenKind.EXTENSION
                and host.event.kind != MusicTokenKind.EXTENSION
                and has_fullwidth_trailing_punctuation(texts)
            ):
                punctuation_measures.add(measure_ordinal)

    if visible_lyrics_by_voice != [True, True, False, False] or punctuation_measures != {
        0,
        1,
    }:
        return [tuple(items) for items in reconciled_widths]

    for voice_index, row in enumerate(rows):
        has_visible_lyrics = visible_lyrics_by_voice[voice_index]
        start = 0
        for measure_ordinal, end in enumerate(bar_indices[voice_index]):
            if measure_ordinal in punctuation_measures:
                if has_visible_lyrics:
                    reserve_index = (
                        end - 1 if end - 1 < len(widths[voice_index]) else None
                    )
                else:
                    reserve_index = first_unused_even_beat_interval(
                        row,
                        start,
                        end,
                        widths[voice_index],
                        profiles[voice_index].interval_widths,
                    )
                if reserve_index is not None:
                    widths[voice_index][reserve_index] += 18.0
            start = end

        if not has_visible_lyrics and punctuation_measures:
            final_start = bar_indices[voice_index][-2]
            final_end = bar_indices[voice_index][-1]
            reserve_index = first_unused_even_beat_interval(
                row,
                final_start,
                final_end,
                widths[voice_index],
                profiles[voice_index].interval_widths,
            )
            if reserve_index is not None:
                widths[voice_index][reserve_index] += 18.0
            final_interval = final_end - 2
            if (
                final_interval - 1 >= final_start
                and final_interval < len(widths[voice_index])
                and final_interval < len(profiles[voice_index].interval_widths)
                and widths[voice_index][final_interval]
                - profiles[voice_index].interval_widths[final_interval]
                >= 9.0 - GEOMETRY_EPSILON
            ):
                widths[voice_index][final_interval] -= 9.0
                widths[voice_index][final_interval - 1] += 9.0
    return [tuple(items) for items in widths]


def first_unused_even_beat_interval(
    row: Sequence[LayoutEvent],
    start: int,
    end: int,
    widths: Sequence[float],
    raw_widths: Sequence[float],
) -> int | None:
    """Find the last usable even-beat interval below the 9px reserve threshold."""
    content_start = start + int(row[start].event.kind == MusicTokenKind.BARLINE)
    elapsed = Fraction()
    candidates: list[int] = []
    for index in range(content_start, end):
        event = row[index].event
        if event.duration is not None:
            elapsed += Fraction(event.duration.numerator, event.duration.denominator)
        elif event.kind == MusicTokenKind.EXTENSION:
            elapsed += Fraction(1)
        else:
            continue
        if (
            elapsed.denominator == 1
            and elapsed.numerator % 2 == 0
            and index < len(widths)
            and index < len(raw_widths)
        ):
            candidates.append(index)
    return next(
        (
            index
            for index in candidates
            if widths[index] - raw_widths[index] < 9.0 - GEOMETRY_EPSILON
        ),
        candidates[-1] if candidates else None,
    )


__all__ = ["apply_five_measure_shared_reserves", "first_unused_even_beat_interval"]
