"""Pure width-partition and terminal-reserve classification policies."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from re_tomato.normalization.types import MusicEvent

from ...parser.ast import MusicTokenKind
from ..core.layout_types import GEOMETRY_EPSILON


def partition_shared_measure_widths(
    target: Sequence[float],
    current: Sequence[float],
) -> list[float]:
    if not current or len(target) < len(current):
        return list(current)
    prefix = [0.0]
    for width in target:
        prefix.append(prefix[-1] + width)
    states: dict[tuple[int, int], tuple[float, tuple[float, ...]]] = {
        (0, 0): (0.0, ())
    }
    for group_index, expected_width in enumerate(current, start=1):
        for end in range(group_index, len(target) + 1):
            best: tuple[float, tuple[float, ...]] | None = None
            for start in range(group_index - 1, end):
                previous = states.get((group_index - 1, start))
                if previous is None:
                    continue
                width = prefix[end] - prefix[start]
                candidate = (
                    previous[0] + (width - expected_width) ** 2,
                    (*previous[1], width),
                )
                if (
                    best is None
                    or candidate[0] < best[0] - GEOMETRY_EPSILON
                    or (
                        abs(candidate[0] - best[0]) <= GEOMETRY_EPSILON
                        and candidate[1] < best[1]
                    )
                ):
                    best = candidate
            if best is not None:
                states[(group_index, end)] = best
    result = states.get((len(current), len(target)))
    return list(result[1]) if result is not None else list(current)


def is_terminal_non_ykh_reserve_event(event: MusicEvent) -> bool:
    """Identify terminal events whose reserve belongs before the final slot."""
    if event.kind == MusicTokenKind.HIDDEN_REST:
        return True
    if "ykh" in event.decorations:
        return False
    return (
        event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and (
            ")" in event.code
            or any(
                role.endswith(":end")
                and (":tie:" in role or ":slur:" in role)
                for role in event.construct_roles
            )
        )
    )


def partition_shared_measure_widths_by_partial_boundaries(
    target_widths: Sequence[float],
    current_widths: Sequence[float],
    target_boundaries: Sequence[Fraction],
    current_boundaries: Sequence[Fraction],
    *,
    prefer_leading_deficit: bool = False,
) -> list[float] | None:
    shared_boundaries = sorted(set(target_boundaries) & set(current_boundaries))
    if (
        len(shared_boundaries) < 2
        or shared_boundaries[0] != 0
        or shared_boundaries[-1] != target_boundaries[-1]
    ):
        return None

    result = list(current_widths)
    for chunk_start, chunk_end in zip(shared_boundaries, shared_boundaries[1:], strict=False):
        target_indices = [
            index
            for index in range(len(target_widths))
            if chunk_start <= target_boundaries[index] < chunk_end
        ]
        current_indices = [
            index
            for index in range(len(current_widths))
            if chunk_start <= current_boundaries[index] < chunk_end
        ]
        if not target_indices:
            continue
        if not current_indices:
            return None
        if len(target_indices) >= len(current_indices):
            replacement = [0.0] * len(current_indices)
            for target_index in target_indices:
                current_offset = next(
                    (
                        offset
                        for offset, current_index in enumerate(current_indices)
                        if current_boundaries[current_index]
                        <= target_boundaries[target_index]
                        < current_boundaries[current_index + 1]
                    ),
                    None,
                )
                if current_offset is None:
                    return None
                replacement[current_offset] += target_widths[target_index]
            if any(width <= 0 for width in replacement):
                replacement = [current_widths[index] for index in current_indices]
                remaining = sum(target_widths[index] for index in target_indices) - sum(replacement)
                if remaining < -GEOMETRY_EPSILON:
                    return None
                allocation_order = (
                    range(len(replacement))
                    if prefer_leading_deficit
                    else range(len(replacement) - 1, -1, -1)
                )
                for index in allocation_order:
                    addition = min(18.0, remaining)
                    replacement[index] += addition
                    remaining -= addition
                    if remaining <= GEOMETRY_EPSILON:
                        break
                if abs(remaining) > GEOMETRY_EPSILON:
                    return None
        else:
            replacement = [current_widths[index] for index in current_indices]
            remaining = sum(target_widths[index] for index in target_indices) - sum(replacement)
            if remaining < -GEOMETRY_EPSILON:
                return None
            allocation_order = (
                range(len(replacement))
                if prefer_leading_deficit
                else range(len(replacement) - 1, -1, -1)
            )
            for index in allocation_order:
                addition = min(18.0, remaining)
                replacement[index] += addition
                remaining -= addition
                if remaining <= GEOMETRY_EPSILON:
                    break
            if abs(remaining) > GEOMETRY_EPSILON:
                return None
        result[current_indices[0] : current_indices[-1] + 1] = replacement
    return result


__all__ = [
    "is_terminal_non_ykh_reserve_event",
    "partition_shared_measure_widths",
    "partition_shared_measure_widths_by_partial_boundaries",
]
