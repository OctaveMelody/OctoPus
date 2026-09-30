"""Small, source-neutral vertical-spacing policies for score layout.

The page-layout facade still decides when these policies apply.  This module
owns only the arithmetic and simple source predicates so the large orchestration
function does not also define basic spacing semantics.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from octopus.normalization.types import LyricLineModel, MusicEvent, SemanticConstruct, SystemModel
from octopus.parser.ast import LyricTokenKind, MusicTokenKind
from octopus.render.core.layout_types import PageMetrics

REPEAT_ENDING_CLEARANCE = 12.0
DSB_INCOMING_CLEARANCE = 28.0


def system_height(
    metrics: PageMetrics,
    lyric_lines: int,
    *,
    has_annotation: bool = False,
    has_extension: bool = False,
    has_repeat_ending: bool = False,
    incoming_repeat_ending: bool = False,
    single_voice: bool = False,
    minimum_height: float | None = None,
    include_multi_verse_gap: bool = True,
) -> float:
    """Calculate the evidence-driven vertical height for one source row."""

    multi_verse_gap = (
        12
        if include_multi_verse_gap
        and lyric_lines == 2
        and metrics.height_cici >= 10
        and not has_annotation
        and not has_extension
        and not has_repeat_ending
        and len(metrics.time_sig.split()) <= 1
        else 0
    )
    repeat_ending_gap = REPEAT_ENDING_CLEARANCE if incoming_repeat_ending else 0.0
    base_evidence_height = (
        25
        + metrics.height_quci
        + metrics.height_ciqu
        + lyric_lines * metrics.lyric_line_spacing
    )
    evidence_height = base_evidence_height + max(multi_verse_gap, repeat_ending_gap)
    minimum = (
        minimum_height
        if minimum_height is not None
        else 47
        if single_voice
        else metrics.height_shengbu + 47
    )
    return float(max(minimum, evidence_height))


def multi_voice_lyrics_between(
    system: SystemModel,
    start_line: int,
    end_line: int | None,
) -> list[LyricLineModel]:
    """Return lyrics strictly between two source music lines in source order."""

    return sorted(
        (
            lyric
            for voice in system.voices
            for lyric in voice.lyrics
            if lyric.span.start.line > start_line
            and (end_line is None or lyric.span.start.line < end_line)
        ),
        key=lambda lyric: lyric.span.start.offset,
    )


def multi_voice_source_line_has_repeat_ending(
    system: SystemModel,
    source_line: int,
) -> bool:
    """Return whether a source line owns a visible repeat-ending barline."""

    return any(
        event.span.start.line == source_line
        and event.kind == MusicTokenKind.BARLINE
        and "[" in event.code
        for voice in system.voices
        for event in voice.events
    )


def system_line_has_visible_block(system: SystemModel, source_line: int) -> bool:
    """Return whether a source line intersects a visible block construct."""

    return any(
        construct.kind == "block"
        and construct.value is None
        and construct.source_span.start.line <= source_line <= construct.source_span.end.line
        for voice in system.voices
        for construct in voice.constructs
    )


def system_incoming_block_clearance(system: SystemModel | None) -> float:
    """Reserve shared transition space before a visible non-DSB block."""

    if system is None or not system.music_line_numbers:
        return 0.0
    first_line = min(system.music_line_numbers)
    return DSB_INCOMING_CLEARANCE if system_line_has_visible_block(system, first_line) else 0.0


def system_outgoing_block_clearance(system: SystemModel) -> float:
    """Reserve shared transition space after a visible non-DSB block."""

    if not system.music_line_numbers:
        return 0.0
    last_line = max(system.music_line_numbers)
    return DSB_INCOMING_CLEARANCE if system_line_has_visible_block(system, last_line) else 0.0


def voice_name_column_width(system: SystemModel) -> int:
    """Return the fixed-width column required by declared voice names."""

    names = [
        name
        for voice in system.voices
        for name in voice.declared_names or ((voice.name,) if voice.name else ())
    ]
    if not names:
        return 0
    max_cells = max(
        sum(2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1 for char in name)
        for name in names
    )
    return 6 + 8 * max_cells


def source_line_has_hidden_bz(
    constructs: tuple[SemanticConstruct, ...],
    source_line: int,
) -> bool:
    """Return whether a source line is covered by a hidden BZ block."""

    return any(
        construct.kind == "block"
        and construct.value == "bz"
        and construct.source_span.start.line <= source_line <= construct.source_span.end.line
        for construct in constructs
    )


def source_group_has_repeat_ending(source_group: list[MusicEvent]) -> bool:
    """Return whether a source event group contains a repeat-ending barline."""

    return any(
        event.kind == MusicTokenKind.BARLINE and "[" in event.code
        for event in source_group
    )


def source_group_needs_repeat_clearance(
    source_group: list[MusicEvent],
    constructs: tuple[SemanticConstruct, ...],
) -> bool:
    """Apply repeat-ending clearance once when hidden BZ is not reserving it."""

    return source_group_has_repeat_ending(source_group) and not source_line_has_hidden_bz(
        constructs,
        source_group[0].span.start.line,
    )


def lyrics_have_annotations(lyrics: Iterable[LyricLineModel]) -> bool:
    """Return whether any lyric line contains an annotation token."""

    return any(
        token.kind == LyricTokenKind.ANNOTATION
        for lyric in lyrics
        for token in lyric.tokens
    )


def lyrics_have_extensions(lyrics: Iterable[LyricLineModel]) -> bool:
    """Return whether any lyric line contains an extension token."""

    return any(
        token.kind == LyricTokenKind.EXTEND
        for lyric in lyrics
        for token in lyric.tokens
    )


__all__ = [
    "REPEAT_ENDING_CLEARANCE",
    "DSB_INCOMING_CLEARANCE",
    "lyrics_have_annotations",
    "lyrics_have_extensions",
    "multi_voice_lyrics_between",
    "multi_voice_source_line_has_repeat_ending",
    "source_group_has_repeat_ending",
    "source_group_needs_repeat_clearance",
    "source_line_has_hidden_bz",
    "system_height",
    "system_incoming_block_clearance",
    "system_line_has_visible_block",
    "system_outgoing_block_clearance",
    "voice_name_column_width",
]
