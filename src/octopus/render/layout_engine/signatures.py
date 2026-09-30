"""Reusable semantic signatures for source-derived layout classifiers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent
from .grid.grids import measure_grid_from_durations
from .hidden.hidden_streams import event_duration_fraction


@dataclass(frozen=True, slots=True)
class NormalizedEventSignature:
    """Source-independent event facts used by structural classifiers."""

    kind: MusicTokenKind
    duration: Fraction
    duration_dots: int
    duration_slashes: int
    pitch: int | None
    accidental: str | None
    octave: int
    attached_to_previous: bool
    construct_roles: tuple[str, ...]


def measure_durations(row: Sequence[LayoutEvent]) -> tuple[Fraction, ...]:
    """Return exact accumulated durations for each completed measure."""

    durations: list[Fraction] = []
    elapsed = Fraction()
    for item in row:
        if item.event.kind == MusicTokenKind.BARLINE:
            durations.append(elapsed)
            elapsed = Fraction()
        else:
            elapsed += event_duration_fraction(item.event)
    return tuple(durations)


def terminal_signature(row: Sequence[LayoutEvent]) -> tuple[tuple[object, ...], ...]:
    """Return the exact event-shape signature after the final completed barline."""

    final_start = max(
        index
        for index, item in enumerate(row[:-1])
        if item.event.kind == MusicTokenKind.BARLINE
    ) + 1
    return tuple(
        (
            item.event.kind,
            event_duration_fraction(item.event),
            item.event.duration_dots,
            item.event.duration_slashes,
            item.event.code.count("("),
            item.event.code.count(")"),
        )
        for item in row[final_start:-1]
    )


def event_signature(item: LayoutEvent) -> tuple[object, ...]:
    """Return the legacy compatibility shape used by measured classifiers."""

    return (
        item.event.kind,
        event_duration_fraction(item.event),
        item.event.duration_dots,
        item.event.duration_slashes,
        item.event.code.count("("),
        item.event.code.count(")"),
    )


def grid_event_signature(item: LayoutEvent) -> tuple[object, ...]:
    """Return the established pitch-aware grid signature."""

    event = item.event
    return (
        event.kind,
        event_duration_fraction(event),
        event.duration_dots,
        event.duration_slashes,
        event.code.count("("),
        event.code.count(")"),
        event.pitch,
        event.accidental,
        event.octave,
        event.attached_to_previous,
    )


def normalized_grid_event_signature(item: LayoutEvent) -> NormalizedEventSignature:
    """Return normalized pitch-aware rhythm and construct topology."""

    event = item.event
    return NormalizedEventSignature(
        kind=event.kind,
        duration=event_duration_fraction(event),
        duration_dots=event.duration_dots,
        duration_slashes=event.duration_slashes,
        pitch=event.pitch,
        accidental=event.accidental,
        octave=event.octave,
        attached_to_previous=event.attached_to_previous,
        construct_roles=construct_role_signature(item),
    )


def _normalized_construct_role(role: str) -> str:
    for semantic_kind in ("tie", "slur", "modifier"):
        marker = f":{semantic_kind}:"
        if marker in role:
            return f"{semantic_kind}:{role.rsplit(':', 1)[-1]}"
    return role


def construct_role_signature(item: LayoutEvent) -> tuple[str, ...]:
    """Return construct roles without source-generated construct identifiers."""

    return tuple(_normalized_construct_role(role) for role in item.event.construct_roles)


def compatibility_event_signature(item: LayoutEvent) -> tuple[object, ...]:
    """Return raw normalized/source fields for exact compatibility classifiers."""

    event = item.event
    duration = event.duration
    return (
        event.kind,
        event.code,
        event.source_code,
        event.render_code,
        event.pitch,
        event.accidental,
        event.octave,
        event.duration_slashes,
        event.duration_dots,
        event.dotted,
        None
        if duration is None
        else (duration.numerator, duration.denominator, duration.text),
        event.decorations,
        event.attached_to_previous,
        construct_role_signature(item),
    )


def semantic_event_signature(item: LayoutEvent) -> tuple[object, ...]:
    """Backward-compatible alias for the measured compatibility signature."""

    return compatibility_event_signature(item)


def measure_duration_boundaries(row: Sequence[LayoutEvent]) -> tuple[Fraction, ...] | None:
    grid = measure_grid_from_durations(
        0,
        (
            event_duration_fraction(item.event)
            for item in row
            if item.event.kind != MusicTokenKind.BARLINE
        ),
    )
    return None if grid is None else grid.boundaries


__all__ = [
    "NormalizedEventSignature",
    "compatibility_event_signature",
    "construct_role_signature",
    "event_signature",
    "grid_event_signature",
    "measure_duration_boundaries",
    "measure_durations",
    "semantic_event_signature",
    "normalized_grid_event_signature",
    "terminal_signature",
]
