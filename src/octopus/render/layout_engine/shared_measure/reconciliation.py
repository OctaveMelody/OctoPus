"""Per-voice shared-measure width replacement policy."""

from __future__ import annotations

from collections.abc import Sequence

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..duration_partition import partition_shared_measure_widths_by_duration
from ..profiles import LegacyIntrinsicProfile
from ..width_partition import (
    partition_shared_measure_widths,
)
from .models import MeasureReconciliationContext, MeasureSlice
from .policies import (
    allocate_shared_measure_deficit,
    apply_target_connector_reserve,
    find_punctuation_reserve,
    normalize_shared_measure_policies,
    release_partial_boundary_reserves,
    target_total_and_deficit,
    transfer_terminal_cap_excess,
)
from .slicing import (
    iter_shared_measure_slices,
    measure_barline_indices,
    select_target_measure_index,
)


def reconcile_shared_measure_voice_widths(
    target: Sequence[float],
    current: Sequence[float],
    target_content: Sequence[LayoutEvent],
    current_content: Sequence[LayoutEvent],
    *,
    context: MeasureReconciliationContext,
) -> list[float]:
    """Choose and adjust one secondary voice's replacement interval widths."""
    target_row = context.target_row
    current_row = context.current_row
    target_start = context.target_start
    target_end = context.target_end
    current_start = context.current_start
    current_end = context.current_end
    target_voice_index = context.target_voice_index
    current_voice_index = context.current_voice_index
    bar_ordinal = context.bar_ordinal
    final_bar_ordinal = context.final_bar_ordinal
    deficit = context.deficit
    punctuation_voice = context.punctuation_voice
    terminal_punctuation_by_row = context.terminal_punctuation_by_row
    punctuation_indices_by_row = context.punctuation_indices_by_row
    skip_indices_by_row = context.skip_indices_by_row
    uses_shifted_voice_grid = context.uses_shifted_voice_grid
    uses_compact_four_voice_grid = context.uses_compact_four_voice_grid
    uses_primary_spanning_hook_grid = context.uses_primary_spanning_hook_grid
    uses_primary_parallel_voice_denominator = context.uses_primary_parallel_voice_denominator
    allows_partial_boundaries = context.allows_partial_boundaries
    allows_shorter_measure_projection = context.allows_shorter_measure_projection
    terminal_cap = context.terminal_cap
    target_content_start = target_start + int(
        target_row[target_start].event.kind == MusicTokenKind.BARLINE
    )
    current_content_start = current_start + int(
        current_row[current_start].event.kind == MusicTokenKind.BARLINE
    )
    rests_only = bool(current_content) and all(
        item.event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
        for item in current_content
    )
    if (
        bar_ordinal == final_bar_ordinal
        and terminal_punctuation_by_row[current_voice_index]
    ):
        replacement = list(current)
    elif (
        punctuation_voice is not None
        and current_content
        and current_content[0].event.duration_dots
        and all(
            index in skip_indices_by_row[current_voice_index]
            for index in range(current_content_start + 1, current_end)
        )
    ):
        replacement = list(current)
        replacement[current_content_start - current_start] += deficit
    elif (
        current_content
        and len(target_content) >= 2
        and current_end - 1 in punctuation_indices_by_row[current_voice_index]
        and "(" in current_content[0].event.code
        and current_content[0].event.pitch == target_content[0].event.pitch
        and not current_content[0].event.duration_dots
        and target_content[0].event.duration_dots
    ):
        replacement = list(current)
        current_interval = current_content_start - current_start
        target_interval = target_content_start - target_start
        opening_addition = target[target_interval] - replacement[current_interval]
        replacement[current_interval] += opening_addition
        replacement[-1] += deficit - opening_addition
    elif (
        uses_shifted_voice_grid
        and len(current_content) == len(target_content) + 1
        and target_content
        and target_content[0].event.duration_dots
        and target_end - 1 in punctuation_indices_by_row[target_voice_index]
    ):
        replacement = list(current)
        replacement[current_content_start - current_start] += deficit
    elif (
        (uses_shifted_voice_grid or uses_compact_four_voice_grid)
        and len(target) == len(current)
        and len(target_content) >= 2
        and current_content
        and target_content[-1].event.code.endswith(")")
        and "(" in target_content[-2].event.code
        and target_content_start + len(target_content) - 1
        in skip_indices_by_row[target_voice_index]
    ):
        replacement = list(current)
        replacement[current_content_start - current_start] += deficit
    elif (
        len(target) == len(current)
        and (
            (
                rests_only
                and (
                    uses_primary_spanning_hook_grid
                    or target_row[target_content_start].event.duration_dots
                )
            )
            or (
                target_row[target_content_start].event.duration_dots
                and current_content_start + 1 < current_end
                and current_row[current_content_start + 1].event.kind
                == MusicTokenKind.EXTENSION
            )
            or (
                uses_shifted_voice_grid
                and target_content
                and target_content[0].event.duration_dots
                and target_content[-1].event.kind == MusicTokenKind.HIDDEN_REST
            )
        )
    ):
        replacement = list(target)
    elif (
        len(target) == len(current)
        and [
            item.event.accidental
            for item in target_content
            if item.event.accidental is not None
        ]
        == ["$", "="]
    ):
        replacement = list(target)
    elif (
        uses_primary_parallel_voice_denominator
        and len(target) == len(current)
        and any(item.event.duration_dots for item in target_content)
        and not any(item.event.duration_dots for item in current_content)
    ):
        replacement = list(target)
    elif (
        len(current_content) == 2
        and current_content[0].event.duration_dots
        and len(target_content) >= 4
    ):
        leading_bar = int(current_row[current_start].event.kind == MusicTokenKind.BARLINE)
        replacement = [
            *target[:leading_bar],
            sum(target[leading_bar : leading_bar + 2]),
            sum(target[leading_bar + 2 :]),
        ]
    elif (
        rests_only
        and bar_ordinal == final_bar_ordinal
        and len(target) == len(current) + 1
        and len(target_content) >= 2
        and all(item.event.duration_slashes for item in target_content[-2:])
    ):
        replacement = list(target[: len(current)])
    elif (
        tuple(item.event.kind for item in current_content)
        == (
            MusicTokenKind.NOTE,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.REST,
        )
        and tuple(item.event.kind for item in target_content)
        == (
            MusicTokenKind.NOTE,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.NOTE,
            MusicTokenKind.NOTE,
        )
        and len(target) == len(current) + 1
    ):
        replacement = list(current)
    elif (
        bar_ordinal == final_bar_ordinal
        and tuple(item.event.kind for item in current_content)
        == (
            MusicTokenKind.NOTE,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.EXTENSION,
            MusicTokenKind.REST,
            MusicTokenKind.HIDDEN_REST,
        )
        and len(target) == len(current) + 1
    ):
        # A held-note closer (``n - - 0``) whose final measure ends in the
        # inserted hidden-rest placeholder keeps the sibling's positional
        # column widths for its real events; the placeholder terminal then
        # absorbs the remainder instead of stretching the rest's width.
        # Oracle probe: standalone Toward-The-Clouds system (Q1 tail
        # ``5 - - 0&zkh 5// 6// |`` over Q2 tail ``2 - - 0 |``) renders the
        # placeholder one rest-slot after the quarter rest in both the
        # standalone page and p1 of the corpus file.
        replacement = list(target[: len(current)])
    elif (
        len(target) == len(current) + 1
        and len(current_content) == 3
        and "(" in current_content[0].event.code
        and ")" in current_content[1].event.code
        and not any(paren in current_content[2].event.code for paren in "()")
        and all(item.event.duration_slashes for item in current_content[:2])
        and len(target_content) >= 3
        and "(" in target_content[0].event.code
        and ")" in target_content[1].event.code
    ):
        # A row holding a parenthesized short-note pair followed by one bare
        # note snaps that bare note to the target's second group column; the
        # trailing interval then absorbs the target's remaining columns, which
        # are occupied by the sibling's extra notes in the shared grid.
        replacement = [
            target[0],
            target[1],
            target[2],
            sum(target) - sum(target[:3]),
        ]
    elif len(target) > len(current):
        replacement = partition_shared_measure_widths_by_duration(
            target,
            current,
            target_row[target_start:target_end],
            current_row[current_start:current_end],
            allow_current_rests=True,
            allow_partial_boundaries=(
                uses_compact_four_voice_grid or allows_partial_boundaries
            ),
            allow_shorter_current=allows_shorter_measure_projection,
        ) or partition_shared_measure_widths(target, current)
    else:
        replacement = allocate_shared_measure_deficit(current, deficit)
    replacement = transfer_terminal_cap_excess(
        replacement,
        current_content,
        target_content,
        raw_terminal_width=terminal_cap,
    )
    if allows_partial_boundaries:
        replacement = release_partial_boundary_reserves(
            replacement,
            current_row,
            start=current_start,
            end=current_end,
        )
    return replacement


__all__ = ["MeasureReconciliationContext", "reconcile_shared_measure_voice_widths"]
def reconcile_shared_measure_widths(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    *,
    punctuation_indices_by_row: list[frozenset[int]] | None = None,
    terminal_punctuation_by_row: list[bool] | None = None,
    skip_indices_by_row: list[frozenset[int]] | None = None,
    skip_connector_indices_by_row: list[frozenset[int]] | None = None,
    uses_shifted_voice_grid: bool = False,
    uses_compact_four_voice_grid: bool = False,
    uses_primary_spanning_hook_grid: bool = False,
    uses_primary_parallel_voice_denominator: bool = False,
    allows_partial_boundaries: bool = False,
    allows_shorter_measure_projection: bool = False,
    natural_measure_widths: Sequence[float] | None = None,
) -> list[tuple[float, ...]]:
    widths = [list(profile.interval_widths) for profile in profiles]
    bar_indices = measure_barline_indices(rows)
    if not bar_indices or len({len(indices) for indices in bar_indices}) != 1:
        return [tuple(items) for items in widths]
    policies = normalize_shared_measure_policies(
        len(rows),
        punctuation_indices_by_row,
        terminal_punctuation_by_row,
        skip_indices_by_row,
        skip_connector_indices_by_row,
    )
    normalized_punctuation_indices = policies.punctuation_indices_by_row
    normalized_terminal_punctuation = policies.terminal_punctuation_by_row
    normalized_skip_indices = policies.skip_indices_by_row
    normalized_skip_connector_indices = policies.skip_connector_indices_by_row
    normalized_natural_widths = _normalize_natural_measure_widths(
        natural_measure_widths,
        bar_indices,
        widths,
    )
    for bar_ordinal, slices in enumerate(iter_shared_measure_slices(bar_indices, widths)):
        target_index = select_target_measure_index(slices)
        punctuation_voice, reserve_index = find_punctuation_reserve(
            slices,
            target_index,
            normalized_punctuation_indices,
            normalized_skip_connector_indices,
        )
        if reserve_index is not None:
            widths[target_index], slices[target_index] = apply_target_connector_reserve(
                slices[target_index],
                widths[target_index],
                reserve_index,
            )
        target_start = slices[target_index].start
        target_content_start = target_start + int(
            rows[target_index][target_start].event.kind == MusicTokenKind.BARLINE
        )
        target = slices[target_index].widths
        if normalized_natural_widths is not None:
            target = _rescale_measure_widths(
                target,
                normalized_natural_widths[bar_ordinal],
            )
            widths[target_index][target_start : slices[target_index].end] = target
            slices[target_index] = MeasureSlice(
                slices[target_index].start,
                slices[target_index].end,
                tuple(target),
            )
        target_total, _unused_target_deficit = target_total_and_deficit(target, target)
        for voice_index, measure_slice in enumerate(slices):
            start = measure_slice.start
            end = measure_slice.end
            current = measure_slice.widths
            _unused_total, deficit = target_total_and_deficit(target, current)
            if voice_index == target_index or deficit <= GEOMETRY_EPSILON:
                continue
            current_content_start = start + int(
                rows[voice_index][start].event.kind == MusicTokenKind.BARLINE
            )
            current_content = rows[voice_index][current_content_start:end]
            target_content = rows[target_index][
                target_content_start : bar_indices[target_index][bar_ordinal]
            ]
            replacement = reconcile_shared_measure_voice_widths(
                target,
                current,
                target_content,
                current_content,
                context=MeasureReconciliationContext(
                    target_row=rows[target_index],
                    current_row=rows[voice_index],
                    target_start=target_start,
                    target_end=bar_indices[target_index][bar_ordinal],
                    current_start=start,
                    current_end=end,
                    target_voice_index=target_index,
                    current_voice_index=voice_index,
                    bar_ordinal=bar_ordinal,
                    final_bar_ordinal=len(bar_indices[0]) - 1,
                    deficit=deficit,
                    punctuation_voice=punctuation_voice,
                    terminal_punctuation_by_row=normalized_terminal_punctuation,
                    punctuation_indices_by_row=normalized_punctuation_indices,
                    skip_indices_by_row=normalized_skip_indices,
                    uses_shifted_voice_grid=uses_shifted_voice_grid,
                    uses_compact_four_voice_grid=uses_compact_four_voice_grid,
                    uses_primary_spanning_hook_grid=uses_primary_spanning_hook_grid,
                    uses_primary_parallel_voice_denominator=(
                        uses_primary_parallel_voice_denominator
                    ),
                    allows_partial_boundaries=allows_partial_boundaries,
                    allows_shorter_measure_projection=allows_shorter_measure_projection,
                    terminal_cap=profiles[voice_index].raw_terminal_width,
                ),
            )
            widths[voice_index][start:end] = replacement
    return [tuple(items) for items in widths]


def _normalize_natural_measure_widths(
    natural_widths: Sequence[float] | None,
    bar_indices: Sequence[Sequence[int]],
    widths: Sequence[Sequence[float]],
) -> tuple[float, ...] | None:
    """Scale natural beat-grid widths to the current shared interval budget."""
    if natural_widths is None or not natural_widths:
        return None
    measure_count = len(bar_indices[0]) if bar_indices else 0
    if len(natural_widths) != measure_count or any(width <= 0 for width in natural_widths):
        return None
    current_totals: list[float] = []
    starts = [0] * len(bar_indices)
    for ordinal in range(measure_count):
        totals: list[float] = []
        for row_index, indices in enumerate(bar_indices):
            end = indices[ordinal]
            totals.append(sum(widths[row_index][starts[row_index] : end]))
            starts[row_index] = end
        current_totals.append(max(totals, default=0.0))
    natural_total = sum(natural_widths)
    current_total = sum(current_totals)
    if natural_total <= 0 or current_total <= 0:
        return None
    scale = current_total / natural_total
    return tuple(width * scale for width in natural_widths)


def _rescale_measure_widths(
    widths: Sequence[float], target_total: float
) -> tuple[float, ...]:
    """Keep a target row's interval shape while changing its measure total."""
    current_total = sum(widths)
    if not widths or current_total <= 0:
        return tuple(widths)
    scale = target_total / current_total
    return tuple(width * scale for width in widths)
