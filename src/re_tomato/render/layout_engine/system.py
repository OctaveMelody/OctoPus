"""Coordinate voice layout, shared projection, braces, and lyrics for a system."""

from __future__ import annotations

from re_tomato.normalization.types import ScoreModel, SystemModel
from re_tomato.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
    PageMetrics,
)
from re_tomato.render.layout_engine.group_projection import (
    _justify_lyricless_aligned_row_runs,
    _justify_shared_intrinsic_voice_rows,
    _register_shared_projection_plan,
)
from re_tomato.render.layout_engine.legacy_cell_projection import (
    reproject_legacy_cell_rows,
)
from re_tomato.render.layout_engine.lyric_rows import (
    _last_visible_row_lyric_events,
    _layout_empty_standalone_lyric_spacers,
)
from re_tomato.render.layout_engine.lyrics.lyric_selection import (
    associate_lyrics as _associate_lyrics,
)
from re_tomato.render.layout_engine.lyrics.lyrics import (
    _layout_lyrics,
    _legacy_lyric_text_by_event,
)
from re_tomato.render.layout_engine.parallel_sustain import align_parallel_sustain_sentinel_rows
from re_tomato.render.layout_engine.shared_system.hidden_projection import (
    reproject_hidden_dsb_events,
)
from re_tomato.render.layout_engine.shared_system.parallel_refrain import (
    align_parallel_refrain_rows,
)
from re_tomato.render.layout_engine.shared_system.projection import SharedProjectionPlan
from re_tomato.render.layout_engine.streams import uses_compound_meter as _uses_compound_meter
from re_tomato.render.layout_engine.system_lyric_authority import (
    _collect_system_lyric_authorities,
    _include_aligned_lyricless_voice_authorities,
)
from re_tomato.render.layout_engine.system_preparation import _prepare_system_layout
from re_tomato.render.layout_engine.voice import _layout_system_voices
from re_tomato.render.layout_engine.voice_braces import (
    collect_voice_braces as _collect_voice_braces,
)


def _layout_system(
    *,
    model: ScoreModel,
    page_index: int,
    system_index: int,
    system: SystemModel,
    metrics: PageMetrics,
    layout: LayoutPage,
    page_uses_legacy_intrinsic_grid: bool,
    current_y: float,
    visual_line: int,
    previous_visible_lyric_events: list[LayoutEvent],
) -> tuple[float, int, list[LayoutEvent]]:
    system_event_start = len(layout.events)
    hidden_event_start = len(layout.hidden_events)
    lyric_start = len(layout.lyrics)
    state = _prepare_system_layout(
        model=model,
        page_index=page_index,
        system_index=system_index,
        system=system,
        metrics=metrics,
        layout=layout,
        current_y=current_y,
        visual_line=visual_line,
    )
    if not any(state.visible_events_by_voice.values()):
        _layout_empty_standalone_lyric_spacers(layout, system, previous_visible_lyric_events)
        _stamp_system_metadata(
            layout,
            system_event_start,
            hidden_event_start,
            lyric_start,
            system_index,
        )
        return (
            state.current_y + state.system_tail_height,
            visual_line,
            previous_visible_lyric_events,
        )
    _layout_system_voices(
        model=model,
        page_index=page_index,
        system=system,
        metrics=metrics,
        layout=layout,
        page_uses_legacy_intrinsic_grid=page_uses_legacy_intrinsic_grid,
        state=state,
    )
    current_y = state.current_y
    max_voice_y = state.max_voice_y
    system_rows = state.system_rows
    system_line_start = state.system_line_start
    system_event_start = state.system_event_start
    system_tail_height = state.system_tail_height
    system_note_start_x = state.system_note_start_x
    shared_lyric_text_by_voice = state.shared_lyric_text_by_voice
    shared_lyric_gap_by_voice = state.shared_lyric_gap_by_voice
    shared_grace_raw_by_voice = state.shared_grace_raw_by_voice
    system_layout_events = layout.events[system_event_start:]
    system_source_lines = frozenset(system.music_line_numbers)
    system_hidden_events = [
        item
        for item in layout.hidden_events
        if item.event.span.start.line in system_source_lines
    ]
    # The shared-grid width must see the same lyric association the reference
    # renders: every C line attaches to the nearest preceding music line of
    # the whole system, stacking as verses on that row (oracle-verified
    # 2026-07-25 on AuldLangSyne-Choir p1 grids 0-1 and Edelweiss-Choir p3:
    # C1+C5 render under one Q row and drive its overflow, while the per-voice
    # model assignment Cn->Qn puts them on the wrong grid rows).
    grid_lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]] = {}
    system_lyric_models = tuple(
        sorted(
            (lyric for voice in system.voices for lyric in voice.lyrics),
            key=lambda lyric: lyric.span.start.offset,
        )
    )
    if system_lyric_models:
        system_lyric_associations = _associate_lyrics(
            system.music_line_numbers,
            system_lyric_models,
        )
        line_owner_voice = {
            line: index
            for index, voice in enumerate(system.voices)
            for line in voice.music_line_numbers
        }
        for source_line, lyric_lines in system_lyric_associations.items():
            owner = line_owner_voice.get(source_line)
            if owner is None:
                continue
            text_by_event = _legacy_lyric_text_by_event(
                metrics,
                layout.header,
                [item for item in system_layout_events if item.voice == owner],
                {source_line: lyric_lines},
                append_floating_punctuation=False,
            )
            if text_by_event:
                grid_lyric_text_by_voice.setdefault(owner, {}).update(text_by_event)
    system_verse_count, uses_ascii_dual_verse_dsb_system = (
        _collect_system_lyric_authorities(
            system=system,
            metrics=metrics,
            layout=layout,
            state=state,
            system_layout_events=system_layout_events,
        )
    )
    _include_aligned_lyricless_voice_authorities(
        metrics=metrics,
        state=state,
        system_layout_events=system_layout_events,
        uses_ascii_dual_verse_dsb_system=uses_ascii_dual_verse_dsb_system,
    )
    shared_projection_plans: dict[tuple[int, int], SharedProjectionPlan] = {}
    _register_shared_projection_plan(
        shared_projection_plans,
        _justify_shared_intrinsic_voice_rows(
            system_layout_events,
            metrics=metrics,
            left=system_note_start_x,
            lyric_text_by_voice=shared_lyric_text_by_voice,
            lyric_gap_by_voice=shared_lyric_gap_by_voice,
            grace_raw_by_voice=shared_grace_raw_by_voice,
            primary_system_verse_count=system_verse_count,
            system_row_count=system_rows,
            authoritative_groups=system.voice_groups,
            projection_plans=shared_projection_plans,
            grid_lyric_text_by_voice=grid_lyric_text_by_voice,
            hidden_events=system_hidden_events,
        ),
    )
    _justify_lyricless_aligned_row_runs(
        system_layout_events,
        metrics=metrics,
        left=system_note_start_x,
        lyric_voices=(
            frozenset(
                voice
                for voice, lyric_text in shared_lyric_text_by_voice.items()
                if any(text for texts in lyric_text.values() for text in texts)
            )
            if (
                _uses_compound_meter(metrics.time_sig)
                or uses_ascii_dual_verse_dsb_system
            )
            else frozenset()
        ),
        projection_plans=shared_projection_plans,
        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
    )
    align_parallel_sustain_sentinel_rows(system_layout_events)
    align_parallel_refrain_rows(system_layout_events)
    reproject_hidden_dsb_events(layout.hidden_events, shared_projection_plans)
    reproject_legacy_cell_rows(
        system_layout_events,
        left=system_note_start_x,
        right=state.right,
    )
    visual_system_rows = system_rows
    _collect_voice_braces(
        layout,
        system,
        layout.events[system_event_start:],
        system_note_start_x,
    )
    _layout_lyrics(
        layout,
        system,
        system_line_start,
        visual_system_rows,
    )
    _stamp_system_metadata(
        layout,
        system_event_start,
        hidden_event_start,
        lyric_start,
        system_index,
    )
    current_y = max_voice_y + system_tail_height
    previous_visible_lyric_events = _last_visible_row_lyric_events(
        layout,
        system_line_start,
        visual_system_rows,
    )
    visual_line += visual_system_rows
    return current_y, visual_line, previous_visible_lyric_events


def _stamp_system_metadata(
    layout: LayoutPage,
    event_start: int,
    hidden_event_start: int,
    lyric_start: int,
    system_index: int,
) -> None:
    for event in layout.events[event_start:]:
        event.system_index = system_index
    for event in layout.hidden_events[hidden_event_start:]:
        event.system_index = system_index
    for lyric in layout.lyrics[lyric_start:]:
        if lyric.source_spans:
            lyric.system_index = system_index
