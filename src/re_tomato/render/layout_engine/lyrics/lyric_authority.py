"""Single-lyric-authority width projection across parallel rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..duration_partition import partition_shared_measure_widths_by_duration
from ..hidden.hidden_streams import event_duration_fraction
from ..profiles import LegacyIntrinsicProfile


def reconcile_single_lyric_authority_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    profiles: Sequence[LegacyIntrinsicProfile],
    *,
    lyric_profile_index: int,
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> list[tuple[float, ...]] | None:
    bar_indices = [
        [index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE]
        for row in rows
    ]
    if not bar_indices or len({len(indices) for indices in bar_indices}) != 1:
        return None

    authority_row = rows[lyric_profile_index]
    authority_widths = list(profiles[lyric_profile_index].interval_widths)
    authority_texts = [
        lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
        for item in authority_row[: len(authority_widths)]
    ]
    for event_index in range(len(authority_widths)):
        texts = authority_texts[event_index]
        next_texts = next(
            (
                later_texts
                for later_texts in authority_texts[event_index + 1 :]
                if any(later_texts)
            ),
            (),
        )
        if any(
            text.endswith(",") and len(text.removesuffix(",")) >= 3 for text in texts
        ) and any(len(text) < 3 for text in next_texts if text):
            authority_widths[event_index] += 10.0
    measure_starts = [0 for _row in rows]
    for measure_ordinal in range(len(bar_indices[0])):
        slices: list[tuple[int, int]] = []
        timed_events: list[list[tuple[Fraction, Fraction, int, LayoutEvent]]] = []
        for voice_index, row in enumerate(rows):
            start = measure_starts[voice_index]
            end = bar_indices[voice_index][measure_ordinal]
            measure_starts[voice_index] = end
            profile_end = min(end, len(profiles[voice_index].interval_widths))
            slices.append((start, profile_end))
            content_start = start + int(row[start].event.kind == MusicTokenKind.BARLINE)
            elapsed = Fraction()
            voice_events: list[tuple[Fraction, Fraction, int, LayoutEvent]] = []
            for index in range(content_start, end):
                duration = event_duration_fraction(row[index].event)
                voice_events.append((elapsed, elapsed + duration, index, row[index]))
                elapsed += duration
            timed_events.append(voice_events)

        for event_start, event_end, event_index, item in timed_events[lyric_profile_index]:
            inserted_events = [
                inserted
                for voice_index, voice_events in enumerate(timed_events)
                if voice_index != lyric_profile_index
                for inserted_start, _inserted_end, _inserted_index, inserted in voice_events
                if event_start < inserted_start < event_end
            ]
            if not inserted_events or event_index >= len(authority_widths):
                continue
            texts = lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
            has_long_ascii = any(
                sum(character.isascii() for character in text) >= 3 for text in texts
            )
            authority_widths[event_index] += (
                25.2
                if any(inserted.event.accidental is not None for inserted in inserted_events)
                else 18.0
                if has_long_ascii
                else 27.0
            )

    result: list[tuple[float, ...]] = []
    measure_starts = [0 for _row in rows]
    for voice_index, row in enumerate(rows):
        projected = list(profiles[voice_index].interval_widths)
        for measure_ordinal in range(len(bar_indices[0])):
            authority_start = measure_starts[lyric_profile_index]
            authority_end = bar_indices[lyric_profile_index][measure_ordinal]
            current_start = measure_starts[voice_index]
            current_end = bar_indices[voice_index][measure_ordinal]
            measure_starts[lyric_profile_index] = authority_end
            measure_starts[voice_index] = current_end
            target_end = min(authority_end, len(authority_widths))
            current_profile_end = min(current_end, len(projected))
            replacement = partition_shared_measure_widths_by_duration(
                authority_widths[authority_start:target_end],
                projected[current_start:current_profile_end],
                authority_row[authority_start:authority_end],
                row[current_start:current_end],
                allow_current_rests=True,
                allow_partial_boundaries=True,
                prefer_leading_deficit=True,
            )
            if replacement is None:
                return None
            target_items = authority_row[authority_start:authority_end]
            current_items = row[current_start:current_end]
            if len(current_items) == len(target_items) + 1 and len(replacement) >= 2:
                terminal_cap = profiles[voice_index].raw_terminal_width
                terminal_excess = replacement[-1] - terminal_cap
                if terminal_excess > GEOMETRY_EPSILON:
                    replacement[-2] += terminal_excess
                    replacement[-1] = terminal_cap
            for item_offset, item in enumerate(current_items):
                if (
                    voice_index != lyric_profile_index
                    and item.event.accidental == "#"
                    and 0 < item_offset < len(replacement)
                    and replacement[item_offset] >= 14.0
                ):
                    replacement[item_offset - 1] += 14.0
                    replacement[item_offset] -= 14.0
            projected[current_start:current_profile_end] = replacement
        result.append(tuple(projected))
        measure_starts = [0 for _row in rows]
    return result


__all__ = ["reconcile_single_lyric_authority_grid"]
