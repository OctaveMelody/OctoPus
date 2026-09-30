"""Final alignment for parallel sustained rows with hidden sentinels."""

from __future__ import annotations

from collections import defaultdict

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent


def align_parallel_sustain_sentinel_rows(events: list[LayoutEvent]) -> None:
    """Project hidden-sentinel variants onto their unique extension authority."""

    rows_by_line: dict[int, list[LayoutEvent]] = defaultdict(list)
    for item in events:
        rows_by_line[item.line].append(item)
    rows = list(rows_by_line.values())
    if (
        len(rows) != 4
        or len({len(row) for row in rows}) != 1
        or any(row[-1].event.code != "|j" for row in rows)
    ):
        return
    bar_indices = {
        tuple(
            index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
        )
        for row in rows
    }
    if len(bar_indices) != 1:
        return
    differing_indices = [
        index
        for index in range(len(rows[0]))
        if len({row[index].event.kind for row in rows}) > 1
    ]
    if len(differing_indices) != 1:
        return
    sentinel_index = differing_indices[0]
    authority_rows = [
        row
        for row in rows
        if row[sentinel_index].event.kind == MusicTokenKind.EXTENSION
    ]
    sentinel_rows = [
        row
        for row in rows
        if row[sentinel_index].event.kind == MusicTokenKind.HIDDEN_REST
    ]
    if len(authority_rows) != 1 or len(sentinel_rows) != 3:
        return
    authority = authority_rows[0]
    for row in sentinel_rows:
        if any(
            item.event.kind != owner.event.kind
            for index, (item, owner) in enumerate(zip(row, authority, strict=True))
            if index != sentinel_index
        ):
            return
    for row in sentinel_rows:
        for item, owner in zip(row, authority, strict=True):
            item.x = owner.x
            item.style_x = owner.style_x


__all__ = ["align_parallel_sustain_sentinel_rows"]
