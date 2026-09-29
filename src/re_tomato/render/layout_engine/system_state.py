"""Shared mutable state and existing reserves for system layout passes."""

from __future__ import annotations

from dataclasses import dataclass

from re_tomato.normalization.types import MusicEvent, SystemModel
from re_tomato.render.layout_engine.spacing.system_spacing import (
    DSB_INCOMING_CLEARANCE as _SYSTEM_DSB_INCOMING_CLEARANCE,
)

REPEAT_ENDING_CLEARANCE = 12.0


TERMINAL_MARK_CLEARANCE = 12.0


DSB_INCOMING_CLEARANCE = _SYSTEM_DSB_INCOMING_CLEARANCE


DSB_BRACKET_OVERLAP = 4.0


BZ_PLACEHOLDER_INDEX_START = -100000


DSB_PLACEHOLDER_INDEX_START = -150000


DSB_GENERATED_TAIL_PLACEHOLDER_INDEX_START = -300000


SHARED_DSB_PLACEHOLDER_RESERVE = 45.0


@dataclass
class _SystemLayoutState:
    current_y: float
    max_voice_y: float
    voice_spacing: float
    system_rows: int
    system_line_start: int
    system_event_start: int
    system_tail_height: float
    right: float
    system_note_start_x: float
    available_width: float
    next_system: SystemModel | None
    visible_events_by_voice: dict[int, list[MusicEvent]]
    source_line_offsets: dict[int, int]
    source_line_y_offsets: dict[int, float]
    shared_lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]]
    shared_lyric_gap_by_voice: dict[int, dict[tuple[int, int], int]]
    shared_grace_raw_by_voice: dict[int, dict[int, str]]
