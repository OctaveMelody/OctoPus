"""Shared reserves and final columns for parallel eight-measure refrains."""

from __future__ import annotations

from collections import defaultdict

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent

# Reserve releases derived from the Edelweiss - Choir parallel-refrain pages
# (pages where four voices carry the same eight-measure refrain).  The opening
# hidden-rest sentinel owns half an accidental column; the closing note keeps a
# full accidental column when one voice is accented there, or a wider release
# when the row's single accidental sits earlier and the ending stays plain.
OPENING_SENTINEL_RELEASE = 1.8
ACCENTED_ENDING_RELEASE = 8.4
PLAIN_ENDING_SINGLE_ACCIDENTAL_RELEASE = 12.0


def apply_parallel_refrain_reserves(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
) -> list[tuple[float, ...]]:
    """Release the opening sentinel and accidental-ending excess reserves."""

    indices = _parallel_refrain_indices(rows)
    if indices is None:
        return reconciled_widths
    opening_note_index, final_note_index, final_release = indices
    adjusted: list[tuple[float, ...]] = []
    for widths in reconciled_widths:
        row_widths = list(widths)
        row_widths[opening_note_index] -= OPENING_SENTINEL_RELEASE
        row_widths[final_note_index] -= final_release
        adjusted.append(tuple(row_widths))
    return adjusted


def align_parallel_refrain_rows(events: list[LayoutEvent]) -> None:
    """Restore one column per source position after secondary row passes."""

    rows_by_line: dict[int, list[LayoutEvent]] = defaultdict(list)
    for item in events:
        rows_by_line[item.line].append(item)
    rows = list(rows_by_line.values())
    if _parallel_refrain_indices(rows) is None:
        return
    authority = rows[0]
    for row in rows[1:]:
        for item, owner in zip(row, authority, strict=True):
            item.x = owner.x
            item.style_x = owner.style_x


def uses_parallel_refrain_rows(rows: list[list[LayoutEvent]]) -> bool:
    """Return whether rows use the parallel eight-measure refrain topology."""

    return _parallel_refrain_indices(rows) is not None


def _parallel_refrain_indices(
    rows: list[list[LayoutEvent]],
) -> tuple[int, int, float] | None:
    if (
        len(rows) != 4
        or len({len(row) for row in rows}) != 1
        or any(row[-1].event.code != "|" for row in rows)
    ):
        return None
    bar_indices_by_row = [
        tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        for row in rows
    ]
    if len(set(bar_indices_by_row)) != 1 or len(bar_indices_by_row[0]) != 8:
        return None
    bar_indices = bar_indices_by_row[0]
    opening_note_index = bar_indices[0] - 1
    final_note_index = bar_indices[-2] + 1
    if (
        opening_note_index < 1
        or any(
            row[opening_note_index - 1].event.kind != MusicTokenKind.HIDDEN_REST
            or row[opening_note_index].event.kind != MusicTokenKind.NOTE
            or row[final_note_index].event.kind != MusicTokenKind.NOTE
            or row[final_note_index + 1].event.kind != MusicTokenKind.EXTENSION
            or row[final_note_index + 2].event.kind != MusicTokenKind.EXTENSION
            for row in rows
        )
    ):
        return None
    final_accidentals = sum(
        row[final_note_index].event.accidental is not None for row in rows
    )
    total_accidentals = sum(
        item.event.accidental is not None for row in rows for item in row
    )
    if final_accidentals == 1:
        final_release = ACCENTED_ENDING_RELEASE
    elif final_accidentals == 0 and total_accidentals == 1:
        final_release = PLAIN_ENDING_SINGLE_ACCIDENTAL_RELEASE
    else:
        return None
    return opening_note_index, final_note_index, final_release


__all__ = [
    "ACCENTED_ENDING_RELEASE",
    "OPENING_SENTINEL_RELEASE",
    "PLAIN_ENDING_SINGLE_ACCIDENTAL_RELEASE",
    "align_parallel_refrain_rows",
    "apply_parallel_refrain_reserves",
    "uses_parallel_refrain_rows",
]
