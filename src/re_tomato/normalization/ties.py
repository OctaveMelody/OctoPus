"""Match span openers and classify same-pitch ties and silent closing notes."""

from __future__ import annotations

from re_tomato.parser.ast import (
    MusicToken,
    MusicTokenKind,
)


def _audio_text(
    tokens: tuple[MusicToken, ...],
    token_index: int,
    token: MusicToken,
    code: str,
    opener_map: dict[int, int],
) -> str | None:
    if token.kind == MusicTokenKind.BARLINE:
        return ""
    if token.kind == MusicTokenKind.EXTENSION:
        return ""
    if token.kind == MusicTokenKind.HIDDEN_REST:
        return ""
    if token.pitch is None:
        return None
    if token.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
    }:
        if _closing_note_is_silent(tokens, token_index, token, opener_map):
            return "0"
        suffix = "'" * max(token.octave, 0) + "," * max(-token.octave, 0)
        return f"{token.pitch}{suffix}"
    return None


def _closing_note_is_silent(
    tokens: tuple[MusicToken, ...],
    token_index: int,
    token: MusicToken,
    opener_map: dict[int, int],
) -> bool:
    attached_closers = _attached_closers(tokens, token_index)
    if not attached_closers:
        return False
    closer_index, _closer_kind = attached_closers[0]
    opening_index = opener_map.get(closer_index)
    if opening_index is None:
        return False
    return _span_close_is_tie(tokens, opening_index, token_index, token)


def _attached_closers(
    tokens: tuple[MusicToken, ...],
    token_index: int,
) -> list[tuple[int, MusicTokenKind]]:
    closers: list[tuple[int, MusicTokenKind]] = []
    next_index = token_index + 1
    while next_index < len(tokens) and tokens[next_index].attached_to_previous:
        next_token = tokens[next_index]
        if next_token.kind in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
        }:
            break
        if next_token.kind in {
            MusicTokenKind.SPAN_END,
            MusicTokenKind.BLOCK_END,
            MusicTokenKind.BRACKET_END,
        }:
            closers.append((next_index, next_token.kind))
        next_index += 1
    return closers


def _precompute_openers(
    tokens: tuple[MusicToken, ...],
) -> dict[int, int]:
    opener_stack: list[tuple[int, MusicTokenKind]] = []
    closer_to_openers = {
        MusicTokenKind.SPAN_END: {
            MusicTokenKind.SPAN_START,
            MusicTokenKind.TUPLET_START,
        },
        MusicTokenKind.BLOCK_END: {MusicTokenKind.BLOCK_START},
        MusicTokenKind.BRACKET_END: {MusicTokenKind.BRACKET_START},
    }
    opener_to_closers = {
        MusicTokenKind.SPAN_START: MusicTokenKind.SPAN_END,
        MusicTokenKind.TUPLET_START: MusicTokenKind.SPAN_END,
        MusicTokenKind.BLOCK_START: MusicTokenKind.BLOCK_END,
        MusicTokenKind.BRACKET_START: MusicTokenKind.BRACKET_END,
    }
    result: dict[int, int] = {}
    for index, token in enumerate(tokens):
        if token.kind in opener_to_closers:
            opener_stack.append((index, token.kind))
        elif token.kind in closer_to_openers and opener_stack:
            closer_openers = closer_to_openers[token.kind]
            while opener_stack and opener_stack[-1][1] not in closer_openers:
                opener_stack.pop()
            if opener_stack and opener_stack[-1][1] in closer_openers:
                result[index] = opener_stack.pop()[0]
    return result


def _first_musical_token_with_index(
    tokens: tuple[MusicToken, ...],
    start_index: int,
    end_index: int,
) -> tuple[int, MusicToken] | None:
    for index in range(start_index, end_index + 1):
        current = tokens[index]
        if current.kind in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
        }:
            return index, current
    return None


def _previous_musical_token_with_index(
    tokens: tuple[MusicToken, ...],
    start_index: int,
) -> tuple[int, MusicToken] | None:
    for index in range(start_index - 1, -1, -1):
        current = tokens[index]
        if current.kind in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
        }:
            return index, current
    return None


def _span_close_is_tie(
    tokens: tuple[MusicToken, ...],
    opening_index: int,
    token_index: int,
    token: MusicToken,
) -> bool:
    opening_note = _first_musical_token_with_index(tokens, opening_index + 1, token_index)
    if opening_note is None:
        return False
    opening_note_index, opening_note_token = opening_note
    previous_note = _previous_musical_token_with_index(tokens, token_index)
    if previous_note is None:
        return False
    previous_note_index, previous_note_token = previous_note

    if opening_note_token is token:
        return _same_tie_note(previous_note_token, token) and _note_has_opening_span(
            tokens, previous_note_index
        )
    return _same_tie_note(opening_note_token, token) and _same_tie_note(previous_note_token, token)


def _note_has_opening_span(tokens: tuple[MusicToken, ...], token_index: int) -> bool:
    scan = token_index - 1
    while scan >= 0 and tokens[scan].kind in {
        MusicTokenKind.SPAN_START,
        MusicTokenKind.TUPLET_START,
        MusicTokenKind.BRACKET_START,
        MusicTokenKind.BLOCK_START,
    }:
        if tokens[scan].kind in {MusicTokenKind.SPAN_START, MusicTokenKind.TUPLET_START}:
            return True
        scan -= 1
    return False


def _same_tie_note(left: MusicToken, right: MusicToken) -> bool:
    return (
        left.kind == right.kind
        and left.pitch == right.pitch
        and left.octave == right.octave
    )
