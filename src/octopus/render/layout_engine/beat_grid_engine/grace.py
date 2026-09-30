"""Compute unscaled grace-marker reservation zones across shared rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from octopus.parser.ast import MusicTokenKind
from octopus.render.layout_engine.beat_grid_engine.spacing import duration_fraction
from octopus.render.layout_engine.beat_grid_engine.types import (
    TIMED_KINDS,
    GridEventKey,
    SharedGridRow,
    _ExactLine,
)


def _grace_marker_shifts(
    rows: Sequence[SharedGridRow],
    exact_lines: Sequence[_ExactLine],
    event_positions: Mapping[GridEventKey, tuple[int, int, int]],
    event_x_offsets: Mapping[GridEventKey, Fraction],
    event_onsets: Mapping[GridEventKey, Fraction],
    barline_x_offsets: Sequence[Fraction],
) -> tuple[dict[GridEventKey, int], dict[tuple[int, int], int], int, int]:
    """Stretched-space shifts caused by unquoted grace markers.

    Returns ``(event_shifts, barline_shifts, reservation_total, left_delta)``
    with ``barline_shifts`` keyed by ``(voice_index, barline_ordinal)``.

    Oracle-verified 2026-08-23 (Looking-Back p1/p3 systems plus probes E/F/G/
    H/I on the reference server): markers in the same union column
    deduplicate to one gap of the largest reservation, applied in stretched
    space (after scaling).  Two marker families:

    * a marker on the system's first column moves the note-start x right by
      its gap (``left_delta``) and reserves no width for the compression
      scale.  It additionally opens a negative zone of ``-gap`` in every row
      that has a column sounding during the host note's span (onset inside
      ``(host_onset, host_onset + host_duration]``): from that row's first
      column strictly after the host note's end to the end of the system,
      events and barlines alike;
    * any other marker shifts, for every row that has an event in the host
      column, from that column onward by ``+gap`` - bounded per row by that
      row's own beat when it holds a later column there, otherwise persisting
      through all later columns and barlines to the end of the system.  It
      counts toward ``reservation_total`` exactly when the system's first row
      has an event in the host column (the anchor row's width budget is what
      the compression scale solves against).

    Zones from different markers add; a negative zone and a positive zone on
    the same column cancel where they overlap (probes H1/H2, Looking-Back p3
    L93-L98).
    """
    event_shifts: dict[GridEventKey, int] = {}
    barline_shifts: dict[tuple[int, int], int] = {}

    # Per-row timed events and barlines in natural-offset order; a row's
    # barline ordinal indexes the shared per-measure barline offsets.
    row_events: list[list[tuple[Fraction, GridEventKey]]] = []
    row_bars: list[list[Fraction]] = []
    row_onsets: list[list[tuple[Fraction, Fraction]]] = []
    for row in rows:
        events: list[tuple[Fraction, GridEventKey]] = []
        onsets: list[tuple[Fraction, Fraction]] = []
        bars: list[Fraction] = []
        ordinal = 0
        for event in row.events:
            if event.kind == MusicTokenKind.BARLINE:
                if ordinal < len(barline_x_offsets):
                    bars.append(barline_x_offsets[ordinal])
                ordinal += 1
                continue
            if event.kind not in TIMED_KINDS:
                continue
            key = GridEventKey.for_event(event, row.voice_index)
            offset = event_x_offsets.get(key)
            if offset is None:
                continue
            events.append((offset, key))
            onset = event_onsets.get(key)
            if onset is not None:
                onsets.append((onset, offset))
        events.sort()
        row_events.append(events)
        row_bars.append(bars)
        row_onsets.append(onsets)

    def row_upper_at(row_index: int, offset: Fraction) -> Fraction | None:
        """The last column of the row's own beat holding ``offset``.

        The stop rule is per-row (oracle-verified 2026-08-23, Looking-Back p1
        L34 m3 vs L31 m3): a row whose beat holds no later column than the
        host column keeps the gap to the end of the system, while a row with
        a later column in that same beat drops it before the next beat.
        """
        for event_offset, key in row_events[row_index]:
            if event_offset != offset:
                continue
            m_i, b_i, c_i = event_positions[key]
            items = exact_lines[row_index][m_i][b_i]
            voice = rows[row_index].voice_index
            last = max(
                event_x_offsets[GridEventKey.for_event(item.event, voice)]
                for item in items
            )
            return None if c_i == len(items) - 1 else last
        return None

    def shift_row_from(
        row_index: int,
        lower: Fraction,
        upper: Fraction | None,
        gap: int,
    ) -> None:
        voice = rows[row_index].voice_index
        for event_offset, key in row_events[row_index]:
            if event_offset >= lower and (upper is None or event_offset <= upper):
                event_shifts[key] = event_shifts.get(key, 0) + gap
        for ordinal, bar_offset in enumerate(row_bars[row_index]):
            if bar_offset >= lower and (upper is None or bar_offset <= upper):
                slot = (voice, ordinal)
                barline_shifts[slot] = barline_shifts.get(slot, 0) + gap

    # Marker hosts grouped by union column (natural offset); the gap of a
    # column is its largest reservation and the host is that marker's event
    # (earliest row wins ties).
    markers_by_column: dict[Fraction, list[tuple[int, int, int, int, int]]] = {}
    for row_index, row in enumerate(rows):
        for event in row.events:
            if event.kind not in TIMED_KINDS or not event.grace_reservation:
                continue
            key = GridEventKey.for_event(event, row.voice_index)
            offset = event_x_offsets.get(key)
            if offset is None:
                continue
            m_i, b_i, c_i = event_positions[key]
            markers_by_column.setdefault(offset, []).append(
                (row_index, m_i, b_i, c_i, event.grace_reservation)
            )

    first_offset = min(event_x_offsets.values()) if event_x_offsets else None
    reservation_total = 0
    left_delta = 0
    for offset in sorted(markers_by_column):
        hosts = markers_by_column[offset]
        # Largest reservation wins; the earliest row breaks ties.
        host_row, m_i, b_i, c_i, gap = min(hosts, key=lambda item: (-item[4], item[0]))
        if offset == first_offset:
            # The system's first column has no room in front of it; the
            # reservation moves the whole system's left edge instead and
            # opens a negative zone behind the host note (probe H1/H2/I1).
            left_delta += gap
            host_item = exact_lines[host_row][m_i][b_i][c_i]
            host_onset = host_item.onset
            host_end = host_onset + duration_fraction(host_item.event)
            for row_index in range(len(rows)):
                row_onset_list = [onset for onset, _ in row_onsets[row_index]]
                if not any(
                    host_onset < onset <= host_end for onset in row_onset_list
                ):
                    continue
                start_offsets = [
                    offset for onset, offset in row_onsets[row_index] if onset > host_end
                ]
                if not start_offsets:
                    continue
                shift_row_from(row_index, min(start_offsets), None, -gap)
            continue
        # The anchor row's width budget is what the compression scale solves
        # against; only markers sitting in an anchor-row column reserve.
        if any(event_offset == offset for event_offset, _ in row_events[0]):
            reservation_total += gap
        for row_index, events in enumerate(row_events):
            if any(event_offset == offset for event_offset, _ in events):
                shift_row_from(
                    row_index, offset, row_upper_at(row_index, offset), gap
                )
    return event_shifts, barline_shifts, reservation_total, left_delta
