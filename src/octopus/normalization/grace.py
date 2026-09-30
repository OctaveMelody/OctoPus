"""Grace-marker width reservations attached to host notes.

Unquoted grace markers (``[n]``) are invisible to row layout — they render
relative to their host note — but they reserve stretched space in front of
the host.  This module folds that reservation into the host event during
normalization so every downstream consumer (shared grid, legacy rows) sees
it on a visible, timed event.
"""

from __future__ import annotations

from dataclasses import replace

from octopus.normalization.types import MusicEvent
from octopus.parser.ast import MusicTokenKind

# Event kinds that occupy rhythmic time (a grace marker attaches to the
# nearest preceding event of one of these kinds).
TIMED_EVENT_KINDS = frozenset(
    {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.EXTENSION,
    }
)


def grace_marker_width(raw: str) -> int:
    """Stretched-space width reserved by one unquoted grace marker.

    Oracle-verified 2026-08-23 (probes P1-P9 on Looking-Back's page config):
    each digit of the marker reserves seven stretched units in front of the
    host note.  Quoted markers (``"[n]"``) are annotations, not grace groups,
    and never reach this helper.
    """
    return 7 * sum(ch in "1234567" for ch in raw)


def attach_grace_reservations(events: list[MusicEvent]) -> list[MusicEvent]:
    """Fold each grace group's width reservation into its host note.

    A marker attaches to the nearest preceding timed event in the same line;
    several markers on one host accumulate.  Quoted labels wrapped in a grace
    group (``["[18]"]``, Watching-Sunset) carry no grace notes and reserve no
    width — the reference renders them without any layout effect.
    """
    reservations: dict[int, int] = {}
    last_timed_index: int | None = None
    for event in events:
        if (
            event.kind == MusicTokenKind.GRACE_GROUP
            and '"' not in event.raw
            and last_timed_index is not None
        ):
            reservations[last_timed_index] = (
                reservations.get(last_timed_index, 0) + grace_marker_width(event.raw)
            )
        elif event.kind in TIMED_EVENT_KINDS:
            last_timed_index = event.index
    if not reservations:
        return events
    return [
        replace(event, grace_reservation=reservations[event.index])
        if event.index in reservations
        else event
        for event in events
    ]
