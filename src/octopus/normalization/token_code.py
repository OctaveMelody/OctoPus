"""Assemble renderer-facing token codes without changing source tokens."""

from __future__ import annotations

from octopus.normalization import brackets as model_brackets
from octopus.parser.ast import (
    MusicToken,
    MusicTokenKind,
)

_BARLINE_CODE_MAP = {
    "|:": "|z",
    ":|": "|y",
    ":|:": "|l",
    "||": "|j",
    "||/": "|s",
    "|*": "|w",
}


def _rendered_code(tokens: tuple[MusicToken, ...], token_index: int) -> str:
    token = tokens[token_index]
    code = _code_fragment(token, _first_attached_token(tokens, token_index))
    if token.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.BARLINE,
        MusicTokenKind.EXTENSION,
    }:
        opener_kinds = {
            MusicTokenKind.SPAN_START,
            MusicTokenKind.TUPLET_START,
            MusicTokenKind.BRACKET_START,
        }
        if token_index > 0:
            opener_fragments: list[str] = []
            scan = token_index - 1
            while scan >= 0 and tokens[scan].kind in opener_kinds | {MusicTokenKind.BLOCK_START}:
                if tokens[scan].kind != MusicTokenKind.BLOCK_START:
                    opener_fragments.append(_code_fragment(tokens[scan]))
                scan -= 1
            opener_fragments.reverse()
            openers = "".join(opener_fragments)
            pitch_end = next(
                (index + 1 for index, char in enumerate(code) if char.isdigit()),
                len(code),
            )
            if token.kind == MusicTokenKind.BARLINE and token.raw == "|*" and openers:
                code = f"|{openers}*"
            else:
                code = code[:pitch_end] + openers + code[pitch_end:]
        next_index = token_index + 1
        attached_kinds = {
            MusicTokenKind.SPAN_END,
            MusicTokenKind.BRACKET_END,
            MusicTokenKind.MODIFIER,
            MusicTokenKind.DECORATION,
        }
        if token.kind == MusicTokenKind.BARLINE:
            attached_kinds |= {
                MusicTokenKind.BRACKET_START,
                MusicTokenKind.DECORATION,
                MusicTokenKind.ANNOTATION,
                MusicTokenKind.MODIFIER,
            }
        skip_kinds = {MusicTokenKind.GRACE_GROUP, MusicTokenKind.BLOCK_END}
        if token.kind != MusicTokenKind.BARLINE:
            skip_kinds |= {MusicTokenKind.ANNOTATION}
        while next_index < len(tokens):
            next_token = tokens[next_index]
            if not next_token.attached_to_previous:
                break
            if next_token.kind in skip_kinds:
                next_index += 1
                continue
            if next_token.kind in attached_kinds:
                code += _code_fragment(next_token)
                next_index += 1
                continue
            break
        if token.kind == MusicTokenKind.BARLINE:
            following = _following_block_opener(tokens, token_index)
            if (
                following is not None
                and "&dsb_a" not in code
            ):
                if following.value == "dsb":
                    code += "&dsb_a"
                elif following.value == "bz":
                    code += f"&dsb_a&{following.value}"
                elif following.value is None:
                    code += "&dsb_a"
    return code


def _code_fragment(
    token: MusicToken,
    attached_next: MusicToken | None = None,
) -> str:
    if token.kind == MusicTokenKind.BARLINE:
        if token.raw == "|/" and attached_next is not None:
            if attached_next.kind == MusicTokenKind.BRACKET_START:
                return "|n"
            if attached_next.kind == MusicTokenKind.BRACKET_END:
                return "|j"
        if token.raw == ":|" and attached_next is not None:
            if attached_next.kind == MusicTokenKind.BRACKET_END:
                return "|y"
        if token.raw == "|/":
            return "|n"
        return _BARLINE_CODE_MAP.get(token.raw, token.raw)
    if token.kind == MusicTokenKind.TUPLET_START:
        return "(ys"
    if token.kind == MusicTokenKind.EXTENSION:
        return token.raw.replace("<", "").replace(">", "")
    if token.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.RHYTHM_NOTE,
    }:
        return token.raw.replace("<", "").replace(">", "")
    if token.kind == MusicTokenKind.ANNOTATION and len(token.raw) >= 2:
        if token.raw.startswith('"') and token.raw.endswith('"'):
            return f"'{token.raw[1:-1]}'"
    if token.kind == MusicTokenKind.MODIFIER:
        return token.raw.replace("<", "").replace(">", "")
    return token.raw


def _first_attached_token(
    tokens: tuple[MusicToken, ...],
    token_index: int,
) -> MusicToken | None:
    next_index = token_index + 1
    if next_index < len(tokens) and tokens[next_index].attached_to_previous:
        return tokens[next_index]
    return None


def _following_block_opener(
    tokens: tuple[MusicToken, ...],
    token_index: int,
) -> MusicToken | None:
    scan = token_index + 1
    skipped_attached = False
    skippable_attached = {
        MusicTokenKind.SPAN_END,
        MusicTokenKind.BLOCK_END,
        MusicTokenKind.BRACKET_END,
        MusicTokenKind.BRACKET_START,
        MusicTokenKind.ANNOTATION,
        MusicTokenKind.DECORATION,
        MusicTokenKind.MODIFIER,
    }
    while scan < len(tokens):
        token = tokens[scan]
        if token.kind == MusicTokenKind.BLOCK_START and token.value in {None, "bz", "dsb"}:
            return token
        if model_brackets.is_visible_music_token(token):
            return None
        if token.attached_to_previous and token.kind in skippable_attached:
            skipped_attached = True
            scan += 1
            continue
        if skipped_attached and token.kind in {
            MusicTokenKind.ANNOTATION,
            MusicTokenKind.DECORATION,
        }:
            scan += 1
            continue
        return None
    return None
