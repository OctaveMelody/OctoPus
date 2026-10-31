"""Derive exact durations, time attributes, and nested tuplet multipliers."""

from __future__ import annotations

from fractions import Fraction

from octopus.normalization.source import fraction_to_text as _fraction_to_text
from octopus.normalization.types import DurationValue
from octopus.parser.ast import (
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


def _flat_tuplet_duration_overrides(
    tokens: tuple[MusicToken, ...],
) -> dict[int, DurationValue]:
    overrides: dict[int, DurationValue] = {}
    nesting_depth = 0
    block_depth = 0
    for token_index, token in enumerate(tokens):
        if (
            token.kind == MusicTokenKind.TUPLET_START
            and nesting_depth == 0
            and block_depth == 0
        ):
            overrides.update(_flat_tuplet_duration_overrides_at(tokens, token_index))
        if token.kind in {MusicTokenKind.TUPLET_START, MusicTokenKind.SPAN_START}:
            nesting_depth += 1
        elif token.kind == MusicTokenKind.SPAN_END:
            nesting_depth = max(nesting_depth - 1, 0)
        elif token.kind == MusicTokenKind.BLOCK_START:
            block_depth += 1
        elif token.kind == MusicTokenKind.BLOCK_END:
            block_depth = max(block_depth - 1, 0)
    return overrides


def _flat_tuplet_duration_overrides_at(
    tokens: tuple[MusicToken, ...],
    opener_index: int,
) -> dict[int, DurationValue]:
    note_index = opener_index + 1
    if note_index >= len(tokens) or not _ordinary_flat_tuplet_note(tokens[note_index]):
        return {}

    extension_indices: list[int] = []
    index = note_index + 1
    final_dynamic = False
    while index < len(tokens) and tokens[index].kind == MusicTokenKind.EXTENSION:
        extension = tokens[index]
        if not _flat_tuplet_dash(extension):
            return {}
        if final_dynamic:
            return {}
        final_dynamic = bool(extension.decorations)
        extension_indices.append(index)
        if len(extension_indices) > 3:
            return {}
        index += 1

    dash_count = len(extension_indices)
    if (
        dash_count == 0
        or index >= len(tokens)
        or tokens[index].kind != MusicTokenKind.SPAN_END
    ):
        return {}

    factor = Fraction(dash_count, dash_count + 1)
    text = {
        Fraction(1, 2): "0.50",
        Fraction(2, 3): "0.67",
        Fraction(3, 4): "0.75",
    }[factor]
    duration = DurationValue(factor.numerator, factor.denominator, text)
    return {token_index: duration for token_index in (note_index, *extension_indices)}


def _ordinary_flat_tuplet_note(token: MusicToken) -> bool:
    return (
        token.kind == MusicTokenKind.NOTE
        and token.pitch is not None
        and 1 <= token.pitch <= 7
        and token.accidental is None
        and token.octave == 0
        and token.duration_slashes == 0
        and token.duration_dots == 0
        and not token.dotted
        and not token.decorations
        and token.raw == str(token.pitch)
    )


def _flat_tuplet_dash(token: MusicToken) -> bool:
    return (
        token.kind == MusicTokenKind.EXTENSION
        and token.duration_slashes == 0
        and token.duration_dots == 0
        and not token.dotted
        and (
            token.raw == "-" and not token.decorations
            or token.raw == "-&f" and token.decorations == ("f",)
        )
    )


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
