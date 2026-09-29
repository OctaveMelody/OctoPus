"""Multi-voice vertical spacing and transition policy."""

from __future__ import annotations

from re_tomato.normalization.types import SemanticConstruct, SystemModel, VoiceModel
from re_tomato.parser.ast import MusicTokenKind
from re_tomato.render.core.layout_types import PageMetrics
from re_tomato.render.layout_engine.profiles import SystemEntranceProfile, SystemTransitionProfile

from .system_spacing import DSB_INCOMING_CLEARANCE, REPEAT_ENDING_CLEARANCE
from .system_spacing import lyrics_have_annotations as _lyrics_have_annotations
from .system_spacing import lyrics_have_extensions as _lyrics_have_extensions
from .system_spacing import multi_voice_lyrics_between as _multi_voice_lyrics_between
from .system_spacing import (
    multi_voice_source_line_has_repeat_ending as _multi_voice_source_line_has_repeat_ending,
)
from .system_spacing import system_height as _system_height
from .system_spacing import system_incoming_block_clearance as _system_incoming_block_clearance

TERMINAL_MARK_CLEARANCE = 12.0
DSB_BRACKET_OVERLAP = 4.0

def multi_voice_row_gap(
    system: SystemModel,
    metrics: PageMetrics,
    start_line: int,
    end_line: int,
) -> float:
    lyrics = _multi_voice_lyrics_between(system, start_line, end_line)
    has_repeat_ending = _multi_voice_source_line_has_repeat_ending(system, start_line)
    incoming_repeat_ending = _multi_voice_source_line_has_repeat_ending(system, end_line)
    base_gap = _system_height(
        metrics,
        len(lyrics),
        has_annotation=_lyrics_have_annotations(lyrics),
        has_extension=_lyrics_have_extensions(lyrics),
        has_repeat_ending=has_repeat_ending,
        incoming_repeat_ending=incoming_repeat_ending,
        single_voice=True,
        minimum_height=0.0,
        include_multi_verse_gap=False,
    )
    dsb_gap_count = sum(
        _multi_voice_source_line_has_dsb(system, source_line)
        for source_line in (start_line, end_line)
    )
    terminal_mark_gap = (
        TERMINAL_MARK_CLEARANCE
        if _multi_voice_source_line_has_terminal_mark(system, end_line)
        and not (
            _system_contains_dsb(system)
            and _multi_voice_source_line_has_only_terminal_extensions(system, end_line)
        )
        else 0.0
    )
    if terminal_mark_gap and lyrics and all(not lyric.tokens for lyric in lyrics):
        terminal_mark_gap = 0.0
    elif (
        terminal_mark_gap
        and _multi_voice_source_line_follows_empty_lyric_gap(system, start_line)
        and _multi_voice_source_line_max_octave(system, start_line)
        > _multi_voice_source_line_max_octave(system, end_line)
    ):
        terminal_mark_gap -= DSB_BRACKET_OVERLAP
    hidden_rest_terminal_gap = (
        TERMINAL_MARK_CLEARANCE
        if end_line != min(system.music_line_numbers, default=end_line)
        and _multi_voice_source_line_has_hidden_rest_terminal_mark(system, end_line)
        else 0.0
    )
    dsb_repeat_overlap = (
        REPEAT_ENDING_CLEARANCE - DSB_BRACKET_OVERLAP
        if incoming_repeat_ending
        and _multi_voice_source_line_has_dsb(system, end_line)
        else 0.0
    )
    return (
        base_gap
        + DSB_INCOMING_CLEARANCE * dsb_gap_count
        + dsb_repeat_overlap
        + hidden_rest_terminal_gap
        + terminal_mark_gap
    )


def multi_voice_tail_height(
    system: SystemModel,
    metrics: PageMetrics,
    next_system: SystemModel | None = None,
) -> float:
    source_lines = sorted(system.music_line_numbers)
    if not source_lines:
        return _system_height(metrics, 0, single_voice=False)
    if _is_empty_lyric_system(next_system):
        return _system_outgoing_dsb_clearance(system)
    lyrics = _multi_voice_lyrics_between(system, source_lines[-1], None)
    tail_height = _system_height(
        metrics,
        len(lyrics),
        has_annotation=_lyrics_have_annotations(lyrics),
        has_extension=_lyrics_have_extensions(lyrics),
        has_repeat_ending=_multi_voice_source_line_has_repeat_ending(
            system,
            source_lines[-1],
        ),
        single_voice=True,
        minimum_height=0.0,
        include_multi_verse_gap=not (
            next_system is not None and len(next_system.voices) == 1
        ),
    )
    if next_system is not None and len(next_system.voices) == 1:
        tail_height += _system_incoming_block_clearance(next_system)
    elif _multi_voice_source_line_has_tail_hook(system, source_lines[-1]):
        # A terminal ykh hook already carries the transition into the next
        # multi-voice staff; do not add a second generic staff-separation gap.
        pass
    elif _lyrics_have_annotations(lyrics):
        # An annotated trailing lyric line supplies its own inter-system
        # clearance; avoid stacking the generic staff-separation gap.
        pass
    else:
        tail_height += metrics.height_shengbu
    return SystemTransitionProfile(
        base_tail_height=tail_height,
        incoming_construct_clearance=_multi_voice_incoming_clearance(next_system),
        dsb_transition_clearance=_multi_voice_dsb_transition_clearance(next_system),
        hidden_rest_transition_clearance=(
            _multi_voice_hidden_rest_transition_clearance(next_system)
        ),
        outgoing_dsb_clearance=_system_outgoing_dsb_clearance(system),
    ).total_height


def _multi_voice_source_line_has_tail_hook(
    system: SystemModel,
    source_line: int,
) -> bool:
    """Return whether a source row ends with Jianpu's ykh continuation hook."""
    return any(
        event.span.start.line == source_line
        and "ykh" in event.decorations
        for voice in system.voices
        for event in voice.events
    )


def _multi_voice_incoming_clearance(next_system: SystemModel | None) -> float:
    """Reserve space for constructs anchored to the next system's first row."""
    if next_system is None or not next_system.music_line_numbers:
        return 0.0
    first_line = min(next_system.music_line_numbers)
    has_bracket = any(
        construct.kind == "bracket"
        and construct.ending_is_first_segment
        and construct.ending_reserves_clearance
        and construct.source_span.start.line <= first_line <= construct.source_span.end.line
        and not _bracket_starts_hidden_barline(voice, construct)
        for voice in next_system.voices
        for construct in voice.constructs
    )
    has_dsb = _multi_voice_source_line_has_dsb(next_system, first_line)
    if has_dsb and has_bracket:
        return DSB_INCOMING_CLEARANCE + REPEAT_ENDING_CLEARANCE - DSB_BRACKET_OVERLAP
    if has_dsb:
        return DSB_INCOMING_CLEARANCE
    return REPEAT_ENDING_CLEARANCE if has_bracket else 0.0


def _is_empty_lyric_system(system: SystemModel | None) -> bool:
    """Return whether a system contains only blank lyric lines."""
    if system is None or system.music_line_numbers:
        return False
    lyric_lines = [lyric for voice in system.voices for lyric in voice.lyrics]
    return bool(lyric_lines) and all(not lyric.tokens for lyric in lyric_lines)


def _multi_voice_dsb_transition_clearance(next_system: SystemModel | None) -> float:
    """Reserve hidden-barline bracket space before a DSB-leading system."""
    if next_system is None or not next_system.music_line_numbers:
        return 0.0
    first_line = min(next_system.music_line_numbers)
    if not _multi_voice_source_line_has_dsb(next_system, first_line):
        return 0.0
    has_hidden_barline_bracket = any(
        construct.kind == "bracket"
        and construct.source_span.start.line == first_line
        and _bracket_starts_hidden_barline(voice, construct)
        for voice in next_system.voices
        for construct in voice.constructs
    )
    return REPEAT_ENDING_CLEARANCE - DSB_BRACKET_OVERLAP if has_hidden_barline_bracket else 0.0


def _multi_voice_hidden_rest_transition_clearance(
    next_system: SystemModel | None,
) -> float:
    """Reserve headroom before a system led by a terminal hidden-rest sentinel."""
    if next_system is None or not next_system.music_line_numbers:
        return 0.0
    first_line = min(next_system.music_line_numbers)
    return (
        TERMINAL_MARK_CLEARANCE
        if _multi_voice_source_line_has_hidden_rest_terminal_mark(next_system, first_line)
        else 0.0
    )


def multi_voice_leading_clearance(system: SystemModel) -> float:
    """Reserve semantic headroom before a continuation page's first staff."""
    if len(system.voices) < 2 or not system.music_line_numbers:
        return 0.0
    return SystemEntranceProfile(
        incoming_construct_clearance=_multi_voice_incoming_clearance(system),
        terminal_mark_clearance=multi_voice_terminal_mark_clearance(system),
    ).page_leading_clearance


def multi_voice_terminal_mark_clearance(
    system: SystemModel,
    *,
    previous_system: SystemModel | None = None,
) -> float:
    """Reserve headroom before a row containing a terminal ``!`` mark."""
    if len(system.voices) < 2 or not system.music_line_numbers:
        return 0.0
    if _is_empty_lyric_system(previous_system):
        return 0.0
    first_line = min(system.music_line_numbers)
    return (
        TERMINAL_MARK_CLEARANCE
        if _multi_voice_source_line_has_terminal_mark(system, first_line)
        else 0.0
    )


def _multi_voice_source_line_has_terminal_mark(
    system: SystemModel,
    source_line: int,
) -> bool:
    """Return whether a source row contains Jianpu's terminal crescendo mark."""
    return any(
        event.span.start.line == source_line
        and event.kind not in {MusicTokenKind.BARLINE, MusicTokenKind.HIDDEN_REST}
        and event.code.endswith("!")
        for voice in system.voices
        for event in voice.events
    )


def _multi_voice_source_line_max_octave(
    system: SystemModel,
    source_line: int,
) -> int:
    return max(
        (
            event.octave
            for voice in system.voices
            for event in voice.events
            if event.span.start.line == source_line
        ),
        default=0,
    )


def _multi_voice_source_line_follows_empty_lyric_gap(
    system: SystemModel,
    source_line: int,
) -> bool:
    source_lines = sorted(system.music_line_numbers)
    try:
        source_line_index = source_lines.index(source_line)
    except ValueError:
        return False
    if source_line_index == 0:
        return False
    lyrics = _multi_voice_lyrics_between(
        system,
        source_lines[source_line_index - 1],
        source_line,
    )
    return bool(lyrics) and all(not lyric.tokens for lyric in lyrics)


def _multi_voice_source_line_has_hidden_rest_terminal_mark(
    system: SystemModel,
    source_line: int,
) -> bool:
    return any(
        event.span.start.line == source_line
        and event.kind == MusicTokenKind.HIDDEN_REST
        and event.code.endswith("!")
        for voice in system.voices
        for event in voice.events
    )


def _multi_voice_source_line_has_only_terminal_extensions(
    system: SystemModel,
    source_line: int,
) -> bool:
    terminal_events = [
        event
        for voice in system.voices
        for event in voice.events
        if event.span.start.line == source_line
        and event.code.endswith("!")
        and event.kind not in {MusicTokenKind.BARLINE, MusicTokenKind.HIDDEN_REST}
    ]
    return bool(terminal_events) and all(
        event.kind == MusicTokenKind.EXTENSION for event in terminal_events
    )


def _multi_voice_dsb_terminal_gap_count(system: SystemModel) -> int:
    source_lines = sorted(system.music_line_numbers)
    return sum(
        _multi_voice_source_line_has_only_terminal_extensions(system, source_line)
        for source_line in source_lines[1:]
    ) if _system_contains_dsb(system) else 0


def _bracket_starts_hidden_barline(
    voice: VoiceModel,
    construct: SemanticConstruct,
) -> bool:
    """Return whether an ending bracket is anchored to Jianpu's hidden ``|/`` barline."""
    return any(
        event.index == construct.start_event_index and event.code.startswith("|n")
        for event in voice.events
    )


def _multi_voice_source_line_has_dsb(system: SystemModel, source_line: int) -> bool:
    return any(
        construct.kind == "block"
        and construct.value == "dsb"
        and construct.source_span.start.line <= source_line <= construct.source_span.end.line
        for voice in system.voices
        for construct in voice.constructs
    )


def _system_contains_dsb(system: SystemModel) -> bool:
    return any(
        construct.kind == "block" and construct.value == "dsb"
        for voice in system.voices
        for construct in voice.constructs
    )


def _system_outgoing_dsb_clearance(system: SystemModel) -> float:
    """Reserve DSB tail space when a system ends inside a DSB block."""
    source_lines = sorted(system.music_line_numbers)
    if source_lines and _multi_voice_source_line_has_dsb(system, source_lines[-1]):
        return DSB_INCOMING_CLEARANCE
    return 0.0


def _system_incoming_dsb_clearance(system: SystemModel | None) -> float:
    """Reserve DSB headroom when a system starts inside a DSB block."""
    if system is None or not system.music_line_numbers:
        return 0.0
    if _multi_voice_source_line_has_dsb(system, min(system.music_line_numbers)):
        return DSB_INCOMING_CLEARANCE
    return 0.0


__all__ = [
    "_multi_voice_dsb_terminal_gap_count",
    "_system_incoming_dsb_clearance",
    "_system_outgoing_dsb_clearance",
    "multi_voice_leading_clearance",
    "multi_voice_row_gap",
    "multi_voice_tail_height",
    "multi_voice_terminal_mark_clearance",
]
