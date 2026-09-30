"""Column snapping for DSB systems whose block runs to the row's end.

When one voice carries a ``{dsb}`` block that spans from its anchor barline
to the row's final barline, the reference ghosts the block content above the
DSB row and places every other row's events in [anchor -> final] on the DSB
row's visible note columns (oracle-verified 2026-08-25 on As-Wished - Choir
p1 L47-L50, reproduced standalone with mutation probes).

Placement rule (verified on all timed events of that system): each event's
ideal position is its own beat onset mapped through the target row's
(beat -> x) table by linear interpolation; the row's events then take the
L1-optimal strictly-increasing columns against those ideals. Surplus events
beyond the target columns continue one underlined step (18 natural units)
past the last column. Extension glyphs carry their own beat onset like any
other event. Barlines at or after the anchor share the DSB row's x.

Systems whose block ends mid-row use a different alignment policy and are
left untouched, as are systems with mismatched barline counts or unsupported
event kinds inside the span.
"""

from __future__ import annotations

from fractions import Fraction
from math import inf

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_continuation_widths import dsb_continuation_context
from .dsb_gap_reserves import _barline_event_indices
from .models import SharedProjectionPlan

_DSB_SNAP_EVENT_KINDS = frozenset(
    {
        MusicTokenKind.NOTE,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.EXTENSION,
    }
)

_OVERFLOW_STEP_NATURAL_UNITS = 18.0


def _segment_beats(
    row: list[LayoutEvent], open_index: int, close_index: int
) -> list[tuple[LayoutEvent, Fraction]]:
    """Return (event, beat onset) for the timed events of one measure."""
    onsets: list[tuple[LayoutEvent, Fraction]] = []
    beat = Fraction(0)
    for item in row[open_index + 1 : close_index]:
        if item.event.kind not in _DSB_SNAP_EVENT_KINDS:
            continue
        onsets.append((item, beat))
        beat += event_duration_fraction(item.event)
    return onsets


def _interpolate(table: list[tuple[Fraction, float]], beat: Fraction) -> float:
    """Linear x for a beat through the target row's (beat, x) table."""
    if beat <= table[0][0]:
        return table[0][1]
    for (b0, x0), (b1, x1) in zip(table, table[1:], strict=False):
        if b0 <= beat <= b1:
            if b1 == b0:
                return x1
            return x0 + (x1 - x0) * float((beat - b0) / (b1 - b0))
    (b0, x0), (b1, x1) = table[-2], table[-1]
    if b1 == b0:
        return x1
    return x1 + (x1 - x0) * float((beat - b1) / (b1 - b0))


def _monotone_column_assignment(
    ideals: list[float], columns: list[float]
) -> list[int] | None:
    """Return the L1-optimal strictly-increasing column index per ideal."""
    count = len(ideals)
    width = len(columns)
    if count == 0 or width < count:
        return None
    dp: list[list[float]] = [[inf] * width for _ in range(count)]
    parent: list[list[int]] = [[-1] * width for _ in range(count)]
    for k in range(width):
        dp[0][k] = abs(ideals[0] - columns[k])
    for j in range(1, count):
        for k in range(j, width):
            best = inf
            best_k = -1
            for previous in range(j - 1, k):
                if dp[j - 1][previous] < best:
                    best = dp[j - 1][previous]
                    best_k = previous
            if best_k < 0:
                continue
            dp[j][k] = best + abs(ideals[j] - columns[k])
            parent[j][k] = best_k
    last = min(range(count - 1, width), key=lambda k: dp[count - 1][k])
    if dp[count - 1][last] == inf:
        return None
    assignment = [0] * count
    column = last
    for j in range(count - 1, -1, -1):
        assignment[j] = column
        column = parent[j][column]
    return assignment


def _assign_columns(
    onsets: list[tuple[LayoutEvent, Fraction]],
    table: list[tuple[Fraction, float]],
    scale: float,
) -> bool:
    """Snap each event onto an L1-optimal target column for its beat onset."""
    columns = [x for _, x in table]
    surplus = len(onsets) - len(columns)
    if surplus > 0:
        columns += [
            columns[-1] + _OVERFLOW_STEP_NATURAL_UNITS * scale * step
            for step in range(1, surplus + 1)
        ]
    assignment = _monotone_column_assignment(
        [_interpolate(table, beat) for _, beat in onsets], columns
    )
    if assignment is None:
        return False
    for (item, _), column_index in zip(onsets, assignment, strict=True):
        item.x = columns[column_index]
    return True


def snap_dsb_continuation_columns(plan: SharedProjectionPlan) -> None:
    """Snap sibling rows' DSB-span columns onto the DSB row's visible x."""
    rows = plan.request.rows
    context = dsb_continuation_context(rows)
    if context is None:
        return
    authority_index, anchor_ordinal = context
    authority = rows[authority_index]
    authority_barlines = _barline_event_indices(authority)
    scale = plan.scale
    for row in rows:
        if row is authority:
            continue
        barlines = _barline_event_indices(row)
        if len(barlines) != len(authority_barlines):
            return
        for close_ordinal in range(anchor_ordinal, len(authority_barlines)):
            open_index = barlines[close_ordinal - 1] if close_ordinal > 0 else 0
            close_index = barlines[close_ordinal]
            auth_open = (
                authority_barlines[close_ordinal - 1] if close_ordinal > 0 else 0
            )
            auth_close = authority_barlines[close_ordinal]
            row[close_index].x = authority[auth_close].x
            table = [
                (beat, item.x)
                for item, beat in _segment_beats(authority, auth_open, auth_close)
            ]
            onsets = _segment_beats(row, open_index, close_index)
            if not table or not onsets:
                continue
            if len(onsets) != len(row[open_index + 1 : close_index]):
                return
            if not _assign_columns(onsets, table, scale):
                return


__all__ = ["snap_dsb_continuation_columns"]
