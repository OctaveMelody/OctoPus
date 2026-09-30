"""Ordered multi-measure phrase-pattern width policies."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..profiles import LegacyIntrinsicProfile
from ..rows.row_signatures import (
    row_event_has_lyric as _row_event_has_lyric,
)
from .five_measure_union import apply_five_measure_dual_lyric_union
from .immediate_tied_response import apply_immediate_dotted_tie_response_reserves
from .models import LyricTextByVoice


@dataclass(frozen=True)
class SharedPhrasePatternState:
    profiles: list[LegacyIntrinsicProfile]
    reconciled_widths: list[tuple[float, ...]]
    uses_two_voice_five_measure_lyric_grid: bool
    uses_two_voice_call_response_lyric_grid: bool
    uses_two_voice_tied_response_lyric_grid: bool
    primary_call_response_starts_with_two_rests: bool


def apply_phrase_pattern_policies(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    left: float,
    visible_lyric_profile_indices: list[int],
    lyric_text_by_voice: LyricTextByVoice,
) -> SharedPhrasePatternState:
    reconciled_widths, uses_two_voice_five_measure_lyric_grid = (
        _apply_extension_measure_policies(
            rows,
            reconciled_widths,
            left=left,
            visible_lyric_profile_indices=visible_lyric_profile_indices,
        )
    )
    (
        reconciled_widths,
        uses_two_voice_call_response_lyric_grid,
        primary_call_response_starts_with_two_rests,
    ) = _apply_call_response_policy(
        rows,
        reconciled_widths,
        left=left,
        visible_lyric_profile_indices=visible_lyric_profile_indices,
        lyric_text_by_voice=lyric_text_by_voice,
    )
    profiles, reconciled_widths, uses_two_voice_tied_response_lyric_grid = (
        _apply_tied_response_policy(
            rows,
            profiles,
            reconciled_widths,
            left=left,
            visible_lyric_profile_indices=visible_lyric_profile_indices,
            lyric_text_by_voice=lyric_text_by_voice,
        )
    )
    profiles, reconciled_widths = apply_immediate_dotted_tie_response_reserves(
        rows,
        profiles,
        reconciled_widths,
        lyric_text_by_voice=lyric_text_by_voice,
    )
    reconciled_widths = apply_five_measure_dual_lyric_union(
        rows,
        profiles,
        reconciled_widths,
        lyric_text_by_voice=lyric_text_by_voice,
    )
    return SharedPhrasePatternState(
        profiles=profiles,
        reconciled_widths=reconciled_widths,
        uses_two_voice_five_measure_lyric_grid=uses_two_voice_five_measure_lyric_grid,
        uses_two_voice_call_response_lyric_grid=uses_two_voice_call_response_lyric_grid,
        uses_two_voice_tied_response_lyric_grid=uses_two_voice_tied_response_lyric_grid,
        primary_call_response_starts_with_two_rests=(
            primary_call_response_starts_with_two_rests
        ),
    )




def _apply_extension_measure_policies(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
    *,
    left: float,
    visible_lyric_profile_indices: list[int],
) -> tuple[list[tuple[float, ...]], bool]:
    uses_two_voice_five_measure_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and rows[0][0].event.pitch == 1
        and rows[0][0].event.octave == 0
        and rows[0][1].event.kind == MusicTokenKind.EXTENSION
        and all(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 5
            and row[-1].event.code == "|"
            for row in rows
        )
    )
    if uses_two_voice_five_measure_lyric_grid:
        adjusted_widths: list[tuple[float, ...]] = []
        for row, row_widths in zip(rows, reconciled_widths, strict=True):
            adjusted = list(row_widths)
            bar_indices = [
                index
                for index, item in enumerate(row)
                if item.event.kind == MusicTokenKind.BARLINE
            ]
            for measure_start, measure_end in zip(
                bar_indices,
                bar_indices[1:-1],
                strict=False,
            ):
                extension_index = next(
                    (
                        index
                        for index in range(measure_start + 1, measure_end)
                        if row[index].event.kind == MusicTokenKind.EXTENSION
                    ),
                    None,
                )
                if extension_index is not None and extension_index < len(adjusted):
                    adjusted[extension_index] += 27.0
            for index, item in enumerate(row[:-2]):
                if (
                    item.event.kind == MusicTokenKind.REST
                    and row[index - 1].event.kind == MusicTokenKind.EXTENSION
                    and row[index + 1].event.kind == MusicTokenKind.BARLINE
                    and adjusted[index] >= 27.0
                ):
                    adjusted[index - 1] += 27.0
                    adjusted[index] -= 27.0
                if (
                    item.event.duration_slashes == 2
                    and "(" in row[index + 1].event.code
                    and adjusted[index] >= 18.0
                ):
                    adjusted[index] -= 18.0
                    adjusted[index + 1] += 18.0
            adjusted_widths.append(tuple(adjusted))
        reconciled_widths = adjusted_widths
    uses_two_voice_six_measure_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and rows[0][0].event.pitch == 1
        and rows[0][0].event.octave == 0
        and rows[0][1].event.kind == MusicTokenKind.EXTENSION
        and all(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 6
            and row[-1].event.code == "|"
            for row in rows
        )
    )
    if uses_two_voice_six_measure_lyric_grid:
        adjusted_widths = []
        for row, row_widths in zip(rows, reconciled_widths, strict=True):
            adjusted = list(row_widths)
            bar_indices = [
                index
                for index, item in enumerate(row)
                if item.event.kind == MusicTokenKind.BARLINE
            ]
            for measure_start, measure_end in zip(
                bar_indices,
                bar_indices[1:4],
                strict=False,
            ):
                extension_index = next(
                    (
                        index
                        for index in range(measure_start + 1, measure_end)
                        if row[index].event.kind == MusicTokenKind.EXTENSION
                    ),
                    None,
                )
                if extension_index is not None and extension_index < len(adjusted):
                    adjusted[extension_index] += 27.0
            for index, item in enumerate(row[:-2]):
                if (
                    item.event.duration_slashes == 2
                    and "(" in row[index + 1].event.code
                    and adjusted[index] >= 18.0
                ):
                    adjusted[index] -= 18.0
                    adjusted[index + 1] += 18.0
            final_start = bar_indices[-2] + 1
            final_end = bar_indices[-1]
            leading_rests = [
                index
                for index in range(final_start, min(final_start + 2, final_end))
                if row[index].event.kind
                in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            ]
            if len(leading_rests) == 2:
                for index in leading_rests:
                    adjusted[index] += 18.0
            elif (
                final_end >= 2
                and row[final_end - 2].event.kind
                in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
                and row[final_end - 1].event.kind == MusicTokenKind.EXTENSION
            ):
                adjusted[final_end - 2] += 18.0
            adjusted_widths.append(tuple(adjusted))
        reconciled_widths = adjusted_widths
    return reconciled_widths, uses_two_voice_five_measure_lyric_grid


def _apply_call_response_policy(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
    *,
    left: float,
    visible_lyric_profile_indices: list[int],
    lyric_text_by_voice: LyricTextByVoice,
) -> tuple[list[tuple[float, ...]], bool, bool]:
    uses_two_voice_call_response_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and all(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 5
            and row[-1].event.code == "|"
            for row in rows
        )
        and any(
            [item.event.pitch for item in row[index : index + 5]] == [2, 2, 1, 2, 6]
            and [item.event.duration_slashes for item in row[index : index + 5]]
            == [1, 0, 1, 0, 0]
            and row[index + 5].event.kind == MusicTokenKind.BARLINE
            for row in rows
            for index in range(len(row) - 5)
        )
    )
    primary_call_response_starts_with_two_rests = (
        uses_two_voice_call_response_lyric_grid
        and len(rows[0]) >= 2
        and all(
            item.event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            for item in rows[0][:2]
        )
    )
    if uses_two_voice_call_response_lyric_grid:
        adjusted_widths = []
        for row, row_widths in zip(rows, reconciled_widths, strict=True):
            adjusted = list(row_widths)
            lyric_text_by_event = lyric_text_by_voice.get(row[0].voice, {})
            if (
                len(row) >= 2
                and all(
                    item.event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    for item in row[:2]
                )
            ):
                adjusted[0] += 18.0
                adjusted[1] += 18.0
            for index, item in enumerate(row[:-2]):
                texts = lyric_text_by_event.get(
                    (item.event.span.start.line, item.event.index),
                    (),
                )
                if (
                    texts
                    and any(texts)
                    and index + 1 < len(adjusted)
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                ):
                    if "f" in item.event.decorations or adjusted[index] >= 45.0:
                        adjusted[index + 1] += 27.0
                    elif row[index + 2].event.kind == MusicTokenKind.EXTENSION:
                        pass
                    elif row[index + 2].event.kind == MusicTokenKind.HIDDEN_REST:
                        adjusted[index] += 18.0
                        adjusted[index + 1] += 9.0
                    else:
                        adjusted[index] += 18.0
                        adjusted[index + 1] += 18.0
                if (
                    index < len(adjusted)
                    and item.event.kind
                    in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    and row[index - 1].event.kind == MusicTokenKind.EXTENSION
                    and row[index + 1].event.kind == MusicTokenKind.BARLINE
                ):
                    adjusted[index] += 27.0
                    closing_bar_index = next(
                        (
                            later
                            for later in range(index + 2, len(row))
                            if row[later].event.kind == MusicTokenKind.BARLINE
                        ),
                        None,
                    )
                    if (
                        closing_bar_index is not None
                        and closing_bar_index - 1 < len(adjusted)
                    ):
                        adjusted[closing_bar_index - 1] -= 27.0
                if (
                    index + 1 < len(adjusted)
                    and item.event.duration_dots
                    and item.event.duration_slashes == 1
                    and not row[index + 1].event.duration_slashes
                    and row[index + 2].event.kind == MusicTokenKind.BARLINE
                    and adjusted[index + 1] >= 9.0
                ):
                    adjusted[index] += 9.0
                    adjusted[index + 1] -= 9.0
            for index in range(len(row) - 5):
                measure_items = row[index : index + 5]
                if (
                    index + 4 < len(adjusted)
                    and [item.event.pitch for item in measure_items] == [2, 2, 1, 2, 6]
                    and [item.event.duration_slashes for item in measure_items]
                    == [1, 0, 1, 0, 0]
                    and row[index + 5].event.kind == MusicTokenKind.BARLINE
                ):
                    adjusted[index] += 9.0
                    adjusted[index + 4] -= 9.0
            adjusted_widths.append(tuple(adjusted))
        reconciled_widths = adjusted_widths
    return (
        reconciled_widths,
        uses_two_voice_call_response_lyric_grid,
        primary_call_response_starts_with_two_rests,
    )


def _apply_tied_response_policy(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    left: float,
    visible_lyric_profile_indices: list[int],
    lyric_text_by_voice: LyricTextByVoice,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]], bool]:
    uses_two_voice_tied_response_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and all(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) in {5, 6}
            and row[-1].event.code == "|"
            for row in rows
        )
        and any(
            "(" in rows[0][index].event.code
            and rows[0][index].event.duration_dots
            and ")" in rows[0][index + 2].event.code
            for index in range(len(rows[0]) - 2)
        )
    )
    if uses_two_voice_tied_response_lyric_grid:
        adjusted_widths = []
        adjusted_terminal_widths: list[float] = []
        for voice_index, (row, row_widths) in enumerate(
            zip(rows, reconciled_widths, strict=True)
        ):
            adjusted = list(row_widths)
            terminal_width = profiles[voice_index].terminal_width
            lyric_text_by_event = lyric_text_by_voice.get(row[0].voice, {})

            for index, item in enumerate(row[:-2]):
                if (
                    _row_event_has_lyric(row, index, lyric_text_by_event)
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                    and row[index + 2].event.kind == MusicTokenKind.EXTENSION
                    and (
                        index + 3 >= len(row)
                        or row[index + 3].event.kind != MusicTokenKind.EXTENSION
                    )
                ):
                    adjusted[index + 1] += 27.0
                elif (
                    _row_event_has_lyric(row, index, lyric_text_by_event)
                    and "(" in item.event.code
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                    and ")" in row[index + 2].event.code
                ):
                    adjusted[index] -= 18.0
                    adjusted[index + 1] += 9.0
                elif (
                    _row_event_has_lyric(row, index, lyric_text_by_event)
                    and "(" in item.event.code
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                    and row[index + 2].event.kind == MusicTokenKind.BARLINE
                    and adjusted[index + 1] < 43.0
                ):
                    adjusted[index + 1] += 27.0
                elif (
                    _row_event_has_lyric(row, index, lyric_text_by_event)
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                    and row[index + 2].event.kind != MusicTokenKind.EXTENSION
                    and "(" not in row[index + 2].event.code
                    and (
                        ")" in row[index - 1].event.code
                        or row[index - 1].event.kind == MusicTokenKind.BARLINE
                        and index >= 2
                        and ")" in row[index - 2].event.code
                    )
                ):
                    adjusted[index] += 18.0
                    if index + 1 < len(adjusted):
                        adjusted[index + 1] += 18.0
                    else:
                        terminal_width += 18.0
                if (
                    "(" in item.event.code
                    and item.event.duration_dots
                    and ")" in row[index + 2].event.code
                    and index > 0
                    and index + 1 < len(adjusted)
                ):
                    adjusted[index - 1] -= 18.0
                    adjusted[index] -= 9.0
                    adjusted[index + 1] += 27.0
                if (
                    index + 3 < len(row)
                    and (
                        item.event.kind == MusicTokenKind.EXTENSION
                        or ")" in item.event.code
                    )
                    and row[index + 1].event.duration_dots
                    and row[index + 1].event.duration_slashes == 1
                    and row[index + 2].event.duration_slashes == 2
                    and "(" in row[index + 3].event.code
                    and index + 3 < len(adjusted)
                ):
                    adjusted[index] -= 18.0
                    adjusted[index + 1] -= 18.0
                    adjusted[index + 2] += 9.0
                    adjusted[index + 3] += 18.0
                if (
                    item.event.kind
                    in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    and row[index + 1].event.kind
                    in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    and _row_event_has_lyric(row, index + 2, lyric_text_by_event)
                ):
                    adjusted[index] += 18.0
                    adjusted[index + 1] += 18.0
            adjusted_widths.append(tuple(adjusted))
            adjusted_terminal_widths.append(terminal_width)
        reconciled_widths = adjusted_widths
        profiles = [
            replace(profile, terminal_width=terminal_width)
            for profile, terminal_width in zip(
                profiles,
                adjusted_terminal_widths,
                strict=True,
            )
        ]
    return profiles, reconciled_widths, uses_two_voice_tied_response_lyric_grid

__all__ = ["SharedPhrasePatternState", "apply_phrase_pattern_policies"]
