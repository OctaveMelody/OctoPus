"""Duration-union reserves for equal-density five-measure lyric rows."""

from __future__ import annotations

from math import fsum

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..grid.union_grid import project_union_duration_grid
from ..profiles import LegacyIntrinsicProfile
from ..rows.row_signatures import row_event_onsets
from .models import LyricTextByVoice


def apply_five_measure_dual_lyric_union(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    lyric_text_by_voice: LyricTextByVoice,
) -> list[tuple[float, ...]]:
    """Project the duration union and retain its phrase-owned reserves."""

    primary_indices = _primary_dotted_prebar_indices(rows[0]) if rows else []
    if not uses_five_measure_dual_lyric_union(
        rows,
        lyric_text_by_voice=lyric_text_by_voice,
    ):
        return reconciled_widths
    union_widths = project_union_duration_grid(rows, profiles, reconciled_widths)
    projected = [
        list(widths)
        for widths in union_widths
    ]
    for index in primary_indices:
        projected[0][index - 1] += 18.0
        projected[0][index] -= 27.0

    secondary = rows[1]
    for index in _secondary_indices_at_primary_onsets(rows, primary_indices):
        projected[1][index - 1] -= 9.0
    prebar_pickup_index = _secondary_prebar_rest_pickup_indices(secondary)[0]
    projected[1][prebar_pickup_index] -= 18.0
    projected[1][prebar_pickup_index + 1] += 18.0
    if any(
        abs((fsum(before) - fsum(after)) - 18.0) > GEOMETRY_EPSILON
        for before, after in zip(union_widths, projected, strict=True)
    ):
        return reconciled_widths
    return [tuple(widths) for widths in projected]


def uses_five_measure_dual_lyric_union(
    rows: list[list[LayoutEvent]],
    *,
    lyric_text_by_voice: LyricTextByVoice,
) -> bool:
    primary_indices = _primary_dotted_prebar_indices(rows[0]) if rows else []
    return (
        len(rows) == 2
        and len({len(row) for row in rows}) == 1
        and all(lyric_text_by_voice.get(row[0].voice) for row in rows)
        and all(
            row[-1].event.code == "|"
            and sum(item.event.kind == MusicTokenKind.BARLINE for item in row) == 5
            for row in rows
        )
        and len(primary_indices) == 2
        and len(_secondary_indices_at_primary_onsets(rows, primary_indices)) == 2
        and len(_secondary_prebar_rest_pickup_indices(rows[1])) == 1
        and rows[1][0].event.code.endswith("(")
        and rows[1][1].event.kind == MusicTokenKind.EXTENSION
    )


def _primary_dotted_prebar_indices(row: list[LayoutEvent]) -> list[int]:
    return [
        index
        for index in range(1, len(row) - 1)
        if row[index - 1].event.duration_slashes == 1
        and row[index].event.duration_dots == 1
        and row[index].event.duration_slashes == 0
        and row[index + 1].event.kind == MusicTokenKind.BARLINE
    ]


def _secondary_indices_at_primary_onsets(
    rows: list[list[LayoutEvent]], primary_indices: list[int]
) -> list[int]:
    if len(rows) != 2:
        return []
    primary_onsets = row_event_onsets(rows[0])
    target_onsets = {primary_onsets[index] for index in primary_indices}
    secondary_onsets = row_event_onsets(rows[1])
    return [
        index
        for index, (item, onset) in enumerate(
            zip(rows[1], secondary_onsets, strict=True)
        )
        if onset in target_onsets and item.event.kind != MusicTokenKind.BARLINE
    ]


def _secondary_prebar_rest_pickup_indices(row: list[LayoutEvent]) -> list[int]:
    return [
        index
        for index in range(len(row) - 2)
        if row[index].event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
        and row[index].event.duration_slashes == 1
        and row[index + 1].event.duration_slashes == 1
        and row[index + 2].event.kind == MusicTokenKind.BARLINE
    ]


__all__ = [
    "apply_five_measure_dual_lyric_union",
    "uses_five_measure_dual_lyric_union",
]
