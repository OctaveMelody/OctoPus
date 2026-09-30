"""Page overflow projection applied after layout geometry is assembled."""

from __future__ import annotations

from ..core.layout_types import LayoutPage
from .profiles import PageFitProfile


def fit_page_height(layout: LayoutPage) -> None:
    """Project vertical positions when the completed page exceeds its bottom bound."""

    bottom = float(layout.metrics.height - layout.metrics.margin_bottom)
    non_lyric_positions = tuple(
        [event.y for event in layout.events]
        + [event.y for event in layout.hidden_events]
        + [brace.y_top for brace in layout.voice_braces]
        + [brace.y_bottom for brace in layout.voice_braces]
        + [caption.y for caption in layout.voice_captions]
    )
    # ``music_start_y`` describes the nominal first-page header profile.  It is
    # not the origin of continuation pages, and it can be shifted by leading
    # construct/voice clearance.  Anchor the projection to the geometry that
    # was actually laid out so the first row remains fixed during compression.
    origin = min(non_lyric_positions, default=float(layout.metrics.music_start_y))
    profile = PageFitProfile(
        bottom=bottom,
        start=origin,
        lyric_tolerance=float(layout.metrics.lyric_size),
        non_lyric_positions=non_lyric_positions,
        lyric_positions=tuple(lyric.y for lyric in layout.lyrics),
    )
    if profile.scale is None:
        return
    for event in layout.events:
        event.y = profile.project_y(event.y)
    for event in layout.hidden_events:
        event.y = profile.project_y(event.y)
    for lyric in layout.lyrics:
        lyric.y = profile.project_y(lyric.y)
    for brace in layout.voice_braces:
        brace.y_top = profile.project_y(brace.y_top)
        brace.y_bottom = profile.project_y(brace.y_bottom)
    for caption in layout.voice_captions:
        caption.y = profile.project_y(caption.y)


__all__ = ["fit_page_height"]
