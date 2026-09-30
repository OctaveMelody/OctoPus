"""Shared columns for the verified overlapping-DSB row topology.

Some shared systems contain two DSB owners whose spans overlap without either
owner forming the complete trailing block handled by
``dsb_continuation_widths``.  The reference still uses one visible column
grid for those rows.  This module admits the narrowly decoded topology and
maps each row onto the columns of a non-DSB authority row.

The admission is intentionally structural: four rows, nine barlines, one
three-tail owner beginning at the first barline, one one-tail owner beginning
at the fourth barline, and one generated placeholder.  It does not inspect a
document name or a reference coordinate.  The authority row supplies the
already-reconciled natural offsets; sparse rows select columns by source
onset, while a closed parenthetical pair and a generated placeholder consume
the next sequential column.  Compression remains owned by the legacy
profile denominator, so this mapping changes row geometry without changing
the system scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout_engine.grid.beat_grid import TIMED_KINDS
from octopus.render.layout_engine.hidden.hidden_streams import event_duration_fraction

from ....parser.ast import MusicTokenKind
from .dsb_gap_reserves import _barline_event_indices


@dataclass(frozen=True, slots=True)
class OverlappingDsbTopology:
    """The two owners in the admitted mixed-closure DSB shape."""

    authority_index: int
    long_owner_index: int
    short_owner_index: int
    anchor_ordinal: int
    short_owner_anchor_ordinal: int


def overlapping_dsb_topology(
    rows: list[list[LayoutEvent]],
) -> OverlappingDsbTopology | None:
    """Return topology metadata for the verified overlapping-DSB shape."""

    if len(rows) != 4 or any(not row for row in rows):
        return None
    barlines_by_row = [_barline_event_indices(row) for row in rows]
    if any(len(barlines) != 9 for barlines in barlines_by_row):
        return None

    owners: list[tuple[int, int, int]] = []
    for row_index, (row, barlines) in enumerate(zip(rows, barlines_by_row, strict=True)):
        anchors = [
            ordinal
            for ordinal, event_index in enumerate(barlines)
            if "&dsb_a" in (row[event_index].event.code or "")
        ]
        if len(anchors) > 1:
            return None
        if not anchors:
            if any(row[event_index].block == "dsb-tail" for event_index in barlines):
                return None
            continue

        anchor_ordinal = anchors[0]
        tail_count = 0
        for event_index in barlines[anchor_ordinal + 1 :]:
            if row[event_index].block != "dsb-tail":
                break
            tail_count += 1
        if tail_count not in {1, 3}:
            return None
        if anchor_ordinal + tail_count >= len(barlines):
            return None
        if any(
            row[event_index].block == "dsb-tail"
            for event_index in barlines[: anchor_ordinal + 1]
        ) or any(
            row[event_index].block == "dsb-tail"
            for event_index in barlines[anchor_ordinal + tail_count + 1 :]
        ):
            return None
        owners.append((row_index, anchor_ordinal, tail_count))

    if sorted((ordinal, tails) for _, ordinal, tails in owners) != [(0, 3), (3, 1)]:
        return None
    if sum(
        item.block == "dsb-placeholder"
        for row in rows
        for item in row
    ) != 1:
        return None
    if any(
        item.event.kind not in TIMED_KINDS | {MusicTokenKind.BARLINE}
        for row in rows
        for item in row
    ):
        return None

    long_owner_index, long_anchor, long_tails = next(
        owner for owner in owners if owner[1:] == (0, 3)
    )
    short_owner_index, short_anchor, short_tails = next(
        owner for owner in owners if owner[1:] == (3, 1)
    )
    if long_anchor + long_tails != short_anchor:
        return None
    if short_anchor + short_tails >= len(barlines_by_row[short_owner_index]):
        return None

    authority_candidates = [
        index
        for index, row in enumerate(rows)
        if index not in {long_owner_index, short_owner_index}
        and not any(item.block == "dsb-placeholder" for item in row)
    ]
    if not authority_candidates:
        return None
    authority_index = max(
        authority_candidates,
        key=lambda index: sum(
            item.event.kind != MusicTokenKind.BARLINE for item in rows[index]
        ),
    )
    return OverlappingDsbTopology(
        authority_index=authority_index,
        long_owner_index=long_owner_index,
        short_owner_index=short_owner_index,
        anchor_ordinal=long_anchor,
        short_owner_anchor_ordinal=short_anchor,
    )


def compute_overlapping_dsb_widths(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
) -> list[tuple[float, ...]] | None:
    """Map admitted rows onto the authority row's natural event columns."""

    topology = overlapping_dsb_topology(rows)
    if topology is None or len(reconciled_widths) != len(rows):
        return None

    authority = rows[topology.authority_index]
    authority_widths = reconciled_widths[topology.authority_index]
    if len(authority_widths) != len(authority) - 2:
        return None
    authority_barlines = _barline_event_indices(authority)
    offsets = [0.0]
    for width in authority_widths:
        offsets.append(offsets[-1] + width)

    authority_columns: list[tuple[tuple[float, Fraction], ...]] = []
    for ordinal, barline_index in enumerate(authority_barlines):
        start = 0 if ordinal == 0 else authority_barlines[ordinal - 1] + 1
        measure_columns: list[tuple[float, Fraction]] = []
        onset = Fraction()
        for event_index in range(start, barline_index):
            item = authority[event_index]
            if item.event.kind not in TIMED_KINDS:
                return None
            measure_columns.append((offsets[event_index], onset))
            onset += event_duration_fraction(item.event)
        if not measure_columns:
            return None
        authority_columns.append(tuple(measure_columns))

    desired_by_row: list[list[float]] = []
    for row, widths in zip(rows, reconciled_widths, strict=True):
        if len(widths) != len(row) - 2:
            return None
        barlines = _barline_event_indices(row)
        desired: list[float | None] = [None] * len(row)
        for ordinal, barline_index in enumerate(barlines):
            start = 0 if ordinal == 0 else barlines[ordinal - 1] + 1
            target_columns = authority_columns[ordinal]
            row_onset = Fraction()
            last_column = -1
            for event_index in range(start, barline_index):
                item = row[event_index]
                if item.event.kind not in TIMED_KINDS:
                    return None
                if item.block == "dsb-placeholder":
                    column = last_column + 1
                elif (
                    last_column >= 0
                    and (item.event.code or "").endswith(")")
                    and "(" in (row[event_index - 1].event.code or "")
                ):
                    column = last_column + 1
                else:
                    column = next(
                        (
                            column_index
                            for column_index, (_, onset) in enumerate(target_columns)
                            if onset >= row_onset
                        ),
                        len(target_columns),
                    )
                    column = max(column, last_column + 1)
                if column >= len(target_columns):
                    return None
                desired[event_index] = target_columns[column][0]
                last_column = column
                row_onset += event_duration_fraction(item.event)
            authority_barline_index = authority_barlines[ordinal]
            if barline_index != len(row) - 1 and authority_barline_index >= len(offsets):
                return None
            if barline_index != len(row) - 1:
                desired[barline_index] = offsets[authority_barline_index]

        row_offsets = [value for value in desired[1:-1] if value is not None]
        if len(row_offsets) != len(row) - 2:
            return None
        desired_by_row.append(row_offsets)

    result: list[tuple[float, ...]] = []
    for row_offsets, widths in zip(desired_by_row, reconciled_widths, strict=True):
        # The final barline is pinned by the shared projection loop, so only
        # offsets through the last visible event become reconciled intervals.
        event_offsets = [0.0, *row_offsets]
        result_widths = tuple(
            event_offsets[index] - event_offsets[index - 1]
            for index in range(1, len(event_offsets))
        )
        if len(result_widths) != len(widths):
            return None
        result.append(result_widths)
    return result


__all__ = [
    "OverlappingDsbTopology",
    "compute_overlapping_dsb_widths",
    "overlapping_dsb_topology",
]
