"""Event visibility and placeholder classification for layout."""

from __future__ import annotations

from octopus.normalization.types import MusicEvent

from ...parser.ast import MusicTokenKind


def is_visible_event(event: MusicEvent) -> bool:
    return event.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.BARLINE,
        MusicTokenKind.EXTENSION,
    }


def is_bz_placeholder_event(event: MusicEvent) -> bool:
    return event.raw == "{bz-placeholder}"


def is_dsb_placeholder_event(event: MusicEvent) -> bool:
    return event.raw == "{dsb-placeholder}"


def is_synthetic_hidden_rest_placeholder(event: MusicEvent) -> bool:
    return (
        event.kind == MusicTokenKind.HIDDEN_REST
        and event.raw == "8"
        and event.index < 0
    )
