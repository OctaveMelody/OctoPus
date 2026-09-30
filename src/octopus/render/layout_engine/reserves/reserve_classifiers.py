"""Source-shape classifiers for interval reserve ownership."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..streams import first_meter


def subdivided_tie_followup_release_index(
    row: Sequence[LayoutEvent],
) -> int | None:
    """Return the style interval released after a subdivided tie/rest cadence.

    The admitted single-voice form closes a tie on a half-beat note, completes
    the measure with half-/full-beat rests, then places a decorated undivided
    note after a rest.  That decoration does not widen its pre-bar interval.
    """

    if (
        not row
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
    ):
        return None

    bar_indices = tuple(
        index
        for index, item in enumerate(row)
        if item.event.kind == MusicTokenKind.BARLINE
    )
    if len(bar_indices) != 12:
        return None

    candidates: list[int] = []
    for bar_ordinal in range(1, len(bar_indices)):
        previous_start = bar_indices[bar_ordinal - 2] + 1 if bar_ordinal >= 2 else 0
        previous = row[previous_start : bar_indices[bar_ordinal - 1]]
        current_start = bar_indices[bar_ordinal - 1] + 1
        current = row[current_start : bar_indices[bar_ordinal]]
        if (
            len(previous) == 3
            and len(current) == 2
            and previous[0].event.kind
            in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and previous[0].event.duration_slashes == 1
            and ")" in previous[0].event.code
            and previous[1].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            and previous[1].event.duration_slashes == 1
            and previous[2].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            and previous[2].event.duration_slashes == 0
            and current[0].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            and current[0].event.duration_slashes == 0
            and current[1].event.kind
            in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and current[1].event.duration_slashes == 0
            and bool(current[1].event.decorations)
        ):
            candidates.append(current_start + 1)
    return candidates[0] if len(candidates) == 1 else None


def decorated_post_rest_prebar_release_indices(
    row: Sequence[LayoutEvent],
    *,
    time_sig: str,
) -> tuple[int, ...]:
    """Return dynamic-note intervals that retain only the ordinary bar reserve."""

    if (
        first_meter(time_sig) != (2, 4)
        or not row
        or row[-1].event.code not in {"|", "|]", "|]/"}
        or len({item.event.span.start.line for item in row}) != 1
    ):
        return ()
    sounded = {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
    rests = {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
    return tuple(
        index
        for index, item in enumerate(row[2:-2], start=2)
        if item.event.kind in sounded
        and bool(item.event.decorations)
        and "zkh" not in item.event.decorations
        and row[index - 1].event.kind in rests
        and (
            row[index - 2].event.kind in sounded
            or row[index - 2].event.kind == row[index - 1].event.kind
            == MusicTokenKind.HIDDEN_REST
        )
        and row[index + 1].event.kind == MusicTokenKind.BARLINE
    )




def four_beat_leading_tied_pickup_reserves(
    row: Sequence[LayoutEvent],
    *,
    time_sig: str,
) -> dict[int, float]:
    """Return prefix reserves transferred from a sparse row's terminal owner."""

    if (
        first_meter(time_sig) != (4, 4)
        or len(row) != 25
        or tuple(
            index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
        )
        != (7, 18, 24)
        or tuple(event_duration_fraction(item.event) for item in row[:7])
        != (
            Fraction(1, 2),
            Fraction(1, 4),
            Fraction(1, 4),
            Fraction(1, 4),
            Fraction(3, 4),
            Fraction(3, 2),
            Fraction(1, 2),
        )
        or not any(
            ":tie:" in role and role.endswith(":start")
            for role in row[2].event.construct_roles
        )
        or not any(
            ":tie:" in role and role.endswith(":end")
            for role in row[3].event.construct_roles
        )
    ):
        return {}
    return {2: 3.6, 4: 9.0}


def four_beat_leading_dotted_tie_reserve_index(
    row: Sequence[LayoutEvent],
    *,
    time_sig: str,
) -> int | None:
    """Return the reserve owner for a leading dotted tied pickup."""

    if (
        first_meter(time_sig) != (4, 4)
        or len(row) < 36
        or sum(item.event.kind == MusicTokenKind.BARLINE for item in row) < 4
        or event_duration_fraction(row[0].event) != Fraction(1, 4)
        or event_duration_fraction(row[1].event) != Fraction(3, 4)
        or event_duration_fraction(row[2].event) != Fraction(1, 2)
        or not any(
            ":tie:" in role and role.endswith(":start")
            for role in row[1].event.construct_roles
        )
        or not any(
            ":tie:" in role and role.endswith(":end")
            for role in row[2].event.construct_roles
        )
    ):
        return None
    return 1


__all__ = [
    "decorated_post_rest_prebar_release_indices",
    "four_beat_leading_tied_pickup_reserves",
    "four_beat_leading_dotted_tie_reserve_index",
    "subdivided_tie_followup_release_index",
]
