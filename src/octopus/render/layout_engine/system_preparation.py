"""Prepare source-row positions, visible streams, and system spacing."""

from __future__ import annotations

from octopus.normalization.types import ScoreModel, SystemModel
from octopus.render.core.layout_types import (
    LayoutPage,
    PageMetrics,
)
from octopus.render.layout_engine.event_selection import (
    visible_events_for_layout as _visible_events_for_layout,
)
from octopus.render.layout_engine.hidden.bz_layout import bz_target_source_lines
from octopus.render.layout_engine.lyrics.lyric_selection import (
    source_line_groups as _source_line_groups,
)
from octopus.render.layout_engine.profiles import SystemSpacingProfile
from octopus.render.layout_engine.rows.row_sizing import (
    split_oversized_source_line as _split_oversized_source_line,
)
from octopus.render.layout_engine.spacing.system_spacing import system_height as _system_height
from octopus.render.layout_engine.spacing.system_spacing import (
    system_outgoing_block_clearance as _system_outgoing_block_clearance,
)
from octopus.render.layout_engine.spacing.system_spacing import (
    voice_name_column_width as _voice_name_column_width,
)
from octopus.render.layout_engine.spacing.vertical_spacing import (
    _multi_voice_dsb_terminal_gap_count,
    _system_incoming_dsb_clearance,
    _system_outgoing_dsb_clearance,
)
from octopus.render.layout_engine.spacing.vertical_spacing import (
    multi_voice_leading_clearance as _multi_voice_leading_clearance,
)
from octopus.render.layout_engine.spacing.vertical_spacing import (
    multi_voice_row_gap as _multi_voice_row_gap,
)
from octopus.render.layout_engine.spacing.vertical_spacing import (
    multi_voice_tail_height as _multi_voice_tail_height,
)
from octopus.render.layout_engine.spacing.vertical_spacing import (
    multi_voice_terminal_mark_clearance as _multi_voice_terminal_mark_clearance,
)
from octopus.render.layout_engine.system_state import REPEAT_ENDING_CLEARANCE, _SystemLayoutState


def _prepare_system_layout(
    *,
    model: ScoreModel,
    page_index: int,
    system_index: int,
    system: SystemModel,
    metrics: PageMetrics,
    layout: LayoutPage,
    current_y: float,
    visual_line: int,
) -> _SystemLayoutState:
    page_model = model.pages[page_index]
    _system_index = system_index
    previous_system = (
        page_model.systems[_system_index - 2]
        if _system_index > 1
        else None
    )
    current_y += _multi_voice_terminal_mark_clearance(
        system,
        previous_system=previous_system,
    )
    system_event_start = len(layout.events)
    max_voice_y = current_y
    voice_spacing = max(metrics.height_shengbu + 47, 57)
    system_lyric_line_count = max(
        (len(voice.lyrics) for voice in system.voices),
        default=0,
    )
    system_rows = 1
    system_line_start = visual_line
    shared_lyric_text_by_voice: dict[
        int, dict[tuple[int, int], tuple[str, ...]]
    ] = {}
    shared_lyric_gap_by_voice: dict[int, dict[tuple[int, int], int]] = {}
    shared_grace_raw_by_voice: dict[int, dict[int, str]] = {}
    next_system = (
        page_model.systems[_system_index]
        if _system_index < len(page_model.systems)
        else None
    )
    system_tail_height = (
        _multi_voice_tail_height(
            system,
            metrics,
            next_system,
        )
        if len(system.voices) > 1
        else _system_height(
            metrics,
            system_lyric_line_count,
            single_voice=True,
            include_multi_verse_gap=False,
        )
        + (
            _system_incoming_dsb_clearance(next_system)
        )
        + _system_outgoing_block_clearance(system)
        + _system_outgoing_dsb_clearance(system)
    )
    if page_index == 0 and _system_index == 1:
        # First-page DSB headroom is local; preserve the system's outgoing flow.
        system_tail_height -= (
            _multi_voice_leading_clearance(system)
            - REPEAT_ENDING_CLEARANCE
            * _multi_voice_dsb_terminal_gap_count(system)
        )
    right = float(metrics.width - metrics.margin_right + 3)
    system_note_start_x = metrics.note_start_x + (
        20 + _voice_name_column_width(system) if len(system.voices) > 1 else 0
    )
    available_width = right - system_note_start_x
    visible_events_by_voice = {
        voice_index: _visible_events_for_layout(
            voice.events,
            voice.constructs,
            bz_reserve_slots=len(system.voices) == 1,
        )
        for voice_index, voice in enumerate(system.voices)
    }
    source_line_offsets: dict[int, int] = {}
    source_line_y_offsets: dict[int, float] = {}
    if len(system.voices) > 1:
        system_source_lines = tuple(sorted(system.music_line_numbers))
        source_line_chunk_counts: dict[int, int] = {}
        for visible_events in visible_events_by_voice.values():
            for source_group in _source_line_groups(visible_events):
                line_number = source_group[0].span.start.line
                source_line_chunk_counts[line_number] = max(
                    source_line_chunk_counts.get(line_number, 0),
                    len(_split_oversized_source_line(source_group, available_width)),
                )
        spacing_profile = SystemSpacingProfile(
            source_lines=system_source_lines,
            chunk_counts=tuple(
                max(source_line_chunk_counts.get(line_number, 1), 1)
                for line_number in system_source_lines
            ),
            line_gaps=tuple(
                _multi_voice_row_gap(
                    system,
                    metrics,
                    line_number,
                    system_source_lines[line_index + 1],
                )
                for line_index, line_number in enumerate(system_source_lines[:-1])
            ),
            chunk_spacing=float(voice_spacing),
        )
        source_line_offsets = dict(
            zip(
                spacing_profile.source_lines,
                spacing_profile.visual_row_offsets,
                strict=True,
            )
        )
        source_line_y_offsets = dict(
            zip(
                spacing_profile.source_lines,
                spacing_profile.source_line_y_offsets,
                strict=True,
            )
        )
        bz_lines = frozenset(
            line
            for voice_index, voice in enumerate(system.voices)
            for line in bz_target_source_lines(
                visible_events_by_voice[voice_index], voice.events, voice.constructs,
            )
        )
        bz_clearance = 0.0
        for line in system_source_lines:
            if line in bz_lines:
                bz_clearance += 40.0
            source_line_y_offsets[line] += bz_clearance
        system_rows = max(system_rows, spacing_profile.physical_row_count)
    return _SystemLayoutState(
        current_y=current_y,
        max_voice_y=max_voice_y,
        voice_spacing=voice_spacing,
        system_rows=system_rows,
        system_line_start=system_line_start,
        system_event_start=system_event_start,
        system_tail_height=system_tail_height,
        right=right,
        system_note_start_x=system_note_start_x,
        available_width=available_width,
        next_system=next_system,
        visible_events_by_voice=visible_events_by_voice,
        source_line_offsets=source_line_offsets,
        source_line_y_offsets=source_line_y_offsets,
        shared_lyric_text_by_voice=shared_lyric_text_by_voice,
        shared_lyric_gap_by_voice=shared_lyric_gap_by_voice,
        shared_grace_raw_by_voice=shared_grace_raw_by_voice,
    )
