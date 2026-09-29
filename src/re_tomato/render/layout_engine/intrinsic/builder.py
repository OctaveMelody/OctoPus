"""Build the ordered intrinsic-width profile for one syllabic row."""

from __future__ import annotations

import unicodedata
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent, PageMetrics
from ..duration_groups import duration_group_positions as _duration_group_positions
from ..hidden.hidden_streams import (
    event_duration_fraction as _event_duration_fraction,
)
from ..profiles import LegacyIntrinsicProfile as _LegacyIntrinsicProfile
from ..streams import first_meter as _first_meter
from ..streams import meter_beat_duration as _meter_beat_duration
from ..streams import uses_compound_meter as _uses_compound_meter
from .profile import (
    apply_accidental_reserve_mutation as _apply_accidental_reserve_mutation,
)
from .profile import (
    apply_cjk_dual_verse_width_adjustments as _apply_cjk_dual_verse_width_adjustments,
)
from .profile import (
    apply_compound_accidental_continuation_correction as _apply_compound_continuation_correction,
)
from .profile import (
    apply_dsb_overlay_width_corrections as _apply_dsb_overlay_width_corrections,
)
from .profile import (
    apply_late_terminal_width_corrections as _apply_late_terminal_width_corrections,
)
from .profile import (
    apply_pickup_overlay_width_correction as _apply_pickup_overlay_width_correction,
)
from .profile import (
    classify_accidental_reserve_destination as _classify_accidental_reserve_destination,
)
from .profile import (
    classify_intrinsic_lyric_flags as _classify_intrinsic_lyric_flags,
)
from .profile import (
    collect_intrinsic_lyric_inputs as _collect_intrinsic_lyric_inputs,
)
from .profile import (
    source_shape_denominator_adjustment as _source_shape_denominator_adjustment,
)
from .profile import (
    terminal_lyric_texts as _terminal_lyric_texts,
)
from .profile import (
    uses_pickup_second_ending_overlay as _uses_pickup_second_ending_overlay,
)
from .terminal import (
    DUAL_VERSE_INTERNAL_XHY_TERMINAL_RESERVE as _DUAL_VERSE_INTERNAL_XHY_TERMINAL_RESERVE,
)
from .terminal import (
    DUAL_VERSE_XHY_TERMINAL_RESERVE as _DUAL_VERSE_XHY_TERMINAL_RESERVE,
)
from .terminal import (
    apply_compact_terminal_denominator_adjustment as _apply_compact_terminal_denominator_adjustment,
)
from .terminal import (
    classify_terminal_profile_widths as _classify_terminal_profile_widths,
)
from .terminal import (
    dual_verse_xhy_terminal_transfer_index as _dual_verse_xhy_terminal_transfer_index,
)
from .terminal import (
    select_terminal_lyric_width as _select_terminal_lyric_width,
)
from .terminal import (
    terminal_decoration_denominator_reserve as _terminal_decoration_denominator_reserve,
)
from .terminal import (
    terminal_lyric_verse_count as _terminal_lyric_verse_count,
)
from .terminal import (
    uses_compact_terminal_lyric_run as _uses_compact_terminal_lyric_run,
)
from .terminal import (
    uses_dual_verse_internal_xhy_terminal_reserve as _uses_dual_verse_internal_xhy_terminal_reserve,
)
from .terminal import (
    uses_normal_terminal_grid as _uses_normal_terminal_grid,
)
from .terminal import (
    uses_rit_extension_terminator as _uses_rit_extension_terminator,
)
from .terminal import (
    uses_terminal_double_extension_lyric_run as _uses_terminal_double_extension_lyric_run,
)
from .widths import assemble_intrinsic_widths as _assemble_intrinsic_widths
from .widths import closed_extension_terminal_release as _closed_extension_terminal_release


def build_legacy_intrinsic_profile(
    row: list[LayoutEvent],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
    compact_latin_bilingual: bool | None = None,
    shares_barline_columns: bool = False,
) -> _LegacyIntrinsicProfile:
    """Build the intrinsic width profile for one row — the per-event natural widths
    before any shared-system reconciliation.

    Aggregates every input that shapes a row's natural geometry: compound-meter
    handling, compact Latin-bilingual profiles, lyric text collection (including
    dual-verse clearance), duration-group membership/terminals, and wide-glyph
    overflow. The resulting profile is the baseline that authority/reserve policies
    adjust; its fields are evidence-pinned to the reference output."""
    uses_compound_meter = _uses_compound_meter(metrics.time_sig)
    uses_compact_latin_bilingual_profile = (
        _is_compact_latin_bilingual_profile(metrics, lyric_text_by_event)
        if compact_latin_bilingual is None
        else compact_latin_bilingual
    )
    lyric_texts_by_position, uses_latin_dual_verse_clearance = _collect_intrinsic_lyric_inputs(
        row,
        lyric_text_by_event,
    )
    duration_group_members, duration_group_terminals = _duration_group_positions(
        row,
        beat_duration=_meter_beat_duration(metrics.time_sig),
    )
    if uses_compound_meter:
        duration_group_terminals = _suppress_in_hook_span_terminals(
            row,
            duration_group_members,
            duration_group_terminals,
        )
    left_hook_group_terminals = _legacy_left_hook_group_terminals(
        row,
        duration_group_members=duration_group_members,
        duration_group_terminals=duration_group_terminals,
        uses_compound_meter=uses_compound_meter,
    )
    row_spanning_hooks = (
        "zkh" in row[0].event.decorations
        and "ykh" in row[-2].event.decorations
    )
    connector_split_positions = frozenset(
        index
        for index in range(len(row) - 1)
        if _is_legacy_connector_split(
            row,
            index,
            duration_group_members=duration_group_members,
            duration_group_terminals=duration_group_terminals,
            lyric_texts=lyric_texts_by_position[index],
            lyric_texts_by_position=lyric_texts_by_position,
            uses_compound_meter=uses_compound_meter,
        )
    )
    widths = _assemble_intrinsic_widths(
        row,
        lyric_texts_by_position,
        duration_group_members=duration_group_members,
        duration_group_terminals=duration_group_terminals,
        lyric_size=metrics.lyric_size,
        uses_compact_latin_bilingual_profile=uses_compact_latin_bilingual_profile,
        uses_latin_dual_verse_clearance=uses_latin_dual_verse_clearance,
        connector_split_positions=connector_split_positions,
        left_hook_group_terminals=left_hook_group_terminals,
        row_spanning_hooks=row_spanning_hooks,
        uses_compound_meter=uses_compound_meter,
        shares_barline_columns=shares_barline_columns,
    )
    closed_extension_terminal_release = _closed_extension_terminal_release(
        row,
        lyric_texts_by_position,
        shares_barline_columns=shares_barline_columns,
    )
    uses_pickup_second_ending_overlay = _uses_pickup_second_ending_overlay(row)
    _apply_pickup_overlay_width_correction(
        widths,
        enabled=uses_pickup_second_ending_overlay,
    )
    for index, item in enumerate(row[:-2]):
        next_item = row[index + 1]
        if (
            "(" in item.event.code
            and ")" in next_item.event.code
            and item.event.duration_slashes
            == next_item.event.duration_slashes
            and index + 1 in duration_group_terminals
            and index > 0
            and row[index - 1].event.accidental is not None
            and _has_single_cjk_lyric_anchor(lyric_texts_by_position[index])
            and not any(lyric_texts_by_position[index + 1])
        ):
            widths[index] -= 3.6
            widths[index + 1] += 3.6
    _apply_cjk_dual_verse_width_adjustments(
        widths,
        lyric_texts_by_position,
        lyric_size=metrics.lyric_size,
        enabled=_uses_cjk_dual_verse_four_four_grid(metrics, lyric_text_by_event),
    )
    if (
        len(row) > 1
        and row[0].event.code.startswith("|z")
        and "zkh" in row[1].event.decorations
    ):
        widths[0] += 9.0
    _apply_dsb_overlay_width_corrections(
        widths,
        row,
        lyric_texts_by_position,
        uses_compound_meter=uses_compound_meter,
        uses_latin_dual_verse_clearance=uses_latin_dual_verse_clearance,
    )
    terminal_accidental_reserve = 0.0
    for index, item in enumerate(row[:-1]):
        if index == 0 or item.event.accidental is None:
            continue
        reserve_destination = _classify_accidental_reserve_destination(
            row,
            index,
            duration_group_terminals=duration_group_terminals,
            lyric_texts_by_position=lyric_texts_by_position,
            uses_compound_meter=uses_compound_meter,
            uses_compact_latin_bilingual_profile=uses_compact_latin_bilingual_profile,
            left=left,
            has_single_cjk_lyric_anchor=_has_single_cjk_lyric_anchor,
        )
        terminal_accidental_reserve = _apply_accidental_reserve_mutation(
            widths,
            row,
            index,
            reserve_destination,
            lyric_texts_by_position=lyric_texts_by_position,
            uses_compact_latin_bilingual_profile=uses_compact_latin_bilingual_profile,
            terminal_accidental_reserve=terminal_accidental_reserve,
        )
    _apply_compound_continuation_correction(
        widths,
        row,
        uses_compound_meter=uses_compound_meter,
    )
    uses_rit_extension_terminator = _uses_rit_extension_terminator(row)
    final_bar_width, default_terminal_event_width = _classify_terminal_profile_widths(
        row,
        left=left,
        note_start_x=metrics.note_start_x,
        uses_compound_meter=uses_compound_meter,
        uses_rit_extension_terminator=uses_rit_extension_terminator,
    )
    terminal_lyrics = _terminal_lyric_texts(row, lyric_text_by_event)
    has_any_lyric_text, has_dual_verse = _classify_intrinsic_lyric_flags(
        lyric_text_by_event,
    )
    terminal_event_width = _select_terminal_lyric_width(
        row,
        terminal_lyric_texts=terminal_lyrics,
        default_width=default_terminal_event_width,
        terminal_accidental_reserve=terminal_accidental_reserve,
        is_two_four_meter=_first_meter(metrics.time_sig) == (2, 4),
        uses_compound_meter=uses_compound_meter,
        has_any_lyric_text=has_any_lyric_text,
        has_dual_verse=has_dual_verse,
        left_hook_group_terminals=left_hook_group_terminals,
        has_single_cjk_lyric_anchor=_has_single_cjk_lyric_anchor,
    )
    denominator_adjustment = _source_shape_denominator_adjustment(
        row,
        uses_pickup_second_ending_overlay=uses_pickup_second_ending_overlay,
    ) + closed_extension_terminal_release
    lyric_verse_count = _terminal_lyric_verse_count(lyric_texts_by_position)
    uses_normal_terminal_grid = _uses_normal_terminal_grid(row)
    denominator_adjustment = _apply_compact_terminal_denominator_adjustment(
        denominator_adjustment,
        uses_compound_meter=uses_compound_meter,
        uses_compact_terminal_lyric_run=_uses_compact_terminal_lyric_run(
            row,
            lyric_text_by_event,
        ),
    )
    _apply_late_terminal_width_corrections(
        widths,
        row,
        lyric_texts_by_position,
        lyric_verse_count=lyric_verse_count,
        uses_normal_terminal_grid=uses_normal_terminal_grid,
        uses_terminal_double_extension_lyric_run=_uses_terminal_double_extension_lyric_run(
            row,
            lyric_text_by_event,
            has_fullwidth_trailing_punctuation=_has_fullwidth_trailing_punctuation,
        ),
    )
    uses_dual_verse_xhy_terminal_transfer = (
        _dual_verse_xhy_terminal_transfer_index(row, lyric_texts_by_position)
        is not None
    )
    uses_dual_verse_internal_xhy_terminal_reserve = (
        _uses_dual_verse_internal_xhy_terminal_reserve(
            row,
            lyric_texts_by_position,
        )
    )
    return _LegacyIntrinsicProfile(
        interval_widths=tuple(widths[:-1]),
        raw_terminal_width=widths[-1],
        terminal_width=(
            terminal_event_width
            + _terminal_decoration_denominator_reserve(row)
            + (
                _DUAL_VERSE_XHY_TERMINAL_RESERVE
                if uses_dual_verse_xhy_terminal_transfer
                else 0.0
            )
            + (
                _DUAL_VERSE_INTERNAL_XHY_TERMINAL_RESERVE
                if uses_dual_verse_internal_xhy_terminal_reserve
                else 0.0
            )
        ),
        final_bar_width=final_bar_width,
        denominator_adjustment=denominator_adjustment,
    )








def _is_compact_latin_bilingual_profile(
    metrics: PageMetrics,
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
) -> bool:
    return (
        metrics.note_start_x == 53.0
        and metrics.lyric_size == 16
        and any(len(texts) >= 2 for texts in lyric_text_by_event.values())
        and all(
            unicodedata.east_asian_width(character) not in {"W", "F"}
            for texts in lyric_text_by_event.values()
            for text in texts
            for character in text
        )
    )


def _uses_cjk_dual_verse_four_four_grid(
    metrics: PageMetrics,
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
) -> bool:
    return (
        _first_meter(metrics.time_sig) == (4, 4)
        and metrics.note_start_x == 83.0
        and any(len(texts) >= 2 for texts in lyric_text_by_event.values())
        and any(
            unicodedata.east_asian_width(character) in {"W", "F"}
            for texts in lyric_text_by_event.values()
            for text in texts
            for character in text
        )
        and not _is_compact_latin_bilingual_profile(metrics, lyric_text_by_event)
    )




def _suppress_in_hook_span_terminals(
    row: list[LayoutEvent],
    duration_group_members: frozenset[int],
    duration_group_terminals: frozenset[int],
) -> frozenset[int]:
    """Drop beat terminals that fall inside a zkh-to-ykh hook span.

    When a left hook opens on ``zkh`` and closes on a ``ykh`` inside the same
    measure, the reference keeps the plain step at the intermediate beat
    boundaries: the tied span visually ends at the closer, so only the
    closing group's terminal carries the extra reserve.
    """
    terminals = set(duration_group_terminals)
    for index in sorted(duration_group_members):
        if "zkh" not in row[index].event.decorations:
            continue
        closer = next(
            (
                position
                for position in range(index + 1, len(row))
                if row[position].event.kind == MusicTokenKind.BARLINE
                or "ykh" in row[position].event.decorations
            ),
            None,
        )
        if closer is None or "ykh" not in row[closer].event.decorations:
            continue
        terminals -= {t for t in terminals if index < t < closer}
    return frozenset(terminals)


def _legacy_left_hook_group_terminals(
    row: list[LayoutEvent],
    *,
    duration_group_members: frozenset[int],
    duration_group_terminals: frozenset[int],
    uses_compound_meter: bool,
) -> frozenset[int]:
    terminals: set[int] = set()
    for index in sorted(duration_group_members):
        if "zkh" not in row[index].event.decorations:
            continue
        # In compound meters the hook may close on a ykh event inside the
        # same measure; the reserve then belongs at that closing group's
        # terminal: the tied span visually ends there, not at an
        # intermediate beat boundary.
        closer = next(
            (
                position
                for position in range(index + 1, len(row))
                if row[position].event.kind == MusicTokenKind.BARLINE
                or "ykh" in row[position].event.decorations
            ),
            None,
        )
        closer_is_ykh = (
            closer is not None and "ykh" in row[closer].event.decorations
        )

        def _first_terminal_after(start: int, origin: int = index) -> int | None:
            return next(
                (
                    candidate
                    for candidate in sorted(duration_group_terminals)
                    if candidate > start
                    and not any(
                        item.event.kind == MusicTokenKind.BARLINE
                        for item in row[origin + 1 : candidate]
                    )
                ),
                None,
            )

        terminal = _first_terminal_after(index)
        if uses_compound_meter and closer is not None and closer_is_ykh:
            closing_terminal = next(
                (
                    candidate
                    for candidate in sorted(duration_group_terminals)
                    if candidate >= closer
                    and not any(
                        item.event.kind == MusicTokenKind.BARLINE
                        for item in row[index + 1 : candidate]
                    )
                ),
                None,
            )
            if closing_terminal is not None:
                terminal = closing_terminal
        if terminal is not None:
            terminals.add(terminal)
    return frozenset(terminals)


def _is_legacy_connector_split(
    row: list[LayoutEvent],
    index: int,
    *,
    duration_group_members: frozenset[int],
    duration_group_terminals: frozenset[int],
    lyric_texts: tuple[str, ...] = (),
    lyric_texts_by_position: list[tuple[str, ...]] | None = None,
    uses_compound_meter: bool = False,
) -> bool:
    if index == 0 or index not in duration_group_members:
        return False
    if index in duration_group_terminals:
        return False
    event = row[index].event
    previous = row[index - 1].event
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
        len(row),
    )
    group_positions = [
        position
        for position in range(measure_start, measure_end)
        if position in duration_group_members
    ]
    if (
        uses_compound_meter
        and len(group_positions) >= 6
        and lyric_texts_by_position is not None
    ):
        group_durations = [
            _event_duration_fraction(row[position].event)
            for position in group_positions
        ]
        half_duration = sum(group_durations, Fraction()) / 2
        elapsed = Fraction()
        midpoint = group_positions[-1]
        for position, duration in zip(group_positions, group_durations, strict=True):
            elapsed += duration
            if elapsed >= half_duration:
                midpoint = position
                break
        visible_anchors = [
            text
            for position in group_positions
            for text in lyric_texts_by_position[position]
            if text
        ]
        if (
            index == midpoint
            and len(visible_anchors) >= len(group_positions) - 2
            and all(
                len(text) == 1 and unicodedata.east_asian_width(text) in {"W", "F"}
                for text in visible_anchors
            )
        ):
            return True
    if event.duration_slashes != 1:
        return False
    if not previous.duration_dots or previous.duration_slashes:
        return False
    visible_lyrics = tuple(text for text in lyric_texts if text)
    if not visible_lyrics or not all(
        len(text) == 1 and unicodedata.east_asian_width(text) in {"W", "F"}
        for text in visible_lyrics
    ):
        return False
    has_tie = any(
        "~" in text
        for text in (event.source_code, event.render_code, event.code, event.raw)
        if text
    )
    return not has_tie or bool(event.duration_dots)








def _has_single_cjk_lyric_anchor(texts: tuple[str, ...]) -> bool:
    visible_texts = tuple(text for text in texts if text)
    return bool(visible_texts) and all(
        len(text) == 1 and unicodedata.east_asian_width(text) in {"W", "F"}
        for text in visible_texts
    )


def _has_fullwidth_trailing_punctuation(texts: tuple[str, ...]) -> bool:
    return any(text.endswith(("，", "。", "！", "？", "、", "；", "：")) for text in texts)

__all__ = ["build_legacy_intrinsic_profile"]
