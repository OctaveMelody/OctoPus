"""Split lyric syllables and compute associated overflow widths."""

from __future__ import annotations

import re
from fractions import Fraction

from re_tomato.normalization.types import MusicEvent
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    PUNCTUATION,
    SYLLABLE_KINDS,
    LyricTextByEvent,
)


def is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def syllable_texts(raw: str) -> list[str]:
    """Split a lyric line into syllable texts (the reference parse)."""
    match = re.match(r"^[A-Z]\d*:\s*", raw)
    if match:
        raw = raw[match.end() :]
    syllables: list[str] = []
    join_next = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if char.isspace() or char == "/":
            index += 1
            continue
        # Quoted lyric annotations are lexed as one annotation token and do
        # not consume a note/lyric slot.  Treat the quote as a unit here too.
        # In particular, do not let the ASCII-run branch below see a quote as
        # its first character: that branch intentionally stops *before* a
        # quote, which otherwise leaves ``index`` unchanged forever.
        if char == '"':
            index += 1
            while index < len(raw) and raw[index] != '"':
                index += 1
            if index < len(raw):
                index += 1
            continue
        if char == "~":
            join_next = True
            index += 1
            continue
        if char == "@":
            syllables.append("")
            index += 1
            continue
        if char in PUNCTUATION:
            index += 1
            continue
        if is_cjk(char):
            if join_next and syllables:
                syllables[-1] += char
            else:
                syllables.append(char)
            join_next = False
            index += 1
            continue
        start = index
        while index < len(raw) and not (
            raw[index].isspace()
            or raw[index] in "/@~\""
            or is_cjk(raw[index])
            or raw[index] in PUNCTUATION
        ):
            index += 1
        if join_next and syllables:
            syllables[-1] += raw[start:index]
        else:
            syllables.append(raw[start:index])
        join_next = False
    return syllables


def lyric_units(text: str) -> int:
    """Spacing units of one rendered lyric element (reference rule).

    A syllable pushes the following column by its first rendered element
    only.  The association layer delivers one string per event with ``~``
    joins folded in (``snow~,`` arrives as ``snow,``); punctuation that was
    not tilde-joined renders as its own element and never reaches this count.
    Count: one unit per ASCII letter, space, hyphen, or punctuation; two units
    per wide (non-ASCII) character.  Oracle-verified 2026-08-23:
    ``a``/``ab`` -> 0, ``abc`` -> 16.667, ``snow~,`` -> 44.444, ``上，`` -> 0,
    ``我~们`` -> 30.556, ``raise~\u3000`` -> 72.222.
    """
    return sum(2 if not char.isascii() else 1 for char in text)


def lyric_overflow(text: str) -> float:
    """Extra width a wide lyric syllable pushes into the following gap."""
    units = lyric_units(text)
    if units <= 2:
        return 0.0
    return (125.0 * units - 225.0) / 9.0


def syllable_overflows(lyric_raws: tuple[str, ...] | list[str]) -> list[float]:
    """One lyric overflow per syllable across the given lyric lines."""
    syllables: list[str] = []
    for raw in lyric_raws:
        syllables.extend(syllable_texts(raw))
    return [lyric_overflow(syllable) for syllable in syllables]


def _lyric_overflow_fraction(text: str) -> Fraction:
    units = lyric_units(text)
    if units <= 2:
        return Fraction(0, 1)
    return Fraction(125 * units - 225, 9)


def _associated_overflow(
    event: MusicEvent, lyric_text_by_event: LyricTextByEvent
) -> Fraction:
    """Combine stacked-verse syllable overflows for one event.

    Oracle-verified 2026-07-25 (AuldLangSyne-Choir p1 grids 0 and 1, every
    lyric-bearing step): verses combine last-non-zero — a later verse's
    overflow replaces an earlier one only when it is non-zero.  A plain max
    over-estimates columns where the top verse carries the wide syllable but
    the reference still uses the lower verse's narrower one.
    """
    if event.kind not in SYLLABLE_KINDS:
        return Fraction(0, 1)
    texts = lyric_text_by_event.get((event.span.start.line, event.index), ())
    for text in reversed(texts):
        overflow = _lyric_overflow_fraction(text)
        if overflow:
            return overflow
    return Fraction(0, 1)
