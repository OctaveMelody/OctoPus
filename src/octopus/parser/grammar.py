"""Parse JPS source into recoverable line and token AST nodes."""

from __future__ import annotations

import re
from pathlib import Path

from octopus.jps import JpsDocument, load_jps

from .ast import (
    BlankLine,
    CommentLine,
    HeaderLine,
    LineKind,
    LineNode,
    LyricLine,
    MusicLine,
    MusicTokenKind,
    PageBreakLine,
    ScoreDocument,
    UnknownLine,
)
from .diagnostics import DiagnosticSeverity, DiagnosticSink
from .lexer import lex_lyrics, lex_music
from .source import SourceSpan

_MUSIC_PREFIX_RE = re.compile(
    r'^Q(?P<voice>\d*)(?:\[(?P<bracket_name>[^\]]*)\]|"(?P<quoted_name>[^"]*)")?$',
    re.IGNORECASE,
)
_LYRIC_PREFIX_RE = re.compile(r"^C(?P<voice>\d*)$", re.IGNORECASE)
_HEADER_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_MAX_VOICE_DIGITS = 100

def parse_jps(path: Path) -> ScoreDocument:
    source = load_jps(path)
    return parse_document(source)

def parse_document(source: JpsDocument) -> ScoreDocument:
    return parse_code(source.code, source_path=str(source.path))

def parse_code(code: str, source_path: str | None = None) -> ScoreDocument:
    diagnostics = DiagnosticSink()
    lines: list[LineNode] = []
    offset = 0
    physical_lines = code.splitlines(keepends=True)
    if not physical_lines and code == "":
        return ScoreDocument(source_path, code, (), ())

    for line_number, physical_line in enumerate(physical_lines, start=1):
        raw = physical_line.rstrip("\r\n")
        lines.append(_parse_line(raw, line_number, offset, diagnostics))
        offset += len(physical_line)

    _validate_delimiters(lines, diagnostics)
    return ScoreDocument(source_path, code, tuple(lines), diagnostics.items)


def _parse_line(
    raw: str,
    line_number: int,
    line_offset: int,
    diagnostics: DiagnosticSink,
) -> LineNode:
    line_span = SourceSpan.on_line(line_number, 1, len(raw) + 1, line_offset)
    stripped = raw.strip()
    if not stripped:
        return BlankLine(LineKind.BLANK, raw, line_span)
    if stripped.startswith("#"):
        return CommentLine(LineKind.COMMENT, raw, line_span, stripped[1:])
    # Case-SENSITIVE literal match (oracle 2026-09-18): the site's own editor JS
    # counts score pages with `code.substring(i+1,i+8)=='[fenye]'` (strict string
    # equality) and splits custom content / render responses with
    # `split('[fenye]')`; the Jianpu-Spec reference implementation likewise uses
    # `split('[fenye]')`. Mixed-case delimiters are ordinary text upstream, so a
    # casefold here would be an unverified broadening (B2, policy §5).
    if stripped == "[fenye]":
        return PageBreakLine(LineKind.PAGE_BREAK, raw, line_span)

    colon = raw.find(":")
    if colon >= 0:
        prefix = raw[:colon].strip()
        body_start = colon + 1
        while body_start < len(raw) and raw[body_start].isspace():
            body_start += 1
        body = raw[body_start:]
        body_column = body_start + 1
        music_match = _MUSIC_PREFIX_RE.fullmatch(prefix)
        if music_match:
            voice = _parse_voice_number(
                music_match.group("voice"), line_span, raw, diagnostics
            )
            if voice is None:
                return UnknownLine(LineKind.UNKNOWN, raw, line_span)
            music_tokens = lex_music(body, line_number, body_column, line_offset, diagnostics)
            return MusicLine(
                LineKind.MUSIC,
                raw,
                line_span,
                voice,
                music_match.group("bracket_name") or music_match.group("quoted_name") or None,
                body,
                music_tokens,
                source_voice=voice if music_match.group("voice") else 1,
            )
        lyric_match = _LYRIC_PREFIX_RE.fullmatch(prefix)
        if lyric_match:
            voice = _parse_voice_number(
                lyric_match.group("voice"), line_span, raw, diagnostics
            )
            if voice is None:
                return UnknownLine(LineKind.UNKNOWN, raw, line_span)
            lyric_tokens = lex_lyrics(body, line_number, body_column, line_offset, diagnostics)
            return LyricLine(LineKind.LYRIC, raw, line_span, voice, body, lyric_tokens)
        if _HEADER_PREFIX_RE.fullmatch(prefix):
            return HeaderLine(LineKind.HEADER, raw, line_span, prefix, body)

    diagnostics.add(
        "JPS001",
        "Unrecognized logical line",
        DiagnosticSeverity.WARNING,
        line_span,
        raw,
        "Preserved the complete line as an unknown node",
    )
    return UnknownLine(LineKind.UNKNOWN, raw, line_span)


def _parse_voice_number(
    digits: str,
    span: SourceSpan,
    raw: str,
    diagnostics: DiagnosticSink,
) -> int | None:
    if len(digits) > _MAX_VOICE_DIGITS:
        diagnostics.add(
            "JPS002",
            f"Voice number exceeds the {_MAX_VOICE_DIGITS}-digit safety limit",
            DiagnosticSeverity.WARNING,
            span,
            raw,
            "Preserved the complete line as an unknown node",
        )
        return None
    return int(digits or 0)


def _validate_delimiters(lines: list[LineNode], diagnostics: DiagnosticSink) -> None:
    stacks: dict[tuple[int, str], list] = {}
    for line in lines:
        if not isinstance(line, MusicLine):
            continue
        for token in line.tokens:
            if token.kind in {
                MusicTokenKind.SPAN_START,
                MusicTokenKind.TUPLET_START,
                MusicTokenKind.BLOCK_START,
                MusicTokenKind.BRACKET_START,
            }:
                family = _delimiter_family(token.kind)
                stacks.setdefault((line.voice, family), []).append(token)
            elif token.kind in {
                MusicTokenKind.SPAN_END,
                MusicTokenKind.BLOCK_END,
                MusicTokenKind.BRACKET_END,
            }:
                family = _delimiter_family(token.kind)
                stack = stacks.setdefault((line.voice, family), [])
                if stack:
                    stack.pop()
                else:
                    diagnostics.add(
                        "JPS102",
                        f"Unmatched {family} close",
                        DiagnosticSeverity.WARNING,
                        token.span,
                        token.raw,
                        "Preserved the closing token",
                    )
    for (_voice, family), stack in stacks.items():
        for token in stack:
            diagnostics.add(
                "JPS101",
                f"Unclosed {family} delimiter",
                DiagnosticSeverity.WARNING,
                token.span,
                token.raw,
                "Preserved the opening token through end of document",
            )

def _delimiter_family(kind: MusicTokenKind) -> str:
    if kind in {MusicTokenKind.SPAN_START, MusicTokenKind.TUPLET_START, MusicTokenKind.SPAN_END}:
        return "span"
    if kind in {MusicTokenKind.BLOCK_START, MusicTokenKind.BLOCK_END}:
        return "block"
    return "bracket"
