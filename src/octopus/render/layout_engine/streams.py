"""Meter and measure helpers used by hidden-stream normalization."""

from __future__ import annotations

from fractions import Fraction

from octopus.normalization.types import MusicEvent

from ...parser.ast import MusicTokenKind


def duration_bucket(onset: Fraction, beat_unit: Fraction) -> int:
    """Map an exact onset to its containing stream beat."""

    if beat_unit <= 0:
        return onset.numerator // onset.denominator
    bucket = onset / beat_unit
    return bucket.numerator // bucket.denominator


def first_meter(time_sig: str) -> tuple[int, int] | None:
    """Parse the first ``numerator/denominator`` meter token."""

    try:
        meter = time_sig.split(maxsplit=1)[0]
        numerator_text, denominator_text = meter.split("/", maxsplit=1)
        numerator = int(numerator_text)
        denominator = int(denominator_text)
    except (IndexError, ValueError):
        return None
    return numerator, denominator


def meter_beat_duration(time_sig: str) -> Fraction:
    """Return the beat duration in quarter-note units for a time signature.

    Compound eighth-note meters (6/8, 9/8, ...) use a dotted-quarter beat;
    every other meter uses a quarter-note beat.
    """

    meter = first_meter(time_sig)
    if meter is None:
        return Fraction(1, 1)
    numerator, denominator = meter
    if denominator == 8 and numerator % 3 == 0 and numerator > 3:
        return Fraction(3, 2)
    return Fraction(1, 1)


def dsb_stream_beat_unit(time_sig: str) -> Fraction:
    """Return the beat unit used to align hidden DSB streams."""

    return meter_beat_duration(time_sig)


def uses_compound_meter(time_sig: str) -> bool:
    """Return whether a time signature uses a compound eighth-note meter."""

    meter = first_meter(time_sig)
    if meter is None:
        return False
    numerator, denominator = meter
    return denominator == 8 and numerator > 3 and numerator % 3 == 0


def split_events_into_measures(events: list[MusicEvent]) -> list[list[MusicEvent]]:
    """Split source events at barlines while retaining each barline."""

    measures: list[list[MusicEvent]] = []
    current: list[MusicEvent] = []
    for event in events:
        current.append(event)
        if event.kind == MusicTokenKind.BARLINE:
            measures.append(current)
            current = []
    if current:
        measures.append(current)
    return measures


__all__ = [
    "dsb_stream_beat_unit",
    "duration_bucket",
    "first_meter",
    "split_events_into_measures",
    "uses_compound_meter",
]
