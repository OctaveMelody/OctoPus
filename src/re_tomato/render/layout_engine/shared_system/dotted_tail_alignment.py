"""Final shared-onset alignment for dotted phrase tails."""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ..hidden.hidden_streams import event_duration_fraction
from ..rows.row_signatures import row_event_onsets
from .models import SharedProjectionPlan


def align_elevated_dotted_tail_subdivision(plan: SharedProjectionPlan) -> None:
    """Snap one elevated dotted-tail subdivision to its companion onset owner."""

    rows = plan.request.rows
    lyric_text_by_voice = plan.request.lyric_text_by_voice
    if (
        len(rows) != 2
        or len({len(row) for row in rows}) == 1
        or any(row[-1].event.code != "|" for row in rows)
        or not all(lyric_text_by_voice.get(row[0].voice) for row in rows)
    ):
        return
    candidates = [
        (row_index, item_index)
        for row_index, row in enumerate(rows)
        for item_index in range(1, len(row) - 1)
        if row[item_index - 1].event.octave > 0
        and row[item_index - 1].event.duration_dots == 1
        and row[item_index - 1].event.duration_slashes == 0
        and row[item_index].event.duration_slashes == 1
        and row[item_index + 1].event.kind == MusicTokenKind.BARLINE
    ]
    if len(candidates) != 1:
        return
    row_index, item_index = candidates[0]
    row = rows[row_index]
    onsets = row_event_onsets(row)
    owner_onset = onsets[item_index] - event_duration_fraction(row[item_index].event)
    companion = rows[1 - row_index]
    companion_onsets = row_event_onsets(companion)
    owners = [
        item
        for item, onset in zip(companion, companion_onsets, strict=True)
        if onset == owner_onset and item.event.kind != MusicTokenKind.BARLINE
    ]
    if len(owners) != 1:
        return
    row[item_index].x = owners[0].x
    row[item_index].style_x = owners[0].style_x


__all__ = ["align_elevated_dotted_tail_subdivision"]
