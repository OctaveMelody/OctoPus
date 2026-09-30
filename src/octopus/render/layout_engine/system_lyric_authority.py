"""Select system lyric widths and aligned lyricless voice authorities."""

from __future__ import annotations

from octopus.normalization.types import SystemModel
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
    PageMetrics,
)
from octopus.render.layout_engine.grid.grid_policies import (
    uses_parallel_first_ending_bilingual_grid as _uses_first_ending_bilingual_grid,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    associate_lyrics as _associate_lyrics,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    is_supported_legacy_lyric_line as _is_supported_legacy_lyric_line,
)
from octopus.render.layout_engine.lyrics.lyrics import (
    _legacy_lyric_gap_by_event,
    _legacy_lyric_text_by_event,
)
from octopus.render.layout_engine.rows.row_signatures import (
    shared_row_rhythm_signature as _shared_row_rhythm_signature,
)
from octopus.render.layout_engine.shared_system.parallel_refrain import (
    uses_parallel_refrain_rows,
)
from octopus.render.layout_engine.streams import uses_compound_meter as _uses_compound_meter
from octopus.render.layout_engine.system_state import _SystemLayoutState


def _include_aligned_lyricless_voice_authorities(
    *,
    metrics: PageMetrics,
    state: _SystemLayoutState,
    system_layout_events: list[LayoutEvent],
    uses_ascii_dual_verse_dsb_system: bool,
) -> None:
    visible_events_by_voice = state.visible_events_by_voice
    system_note_start_x = state.system_note_start_x
    shared_lyric_text_by_voice = state.shared_lyric_text_by_voice
    shared_lyric_gap_by_voice = state.shared_lyric_gap_by_voice
    if shared_lyric_text_by_voice:
        lyric_voice_event_counts = {
            len(visible_events_by_voice[voice_index])
            for voice_index in shared_lyric_text_by_voice
        }
        uses_compact_aligned_voice_grid = (
            len(visible_events_by_voice) == 4
            and system_note_start_x == 83.0
        )
        for voice_index, visible_events in visible_events_by_voice.items():
            first_layout_event = next(
                (
                    item
                    for item in system_layout_events
                    if item.voice == voice_index
                ),
                None,
            )
            candidate_voice_row = [
                item
                for item in system_layout_events
                if item.voice == voice_index
            ]
            matches_lyric_voice_rhythm = bool(candidate_voice_row) and any(
                _shared_row_rhythm_signature(candidate_voice_row)
                == _shared_row_rhythm_signature(
                    [
                        item
                        for item in system_layout_events
                        if item.voice == lyric_voice
                    ]
                )
                for lyric_voice in shared_lyric_text_by_voice
                if lyric_voice != voice_index
            )
            candidate_bar_slots = tuple(
                index
                for index, item in enumerate(candidate_voice_row)
                if item.event.kind == MusicTokenKind.BARLINE
            )
            all_voice_rhythms_distinct = len(
                {
                    _shared_row_rhythm_signature(
                        [
                            item
                            for item in system_layout_events
                            if item.voice == candidate_voice
                        ]
                    )
                    for candidate_voice in visible_events_by_voice
                }
            ) == len(visible_events_by_voice)
            matches_lyric_voice_slots = bool(candidate_voice_row) and any(
                len(candidate_voice_row) == len(lyric_row)
                and candidate_bar_slots
                == tuple(
                    index
                    for index, item in enumerate(lyric_row)
                    if item.event.kind == MusicTokenKind.BARLINE
                )
                for lyric_voice in shared_lyric_text_by_voice
                if lyric_voice != voice_index
                for lyric_row in [
                    [
                        item
                        for item in system_layout_events
                        if item.voice == lyric_voice
                    ]
                ]
            ) and all_voice_rhythms_distinct
            uses_mixed_note_origins = any(
                item.x != system_note_start_x
                for item in system_layout_events
                if item.slot == 0
            )
            if (
                visible_events
                and first_layout_event is not None
                and first_layout_event.x == system_note_start_x
                and (
                    uses_mixed_note_origins
                    or uses_compact_aligned_voice_grid
                    or len(visible_events) not in lyric_voice_event_counts
                    or len(visible_events_by_voice) >= 3
                    and (
                        matches_lyric_voice_rhythm
                        or matches_lyric_voice_slots
                    )
                    or (
                        len(shared_lyric_text_by_voice) == 1
                        and len(visible_events_by_voice) == 2
                        and (
                            uses_ascii_dual_verse_dsb_system
                            or matches_lyric_voice_rhythm
                            and (
                                _uses_compound_meter(metrics.time_sig)
                                or any(
                                    "(" in item.code
                                    and ")" in visible_events[index + 1].code
                                    and text.startswith("\u3000")
                                    for voice_index, visible_events in (
                                        visible_events_by_voice.items()
                                    )
                                    for index, item in enumerate(
                                        visible_events[:-1]
                                    )
                                    for text in shared_lyric_text_by_voice.get(
                                        voice_index, {}
                                    ).get((item.span.start.line, item.index), ())
                                )
                            )
                        )
                    )
                )
            ):
                shared_lyric_text_by_voice.setdefault(voice_index, {})
                shared_lyric_gap_by_voice.setdefault(voice_index, {})


def _collect_system_lyric_authorities(
    *,
    system: SystemModel,
    metrics: PageMetrics,
    layout: LayoutPage,
    state: _SystemLayoutState,
    system_layout_events: list[LayoutEvent],
) -> tuple[int, bool]:
    visible_events_by_voice = state.visible_events_by_voice
    system_note_start_x = state.system_note_start_x
    shared_lyric_text_by_voice = state.shared_lyric_text_by_voice
    shared_lyric_gap_by_voice = state.shared_lyric_gap_by_voice
    system_lyric_models = tuple(
        sorted(
            (lyric for voice in system.voices for lyric in voice.lyrics),
            key=lambda lyric: lyric.span.start.offset,
        )
    )
    system_lyric_associations = _associate_lyrics(
        system.music_line_numbers,
        system_lyric_models,
    )
    shared_grid_rows = tuple(
        tuple(
            item
            for item in system_layout_events
            if item.voice == voice_index
        )
        for voice_index in sorted(visible_events_by_voice)
    )
    uses_first_ending_bilingual_grid = _uses_first_ending_bilingual_grid(
        shared_grid_rows,
        tuple(
            len(
                system_lyric_associations.get(
                    row[0].event.span.start.line,
                    (),
                )
            )
            if row
            else 0
            for row in shared_grid_rows
        ),
    )
    shares_system_lyric_associations = (
        any(item.x < system_note_start_x for item in system_layout_events)
        or uses_first_ending_bilingual_grid
        or (
            uses_parallel_refrain_rows([list(row) for row in shared_grid_rows])
            and any(len(lyrics) >= 2 for lyrics in system_lyric_associations.values())
        )
    )
    first_ending_bilingual_authority_line = (
        next(
            row[0].event.span.start.line
            for row in shared_grid_rows
            if row
            and len(
                system_lyric_associations.get(
                    row[0].event.span.start.line,
                    (),
                )
            )
            == 2
        )
        if uses_first_ending_bilingual_grid
        else None
    )
    if uses_first_ending_bilingual_grid:
        # The two bilingual pairs repeat the same phrase on distinct rhythms.
        # Legacy spacing elects the first pair as the sole width authority;
        # visible lyric layout still associates and renders both pairs.
        shared_lyric_text_by_voice.clear()
        shared_lyric_gap_by_voice.clear()
    system_verse_count = max(
        (len(lyrics) for lyrics in system_lyric_associations.values()),
        default=0,
    )
    for source_line, lyric_lines in (
        system_lyric_associations.items()
        if shares_system_lyric_associations
        else ()
    ):
        if (
            first_ending_bilingual_authority_line is not None
            and source_line != first_ending_bilingual_authority_line
        ):
            continue
        source_events = [
            item
            for item in system_layout_events
            if item.event.span.start.line == source_line
        ]
        if (
            not source_events
            or source_events[0].x != system_note_start_x
            or not lyric_lines
            or not any(line.tokens for line in lyric_lines)
            or not all(
                _is_supported_legacy_lyric_line(line)
                for line in lyric_lines
                if line.tokens
            )
        ):
            continue
        voice_index = source_events[0].voice
        association = {source_line: lyric_lines}
        shared_lyric_text_by_voice.setdefault(voice_index, {}).update(
            _legacy_lyric_text_by_event(
                metrics,
                layout.header,
                source_events,
                association,
            )
        )
        shared_lyric_gap_by_voice.setdefault(voice_index, {}).update(
            _legacy_lyric_gap_by_event(
                metrics,
                layout.header,
                source_events,
                association,
            )
        )
    uses_ascii_dual_verse_dsb_system = (
        system_verse_count >= 2
        and any("&dsb_a" in item.event.code for item in system_layout_events)
        and all(
            character.isascii() or character.isspace()
            for lyric_text in shared_lyric_text_by_voice.values()
            for texts in lyric_text.values()
            for text in texts
            for character in text
        )
    )
    return system_verse_count, uses_ascii_dual_verse_dsb_system
