"""Exact rational column, accidental, annotation, and terminal reserves."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from octopus.normalization.types import MusicEvent
from octopus.render.layout_engine.beat_grid_engine.spacing import is_note, target_spacing
from octopus.render.layout_engine.beat_grid_engine.types import (
    PLAIN_NOTE_STEP,
    UNDERLINED_NOTE_STEP,
    _ExactGridItem,
)


def _target_spacing_fraction(event: MusicEvent) -> Fraction:
    return Fraction(str(target_spacing(event)))


def _annotation_widths(event: MusicEvent) -> tuple[Fraction, Fraction]:
    """(before, after) width reserved by key-change style annotations.

    Oracle-verified 2026-08-23 (natural-width probes): ``&zkh`` reserves
    12.5 on both sides of the annotated event, ``&ykh`` 12.5 after, and
    ``&shy``/``&xhy`` 7.5 after; every other annotation is width-neutral.
    The widths apply to any event kind (note, rest, dash, hidden rest) and
    add outside the dot-trail/overflow max.
    """
    before = Fraction(0, 1)
    after = Fraction(0, 1)
    for name in event.decorations or ():
        if name == "zkh":
            before += Fraction(25, 2)
            after += Fraction(25, 2)
        elif name == "ykh":
            after += Fraction(25, 2)
        elif name in ("shy", "xhy"):
            after += Fraction(15, 2)
    return before, after


def _within_beat_trailing_fraction(event: MusicEvent) -> Fraction:
    if not is_note(event):
        return Fraction(0, 1)
    return Fraction(event.duration_dots, 1) * (
        Fraction(PLAIN_NOTE_STEP) - Fraction(UNDERLINED_NOTE_STEP)
    )


def _leading_width_fraction(
    event: MusicEvent, at_beat_start: bool, previous: MusicEvent | None
) -> Fraction:
    if not is_note(event):
        return Fraction(0, 1)
    width = Fraction(5 if event.accidental is not None else 0, 1)
    if (
        not at_beat_start
        and event.duration_slashes == 1
        and previous is not None
        and is_note(previous)
        and previous.duration_slashes == 1
    ):
        width += Fraction(event.duration_dots, 1) * (
            Fraction(PLAIN_NOTE_STEP) - Fraction(UNDERLINED_NOTE_STEP)
        )
    return width


def _within_beat_spacing_fraction(
    previous: _ExactGridItem, current: _ExactGridItem
) -> Fraction:
    """Step between two events of the same beat.

    Oracle-verified 2026-08-23: the dot trail and the syllable overflow never
    stack; an accidental on the previous note reserves five units at the beat
    terminal, so it must clear ``trail + 5`` before the overflow can widen the
    pair step (``max(trail, ovf - 5*acc)``).

    Oracle-verified 2026-08-23 (6/8 probes J-L): a tied previous note takes
    the underlined base even when it is an unslashed plain note, so quarter+
eighth pairs that only fit inside a compound beat stay tight (25) while
    untied plain notes keep ``max(target(prev), target(next))``.
    """
    previous_event = previous.event
    accidental = Fraction(
        5 if is_note(previous_event) and previous_event.accidental is not None else 0,
        1,
    )
    base = (
        Fraction(UNDERLINED_NOTE_STEP)
        if previous.tied
        else max(
            _target_spacing_fraction(previous_event),
            _target_spacing_fraction(current.event),
        )
    )
    return (
        base
        + _leading_width_fraction(current.event, False, previous_event)
        + max(
            _within_beat_trailing_fraction(previous_event),
            previous.overflow - accidental,
        )
        + _annotation_widths(previous_event)[1]
        + _annotation_widths(current.event)[0]
    )


def _trailing_or_overflow_fraction(
    events: Sequence[MusicEvent],
    overflow: Fraction,
    accidental_reserve: Fraction,
) -> Fraction:
    """Beat trailing space and lyric overflow never stack.

    Oracle-verified 2026-08-23: a dotted event with a wide syllable pushes the
    following column by ``max(dot_trail + accidental_reserve, overflow)``, not
    their sum; the accidental reserve (the row's own accented columns, see
    _accidental_column_reserve) is part of the trail side of the max, so a
    dominant overflow replaces it rather than adding to it.
    """
    if not events:
        return max(Fraction(0, 1), overflow)
    last = events[-1]
    trail = _within_beat_trailing_fraction(last) + accidental_reserve
    return max(trail, overflow) + _annotation_widths(last)[1]


def _accidental_column_reserve(
    columns_items: Sequence[Sequence[_ExactGridItem]],
) -> Fraction:
    """Five units per column (of the given rows) holding an accented note.

    Oracle-verified 2026-08-23 (As-Wished-Choir p1 systems 1-2 + minimal
    probes A-I): a beat reserves five units before the next column or barline
    for every column that contains at least one accented note. Two accented
    notes in the same column reserve once; two in different columns reserve
    twice (As-Wished p1 m3: four rows carry accidentals in columns 0 and 1
    -> +10, not +5 per row or +20 per note). Call it with a single row's
    items for that row's own reserve, or with the whole beat for the union
    reserve.
    """
    column_count = max((len(items) for items in columns_items), default=0)
    reserved_columns = 0
    for item_index in range(column_count):
        if any(
            is_note(items[item_index].event)
            and items[item_index].event.accidental is not None
            for items in columns_items
            if item_index < len(items)
        ):
            reserved_columns += 1
    return Fraction(5 * reserved_columns, 1)


def _phantom_column_step_fraction(
    columns_items: Sequence[Sequence[_ExactGridItem]],
    item_index: int,
    items: Sequence[_ExactGridItem],
) -> Fraction:
    """Step a short row reserves into a shared column it does not fill.

    Oracle-verified 2026-08-23: the base is the target spacing of the events
    that do occupy the column, widened by their leading (accidental) width; the
    addend is the row's last-item lyric overflow. Dot trails do not apply.
    """
    next_events = [
        other[item_index].event
        for other in columns_items
        if item_index < len(other)
    ]
    base = max(
        (
            _target_spacing_fraction(event)
            + _leading_width_fraction(event, True, None)
            + _annotation_widths(event)[0]
            for event in next_events
        ),
        default=Fraction(0, 1),
    )
    return base + items[-1].overflow + _annotation_widths(items[-1].event)[1]


def _barline_trailing_for_beat(
    items: Sequence[_ExactGridItem],
    fills_last_column: bool,
    accidental_reserve: Fraction,
) -> Fraction:
    """Barline trailing for one row's final beat.

    Rows that stop short of the last shared column already spent their dot
    trail and lyric overflow on the phantom column step, so only their own
    accidental reserve remains for the barline gap. The union reserve (all
    rows) is folded in by the caller's max; oracle probe I shows it can
    exceed every single row's own reserve when accidentals sit in different
    columns of different full rows.
    """
    if not items:
        return Fraction(0, 1)
    if fills_last_column:
        return _trailing_or_overflow_fraction(
            [item.event for item in items], items[-1].overflow, accidental_reserve
        )
    return accidental_reserve
