"""Mutable page, system, and voice builders; finalize immutable model values."""

from __future__ import annotations

from dataclasses import dataclass, field

from re_tomato.normalization.source import combine_spans as _combine_spans
from re_tomato.normalization.types import (
    LyricLineModel,
    MusicEvent,
    PageModel,
    SemanticConstruct,
    SystemModel,
    VoiceGroupModel,
    VoiceModel,
)
from re_tomato.parser.source import SourceSpan


@dataclass(slots=True)
class _VoiceBuilder:
    voice: int
    name: str | None = None
    declared_names: list[str] = field(default_factory=list)
    music_line_numbers: list[int] = field(default_factory=list)
    lyric_line_numbers: list[int] = field(default_factory=list)
    events: list[MusicEvent] = field(default_factory=list)
    lyrics: list[LyricLineModel] = field(default_factory=list)
    constructs: list[SemanticConstruct] = field(default_factory=list)
    line_names: dict[int, str] = field(default_factory=dict)
    first_span: SourceSpan | None = None
    last_span: SourceSpan | None = None

    def add_span(self, span: SourceSpan) -> None:
        if self.first_span is None or span.start.offset < self.first_span.start.offset:
            self.first_span = span
        if self.last_span is None or span.end.offset > self.last_span.end.offset:
            self.last_span = span

    def finalize(self) -> VoiceModel:
        return VoiceModel(
            voice=self.voice,
            name=self.name,
            declared_names=tuple(self.declared_names),
            source_span=_combine_spans(self.first_span, self.last_span),
            music_line_numbers=tuple(self.music_line_numbers),
            lyric_line_numbers=tuple(self.lyric_line_numbers),
            events=tuple(self.events),
            lyrics=tuple(self.lyrics),
            constructs=tuple(self.constructs),
            line_names=tuple(sorted(self.line_names.items())),
        )


@dataclass(slots=True)
class _SystemBuilder:
    index: int
    page_index: int = 1
    voices: dict[int, _VoiceBuilder] = field(default_factory=dict)
    voice_groups: tuple[VoiceGroupModel, ...] = ()
    music_line_numbers: list[int] = field(default_factory=list)
    lyric_line_numbers: list[int] = field(default_factory=list)
    first_span: SourceSpan | None = None
    last_span: SourceSpan | None = None

    def add_span(self, span: SourceSpan) -> None:
        if self.first_span is None or span.start.offset < self.first_span.start.offset:
            self.first_span = span
        if self.last_span is None or span.end.offset > self.last_span.end.offset:
            self.last_span = span

    def voice(self, number: int) -> _VoiceBuilder:
        builder = self.voices.get(number)
        if builder is None:
            builder = _VoiceBuilder(number)
            self.voices[number] = builder
        return builder

    def finalize(self) -> SystemModel:
        return SystemModel(
            index=self.index,
            source_span=_combine_spans(self.first_span, self.last_span),
            music_line_numbers=tuple(self.music_line_numbers),
            lyric_line_numbers=tuple(self.lyric_line_numbers),
            voices=tuple(self.voices[number].finalize() for number in sorted(self.voices)),
            voice_groups=self.voice_groups,
        )


@dataclass(slots=True)
class _PageBuilder:
    index: int
    systems: list[_SystemBuilder] = field(default_factory=list)
    first_span: SourceSpan | None = None
    last_span: SourceSpan | None = None

    def add_span(self, span: SourceSpan) -> None:
        if self.first_span is None or span.start.offset < self.first_span.start.offset:
            self.first_span = span
        if self.last_span is None or span.end.offset > self.last_span.end.offset:
            self.last_span = span

    def finalize(self) -> PageModel:
        return PageModel(
            index=self.index,
            source_span=_combine_spans(self.first_span, self.last_span),
            systems=tuple(system.finalize() for system in self.systems),
        )
