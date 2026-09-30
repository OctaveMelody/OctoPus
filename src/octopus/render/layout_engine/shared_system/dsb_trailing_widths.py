"""Trailing DSB block systems on the union note-group column grid.

A trailing system carries a ``{dsb}`` block that runs from its anchor to the
row's final barline; the visible rows are laid on the shared beat-onset
columns decoded from the oracle (2026-08-25, As-Wished - Choir p1/p2).
"""

from __future__ import annotations

from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent, MusicEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_gap_reserves import _barline_event_indices
from .dsb_union_common import (
    _ACCIDENTAL_UNIT,
    _CHAIN_KINDS,
    _DOT_SPAN_EXTRA,
    _DSB_ZONE_GAP,
    _LEADING_GAP,
    _PLACED_KINDS,
    _STEP_OUT_BY_DURATION,
    OnsetMaxTracker,
    _base_step,
    _ceiling_slot_after,
    _is_pair,
)


def dsb_continuation_context(
    rows: list[list[LayoutEvent]],
) -> tuple[int, int] | None:
    """Return (authority row index, anchor barline ordinal) when eligible.

    The verified shape is a block that runs from the anchor to the row's final
    barline with visible timed content after the anchor; every row of the
    system must share the same barline count and open with a placed event.
    The decoded step rules (27 per integer beat, 18 per half beat) were
    oracle-verified only in four-beat measures, so systems whose first
    measure holds a different beat total (e.g. City-of-Light - Choir v3 p2,
    three beats per bar) stay on the legacy projection.
    """
    if len(rows) < 2:
        return None
    authority_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any("&dsb_a" in (item.event.code or "") for item in row)
        ),
        None,
    )
    if authority_index is None:
        return None
    authority = rows[authority_index]
    authority_barlines = _barline_event_indices(authority)
    anchor_ordinal = next(
        (
            position
            for position, event_index in enumerate(authority_barlines)
            if "&dsb_a" in (authority[event_index].event.code or "")
        ),
        None,
    )
    if anchor_ordinal is None:
        return None
    anchor_event = authority_barlines[anchor_ordinal]
    if not any(
        item.event.kind
        in _PLACED_KINDS | frozenset({MusicTokenKind.HIDDEN_REST})
        for item in authority[anchor_event + 1 :]
    ):
        return None
    tails = 0
    for later in authority_barlines[anchor_ordinal + 1 :]:
        if authority[later].block == "dsb-tail":
            tails += 1
        else:
            break
    if tails < 2 or authority_barlines[anchor_ordinal + tails] != len(authority) - 1:
        return None
    for row in rows:
        if len(_barline_event_indices(row)) != len(authority_barlines):
            return None
        if not row or row[0].event.kind not in _PLACED_KINDS:
            return None
        # An extension glyph holds the previous note out for one extra beat.
        first_measure = sum(
            event_duration_fraction(item.event)
            for item in row[: _barline_event_indices(row)[0]]
            if item.event.kind in _CHAIN_KINDS
        ) + sum(
            1
            for item in row[: _barline_event_indices(row)[0]]
            if item.event.kind == MusicTokenKind.EXTENSION
        )
        if first_measure != 4:
            return None
    return authority_index, anchor_ordinal


def _segment_row_events(
    rows: list[list[LayoutEvent]],
    segments_by_row: list[list[list[int]]],
    ordinal: int,
) -> list[list[tuple[int, LayoutEvent, Fraction]]] | None:
    """Collect each row's placed events with beat onsets for one segment.

    Returns None when a segment is empty or the rows disagree on the total
    beat count (the reference only shares columns across equal measures).
    """
    row_events: list[list[tuple[int, LayoutEvent, Fraction]]] = []
    totals: set[Fraction] = set()
    for row_index in range(len(rows)):
        events: list[tuple[int, LayoutEvent, Fraction]] = []
        beat = Fraction(0)
        for event_index in segments_by_row[row_index][ordinal]:
            item = rows[row_index][event_index]
            if item.event.kind not in _PLACED_KINDS:
                return None
            events.append((event_index, item, beat))
            beat += event_duration_fraction(item.event)
        if not events:
            return None
        row_events.append(events)
        totals.add(beat)
    if len(totals) != 1:
        return None
    return row_events


def _has_regular_marker(
    placed: list[tuple[int, int, LayoutEvent]],
    cursor: list[tuple[float, Fraction, MusicEvent] | None],
    onset: Fraction,
) -> bool:
    """Whether any row marks the onset with a plain chain event.

    Dotted eighths only project onto such onsets (As-Wished p1 m2: the 3/).@b3
    reserve stays out of b3.5 because its only marker is the dotted half's
    continuation, while the zone 4/.@b1 projects onto b1.5 which plain
    eighths mark).
    """
    for row_index, _, item in placed:
        if item.event.kind not in _CHAIN_KINDS:
            continue
        previous = cursor[row_index]
        if previous is None:
            return True
        _, previous_onset, previous_event = previous
        previous_duration = event_duration_fraction(previous_event)
        if (
            previous_duration in _STEP_OUT_BY_DURATION
            and previous_onset + previous_duration == onset
        ):
            continue
        return True
    return False


def _dotted_span_projects(
    duration: Fraction,
    onset: Fraction,
    union_onsets: list[Fraction],
) -> bool:
    """Eligibility of a dotted note's span reserve at its start onset.

    A dotted quarter projects only when every interior onset sits at or past
    the next integer beat; an earlier half or sixteenth inside its span voids
    the reserve (As-Wished p1 m2: 3,.)@b2 with b2.5/b2.75 inside never
    projects, while the post-zone 3.@b2 with only b3/b3.25 inside does).
    """
    if duration != Fraction(3, 2):
        return True
    interiors = [u for u in union_onsets if onset < u < onset + duration]
    return all(u >= int(onset) + 1 for u in interiors)


def _model_segment(
    rows: list[list[LayoutEvent]],
    segments_by_row: list[list[list[int]]],
    ordinal: int,
    *,
    is_first: bool,
    is_dsb_zone: bool,
    assigned: dict[tuple[int, int], float],
) -> tuple[float, float] | None:
    """Model one DSB (double-stemmed-beat) trailing segment across the shared rows.

    Collects the chain-kind events of the given segment ordinal from every row,
    aligns them by onset, and returns the segment's modeled (start, end) x span or
    None when the segment has no chainable content in this system."""
    row_events = _segment_row_events(rows, segments_by_row, ordinal)
    if row_events is None:
        return None

    union_onsets = sorted(
        {
            onset
            for events in row_events
            for _, item, onset in events
            if item.event.kind in _CHAIN_KINDS
        }
    )
    if not union_onsets:
        return None
    first_onset = union_onsets[0]

    placed_by_onset: dict[Fraction, list[tuple[int, int, LayoutEvent]]] = {}
    for row_index, events in enumerate(row_events):
        for event_index, item, onset in events:
            if onset not in union_onsets:
                # Extension glyphs only ride on onsets that some row marks.
                return None
            placed_by_onset.setdefault(onset, []).append((row_index, event_index, item))

    columns: dict[Fraction, float] = {}
    # An onset is "directly strong" when its column value is achieved by a
    # structural candidate (first note, dot span, accidental reserve, pair,
    # or dotted step-out) rather than by plain rhythm steps. Only directly
    # strong columns bind other rows' events to their shared position.
    directly_strong: dict[Fraction, bool] = {}
    binding_max: dict[Fraction, float] = {}
    slots: list[float] = []
    cursor: list[tuple[float, Fraction, MusicEvent] | None] = [None] * len(rows)
    # (start_onset, start_x, duration, projects) where `projects` is the
    # decoded eligibility of the dotted note's span reserve (see below).
    dotted_notes: list[tuple[Fraction, float, Fraction, bool]] = []
    # An accidental keeps widening the row's step into the next integer-beat
    # onset until that step has paid the reserve.
    accidental_debt: list[bool] = [False] * len(rows)
    previous_column = 0.0
    previous_onset_global: Fraction | None = None
    for onset in union_onsets:
        placed = placed_by_onset[onset]
        tracker = OnsetMaxTracker()

        tracker.note(
            previous_column,
            binding=(
                previous_onset_global is not None
                and directly_strong.get(previous_onset_global, False)
            ),
        )
        for row_index, _, item in placed:
            previous = cursor[row_index]
            if previous is None:
                tracker.note(0.0, direct=True, binding=True)
                continue
            previous_x, previous_onset, previous_event = previous
            # A row that was snapped off its own column still measures its
            # next step from the shared column it belongs to (As-Wished p2
            # m5: 3,/ snaps to 48.6 but 6,,@b2 still steps from 75.6).
            base_x = columns[previous_onset]
            duration = event_duration_fraction(previous_event)
            if (
                item.event.kind in _CHAIN_KINDS
                and duration in _STEP_OUT_BY_DURATION
                and previous_onset + duration == onset
            ):
                # A dotted continuation proposes its own step-out ideal; it
                # never drags the shared column with a plain rhythm step.
                tracker.note(
                    base_x + _STEP_OUT_BY_DURATION[duration],
                    direct=True,
                    binding=True,
                )
            else:
                step = _gap_step(
                    previous_onset,
                    onset,
                    union_onsets,
                    item.event,
                    accidental_debt[row_index],
                )
                structural = (
                    item.event.accidental is not None
                    or _is_pair(item.event.code)
                    or (accidental_debt[row_index] and onset.denominator == 1)
                )
                tracker.note(
                    base_x + step,
                    direct=structural,
                    binding=structural or directly_strong.get(previous_onset, False),
                )
        regular_here = _has_regular_marker(placed, cursor, onset)
        for start_onset, start_x, duration, projects in dotted_notes:
            if not (start_onset < onset < start_onset + duration):
                continue
            if duration == Fraction(3, 4):
                if not regular_here:
                    continue
            elif not projects:
                continue
            base = sum(
                _base_step(u) for u in union_onsets if start_onset < u <= onset
            )
            tracker.note(start_x + base + _DOT_SPAN_EXTRA, direct=True, binding=True)
        column = max(tracker.candidates)
        columns[onset] = column
        # A column is directly strong only when every candidate that reaches
        # its value is structural; a plain step tying a dot span leaves the
        # onset unbound (As-Wished p1 post-zone b3.25: 165.6 from both).
        directly_strong[onset] = (
            tracker.direct_max is not None
            and abs(column - tracker.direct_max) < GEOMETRY_EPSILON
            and (
                tracker.non_direct_max is None
                or column > tracker.non_direct_max + GEOMETRY_EPSILON
            )
        )
        bound = tracker.bound_max
        binding_max[onset] = bound if bound is not None else float("-inf")
        previous_onset_global = onset
        slots = sorted(set(slots) | {column})

        for row_index, event_index, item in placed:
            previous = cursor[row_index]
            if previous is None or item.event.kind == MusicTokenKind.EXTENSION or _is_pair(
                item.event.code
            ):
                x = column
            else:
                previous_x, previous_onset, previous_event = previous
                duration = event_duration_fraction(previous_event)
                if (
                    duration in _STEP_OUT_BY_DURATION
                    and previous_onset + duration == onset
                ):
                    # A dotted continuation may sit before its own column,
                    # on the first slot at or after its step-out ideal, but
                    # only when other rows mark the onset; an unmarked onset
                    # keeps it on the shared column (As-Wished p2 zone Q2
                    # 3/@b1.5 -> 45 below the shared 63, while p1 m2 Q4
                    # 0//@b3.5 -> 153 on its own unmarked column).
                    others_mark = any(
                        other_row != row_index
                        and other_item.event.kind in _CHAIN_KINDS
                        for other_row, _, other_item in placed
                    )
                    if not others_mark:
                        x = column
                    else:
                        ideal = (
                            columns[previous_onset]
                            + _STEP_OUT_BY_DURATION[duration]
                        )
                        x = _ceiling_slot_after(slots, previous_x, ideal)
                elif previous_x != columns[previous_onset]:
                    x = column
                else:
                    # A plain event keeps its own chain ideal unless a
                    # binding (structural) candidate at the same onset pulls
                    # it onto the shared position: post-zone Q2 0/@b3.5 stays
                    # at 165.6 below the 183.6 another row's plain step made,
                    # while p2 m5 Q4 6,,@b2 joins the 102.6 that a dotted
                    # step-out column steps into.
                    step = _gap_step(
                        previous_onset,
                        onset,
                        union_onsets,
                        item.event,
                        accidental_debt[row_index],
                    )
                    ideal = columns[previous_onset] + step
                    bound = binding_max.get(onset, float("-inf"))
                    x = max(ideal, bound)
            assigned[(row_index, event_index)] = x
            cursor[row_index] = (x, onset, item.event)
            if item.event.accidental is not None:
                accidental_debt[row_index] = True
            elif onset.denominator == 1:
                accidental_debt[row_index] = False
        previous_column = column

        for _row_index, _, item in placed:
            if item.event.kind not in _CHAIN_KINDS:
                continue
            duration = event_duration_fraction(item.event)
            if duration not in _STEP_OUT_BY_DURATION or onset == first_onset:
                continue
            projects = _dotted_span_projects(duration, onset, union_onsets)
            dotted_notes.append((onset, column, duration, projects))

    last_column = columns[union_onsets[-1]]
    leading_gap = 0.0
    if not is_first:
        leading_gap = _DSB_ZONE_GAP if is_dsb_zone else _LEADING_GAP
        if any(
            item.event.accidental is not None
            for _, _, item in placed_by_onset[first_onset]
            if item.event.kind in _CHAIN_KINDS
        ):
            leading_gap += _ACCIDENTAL_UNIT
    return last_column, leading_gap


def _chain_step(
    previous_onset: Fraction,
    onset: Fraction,
    union_onsets: list[Fraction],
) -> float:
    """Width of a row's own chain step between two of its onsets.

    The destination onset always carries its base width; intermediate union
    onsets add their base width only at half-beat granularity, so sixteenth
    positions are subdivisions that do not add width when a row skips over
    them (oracle-verified 2026-08-25: As-Wished p1 zone b0->b1 steps 45
    across the half beat while b1.5->b2 steps 27 across the sixteenth
    position; consecutive sixteenths in p2 m1 still step 18 each).
    """
    return _base_step(onset) + sum(
        _base_step(u)
        for u in union_onsets
        if previous_onset < u < onset and u.denominator <= 2
    )


def _gap_step(
    previous_onset: Fraction,
    onset: Fraction,
    union_onsets: list[Fraction],
    event: MusicEvent,
    accidental_debt: bool,
) -> float:
    step = _chain_step(previous_onset, onset, union_onsets)
    if event.accidental is not None:
        step += _ACCIDENTAL_UNIT
    if accidental_debt and onset.denominator == 1:
        step += _ACCIDENTAL_UNIT
    return step


__all__ = [
    "_dotted_span_projects",
    "_gap_step",
    "_has_regular_marker",
    "_model_segment",
    "dsb_continuation_context",
]
