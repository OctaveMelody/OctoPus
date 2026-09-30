"""Shared-column gap reserves for systems containing DSB blocks.

The reference layout widens specific barline gaps in every row of a system that
contains a ``{dsb ...}`` block (verified by oracle probes on standalone systems
and against the Hulunbuir-Grassland corpus pages; see docs/SLICE_HISTORY.md,
workstream B0-3a12):

* the barline immediately before a multi-measure block reserves 55 natural
  units to the next note in every row (35 + 20 for the ``dakuohu_zuo`` brace);
* the barline closing the block span reserves 60 natural units from the last
  note in non-block rows (35 + 25 for the ``dakuohu_you`` brace; the reference
  varies per row — e.g. Hulunbuir p3 System A measures 60/85/25 across its
  four rows — so 60 is the validated common target, see plan B0-3a12 slice 3),
  and the step out of that measure's first closed parenthetical pair is one
  extra underlined step wide (42.5 instead of 37.5);
* the barline closing a measure that carries an inline ``{dsb ...}`` reserves
  55 natural units from its last note in every row (35 + 20).

The projection stretches each row to fill [left, right] with a shared scale
derived from the reconciled widths plus per-profile terminal terms, and the
last interval is a filler. Because the denominator already matches the
reference total for these systems, the reserves are added to the reconciled
interval widths and subtracted from the same row's ``denominator_adjustment``
so the shared scale (and every unrelated gap) is left untouched while the
terminal filler shrinks by exactly the reserved amount.

Ordering matters: this must run after the family-specific boundary
clearances that reserve the same anchor gap for other DSB cohorts (the
second-ending continuation reserve in ``apply_terminal_reserve_policies`` and
the trailing-sustain reserve in ``apply_trailing_dsb_sustain_reserve``). The
``max()`` semantics then leave already-reserved gaps untouched, so the call
lives in ``build_shared_projection_plan`` right after the trailing-sustain
reserve.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..profiles import LegacyIntrinsicProfile

# Reconciled widths use legacy intrinsic units (one underlined step = 18.0).
# Reference targets in grid units (underlined step = 25) converted at 18/25.
DSB_BLOCK_START_AFTER_GAP = 39.6  # 55 grid units
DSB_BLOCK_END_BEFORE_GAP = 43.2  # 60 grid units
DSB_PAIR_EXIT_STEP = 30.6  # 42.5 grid units
DSB_INLINE_CLOSE_BEFORE_GAP = 39.6  # 55 grid units
TWO_OWNER_DSB_PRE_ANCHOR_TRANSFER = 9.0
TWO_OWNER_DSB_POST_ANCHOR_RESERVE = 14.4


@dataclass(frozen=True, slots=True)
class TwoOwnerTrailingDsbTopology:
    """The verified lower-row, same-anchor trailing-DSB topology."""

    anchor_index: int
    anchor_ordinal: int
    owner_indices: tuple[int, int]


def _barline_event_indices(row: list[LayoutEvent]) -> list[int]:
    return [
        index
        for index, item in enumerate(row)
        if item.event.kind == MusicTokenKind.BARLINE
    ]


def two_owner_trailing_dsb_topology(
    rows: list[list[LayoutEvent]],
) -> TwoOwnerTrailingDsbTopology | None:
    """Identify the c10 two-owner trailing DSB boundary.

    This is deliberately a structural admission rule.  It requires four
    common-origin rows, five visible barlines, and exactly two lower-row DSB
    owners.  Both owners start at the third visible barline and continue with
    exactly two generated tail barlines through the row ending.  The rule is
    distinct from the one-owner gap reserve because two synchronized owners
    share the post-anchor boundary.
    """

    if len(rows) != 4 or any(not row for row in rows):
        return None
    if len({row[0].x for row in rows}) != 1:
        return None
    barlines_by_row = [_barline_event_indices(row) for row in rows]
    if any(len(barlines) != 5 for barlines in barlines_by_row):
        return None

    owners: list[int] = []
    anchor_indices: list[int] = []
    anchor_ordinals: list[int] = []
    for row_index, (row, barlines) in enumerate(zip(rows, barlines_by_row, strict=True)):
        anchors = [
            ordinal
            for ordinal, event_index in enumerate(barlines)
            if "&dsb_a" in (row[event_index].event.code or "")
        ]
        if not anchors:
            continue
        if len(anchors) != 1:
            return None
        anchor_ordinal = anchors[0]
        anchor_index = barlines[anchor_ordinal]
        trailing_barlines = barlines[anchor_ordinal + 1 :]
        if (
            anchor_ordinal != 2
            or len(trailing_barlines) != 2
            or row[-1].event.kind != MusicTokenKind.BARLINE
            or any(row[index].block != "dsb-tail" for index in trailing_barlines)
            or trailing_barlines[-1] != len(row) - 1
        ):
            return None
        owners.append(row_index)
        anchor_indices.append(anchor_index)
        anchor_ordinals.append(anchor_ordinal)

    if (
        tuple(owners) != (2, 3)
        or len(set(anchor_indices)) != 1
        or len(set(anchor_ordinals)) != 1
    ):
        return None
    return TwoOwnerTrailingDsbTopology(
        anchor_index=anchor_indices[0],
        anchor_ordinal=anchor_ordinals[0],
        owner_indices=(owners[0], owners[1]),
    )


def apply_two_owner_trailing_dsb_widths(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
) -> list[tuple[float, ...]] | None:
    """Apply the c10 shared boundary transfer without changing profile terms."""

    topology = two_owner_trailing_dsb_topology(rows)
    if topology is None:
        return None
    if len(reconciled_widths) != len(rows):
        return None
    adjusted = [list(widths) for widths in reconciled_widths]
    for source_row, widths in zip(rows, adjusted, strict=True):
        anchor = _barline_event_indices(source_row)[topology.anchor_ordinal]
        if anchor < 1:
            return None
        transfer_index = (
            anchor - 2
            if source_row[anchor - 1].event.kind
            in {
                MusicTokenKind.NOTE,
                MusicTokenKind.REST,
                MusicTokenKind.RHYTHM_NOTE,
                MusicTokenKind.HIDDEN_REST,
            }
            else anchor - 1
        )
        if transfer_index < 0 or anchor >= len(widths):
            return None
        widths[transfer_index] -= TWO_OWNER_DSB_PRE_ANCHOR_TRANSFER
        widths[anchor] += TWO_OWNER_DSB_POST_ANCHOR_RESERVE
    return [tuple(widths) for widths in adjusted]


def _dsb_structure(
    rows: list[list[LayoutEvent]],
) -> tuple[int | None, int | None, list[int]]:
    """Return (block_start_ordinal, block_end_ordinal, inline_close_ordinals).

    Ordinals count barlines per row. A multi-measure block is an ``&dsb_a``
    anchor followed by two or more consecutive ``dsb-tail`` barlines; a single
    trailing ``dsb-tail`` barline marks an inline DSB whose closing barline is
    one ordinal after the anchor.

    One system may mix several DSB shapes (a full-line block in one row and a
    trailing block in another). The shared-column gap reserves are only
    validated for systems where every multi-measure block candidate spans the
    same ordinals, so conflicting candidates disable the block reserves while
    leaving inline-close reserves intact.
    """
    block_candidates: list[tuple[int, int]] = []
    inline_closes: list[int] = []
    for row in rows:
        barlines = _barline_event_indices(row)
        for position, event_index in enumerate(barlines):
            item = row[event_index]
            if "&dsb_a" not in (item.event.code or ""):
                continue
            tails = 0
            for later in barlines[position + 1 :]:
                if row[later].block == "dsb-tail":
                    tails += 1
                else:
                    break
            if tails >= 2:
                block_candidates.append((position, position + tails))
            elif tails == 1:
                inline_closes.append(position + 1)
    if not block_candidates or len(set(block_candidates)) != 1:
        return None, None, inline_closes
    block_start, block_end = block_candidates[0]
    return block_start, block_end, inline_closes


def apply_dsb_gap_reserves(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
    profiles: list[LegacyIntrinsicProfile],
    *,
    four_beat_refinement_owned: bool = False,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    """Add the shared-column DSB gap reserves without changing the scale.

    ``four_beat_refinement_owned`` marks systems whose visible spacing is
    owned by the four-beat refinement while the DSB overlay stays a legacy
    intrinsic stream (notably the second As-Wished page). Widening visible
    gaps there desynchronizes the static ghost overlay, so the reserves are
    deferred until that family's ghost placement is decoded.
    """
    if four_beat_refinement_owned:
        return profiles, reconciled_widths
    two_owner_widths = apply_two_owner_trailing_dsb_widths(rows, reconciled_widths)
    if two_owner_widths is not None:
        return profiles, two_owner_widths
    block_start, block_end, inline_closes = _dsb_structure(rows)
    if block_start is None and not inline_closes:
        return profiles, reconciled_widths

    adjusted_profiles = list(profiles)
    adjusted_widths = [list(widths) for widths in reconciled_widths]
    for row_index, (row, widths) in enumerate(zip(rows, adjusted_widths, strict=True)):
        barlines = _barline_event_indices(row)
        delta = 0.0
        if block_start is not None and block_start < len(barlines):
            anchor = barlines[block_start]
            if anchor < len(widths):
                target = max(widths[anchor], DSB_BLOCK_START_AFTER_GAP)
                delta += target - widths[anchor]
                widths[anchor] = target
        if block_end is not None and block_end < len(barlines):
            closer = barlines[block_end]
            if 2 <= closer - 1 < len(widths):
                before_target = max(widths[closer - 1], DSB_BLOCK_END_BEFORE_GAP)
                delta += before_target - widths[closer - 1]
                widths[closer - 1] = before_target
                exit_index = _first_pair_exit_step(row, barlines, closer)
                if exit_index is not None and exit_index < len(widths):
                    step_target = max(widths[exit_index], DSB_PAIR_EXIT_STEP)
                    delta += step_target - widths[exit_index]
                    widths[exit_index] = step_target
        for ordinal in inline_closes:
            if ordinal >= len(barlines):
                continue
            closer = barlines[ordinal]
            if 1 <= closer - 1 < len(widths):
                target = max(widths[closer - 1], DSB_INLINE_CLOSE_BEFORE_GAP)
                delta += target - widths[closer - 1]
                widths[closer - 1] = target
        if delta > 0.0:
            adjusted_profiles[row_index] = replace(
                profiles[row_index],
                denominator_adjustment=profiles[row_index].denominator_adjustment - delta,
            )
    return adjusted_profiles, [tuple(widths) for widths in adjusted_widths]


def _first_pair_exit_step(
    row: list[LayoutEvent],
    barlines: list[int],
    closer: int,
) -> int | None:
    """Index of the step leaving the first closed parenthetical pair.

    Only the narrow shape observed in the reference is matched: a note whose
    code ends with ``)`` followed by another note inside the block-end
    measure. The returned index addresses the reconciled width between those
    two events.
    """
    position = barlines.index(closer)
    if position == 0:
        return None
    start = barlines[position - 1] + 1
    for index in range(start, closer):
        item = row[index]
        previous = row[index - 1]
        if (
            item.event.kind == MusicTokenKind.NOTE
            and previous.event.kind == MusicTokenKind.NOTE
            and (previous.event.code or "").endswith(")")
        ):
            return index - 1
    return None


__all__ = [
    "TWO_OWNER_DSB_POST_ANCHOR_RESERVE",
    "TWO_OWNER_DSB_PRE_ANCHOR_TRANSFER",
    "TwoOwnerTrailingDsbTopology",
    "apply_dsb_gap_reserves",
    "apply_two_owner_trailing_dsb_widths",
    "two_owner_trailing_dsb_topology",
]
