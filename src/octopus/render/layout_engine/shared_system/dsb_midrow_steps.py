"""Step-width rules for mid-row DSB union-grid zones.

The mid-row grid shares the trailing architecture but measures each row's
steps differently (2026-08-26, As-Wished - Choir p3 systems 1 and 2 probe
matrices): rows measure from their own previous position, integer beats are
shared columns every row snaps up to while sub-beat plain events keep their
own chain and dotted continuations keep their own ideal, pair-start and
dotted-note destinations reserve 3.6 on integer steps (dotted starts force
the integer base width at sub-beat onsets), a pair close steps by its own
duration class plus 3.6 on an integer beat when the zone opens with an
accidental and still continues, and a row's own accidental reserves 3.6 on
its very next step when that step lands on an integer beat.
"""

from __future__ import annotations

from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import MusicEvent
from ..hidden.hidden_streams import event_duration_fraction
from .dsb_union_common import (
    _ACCIDENTAL_UNIT,
    _INTEGER_STEP,
    _STEP_OUT_BY_DURATION,
    _SUBSTEP,
    _base_step,
)


def _is_dotted(event: MusicEvent) -> bool:
    return "." in (event.code or "")


def _is_pair_start(code: str | None) -> bool:
    return code is not None and "(" in code and ")" not in code


def _is_pair_close(previous_code: str | None, code: str | None) -> bool:
    return (
        code is not None
        and ")" in code
        and "(" not in code
        and previous_code is not None
        and "(" in previous_code
    )


def _midrow_gap_step(
    previous_onset: Fraction,
    onset: Fraction,
    previous_event: MusicEvent,
    event: MusicEvent,
    *,
    union_onsets: list[Fraction],
    last_onset: Fraction,
    leading_accidental: bool,
    debt_fires: bool = False,
) -> float:
    """Step width of one mid-row row between two of its own onsets."""
    base = _base_step(onset)
    if _is_dotted(event) and onset.denominator > 1:
        # A dotted start reserves the integer width even at a sub-beat
        # onset (probe H/K: 4.@b2.5 steps 27 from b2).
        base = _INTEGER_STEP
    if _is_pair_close(previous_event.code, event.code):
        # A pair close advances by its own duration class regardless of
        # the destination onset (probe J: eighth close at b3.5 steps 27;
        # target Z4: sixteenth close at b1.75 steps 18).
        base = (
            _INTEGER_STEP
            if event_duration_fraction(event) >= Fraction(1, 2)
            else _SUBSTEP
        )
    step = base + sum(
        _base_step(u)
        for u in union_onsets
        if previous_onset < u < onset and u.denominator <= 2
    )
    if event.accidental is not None:
        step += _ACCIDENTAL_UNIT
    if onset.denominator == 1 and (
        _is_pair_start(event.code)
        or (
            _is_dotted(event)
            and event.kind is not MusicTokenKind.REST
            and ")" not in (event.code or "")
        )
    ):
        # Pair starts and dotted notes reserve the accidental unit on integer
        # steps (system 1 Z5: 7.@b2 makes all four rows step 30.6).  Dotted
        # rests and dotted pair closes do not (system 2 Z1/Z2: 0/. at b1/b3
        # and the dotted close of (1// 1/.) keep the plain 27).
        step += _ACCIDENTAL_UNIT
    if (
        _is_pair_close(previous_event.code, event.code)
        and onset.denominator == 1
        and onset < last_onset
        and leading_accidental
    ):
        # A pair close on an integer beat reserves the unit when the zone
        # opens with an accidental and still continues (target Z4 b1 steps
        # 30.6; probe PC1 without the leading $ steps 27; target Z3 has no
        # accidental and its b3 closes step 27).
        step += _ACCIDENTAL_UNIT
    if debt_fires:
        # A row's own accidental reserves the unit on its very next step
        # when that step lands on an integer beat (target Z0: 5#@b0 makes
        # b1 land at 30.6; target Z4: $,,.@b0 expires on the sub-beat b1.5
        # and leaves b2 at 115.2).
        step += _ACCIDENTAL_UNIT
    return step


def _midrow_continuation_ideal(
    previous_x: float,
    previous_onset: Fraction,
    onset: Fraction,
    duration: Fraction,
    *,
    first_onset: Fraction,
    union_onsets: list[Fraction],
    leading_accidental: bool,
) -> float:
    """Ideal x for a dotted continuation at its destination onset.

    A zone-leading dotted note also proposes the full interior sum, plus the
    accidental unit when the zone opens with an accidental (target Z4: 4.@b0
    -> b1.5 at 66.6 = 63 + 3.6; probe PC1 without the leading $ keeps 63;
    probe N keeps the fixed 36 when no interior onsets exist).
    """
    ideal = previous_x + _STEP_OUT_BY_DURATION[duration]
    if previous_onset == first_onset:
        sum_ideal = previous_x + sum(
            _base_step(u) for u in union_onsets if first_onset < u < onset
        )
        if leading_accidental:
            sum_ideal += _ACCIDENTAL_UNIT
        ideal = max(ideal, sum_ideal)
    return ideal
