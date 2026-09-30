"""Projection-plan builders for event-keyed shared grids."""

from __future__ import annotations

from fractions import Fraction

from octopus.render.core.layout_types import LayoutEvent, PageMetrics
from octopus.render.layout_engine.grid.beat_grid import (
    SharedGridRow,
    compression_scale,
    four_voice_majority_beat_shape,
    project_shared_grid,
)
from octopus.render.layout_engine.grid.shared_grid_policies import (
    uses_four_voice_majority_beat_grid,
)

from .alternating_dsb_shadow_grid import (
    build_alternating_dual_verse_trailing_dsb_shadow_grid,
    build_four_row_six_measure_trailing_dsb_shadow_grid,
)
from .dsb_shadow_grid import (
    build_coherent_mixed_dsb_shadow_grid,
    build_complete_midrow_dsb_shadow_grid,
)
from .models import LyricTextByVoice, SharedProjectionPlan, SharedProjectionRequest


def build_grid_owned_projection_plan(
    *,
    rows: list[list[LayoutEvent]],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
) -> SharedProjectionPlan | None:
    if not rows or len({row[0].voice for row in rows if row}) != len(rows):
        return None
    grid_rows = tuple(
        SharedGridRow(
            row[0].voice,
            tuple(item.event for item in row),
            lyric_text_by_voice.get(row[0].voice, {}),
        )
        for row in rows
        if row
    )
    if len(grid_rows) != len(rows):
        return None
    majority_beat_shape = (
        four_voice_majority_beat_shape(
            tuple(tuple(item.event for item in row) for row in rows)
        )
        if uses_four_voice_majority_beat_grid(rows, lyric_text_by_voice)
        else None
    )
    projection = project_shared_grid(
        grid_rows,
        majority_beat_shape=majority_beat_shape,
    )
    if not projection.barline_x_offsets:
        return None
    right = float(metrics.width - metrics.margin_right + 3)
    # A grace marker on the system's first column moves the note-start x
    # right by its stretched reservation (oracle-verified 2026-08-23, probes
    # H1/H2 and Looking-Back p3 L93-L98: left edge 117 -> 124 for a [2]).
    left = float(left) + projection.grace_left_delta
    # Unquoted grace markers reserve stretched width in front of their host
    # notes; the reference solves the compression scale with that width taken
    # out of the available space (oracle-verified 2026-08-23, probe P1 and the
    # stretched Looking-Back p1 rows 14-17 system).
    scale = compression_scale(
        right - left - projection.grace_reservation_total,
        float(projection.natural_width),
    )
    request = _grid_projection_request(
        rows=rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=lyric_text_by_voice,
    )
    return SharedProjectionPlan(
        request=request,
        reconciled_widths=[],
        grace_timeline=(),
        profile_denominators=(),
        right=right,
        scale=scale,
        shared_anchor_offset=0.0,
        uses_measure_origin_spacing=False,
        grid_projection=projection,
        grid_owned=True,
    )


def build_dsb_shadow_grid_projection_plan(
    *,
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
    grid_lyric_text_by_voice: LyricTextByVoice | None = None,
) -> SharedProjectionPlan | None:
    """Build a typed complete or coherent mixed-length DSB shadow-owner projection."""

    shadow_grid = build_complete_midrow_dsb_shadow_grid(rows, hidden_events)
    request_lyric_text_by_voice = lyric_text_by_voice
    if shadow_grid is None:
        shadow_grid = build_coherent_mixed_dsb_shadow_grid(rows, hidden_events)
    if shadow_grid is None:
        request_lyric_text_by_voice = (
            grid_lyric_text_by_voice
            if grid_lyric_text_by_voice is not None
            else lyric_text_by_voice
        )
        shadow_grid = build_alternating_dual_verse_trailing_dsb_shadow_grid(
            rows,
            hidden_events,
            left=left,
            lyric_text_by_voice=request_lyric_text_by_voice,
        )
    if shadow_grid is None:
        shadow_grid = build_four_row_six_measure_trailing_dsb_shadow_grid(
            rows,
            hidden_events,
            left=left,
            lyric_text_by_voice=request_lyric_text_by_voice,
        )
    if shadow_grid is None:
        return None
    right = float(metrics.width - metrics.margin_right + 3)
    denominator = (
        shadow_grid.projection.natural_width
        + shadow_grid.total_reserve
        + Fraction(25)
    )
    scale = (right - left + 14.0) / float(denominator)
    if scale >= 20.0 / 13.0:
        return None
    request = _grid_projection_request(
        rows=rows,
        metrics=metrics,
        left=left,
        lyric_text_by_voice=request_lyric_text_by_voice,
    )
    return SharedProjectionPlan(
        request=request,
        reconciled_widths=[],
        grace_timeline=(),
        profile_denominators=(float(denominator),) * len(rows),
        right=right,
        scale=scale,
        shared_anchor_offset=0.0,
        uses_measure_origin_spacing=False,
        grid_projection=shadow_grid.projection,
        grid_owned=True,
        dsb_shadow_grid=shadow_grid,
    )


def _grid_projection_request(
    *,
    rows: list[list[LayoutEvent]],
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
) -> SharedProjectionRequest:
    return SharedProjectionRequest(
        rows=rows,
        profiles=[],
        reconciled_widths=[],
        metrics=metrics,
        left=left,
        origin_offset=left - metrics.note_start_x,
        lyric_text_by_voice=lyric_text_by_voice,
        shared_grace_raw={},
        skip_indices_by_row=[frozenset() for _ in rows],
        shared_leading_accidental_reserve=0.0,
    )


__all__ = [
    "build_dsb_shadow_grid_projection_plan",
    "build_grid_owned_projection_plan",
]
