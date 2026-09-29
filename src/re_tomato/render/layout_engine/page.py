"""Lay out a score page and apply final endpoint and page-height adjustments."""

from __future__ import annotations

from re_tomato.normalization.types import ScoreModel
from re_tomato.render.compatibility_identity import compatibility_profile_key
from re_tomato.render.core.layout_metrics import page_metrics
from re_tomato.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
)
from re_tomato.render.layout_engine.constructs import (
    retarget_unresolved_endpoint_starts as _retarget_unresolved_endpoint_starts,
)
from re_tomato.render.layout_engine.first_tie_lift import plan_first_tie_lift_rows
from re_tomato.render.layout_engine.header import compute_header
from re_tomato.render.layout_engine.lyrics.lyric_selection import (
    is_supported_legacy_lyric_line as _is_supported_legacy_lyric_line,
)
from re_tomato.render.layout_engine.page_fit import fit_page_height as _fit_page_height
from re_tomato.render.layout_engine.spacing.vertical_spacing import (
    multi_voice_leading_clearance as _multi_voice_leading_clearance,
)
from re_tomato.render.layout_engine.system import _layout_system


def layout_page(model: ScoreModel, page_index: int) -> LayoutPage:
    metrics = page_metrics(model)
    compatibility_key = compatibility_profile_key(
        code=model.code,
        custom_code=model.custom_code,
        page_config=model.page_config,
    )
    if page_index >= len(model.pages):
        return LayoutPage(
            metrics=metrics,
            page_index=page_index + 1,
            compatibility_key=compatibility_key,
            header=compute_header(model),
        )

    page_model = model.pages[page_index]
    layout = LayoutPage(
        metrics=metrics,
        page_index=page_index + 1,
        compatibility_key=compatibility_key,
        header=compute_header(model),
        source_voice_by_line=dict(model.source_voice_by_line),
        unresolved_span_states=model.unresolved_span_states,
    )
    page_uses_legacy_intrinsic_grid = any(
        any(
            voice.voice == 0
            and
            _is_supported_legacy_lyric_line(lyric)
            for lyric in voice.lyrics
        )
        for system in page_model.systems
        for voice in system.voices
    )
    if page_index == 0:
        current_y = float(metrics.music_start_y - (0 if layout.header.tempo else 30))
        if page_model.systems:
            current_y += _multi_voice_leading_clearance(page_model.systems[0])
    else:
        current_y = float(metrics.continuation_music_start_y)
        if page_model.systems:
            current_y += _multi_voice_leading_clearance(page_model.systems[0])

    visual_line = 1
    previous_visible_lyric_events: list[LayoutEvent] = []
    for system_index, system in enumerate(page_model.systems, start=1):
        current_y, visual_line, previous_visible_lyric_events = _layout_system(
            model=model,
            page_index=page_index,
            system_index=system_index,
            system=system,
            metrics=metrics,
            layout=layout,
            page_uses_legacy_intrinsic_grid=page_uses_legacy_intrinsic_grid,
            current_y=current_y,
            visual_line=visual_line,
            previous_visible_lyric_events=previous_visible_lyric_events,
        )
    _retarget_unresolved_endpoint_starts(layout)
    _fit_page_height(layout)
    layout.first_tie_lift_rows = plan_first_tie_lift_rows(model, page_index, layout)
    return layout
