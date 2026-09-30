"""Shared accidental reserves for unequal-rhythm voice rows."""

from __future__ import annotations

from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..reserves.interval_reserves import add_interval_reserve
from ..rows.row_signatures import row_event_onsets

_ACCIDENTAL_RESERVE = 3.6


def restore_open_ending_accidental_onset_reserve(
    rows: list[list[LayoutEvent]],
    reconciled_widths: list[tuple[float, ...]],
) -> list[tuple[float, ...]]:
    """Retain one shared reserve before an internal accidental onset.

    Unequal-rhythm rows address the same onset through different event indices.
    Their measure reconciliation therefore cannot preserve an accidental reserve
    by copying a same-index interval.  An ordinary open ending keeps that reserve
    in every voice so the shared cursor remains aligned after the accidental.
    """

    accidental_onset = _open_ending_accidental_onset(rows)
    if accidental_onset is None:
        return reconciled_widths
    adjusted: list[tuple[float, ...]] = []
    for row, widths in zip(rows, reconciled_widths, strict=True):
        onsets = row_event_onsets(row)
        onset_index = next(
            (
                index
                for index, (item, onset) in enumerate(zip(row, onsets, strict=True))
                if onset == accidental_onset
                and item.event.kind != MusicTokenKind.BARLINE
            ),
            None,
        )
        if onset_index is None or onset_index == 0:
            return reconciled_widths
        adjusted.append(
            add_interval_reserve(
                widths,
                interval_index=onset_index - 1,
                added_width=_ACCIDENTAL_RESERVE,
            ).interval_widths
        )
    return adjusted


def _open_ending_accidental_onset(
    rows: list[list[LayoutEvent]],
) -> Fraction | None:
    if (
        len(rows) != 2
        or len({len(row) for row in rows}) == 1
        or any(row[-1].event.code != "|" for row in rows)
    ):
        return None
    accidental_onsets = [
        onset
        for row in rows
        for item, onset in zip(row, row_event_onsets(row), strict=True)
        if onset > 0
        and item.event.accidental is not None
        and item.event.duration_slashes == 0
        and item.event.duration_dots == 0
    ]
    return accidental_onsets[0] if len(accidental_onsets) == 1 else None


__all__ = ["restore_open_ending_accidental_onset_reserve"]
