"""Shared-grid widths for multi-block DSB continuation systems.

Hulunbuir-Grassland p3/p4 systems carry several ``{dsb}`` blocks at once;
their visible rows lay on a shared measure-column grid the trailing/mid-row
models do not cover.  Oracle-verified architecture (HANDOFF.md "Multi-block
DSB shared-grid decode"): one column per measure position (G = the blockless
rows' measure count); content-space width ``W'_c = max_row(row lead + last
relative position) + closer_c`` (rows whose first measure is hidden-origin
carry no lead of their own), ``D = sum(W')``, scale ``(right - left + 14) / D``
(mid_row=False, final barline pinned at right); per-row sequential chains with
integer-onset snapping and pair closes at ``max(start + own gap, shared
floor-integer)``; zone lead 39.6u iff >=2 blocks touch a column or a
multi-measure block starts there, plus 3.6 accidental addends on zone-start
columns.  Block content is
not part of the row: it lives in the hidden stream and is projected
separately.  Zone key-signature change marks are modeled: a system carrying
&zkh seats column 0 at a 9u lead with 36u integer-onset steps (the hook span
of Hulunbuir [84] is exactly its pickup column), and &ykh widens the closer
of the column holding it by 9u.  Returns None outside this verified cohort
(legacy widths).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_multiblock_rows import (
    _column_map,
    _Measure,
    _row_measures,
)

_LEAD = 25.2
_ZONE_LEAD_EXTRA = 14.4
_ACCIDENTAL_ADDEND = 3.6
_CLOSER = 25.2
# A multi-measure block ending mid-system with no other block starting in the
# same column keeps a single widened closer (Hulunbuir [84] c3: n=3 -> 43.2);
# co-located starts widen per measure instead ([100] c3: n=3 -> 54).
_BLOCK_END_SOLO = 43.2
# A one-measure block column reserves one zone extra after its content
# (Hulunbuir [84] c4: {dsb 2 - } -> closer 39.6).
_SINGLE_BLOCK_CLOSER = 39.6
# &zkh hook span: column-0 lead and integer-onset step (Hulunbuir [84]:
# pickup chain [9, 27, 63, 81] vs the plain [0, 18, 45, 63]).
_HOOK_LEAD = 9.0
# Acceptance-level float tolerance (REF comparison family; not GEOMETRY_EPSILON).
_FLOAT_NOISE_LIMIT = 1e-6
_HOOK_INTEGER_STEP = 36.0
# &ykh trailing reserve on the closer of the column holding the mark.
_YKH_CLOSER_EXTRA = 9.0
_TERMINAL_REGION = 43.2
# Leading-barline systems shrink the pinned terminal region by half a
# substep (oracle-verified on Hulunbuir [92]: 41.4u, D = 833.4).
_TERMINAL_REGION_LEADING = 41.4
_LONG_SOURCE = Fraction(3, 4)


def is_zkh_hook_system(rows: list[list[LayoutEvent]]) -> bool:
    """True when the system carries ``&zkh`` on any token of any row.

    Oracle probe Z3 (``tools/probes/hb84_zkh.py``): the hook effects are
    system-level — moving the marks onto another row's pickup leaves the
    geometry unchanged — so the scan deliberately covers every token, not
    just notes.  Hulunbuir [84] is the corpus instance.
    """
    return any("&zkh" in (item.event.code or "") for row in rows for item in row)


def hook_grid_rejected(
    dsb_union_widths: object,
    rows: list[list[LayoutEvent]],
    scale: float,
    shared_anchor_offset: float,
) -> bool:
    """Whether a zkh hook system's anchor offset misses the column-0 lead.

    The multi-block hook model seats column 0 at _HOOK_LEAD natural units;
    the projection's mixed-origin first-interval/2 formula must land on it
    exactly (Hulunbuir [84]: 18u / 2 = 9u).  When it does not, callers fall
    back to the legacy widths so a mis-anchored column grid is never
    projected.
    """
    if dsb_union_widths is None or not is_zkh_hook_system(rows):
        return False
    return abs(shared_anchor_offset / scale - _HOOK_LEAD) > _FLOAT_NOISE_LIMIT


def _base_step(delta: Fraction, dest_integer: bool) -> float:
    if dest_integer:
        return 27.0
    if delta <= Fraction(1, 2):
        return 18.0
    if delta <= 1:
        return 27.0
    return 54.0


def _chain_step(
    previous_onset: Fraction,
    onset: Fraction,
    previous_event: LayoutEvent,
    event: LayoutEvent,
    *,
    hook_integer: bool = False,
) -> float:
    """Sequential step of one row's chain between two consecutive events."""
    dest_integer = onset.denominator == 1
    base = _base_step(onset - previous_onset, dest_integer)
    if hook_integer and dest_integer:
        # Inside the &zkh hook span the step into an integer onset takes the
        # quarter-class width ([84] c0: 3/ -> 5/ steps 36, not 27).
        base = max(base, _HOOK_INTEGER_STEP)
    duration = event_duration_fraction(event.event)
    # Sixteenth and eighth destinations keep the substep; longer notes force
    # the integer-class width (c5: 5/ -> 3'/ at b1.5 steps 18).
    dest_class = 18.0 if duration <= Fraction(1, 2) else 27.0
    step = max(base, dest_class)
    if (
        not dest_integer
        and (event.event.code or "").find("(") != -1
        and event_duration_fraction(previous_event.event) >= 1
    ):
        # A pair opening on a sub-beat onset after a full-beat note reserves
        # the integer-class width ([108] c7: 2' -> 5(// steps 27); after a
        # shorter note the chain spacing suffices ([100] c4/c5 keep 18).
        step = max(step, 27.0)
    if event.event.accidental is not None:
        # A mid-measure accidental widens its step by one reserve; the shared
        # beat position carries the shift to every row snapping in ([100] c3).
        step += _ACCIDENTAL_ADDEND
    return step


def _pair_close_gap(previous_event: LayoutEvent) -> float:
    """Natural gap of a pair close from its pair start, by source duration.

    The gap takes the opening element's duration class, not the close's: [92]
    c1 closes (1'. 3/) sit at lead + 36 although the close is an eighth; short
    sources keep the substep ([92] c0: 6(/ 3'/) closes at +18).
    """
    duration = event_duration_fraction(previous_event.event)
    if duration <= Fraction(1, 2):
        return 18.0
    if duration < Fraction(3, 2):
        return 27.0
    return 36.0


def _is_pair_close(previous: LayoutEvent, event: LayoutEvent) -> bool:
    code = event.event.code or ""
    previous_code = previous.event.code or ""
    return ")" in code and "(" not in code and "(" in previous_code


def _quantize_unit(value: float) -> float | None:
    """Snap a natural-unit coordinate onto the model's 0.9u grid.

    Every step, lead, and closer constant is an exact multiple of 0.9u, so
    snapping removes float accumulation noise before the shared projection
    re-summation.  Returns None when off-grid by more than float noise.
    """
    source = Decimal(repr(value))
    units = (source / Decimal("0.9")).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if abs(source - units * Decimal("0.9")) > Decimal("0.05"):
        return None
    return float(units * Decimal("0.9"))


def _column_closer(
    col: int,
    grid_cols: int,
    leading_system: bool,
    block_end_n: int,
    co_located_start: bool,
) -> float:
    """Terminal clearance after a column's content (natural units)."""
    # The standard closer everywhere except the final column, whose barline
    # is pinned to the right edge (the wide region absorbs the +14u overhang;
    # a leading barline shrinks it to 41.4u).  A multi-measure block ending
    # mid-system widens the closer by one zone extra per measure beyond the
    # first when another block starts in the same column (Hulunbuir [100] c3:
    # n=3 -> 54; oracle ExpC col3: n=2 -> 39.6); alone it keeps a single
    # widened closer ([84] c3: n=3 -> 43.2).  A one-measure block column
    # reserves one zone extra ([84] c4 -> 39.6).
    if col == grid_cols - 1:
        return _TERMINAL_REGION_LEADING if leading_system else _TERMINAL_REGION
    if block_end_n >= 2:
        if co_located_start:
            return _CLOSER + _ZONE_LEAD_EXTRA * (block_end_n - 1)
        return _BLOCK_END_SOLO
    if block_end_n == 1:
        return _SINGLE_BLOCK_CLOSER
    return _CLOSER


def _map_voices_to_columns(
    rows: list[list[LayoutEvent]],
    measures_by_row: list[list[_Measure]],
    pres: list[int],
    dsb_lengths: list[int],
    anchoreds: list[bool],
) -> tuple[int, list[tuple[int, int, int]]] | None:
    """Group rows into voices and map every measure onto a grid column.

    A voice may occupy several visual rows (a main row plus stacked
    continuation rows) sharing one measure sequence; line groups must be
    contiguous in system order.  Returns (grid_cols, block_ranges), or None
    outside the verified cohort: systems must carry {dsb} blocks (>=2 anchored
    voices, or one voice with a multi-measure block), and the grid width comes
    from the blockless voices, which must span the whole grid.
    """
    voices: list[list[int]] = []
    for row_index, row in enumerate(rows):
        if voices and rows[voices[-1][0]][0].line == row[0].line:
            voices[-1].append(row_index)
        else:
            voices.append([row_index])
    anchored_voices = [voice for voice in voices if any(anchoreds[i] for i in voice)]
    max_block = max([dsb_lengths[i] for i in range(len(rows))] + [0])
    if len(anchored_voices) < 2 and max_block < 2:
        return None
    blockless = [voice for voice in voices if not any(anchoreds[i] for i in voice)]
    if not blockless:
        return None
    grid_cols = max(len(measures_by_row[voice[0]]) for voice in blockless)

    # Block column ranges per voice (for zone-lead / closer rules).
    block_ranges: list[tuple[int, int, int]] = []  # (start_col, end_col, n)
    for voice in voices:
        main = next((i for i in voice if anchoreds[i]), voice[0])
        conts = [i for i in voice if i != main]
        if not anchoreds[main]:
            # A blockless voice may not carry stacked continuation rows.
            if conts or len(measures_by_row[main]) != grid_cols:
                return None
            if not _column_map(measures_by_row[main], 0, 0, grid_cols):
                return None
            continue
        pre = pres[main]
        in_row = dsb_lengths[main]
        # A main row ending at its anchor has a block running to the end of
        # the grid; its post-block measures arrive on continuation rows.
        n_dsb = in_row if in_row > 0 else grid_cols - pre
        if pre + n_dsb > grid_cols:
            return None
        main_measures = measures_by_row[main]
        for position, measure in enumerate(main_measures):
            measure.col = position
        cont_measures = [m for i in conts for m in measures_by_row[i]]
        if pre + in_row + len(cont_measures) > grid_cols:
            return None
        for offset, measure in enumerate(cont_measures):
            measure.col = pre + in_row + offset
            measure.fragment = "continuation"
        block_ranges.append((pre, pre + n_dsb - 1, n_dsb))
    return grid_cols, block_ranges


def _last_content(measure: _Measure) -> LayoutEvent:
    """The measure's last placed glyph (hidden rests never widen columns)."""
    for item in reversed(measure.events):
        if item.event.kind != MusicTokenKind.HIDDEN_REST:
            return item
    return measure.events[-1]


def _column_positions(
    col: int,
    grid_cols: int,
    rows: list[list[LayoutEvent]],
    measures_by_row: list[list[_Measure]],
    block_ranges: list[tuple[int, int, int]],
    leading_system: bool,
    hook_system: bool,
    hidden_origin_measures: set[int],
    cum_by_id: dict[int, float],
    position_of: dict[int, int],
    rows_by_measure: dict[int, list[LayoutEvent]],
    column_bounds: list[float],  # extended in place with the new boundary
) -> float | None:
    """Final event positions and the width of one grid column; None on error."""
    per_row = [
        next((m for m in measures if m.col == col), None) for measures in measures_by_row
    ]
    main_measures = [m for m in per_row if m is not None and m.fragment is None]
    if not main_measures:
        return None
    # Zone lead: >=2 blocks touch the column or a multi-measure block starts
    # there; column 0 of note-anchored systems never carries a lead (rows
    # start on a note at the origin); the final column never takes it.
    touching = [b for b in block_ranges if b[0] <= col <= b[1]]
    zone_lead = col != grid_cols - 1 and (
        len(touching) >= 2 or any(b[2] >= 2 and b[0] == col for b in block_ranges)
    )
    accidental_zone_start = any(
        m.events[0].event.accidental is not None for m in per_row if m
    )
    lead_extra = _ZONE_LEAD_EXTRA if zone_lead else 0.0
    if col == 0 and not leading_system:
        # The &zkh hook opens the system: every row's first events sit one
        # substep past the origin ([84] c0: notes and rests alike at 9u).
        base_lead = _HOOK_LEAD if hook_system else 0.0
    else:
        base_lead = _LEAD + lead_extra
    accidental = accidental_zone_start and base_lead > 0
    main_lead = base_lead + (_ACCIDENTAL_ADDEND if accidental else 0.0)
    # Phase 1: raw sequential chains per row (no snapping yet).
    chains: list[list[float] | None] = [None] * len(rows)
    for row_index, measure in enumerate(per_row):
        if measure is None:
            continue
        chain = [0.0]
        for index in range(1, len(measure.events)):
            previous = measure.events[index - 1]
            event = measure.events[index]
            onset = measure.onsets[index]
            if _is_pair_close(previous, event):
                step = _pair_close_gap(previous)
            else:
                step = _chain_step(
                    measure.onsets[index - 1],
                    onset,
                    previous,
                    event,
                    hook_integer=hook_system and col == 0,
                )
            chain.append(chain[index - 1] + step)
        chains[row_index] = chain
    # A zone-start accidental shifts the lead by one unit and reserves another
    # on every later position (c4: 2' - dash at 30.6 beyond the shifted lead).
    main_shift = _ACCIDENTAL_ADDEND if accidental else 0.0

    # Phase 2: shared integer-beat positions from the main rows.
    shared_int: dict[Fraction, float] = {}
    for row_index, measure in enumerate(per_row):
        row_chain = chains[row_index]
        if measure is None or row_chain is None:
            continue
        if measure.fragment is not None:
            # A stacked fragment contributes to the shared grid only via its
            # mid-measure accidentals ([100] c3: the fragment's 4# pushes b1
            # to lead + 48.6 and every row snapping in follows).
            for index, onset in enumerate(measure.onsets):
                if index == 0 or onset.denominator != 1:
                    continue
                if measure.events[index].event.accidental is None:
                    continue
                absolute = main_lead + row_chain[index] + main_shift
                if absolute > shared_int.get(onset, float("-inf")):
                    shared_int[onset] = absolute
            continue
        row_lead = 0.0 if id(measure) in hidden_origin_measures else main_lead
        for index, onset in enumerate(measure.onsets):
            if onset.denominator != 1:
                continue
            absolute = row_lead + row_chain[index] + main_shift
            if absolute > shared_int.get(onset, float("-inf")):
                shared_int[onset] = absolute
        # A long-source pair close reserves its natural position at the floor
        # integer beat ([92] c1; short sources reserve nothing, [92] c0).
        for index in range(1, len(measure.events)):
            previous = measure.events[index - 1]
            if not _is_pair_close(previous, measure.events[index]):
                continue
            if event_duration_fraction(previous.event) < _LONG_SOURCE:
                continue
            close_position = (
                row_lead
                + row_chain[index - 1]
                + (main_shift if index - 1 > 0 else 0.0)
                + _pair_close_gap(previous)
            )
            floor_onset = Fraction(
                measure.onsets[index].numerator // measure.onsets[index].denominator
            )
            if close_position > shared_int.get(floor_onset, float("-inf")):
                shared_int[floor_onset] = close_position

    # Phase 3: final positions with integer-beat snapping.
    for row_index, measure in enumerate(per_row):
        row_chain = chains[row_index]
        if measure is None or row_chain is None:
            continue
        lead = 0.0 if id(measure) in hidden_origin_measures else main_lead
        shift = main_shift
        positions: list[float] = []
        for index, event in enumerate(measure.events):
            onset = measure.onsets[index]
            if index == 0:
                position = lead
            elif event.event.kind == MusicTokenKind.HIDDEN_REST and index > 0:
                # Trailing hidden rest: one plain substep after the previous
                # glyph (Hulunbuir [100] c3: the null after 4#).
                position = positions[index - 1] + 18.0
            elif _is_pair_close(measure.events[index - 1], event):
                # The close advances from the pair's opening element by its
                # source duration-class gap, snapping up to the shared floor-
                # integer position when that is further.
                floor_onset = Fraction(onset.numerator // onset.denominator)
                position = max(
                    positions[index - 1] + _pair_close_gap(measure.events[index - 1]),
                    shared_int.get(floor_onset, float("-inf")),
                )
            else:
                position = lead + row_chain[index] + shift
                if onset.denominator == 1 or event.event.kind == MusicTokenKind.EXTENSION:
                    snap = shared_int.get(onset, float("-inf"))
                    if snap > position:
                        position = snap
            positions.append(position)
            cum_by_id[id(event)] = column_bounds[col] + position
    # Stacked fragments follow the same lead and can set the column's span
    # (c2: the block fragment's pair close reaches further than main rows).
    # Each row's last position already includes its own lead (zero for
    # hidden-origin measures), so the span is the plain maximum over rows.
    max_last = max(
        cum_by_id[id(_last_content(m))] - column_bounds[col]
        for m in per_row
        if m is not None
    )
    # Any block ending here counts (a one-measure block column still widens
    # its closer); a start in the same column switches multi-measure ends to
    # the per-measure widening ([100] c3 vs [84] c3).
    block_end_n = max([b[2] for b in block_ranges if b[1] == col], default=0)
    co_located_start = any(b[0] == col for b in block_ranges)
    closer = _column_closer(col, grid_cols, leading_system, block_end_n, co_located_start)
    # The &ykh hook closes its span here: one substep of trailing reserve.
    if any(
        "&ykh" in (event.event.code or "")
        for measure in per_row
        if measure is not None
        for event in measure.events
    ):
        closer += _YKH_CLOSER_EXTRA
    column_width = _quantize_unit(max_last + closer)
    if column_width is None:
        return None
    column_bounds.append(column_bounds[-1] + column_width)
    # The barline closing each row's measure sits at the column boundary.
    for measure in per_row:
        if measure is None:
            continue
        next_index = position_of[id(measure.events[-1])] + 1
        row_items = rows_by_measure[id(measure)]
        if next_index < len(row_items) and (
            row_items[next_index].event.kind == MusicTokenKind.BARLINE
        ):
            cum_by_id[id(row_items[next_index])] = column_bounds[col + 1]
    return column_width


def compute_dsb_multiblock_widths(
    rows: list[list[LayoutEvent]],
) -> tuple[list[tuple[float, ...]], float, bool] | None:
    """Per-row interval widths + denominator on the multi-block shared grid."""
    # Zone key-signature change marks: &zkh opens the hook (column-0 lead and
    # integer-onset steps), &ykh closes it (closer reserve); see
    # _column_positions.  Hulunbuir [84] is the corpus instance.
    hook_system = is_zkh_hook_system(rows)
    parsed = [_row_measures(row) for row in rows]
    if any(item is None for item in parsed):
        return None
    measures_by_row, pres, dsb_lengths, anchoreds, leadings = zip(*parsed, strict=True)
    leading_system = any(leadings)
    # The measure holding a row-leading hidden rest (``8``): the null glyph
    # sits at the column origin and the visible content chains from there, so
    # only that measure contributes no lead of its own (Hulunbuir [100]).
    hidden_origin_measures = {
        id(ms[0]) for row, ms in zip(rows, measures_by_row, strict=True)
        if row[0].event.kind == MusicTokenKind.HIDDEN_REST and ms
    }

    mapped = _map_voices_to_columns(rows, measures_by_row, pres, dsb_lengths, anchoreds)
    if mapped is None:
        return None
    grid_cols, block_ranges = mapped
    cum_by_id: dict[int, float] = {}
    position_of = {id(i): p for row in rows for p, i in enumerate(row)}
    rows_by_measure = {
        id(m): row for row, ms in zip(rows, measures_by_row, strict=True) for m in ms
    }
    denominator = 0.0
    column_bounds: list[float] = [0.0]
    for col in range(grid_cols):
        column_width = _column_positions(
            col, grid_cols, rows, measures_by_row, block_ranges, leading_system,
            hook_system, hidden_origin_measures, cum_by_id, position_of,
            rows_by_measure, column_bounds,
        )
        if column_width is None:
            return None
        denominator += column_width

    # A leading barline sits at the origin; its row's first interval then
    # carries the column-0 lead up to the first note.  Every position is also
    # re-snapped so the per-row interval widths carry no float noise.
    for row_index, row in enumerate(rows):
        if leadings[row_index]:
            cum_by_id[id(row[0])] = 0.0
    for key, value in list(cum_by_id.items()):
        snapped = _quantize_unit(value)
        if snapped is None:
            return None
        cum_by_id[key] = snapped
    widths_by_row: list[tuple[float, ...]] = []
    for row in rows:
        # Widths are the pure intervals between consecutive events; row[0]
        # sits at its own (possibly hook-leaded) position and the projection
        # places it via the shared anchor offset.
        widths: list[float] = []
        previous = cum_by_id[id(row[0])]
        for item in row[1:]:
            cum = cum_by_id.get(id(item))
            if cum is None or cum < previous - GEOMETRY_EPSILON:
                return None
            widths.append(cum - previous)
            previous = cum
        widths_by_row.append(tuple(widths))
    return widths_by_row, denominator, False


__all__ = ["compute_dsb_multiblock_widths", "is_zkh_hook_system"]
