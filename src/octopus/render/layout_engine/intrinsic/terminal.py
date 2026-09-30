"""Intrinsic terminal shape, lyric-run, and width policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from .widths import terminal_event_width

TERMINAL_DECORATION_DENOMINATOR_RESERVE = 5.4
_TERMINAL_CLEARANCE_DECORATIONS = frozenset({"shy", "xhy"})
SBY_YC_PREBARLINE_COLLAPSE = 1.8
SBY_SECOND_ENDING_COLLAPSE = 1.8
TIED_ZKH_EXTENSION_RESERVE = 9.0
DUAL_VERSE_XHY_INTERVAL_RESERVE = 5.4
DUAL_VERSE_XHY_TERMINAL_RESERVE = 9.0
DUAL_VERSE_INTERNAL_XHY_TERMINAL_RESERVE = 9.0


def terminal_extension_run_length(row: Sequence[LayoutEvent]) -> int:
    """Count contiguous extension events immediately before the final barline."""
    terminal_extension_run = 0
    for item in reversed(row[:-1]):
        if item.event.kind != MusicTokenKind.EXTENSION:
            break
        terminal_extension_run += 1
    return terminal_extension_run

def uses_rit_extension_terminator(row: Sequence[LayoutEvent]) -> bool:
    """Return whether the terminal extension closes a ritardando construct."""
    if len(row) < 3:
        return False
    terminal_event = row[-2].event
    return (
        terminal_event.kind == MusicTokenKind.EXTENSION
        and ")" in row[-3].event.code
        and any("rit" in item.event.decorations for item in row)
    )

def classify_final_bar_width(
    row: Sequence[LayoutEvent],
    *,
    left: float,
    note_start_x: float,
    uses_compound_meter: bool,
    uses_rit_extension_terminator: bool,
    terminal_extension_run: int,
) -> float:
    """Return the ordered final-bar width before terminal lyric expansion."""
    terminal_event = row[-2].event
    final_bar_width = (
        16.2
        if row[0].event.code.startswith("|n[") and row[-1].event.code == "|j]"
        else 34.2
        if (
            row[-1].event.code == "|j"
            and left == note_start_x
            and (
                terminal_event.kind == MusicTokenKind.EXTENSION
                or "ykh" in terminal_event.decorations
            )
            and not uses_rit_extension_terminator
        )
        or (
            len(row) >= 3
            and "zkh" in row[-3].event.decorations
            and "ykh" in row[-2].event.decorations
        )
        else 25.2
    )
    if terminal_extension_run >= 2 and row[-1].event.code == "|j":
        final_bar_width = 25.2
    if (
        row[-1].event.code == "|w"
        and len(row) >= 4
        and event_duration_fraction(row[0].event) == Fraction(1, 4)
        and event_duration_fraction(row[1].event) == Fraction(1, 4)
        and row[2].event.kind == MusicTokenKind.BARLINE
        and sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 3
        and terminal_event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and not terminal_event.duration_dots
        and not terminal_event.duration_slashes
    ):
        final_bar_width = 16.2
    if (
        uses_compound_meter
        and row[-1].event.code == "|j"
        and "ykh" in terminal_event.decorations
        and any("zkh" in item.event.decorations for item in row[:-1])
    ):
        final_bar_width = 25.2
    return final_bar_width

def classify_default_terminal_event_width(
    row: Sequence[LayoutEvent],
    *,
    uses_rit_extension_terminator: bool,
    terminal_extension_run: int,
    starts_at_note_origin: bool,
    uses_compound_meter: bool = False,
) -> float:
    """Return the default terminal-event width before lyric expansion.

    A dotted rest closing a compound-meter row keeps the full 27.0 step in
    the denominator (the dot occupies its own beat slot), while plain rests
    and slashed notes keep the short 18.0 step.
    """
    terminal_event = row[-2].event
    return (
        (
            18.0
            if uses_rit_extension_terminator
            or (terminal_extension_run >= 2 and row[-1].event.code == "|j")
            else 27.0
            if "ykh" in terminal_event.decorations
            or (
                row[-1].event.code == "|j"
                and starts_at_note_origin
            )
            or (terminal_extension_run == 2 and "zkh" in row[0].event.decorations)
            else 18.0
        )
        if terminal_event.kind == MusicTokenKind.EXTENSION
        else (
            18.0
            if (
                terminal_event.kind
                in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
                and not terminal_event.decorations
                and not (uses_compound_meter and terminal_event.duration_dots)
            )
            or terminal_event.duration_slashes
            and "zkh" not in terminal_event.decorations
            and "zkh" not in row[0].event.decorations
            else 27.0
        )
    )

def classify_terminal_profile_widths(
    row: Sequence[LayoutEvent],
    *,
    left: float,
    note_start_x: float,
    uses_compound_meter: bool,
    uses_rit_extension_terminator: bool,
) -> tuple[float, float]:
    """Return final-bar and default-terminal widths before lyric expansion."""
    terminal_extension_run = terminal_extension_run_length(row)
    final_bar_width = classify_final_bar_width(
        row,
        left=left,
        note_start_x=note_start_x,
        uses_compound_meter=uses_compound_meter,
        uses_rit_extension_terminator=uses_rit_extension_terminator,
        terminal_extension_run=terminal_extension_run,
    )
    default_terminal_event_width = classify_default_terminal_event_width(
        row,
        uses_rit_extension_terminator=uses_rit_extension_terminator,
        terminal_extension_run=terminal_extension_run,
        starts_at_note_origin=left == note_start_x,
        uses_compound_meter=uses_compound_meter,
    )
    return final_bar_width, default_terminal_event_width


def terminal_decoration_denominator_reserve(row: Sequence[LayoutEvent]) -> float:
    """Return terminal clearance owned by a marked final note.

    ``shy`` and ``xhy`` already widen the step that follows an in-measure
    note.  When the marked note is the final timed event, the same clearance
    belongs to the terminal denominator reserve because the following item is
    the closing barline rather than another projected interval.
    """
    if len(row) < 3 or row[-1].event.kind != MusicTokenKind.BARLINE:
        return 0.0
    terminal_event = row[-2].event
    if terminal_event.kind not in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}:
        return 0.0
    if not _TERMINAL_CLEARANCE_DECORATIONS.intersection(terminal_event.decorations):
        return 0.0
    return TERMINAL_DECORATION_DENOMINATOR_RESERVE


def uses_sby_yc_prebarline_collapse(
    row: Sequence[LayoutEvent],
    index: int,
) -> bool:
    """Return whether a stacked ``sby``/``yc`` note owns a short barline step."""
    if index < 0 or index + 1 >= len(row):
        return False
    event = row[index].event
    return (
        event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and {"sby", "yc"}.issubset(event.decorations)
        and row[index + 1].event.kind == MusicTokenKind.BARLINE
    )


def sby_second_ending_zkh_transfer_indices(
    row: Sequence[LayoutEvent],
) -> tuple[int, int] | None:
    """Return the source-ordered indices for the joint second-ending transfer."""
    sby_index = next(
        (
            index
            for index, item in enumerate(row[:-1])
            if (
                item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
                and "sby" in item.event.decorations
                and row[index + 1].event.kind == MusicTokenKind.BARLINE
                and row[index + 1].event.code.startswith("|['")
            )
        ),
        None,
    )
    if sby_index is None:
        return None
    for index in range(sby_index + 2, len(row) - 1):
        event = row[index].event
        next_event = row[index + 1].event
        if (
            event.kind == MusicTokenKind.EXTENSION
            and next_event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            and "zkh" in next_event.decorations
            and "~" in next_event.code
        ):
            return sby_index, index
    return None


def dual_verse_xhy_terminal_transfer_index(
    row: Sequence[LayoutEvent],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
) -> int | None:
    """Return the nonterminal ``xhy`` owner for the dual-verse terminal transfer.

    The source shape is deliberately narrow: a closing plain barline follows a
    marked terminal note, exactly one earlier ``xhy`` note is present, an
    earlier event carries ``ykh``, and at least one event owns two nonempty lyric
    verses.  The two width reserves are applied together by the intrinsic
    profile and late-width stages.
    """
    if len(row) < 4 or len(lyric_texts_by_position) != len(row):
        return None
    if row[-1].event.kind != MusicTokenKind.BARLINE or row[-1].event.code != "|":
        return None
    terminal_event = row[-2].event
    if (
        terminal_event.kind not in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        or "shy" not in terminal_event.decorations
    ):
        return None
    if not any(
        len(texts) >= 2 and all(texts)
        for texts in lyric_texts_by_position
    ):
        return None
    xhy_indices = [
        index
        for index, item in enumerate(row[:-2])
        if (
            item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and "xhy" in item.event.decorations
        )
    ]
    if len(xhy_indices) != 1:
        return None
    xhy_index = xhy_indices[0]
    if not any("ykh" in item.event.decorations for item in row[:xhy_index]):
        return None
    return xhy_index


def uses_dual_verse_internal_xhy_terminal_reserve(
    row: Sequence[LayoutEvent],
    lyric_texts_by_position: Sequence[tuple[str, ...]],
) -> bool:
    """Return whether a dual-verse row owns the internal-``xhy`` terminal reserve."""
    if len(row) < 6 or len(lyric_texts_by_position) != len(row):
        return False
    if row[-1].event.kind != MusicTokenKind.BARLINE or row[-1].event.code != "|":
        return False
    terminal_event = row[-2].event
    if (
        terminal_event.kind not in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        or terminal_event.decorations
    ):
        return False
    if not any(
        len(texts) >= 2 and all(texts)
        for texts in lyric_texts_by_position
    ):
        return False
    xhy_indices = [
        index
        for index, item in enumerate(row[:-2])
        if (
            item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and "xhy" in item.event.decorations
            and row[index + 1].event.kind == MusicTokenKind.BARLINE
        )
    ]
    return len(xhy_indices) == 1


def select_terminal_lyric_width(
    row: Sequence[LayoutEvent],
    *,
    terminal_lyric_texts: tuple[str, ...],
    default_width: float,
    terminal_accidental_reserve: float,
    is_two_four_meter: bool,
    uses_compound_meter: bool,
    has_any_lyric_text: bool,
    has_dual_verse: bool,
    left_hook_group_terminals: frozenset[int],
    has_single_cjk_lyric_anchor: Callable[[tuple[str, ...]], bool],
) -> float:
    """Select terminal lyric width and preserve the ordered terminal overrides."""
    terminal_event = row[-2].event
    width = terminal_event_width(terminal_lyric_texts, default=default_width)
    width += terminal_accidental_reserve
    if (
        is_two_four_meter
        and row[-1].event.code == "|"
        and terminal_event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and not terminal_event.duration_dots
        and not terminal_event.duration_slashes
        and has_single_cjk_lyric_anchor(terminal_lyric_texts)
    ):
        width = 18.0
    if (
        uses_compound_meter
        and row[-1].event.code == "|"
        and "zkh" in row[0].event.decorations
        and terminal_event.duration_dots
        and ")" in terminal_event.code
        and not has_any_lyric_text
    ):
        width = max(width, 36.0)
    if (
        uses_compound_meter
        and "ykh" in terminal_event.decorations
        and terminal_event.duration_slashes
        and terminal_lyric_texts
        and not any(terminal_lyric_texts)
    ):
        width += 3.6
    if row[0].event.code == "|n&hs":
        width = 18.0
    if (
        row[0].event.code == "8"
        and terminal_event.kind == MusicTokenKind.NOTE
        and not terminal_event.duration_dots
        and not terminal_event.duration_slashes
        and has_dual_verse
    ):
        width = 18.0
    if (
        row[0].event.code.startswith("|n[")
        and row[-1].event.code == "|j]"
        and terminal_event.kind == MusicTokenKind.HIDDEN_REST
        and "ykh" in terminal_event.decorations
    ):
        width = 18.0
    if (
        terminal_event.kind == MusicTokenKind.EXTENSION
        and row[0].event.duration_dots
        and "zkh" in row[0].event.decorations
    ):
        width = 27.0
    if len(row) - 2 in left_hook_group_terminals:
        width += 9.0
    if "ykh" in terminal_event.decorations and any(
        ":tuplet:" in role and role.endswith(":end")
        for role in terminal_event.construct_roles
    ):
        width += 9.0
    if (
        terminal_event.kind in {MusicTokenKind.EXTENSION, MusicTokenKind.HIDDEN_REST}
        and "ykh" in terminal_event.decorations
        and "zkh" in row[0].event.decorations
    ):
        width += 9.0
    return width

def terminal_lyric_verse_count(
    lyric_texts_by_position: Sequence[tuple[str, ...]],
) -> int:
    """Return the maximum lyric-verse count present in an intrinsic row."""
    return max(
        (len(texts) for texts in lyric_texts_by_position),
        default=0,
    )

def uses_normal_terminal_grid(row: Sequence[LayoutEvent]) -> bool:
    """Return whether the row uses the ordinary terminal barline grid."""
    terminal_event = row[-2].event
    return (
        row[-1].event.code == "|"
        and "zkh" not in row[0].event.decorations
        and "ykh" not in terminal_event.decorations
    )

def apply_compact_terminal_denominator_adjustment(
    denominator_adjustment: float,
    *,
    uses_compound_meter: bool,
    uses_compact_terminal_lyric_run: bool,
) -> float:
    """Apply the compact terminal-run denominator transfer when eligible."""
    if not uses_compound_meter and uses_compact_terminal_lyric_run:
        return denominator_adjustment - 9.0
    return denominator_adjustment

def uses_compact_terminal_lyric_run(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], tuple[str, ...]],
) -> bool:
    """Return whether the row uses the compact single-verse terminal run."""
    if len(row) < 6:
        return False
    terminal_event = row[-2].event
    lyric_texts = [
        lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
        for item in row
    ]
    return (
        row[-1].event.code == "|"
        and "zkh" not in row[0].event.decorations
        and "ykh" not in terminal_event.decorations
        and max((len(texts) for texts in lyric_texts), default=0) == 1
        and all(
            lyric_texts[index] and all(lyric_texts[index])
            for index in range(len(row) - 6, len(row) - 1)
        )
        and terminal_event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and terminal_event.pitch == 5
        and terminal_event.duration_slashes == 1
    )

def uses_terminal_double_extension_lyric_run(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], tuple[str, ...]],
    *,
    has_fullwidth_trailing_punctuation: Callable[[tuple[str, ...]], bool],
) -> bool:
    """Return whether a terminal double-extension punctuation run is present."""
    if len(row) < 5 or row[-1].event.code != "|w":
        return False
    last_bar_index = max(
        (
            index
            for index, item in enumerate(row[:-1])
            if item.event.kind == MusicTokenKind.BARLINE
        ),
        default=-1,
    )
    if last_bar_index < 0 or len(row) - last_bar_index != 5:
        return False
    note, first_extension, second_extension = row[last_bar_index + 1 : -1]
    texts = lyric_text_by_event.get(
        (note.event.span.start.line, note.event.index),
        (),
    )
    return (
        note.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and first_extension.event.kind == MusicTokenKind.EXTENSION
        and second_extension.event.kind == MusicTokenKind.EXTENSION
        and has_fullwidth_trailing_punctuation(texts)
        and any("sby" in item.event.decorations for item in row)
    )
