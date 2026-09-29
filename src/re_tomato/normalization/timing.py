"""Derive exact durations, time attributes, and nested tuplet multipliers."""

from __future__ import annotations

from fractions import Fraction

from re_tomato.normalization.source import fraction_to_text as _fraction_to_text
from re_tomato.normalization.types import DurationValue
from re_tomato.parser.ast import (
    MusicToken,
    MusicTokenKind,
)

_TUPLET_FACTOR = Fraction(2, 3)


def _music_duration(
    token: MusicToken,
    tuplet_multiplier: Fraction = Fraction(1, 1),
) -> DurationValue | None:
    if token.kind not in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
    }:
        return None
    duration = Fraction(
        2 ** (token.duration_dots + 1) - 1,
        2 ** (token.duration_slashes + token.duration_dots),
    )
    duration *= tuplet_multiplier
    return DurationValue(duration.numerator, duration.denominator, _fraction_to_text(duration))


def _time_text(token: MusicToken, duration: DurationValue | None) -> str | None:
    if duration is not None:
        return duration.text
    if token.kind == MusicTokenKind.HIDDEN_REST:
        return "0"
    if token.kind == MusicTokenKind.BARLINE:
        return "0"
    if token.kind == MusicTokenKind.EXTENSION:
        return str(max(token.raw.count("-"), 1))
    return None


def _tuplet_multipliers(tokens: tuple[MusicToken, ...]) -> list[Fraction]:
    multipliers: list[Fraction] = []
    opener_stack: list[tuple[MusicTokenKind, bool]] = []
    active_tuplets = 0
    for token_index, token in enumerate(tokens):
        if token.kind == MusicTokenKind.TUPLET_START:
            scales_duration = not _tuplet_preserves_written_duration(tokens, token_index)
            opener_stack.append((token.kind, scales_duration))
            if scales_duration:
                active_tuplets += 1
            multipliers.append(Fraction(1, 1))
            continue
        if token.kind == MusicTokenKind.SPAN_START:
            opener_stack.append((token.kind, False))
            multipliers.append(Fraction(1, 1))
            continue
        multipliers.append(_TUPLET_FACTOR**active_tuplets)
        if token.kind == MusicTokenKind.SPAN_END and opener_stack:
            popped, counted = opener_stack.pop()
            if popped == MusicTokenKind.TUPLET_START and counted:
                active_tuplets -= 1
    return multipliers


def _tuplet_preserves_written_duration(tokens: tuple[MusicToken, ...], opener_index: int) -> bool:
    enclosed: list[MusicToken] = []
    depth = 0
    for token in tokens[opener_index + 1 :]:
        if token.kind in {MusicTokenKind.TUPLET_START, MusicTokenKind.SPAN_START}:
            depth += 1
        elif token.kind == MusicTokenKind.SPAN_END:
            if depth == 0:
                break
            depth -= 1
        if depth > 0:
            continue
        if token.kind in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
        }:
            enclosed.append(token)
    return bool(enclosed) and all(token.duration_slashes == 2 for token in enclosed)
