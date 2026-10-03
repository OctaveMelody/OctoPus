"""Finalize voice projection, hidden streams, constructs, and tail clearance."""

from __future__ import annotations

from octopus.normalization.types import (
    LyricLineModel,
    MusicEvent,
    ScoreModel,
    SystemModel,
    VoiceModel,
)
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
    PageMetrics,
)
from octopus.render.layout_engine.constructs import collect_constructs as _collect_constructs
from octopus.render.layout_engine.hidden.hidden_rest_slots import reconcile_hidden_rest_slots
from octopus.render.layout_engine.hidden.hidden_stream_layout import (
    hidden_dsb_events_for_layout,
    lower_aligned_visible_dsb_targets,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    include_interior_music_source_lines as _include_interior_music_source_lines,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    include_terminal_hidden_rest_source_lines as _include_terminal_hidden_rest_source_lines,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    include_trailing_cross_row_hook_source_lines as _include_trailing_cross_row_hook_source_lines,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    is_supported_legacy_lyric_line as _is_supported_legacy_lyric_line,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    legacy_intrinsic_source_lines as _legacy_intrinsic_source_lines,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    numbered_lyric_source_lines as _numbered_lyric_source_lines,
)
from octopus.render.layout_engine.lyrics.lyrics import (
    _legacy_lyric_gap_by_event,
    _legacy_lyric_text_by_event,
)
from octopus.render.layout_engine.spacing.system_spacing import (
    lyrics_have_annotations as _lyrics_have_annotations,
)
from octopus.render.layout_engine.spacing.system_spacing import (
    lyrics_have_extensions as _lyrics_have_extensions,
)
from octopus.render.layout_engine.spacing.system_spacing import (
    source_group_needs_repeat_clearance as _source_group_needs_repeat_clearance,
)
from octopus.render.layout_engine.spacing.system_spacing import system_height as _system_height
from octopus.render.layout_engine.spacing.system_spacing import (
    system_outgoing_block_clearance as _system_outgoing_block_clearance,
)
from octopus.render.layout_engine.spacing.vertical_spacing import (
    _system_incoming_dsb_clearance,
    _system_outgoing_dsb_clearance,
)
from octopus.render.layout_engine.streams import dsb_stream_beat_unit as _dsb_stream_beat_unit
from octopus.render.layout_engine.system_state import _SystemLayoutState
from octopus.render.layout_engine.voice_projection import _justify_voice_rows


def _finalize_layout_voice(
    *,
    model: ScoreModel,
    page_index: int,
    system: SystemModel,
    voice: VoiceModel,
    voice_index: int,
    voice_y: float,
    voice_note_start_x: float,
    metrics: PageMetrics,
    layout: LayoutPage,
    state: _SystemLayoutState,
    voice_event_start: int,
    tail_barlines: list[LayoutEvent],
    source_groups: list[list[MusicEvent]],
    lyrics_by_music_line: dict[int, list[LyricLineModel]],
    previous_source_line: int | None,
    page_uses_legacy_intrinsic_grid: bool,
    max_voice_y: float,
    system_tail_height: float,
) -> tuple[float, float]:
    shared_lyric_text_by_voice = state.shared_lyric_text_by_voice
    shared_lyric_gap_by_voice = state.shared_lyric_gap_by_voice
    shared_grace_raw_by_voice = state.shared_grace_raw_by_voice
    next_system = state.next_system
    laid_out = layout.events[voice_event_start:]
    grace_host_indices = frozenset(
        construct.host_event_index
        for construct in voice.constructs
        if construct.kind == "grace" and construct.host_event_index is not None
    )
    shared_grace_raw_by_voice[voice_index] = {
        construct.host_event_index: str(construct.value)
        for construct in voice.constructs
        if construct.kind == "grace" and construct.host_event_index is not None
    }
    legacy_source_lines = (
        _legacy_intrinsic_source_lines(lyrics_by_music_line)
        if len(system.voices) == 1
        or voice_note_start_x == metrics.note_start_x
        else (
            frozenset(item.event.span.start.line for item in laid_out)
            if laid_out
            and laid_out[-1].event.code == "|j"
            and len({item.event.span.start.line for item in laid_out}) == 1
            else frozenset()
        )
    )
    legacy_source_lines = _include_interior_music_source_lines(
        legacy_source_lines,
        laid_out,
        include_lyricless=page_uses_legacy_intrinsic_grid,
    )
    legacy_source_lines = _include_trailing_cross_row_hook_source_lines(
        legacy_source_lines,
        laid_out,
    )
    if len(system.voices) == 1:
        legacy_source_lines = _include_terminal_hidden_rest_source_lines(
            legacy_source_lines,
            laid_out,
            lyrics_by_music_line,
        )
    if (
        len(system.voices) >= 2
        and voice.lyrics
        and any(line.tokens for line in voice.lyrics)
        and all(
            _is_supported_legacy_lyric_line(line)
            for line in voice.lyrics
            if line.tokens
        )
    ):
        shared_lyric_text_by_voice[voice_index] = _legacy_lyric_text_by_event(
            metrics,
            layout.header,
            laid_out,
            lyrics_by_music_line,
        )
        shared_lyric_gap_by_voice[voice_index] = _legacy_lyric_gap_by_event(
            metrics,
            layout.header,
            laid_out,
            lyrics_by_music_line,
        )
    intrinsic_tail_lines = frozenset(
        source_group[-1].span.start.line
        for source_group in source_groups
        if source_group[-1].kind
        in {MusicTokenKind.EXTENSION, MusicTokenKind.HIDDEN_REST}
        and "ykh" in source_group[-1].decorations
    )
    legacy_source_lines |= intrinsic_tail_lines
    _justify_voice_rows(
        [
            *laid_out,
            *(
                tail
                for tail in tail_barlines
                if (
                    tail.event.span.start.line in legacy_source_lines
                    or tail.event.span.start.line in intrinsic_tail_lines
                )
                and (
                    tail.event.span.start.line in intrinsic_tail_lines
                    or tail.event.kind == MusicTokenKind.BARLINE
                )
            ),
        ],
        metrics,
        note_start_x=voice_note_start_x,
        grace_host_indices=grace_host_indices,
        grace_raw_by_host={
            construct.host_event_index: str(construct.value)
            for construct in voice.constructs
            if construct.kind == "grace"
            and construct.host_event_index is not None
        },
        reserves_lyric_dotted_notes=(
            len(system.voices) > 1 and voice.voice == 0
        ),
        legacy_intrinsic_source_lines=legacy_source_lines,
        numbered_lyric_source_lines=_numbered_lyric_source_lines(
            lyrics_by_music_line
        ),
        legacy_lyric_text_by_event=(
            _legacy_lyric_text_by_event(
                metrics,
                layout.header,
                laid_out,
                lyrics_by_music_line,
            )
            if legacy_source_lines
            else {}
        ),
    )
    hidden_events = hidden_dsb_events_for_layout(
        voice.events,
        voice.constructs,
        [*laid_out, *tail_barlines],
        page_index=page_index,
        voice=voice_index,
        beat_unit=_dsb_stream_beat_unit(layout.header.time_sig),
        metrics=metrics,
        bz_legacy_slots=len(system.voices) == 1,
    )
    lower_aligned_visible_dsb_targets(
        voice.events,
        voice.constructs,
        laid_out,
        tail_barlines,
    )
    layout.hidden_events.extend(hidden_events)
    _collect_constructs(
        layout,
        voice.constructs,
        voice.events,
        laid_out,
        hidden_events,
    )
    layout.events.extend(tail_barlines)
    reconcile_hidden_rest_slots(layout.events, laid_out, tail_barlines)
    if len(system.voices) == 1:
        max_voice_y = max(max_voice_y, voice_y)
    if len(system.voices) == 1:
        tail_lyrics = (
            lyrics_by_music_line.get(previous_source_line, ())
            if previous_source_line is not None
            else ()
        )
        system_tail_height = _system_height(
            metrics,
            len(tail_lyrics),
            has_annotation=_lyrics_have_annotations(tail_lyrics),
            has_extension=_lyrics_have_extensions(tail_lyrics),
            has_repeat_ending=(
                _source_group_needs_repeat_clearance(
                    source_groups[-1],
                    voice.constructs,
                )
                if source_groups
                else False
            ),
            single_voice=True,
            include_multi_verse_gap=False,
        ) + (
            _system_incoming_dsb_clearance(next_system)
        ) + _system_outgoing_block_clearance(system) + _system_outgoing_dsb_clearance(
            system
        )
    return max_voice_y, system_tail_height
