"""Typed parser nodes for source lines, music tokens, lyric tokens, and spans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias, cast

from .._json import json_value
from .diagnostics import Diagnostic
from .source import SourceSpan


class LineKind(StrEnum):
    BLANK = "blank"
    COMMENT = "comment"
    PAGE_BREAK = "page_break"
    HEADER = "header"
    MUSIC = "music"
    LYRIC = "lyric"
    UNKNOWN = "unknown"


class MusicTokenKind(StrEnum):
    NOTE = "note"
    REST = "rest"
    HIDDEN_REST = "hidden_rest"
    RHYTHM_NOTE = "rhythm_note"
    EXTENSION = "extension"
    BARLINE = "barline"
    SPAN_START = "span_start"
    SPAN_END = "span_end"
    TUPLET_START = "tuplet_start"
    BLOCK_START = "block_start"
    BLOCK_END = "block_end"
    GRACE_GROUP = "grace_group"
    BRACKET_START = "bracket_start"
    BRACKET_END = "bracket_end"
    ANNOTATION = "annotation"
    DECORATION = "decoration"
    MODIFIER = "modifier"
    IGNORED_TEXT = "ignored_text"
    UNKNOWN = "unknown"


class LyricTokenKind(StrEnum):
    TEXT = "text"
    PUNCTUATION = "punctuation"
    SKIP = "skip"
    EXTEND = "extend"
    SEPARATOR = "separator"
    ANNOTATION = "annotation"


@dataclass(frozen=True, slots=True)
class MusicToken:
    kind: MusicTokenKind
    raw: str
    span: SourceSpan
    value: str | None = None
    pitch: int | None = None
    accidental: str | None = None
    octave: int = 0
    duration_slashes: int = 0
    duration_dots: int = 0
    dotted: bool = False
    decorations: tuple[str, ...] = ()
    attached_to_previous: bool = False
    children: tuple[MusicToken, ...] = ()


@dataclass(frozen=True, slots=True)
class LyricToken:
    kind: LyricTokenKind
    raw: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BlankLine:
    kind: LineKind
    raw: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CommentLine:
    kind: LineKind
    raw: str
    span: SourceSpan
    text: str


@dataclass(frozen=True, slots=True)
class PageBreakLine:
    kind: LineKind
    raw: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class HeaderLine:
    kind: LineKind
    raw: str
    span: SourceSpan
    prefix: str
    value: str


@dataclass(frozen=True, slots=True)
class MusicLine:
    kind: LineKind
    raw: str
    span: SourceSpan
    voice: int
    voice_name: str | None
    body: str
    tokens: tuple[MusicToken, ...]
    # Export replay identity: unnumbered Q aliases Q1; explicit Q0 remains distinct.
    source_voice: int | None = None


@dataclass(frozen=True, slots=True)
class LyricLine:
    kind: LineKind
    raw: str
    span: SourceSpan
    voice: int
    body: str
    tokens: tuple[LyricToken, ...]


@dataclass(frozen=True, slots=True)
class UnknownLine:
    kind: LineKind
    raw: str
    span: SourceSpan


LineNode: TypeAlias = (
    BlankLine | CommentLine | PageBreakLine | HeaderLine | MusicLine | LyricLine | UnknownLine
)


@dataclass(frozen=True, slots=True)
class ScoreDocument:
    source_path: str | None
    code: str
    lines: tuple[LineNode, ...]
    diagnostics: tuple[Diagnostic, ...]


def document_to_dict(
    document: ScoreDocument, *, include_diagnostics: bool = False
) -> dict[str, Any]:
    """Serialize parser data, omitting source provenance unless requested."""
    result = cast(dict[str, Any], json_value(document))
    # Preserve the public parser snapshot schema; replay metadata stays on the AST.
    for line in result["lines"]:
        line.pop("source_voice", None)
    if not include_diagnostics:
        result.pop("source_path", None)
    return result
