"""Scoped union projection for alternating dual-verse trailing DSB systems."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from types import MappingProxyType

from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout_engine.grid.beat_grid import (
    TIMED_KINDS,
    GridEventKey,
    SharedGridRow,
    project_shared_grid,
)

from ....parser.ast import MusicTokenKind
from .dsb_shadow_grid import (
    DSB_BOUNDARY_RESERVE,
    _boundary_adjustment,
    _hidden_offsets,
)
from .models import DsbShadowGridProjection, LyricTextByVoice


def build_alternating_dual_verse_trailing_dsb_shadow_grid(
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
    *,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
) -> DsbShadowGridProjection | None:
    """Build the scoped c8 trailing shadow for alternating dual-verse rows.

    The admitted shape has four common-origin rows, identical eight-bar
    topology, two lyric streams on rows zero and two, and one two-measure
    hidden block that runs from its anchor through the authority's final
    visible barlines.  It is intentionally separate from the lyricless M-6a
    continuation owner and from the coherent multi-owner rule.
    """
    if len(rows) != 4 or any(not row for row in rows):
        return None
    if len({len(row) for row in rows}) != 1:
        return None
    if any(row[0].x != left for row in rows):
        return None
    if any(item.event.grace_reservation for row in rows for item in row):
        return None
    allowed_kinds = {MusicTokenKind.BARLINE, *TIMED_KINDS}
    if any(item.event.kind not in allowed_kinds for row in rows for item in row):
        return None
    barline_positions = {
        tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        for row in rows
    }
    if len(barline_positions) != 1:
        return None
    barline_position = next(iter(barline_positions))
    if len(barline_position) != 8:
        return None

    row_voices = {row[0].voice for row in rows}
    source_lines = {
        item.event.span.start.line
        for row in rows
        for item in row
    }
    filtered_lyrics = {
        voice: {
            key: texts
            for key, texts in text_by_event.items()
            if key[0] in source_lines
        }
        for voice, text_by_event in lyric_text_by_voice.items()
        if voice in row_voices
    }
    visible_lyric_rows = tuple(
        any(
            text
            for texts in filtered_lyrics.get(row[0].voice, {}).values()
            for text in texts
        )
        for row in rows
    )
    if visible_lyric_rows != (True, False, True, False):
        return None
    for row, owns_lyrics in zip(rows, visible_lyric_rows, strict=True):
        text_by_event = filtered_lyrics.get(row[0].voice, {})
        if not owns_lyrics:
            continue
        if not text_by_event or any(
            len(texts) != 2 for texts in text_by_event.values()
        ):
            return None

    row_by_owner = {(row[0].voice, row[0].line): row for row in rows}
    if len(row_by_owner) != len(rows):
        return None
    hidden_groups: dict[
        tuple[int, int, tuple[str, ...]], list[LayoutEvent]
    ] = defaultdict(list)
    for item in hidden_events:
        block_ids = tuple(
            construct_id
            for construct_id in item.event.construct_ids
            if ":block:" in construct_id
        )
        if item.block == "dsb-hidden" and block_ids:
            hidden_groups[(item.voice, item.line, block_ids)].append(item)
    if len(hidden_groups) != 1:
        return None
    (voice, line, _block_ids), group_items = next(iter(hidden_groups.items()))
    owner_row = row_by_owner.get((voice, line))
    if owner_row is None:
        return None
    hidden_group = tuple(
        sorted(group_items, key=lambda item: item.event.span.start.offset)
    )
    if (
        sum(item.event.kind == MusicTokenKind.BARLINE for item in hidden_group) != 2
        or hidden_group[-1].event.kind != MusicTokenKind.BARLINE
        or any(item.event.kind not in allowed_kinds for item in hidden_group)
    ):
        return None

    anchors = [
        index
        for index, item in enumerate(owner_row)
        if item.event.kind == MusicTokenKind.BARLINE
        and "&dsb_a" in (item.event.code or "")
    ]
    if len(anchors) != 1:
        return None
    anchor_index = anchors[0]
    anchor_ordinal = _barline_ordinal(owner_row, anchor_index)
    final_barline_ordinal = len(barline_position) - 1
    if anchor_ordinal + 2 != final_barline_ordinal:
        return None
    trailing_barlines = [
        item
        for item in owner_row[anchor_index + 1 :]
        if item.event.kind == MusicTokenKind.BARLINE
    ]
    if len(trailing_barlines) != 2 or any(
        item.block != "dsb-tail" for item in trailing_barlines
    ):
        return None

    visible_rows = tuple(
        SharedGridRow(
            row[0].voice,
            tuple(item.event for item in row),
            filtered_lyrics.get(row[0].voice, {}),
        )
        for row in rows
    )
    shadow_voice = max(row.voice_index for row in visible_rows) + 1
    shadow = SharedGridRow(
        shadow_voice,
        tuple(item.event for item in owner_row[: anchor_index + 1])
        + tuple(item.event for item in hidden_group),
        filtered_lyrics.get(voice, {}),
    )
    projection = project_shared_grid((*visible_rows, shadow))
    if not projection.barline_x_offsets:
        return None

    anchor_ordinals = {anchor_ordinal}
    close_ordinals: set[int] = set()
    visible_event_adjustments: dict[GridEventKey, Fraction] = {}
    for grid_row, row in zip(visible_rows, rows, strict=True):
        barline_ordinal = -1
        for item in row:
            if item.event.kind == MusicTokenKind.BARLINE:
                barline_ordinal += 1
                continue
            key = GridEventKey.for_event(item.event, grid_row.voice_index)
            visible_event_adjustments[key] = _boundary_adjustment(
                barline_ordinal,
                after_current_barline=True,
                anchor_ordinals=anchor_ordinals,
                close_ordinals=close_ordinals,
            )
    barline_adjustments = tuple(
        _boundary_adjustment(
            ordinal,
            after_current_barline=False,
            anchor_ordinals=anchor_ordinals,
            close_ordinals=close_ordinals,
        )
        for ordinal in range(len(projection.barline_x_offsets))
    )
    hidden_event_offsets = _hidden_offsets(
        [(shadow, (voice, line), hidden_group)],
        projection=projection,
        anchor_ordinals=anchor_ordinals,
        close_ordinals=close_ordinals,
        visible_accidental_offsets=frozenset(
            offset
            for row in visible_rows
            for event in row.events
            if event.accidental is not None
            for offset in (
                projection.event_x_offsets.get(
                    GridEventKey.for_event(event, row.voice_index)
                ),
            )
            if offset is not None
        ),
    )
    return DsbShadowGridProjection(
        projection=projection,
        visible_event_adjustments=MappingProxyType(visible_event_adjustments),
        barline_adjustments=barline_adjustments,
        hidden_event_offsets=MappingProxyType(hidden_event_offsets),
        total_reserve=DSB_BOUNDARY_RESERVE,
        hidden_event_right_pins=frozenset({(voice, line, hidden_group[-1].event.index)}),
    )


def build_four_row_six_measure_trailing_dsb_shadow_grid(
    rows: list[list[LayoutEvent]],
    hidden_events: tuple[LayoutEvent, ...],
    *,
    left: float,
    lyric_text_by_voice: LyricTextByVoice,
) -> DsbShadowGridProjection | None:
    """Build the scoped c9 six-measure trailing shadow.

    This owner is distinct from the c8 alternating lyric shape: it has four
    eight-bar rows, a single six-measure hidden group owned by the third row,
    and no hidden/visible topology before the second visible barline.  The
    system lyric map is retained for the union so lyric ownership stays
    source-derived even though the admitted Hulunbuir shape's natural width
    is unchanged by it.
    """
    if len(rows) != 4 or any(not row for row in rows):
        return None
    if any(row[0].x != left for row in rows):
        return None
    if any(item.event.grace_reservation for row in rows for item in row):
        return None
    allowed_kinds = {MusicTokenKind.BARLINE, *TIMED_KINDS}
    if any(item.event.kind not in allowed_kinds for row in rows for item in row):
        return None
    if {
        sum(item.event.kind == MusicTokenKind.BARLINE for item in row)
        for row in rows
    } != {8}:
        return None

    row_by_owner = {(row[0].voice, row[0].line): row for row in rows}
    if len(row_by_owner) != len(rows):
        return None
    hidden_groups: dict[
        tuple[int, int, tuple[str, ...]], list[LayoutEvent]
    ] = defaultdict(list)
    for item in hidden_events:
        block_ids = tuple(
            construct_id
            for construct_id in item.event.construct_ids
            if ":block:" in construct_id
        )
        if item.block == "dsb-hidden" and block_ids:
            hidden_groups[(item.voice, item.line, block_ids)].append(item)
    if len(hidden_groups) != 1:
        return None
    (voice, line, _block_ids), group_items = next(iter(hidden_groups.items()))
    owner_row = row_by_owner.get((voice, line))
    if owner_row is None:
        return None
    owner_index = next(
        index
        for index, row in enumerate(rows)
        if row[0].voice == voice and row[0].line == line
    )
    if owner_index != 2:
        return None
    hidden_group = tuple(
        sorted(group_items, key=lambda item: item.event.span.start.offset)
    )
    hidden_bar_count = sum(
        item.event.kind == MusicTokenKind.BARLINE for item in hidden_group
    )
    if (
        hidden_bar_count != 6
        or hidden_group[-1].event.kind != MusicTokenKind.BARLINE
        or any(item.event.kind not in allowed_kinds for item in hidden_group)
    ):
        return None

    anchors = [
        index
        for index, item in enumerate(owner_row)
        if item.event.kind == MusicTokenKind.BARLINE
        and "&dsb_a" in (item.event.code or "")
    ]
    if len(anchors) != 1:
        return None
    anchor_index = anchors[0]
    anchor_ordinal = _barline_ordinal(owner_row, anchor_index)
    if anchor_ordinal != 1:
        return None
    trailing_barlines = [
        item
        for item in owner_row[anchor_index + 1 :]
        if item.event.kind == MusicTokenKind.BARLINE
    ]
    if len(trailing_barlines) != hidden_bar_count or any(
        item.block != "dsb-tail" for item in trailing_barlines
    ):
        return None
    final_barline_ordinal = sum(
        item.event.kind == MusicTokenKind.BARLINE for item in owner_row
    ) - 1
    if anchor_ordinal + hidden_bar_count != final_barline_ordinal:
        return None
    if hidden_group[0].event.span.start.offset <= owner_row[anchor_index].event.span.start.offset:
        return None

    source_lines = {
        item.event.span.start.line
        for row in rows
        for item in row
    }
    row_voices = {row[0].voice for row in rows}
    filtered_lyrics = {
        voice: {
            key: texts
            for key, texts in text_by_event.items()
            if key[0] in source_lines
        }
        for voice, text_by_event in lyric_text_by_voice.items()
        if voice in row_voices
    }
    visible_rows = tuple(
        SharedGridRow(
            row[0].voice,
            tuple(item.event for item in row),
            filtered_lyrics.get(row[0].voice, {}),
        )
        for row in rows
    )
    shadow_voice = max(row.voice_index for row in visible_rows) + 1
    shadow = SharedGridRow(
        shadow_voice,
        tuple(item.event for item in owner_row[: anchor_index + 1])
        + tuple(item.event for item in hidden_group),
        filtered_lyrics.get(voice, {}),
    )
    projection = project_shared_grid((*visible_rows, shadow))
    if not projection.barline_x_offsets:
        return None

    anchor_ordinals = {anchor_ordinal}
    close_ordinals: set[int] = set()
    visible_event_adjustments: dict[GridEventKey, Fraction] = {}
    for grid_row, row in zip(visible_rows, rows, strict=True):
        barline_ordinal = -1
        for item in row:
            if item.event.kind == MusicTokenKind.BARLINE:
                barline_ordinal += 1
                continue
            key = GridEventKey.for_event(item.event, grid_row.voice_index)
            visible_event_adjustments[key] = _boundary_adjustment(
                barline_ordinal,
                after_current_barline=True,
                anchor_ordinals=anchor_ordinals,
                close_ordinals=close_ordinals,
            )
    barline_adjustments = tuple(
        _boundary_adjustment(
            ordinal,
            after_current_barline=False,
            anchor_ordinals=anchor_ordinals,
            close_ordinals=close_ordinals,
        )
        for ordinal in range(len(projection.barline_x_offsets))
    )
    hidden_event_offsets = _hidden_offsets(
        [(shadow, (voice, line), hidden_group)],
        projection=projection,
        anchor_ordinals=anchor_ordinals,
        close_ordinals=close_ordinals,
        visible_accidental_offsets=frozenset(
            offset
            for row in visible_rows
            for event in row.events
            if event.accidental is not None
            for offset in (
                projection.event_x_offsets.get(
                    GridEventKey.for_event(event, row.voice_index)
                ),
            )
            if offset is not None
        ),
    )
    return DsbShadowGridProjection(
        projection=projection,
        visible_event_adjustments=MappingProxyType(visible_event_adjustments),
        barline_adjustments=barline_adjustments,
        hidden_event_offsets=MappingProxyType(hidden_event_offsets),
        total_reserve=DSB_BOUNDARY_RESERVE,
        hidden_event_right_pins=frozenset({(voice, line, hidden_group[-1].event.index)}),
    )


def _barline_ordinal(row: list[LayoutEvent], item_index: int) -> int:
    return sum(
        item.event.kind == MusicTokenKind.BARLINE
        for item in row[: item_index + 1]
    ) - 1


__all__ = [
    "build_alternating_dual_verse_trailing_dsb_shadow_grid",
    "build_four_row_six_measure_trailing_dsb_shadow_grid",
]
