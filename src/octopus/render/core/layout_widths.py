"""Shared event-width calculations used by layout and row justification."""

from __future__ import annotations

from octopus.normalization.types import MusicEvent
from octopus.parser.ast import MusicTokenKind

from .layout_types import LayoutEvent

NOTE_WIDTH = 30.0
REST_WIDTH = 20.0
BARLINE_WIDTH = 20.0
EXTENSION_WIDTH = 30.0
BARLINE_EXTRA_GAP = 8.0
MEASURE_GAP = 8.0
INLINE_TIME_SIGNATURE_WIDTH = 24.0


def _is_zero_space_barline(event: MusicEvent) -> bool:
    return event.kind == MusicTokenKind.BARLINE and event.code.startswith("|n")


def compute_event_width(event: MusicEvent) -> float:
    if event.kind == MusicTokenKind.BARLINE:
        if _is_zero_space_barline(event):
            return INLINE_TIME_SIGNATURE_WIDTH if "'p:" in event.code else 0.0
        inline_meter_width = INLINE_TIME_SIGNATURE_WIDTH if "'p:" in event.code else 0.0
        return BARLINE_WIDTH + inline_meter_width
    if event.kind == MusicTokenKind.EXTENSION:
        width = EXTENSION_WIDTH
        if any(mark in event.decorations for mark in ("zkh", "ykh")):
            width += 12.0
        return width
    if event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}:
        width = REST_WIDTH
        if any(mark in event.decorations for mark in ("zkh", "ykh")):
            width += 12.0
        return width
    if event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}:
        dur_widths: dict[int, float] = {
            0: NOTE_WIDTH,
            1: 20.0,
            2: NOTE_WIDTH,
            3: 20.0,
        }
        base = dur_widths.get(event.duration_slashes, 20.0)
        if event.duration_dots > 0:
            base *= 1.5
        if any(mark in event.decorations for mark in ("zkh", "ykh")):
            base += 12.0
        return base
    return NOTE_WIDTH


def event_duration_weight(event: LayoutEvent) -> float:
    """Return a proportional weight for spacing based on event duration."""
    music_event = event.event
    if music_event.kind == MusicTokenKind.BARLINE:
        if _is_zero_space_barline(music_event):
            return INLINE_TIME_SIGNATURE_WIDTH if "'p:" in music_event.code else 0.0
        return BARLINE_WIDTH
    if music_event.kind == MusicTokenKind.EXTENSION:
        return EXTENSION_WIDTH
    if music_event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}:
        return REST_WIDTH
    if music_event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}:
        base = NOTE_WIDTH
        slashes = music_event.duration_slashes
        if slashes == 1:
            base = 20.0
        elif slashes >= 2:
            base = 15.0
        if music_event.duration_dots > 0:
            base *= 1.5
        return base
    return NOTE_WIDTH
