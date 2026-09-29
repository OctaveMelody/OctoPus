"""Assemble parsed source lines into pages, systems, and voice streams."""

from __future__ import annotations

from re_tomato.normalization.builders import _PageBuilder, _SystemBuilder
from re_tomato.normalization.events import _normalize_lyric_line, _normalize_music_token_stream
from re_tomato.normalization.topology import derive_voice_groups as _derive_voice_groups
from re_tomato.normalization.types import MusicEvent, SemanticConstruct
from re_tomato.parser.ast import (
    BlankLine,
    LyricLine,
    MusicLine,
    PageBreakLine,
    ScoreDocument,
)


def _build_pages(document: ScoreDocument) -> list[_PageBuilder]:
    segments: list[list] = []
    current: list = []
    for line in document.lines:
        if isinstance(line, PageBreakLine):
            segments.append(current)
            current = []
            continue
        current.append(line)
    segments.append(current)
    return [_build_page(index + 1, lines) for index, lines in enumerate(segments)]


def _build_page(index: int, lines: list) -> _PageBuilder:
    page = _PageBuilder(index)
    current: list = []
    for line in lines:
        page.add_span(line.span)
        if isinstance(line, BlankLine):
            if _contains_voice_content(current):
                page.systems.append(
                    _build_system(len(page.systems) + 1, current, page_index=page.index)
                )
            current = []
            continue
        current.append(line)
    if _contains_voice_content(current):
        page.systems.append(
            _build_system(len(page.systems) + 1, current, page_index=page.index)
        )
    return page


def _build_system(index: int, lines: list, *, page_index: int = 1) -> _SystemBuilder:
    system = _SystemBuilder(index=index, page_index=page_index)
    normalized_music = _normalize_system_music_lines(lines, system_index=index)
    constructs_added: set[int] = set()
    music_voices = {line.voice for line in lines if isinstance(line, MusicLine)}
    sole_music_voice = next(iter(music_voices)) if len(music_voices) == 1 else None
    most_recent_music_voice: int | None = None
    for line in lines:
        if isinstance(line, (MusicLine, LyricLine)):
            system.add_span(line.span)
            if isinstance(line, MusicLine):
                most_recent_music_voice = line.voice
                system.music_line_numbers.append(line.span.start.line)
                voice = system.voice(line.voice)
                voice.music_line_numbers.append(line.span.start.line)
                voice.add_span(line.span)
                if line.voice_name:
                    if voice.name is None:
                        voice.name = line.voice_name
                    if line.voice_name not in voice.declared_names:
                        voice.declared_names.append(line.voice_name)
                    voice.line_names[line.span.start.line] = line.voice_name
                normalized_events, constructs = normalized_music.get(
                    (line.voice, line.span.start.line), ([], [])
                )
                voice.events.extend(normalized_events)
                if line.voice not in constructs_added:
                    voice.constructs.extend(constructs)
                    constructs_added.add(line.voice)
            else:
                system.lyric_line_numbers.append(line.span.start.line)
                lyric_voice: int = line.voice
                if lyric_voice == 0 and sole_music_voice is not None and sole_music_voice != 0:
                    lyric_voice = sole_music_voice
                elif (
                    lyric_voice == 0
                    and 0 not in music_voices
                    and most_recent_music_voice is not None
                ):
                    lyric_voice = most_recent_music_voice
                voice = system.voice(lyric_voice)
                voice.lyric_line_numbers.append(line.span.start.line)
                voice.add_span(line.span)
                voice.lyrics.append(_normalize_lyric_line(line, voice=lyric_voice))
    system.voice_groups = _derive_voice_groups(page_index, index, lines)
    return system


def _normalize_system_music_lines(
    lines: list,
    *,
    system_index: int,
) -> dict[tuple[int, int], tuple[list[MusicEvent], list[SemanticConstruct]]]:
    """Normalize each voice stream once, then restore physical line buckets."""
    by_voice: dict[int, list[MusicLine]] = {}
    for line in lines:
        if isinstance(line, MusicLine):
            by_voice.setdefault(line.voice, []).append(line)
    normalized: dict[tuple[int, int], tuple[list[MusicEvent], list[SemanticConstruct]]] = {}
    for voice, music_lines in by_voice.items():
        tokens = tuple(token for line in music_lines for token in line.tokens)
        prefix = lambda token, voice=voice: f"s{system_index}v{voice}l{token.span.start.line}"  # noqa: E731
        events, constructs = _normalize_music_token_stream(
            tokens, next_event_index=1, construct_prefix=prefix
        )
        for line in music_lines:
            line_events = [e for e in events if e.span.start.line == line.span.start.line]
            normalized[(voice, line.span.start.line)] = line_events, constructs
    return normalized


def _contains_voice_content(lines: list) -> bool:
    return any(isinstance(line, (MusicLine, LyricLine)) for line in lines)
