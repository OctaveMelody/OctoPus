"""Derive exact durations, time attributes, and nested tuplet multipliers."""

from __future__ import annotations

from fractions import Fraction

from octopus.normalization.source import fraction_to_text as _fraction_to_text
from octopus.normalization.types import DurationValue
from octopus.parser.ast import (
    MusicToken,
    MusicTokenKind,
)

_TUPLET_NORMAL_UNITS = {"2": 3, "3": 2, "4": 3, "5": 4, "6": 4, "7": 4, "8": 6, "9": 8}


def _music_duration(
    token: MusicToken,
    tuplet_multiplier: Fraction = Fraction(1, 1),
) -> DurationValue | None:
    if token.kind == MusicTokenKind.EXTENSION and tuplet_multiplier != 1:
        duration = max(token.raw.count("-"), 1) * tuplet_multiplier
        return DurationValue(duration.numerator, duration.denominator, _fraction_to_text(duration))
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
        return duration.text if duration is not None else str(max(token.raw.count("-"), 1))
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
            and token.value is None
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
    closed_numbered: set[int] = set()
    pending_closes = 0
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if token.kind == MusicTokenKind.SPAN_END:
            pending_closes += 1
        elif token.kind in {MusicTokenKind.SPAN_START, MusicTokenKind.TUPLET_START}:
            if pending_closes:
                pending_closes -= 1
                if token.kind == MusicTokenKind.TUPLET_START and token.value is not None:
                    closed_numbered.add(index)

    multipliers: list[Fraction] = []
    opener_stack: list[tuple[Fraction, Fraction]] = []
    note_multiplier = extension_multiplier = Fraction(1)
    for token_index, token in enumerate(tokens):
        if token.kind == MusicTokenKind.TUPLET_START:
            opener_stack.append((note_multiplier, extension_multiplier))
            if token.value is not None:
                if token_index in closed_numbered:
                    factor = Fraction(_TUPLET_NORMAL_UNITS[token.value], int(token.value))
                    note_multiplier *= factor
                    extension_multiplier *= factor
            elif not _tuplet_preserves_written_duration(tokens, token_index):
                note_multiplier *= Fraction(2, 3)
            multipliers.append(Fraction(1, 1))
            continue
        if token.kind == MusicTokenKind.SPAN_START:
            opener_stack.append((note_multiplier, extension_multiplier))
            multipliers.append(Fraction(1, 1))
            continue
        multipliers.append(
            extension_multiplier if token.kind == MusicTokenKind.EXTENSION else note_multiplier
        )
        if token.kind == MusicTokenKind.SPAN_END and opener_stack:
            note_multiplier, extension_multiplier = opener_stack.pop()
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
