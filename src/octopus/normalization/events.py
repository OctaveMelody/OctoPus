"""Normalize music and lyric token streams into model events and constructs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction

from octopus.normalization.constructs import (
    _annotate_construct_roles,
    _extract_semantic_constructs,
)
from octopus.normalization.grace import attach_grace_reservations
from octopus.normalization.ties import _audio_text, _precompute_openers
from octopus.normalization.timing import (
    _flat_tuplet_duration_overrides,
    _music_duration,
    _time_text,
    _tuplet_multipliers,
)
from octopus.normalization.token_code import _rendered_code
from octopus.normalization.types import (
    DurationValue,
    LyricEvent,
    LyricLineModel,
    MusicEvent,
    SemanticConstruct,
)
from octopus.normalization.visual_chains import resolve_visual_chain_endpoints
from octopus.parser.ast import (
    LyricLine,
    MusicToken,
    MusicTokenKind,
)
from octopus.parser.source import SourceSpan


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
    duration_overrides = _flat_tuplet_duration_overrides(tokens)
    opener_map = _precompute_openers(tokens)
    bz_barlines: set[int] | None = None
    for token_index, token in enumerate(tokens):
        if token.kind == MusicTokenKind.IGNORED_TEXT:
            continue
        if (
            token_index > 0
            and token.kind == MusicTokenKind.BARLINE
            and tokens[token_index - 1].kind == MusicTokenKind.BARLINE
            and tokens[token_index - 1].span.start.line == token.span.start.line
            and events
            and events[-1].code == "|"
        ):
            second_code = _rendered_code(tokens, token_index)
            if second_code == "|" and bz_barlines is None:
                bz_barlines = _bz_measure_barlines(tokens)
            if second_code in {"|s", "|z"} or (
                bz_barlines is not None and second_code == "|"
                and token_index not in bz_barlines and token_index - 1 not in bz_barlines
            ):
                previous = events[-1]
                combined_code = "|j" + second_code[1:]
                events[-1] = replace(
                    previous, span=SourceSpan(previous.span.start, token.span.end),
                    code=combined_code, render_code=combined_code,
                )
                token_to_event_index[token_index] = previous.index
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
                duration_overrides.get(token_index),
            )
        )
    constructs = _extract_semantic_constructs(tokens, token_to_event_index, construct_prefix)
    constructs = resolve_visual_chain_endpoints(events, constructs)
    events = attach_grace_reservations(events)
    return _annotate_construct_roles(events, constructs), constructs


def _bz_measure_barlines(tokens: tuple[MusicToken, ...]) -> set[int]:
    """Keep plain barlines distinct where each one delimits a BZ measure."""
    boundaries: set[int] = set()
    depth = 0
    bz_depth: int | None = None
    hidden_measures = 0
    open_measure = False
    has_music = False
    host_measures = 0
    for index, token in enumerate(tokens):
        if token.kind == MusicTokenKind.BLOCK_START:
            depth += 1
            if token.value == "bz" and bz_depth is None:
                bz_depth = depth
                hidden_measures = 0
                open_measure = False
                has_music = False
        elif token.kind == MusicTokenKind.BLOCK_END and depth:
            if depth == bz_depth:
                if has_music:
                    host_measures = max(host_measures, hidden_measures + int(open_measure))
                bz_depth = None
            depth -= 1
        elif token.kind == MusicTokenKind.BARLINE:
            if bz_depth is not None:
                boundaries.add(index)
                hidden_measures += 1
                open_measure = False
            elif depth == 0 and host_measures:
                boundaries.add(index)
                host_measures -= 1
        elif bz_depth is not None and token.kind in {
            MusicTokenKind.NOTE, MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST,
            MusicTokenKind.RHYTHM_NOTE, MusicTokenKind.EXTENSION,
        }:
            open_measure = True
            has_music = True
    return boundaries


def _normalize_music_token(
    tokens: tuple[MusicToken, ...],
    token_index: int,
    index: int,
    tuplet_multiplier: Fraction = Fraction(1, 1),
    opener_map: dict[int, int] | None = None,
    duration_override: DurationValue | None = None,
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
    duration = duration_override or _music_duration(token, tuplet_multiplier)
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
