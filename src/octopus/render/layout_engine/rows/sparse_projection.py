"""Sparse shared-row projection and authority partitioning."""

from __future__ import annotations

from fractions import Fraction
from math import fsum

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent, PageMetrics
from ..hidden.hidden_streams import event_duration_fraction
from ..intrinsic.builder import build_legacy_intrinsic_profile
from ..visibility import is_synthetic_hidden_rest_placeholder


def project_sparse_leading_rows_from_continuation(
    voice_rows: list[list[list[LayoutEvent]]],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]],
) -> None:
    system_rows = [row for rows in voice_rows for row in rows]
    authority_row = max(system_rows, key=len)
    authority_profile = build_legacy_intrinsic_profile(
        authority_row,
        metrics=metrics,
        left=left,
        lyric_text_by_event=lyric_text_by_voice.get(authority_row[0].voice, {}),
    )
    authority_bars = [
        index
        for index, item in enumerate(authority_row)
        if item.event.kind == MusicTokenKind.BARLINE
    ]
    denominator = fsum(
        (
            *authority_profile.interval_widths,
            authority_profile.terminal_width,
            authority_profile.final_bar_width,
            authority_profile.denominator_adjustment,
        )
    )
    if denominator <= 0:
        return
    right = float(metrics.width - metrics.margin_right + 3)
    scale = (right - left + 14.0) / denominator
    for row in system_rows:
        if row is authority_row or len(row) >= len(authority_row):
            continue
        row_profile = build_legacy_intrinsic_profile(
            row,
            metrics=metrics,
            left=left,
            lyric_text_by_event=lyric_text_by_voice.get(row[0].voice, {}),
        )
        row_bars = [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        if len(row_bars) != len(authority_bars):
            continue
        projected: list[float] = []
        authority_start = 0
        row_start = 0
        for authority_end, row_end in zip(authority_bars, row_bars, strict=True):
            target_widths = list(
                authority_profile.interval_widths[authority_start:authority_end]
            )
            current_widths = list(row_profile.interval_widths[row_start:row_end])
            target_items = authority_row[authority_start:authority_end]
            current_items = row[row_start:row_end]
            starts_with_bar = (
                bool(target_items)
                and bool(current_items)
                and target_items[0].event.kind == MusicTokenKind.BARLINE
                and current_items[0].event.kind == MusicTokenKind.BARLINE
            )
            prefix = target_widths[:1] if starts_with_bar else []
            target_content_widths = target_widths[len(prefix) :]
            target_content = target_items[len(prefix) :]
            current_content_widths = current_widths[len(prefix) :]
            current_content = current_items[len(prefix) :]
            if (
                current_content
                and is_synthetic_hidden_rest_placeholder(current_content[-1].event)
            ):
                replacement = _partition_hidden_tail_authority_widths(
                    target_content_widths,
                    target_content,
                    current_content,
                )
            else:
                replacement = _partition_centered_authority_widths(
                    target_content_widths,
                    len(current_content_widths),
                )
            if replacement is None:
                break
            projected.extend((*prefix, *replacement))
            authority_start = authority_end
            row_start = row_end
        else:
            if len(projected) != len(row_profile.interval_widths):
                continue
            row[0].x = left
            for index, item in enumerate(row[1:-1], start=1):
                item.x = left + fsum(projected[:index]) * scale
            row[-1].x = right
            for item in row:
                item.projection_scale = scale
                item.projection_kind = "sparse"


def _partition_hidden_tail_authority_widths(
    target_widths: list[float],
    target_items: list[LayoutEvent],
    current_items: list[LayoutEvent],
) -> list[float] | None:
    if not target_widths or len(current_items) < 2:
        return None
    target_boundaries = [Fraction()]
    for item in target_items:
        duration = event_duration_fraction(item.event)
        if duration <= 0:
            return None
        target_boundaries.append(target_boundaries[-1] + duration)
    groups: list[float] = []
    cursor = 0
    for item in current_items[:-1]:
        duration = event_duration_fraction(item.event)
        if duration <= 0:
            return None
        desired_end = target_boundaries[cursor] + duration
        end = max(
            (
                index
                for index, boundary in enumerate(target_boundaries)
                if cursor < index < len(target_boundaries)
                and boundary <= desired_end
            ),
            default=cursor,
        )
        if end == cursor:
            return None
        groups.append(fsum(target_widths[cursor:end]))
        cursor = end
    if cursor >= len(target_widths):
        return None
    groups.append(fsum(target_widths[cursor:]))
    return groups if len(groups) == len(current_items) else None


def _partition_centered_authority_widths(
    target_widths: list[float],
    group_count: int,
) -> list[float] | None:
    if group_count <= 0 or len(target_widths) < group_count:
        return None
    base, remainder = divmod(len(target_widths), group_count)
    group_sizes = [base] * group_count
    center_order = sorted(
        range(group_count),
        key=lambda index: (abs(index - (group_count - 1) / 2), index),
    )
    for index in center_order[:remainder]:
        group_sizes[index] += 1
    result: list[float] = []
    start = 0
    for size in group_sizes:
        result.append(fsum(target_widths[start : start + size]))
        start += size
    return result


def project_sparse_hidden_measure_widths(
    rows: list[list[LayoutEvent]],
    widths: list[tuple[float, ...]],
) -> list[tuple[float, ...]]:
    if len({len(row) for row in rows}) == 1:
        return widths
    bar_indices = [
        [
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        ]
        for row in rows
    ]
    if not bar_indices or len({len(indices) for indices in bar_indices}) != 1:
        return widths

    projected = [list(items) for items in widths]
    measure_starts = [0] * len(rows)
    for bar_ordinal in range(len(bar_indices[0])):
        slices: list[tuple[int, int, int, list[LayoutEvent]]] = []
        for voice_index, row in enumerate(rows):
            start = measure_starts[voice_index]
            end = bar_indices[voice_index][bar_ordinal]
            measure_starts[voice_index] = end
            content_start = start + int(row[start].event.kind == MusicTokenKind.BARLINE)
            slices.append((start, end, content_start, row[content_start:end]))

        for voice_index, (start, end, content_start, content) in enumerate(slices):
            if len(content) < 2:
                continue
            current_has_hidden_tail = content[-1].event.kind == MusicTokenKind.HIDDEN_REST
            authority_index = max(
                (
                    index
                    for index, (_start, _end, _content_start, items) in enumerate(slices)
                    if index != voice_index
                    and len(items) >= len(content) + 3
                    and (
                        current_has_hidden_tail
                        or items[-1].event.kind == MusicTokenKind.HIDDEN_REST
                    )
                ),
                key=lambda index: len(slices[index][3]),
                default=None,
            )
            if authority_index is None:
                continue
            authority_start, authority_end, authority_content_start, authority = slices[
                authority_index
            ]
            authority_widths = projected[authority_index][
                authority_content_start:authority_end
            ]
            authority_onsets: list[Fraction] = []
            elapsed = Fraction()
            for item in authority:
                authority_onsets.append(elapsed)
                elapsed += event_duration_fraction(item.event)

            mapped_indices: list[int] = []
            elapsed = Fraction()
            for item in content:
                if item is content[-1] and current_has_hidden_tail:
                    mapped_index = len(authority) - 2
                else:
                    mapped_index = max(
                        index
                        for index, onset in enumerate(authority_onsets)
                        if onset <= elapsed
                    )
                if mapped_indices and mapped_index <= mapped_indices[-1]:
                    mapped_index = mapped_indices[-1] + 1
                if mapped_index >= len(authority):
                    break
                mapped_indices.append(mapped_index)
                elapsed += event_duration_fraction(item.event)
            if len(mapped_indices) != len(content):
                continue

            boundaries = [*mapped_indices, len(authority)]
            replacement = [
                sum(authority_widths[left:right])
                for left, right in zip(boundaries[:-1], boundaries[1:], strict=True)
            ]
            if start != content_start:
                replacement.insert(0, projected[authority_index][authority_start])
            if len(replacement) == end - start:
                projected[voice_index][start:end] = replacement
    return [tuple(items) for items in projected]

__all__ = [
    "project_sparse_hidden_measure_widths",
    "project_sparse_leading_rows_from_continuation",
]

