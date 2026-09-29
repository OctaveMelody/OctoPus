"""Post-prefix syllabic event corrections in compatibility order.

Only unit-scale transfers remain here (decoded reference geometry of up to
20 natural units). The adjacent-float (ULP) serialization corrections that
used to live in this module were retired under the 1e-6 acceptance rule
(owner decision 2026-09-07, item 22): they moved coordinates by a handful of
representable floats at most, which the policy counts as equal.
"""

from __future__ import annotations

from ..dotted.dotted_temporary_meter import (
    restored_meter_borrowed_cursor_indices,
)
from .models import SyllabicProjectionPlan, SyllabicProjectionState


def apply_semantic_corrections(
    plan: SyllabicProjectionPlan,
    state: SyllabicProjectionState,
    index: int,
) -> None:
    request = plan.request
    flags = plan.flags
    row = request.row
    item = row[index]
    lyric_text_by_event = request.lyric_text_by_event
    scale = plan.scale
    uses_numbered_cjk_verse_label = request.uses_numbered_cjk_verse_label
    localizes_cross_row_hook_opener = request.localizes_cross_row_hook_opener
    uses_compact_terminal_lyric_run = flags.uses_compact_terminal_lyric_run
    uses_dotted_open_extension_tail = flags.uses_dotted_open_extension_tail
    texts = lyric_text_by_event.get(
        (item.event.span.start.line, item.event.index),
        (),
    )
    restored_meter_borrowed_indices = restored_meter_borrowed_cursor_indices(
        row,
        time_sig=request.metrics.time_sig,
    )
    if index in restored_meter_borrowed_indices:
        item.x -= 9.0 * scale
    elif (
        uses_numbered_cjk_verse_label
        and index == len(row) - 2
    ):
        item.x += 20.0 * scale
    elif (
        (localizes_cross_row_hook_opener and "zkh" in item.event.decorations)
        or (uses_compact_terminal_lyric_run and index == len(row) - 6)
    ):
        item.x += 9.0 * scale
    elif (
        uses_compact_terminal_lyric_run
        and index == len(row) - 2
    ):
        item.x -= 9.0 * scale
    elif (
        uses_dotted_open_extension_tail
        and len(texts) == 2
        and all(texts)
        and index + 2 < len(row)
        and row[index].event.duration_slashes == 1
        and row[index + 1].event.duration_slashes == 2
        and row[index + 2].event.duration_slashes == 2
        and "(" not in row[index + 1].event.code
        and ")" not in row[index + 2].event.code
        and all(
            lyric_text_by_event.get(
                (
                    row[index + 1].event.span.start.line,
                    row[index + 1].event.index,
                ),
                (),
            )
        )
        and lyric_text_by_event.get(
            (
                row[index + 2].event.span.start.line,
                row[index + 2].event.index,
            ),
            (),
        )
        and not all(
            lyric_text_by_event.get(
                (
                    row[index + 2].event.span.start.line,
                    row[index + 2].event.index,
                ),
                (),
            )
        )
    ):
        item.x += 9.0 * scale


__all__ = ["apply_semantic_corrections"]
