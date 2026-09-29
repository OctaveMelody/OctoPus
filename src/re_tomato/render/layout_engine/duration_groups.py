"""Duration-slash group discovery for row and intrinsic layout policies."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent


def duration_group_positions(
    row: Sequence[LayoutEvent],
    *,
    beat_duration: Fraction = Fraction(1, 1),
) -> tuple[frozenset[int], frozenset[int]]:
    """Return duration-group members and terminal positions in source order.

    Groups close at each beat boundary.  In compound eighth-note meters the
    beat is a dotted quarter note (three eighths), so slashed runs group per
    compound beat instead of per whole-note unit; this matches the reference
    width pattern where the last slashed event of each beat keeps the full
    step and the others inside the beat share the short step.
    """
    members: set[int] = set()
    terminals: set[int] = set()
    group: list[int] = []
    progress = Fraction(0, 1)
    for index, item in enumerate(row):
        event = item.event
        if event.kind == MusicTokenKind.BARLINE:
            _record_duration_group(group, members, terminals)
            progress = Fraction(0, 1)
            continue
        if event.duration is None:
            continue
        duration = Fraction(event.duration.numerator, event.duration.denominator)
        if event.duration_slashes:
            group.append(index)
        progress += duration
        continues = any(
            "~" in text
            for text in (event.source_code, event.render_code, event.code, event.raw)
            if text
        )
        if progress >= beat_duration and not continues:
            if (
                beat_duration > 1
                and group
                and _suppresses_beat_terminal(row, group[-1])
            ):
                # A slashed event tied from a longer (unslashed) note closes
                # the beat as part of one merged unit; while short notes keep
                # running into the next beat the reference keeps the plain
                # step there instead of the terminal bump.
                members.update(group)
                group.clear()
            else:
                _record_duration_group(group, members, terminals)
        if progress >= beat_duration:
            progress %= beat_duration
    _record_duration_group(group, members, terminals)
    return frozenset(members), frozenset(terminals)


def _suppresses_beat_terminal(row: Sequence[LayoutEvent], index: int) -> bool:
    """Return whether the beat-boundary event suppresses its terminal bump.

    A slashed event tied from an immediately prior unslashed note closes the
    beat as part of one merged unit.  The reference keeps the plain step
    there only while short notes keep running into the next beat; when the
    following event is itself a long (unslashed) note the boundary keeps the
    full terminal step.
    """
    if index == 0 or index + 1 >= len(row):
        return False
    previous = row[index - 1].event
    following = row[index + 1].event
    if following.kind != MusicTokenKind.NOTE:
        return False
    return previous.duration_slashes == 0 and following.duration_slashes > 0 and any(
        "~" in text
        for text in (previous.source_code, previous.render_code, previous.code, previous.raw)
        if text
    )


def _record_duration_group(
    group: list[int],
    members: set[int],
    terminals: set[int],
) -> None:
    if not group:
        return
    members.update(group)
    terminals.add(group[-1])
    group.clear()


__all__ = ["duration_group_positions"]
