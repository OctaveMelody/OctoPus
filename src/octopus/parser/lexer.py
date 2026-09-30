"""Lex music and lyric bodies while preserving unknown source syntax."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from .ast import LyricToken, LyricTokenKind, MusicToken, MusicTokenKind
from .diagnostics import DiagnosticSeverity, DiagnosticSink
from .source import SourceSpan

_NOTE_RE = re.compile(r"^(?P<prefix>[#$=]?)(?P<pitch>[0-9])(?P<suffix>.*)$", re.DOTALL)
_DECORATION_RE = re.compile(r"&(?P<name>[A-Za-z]+(?:\s+tempo)?)")
_STANDALONE_DECORATIONS_RE = re.compile(
    r"&[A-Za-z]+(?:\s+[A-Za-z]+)*"
    r"(?:&[A-Za-z]+(?:\s+[A-Za-z]+)*)*"
    r"(?:\d+)?$"
)
_EXTENSION_RE = re.compile(r"-+[!*<>+]*(?:&[A-Za-z]+)*$")
_BLOCK_NAME_RE = re.compile(r"[A-Za-z]+")
_VALID_BARLINES = frozenset({"|", "||", "|:", ":|", ":|:", "|/", "|*", "||/"})
_STRUCTURAL = frozenset('[]{}()"|:')
_MODIFIER_CHARS = frozenset("<>+!~./^,")
_NOTE_SUFFIX_CHARS = frozenset(
    ("'", ",", ".", "/", "#", "$", "=", "<", ">", "+", "!", "~", "^", "\\")
)
_DURATION_BEARING_KINDS = frozenset(
    {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
    }
)
_DURATION_MODIFIERS = frozenset({"/", "."})


class MusicLexer:
    def __init__(
        self,
        body: str,
        line: int,
        body_column: int,
        line_offset: int,
        diagnostics: DiagnosticSink,
    ) -> None:
        self.body = body
        self.line = line
        self.body_column = body_column
        self.line_offset = line_offset
        self.diagnostics = diagnostics
        self.index = 0
        self.tokens: list[MusicToken] = []

    def lex(self) -> tuple[MusicToken, ...]:
        while self.index < len(self.body):
            if self.body[self.index].isspace():
                self.index += 1
                continue
            start = self.index
            attached = start > 0 and not self.body[start - 1].isspace()
            char = self.body[start]
            if char == "[":
                self._lex_bracket(attached)
            elif char == "]":
                self.index += 1
                self._append(MusicTokenKind.BRACKET_END, start, self.index, attached=attached)
            elif char == '"':
                self._lex_annotation(attached)
            elif char == "{":
                self._lex_block_start(attached)
            elif char == "}":
                self.index += 1
                self._append(MusicTokenKind.BLOCK_END, start, self.index, attached=attached)
            elif char == "(":
                self.index += 2 if self.body.startswith("(y", start) else 1
                kind = (
                    MusicTokenKind.TUPLET_START
                    if self.body.startswith("(y", start)
                    else MusicTokenKind.SPAN_START
                )
                self._append(kind, start, self.index, attached=attached)
            elif char == ")":
                self.index += 1
                self._append(MusicTokenKind.SPAN_END, start, self.index, attached=attached)
            elif char in "|:":
                self._lex_barline(attached)
            else:
                self._lex_atom(attached)

        return tuple(_apply_attached_duration_modifiers(self.tokens))

    def _lex_bracket(self, attached: bool) -> None:
        start = self.index
        previous = self.tokens[-1] if self.tokens else None
        is_grace = bool(
            attached
            and previous
            and previous.kind
            in {
                MusicTokenKind.NOTE,
                MusicTokenKind.REST,
                MusicTokenKind.HIDDEN_REST,
                MusicTokenKind.RHYTHM_NOTE,
                MusicTokenKind.GRACE_GROUP,
            }
        )
        if is_grace:
            end, closed = self._balanced_end(start, "[", "]")
            self.index = end
            value_end = end - 1 if closed else end
            child_start = start + 1
            if child_start < value_end and self.body[child_start] == "h":
                child_start += 1
            children = MusicLexer(
                self.body[child_start:value_end],
                self.line,
                self.body_column + child_start,
                self.line_offset,
                self.diagnostics,
            ).lex()
            self._append(
                MusicTokenKind.GRACE_GROUP,
                start,
                end,
                value=self.body[start + 1 : value_end],
                attached=attached,
                children=children,
            )
            if not closed:
                self._diagnose(
                    "JPS105",
                    "Unclosed attached grace-note group",
                    self._span(start, end),
                    "Consumed the remaining line as the grace-note group",
                )
            return
        self.index += 1
        self._append(MusicTokenKind.BRACKET_START, start, self.index, attached=attached)

    def _lex_annotation(self, attached: bool) -> None:
        start = self.index
        self.index += 1
        while self.index < len(self.body) and self.body[self.index] != '"':
            self.index += 1
        closed = self.index < len(self.body)
        if closed:
            self.index += 1
        value_end = self.index - 1 if closed else self.index
        self._append(
            MusicTokenKind.ANNOTATION,
            start,
            self.index,
            value=self.body[start + 1 : value_end],
            attached=attached,
        )
        if not closed:
            self._diagnose(
                "JPS106",
                "Unclosed quoted annotation",
                self._span(start, self.index),
                "Consumed the remaining line as annotation text",
            )

    def _lex_block_start(self, attached: bool) -> None:
        start = self.index
        self.index += 1
        match = _BLOCK_NAME_RE.match(self.body, self.index)
        if match:
            self.index = match.end()
            value = match.group(0)
        else:
            value = None
        self._append(
            MusicTokenKind.BLOCK_START,
            start,
            self.index,
            value=value,
            attached=attached,
        )
        if value not in {None, "bz", "dsb"}:
            self._diagnose(
                "JPS202",
                f"Unknown temporary voice block type: {value}",
                self._span(start, self.index),
                "Preserved the block name",
                DiagnosticSeverity.INFO,
            )

    def _lex_barline(self, attached: bool) -> None:
        start = self.index
        while self.index < len(self.body) and self.body[self.index] in "|:/*":
            self.index += 1
        if self.body[start : self.index] in _VALID_BARLINES:
            self._append(MusicTokenKind.BARLINE, start, self.index, attached=attached)
        else:
            self._append_unknown(start, self.index, attached)

    def _lex_atom(self, attached: bool) -> None:
        start = self.index
        if self._is_note_start(start):
            self._scan_note()
        else:
            while (
                self.index < len(self.body)
                and not self.body[self.index].isspace()
                and self.body[self.index] not in _STRUCTURAL
            ):
                self.index += 1
        if self.index == start:
            self.index += 1
        raw = self.body[start : self.index]
        if raw.endswith("&a"):
            tempo = re.match(r"\s+tempo\b", self.body[self.index :])
            if tempo:
                self.index += tempo.end()
                raw = self.body[start : self.index]
        self._append_atom(raw, start, self.index, attached)

    def _is_note_start(self, index: int) -> bool:
        if self.body[index].isdigit():
            return True
        return (
            self.body[index] in "#$="
            and index + 1 < len(self.body)
            and self.body[index + 1].isdigit()
        )

    def _scan_note(self) -> None:
        if self.body[self.index] in "#$=":
            self.index += 1
        self.index += 1
        while self.index < len(self.body):
            char = self.body[self.index]
            if char.isspace() or char in _STRUCTURAL or char.isdigit() or char == "-":
                return
            if char == "&":
                decoration = _DECORATION_RE.match(self.body, self.index)
                if decoration is None:
                    return
                self.index = decoration.end()
                continue
            if char not in _NOTE_SUFFIX_CHARS:
                return
            self.index += 1

    def _append_atom(self, raw: str, start: int, end: int, attached: bool) -> None:
        note = _NOTE_RE.match(raw)
        if note:
            pitch = int(note.group("pitch"))
            suffix = note.group("suffix")
            if sum(suffix.count(char) for char in "#$=") > 1:
                self._append_unknown(start, end, attached)
                return
            kind = MusicTokenKind.NOTE
            if pitch == 0:
                kind = MusicTokenKind.REST
            elif pitch == 8:
                kind = MusicTokenKind.HIDDEN_REST
            elif pitch == 9:
                kind = MusicTokenKind.RHYTHM_NOTE
            prefix = note.group("prefix") or None
            postfix = next((char for char in suffix if char in "#$="), None)
            decorations = tuple(match.group("name") for match in _DECORATION_RE.finditer(raw))
            self._append(
                kind,
                start,
                end,
                pitch=pitch,
                accidental=prefix or postfix,
                octave=suffix.count("'") - suffix.count(","),
                duration_slashes=suffix.count("/"),
                duration_dots=suffix.count("."),
                dotted="." in suffix,
                decorations=decorations,
                attached=attached,
            )
            return
        if raw.startswith("&"):
            decoration_matches = tuple(_DECORATION_RE.finditer(raw))
            if decoration_matches:
                decoration_end = decoration_matches[-1].end()
                trailing = raw[decoration_end:]
                if (
                    decoration_end == len(raw)
                    or trailing.isdigit()
                    or all(char in _MODIFIER_CHARS for char in trailing)
                ):
                    first = True
                    for match in decoration_matches:
                        value = match.group("name")
                        self._append(
                            MusicTokenKind.DECORATION,
                            start + match.start(),
                            start + match.end(),
                            value=value,
                            decorations=(value,),
                            attached=attached if first else True,
                        )
                        first = False
                    if trailing.isdigit():
                        for offset, _digit in enumerate(trailing, start=decoration_end):
                            self._append_atom(raw[offset], start + offset, start + offset + 1, True)
                    elif trailing:
                        self._append(
                            MusicTokenKind.MODIFIER,
                            start + decoration_end,
                            end,
                            attached=True,
                        )
                    return
        if _EXTENSION_RE.fullmatch(raw):
            decorations = tuple(match.group("name") for match in _DECORATION_RE.finditer(raw))
            self._append(
                MusicTokenKind.EXTENSION,
                start,
                end,
                decorations=decorations,
                attached=attached,
            )
            return
        if _STANDALONE_DECORATIONS_RE.fullmatch(raw):
            value = raw[1:]
            self._append(
                MusicTokenKind.DECORATION,
                start,
                end,
                value=value,
                decorations=(value,),
                attached=attached,
            )
            return
        modifier_prefix = raw.split("&", 1)[0]
        modifier_decorations = tuple(match.group("name") for match in _DECORATION_RE.finditer(raw))
        if modifier_prefix and all(char in _MODIFIER_CHARS for char in modifier_prefix):
            self._append(
                MusicTokenKind.MODIFIER,
                start,
                end,
                decorations=modifier_decorations,
                attached=attached,
            )
            return
        self._append_unknown(start, end, attached)

    def _append_unknown(self, start: int, end: int, attached: bool) -> None:
        token = self._append(MusicTokenKind.UNKNOWN, start, end, attached=attached)
        self._diagnose(
            "JPS201",
            "Unknown music token",
            token.span,
            "Preserved verbatim as an unknown token",
            DiagnosticSeverity.INFO,
        )

    def _balanced_end(self, start: int, opening: str, closing: str) -> tuple[int, bool]:
        depth = 0
        quote = False
        index = start
        while index < len(self.body):
            char = self.body[index]
            if char == '"':
                quote = not quote
            elif not quote:
                if char == opening:
                    depth += 1
                elif char == closing:
                    depth -= 1
                    if depth == 0:
                        return index + 1, True
            index += 1
        return len(self.body), False

    def _append(
        self,
        kind: MusicTokenKind,
        start: int,
        end: int,
        *,
        value: str | None = None,
        pitch: int | None = None,
        accidental: str | None = None,
        octave: int = 0,
        duration_slashes: int = 0,
        duration_dots: int = 0,
        dotted: bool = False,
        decorations: tuple[str, ...] = (),
        attached: bool = False,
        children: tuple[MusicToken, ...] = (),
    ) -> MusicToken:
        token = MusicToken(
            kind=kind,
            raw=self.body[start:end],
            span=self._span(start, end),
            value=value,
            pitch=pitch,
            accidental=accidental,
            octave=octave,
            duration_slashes=duration_slashes,
            duration_dots=duration_dots,
            dotted=dotted,
            decorations=decorations,
            attached_to_previous=attached,
            children=children,
        )
        self.tokens.append(token)
        return token

    def _span(self, start: int, end: int) -> SourceSpan:
        return SourceSpan.on_line(
            self.line,
            self.body_column + start,
            self.body_column + end,
            self.line_offset,
        )

    def _diagnose(
        self,
        code: str,
        message: str,
        span: SourceSpan,
        recovery: str,
        severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
    ) -> None:
        start = span.start.column - self.body_column
        end = span.end.column - self.body_column
        self.diagnostics.add(code, message, severity, span, self.body[start:end], recovery)


def lex_music(
    body: str,
    line: int,
    body_column: int,
    line_offset: int,
    diagnostics: DiagnosticSink,
) -> tuple[MusicToken, ...]:
    return MusicLexer(body, line, body_column, line_offset, diagnostics).lex()


def _apply_attached_duration_modifiers(tokens: list[MusicToken]) -> list[MusicToken]:
    result = list(tokens)
    for index, token in enumerate(tokens):
        if token.kind != MusicTokenKind.MODIFIER or not token.attached_to_previous:
            continue
        modifier_counts = _duration_modifier_counts(token.raw)
        if not any(modifier_counts.values()):
            continue
        target_index = _attached_duration_target(result, index)
        if target_index is None:
            continue
        target = result[target_index]
        result[target_index] = replace(
            target,
            duration_slashes=target.duration_slashes + modifier_counts["/"],
            duration_dots=target.duration_dots + modifier_counts["."],
            dotted=target.dotted or modifier_counts["."] > 0,
        )
    return result


def _duration_modifier_counts(raw: str) -> dict[str, int]:
    return {modifier: raw.count(modifier) for modifier in _DURATION_MODIFIERS}


def _attached_duration_target(tokens: list[MusicToken], index: int) -> int | None:
    scan = index - 1
    while scan >= 0:
        token = tokens[scan]
        if token.kind in _DURATION_BEARING_KINDS:
            return scan
        if not token.attached_to_previous:
            return None
        scan -= 1
    return None


def _is_cjk(char: str) -> bool:
    value = ord(char)
    return 0x3400 <= value <= 0x4DBF or 0x4E00 <= value <= 0x9FFF or 0xF900 <= value <= 0xFAFF


def lex_lyrics(
    body: str,
    line: int,
    body_column: int,
    line_offset: int,
    diagnostics: DiagnosticSink,
) -> tuple[LyricToken, ...]:
    tokens: list[LyricToken] = []
    index = 0

    def append(kind: LyricTokenKind, start: int, end: int) -> None:
        tokens.append(
            LyricToken(
                kind,
                body[start:end],
                SourceSpan.on_line(
                    line,
                    body_column + start,
                    body_column + end,
                    line_offset,
                ),
            )
        )

    while index < len(body):
        if body[index].isspace() and body[index] != "\u3000":
            index += 1
            continue
        start = index
        char = body[index]
        if char == '"':
            index += 1
            while index < len(body) and body[index] != '"':
                index += 1
            if index < len(body):
                index += 1
            else:
                span = SourceSpan.on_line(
                    line, body_column + start, body_column + index, line_offset
                )
                diagnostics.add(
                    "JPS301",
                    "Unclosed lyric annotation",
                    DiagnosticSeverity.WARNING,
                    span,
                    body[start:index],
                    "Consumed the remaining line as annotation text",
                )
            append(LyricTokenKind.ANNOTATION, start, index)
        elif char == "@":
            index += 1
            append(LyricTokenKind.SKIP, start, index)
        elif char == "~":
            index += 1
            append(LyricTokenKind.EXTEND, start, index)
        elif char == "/":
            index += 1
            append(LyricTokenKind.SEPARATOR, start, index)
        elif _is_cjk(char):
            index += 1
            append(LyricTokenKind.TEXT, start, index)
        elif unicodedata.category(char).startswith("P"):
            index += 1
            if char in {"-", "‐", "‑"} and tokens and tokens[-1].kind == LyricTokenKind.TEXT:
                previous = tokens[-1]
                if previous.span.end.offset == line_offset + body_column + start - 1:
                    tokens[-1] = LyricToken(
                        previous.kind,
                        previous.raw + char,
                        SourceSpan(previous.span.start, SourceSpan.on_line(
                            line,
                            body_column + start,
                            body_column + index,
                            line_offset,
                        ).end),
                    )
                    continue
            append(LyricTokenKind.PUNCTUATION, start, index)
        else:
            index += 1
            while index < len(body):
                candidate = body[index]
                if (
                    (candidate.isspace() and candidate != "\u3000")
                    or candidate in '"@~/'
                    or _is_cjk(candidate)
                    or unicodedata.category(candidate).startswith("P")
                ):
                    break
                index += 1
            append(LyricTokenKind.TEXT, start, index)
    return tuple(tokens)
