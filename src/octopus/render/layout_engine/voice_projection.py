"""Coordinate ordinary and syllabic row projection, including cross-row carry."""

from __future__ import annotations

from dataclasses import replace

from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import (
    LayoutEvent,
    PageMetrics,
)
from octopus.render.layout_engine.cross_row_hooks import (
    plan_cross_row_hooks as _plan_cross_row_hooks,
)
from octopus.render.layout_engine.grid.grid_policies import (
    lyricless_alternating_extension_reserve_count as _alternating_extension_reserve_count,
)
from octopus.render.layout_engine.grid.grid_policies import (
    uses_lyricless_intrinsic_entry_grid as _uses_lyricless_intrinsic_entry_grid,
)
from octopus.render.layout_engine.intrinsic.builder import _uses_cjk_dual_verse_four_four_grid
from octopus.render.layout_engine.rows.row_projection import (
    project_ordinary_row as _project_ordinary_row,
)
from octopus.render.layout_engine.streams import uses_compound_meter as _uses_compound_meter
from octopus.render.layout_engine.syllabic.models import SyllabicRowRequest
from octopus.render.layout_engine.syllabic.planning import build_syllabic_projection_plan
from octopus.render.layout_engine.syllabic.projection import project_syllabic_row


def _justify_voice_rows(
    events: list[LayoutEvent],
    metrics: PageMetrics,
    *,
    note_start_x: float | None = None,
    grace_host_indices: frozenset[int] = frozenset(),
    grace_raw_by_host: dict[int, str] | None = None,
    reserves_lyric_dotted_notes: bool = False,
    legacy_intrinsic_source_lines: frozenset[int] = frozenset(),
    numbered_lyric_source_lines: frozenset[int] = frozenset(),
    legacy_lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]] | None = None,
    selects_structural_intrinsic_entries: bool = True,
) -> None:
    by_line: dict[int, list[LayoutEvent]] = {}
    for event in events:
        by_line.setdefault(event.line, []).append(event)
    left = metrics.note_start_x if note_start_x is None else note_start_x
    right = float(metrics.width - metrics.margin_right + 3)
    previous_legacy_scale: float | None = None
    rows = list(by_line.values())
    hook_plan = _plan_cross_row_hooks(rows, legacy_lyric_text_by_event or {})
    lyricless_cross_row_hook_indices = hook_plan.lyricless_rows
    lyricless_cross_row_hook_width_adjustments = hook_plan.width_adjustments
    lyric_to_lyricless_hook_width_adjustments = hook_plan.lyric_to_lyricless_adjustments
    lyric_to_lyricless_hook_openers = hook_plan.lyric_to_lyricless_openers
    uses_lyricless_cross_row_cursor = hook_plan.uses_lyricless_cursor
    for row_index, row in enumerate(rows):
        if len(row) < 2:
            continue
        natural_left = row[0].x
        natural_right = row[-1].x
        if natural_right <= natural_left:
            continue
        target_left = (
            left
            + (10 if "zkh" in row[0].event.decorations else 0)
            + (
                7 * (1 + row[0].event.duration_slashes)
                if row[0].event.index in grace_host_indices
                else 0
            )
        )
        legacy_short_row = natural_right - natural_left < (right - left) * 0.7
        if legacy_short_row:
            legacy_shift = target_left - natural_left
            for event in row:
                event.style_x = event.x + legacy_shift
        alternating_extension_reserve_count = (
            _alternating_extension_reserve_count(
                row,
                legacy_lyric_text_by_event or {},
            )
            if selects_structural_intrinsic_entries
            else 0
        )
        uses_structural_intrinsic_entry_grid = (
            selects_structural_intrinsic_entries
            and _uses_lyricless_intrinsic_entry_grid(
                row,
                legacy_lyric_text_by_event or {},
            )
        )
        if (
            row[0].event.span.start.line in legacy_intrinsic_source_lines
            or uses_structural_intrinsic_entry_grid
        ):
            opening_cross_row_hook_reserve = (
                9.0
                if "zkh" in row[0].event.decorations
                and row[0].event.duration_slashes
                and (
                    row[0].event.octave < 0
                    or row[0].event.kind == MusicTokenKind.REST
                    or (
                        _uses_compound_meter(metrics.time_sig)
                        and len(row) > 1
                        and row[1].event.kind == MusicTokenKind.BARLINE
                    )
                )
                and not any(
                    text
                    for item in row
                    for text in (legacy_lyric_text_by_event or {}).get(
                        (item.event.span.start.line, item.event.index),
                        (),
                    )
                )
                and not any("ykh" in item.event.decorations for item in row)
                and row_index + 1 < len(rows)
                and any(
                    "ykh" in item.event.decorations
                    for item in rows[row_index + 1]
                )
                else 0.0
            )
            terminal_cross_row_hook = (
                True
                if "zkh" in row[-2].event.decorations
                and not row[-2].event.duration_slashes
                and not any("ykh" in item.event.decorations for item in row)
                and any(
                    "ykh" in item.event.decorations
                    for later_row in rows[row_index + 1 :]
                    for item in later_row
                )
                else False
            )
            dual_verse_continuation_adjustment = (
                -9.0
                if row_index > 0
                and row[-1].event.code == "|"
                and "zkh" not in row[0].event.decorations
                and _uses_cjk_dual_verse_four_four_grid(
                    metrics,
                    legacy_lyric_text_by_event or {},
                )
                else 0.0
            )
            previous_legacy_scale = _justify_legacy_syllabic_row(
                row,
                metrics=metrics,
                left=left,
                right=right,
                lyric_text_by_event=legacy_lyric_text_by_event or {},
                grace_host_indices=grace_host_indices,
                grace_raw_by_host=grace_raw_by_host or {},
                reserves_lyric_dotted_notes=reserves_lyric_dotted_notes,
                uses_numbered_cjk_verse_label=(
                    row[0].event.span.start.line in numbered_lyric_source_lines
                ),
                intrinsic_width_adjustment=(
                    opening_cross_row_hook_reserve
                    + (9.0 if terminal_cross_row_hook else 0.0)
                    + dual_verse_continuation_adjustment
                    + lyricless_cross_row_hook_width_adjustments.get(row_index, 0.0)
                    + lyric_to_lyricless_hook_width_adjustments.get(row_index, 0.0)
                    - 9.0 * alternating_extension_reserve_count
                    + (
                        20.0
                        if row[0].event.span.start.line
                        in numbered_lyric_source_lines
                        else 0.0
                    )
                ),
                uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                terminal_cross_row_hook=terminal_cross_row_hook,
                localizes_cross_row_hook_opener=(
                    row_index in lyric_to_lyricless_hook_openers
                ),
                uses_lyricless_cross_row_compound_grid=(
                    row_index in lyricless_cross_row_hook_indices
                ),
                uses_undivided_cross_row_hook_transfer=(
                    row_index in lyricless_cross_row_hook_width_adjustments
                ),
            )
            continue
        if (
            row[-1].event.code == "|j"
            and previous_legacy_scale is not None
        ):
            if natural_right - natural_left <= right - target_left:
                inherited_scale = _justify_legacy_syllabic_row(
                    row,
                    metrics=metrics,
                    left=left,
                    right=right,
                    lyric_text_by_event=legacy_lyric_text_by_event or {},
                    scale=previous_legacy_scale,
                    ragged=True,
                    grace_host_indices=grace_host_indices,
                    grace_raw_by_host=grace_raw_by_host or {},
                    uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                )
                if inherited_scale is not None:
                    continue
                previous_legacy_scale = _justify_legacy_syllabic_row(
                    row,
                    metrics=metrics,
                    left=left,
                    right=right,
                    lyric_text_by_event=legacy_lyric_text_by_event or {},
                    grace_host_indices=grace_host_indices,
                    grace_raw_by_host=grace_raw_by_host or {},
                    uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                )
                continue
            else:
                previous_legacy_scale = _justify_legacy_syllabic_row(
                    row,
                    metrics=metrics,
                    left=left,
                    right=right,
                    lyric_text_by_event=legacy_lyric_text_by_event or {},
                    grace_host_indices=grace_host_indices,
                    grace_raw_by_host=grace_raw_by_host or {},
                    uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                )
                continue
        previous_legacy_scale = None
        if (
            row[-1].event.code == "|j"
            and natural_right - natural_left <= right - target_left
        ):
            shift = target_left - natural_left
            for event in row:
                event.x += shift
            continue
        _project_ordinary_row(
            row,
            natural_left=natural_left,
            natural_right=natural_right,
            target_left=target_left,
            right=right,
            grace_raw_by_host=grace_raw_by_host or {},
        )


def _justify_legacy_syllabic_row(
    row: list[LayoutEvent],
    *,
    metrics: PageMetrics,
    left: float,
    right: float,
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
    scale: float | None = None,
    ragged: bool = False,
    grace_host_indices: frozenset[int] = frozenset(),
    grace_raw_by_host: dict[int, str] | None = None,
    reserves_lyric_dotted_notes: bool = False,
    uses_numbered_cjk_verse_label: bool = False,
    intrinsic_width_adjustment: float = 0.0,
    uses_lyricless_cross_row_cursor: bool = False,
    terminal_cross_row_hook: bool = False,
    localizes_cross_row_hook_opener: bool = False,
    uses_lyricless_cross_row_compound_grid: bool = False,
    uses_undivided_cross_row_hook_transfer: bool = False,
) -> float | None:
    request = SyllabicRowRequest(
        row=row,
        metrics=metrics,
        left=left,
        right=right,
        lyric_text_by_event=lyric_text_by_event,
        requested_scale=scale,
        ragged=ragged,
        grace_host_indices=grace_host_indices,
        grace_raw_by_host=grace_raw_by_host or {},
        reserves_lyric_dotted_notes=reserves_lyric_dotted_notes,
        uses_numbered_cjk_verse_label=uses_numbered_cjk_verse_label,
        intrinsic_width_adjustment=intrinsic_width_adjustment,
        uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
        terminal_cross_row_hook=terminal_cross_row_hook,
        localizes_cross_row_hook_opener=localizes_cross_row_hook_opener,
        uses_lyricless_cross_row_compound_grid=uses_lyricless_cross_row_compound_grid,
        uses_undivided_cross_row_hook_transfer=uses_undivided_cross_row_hook_transfer,
    )
    style_row = [replace(item) for item in row]
    style_source_row = (
        style_row[:-1]
        if style_row[-1].event.code == "|w"
        else style_row
    )
    _justify_voice_rows(
        style_source_row,
        metrics,
        note_start_x=left,
        selects_structural_intrinsic_entries=False,
    )
    style_positions = [
        item.style_x if item.style_x is not None else item.x
        for item in style_row
    ]
    projection_plan = build_syllabic_projection_plan(request, tuple(style_positions))
    if projection_plan is None:
        return None
    project_syllabic_row(projection_plan)
    return projection_plan.scale
