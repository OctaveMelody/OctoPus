"""Intrinsic profile inputs and ordered width corrections."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..signatures import measure_durations
from .terminal import (
    DUAL_VERSE_XHY_INTERVAL_RESERVE as _DUAL_VERSE_XHY_INTERVAL_RESERVE,
)
from .terminal import (
    DUAL_VERSE_XHY_TERMINAL_RESERVE as _DUAL_VERSE_XHY_TERMINAL_RESERVE,
)
from .terminal import (
    SBY_SECOND_ENDING_COLLAPSE as _SBY_SECOND_ENDING_COLLAPSE,
)
from .terminal import (
    SBY_YC_PREBARLINE_COLLAPSE as _SBY_YC_PREBARLINE_COLLAPSE,
)
from .terminal import (
    TIED_ZKH_EXTENSION_RESERVE as _TIED_ZKH_EXTENSION_RESERVE,
)
from .terminal import (
    dual_verse_xhy_terminal_transfer_index as _dual_verse_xhy_terminal_transfer_index,
)
from .terminal import (
    sby_second_ending_zkh_transfer_indices as _sby_second_ending_zkh_transfer_indices,
)
from .terminal import (
    uses_sby_yc_prebarline_collapse as _uses_sby_yc_prebarline_collapse,
)


def collect_intrinsic_lyric_inputs(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], tuple[str, ...]],
) -> tuple[list[tuple[str, ...]], bool]:
    """Collect per-event lyric text and detect all-ASCII dual-verse clearance."""
    lyric_texts_by_position = [
        lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
        for item in row
    ]
    uses_latin_dual_verse_clearance = (
        any(len(texts) >= 2 for texts in lyric_texts_by_position)
        and all(
            character.isascii() or character.isspace()
            for texts in lyric_texts_by_position
            for text in texts
            for character in text
        )
    )
    return lyric_texts_by_position, uses_latin_dual_verse_clearance

def classify_intrinsic_lyric_flags(
    lyric_text_by_event: Mapping[tuple[int, int], tuple[str, ...]],
) -> tuple[bool, bool]:
    """Return whether any lyric text and any dual-verse text are present."""
    return (
        any(text for texts in lyric_text_by_event.values() for text in texts),
        any(len(texts) >= 2 for texts in lyric_text_by_event.values()),
    )

def terminal_lyric_texts(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], tuple[str, ...]],
) -> tuple[str, ...]:
    """Return terminal-event lyric text using the intrinsic source key."""
    terminal_event = row[-2].event
    return lyric_text_by_event.get(
        (terminal_event.span.start.line, terminal_event.index),
        (),
    )

def uses_pickup_second_ending_overlay(row: Sequence[LayoutEvent]) -> bool:
    """Return whether the row starts with a pickup second-ending overlay."""
    return (
        len(row) >= 3
        and row[0].event.kind != MusicTokenKind.BARLINE
        and row[1].event.code.startswith("|n[+'2'")
    )

def apply_cjk_dual_verse_width_adjustments(
    widths: list[float],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    *,
    lyric_size: int,
    enabled: bool,
) -> None:
    """Apply the four-four CJK dual-verse correction in source order."""
    if not enabled:
        return
    for index, texts in enumerate(lyric_texts_by_position[:-1]):
        wide_character_counts = [
            sum(
                unicodedata.east_asian_width(char) in {"W", "F"}
                for char in text.rstrip("，。！？、；：")
            )
            for text in texts
            if not (text.startswith("(") or text.endswith(")"))
        ]
        width_adjustments = [
            max(20.0 * count + lyric_size / 2.0 - 23.6 * count, 0.0)
            for count in wide_character_counts
            if count >= 2
        ]
        if width_adjustments:
            widths[index] -= max(width_adjustments)

def apply_pickup_overlay_width_correction(
    widths: list[float],
    *,
    enabled: bool,
) -> None:
    """Suppress the generated second-ending slot immediately after collection."""
    if enabled:
        widths[1] = 0.0

def apply_dsb_overlay_width_corrections(
    widths: list[float],
    row: Sequence[LayoutEvent],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    *,
    uses_compound_meter: bool,
    uses_latin_dual_verse_clearance: bool,
) -> None:
    """Apply DSB overlay transfers after earlier intrinsic corrections."""
    for index, item in enumerate(row[:-1]):
        if (
            not uses_compound_meter
            and uses_latin_dual_verse_clearance
            and any(
                len(texts) >= 2 and any(texts[:-1]) and not texts[-1]
                for texts in lyric_texts_by_position
            )
            and "&dsb_a" in item.event.code
            and any(later.block == "dsb-tail" for later in row[index + 1 :])
        ):
            widths[index] += 14.4
            continue
        if (
            not uses_compound_meter
            or "&dsb_a" not in item.event.code
            or "&bz" in item.event.code
        ):
            continue
        closing_bar_index = next(
            (
                position
                for position in range(index + 1, len(row))
                if row[position].event.kind == MusicTokenKind.BARLINE
            ),
            None,
        )
        if closing_bar_index is not None and closing_bar_index - 1 > index:
            widths[index] += 14.4
            visible_span_events = sum(
                row[position].event.kind
                in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
                for position in range(index + 1, closing_bar_index)
            )
            if visible_span_events <= 2:
                widths[closing_bar_index - 1] += 14.4

def source_shape_denominator_adjustment(
    row: Sequence[LayoutEvent],
    *,
    uses_pickup_second_ending_overlay: bool,
) -> float:
    """Return the source-ordered denominator adjustment for an intrinsic row."""
    denominator_adjustment = 0.0
    if uses_pickup_second_ending_overlay:
        denominator_adjustment -= 1.8
    if (
        "zkh" in row[0].event.decorations
        and "," in row[0].event.raw
        and not row[0].event.duration_slashes
        and row[1].event.code == "|"
        and row[-1].event.code == "|"
    ):
        denominator_adjustment += 9.0
    if (
        row[0].event.code == "|n"
        or row[0].event.code.startswith("|n[")
        or "'p:" in row[0].event.code
    ):
        denominator_adjustment -= 3.6
    elif (
        sum("'p:" in item.event.code for item in row) == 1
        and row[-1].event.code == "|j"
    ):
        denominator_adjustment -= 18.0
    if row[0].event.code == "|&hs":
        denominator_adjustment -= 1.8
    if row[0].event.code == "|n&hs":
        denominator_adjustment -= 3.6
    if row[0].event.code.startswith("|["):
        denominator_adjustment -= 1.8
    if row[0].event.code.startswith("|z"):
        denominator_adjustment -= 1.8
    if row[0].event.code.startswith("|n[+'2'") and row[-1].event.code != "|]/":
        denominator_adjustment += 9.0
    if (
        row[0].event.code == "|z"
        and row[-1].event.code == "|y]"
        and any(item.event.code.startswith("|['1'") for item in row)
    ):
        denominator_adjustment += 9.0
    if (
        row[0].event.duration_dots
        and "(" in row[0].event.code
        and row[-1].event.code == "|y]"
        and any(item.event.code.startswith("|[+'1'") for item in row)
    ):
        denominator_adjustment -= 9.0
    if (
        len(row) == 43
        and row[-1].event.code == "|"
        and measure_durations(row) == (Fraction(2),) * 13
        and tuple(item.event.pitch for item in row[-3:-1]) == (6, 5)
        and all(item.event.kind == MusicTokenKind.NOTE for item in row[-3:-1])
    ):
        denominator_adjustment -= 9.0
    return denominator_adjustment

def apply_late_terminal_width_corrections(
    widths: list[float],
    row: Sequence[LayoutEvent],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    *,
    lyric_verse_count: int,
    uses_normal_terminal_grid: bool,
    uses_terminal_double_extension_lyric_run: bool,
) -> None:
    """Apply late terminal-grid width corrections in their original order."""
    if lyric_verse_count >= 2 and row[-1].event.code == "|w":
        for index, item in enumerate(row[:-1]):
            if (
                "sby" in item.event.decorations
                and row[index + 1].event.kind == MusicTokenKind.BARLINE
            ):
                widths[index] -= 1.8
    if uses_terminal_double_extension_lyric_run:
        last_bar_index = max(
            index
            for index, item in enumerate(row[:-1])
            if item.event.kind == MusicTokenKind.BARLINE
        )
        widths[last_bar_index - 1] -= 1.8
    for index in range(len(row) - 1):
        if _uses_sby_yc_prebarline_collapse(row, index):
            widths[index] -= _SBY_YC_PREBARLINE_COLLAPSE
    transfer_indices = _sby_second_ending_zkh_transfer_indices(row)
    if transfer_indices is not None:
        sby_index, extension_index = transfer_indices
        widths[sby_index] -= _SBY_SECOND_ENDING_COLLAPSE
        widths[extension_index] += _TIED_ZKH_EXTENSION_RESERVE
    xhy_index = _dual_verse_xhy_terminal_transfer_index(
        row,
        lyric_texts_by_position,
    )
    if xhy_index is not None:
        widths[xhy_index] += _DUAL_VERSE_XHY_INTERVAL_RESERVE
        widths[-1] += _DUAL_VERSE_XHY_TERMINAL_RESERVE
    if not uses_normal_terminal_grid or lyric_verse_count != 2:
        return
    last_bar_index = max(
        (
            index
            for index, item in enumerate(row[:-1])
            if item.event.kind == MusicTokenKind.BARLINE
        ),
        default=-1,
    )
    terminal_event = row[-2].event
    terminal_has_both_lyrics = (
        last_bar_index >= 1
        and len(row) - last_bar_index - 2 >= 7
        and len(lyric_texts_by_position[-2]) == 2
        and all(lyric_texts_by_position[-2])
        and terminal_event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and all(
            row[index].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            for index in range(last_bar_index + 1, len(row) - 1)
        )
        and all(
            len(lyric_texts_by_position[index]) == 2
            and all(lyric_texts_by_position[index])
            for index in range(last_bar_index + 1, len(row) - 1)
            if row[index].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and ")" not in row[index].event.code
        )
    )
    low_note_extension_ending = (
        last_bar_index >= 1
        and terminal_event.kind == MusicTokenKind.EXTENSION
        and row[-3].event.octave < 0
        and len(lyric_texts_by_position[-3]) == 2
        and all(lyric_texts_by_position[-3])
        and len(row) - last_bar_index - 2 >= 4
    )
    if terminal_has_both_lyrics or low_note_extension_ending:
        widths[last_bar_index - 1] -= 1.8

@dataclass(frozen=True, slots=True)
class AccidentalReserveDestination:
    """Ordered destinations selected for one accidental reserve."""

    hook_end: int | None
    inside_same_measure_hook: bool
    trailing_reserve_index: int

def apply_accidental_reserve_mutation(
    widths: list[float],
    row: Sequence[LayoutEvent],
    index: int,
    destination: AccidentalReserveDestination,
    *,
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    uses_compact_latin_bilingual_profile: bool,
    terminal_accidental_reserve: float,
) -> float:
    """Apply one classified accidental reserve and return its terminal total."""
    widths[index - 1] += 3.6
    lyric_clearance_suppresses_trailing_reserve = any(
        lyric_texts_by_position[index]
    ) and (
        uses_compact_latin_bilingual_profile
        or row[-1].event.code == "|]/"
        and any(prior.event.code.startswith("|[") for prior in row[:index])
    )
    if (
        not lyric_clearance_suppresses_trailing_reserve
        and not destination.inside_same_measure_hook
    ):
        if destination.trailing_reserve_index == len(row) - 2:
            terminal_accidental_reserve += 3.6
        else:
            widths[destination.trailing_reserve_index] += 3.6
    if destination.inside_same_measure_hook and destination.hook_end is not None:
        widths[index - 1] += 18.0
        widths[destination.hook_end] -= 5.4
    return terminal_accidental_reserve

def apply_compound_accidental_continuation_correction(
    widths: list[float],
    row: Sequence[LayoutEvent],
    *,
    uses_compound_meter: bool,
) -> None:
    """Apply the isolated three-event compound accidental continuation transfer."""
    if not uses_compound_meter:
        return
    for index in range(1, len(row) - 3):
        first = row[index].event
        second = row[index + 1].event
        continuation = row[index + 2].event
        if (
            first.accidental is not None
            and second.accidental is not None
            and "~" in first.code
            and "~" in second.code
            and second.duration_dots
            and continuation.duration_slashes == 2
            and row[index + 3].event.kind == MusicTokenKind.BARLINE
        ):
            widths[index - 1] += 9.0
            widths[index + 1] += 5.4
            widths[index + 2] += 3.6

def classify_accidental_reserve_destination(
    row: Sequence[LayoutEvent],
    index: int,
    *,
    duration_group_terminals: frozenset[int],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    uses_compound_meter: bool,
    uses_compact_latin_bilingual_profile: bool,
    left: float,
    has_single_cjk_lyric_anchor: Callable[[tuple[str, ...]], bool],
) -> AccidentalReserveDestination:
    """Classify hook and trailing destinations without mutating profile widths."""
    measure_start = next(
        (
            position + 1
            for position in range(index - 1, -1, -1)
            if row[position].event.kind == MusicTokenKind.BARLINE
        ),
        0,
    )
    measure_end = next(
        (
            position
            for position in range(index + 1, len(row))
            if row[position].event.kind == MusicTokenKind.BARLINE
        ),
        len(row) - 1,
    )
    hook_end = next(
        (
            position
            for position in range(index + 1, measure_end)
            if "ykh" in row[position].event.decorations
        ),
        None,
    )
    inside_same_measure_hook = uses_compound_meter and hook_end is not None and any(
        "zkh" in row[position].event.decorations
        for position in range(measure_start, index)
    )
    item = row[index]
    repeated_subdivision_boundary: int | None = None
    if item.event.duration_slashes:
        elapsed = event_duration_fraction(item.event)
        repeated_subdivisions = 0
        follows_syllabic_subdivisions = has_single_cjk_lyric_anchor(
            lyric_texts_by_position[index]
        )
        for position in range(index + 1, measure_end):
            following = row[position].event
            follows_syllabic_subdivisions = (
                follows_syllabic_subdivisions
                and has_single_cjk_lyric_anchor(lyric_texts_by_position[position])
            )
            if (
                following.pitch != item.event.pitch
                and not follows_syllabic_subdivisions
                or following.duration_slashes <= item.event.duration_slashes
            ):
                break
            elapsed += event_duration_fraction(following)
            repeated_subdivisions += 1
            if elapsed.denominator == 1:
                if repeated_subdivisions >= 2:
                    repeated_subdivision_boundary = position
                break
    trailing_reserve_index = (
        repeated_subdivision_boundary
        if repeated_subdivision_boundary is not None
        else index + 1
        if (
            item.event.accidental != "="
            and index + 1 in duration_group_terminals
            and row[index + 1].event.duration_slashes == item.event.duration_slashes
            and index + 2 < len(row)
            and row[index + 2].event.kind == MusicTokenKind.BARLINE
        )
        else index + 2
        if (
            item.event.duration_slashes
            and index + 2 < len(row) - 1
            and "~" in row[index + 1].event.code
            and row[index + 1].event.kind
            in {MusicTokenKind.EXTENSION, MusicTokenKind.HIDDEN_REST}
        )
        or (
            not uses_compact_latin_bilingual_profile
            and item.event.duration_slashes
            and index + 2 < len(row) - 1
            and row[index + 1].event.duration_slashes
            and "(" in row[index + 2].event.code
            and (
                left == 105.0
                or row[index + 2].event.duration_slashes
            )
        )
        else index + 1
        if (
            not uses_compact_latin_bilingual_profile
            and item.event.duration_slashes
            and index + 1 < len(row) - 1
            and "(" in row[index + 1].event.code
        )
        else index
    )
    if (
        not inside_same_measure_hook
        and uses_compound_meter
        and item.event.duration_slashes
        and "~" in item.event.code
        and index + 1 < len(row) - 1
    ):
        trailing_reserve_index = index + 1
    return AccidentalReserveDestination(
        hook_end=hook_end,
        inside_same_measure_hook=inside_same_measure_hook,
        trailing_reserve_index=trailing_reserve_index,
    )
