"""Place source voice rows and allocate generated tail barlines."""

from __future__ import annotations

from octopus.normalization.types import ScoreModel, SystemModel
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
    PageMetrics,
    RowLayoutInput,
    _SyntheticIndexAllocator,
)
from octopus.render.core.layout_widths import (
    BARLINE_EXTRA_GAP,
    MEASURE_GAP,
    REST_WIDTH,
    _is_zero_space_barline,
    compute_event_width,
)
from octopus.render.layout_engine.hidden.hidden_stream_layout import (
    _tail_layout_event,
)
from octopus.render.layout_engine.hidden.hidden_streams import (
    block_tail_identity as _block_tail_identity,
)
from octopus.render.layout_engine.hidden.hidden_streams import (
    empty_alignment_placeholder_event as _empty_alignment_placeholder_event,
)
from octopus.render.layout_engine.hidden.hidden_streams import (
    generated_tail_barline as _generated_tail_barline,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    associate_lyrics as _associate_lyrics,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    source_line_groups as _source_line_groups,
)
from octopus.render.layout_engine.rows.row_sizing import (
    split_oversized_source_line as _split_oversized_source_line,
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
from octopus.render.layout_engine.spacing.system_spacing import (
    source_line_has_hidden_bz as _source_line_has_hidden_bz,
)
from octopus.render.layout_engine.spacing.system_spacing import system_height as _system_height
from octopus.render.layout_engine.system_state import (
    DSB_GENERATED_TAIL_PLACEHOLDER_INDEX_START,
    REPEAT_ENDING_CLEARANCE,
    _SystemLayoutState,
)
from octopus.render.layout_engine.voice_finalization import _finalize_layout_voice


def _layout_system_voices(
    *,
    model: ScoreModel,
    page_index: int,
    system: SystemModel,
    metrics: PageMetrics,
    layout: LayoutPage,
    page_uses_legacy_intrinsic_grid: bool,
    state: _SystemLayoutState,
) -> None:
    current_y = state.current_y
    max_voice_y = state.max_voice_y
    voice_spacing = state.voice_spacing
    system_rows = state.system_rows
    system_line_start = state.system_line_start
    system_tail_height = state.system_tail_height
    right = state.right
    system_note_start_x = state.system_note_start_x
    available_width = state.available_width
    visible_events_by_voice = state.visible_events_by_voice
    source_line_offsets = state.source_line_offsets
    source_line_y_offsets = state.source_line_y_offsets
    for voice_index, voice in enumerate(system.voices):
        voice_note_start_x = (
            metrics.note_start_x if voice.voice == 0 else system_note_start_x
        )
        voice_y = current_y + voice_index * voice_spacing
        row_y = voice_y
        x = voice_note_start_x
        prev_was_barline = False
        row = 0
        slot = 0
        voice_event_start = len(layout.events)
        visible_events = visible_events_by_voice[voice_index]
        tail_identity = _block_tail_identity(
            visible_events,
            voice.events,
            voice.constructs,
        )
        source_groups = _source_line_groups(visible_events)
        lyrics_by_music_line = _associate_lyrics(voice.music_line_numbers, voice.lyrics)
        if len(system.voices) == 1 and source_groups and _source_group_needs_repeat_clearance(
            source_groups[0],
            voice.constructs,
        ):
            voice_y += REPEAT_ENDING_CLEARANCE
            row_y = voice_y
        previous_source_line: int | None = None
        tail_barlines: list[LayoutEvent] = []
        dsb_generated_tail_placeholder_indices = _SyntheticIndexAllocator(
            DSB_GENERATED_TAIL_PLACEHOLDER_INDEX_START
        )
        for source_group_index, source_group in enumerate(source_groups):
            source_line = source_group[0].span.start.line
            hidden_bz_offset = (
                40.0
                if len(system.voices) == 1
                and _source_line_has_hidden_bz(voice.constructs, source_line)
                else 0.0
            )
            row_input = RowLayoutInput(
                source_group=tuple(source_group),
                voice=voice,
                lyrics=tuple(lyrics_by_music_line.get(source_line, ())),
                meter=metrics.time_sig,
                hidden_reserve_width=hidden_bz_offset,
                available_width=available_width,
            )
            chunks = _split_oversized_source_line(
                list(row_input.source_group),
                row_input.available_width,
            )
            for chunk_index, chunk in enumerate(chunks):
                if len(system.voices) > 1:
                    row = source_line_offsets[source_line] + chunk_index
                    x = voice_note_start_x
                    prev_was_barline = False
                    slot = 0
                elif source_group_index > 0 or chunk_index > 0:
                    row += 1
                    system_rows = max(system_rows, row + 1)
                    x = metrics.note_start_x
                    prev_was_barline = False
                    slot = 0
                    if len(system.voices) == 1:
                        if chunk_index > 0:
                            row_y += voice_spacing
                        else:
                            previous_lyrics = (
                                lyrics_by_music_line.get(previous_source_line, ())
                                if previous_source_line is not None
                                else ()
                            )
                            row_y += _system_height(
                                metrics,
                                len(previous_lyrics),
                                has_annotation=_lyrics_have_annotations(previous_lyrics),
                                has_extension=_lyrics_have_extensions(previous_lyrics),
                                has_repeat_ending=(
                                    _source_group_needs_repeat_clearance(
                                        source_groups[source_group_index - 1],
                                        voice.constructs,
                                    )
                                    if chunk_index == 0 and source_group_index > 0
                                    else False
                                ),
                                incoming_repeat_ending=(
                                    chunk_index == 0
                                    and _source_group_needs_repeat_clearance(
                                        source_group,
                                        voice.constructs,
                                    )
                                ),
                                single_voice=True,
                            )
                if chunk_index == 0:
                    row_y += row_input.hidden_reserve_width
                for event in chunk:
                    event_width = compute_event_width(event)
                    leading_gap = 0.0
                    if (
                        event.kind == MusicTokenKind.BARLINE
                        and not _is_zero_space_barline(event)
                    ):
                        leading_gap = (
                            MEASURE_GAP if prev_was_barline else BARLINE_EXTRA_GAP
                        )
                    x += leading_gap
                    event_y = (
                        row_y
                        if len(system.voices) == 1
                        else current_y
                        + source_line_y_offsets[source_line]
                        + chunk_index * voice_spacing
                    )
                    event_line = (
                        system_line_start + row
                        if len(system.voices) == 1
                        else system_line_start + row
                    )
                    prev_was_barline = event.kind == MusicTokenKind.BARLINE
                    if tail_identity.advances_slot(event):
                        slot += 1
                    layout.events.append(
                        LayoutEvent(
                            event=event,
                            x=x,
                            y=event_y,
                            page_index=page_index,
                            voice=voice_index,
                            line=event_line,
                            slot=slot,
                            block=tail_identity.block_for_event(event),
                        )
                    )
                    x += event_width
                    if (
                        event.kind == MusicTokenKind.BARLINE
                        and not _is_zero_space_barline(event)
                    ):
                        x += MEASURE_GAP
                    max_voice_y = max(max_voice_y, event_y)
                if chunk and chunk[-1].kind != MusicTokenKind.BARLINE:
                    dsb_generated_tail = tail_identity.is_dsb_generated_tail_reference(
                        chunk[-1]
                    )
                    tail_slot = slot + 1
                    tail_line = system_line_start + row
                    if dsb_generated_tail:
                        tail_barlines.append(
                            _tail_layout_event(
                                event=_empty_alignment_placeholder_event(
                                    chunk[-1],
                                    dsb_generated_tail_placeholder_indices.take(),
                                    "{dsb-placeholder}",
                                ),
                                x=right - REST_WIDTH,
                                y=event_y,
                                page_index=page_index,
                                voice=voice_index,
                                line=tail_line,
                                slot=tail_slot,
                                block="dsb-placeholder",
                            )
                        )
                    tail_barlines.append(
                        _tail_layout_event(
                            event=_generated_tail_barline(chunk[-1]),
                            x=right,
                            y=event_y,
                            page_index=page_index,
                            voice=voice_index,
                            line=tail_line,
                            slot=tail_slot,
                            block="dsb-tail" if dsb_generated_tail else None,
                        )
                    )
            previous_source_line = source_group[0].span.start.line
        max_voice_y, system_tail_height = _finalize_layout_voice(
            model=model,
            page_index=page_index,
            system=system,
            voice=voice,
            voice_index=voice_index,
            voice_y=voice_y,
            voice_note_start_x=voice_note_start_x,
            metrics=metrics,
            layout=layout,
            state=state,
            voice_event_start=voice_event_start,
            tail_barlines=tail_barlines,
            source_groups=source_groups,
            lyrics_by_music_line=lyrics_by_music_line,
            previous_source_line=previous_source_line,
            page_uses_legacy_intrinsic_grid=page_uses_legacy_intrinsic_grid,
            max_voice_y=max_voice_y,
            system_tail_height=system_tail_height,
        )
    state.max_voice_y = max_voice_y
    state.system_rows = system_rows
    state.system_tail_height = system_tail_height
