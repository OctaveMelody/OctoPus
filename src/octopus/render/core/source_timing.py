"""Exact written timing and source-onset projection shared by layout and SVG emission."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from octopus.normalization.types import MusicEvent
from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import LayoutEvent
from octopus.render.core.layout_widths import NOTE_WIDTH


def duration_fraction(event: MusicEvent) -> Fraction:
    """Return an event duration without converting through binary floats."""
    if event.kind == MusicTokenKind.EXTENSION:
        return Fraction(1, 1)
    if event.kind == MusicTokenKind.HIDDEN_REST:
        return Fraction(1, 2**event.duration_slashes)
    duration = event.duration
    if duration is None:
        return Fraction(0, 1)
    return Fraction(duration.numerator, duration.denominator)



def source_onsets(items: Sequence[LayoutEvent]) -> list[tuple[Fraction, LayoutEvent]]:
    onset = Fraction()
    result: list[tuple[Fraction, LayoutEvent]] = []
    for item in items:
        result.append((onset, item))
        onset += duration_fraction(item.event)
    return result



def project_source_onset(
    onset: Fraction,
    kind: MusicTokenKind,
    timeline: Sequence[tuple[Fraction, LayoutEvent]],
) -> tuple[float, LayoutEvent, bool]:
    """Use an exact host column or interpolate within its written duration."""
    exact = [item for time, item in timeline if time == onset]
    if exact:
        matching = [item for item in exact if (item.event.kind == MusicTokenKind.BARLINE)
                    == (kind == MusicTokenKind.BARLINE)]
        target = (matching or exact)[0]
        # A written upper separator may precede a host note without a lower
        # separator. Keep that separator clear of the note's erasing box;
        # its existence does not manufacture a barline in the main stream.
        x = target.x
        if kind == MusicTokenKind.BARLINE and not matching and onset > 0:
            previous = next(
                (item for time, item in reversed(timeline)
                 if time < onset and item.event.kind != MusicTokenKind.BARLINE),
                None,
            )
            x = (previous.x + target.x) / 2 if previous is not None else target.x - NOTE_WIDTH / 2
        return x, target, True
    previous_time, previous = max(
        ((time, item) for time, item in timeline if time < onset),
        key=lambda pair: pair[0],
        default=timeline[0],
    )
    following = next(((time, item) for time, item in timeline if time > onset), None)
    if following is None:
        duration = duration_fraction(previous.event)
        step = NOTE_WIDTH / float(duration) if duration > 0 else NOTE_WIDTH
        return previous.x + float(onset - previous_time) * step, previous, False
    next_time, next_item = following
    fraction = float((onset - previous_time) / (next_time - previous_time))
    return previous.x + fraction * (next_item.x - previous.x), previous, False
