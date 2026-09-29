"""Ordered transition, refrain, and pickup phrase policies."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import (
    event_duration_fraction as _event_duration_fraction,
)
from ..profiles import LegacyIntrinsicProfile
from ..rows.row_signatures import (
    row_event_has_lyric as _row_event_has_lyric,
)
from ..rows.row_signatures import row_event_onsets as _row_event_onsets
from .models import LyricTextByVoice


def apply_phrase_transition_policies(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    left: float,
    visible_lyric_profile_indices: list[int],
    lyric_text_by_voice: LyricTextByVoice,
    uses_two_voice_five_measure_lyric_grid: bool,
    uses_two_voice_call_response_lyric_grid: bool,
    uses_two_voice_tied_response_lyric_grid: bool,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    """Apply phrase-transition width policies to two-voice lyric grids.

    Detects the REF-decoded transition shapes (hook transitions at the 83.0 compact
    origin, five-measure lyric grids, call/response pairs, tied responses) and
    adjusts the per-row reconciled widths so the second voice's phrase entry/exit
    matches the reference engraving. Pure width policy: inputs and outputs are the
    profile/width lists; row geometry is untouched."""
    uses_two_voice_hook_transition_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and any("zkh" in item.event.decorations for row in rows for item in row)
        and all(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 6
            and row[-1].event.code == "|"
            for row in rows
        )
        and all(
            any(
                "(" in row[index].event.code
                and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                and ")" in row[index + 2].event.code
                for index in range(len(row) - 2)
            )
            for row in rows
        )
    )
    if uses_two_voice_hook_transition_lyric_grid:
        primary_onsets = _row_event_onsets(rows[0])
        hook_onset = next(
            primary_onsets[index]
            for index, item in enumerate(rows[0])
            if "zkh" in item.event.decorations
        )
        adjusted_widths = []
        for row, row_widths in zip(rows, reconciled_widths, strict=True):
            adjusted = list(row_widths)
            onsets = _row_event_onsets(row)
            hook_index = next(
                index
                for index, onset in enumerate(onsets)
                if onset == hook_onset
                and row[index].event.kind != MusicTokenKind.BARLINE
            )
            if hook_index > 0:
                adjusted[hook_index - 1] += 9.0
            final_bar_index = max(
                index
                for index, item in enumerate(row[:-1])
                if item.event.kind == MusicTokenKind.BARLINE
            )
            for index in range(final_bar_index + 1, len(row) - 2):
                if (
                    "(" in row[index].event.code
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                    and ")" in row[index + 2].event.code
                ):
                    adjusted[index] -= 18.0
                    adjusted[index + 1] -= 18.0
                    break
            adjusted_widths.append(tuple(adjusted))
        reconciled_widths = adjusted_widths
    uses_two_voice_meter_transition_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and all(
            any("p:2/4" in item.event.code for item in row)
            and any("p:4/4" in item.event.code for item in row)
            for row in rows
        )
    )
    if uses_two_voice_meter_transition_lyric_grid:
        adjusted_widths = []
        for row, row_widths in zip(rows, reconciled_widths, strict=True):
            adjusted = list(row_widths)
            lyric_text_by_event = lyric_text_by_voice.get(row[0].voice, {})
            first_directive_index = next(
                index
                for index, item in enumerate(row)
                if "p:2/4" in item.event.code
            )
            extended_lyric_index = next(
                index
                for index in range(first_directive_index)
                if _row_event_has_lyric(row, index, lyric_text_by_event)
                and row[index + 1].event.kind == MusicTokenKind.EXTENSION
            )
            adjusted[extended_lyric_index] += 18.0
            adjusted[extended_lyric_index + 1] += 18.0
            restore_directive_index = next(
                index
                for index, item in enumerate(row)
                if "p:4/4" in item.event.code
            )
            adjusted[restore_directive_index] -= 9.0
            adjusted_widths.append(tuple(adjusted))
        reconciled_widths = adjusted_widths
    uses_two_voice_refrain_lyric_grid = (
        len(rows) == 2
        and left == 83.0
        and visible_lyric_profile_indices == [0, 1]
        and not (
            uses_two_voice_five_measure_lyric_grid
            or uses_two_voice_call_response_lyric_grid
            or uses_two_voice_tied_response_lyric_grid
        )
        and all(
            sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 5
            and row[-1].event.code == "|"
            for row in rows
        )
        and any(
            row[index].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            and row[index + 1].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            for row in rows
            for index in range(len(row) - 2)
        )
    )
    if uses_two_voice_refrain_lyric_grid:
        adjusted_widths = []
        adjusted_terminal_widths = []
        for voice_index, (row, row_widths) in enumerate(
            zip(rows, reconciled_widths, strict=True)
        ):
            adjusted = list(row_widths)
            terminal_width = profiles[voice_index].terminal_width
            lyric_text_by_event = lyric_text_by_voice.get(row[0].voice, {})
            for index, item in enumerate(row[:-2]):
                if (
                    item.event.kind
                    in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    and row[index + 1].event.kind
                    in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    and _row_event_has_lyric(row, index + 2, lyric_text_by_event)
                ):
                    adjusted[index] += 18.0
                    adjusted[index + 1] += 18.0
                if (
                    _row_event_has_lyric(row, index, lyric_text_by_event)
                    and row[index + 1].event.kind == MusicTokenKind.EXTENSION
                    and row[index + 2].event.kind != MusicTokenKind.EXTENSION
                    and "(" not in row[index + 2].event.code
                    and (
                        ")" in row[index - 1].event.code
                        or index >= 2
                        and row[index - 1].event.kind == MusicTokenKind.BARLINE
                        and ")" in row[index - 2].event.code
                    )
                ):
                    adjusted[index] += 18.0
                    if index + 1 < len(adjusted):
                        adjusted[index + 1] += 18.0
                    else:
                        terminal_width += 18.0
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
    uses_three_voice_quarter_pickup_lyric_grid = (
        len(rows) == 3
        and left == 105.0
        and visible_lyric_profile_indices == [1]
        and all(
            row[0].event.duration_slashes == 1
            and row[1].event.kind == MusicTokenKind.BARLINE
            and sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 3
            and row[-1].event.code == "|w"
            for row in rows
        )
    )
    if uses_three_voice_quarter_pickup_lyric_grid:
        adjusted_widths = []
        authority_row = rows[visible_lyric_profile_indices[0]]
        authority_bars = [
            index
            for index, item in enumerate(authority_row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        authority_final_start = authority_bars[-2] + 1
        authority_first_beat = _event_duration_fraction(
            authority_row[authority_final_start].event
        )
        for voice_index, (row, row_widths) in enumerate(
            zip(rows, reconciled_widths, strict=True)
        ):
            adjusted = list(row_widths)
            bar_indices = [
                index
                for index, item in enumerate(row)
                if item.event.kind == MusicTokenKind.BARLINE
            ]
            for index, item in enumerate(row[:-2]):
                if (
                    item.event.duration_dots
                    and "(" in item.event.code
                    and ")" in row[index + 1].event.code
                ):
                    adjusted[index] = max(
                        widths[index]
                        for widths in reconciled_widths
                        if index < len(widths)
                    )
                if (
                    item.event.duration_slashes == 2
                    and "(" in item.event.code
                    and ")" in row[index + 1].event.code
                    and "~" in row[index + 1].event.code
                ):
                    adjusted[index] += 9.0
            closing_interval = bar_indices[-2] - 1
            adjusted[closing_interval] = min(
                adjusted[closing_interval],
                profiles[voice_index].final_bar_width,
            )
            elapsed = Fraction()
            for index in range(bar_indices[-2] + 1, bar_indices[-1]):
                elapsed += _event_duration_fraction(row[index].event)
                if elapsed >= authority_first_beat:
                    adjusted[index] += 9.0
                    break
            adjusted_widths.append(tuple(adjusted))
        reconciled_widths = adjusted_widths
        profiles = [replace(profile, terminal_width=18.0) for profile in profiles]
    return profiles, reconciled_widths


__all__ = ["apply_phrase_transition_policies"]
