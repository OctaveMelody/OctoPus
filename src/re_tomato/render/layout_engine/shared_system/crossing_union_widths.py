"""Union onset column widths for crossing-pair two-row shared systems.

A two-row system whose voices contain parenthesized groups that span a
barline is laid by the reference renderer on a per-zone union column grid
instead of independent per-row widths:

* Integer-beat onsets share one column per zone. Every row's event at such an
  onset snaps to the max of all rows' chain values plus structural reserves
  (dotted-span projections, accidental and &zkh debts). A sparse voice is
  pulled up to the shared value; a dense voice defines it (TTC p1 y449 z4:
  the quarter-note voice's b2 note joins the sixteenth voice at column 72).
* Sub-beat onsets keep per-row chain values. Each row measures from the
  position its own previous event holds, so two rows with different local
  subdivisions may sit at different x for the same onset (TTC p1 y805 z4:
  b3.5/b3.75 hold 171/189 in one row and 189/207 in the other).
* A mid-zone dotted note jumps one integer beat (27) ahead of its chain value
  when a marked integer onset falls inside its span: the dot mark must clear
  the other voice's activity on that beat (TTC p1 y805: 6(.@b2.5 and 2.@b2.5
  draw at 99; TTC p2 y80: 3/.@b2 stays at 90 because its span marks no beat).
* A &zkh-decorated event claims +9 on its step-in and pays +9 debt on the
  next integer-beat step (TTC p1 y983 z4: 0&zkh@b3, then b4 at 36).
* Zero-duration hidden rests are placed like rests (they render a null glyph)
  but carry no beat (TTC p1 y983 z4: the hidden rest shares column b4).
* A zone-start glyph needs clearance left of the first notehead: an
  accidental mark adds 3.6 to the lead (I-Like p1 y326 z3: lead 28.8) and a
  &zkh opening paren adds 9 (China-In-The-Lights p1 y910 z5: lead 34.2).
* A closing paren (&ykh) on the zone's final event reserves one dot-span unit
  (9) of clearance after it (China-In-The-Lights p1 y910 z5: last column 99
  instead of 90).
* A meter-change barline (code like ``|'p:2/4'``) carries the new meter label,
  which needs one extra sub-step (18) of clearance after it: the zone that
  follows draws at lead 43.2 (Wait-For-My-Dear p1 y1253 and Wait-For-My-Dear2
  p1 y1223: both barlines around the temporary 2/4 measure).  A plain short
  or pickup measure without a meter marker keeps the plain lead (I-Like p1
  y326).

The system scale uses the trailing DSB formula k = (right - left + 14) /
(total + 18) with the final barline pinned to ``right``.

Eligibility: only systems without accidentals or hidden rests are routed here
(oracle-verified 2026-08-27 on all 22 such crossing systems in the corpus).
Systems carrying those glyphs use per-row intrinsic spacing in the reference
output and keep the legacy reconciled widths.
"""

from __future__ import annotations

import re
from fractions import Fraction

from ....normalization.types import MusicEvent
from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_gap_reserves import _barline_event_indices
from .dsb_union_common import (
    _ACCIDENTAL_UNIT,
    _CHAIN_KINDS,
    _DENOMINATOR_EXTRA,
    _DOT_SPAN_EXTRA,
    _LEADING_GAP,
    _PLACED_KINDS,
    _STEP_OUT_BY_DURATION,
    _SUBSTEP,
    _TERMINAL_GAP,
    _base_step,
)

_ZKH_UNIT = 9.0
_CROSSING_PLACED_KINDS = _PLACED_KINDS | frozenset({MusicTokenKind.HIDDEN_REST})
_METER_CHANGE_RE = re.compile(r"p:\d+/\d+")
# Float-match tolerance from the acceptance policy: below this, a coordinate
# difference is float noise rather than a real repositioning.
_FLOAT_NOISE_LIMIT = 1e-6


def _row_has_crossing_group(row: list[LayoutEvent]) -> bool:
    """True when some parenthesized group in the row spans a barline."""
    depth = 0
    for item in row:
        code = item.event.code or ""
        if item.event.kind == MusicTokenKind.BARLINE:
            if depth > 0:
                return True
            continue
        depth += code.count("(") - code.count(")")
    return False


def _has_regular_marker(
    placed: list[tuple[int, int, LayoutEvent]],
    cursor: list[tuple[float, Fraction, MusicEvent] | None],
    onset: Fraction,
) -> bool:
    """True when some row marks ``onset`` with a plain chain step."""
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


def _dotted_span_projects_crossing(
    duration: Fraction,
    onset: Fraction,
    union_onsets: list[Fraction],
) -> bool:
    """A dotted quarter projects its span reserve only when its end onset is
    itself a union onset and every interior onset sits on or after the next
    integer beat (TTC p1 y449: 5(.@b0 projects onto b1; y805: 2.@b2.5 does
    not project past b3 because its end b4 is unmarked)."""
    if duration != Fraction(3, 2):
        return True
    if onset + duration not in union_onsets:
        return False
    interiors = [u for u in union_onsets if onset < u < onset + duration]
    return all(u >= int(onset) + 1 for u in interiors)


def _model_segment_crossing(
    rows: list[list[LayoutEvent]],
    segments_by_row: list[list[list[int]]],
    ordinal: int,
    *,
    is_first: bool,
    assigned: dict[tuple[int, int], float],
) -> tuple[float, float] | None:
    """Model one zone of a crossing system.

    Returns (last_x, leading_gap) where last_x is the maximum assigned x in
    the zone, or None when the zone cannot be modeled.
    """
    row_events: list[list[tuple[int, LayoutEvent, Fraction]]] = []
    for r in range(len(rows)):
        events: list[tuple[int, LayoutEvent, Fraction]] = []
        beat = Fraction(0)
        for idx in segments_by_row[r][ordinal]:
            item = rows[r][idx]
            if item.event.kind not in _CROSSING_PLACED_KINDS:
                return None
            events.append((idx, item, beat))
            beat += event_duration_fraction(item.event)
        if not events:
            return None
        row_events.append(events)

    union_onsets = sorted({o for ev in row_events for _, _, o in ev})
    if not union_onsets:
        return None
    # Every row must anchor the zone at its first union onset; a row entering
    # mid-zone has no verified placement rule and keeps the legacy widths.
    for ev in row_events:
        if ev[0][2] != union_onsets[0]:
            return None
    placed_by_onset: dict[Fraction, list[tuple[int, int, LayoutEvent]]] = {}
    for row_index, ev in enumerate(row_events):
        for idx, item, onset in ev:
            placed_by_onset.setdefault(onset, []).append((row_index, idx, item))

    columns: dict[Fraction, float] = {}
    cursor: list[tuple[float, Fraction, MusicEvent] | None] = [None] * len(rows)
    dotted_notes: list[tuple[Fraction, float, Fraction, bool]] = []
    accidental_debt: list[bool] = [False] * len(rows)
    zkh_debt: list[bool] = [False] * len(rows)
    previous_column = 0.0
    zone_max_x = 0.0

    def _gap_step(
        prev_onset: Fraction,
        onset: Fraction,
        event: object,
        debt: bool,
        zdebt: bool,
    ) -> float:
        step = _base_step(onset) + sum(
            _base_step(u)
            for u in union_onsets
            if prev_onset < u < onset and u.denominator <= 2
        )
        if getattr(event, "accidental", None) is not None:
            step += _ACCIDENTAL_UNIT
        if debt and onset.denominator == 1:
            step += _ACCIDENTAL_UNIT
        if "zkh" in (getattr(event, "decorations", None) or ()):
            step += _ZKH_UNIT
        if zdebt and onset.denominator == 1:
            step += _ZKH_UNIT
        return step

    def _chain_value(
        row_index: int, item: LayoutEvent, onset: Fraction
    ) -> tuple[float, bool]:
        """This row's own x for ``onset``, measured from its cursor.

        Returns (x, is_step_out). A step-out continuation (the event that
        follows a dotted note) may be ceilinged to the previous integer-beat
        column by the caller so it never sits left of that beat's shared
        position (WFD2 p1 y766 z2: 3/@b1.5 draws at 45, not 36).
        """
        previous = cursor[row_index]
        if previous is None:
            return 0.0, False
        prev_x, prev_onset, prev_event = previous
        duration = event_duration_fraction(prev_event)
        if (
            item.event.kind in _CHAIN_KINDS
            and duration in _STEP_OUT_BY_DURATION
            and prev_onset + duration == onset
        ):
            return prev_x + _STEP_OUT_BY_DURATION[duration], True
        return (
            prev_x
            + _gap_step(
                prev_onset,
                onset,
                item.event,
                accidental_debt[row_index],
                zkh_debt[row_index],
            ),
            False,
        )

    def _dotted_jump_applies(item: LayoutEvent, onset: Fraction) -> bool:
        """A mid-zone dotted note jumps one integer beat (27) ahead of its
        chain value when a marked integer onset falls inside its span: the dot
        mark must clear the other voice's activity on that beat.

        TTC p1 y805: 6(.@b2.5 and 2.@b2.5 draw at 99 (b3 is marked in the
        other row); TTC p2 y80: 3/.@b2 stays at 90 (span b2..b2.75 marks no
        beat); Looking-Back p4: 0.@b1.5 stays at 36 (b2 unmarked).
        """
        if item.event.kind not in _CHAIN_KINDS:
            return False
        duration = event_duration_fraction(item.event)
        if duration not in _STEP_OUT_BY_DURATION:
            return False
        if onset == union_onsets[0]:
            return False
        end = onset + duration
        return any(u.denominator == 1 for u in union_onsets if onset < u < end)

    def _place(
        row_index: int, event_index: int, item: LayoutEvent, x: float, onset: Fraction
    ) -> None:
        nonlocal zone_max_x
        assigned[(row_index, event_index)] = x
        cursor[row_index] = (x, onset, item.event)
        zone_max_x = max(zone_max_x, x)
        if item.event.accidental is not None:
            accidental_debt[row_index] = True
        elif onset.denominator == 1:
            accidental_debt[row_index] = False
        if "zkh" in (item.event.decorations or ()):
            zkh_debt[row_index] = True
        elif onset.denominator == 1:
            zkh_debt[row_index] = False

    for onset in union_onsets:
        placed = placed_by_onset.get(onset, [])
        if onset.denominator == 1:
            candidates = [previous_column]
            for row_index, _, item in placed:
                value, _ = _chain_value(row_index, item, onset)
                candidates.append(value)
            for start_onset, start_x, duration, projects in dotted_notes:
                if not (start_onset < onset < start_onset + duration):
                    continue
                if duration == Fraction(3, 4):
                    if not _has_regular_marker(placed, cursor, onset):
                        continue
                elif not projects:
                    continue
                base = sum(
                    _base_step(u) for u in union_onsets if start_onset < u <= onset
                )
                candidates.append(start_x + base + _DOT_SPAN_EXTRA)
            column = max(candidates)
            columns[onset] = column
            previous_column = column
            for row_index, event_index, item in placed:
                x = column + (27.0 if _dotted_jump_applies(item, onset) else 0.0)
                _place(row_index, event_index, item, x, onset)
        else:
            for row_index, event_index, item in placed:
                x, is_step_out = _chain_value(row_index, item, onset)
                # ``Fraction`` keys hash equal to their integer value; spell it out so the
                # lookup type-checks instead of relying on that.
                beat_column = columns.get(Fraction(int(onset)))
                if is_step_out and beat_column is not None:
                    x = max(x, beat_column)
                if _dotted_jump_applies(item, onset):
                    x += 27.0
                _place(row_index, event_index, item, x, onset)

        for row_index, event_index, item in placed:
            if item.event.kind not in _CHAIN_KINDS:
                continue
            duration = event_duration_fraction(item.event)
            if duration not in _STEP_OUT_BY_DURATION:
                continue
            projects = _dotted_span_projects_crossing(duration, onset, union_onsets)
            dotted_notes.append(
                (onset, assigned[(row_index, event_index)], duration, projects)
            )

    # Trailing reserves at the zone's last column.
    for r in range(len(rows)):
        idx, item, onset = row_events[r][-1]
        x = assigned[(r, idx)]
        duration = event_duration_fraction(item.event)
        beat_total = sum(
            event_duration_fraction(it.event) for _, it, _ in row_events[r]
        )
        # A final dotted note ending exactly at the zone's beat total reserves
        # the dot-mark width after its step-out position (Looking-Back p4
        # y1043: 0.@b1.5 draws at 36 but the zone's last column is 45).
        if (
            item.event.kind in _CHAIN_KINDS
            and duration in _STEP_OUT_BY_DURATION
            and onset + duration == beat_total
        ):
            x += _DOT_SPAN_EXTRA
        # A closing paren (&ykh) on the zone's final event reserves one
        # dot-span unit of clearance after it (China-In-The-Lights p1 y910
        # z5: 5&ykh ends the system at b3, last column 99 instead of 90).
        if "ykh" in (item.event.decorations or ()):
            x += _DOT_SPAN_EXTRA
        zone_max_x = max(zone_max_x, x)

    if is_first:
        leading_gap = 0.0
    else:
        # A zone-start glyph needs clearance left of the first notehead: an
        # accidental mark (3.6, I-Like p1 y326 z3) or a &zkh opening paren
        # (9, China-In-The-Lights p1 y910 z5).
        leading_gap = _LEADING_GAP + (
            _ACCIDENTAL_UNIT
            if any(ev[0][1].event.accidental is not None for ev in row_events)
            else 0.0
        ) + (
            _ZKH_UNIT
            if any("zkh" in (ev[0][1].event.decorations or ()) for ev in row_events)
            else 0.0
        )
        # A meter-change barline (code like |'p:2/4') carries the new meter
        # label, which needs one extra sub-step of clearance after it: the
        # zone that follows draws at lead 43.2 instead of 25.2 (Wait-For-My-
        # Dear p1 y1253 and Wait-For-My-Dear2 p1 y1223: both barlines around
        # the temporary 2/4 measure).
        for row_index in range(len(rows)):
            barline_index = segments_by_row[row_index][ordinal - 1][-1] + 1
            if _METER_CHANGE_RE.search(
                rows[row_index][barline_index].event.code or ""
            ):
                leading_gap += _SUBSTEP
                break
    return zone_max_x, leading_gap


def compute_crossing_union_widths(
    rows: list[list[LayoutEvent]],
) -> tuple[list[tuple[float, ...]], float] | None:
    """Return (per-row interval widths, denominator) on the union grid.

    Widths are natural units between consecutive events of each row; the final
    barline is pinned separately by the projection loop.  The denominator
    already includes the trailing +18 underlined step, so the caller scales
    with k = (right - left + 14) / denominator.  Returns ``None`` when the
    system falls outside the verified shapes (no crossing paren group, or it
    carries accidentals/hidden rests that keep the legacy per-row widths).
    """
    if len(rows) != 2:
        return None
    barline_count = len(_barline_event_indices(rows[0]))
    if barline_count < 2:
        return None
    for row in rows:
        if len(_barline_event_indices(row)) != barline_count:
            return None
        if not row or row[0].event.kind not in _CROSSING_PLACED_KINDS:
            return None
        if any(item.event.accidental is not None for item in row):
            return None
        if any(item.event.kind == MusicTokenKind.HIDDEN_REST for item in row):
            return None
    if not any(_row_has_crossing_group(row) for row in rows):
        return None

    segments_by_row: list[list[list[int]]] = []
    for row in rows:
        bars = _barline_event_indices(row)
        segs: list[list[int]] = []
        start = 0
        for b in bars:
            segs.append(list(range(start, b)))
            start = b + 1
        segments_by_row.append(segs)
    assigned: dict[tuple[int, int], float] = {}
    zone_info: list[tuple[float, float]] = []
    for position, ordinal in enumerate(range(barline_count)):
        out = _model_segment_crossing(
            rows,
            segments_by_row,
            ordinal,
            is_first=(position == 0),
            assigned=assigned,
        )
        if out is None:
            return None
        zone_info.append(out)  # (last_x, leading_gap)

    widths_by_row: list[tuple[float, ...]] = []
    last_ordinal = len(zone_info) - 1
    for row_index, row in enumerate(rows):
        widths: list[float] = []
        offset = 0.0
        # The row's first note anchors at the system left edge; the final
        # barline is pinned to the right edge by the projection loop.
        previous_x: float | None = None
        for ordinal, segment in enumerate(segments_by_row[row_index]):
            if not segment:
                return None
            last_x, leading_gap = zone_info[ordinal]
            for event_index in segment:
                item = row[event_index]
                if item.event.kind not in _CROSSING_PLACED_KINDS:
                    continue
                x = assigned.get((row_index, event_index))
                if x is None:
                    return None
                x += offset + leading_gap
                if previous_x is not None:
                    widths.append(x - previous_x)
                previous_x = x
            if ordinal != last_ordinal and previous_x is not None:
                segment_end = offset + leading_gap + last_x + _TERMINAL_GAP
                widths.append(segment_end - previous_x)
                previous_x = segment_end
            offset += leading_gap + last_x + _TERMINAL_GAP
        widths_by_row.append(tuple(widths))
    total = sum(
        last_x + leading_gap + _TERMINAL_GAP for last_x, leading_gap in zone_info
    )
    return widths_by_row, total + _DENOMINATOR_EXTRA


def union_grid_repositions_events(
    legacy_widths: list[tuple[float, ...]],
    union_widths: list[tuple[float, ...]],
    *,
    scale_numerator: float,
    legacy_denominator: float,
    union_denominator: float,
) -> bool:
    """True when the union grid moves any interior event beyond float noise.

    Both grids anchor each row's first event at the left edge and pin the
    final barline to the right edge, so only the interior positions can
    differ.  When the two grids agree within the float-match tolerance the
    legacy widths are kept: they already reproduce the reference bytes for
    that system, and re-routing would only change last-ulp serialization
    noise (e.g. a trailing extension dash landing one ulp off).
    """
    if legacy_denominator <= 0 or union_denominator <= 0:
        return False
    k_legacy = scale_numerator / legacy_denominator
    k_union = scale_numerator / union_denominator
    for legacy_row, union_row in zip(legacy_widths, union_widths, strict=True):
        if len(legacy_row) != len(union_row):
            return True
        cumulative_legacy = 0.0
        cumulative_union = 0.0
        for width_legacy, width_union in zip(legacy_row, union_row, strict=True):
            cumulative_legacy += width_legacy
            cumulative_union += width_union
            if abs(
                cumulative_union * k_union - cumulative_legacy * k_legacy
            ) > _FLOAT_NOISE_LIMIT:
                return True
    return False


__all__ = ["compute_crossing_union_widths", "union_grid_repositions_events"]
