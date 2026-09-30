"""Duration and floating-point spacing primitives for natural beat grids."""

from __future__ import annotations

from fractions import Fraction

from octopus.normalization.types import MusicEvent
from octopus.parser.ast import MusicTokenKind
from octopus.render.layout_engine.beat_grid_engine.types import (
    PLAIN_NOTE_STEP,
    SYLLABLE_KINDS,
    UNDERLINED_NOTE_STEP,
)


def duration_beats(event: MusicEvent) -> float:
    """Duration in quarter-note beats.

    The model stores two timed events with ``duration=None``; both are derived
    from the reference (OpenFanqieCore) parser: a sustain ``-`` is always 1
    beat (EXTENSION), and a hidden rest ``8`` is a note-like rest whose length
    follows its slashes (HIDDEN_REST).
    """
    return float(duration_fraction(event))


def duration_fraction(event: MusicEvent) -> Fraction:
    """Return an event duration without converting through binary floats."""
    if event.kind == MusicTokenKind.EXTENSION:
        return Fraction(1, 1)
    if event.kind == MusicTokenKind.HIDDEN_REST:
        return Fraction(1, 2**event.duration_slashes)
    duration = event.duration
    if duration is None:
        return Fraction(0, 1)
    return Fraction(duration.numerator, duration.denominator)


def is_note(event: MusicEvent) -> bool:
    """Reference 'note' = note + rest (0) + rhythm (9); sustain '-' is not."""
    return event.kind in SYLLABLE_KINDS


def target_spacing(event: MusicEvent) -> float:
    """The step a note reserves to the next column in its beat."""
    # Rests (0 and 8) are narrow symbols: the reference gives them the
    # underlined step even without slashes, so a rest never widens a shared
    # beat column.
    if event.kind in (MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST):
        return UNDERLINED_NOTE_STEP
    if is_note(event) and event.duration_slashes >= 1:
        return UNDERLINED_NOTE_STEP
    return PLAIN_NOTE_STEP


def within_beat_trailing(event: MusicEvent) -> float:
    if not is_note(event):
        return 0.0
    return event.duration_dots * (PLAIN_NOTE_STEP - UNDERLINED_NOTE_STEP)


def leading_width(
    event: MusicEvent, at_beat_start: bool, previous: MusicEvent | None
) -> float:
    if not is_note(event):
        return 0.0
    width = 5.0 if event.accidental is not None else 0.0
    if (
        not at_beat_start
        and event.duration_slashes == 1
        and previous is not None
        and is_note(previous)
        and previous.duration_slashes == 1
    ):
        width += event.duration_dots * (PLAIN_NOTE_STEP - UNDERLINED_NOTE_STEP)
    return width


def within_beat_spacing(
    previous: MusicEvent, current: MusicEvent, previous_overflow: float
) -> float:
    return (
        max(target_spacing(previous), target_spacing(current))
        + within_beat_trailing(previous)
        + leading_width(current, False, previous)
        + previous_overflow
    )


def beat_terminal(items: list[MusicEvent]) -> float:
    if not items:
        return 0.0
    last = items[-1]
    has_accidental = any(is_note(item) and item.accidental is not None for item in items)
    return within_beat_trailing(last) + (5.0 if has_accidental else 0.0)


def beat_barline_trailing(beat_items: list[tuple[MusicEvent, float]]) -> float:
    """Width reserved after a measure's final beat, up to the barline.

    Mirrors the reference ``beatBarlineTrailingWidth`` = beat terminal width +
    the last note's lyric overflow (a wide syllable on the closing note pushes
    the barline right so the lyric is not clipped).
    """
    if not beat_items:
        return 0.0
    events = [item[0] for item in beat_items]
    return beat_terminal(events) + beat_items[-1][1]
