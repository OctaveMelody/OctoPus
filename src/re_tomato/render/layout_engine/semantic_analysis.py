"""Immutable semantic facts shared by layout classifiers and projections.

The compatibility renderer historically rediscovered these facts by matching
raw event-code strings.  This module computes them once from normalized events
and exact rational timing so subsequent policies can be independent of source
filenames, page numbers, and row snapshots.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from re_tomato.normalization.types import MusicEvent

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent, LayoutPage
from .hidden.hidden_streams import event_duration_fraction


class BoundaryKind(StrEnum):
    """Semantic boundary represented by a normalized event."""

    CONTENT = "content"
    BARLINE = "barline"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class EventFeatures:
    """Source-derived facts needed by layout and SVG policy."""

    item: LayoutEvent
    onset: Fraction
    duration: Fraction
    boundary: BoundaryKind
    is_timed: bool
    is_pitched: bool
    is_lyric_host: bool = False

    @property
    def event(self) -> MusicEvent:
        return self.item.event

    @property
    def construct_roles(self) -> tuple[str, ...]:
        return self.event.construct_roles

    def has_role(self, kind: str, role: str) -> bool:
        marker = f":{kind}:{role}"
        return any(part.endswith(marker) for part in self.construct_roles)


@dataclass(frozen=True, slots=True)
class RowAnalysis:
    """Exact timing and semantic topology for one visual row."""

    key: tuple[int, int, int]
    events: tuple[EventFeatures, ...]
    onset_grid: tuple[Fraction, ...]
    measure_boundaries: tuple[Fraction, ...]
    terminal_onset: Fraction
    lyric_hosts: frozenset[tuple[int, int]]

    @property
    def timed_events(self) -> tuple[EventFeatures, ...]:
        return tuple(feature for feature in self.events if feature.is_timed)

    @property
    def barlines(self) -> tuple[EventFeatures, ...]:
        return tuple(
            feature for feature in self.events if feature.boundary is BoundaryKind.BARLINE
        )

    @property
    def terminal_events(self) -> tuple[EventFeatures, ...]:
        return tuple(
            feature
            for feature in self.events
            if feature.onset >= self.terminal_onset
        )

    def feature_at(self, onset: Fraction) -> tuple[EventFeatures, ...]:
        return tuple(feature for feature in self.events if feature.onset == onset)


@dataclass(frozen=True, slots=True)
class SystemAnalysis:
    """Aligned row analyses and the union timing grid for one visual system."""

    key: tuple[int, int]
    rows: tuple[RowAnalysis, ...]
    union_onset_grid: tuple[Fraction, ...]

    @property
    def voices(self) -> tuple[int, ...]:
        return tuple(sorted({row.key[1] for row in self.rows}))

    def rows_at_onset(self, onset: Fraction) -> tuple[tuple[int, EventFeatures], ...]:
        return tuple(
            (row.key[1], feature)
            for row in self.rows
            for feature in row.feature_at(onset)
        )


def analyze_row(
    events: Sequence[LayoutEvent],
    *,
    lyric_hosts: Iterable[tuple[int, int]] = (),
) -> RowAnalysis:
    """Build an exact semantic row analysis from already ordered layout events."""

    if not events:
        raise ValueError("cannot analyze an empty row")
    first = events[0]
    lyric_host_set = frozenset(lyric_hosts)
    onset = Fraction()
    features: list[EventFeatures] = []
    boundaries: list[Fraction] = []
    for item in events:
        event = item.event
        is_barline = event.kind is MusicTokenKind.BARLINE
        duration = event_duration_fraction(event)
        timed = not is_barline and duration > 0
        feature = EventFeatures(
            item=item,
            onset=onset,
            duration=duration,
            boundary=BoundaryKind.BARLINE if is_barline else BoundaryKind.CONTENT,
            is_timed=timed,
            is_pitched=event.pitch is not None,
            is_lyric_host=(event.span.start.line, event.index) in lyric_host_set,
        )
        features.append(feature)
        if is_barline:
            boundaries.append(onset)
        elif timed:
            onset += duration
    terminal_onset = boundaries[-1] if boundaries else onset
    for index, feature in enumerate(features):
        if feature.onset >= terminal_onset and feature.boundary is BoundaryKind.CONTENT:
            features[index] = EventFeatures(
                item=feature.item,
                onset=feature.onset,
                duration=feature.duration,
                boundary=BoundaryKind.TERMINAL,
                is_timed=feature.is_timed,
                is_pitched=feature.is_pitched,
                is_lyric_host=feature.is_lyric_host,
            )
    grid = sorted({feature.onset for feature in features} | set(boundaries) | {onset})
    return RowAnalysis(
        key=(first.page_index, first.voice, first.line),
        events=tuple(features),
        onset_grid=tuple(grid),
        measure_boundaries=tuple(boundaries),
        terminal_onset=terminal_onset,
        lyric_hosts=lyric_host_set,
    )


def analyze_system(
    rows: Mapping[tuple[int, int, int], Sequence[LayoutEvent]],
    *,
    lyric_hosts_by_row: Mapping[tuple[int, int, int], Iterable[tuple[int, int]]] | None = None,
) -> tuple[SystemAnalysis, ...]:
    """Analyze rows and align them by page and visual-line identity."""

    lyric_hosts_by_row = lyric_hosts_by_row or {}
    analyzed = [
        analyze_row(events, lyric_hosts=lyric_hosts_by_row.get(key, ()))
        for key, events in rows.items()
        if events
    ]
    grouped: dict[tuple[int, int], list[RowAnalysis]] = defaultdict(list)
    for row in analyzed:
        grouped[(row.key[0], row.key[2])].append(row)
    result: list[SystemAnalysis] = []
    for key, system_rows in sorted(grouped.items()):
        union = sorted({onset for row in system_rows for onset in row.onset_grid})
        result.append(
            SystemAnalysis(
                key,
                tuple(sorted(system_rows, key=lambda row: row.key[1])),
                tuple(union),
            )
        )
    return tuple(result)


def analyze_layout_systems(layout: LayoutPage) -> tuple[SystemAnalysis, ...]:
    """Analyze visible rows in a page without changing layout state."""

    rows: dict[tuple[int, int, int], list[LayoutEvent]] = defaultdict(list)
    for item in layout.events:
        rows[(item.page_index, item.voice, item.line)].append(item)
    return analyze_system(rows)


__all__ = [
    "BoundaryKind",
    "EventFeatures",
    "RowAnalysis",
    "SystemAnalysis",
    "analyze_layout_systems",
    "analyze_row",
    "analyze_system",
]
