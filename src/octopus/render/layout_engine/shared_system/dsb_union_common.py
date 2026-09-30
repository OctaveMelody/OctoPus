"""Shared constants and helpers for the DSB union note-group column grid.

The trailing (block runs to the row's final barline) and mid-row (block ends
earlier) shapes both lay their systems on a union of beat-onset columns; this
module holds the width units, event-kind sets, small step helpers, and the
OnsetMaxTracker accumulator they share.

DSB policy index (item 50 — where to look when DSB behavior needs rework):

Foundation
  dsb_union_common      width units, event-kind sets, step helpers, OnsetMaxTracker
  dsb_gap_reserves      barline-gap widening for every row of a system that contains
                        a {dsb} block (imported by nearly all other passes)

Shape-specific width passes (one REF-decoded shape each)
  dsb_trailing_widths   block runs anchor → final barline
  dsb_midrow_steps      mid-row step measurement (feeds the widths pass)
  dsb_midrow_widths     block closes before the final barline
  dsb_multiblock_rows   multi-block systems: row/measure splitting + continuation stacks
  dsb_multiblock_widths multi-block shared measure-column grid (+ hook_grid_rejected gate)

Continuation layer (visible rows around a voice's {dsb} block)
  dsb_continuation_widths shared beat-onset column grid for the visible rows
  dsb_continuation_snap   ghosts block content spanning the final barline; snaps columns

Call order in projection: trailing-dsb sustain reserve → gap reserves →
``compute_dsb_continuation_widths`` (dispatches to the trailing / mid-row / multi-block
shape passes above) → ``hook_grid_rejected`` gate (multi-block hook anchor check; a
divergent offset keeps legacy widths) → … → ``snap_dsb_continuation_columns``. Each
module's docstring cites its oracle probe record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON

_INTEGER_STEP = 27.0
_SUBSTEP = 18.0
_ACCIDENTAL_UNIT = 3.6
_DOT_SPAN_EXTRA = 9.0
_STEP_OUT_BY_DURATION = {Fraction(3, 4): 27.0, Fraction(3, 2): 36.0}
_TERMINAL_GAP = 25.2
_LEADING_GAP = 25.2
_DSB_ZONE_GAP = 39.6
_DENOMINATOR_EXTRA = 18.0

_CHAIN_KINDS = frozenset(
    {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE, MusicTokenKind.REST}
)
_PLACED_KINDS = _CHAIN_KINDS | frozenset({MusicTokenKind.EXTENSION})



@dataclass(slots=True)
class OnsetMaxTracker:
    """Per-onset max accumulator for the DSB union column grid.

    Shared by the mid-row and trailing width passes: each onset's note
    candidates are recorded with their direct/binding flags, and the three
    maxima plus the candidate list feed the column decision.
    """

    candidates: list[float] = field(default_factory=list)
    direct_max: float | None = None
    bound_max: float | None = None
    non_direct_max: float | None = None

    def note(self, candidate: float, *, direct: bool = False, binding: bool = False) -> None:
        self.candidates.append(candidate)
        if direct:
            self.direct_max = (
                candidate if self.direct_max is None else max(self.direct_max, candidate)
            )
        else:
            self.non_direct_max = (
                candidate
                if self.non_direct_max is None
                else max(self.non_direct_max, candidate)
            )
        if binding:
            self.bound_max = candidate if self.bound_max is None else max(self.bound_max, candidate)


def _base_step(onset: Fraction) -> float:
    return _INTEGER_STEP if onset.denominator == 1 else _SUBSTEP


def _is_pair(code: str | None) -> bool:
    return code is not None and ("(" in code or ")" in code)


def _ceiling_slot_after(slots: list[float], previous_x: float, ideal: float) -> float:
    """Return the first column at or after the row's own ideal position.

    Rows never fall behind their sequential chain: an event whose ideal lies
    between two shared columns takes the next column up (oracle-verified
    2026-08-25 on As-Wished p2 zone Q3 b3, ideal 135 taking column 153,
    and p1 m19 Q4 b3.5, ideal 153 taking column 153 below the shared 180).
    """
    for slot in slots:
        if slot >= ideal - GEOMETRY_EPSILON and slot > previous_x - GEOMETRY_EPSILON:
            return slot
    return slots[-1]


__all__ = [
    "_ACCIDENTAL_UNIT",
    "_CHAIN_KINDS",
    "_DENOMINATOR_EXTRA",
    "_DOT_SPAN_EXTRA",
    "_DSB_ZONE_GAP",
    "_INTEGER_STEP",
    "_LEADING_GAP",
    "_PLACED_KINDS",
    "_STEP_OUT_BY_DURATION",
    "_SUBSTEP",
    "_TERMINAL_GAP",
    "_base_step",
    "_ceiling_slot_after",
    "_is_pair",
]
