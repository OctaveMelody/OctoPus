"""Intrinsic event-width models, lyric metrics, and profile assembly."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent

# Dynamic and ornament markings are glyph overlays: they do not change the
# note-to-barline layout step. Shared multi-row systems align barline columns
# (oracle probes E1-E3 on a standalone two-voice 2/4 system show f/mf/sby/yc
# terminals all at the plain 25.2 step, while zkh/ykh keep their dedicated
# reserves). Single-row syllabic layouts take the same plain 25.2 step for a
# dynamic/trill-marked note directly before a barline regardless of what
# precedes it: oracle probes on Half-Pot-of-Yarn p1 (series J/Q/S/T,
# 2026-09-01) show sby/p/mp terminals at the 25.2 step after notes, rests,
# paren groups, in both 2/4 and 4/4, with or without second endings or
# lyrics. Accent (slur) marks keep the full 27.0 reserve unless a rest
# precedes the note — Half-Pot p1's exact shy/xhy rows pin that at 30.6.
# (The earlier "note-preceded sby stays at 27.0" reading of
# Night-In-Ulaanbaatar and I-Want-You was wrong: those rows resolve to 25.2
# through the late terminal release rules, which now guard against
# double-firing.)
_OVERLAY_DECORATIONS = frozenset(
    {
        "f",
        "ff",
        "mf",
        "mp",
        "p",
        "pp",
        "sby",
        "shy",
        "xhy",
        "sby3",
        "sby5",
        "sby7",
        "shy3",
        "shy4",
        "shy6",
    }
)
@dataclass(frozen=True, slots=True)
class IntrinsicWidthContext:
    """Row-level structural flags used for each intrinsic interval."""

    duration_group_members: frozenset[int]
    duration_group_terminals: frozenset[int]
    lyric_size: int
    connector_split_positions: frozenset[int] = frozenset()
    left_hook_group_terminals: frozenset[int] = frozenset()
    row_spanning_hooks: bool = False
    uses_compact_latin_bilingual_profile: bool = False
    uses_latin_dual_verse_clearance: bool = False
    uses_compound_meter: bool = False
    shares_barline_columns: bool = False
    lyric_host_positions: frozenset[int] = frozenset()

def lyric_clearance(
    texts: Sequence[str],
    *,
    lyric_size: int,
) -> tuple[float, bool, bool]:
    """Return width, long-ASCII flag, and parenthetical-wide flag for lyric texts."""
    widths: list[tuple[float, bool, bool]] = []
    for text in texts:
        text = text.rstrip("，。！？、；：")
        ascii_characters = sum(char.isascii() for char in text)
        wide_characters = sum(
            unicodedata.east_asian_width(char) in {"W", "F"}
            for char in text
            if not char.isspace()
        )
        has_long_ascii = ascii_characters >= 3
        has_parenthetical_wide = (
            wide_characters > 0
            and (text.startswith("(") or text.endswith(")"))
        )
        width = 10.0 * ascii_characters if has_long_ascii else 0.0
        width += 20.0 * (len(text) - len(text.rstrip("\u3000")))
        if has_parenthetical_wide:
            enclosure_width = (
                20.0 * (wide_characters + 1)
                if text.startswith("(") and text.endswith(")")
                else 20.0 * wide_characters + 10.0 * ascii_characters
            )
            width = max(width, enclosure_width)
        if wide_characters and (has_long_ascii or wide_characters >= 2):
            width += max(
                23.6 * wide_characters,
                20.0 * wide_characters + lyric_size / 2.0,
            )
        widths.append((width, has_long_ascii, has_parenthetical_wide))
    return max(widths, default=(0.0, False, False))

def terminal_event_width(texts: Sequence[str], *, default: float) -> float:
    """Return the maximum terminal width implied by lyric text or a default."""
    widths = [default]
    for text in texts:
        text = text.rstrip("，。！？、；：")
        ascii_characters = sum(char.isascii() for char in text)
        wide_characters = sum(
            unicodedata.east_asian_width(char) in {"W", "F"}
            for char in text
            if not char.isspace()
        )
        if ascii_characters >= 3:
            widths.append(10.0 * ascii_characters)
        if wide_characters >= 2:
            widths.append(20.0 * wide_characters)
    return max(widths)

def intrinsic_event_width(
    row: Sequence[LayoutEvent],
    index: int,
    *,
    lyric_texts: tuple[str, ...],
    next_lyric_texts: tuple[str, ...],
    context: IntrinsicWidthContext,
) -> float:
    """Return one intrinsic interval width while preserving source branch order."""
    duration_group_members = context.duration_group_members
    duration_group_terminals = context.duration_group_terminals
    lyric_size = context.lyric_size
    connector_split_positions = context.connector_split_positions
    left_hook_group_terminals = context.left_hook_group_terminals
    row_spanning_hooks = context.row_spanning_hooks
    uses_compact_latin_bilingual_profile = context.uses_compact_latin_bilingual_profile
    uses_latin_dual_verse_clearance = context.uses_latin_dual_verse_clearance
    uses_compound_meter = context.uses_compound_meter
    item = row[index]
    event = item.event
    next_event = row[index + 1].event
    if event.kind == MusicTokenKind.BARLINE:
        opens_beamed_left_hook = "zkh" in next_event.decorations and (
            "bc" in next_event.decorations or uses_compound_meter
        )
        width = (
            0.0
            if index == 0
            and (
                event.code in {"|n", "|n&hs"}
                or event.code.startswith("|n[")
            )
            else 34.2
            if (
                index == 0
                and event.code.startswith("|[")
                and "zkh" in next_event.decorations
            )
            else 27.0
            if index == 0 and "'p:" in event.code and "zkh" in next_event.decorations
            else 18.0
            if index == 0 and "'p:" in event.code
            else 43.2
            if "'p:" in event.code
            else 34.2
            if opens_beamed_left_hook
            else 25.2
        )
        if (
            "'p:" in event.code
            and row[-1].event.code != "|w"
            and sum(
                item.event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                for item in row[:-1]
            )
            < 6
            and not (
                row[-1].event.code == "|]/"
                and any(
                    "zkh" in later.event.decorations for later in row[index + 1 :]
                )
            )
            and any("'p:" in prior.event.code for prior in row[:index])
        ):
            width += 9.0
    elif _uses_closed_extension_reserve(row, index, context=context):
        width = 45.0
    elif (
        next_event.code == "|w"
        and event.kind == MusicTokenKind.EXTENSION
        and "ykh" in event.decorations
    ):
        width = 18.0
    elif (
        next_event.kind == MusicTokenKind.BARLINE
        and set(event.decorations) <= {"yc", "rit"} | _OVERLAY_DECORATIONS
        and (
            context.shares_barline_columns
            or not event.decorations
            or set(event.decorations) <= {"yc", "rit"}
            or index > 0
            and row[index - 1].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
        )
    ):
        width = (
            34.2
            if event.duration_dots
            and (
                any(lyric_texts)
                or row_spanning_hooks
                or uses_compound_meter
                and (
                    ")" in event.code
                    or event.kind
                    in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                    or not _inside_dsb_block(row, index)
                )
            )
            else 25.2
        )
    elif (
        event.kind == MusicTokenKind.EXTENSION
        and "zkh" in next_event.decorations
        and (
            index + 2 < len(row)
            and "ykh" in row[index + 2].event.decorations
            or (
                row[-1].event.code == "|]/"
                and sum("'p:" in item.event.code for item in row) >= 2
            )
        )
    ):
        width = 36.0
    elif any(
        "~" in text
        for text in (event.source_code, event.render_code, event.code, event.raw)
        if text
    ):
        width = 18.0
    elif event.code == "8" and "zkh" in next_event.decorations:
        width = 36.0
    elif any(
        ":tuplet:" in role and role.endswith((":start", ":inside"))
        for role in event.construct_roles
    ):
        width = 18.0
    elif (
        event.duration_dots
        and event.duration_slashes
        and any(lyric_texts)
        and next_event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
    ):
        width = 36.0
    elif index in duration_group_members and index not in duration_group_terminals:
        width = 27.0 if event.duration_dots else 18.0
    elif event.duration_dots and not event.duration_slashes:
        width = 36.0
    else:
        width = 27.0
    if uses_compound_meter and "shy" in event.decorations and event.duration_dots:
        width += 5.4
    if "zkh" in event.decorations and not (
        index in duration_group_members and index not in duration_group_terminals
    ):
        width += 7.2 if next_event.kind == MusicTokenKind.BARLINE else 9.0
    if "ykh" in event.decorations:
        width += 7.2 if next_event.kind == MusicTokenKind.BARLINE else 9.0
    # Accent-mark trailing reserves (oracle-decoded on Half-Pot-of-Yarn p1):
    # a shy/xhy note holds extra space before the following step — five-point-
    # four inside the measure, three-point-six across a barline.  Compound
    # meters keep their own dotted-shy rule above.
    if (
        not uses_compound_meter
        and event.kind in {MusicTokenKind.NOTE, MusicTokenKind.REST}
        and ("shy" in event.decorations or "xhy" in event.decorations)
    ):
        width += 3.6 if next_event.kind == MusicTokenKind.BARLINE else 5.4
    if index in connector_split_positions:
        width += 9.0
    if index in left_hook_group_terminals:
        width += 9.0
    if (
        "(" in event.code
        and ")" in next_event.code
        and any(text.startswith("\u3000") for text in lyric_texts)
    ):
        width += lyric_size * 2.0 / 3.0
    lyric_width, has_long_ascii, has_parenthetical_wide = lyric_clearance(
        lyric_texts,
        lyric_size=lyric_size,
    )
    if (
        (uses_compact_latin_bilingual_profile or uses_latin_dual_verse_clearance)
        and len(lyric_texts) >= 2
    ):
        last_width, last_is_long, _last_is_parenthetical = lyric_clearance(
            (lyric_texts[-1],),
            lyric_size=lyric_size,
        )
        next_first_width = (
            lyric_clearance((next_lyric_texts[0],), lyric_size=lyric_size)[0]
            if len(next_lyric_texts) >= 2
            else 0.0
        )
        next_last_width = (
            lyric_clearance((next_lyric_texts[-1],), lyric_size=lyric_size)[0]
            if len(next_lyric_texts) >= 2
            else 0.0
        )
        if (
            index == 0
            and last_is_long
            or next_event.kind == MusicTokenKind.HIDDEN_REST
            and (uses_compact_latin_bilingual_profile or last_is_long)
            or not uses_compact_latin_bilingual_profile
            and "(" in event.code
            and ")" in next_event.code
            or last_is_long
            and len(next_lyric_texts) >= 2
            and next_last_width >= next_first_width
        ):
            lyric_width = last_width
            has_long_ascii = last_is_long
    if (
        uses_compact_latin_bilingual_profile
        and has_long_ascii
        and len(lyric_texts) >= 2
        and next_event.kind == MusicTokenKind.BARLINE
        and index > 0
        and row[index - 1].event.kind
        not in {
            MusicTokenKind.REST,
            MusicTokenKind.HIDDEN_REST,
            MusicTokenKind.EXTENSION,
        }
    ):
        lyric_width, has_long_ascii, _last_is_parenthetical = lyric_clearance(
            (lyric_texts[-1],),
            lyric_size=lyric_size,
        )
    if (
        uses_compact_latin_bilingual_profile
        and event.duration_slashes
        and "~" in event.code
        and not any("&dsb_a" in later.event.code for later in row[index + 1 :])
    ):
        lyric_width = min(lyric_width, 30.0)
    if has_long_ascii and next_event.code.startswith("|z"):
        lyric_width = min(lyric_width, 30.0)
    if (has_long_ascii or has_parenthetical_wide) and (
        index in duration_group_terminals
        or (
            event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and not event.duration_slashes
        )
    ):
        lyric_width += (
            7.2
            if next_event.kind == MusicTokenKind.BARLINE
            or ")" in event.code
            and event.duration_dots
            else 9.0
        )
    return max(width, lyric_width)


def _inside_dsb_block(row: Sequence[LayoutEvent], index: int) -> bool:
    """Return whether the event sits inside an open ``{dsb ...}`` block.

    A block opens at the barline carrying the ``&dsb_a`` anchor and stays
    open across consecutive ``dsb-tail`` barlines; the first ordinary
    barline before the event (with no anchor further back) ends it.
    """
    position = index - 1
    while position >= 0:
        item = row[position]
        if item.event.kind != MusicTokenKind.BARLINE:
            position -= 1
            continue
        if "&dsb_a" in (item.event.code or ""):
            return all(
                row[later].block == "dsb-tail"
                for later in range(position + 1, index)
                if row[later].event.kind == MusicTokenKind.BARLINE
            )
        if item.block != "dsb-tail":
            return False
        position -= 1
    return False


def is_closed_extension_span(row: Sequence[LayoutEvent], index: int) -> bool:
    """Return whether an extension has the legacy closed-span syntax."""
    return _closed_extension_span_indices(row, index) is not None


def _closed_extension_span_indices(
    row: Sequence[LayoutEvent],
    index: int,
) -> tuple[int, int] | None:
    if row[index].event.kind == MusicTokenKind.EXTENSION:
        host_index = index - 1
        closing_index = index + 1
    elif index + 2 < len(row) and row[index + 1].event.kind == MusicTokenKind.EXTENSION:
        host_index = index
        closing_index = index + 2
    else:
        return None
    if host_index < 0 or closing_index >= len(row):
        return None
    host_code = row[host_index].event.code
    opening_count = host_code.count("(")
    closing_count = row[closing_index].event.code.count(")")
    if not (
        0 < closing_count <= opening_count
        and "zkh" not in row[host_index].event.decorations
        and (opening_count >= 2 or "'" in row[host_index].event.code)
    ):
        return None
    return host_index, closing_index


def _uses_closed_extension_reserve(
    row: Sequence[LayoutEvent],
    index: int,
    *,
    context: IntrinsicWidthContext,
) -> bool:
    """Admit the 45-unit span reserve only for lyric/shared projection owners."""
    indices = _closed_extension_span_indices(row, index)
    if indices is None:
        return False
    host_index, _closing_index = indices
    return (
        context.shares_barline_columns
        or host_index in context.lyric_host_positions
    )


def closed_extension_terminal_release(
    row: Sequence[LayoutEvent],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    *,
    shares_barline_columns: bool,
) -> float:
    """Return interior span width released into the terminal filler budget."""
    if shares_barline_columns:
        return 0.0
    lyric_host_positions = frozenset(
        index for index, texts in enumerate(lyric_texts_by_position) if any(texts)
    )
    released_intervals = 0
    for index in range(len(row) - 1):
        indices = _closed_extension_span_indices(row, index)
        if indices is None:
            continue
        host_index, _closing_index = indices
        if host_index not in lyric_host_positions:
            released_intervals += 1
    return 18.0 * released_intervals

def assemble_intrinsic_widths(
    row: Sequence[LayoutEvent],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
    *,
    duration_group_members: frozenset[int],
    duration_group_terminals: frozenset[int],
    lyric_size: int,
    connector_split_positions: frozenset[int],
    left_hook_group_terminals: frozenset[int],
    row_spanning_hooks: bool,
    uses_compact_latin_bilingual_profile: bool,
    uses_latin_dual_verse_clearance: bool,
    uses_compound_meter: bool,
    shares_barline_columns: bool = False,
) -> list[float]:
    """Assemble widths for every non-terminal event interval in source order."""
    context = IntrinsicWidthContext(
        duration_group_members=duration_group_members,
        duration_group_terminals=duration_group_terminals,
        lyric_size=lyric_size,
        connector_split_positions=connector_split_positions,
        left_hook_group_terminals=left_hook_group_terminals,
        row_spanning_hooks=row_spanning_hooks,
        uses_compact_latin_bilingual_profile=uses_compact_latin_bilingual_profile,
        uses_latin_dual_verse_clearance=uses_latin_dual_verse_clearance,
        uses_compound_meter=uses_compound_meter,
        shares_barline_columns=shares_barline_columns,
        lyric_host_positions=frozenset(
            index for index, texts in enumerate(lyric_texts_by_position) if any(texts)
        ),
    )
    return [
        intrinsic_event_width(
            row,
            index,
            lyric_texts=lyric_texts_by_position[index],
            next_lyric_texts=lyric_texts_by_position[index + 1],
            context=context,
        )
        for index in range(len(row) - 1)
    ]

__all__ = [
    "IntrinsicWidthContext",
    "assemble_intrinsic_widths",
    "closed_extension_terminal_release",
    "intrinsic_event_width",
    "is_closed_extension_span",
    "lyric_clearance",
    "terminal_event_width",
]
