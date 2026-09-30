"""Mid-row DSB block systems on the union note-group column grid.

A mid-row system carries a ``{dsb}`` block that closes before the row's final
barline (2026-08-26, As-Wished - Choir p3 system 1 probe matrix).  The zone
grid shares the trailing architecture with decoded differences: extension
events create union onsets, rows may hold unequal beat totals per zone,
integer beats are shared columns every row snaps up to while sub-beat plain
events keep their own chain and dotted continuations keep their own ideal,
pair-start and dotted destinations reserve 3.6 on integer steps (dotted
starts force the integer base width at sub-beat onsets), a pair close steps
by its own duration class plus 3.6 on an integer beat when the zone opens
with an accidental and still continues, a row's own accidental reserves 3.6
on its very next step when that step lands on an integer beat.  Zone 1 leads
are per-row (each row clears its own meter-change label; a labeled leading
anchor adds the label width once more for the whole zone and suppresses the
accidental addend); block zones close with the DSB gap except when the block
region runs to the piece's end; and the natural total is c x (widest row span
+ one DSB gap) so each row's final zone absorbs its own slack to the page
edge.
"""

from __future__ import annotations

from fractions import Fraction

from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent, MusicEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_gap_reserves import _barline_event_indices
from .dsb_midrow_steps import (
    _midrow_continuation_ideal,
    _midrow_gap_step,
)
from .dsb_trailing_widths import (
    _dotted_span_projects,
    _has_regular_marker,
)
from .dsb_union_common import (
    _ACCIDENTAL_UNIT,
    _CHAIN_KINDS,
    _DOT_SPAN_EXTRA,
    _DSB_ZONE_GAP,
    _LEADING_GAP,
    _PLACED_KINDS,
    _STEP_OUT_BY_DURATION,
    _TERMINAL_GAP,
    OnsetMaxTracker,
    _base_step,
    _is_pair,
)

# The natural total of a mid-row system is c x (span + one DSB zone gap)
# where span is the widest row's sum of non-final zone widths plus its final
# zone span (leading gap + last column); k = (right - left) / total and each
# row's final zone absorbs whatever remains so every final barline lands on
# the page edge.  c was oracle-fit to <1e-7 across five probe configurations
# of As-Wished - Choir p3 system 2 plus the embedded system itself, and it
# reproduces the embedded p3 system 1 total exactly.
_MIDROW_FINAL_SCALE = Fraction(430, 437)

# A meter-change leading barline (|n'p:X/Y') reserves this much width before
# the first note of zone 1 for every row whose own leading barline carries
# the label; a labeled leading anchor additionally reserves it once more for
# the whole zone, and suppresses the accidental addend (2026-08-26 probes
# BASE/P1/P3/P5a/P10 of As-Wished - Choir p3 system 2).
_METER_LABEL_LEAD = 18.0



def dsb_midrow_context(rows: list[list[LayoutEvent]]) -> bool:
    """Whether the system carries a mid-row DSB block (oracle-verified shape).

    The verified shape (As-Wished - Choir p3 system 1, 2026-08-26): at least
    one voice anchors a ``{dsb}`` block that closes before the row's final
    barline, every row shares the same barline count, every zone of every
    row holds placed content (a row's own block zone holds its post-block
    events; the block content itself renders on the ghost/lower streams),
    and no pair crosses a barline: the per-zone model restarts each row's
    beat chain at every zone, so an unbalanced zone would misplace the pair
    (Hulunbuir-Grassland p3 carries such pairs and stays legacy).
    """
    if len(rows) < 2:
        return False
    barline_counts = {len(_barline_event_indices(row)) for row in rows}
    if len(barline_counts) != 1 or min(barline_counts) < 3:
        return False
    anchor_rows = [
        index
        for index, row in enumerate(rows)
        if any("&dsb_a" in (item.event.code or "") for item in row)
    ]
    if not anchor_rows:
        return False
    for index in anchor_rows:
        bars = _barline_event_indices(rows[index])
        anchor_position = next(
            position
            for position, event_index in enumerate(bars)
            if "&dsb_a" in (rows[index][event_index].event.code or "")
        )
        # A block that runs to the row's final barline is the trailing shape,
        # owned by dsb_continuation_context.
        if anchor_position + 1 >= len(bars):
            return False
    for row in rows:
        bars = _barline_event_indices(row)
        for start, end in zip(bars, bars[1:], strict=False):
            zone = row[start + 1 : end]
            if not any(item.event.kind in _PLACED_KINDS for item in zone):
                return False
            balance = sum(
                (item.event.code or "").count("(") - (item.event.code or "").count(")")
                for item in zone
            )
            if balance != 0:
                return False
    return True


def _leading_barline_has_meter_label(row: list[LayoutEvent]) -> bool:
    """Whether the row's leading barline carries a meter-change label."""
    code = row[0].event.code or ""
    return code.startswith("|n") and "'p:" in code


def _midrow_block_zone_ordinals(rows: list[list[LayoutEvent]]) -> set[int] | None:
    """Zone ordinals that are a DSB block zone for at least one row.

    A block spans exactly one zone: its closer barline sits immediately after
    the anchor.  Returns ``None`` when a block spans more than one zone (an
    unverified shape).
    """
    ordinals: set[int] = set()
    for row in rows:
        bars = _barline_event_indices(row)
        for position, event_index in enumerate(bars):
            if "&dsb_a" not in (row[event_index].event.code or ""):
                continue
            closer = next(
                (
                    later
                    for later in bars[position + 1 :]
                    if row[later].block == "dsb-tail"
                ),
                None,
            )
            if closer is None or bars.index(closer) != position + 1:
                return None
            ordinals.add(position + 1)
    return ordinals


def _segment_row_events_midrow(
    rows: list[list[LayoutEvent]],
    segments_by_row: list[list[list[int]]],
    ordinal: int,
) -> list[list[tuple[int, LayoutEvent, Fraction]]] | None:
    """Collect each row's placed events with beat onsets for one mid-row zone.

    Unlike the trailing shape, mid-row zones may hold unequal beat totals per
    row (parser quirks and partial block measures); the union grid only needs
    each row's onsets, and extension glyphs create onsets of their own.
    """
    row_events: list[list[tuple[int, LayoutEvent, Fraction]]] = []
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
    return row_events


def _model_segment_midrow(
    rows: list[list[LayoutEvent]],
    segments_by_row: list[list[list[int]]],
    ordinal: int,
    *,
    is_first: bool,
    is_block_zone: bool,
    assigned: dict[tuple[int, int], float],
) -> tuple[float, list[float]] | None:
    """Union column grid for one mid-row DSB zone (oracle-verified 2026-08-26).

    Same forward-pass architecture as the trailing shape, with the decoded
    mid-row differences: extension events create union onsets; rows measure
    their next step from their own previous position; integer beats are
    shared columns that every row snaps up to while sub-beat plain events
    keep their own chain below the column and dotted continuations keep
    their own ideal (max fixed step-out, full interior sum + 3.6 when the
    zone opens with an accidental); pair-start and dotted destinations
    reserve 3.6 on integer steps while dotted starts force the integer base
    width at sub-beat onsets; and a pair close steps by its own duration
    class plus 3.6 on an integer beat when the zone opens with an accidental
    and still continues.  Returns the furthest shared column together with
    one leading gap per row (zone 1's are genuinely per-row; other zones
    repeat a single shared value).
    """
    row_events = _segment_row_events_midrow(rows, segments_by_row, ordinal)
    if row_events is None:
        return None

    union_onsets = sorted(
        {onset for events in row_events for _, item, onset in events}
    )
    if not union_onsets:
        return None
    first_onset = union_onsets[0]
    last_onset = union_onsets[-1]
    leading_accidental = any(
        item.event.accidental is not None
        for events in row_events
        for _, item, onset in events
        if onset == first_onset and item.event.kind in _CHAIN_KINDS
    )

    placed_by_onset: dict[Fraction, list[tuple[int, int, LayoutEvent]]] = {}
    for row_index, events in enumerate(row_events):
        for event_index, item, onset in events:
            placed_by_onset.setdefault(onset, []).append((row_index, event_index, item))

    columns: dict[Fraction, float] = {}
    directly_strong: dict[Fraction, bool] = {}
    binding_max: dict[Fraction, float] = {}
    slots: list[float] = []
    cursor: list[tuple[float, Fraction, MusicEvent] | None] = [None] * len(rows)
    dotted_notes: list[tuple[Fraction, float, Fraction, bool]] = []
    pending_debt: list[bool] = [False] * len(rows)
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
            # Mid-row rows measure from their own position: a row sitting
            # below its shared column (target Z4 Q3 b1.5 at 66.6 under the
            # shared 84.6) keeps chaining from there.
            base_x = previous_x
            duration = event_duration_fraction(previous_event)
            if (
                item.event.kind in _CHAIN_KINDS
                and duration in _STEP_OUT_BY_DURATION
                and previous_onset + duration == onset
            ):
                ideal = _midrow_continuation_ideal(
                    base_x,
                    previous_onset,
                    onset,
                    duration,
                    first_onset=first_onset,
                    union_onsets=union_onsets,
                    leading_accidental=leading_accidental,
                )
                tracker.note(ideal, direct=True, binding=True)
            else:
                debt_fires = pending_debt[row_index] and onset.denominator == 1
                step = _midrow_gap_step(
                    previous_onset,
                    onset,
                    previous_event,
                    item.event,
                    union_onsets=union_onsets,
                    last_onset=last_onset,
                    leading_accidental=leading_accidental,
                    debt_fires=debt_fires,
                )
                structural_candidate = (
                    item.event.accidental is not None
                    or _is_pair(item.event.code)
                    or debt_fires
                )
                tracker.note(
                    base_x + step,
                    direct=structural_candidate,
                    binding=structural_candidate
                    or directly_strong.get(previous_onset, False),
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
            x = _midrow_assign_onset(
                row_index,
                item,
                onset=onset,
                previous=cursor[row_index],
                column=column,
                placed=placed,
                pending_debt=pending_debt,
                union_onsets=union_onsets,
                first_onset=first_onset,
                last_onset=last_onset,
                leading_accidental=leading_accidental,
            )
            assigned[(row_index, event_index)] = x
            cursor[row_index] = (x, onset, item.event)
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
    leading_gaps: list[float]
    if is_first:
        # Zone 1 leads are per-row (2026-08-26 probes BASE/P1/P3/P5a/P10):
        # each row clears its own meter label, a labeled leading anchor adds
        # the label width once more for the whole zone and suppresses the
        # accidental addend, and otherwise an accidental on the zone's first
        # onset reserves the unit.
        block_in_first = [
            index
            for index, row in enumerate(rows)
            if "&dsb_a" in (row[0].event.code or "")
        ]
        labeled_block_in_first = any(
            _leading_barline_has_meter_label(rows[index])
            for index in block_in_first
        )
        accidental_addend = (
            0.0 if labeled_block_in_first else _ACCIDENTAL_UNIT * leading_accidental
        )
        leading_gaps = [
            (_METER_LABEL_LEAD if _leading_barline_has_meter_label(row) else 0.0)
            + (_METER_LABEL_LEAD if labeled_block_in_first else 0.0)
            + accidental_addend
            for row in rows
        ]
    else:
        leading_gap = _DSB_ZONE_GAP if is_block_zone else _LEADING_GAP
        if leading_accidental:
            leading_gap += _ACCIDENTAL_UNIT
        leading_gaps = [leading_gap] * len(rows)
    return last_column, leading_gaps


def _midrow_assign_onset(
    row_index: int,
    item: LayoutEvent,
    *,
    onset: Fraction,
    previous: tuple[float, Fraction, MusicEvent] | None,
    column: float,
    placed: list[tuple[int, int, LayoutEvent]],
    pending_debt: list[bool],
    union_onsets: list[Fraction],
    first_onset: Fraction,
    last_onset: Fraction,
    leading_accidental: bool,
) -> float:
    """Assign one row's x at an onset (mid-row rule set).

    Integer beats snap up to the shared column; sub-beat dotted
    continuations keep their own ideal; sub-beat plain events chain from
    the row's own previous position.  Updates the row's one-shot accidental
    debt in place.
    """
    if previous is None:
        x = column
    elif onset.denominator == 1:
        # Integer beats are shared columns: every row snaps up to the zone
        # maximum (target Z4 b2/b3: rows chaining at 97.2/145.8 render on
        # the shared 115.2/151.2).
        x = column
    else:
        previous_x, previous_onset, previous_event = previous
        duration = event_duration_fraction(previous_event)
        if (
            item.event.kind in _CHAIN_KINDS
            and duration in _STEP_OUT_BY_DURATION
            and previous_onset + duration == onset
        ):
            # A dotted continuation at a sub-beat onset keeps its own ideal
            # (target Z4: 7.@b2 -> b3.5 at 151.2 while the shared column is
            # 187.2).
            others_mark = any(
                other_row != row_index
                and other_item.event.kind in _CHAIN_KINDS
                for other_row, _, other_item in placed
            )
            if not others_mark:
                x = column
            else:
                x = _midrow_continuation_ideal(
                    previous_x,
                    previous_onset,
                    onset,
                    duration,
                    first_onset=first_onset,
                    union_onsets=union_onsets,
                    leading_accidental=leading_accidental,
                )
        else:
            # Sub-beat plain events keep their own chain below the shared
            # column (target Z4 Q3 b1.5 at 66.6 under the shared 84.6;
            # b1.75 at 84.6).
            step = _midrow_gap_step(
                previous_onset,
                onset,
                previous_event,
                item.event,
                union_onsets=union_onsets,
                last_onset=last_onset,
                leading_accidental=leading_accidental,
                debt_fires=False,
            )
            x = previous_x + step
    if item.event.accidental is not None:
        pending_debt[row_index] = True
    elif previous is not None:
        # One-shot: the row's next step has been taken, whether or not it
        # landed on an integer beat.
        pending_debt[row_index] = False
    return x


def _midrow_zone_terminal(is_block_zone: bool, dsb_tail_final: bool = False) -> float:
    """Terminal gap of a non-final mid-row zone (oracle-verified 2026-08-26).

    Non-final zones close with 25.2, or 39.6 when the zone is a DSB block
    zone for any row — except that a block whose region runs to the piece's
    end (the anchor row's final barline carries the dsb-tail identity; the
    two-measure blocks of As-Wished - Choir p3 system 2) closes with the
    plain 25.2 terminal instead.
    """
    if is_block_zone:
        return _TERMINAL_GAP if dsb_tail_final else _DSB_ZONE_GAP
    return _TERMINAL_GAP


__all__ = [
    "_midrow_block_zone_ordinals",
    "_model_segment_midrow",
    "_midrow_zone_terminal",
    "dsb_midrow_context",
]
