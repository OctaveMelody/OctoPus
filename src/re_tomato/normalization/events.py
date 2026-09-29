"""Normalize music and lyric token streams into model events and constructs."""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction

from re_tomato.normalization.constructs import (
    _annotate_construct_roles,
    _extract_semantic_constructs,
)
from re_tomato.normalization.grace import attach_grace_reservations
from re_tomato.normalization.ties import _audio_text, _precompute_openers
from re_tomato.normalization.timing import _music_duration, _time_text, _tuplet_multipliers
from re_tomato.normalization.token_code import _rendered_code
from re_tomato.normalization.types import LyricEvent, LyricLineModel, MusicEvent, SemanticConstruct
from re_tomato.normalization.visual_chains import resolve_visual_chain_endpoints
from re_tomato.parser.ast import (
    LyricLine,
    MusicToken,
    MusicTokenKind,
)


def _normalize_music_token_stream(
    tokens: tuple[MusicToken, ...],
    *,
    next_event_index: int,
    construct_prefix: Callable[[MusicToken], str],
) -> tuple[list[MusicEvent], list[SemanticConstruct]]:
    events: list[MusicEvent] = []
    token_to_event_index: dict[int, int] = {}
    event_index = next_event_index - 1
    tuplet_multipliers = _tuplet_multipliers(tokens)
    opener_map = _precompute_openers(tokens)
    for token_index, token in enumerate(tokens):
        if token.kind == MusicTokenKind.IGNORED_TEXT:
            continue
        event_index += 1
        token_to_event_index[token_index] = event_index
        events.append(
            _normalize_music_token(
                tokens,
                token_index,
                event_index,
                tuplet_multipliers[token_index],
                opener_map,
            )
        )
    constructs = _extract_semantic_constructs(tokens, token_to_event_index, construct_prefix)
    constructs = resolve_visual_chain_endpoints(events, constructs)
    events = attach_grace_reservations(events)
    return _annotate_construct_roles(events, constructs), constructs


def _normalize_music_token(
    tokens: tuple[MusicToken, ...],
    token_index: int,
    index: int,
    tuplet_multiplier: Fraction = Fraction(1, 1),
    opener_map: dict[int, int] | None = None,
) -> MusicEvent:
    token = tokens[token_index]
    child_multipliers = _tuplet_multipliers(token.children)
    child_openers = _precompute_openers(token.children)
    children = tuple(
        _normalize_music_token(
            token.children,
            child_index - 1,
            child_index,
            child_multipliers[child_index - 1],
            child_openers,
        )
        for child_index, _child in enumerate(token.children, start=1)
    )
    duration = _music_duration(token, tuplet_multiplier)
    code = _rendered_code(tokens, token_index)
    time = _time_text(token, duration)
    audio = _audio_text(tokens, token_index, token, code, opener_map or {})
    return MusicEvent(
        index=index,
        kind=token.kind,
        raw=token.raw,
        span=token.span,
        code=code,
        source_code=token.raw,
        render_code=code,
        value=token.value,
        pitch=token.pitch,
        accidental=token.accidental,
        octave=token.octave,
        duration_slashes=token.duration_slashes,
        duration_dots=token.duration_dots,
        dotted=token.dotted,
        decorations=token.decorations,
        attached_to_previous=token.attached_to_previous,
        duration=duration,
        time=time,
        audio=audio,
        children=children,
    )


def _normalize_lyric_line(line: LyricLine, voice: int | None = None) -> LyricLineModel:
    return LyricLineModel(
        voice=line.voice if voice is None else voice,
        raw=line.raw,
        span=line.span,
        tokens=tuple(LyricEvent(token.kind, token.raw, token.span) for token in line.tokens),
    )
