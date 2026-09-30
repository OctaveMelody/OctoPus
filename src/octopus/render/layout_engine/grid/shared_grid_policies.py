"""Pure shared-row grid admission policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from octopus.parser.ast import MusicTokenKind
from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout_engine.hidden.hidden_streams import event_duration_fraction
from octopus.render.layout_engine.rows.row_signatures import (
    shared_measure_durations_match,
    shared_row_rhythm_signature,
)
from octopus.render.layout_engine.visibility import is_synthetic_hidden_rest_placeholder

from .beat_grid import TIMED_KINDS, four_voice_majority_beat_shape
from .grid_policies import split_measures


def uses_primary_modified_ending_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    return (
        len(rows) == 2
        and list(visible_lyric_profile_indices) == [0, 1]
        and shared_measure_durations_match(rows)
        and rows[0][-2].event.kind == MusicTokenKind.EXTENSION
        and rows[1][-2].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and any(":modifier:" in role for role in rows[1][-2].event.construct_roles)
    )


def uses_four_beat_refinement_grid(rows: Sequence[Sequence[LayoutEvent]]) -> bool:
    measures_by_row = [split_measures(row) for row in rows]
    for target_measures in measures_by_row:
        for current_measures in measures_by_row:
            for target, current in zip(target_measures, current_measures, strict=False):
                target_events = [
                    item for item in target if item.event.kind != MusicTokenKind.BARLINE
                ]
                current_events = [
                    item for item in current if item.event.kind != MusicTokenKind.BARLINE
                ]
                if (
                    len(target_events) == 6
                    and len(current_events) == 4
                    and all(event_duration_fraction(item.event) == 1 for item in current_events)
                    and sum(
                        (event_duration_fraction(item.event) for item in target_events),
                        start=0,
                    )
                    == 4
                    and all(
                        item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.EXTENSION}
                        for item in target_events
                    )
                ):
                    return True
    return False


def uses_dominant_primary_lyric_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
    lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], Sequence[str]]],
) -> bool:
    if len(rows) != 2 or not shared_measure_durations_match(rows):
        return False
    lyric_counts = [
        sum(
            bool(text)
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
        )
        for row in rows
    ]
    measure_counts = [
        [
            sum(item.event.kind != MusicTokenKind.BARLINE for item in measure)
            for measure in split_measures(row)
        ]
        for row in rows
    ]
    uses_dominant_lyrics = (
        list(visible_lyric_profile_indices) == [0, 1]
        and lyric_counts[1] > 0
        and lyric_counts[0] >= lyric_counts[1] * 2
    )
    uses_lyricless_coarse_secondary = (
        not visible_lyric_profile_indices and len(rows[0]) >= len(rows[1]) + 3
    )
    return (
        (uses_dominant_lyrics or uses_lyricless_coarse_secondary)
        and len(measure_counts[0]) == len(measure_counts[1])
        and all(
            primary >= secondary
            for primary, secondary in zip(measure_counts[0], measure_counts[1], strict=True)
        )
    )


def uses_primary_parallel_voice_denominator_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    return (
        len(rows) == 4
        and list(visible_lyric_profile_indices) == [0, 1]
        and len({len(row) for row in rows}) > 1
        and shared_measure_durations_match(rows)
        and shared_row_rhythm_signature(rows[0]) == shared_row_rhythm_signature(rows[2])
    )


def uses_primary_spanning_hook_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_profile_indices: Sequence[int],
) -> bool:
    if (
        len(rows) != 2
        or list(visible_lyric_profile_indices) != [0, 1]
        or not shared_measure_durations_match(rows)
    ):
        return False
    final_measure_starts = [
        max(
            (
                index
                for index, item in enumerate(row[:-1])
                if item.event.kind == MusicTokenKind.BARLINE
            ),
            default=-1,
        )
        for row in rows
    ]
    primary = rows[0][final_measure_starts[0] + 1 : -1]
    secondary = rows[1][final_measure_starts[1] + 1 : -1]
    return (
        bool(primary)
        and "ykh" in primary[-1].event.decorations
        and any("zkh" in item.event.decorations for item in primary)
        and bool(secondary)
        and all(
            item.event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            for item in secondary
        )
    )


def uses_widest_compound_lyric_denominator(
    rows: Sequence[Sequence[LayoutEvent]],
    profile_denominators: Sequence[float],
    *,
    uses_primary_lyric_parallel_grid: bool,
    uses_compound_aligned_two_voice_lyric_grid: bool,
) -> bool:
    """Return whether an aligned compound lyric pair owns the widest profile.

    A primary-only lyric authority can share event columns with a rhythm-aligned
    secondary row while the secondary row contributes a larger terminal reserve.
    In that shape the shared scale must be based on the widest terminal-inclusive
    profile; equal profiles remain a no-op and the primary authority remains the
    owner for all other shared-grid families.
    """
    return (
        uses_primary_lyric_parallel_grid
        and uses_compound_aligned_two_voice_lyric_grid
        and len(rows) == 2
        and len(profile_denominators) == 2
        and profile_denominators[1] > profile_denominators[0]
    )


def uses_compound_tied_grace_beat_expiry(
    rows: Sequence[Sequence[LayoutEvent]],
    *,
    uses_primary_lyric_parallel_grid: bool,
    uses_compound_aligned_two_voice_lyric_grid: bool,
) -> bool:
    """Return whether tied grace reserves expire at the next compound beat.

    The primary-only lyric authority owns the shared columns for this aligned
    two-row compound family.  Its tied grace reserve follows the compound beat
    boundary rather than the enclosing barline; other shared owners retain the
    ordinary barline expiry.
    """
    return (
        uses_primary_lyric_parallel_grid
        and uses_compound_aligned_two_voice_lyric_grid
        and len(rows) == 2
        and shared_measure_durations_match(rows)
        and len({shared_row_rhythm_signature(row) for row in rows}) == 1
    )


def uses_compound_dual_verse_lyric_profile_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    visible_lyric_rows: Sequence[bool],
    *,
    uses_primary_dual_verse_compound_grid: bool,
    grid_lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], Sequence[str]]],
) -> bool:
    """Return whether the complete system lyric map owns intrinsic widths.

    A primary-only compound pair can have additional verse lines attached to
    the same music row.  The ordinary authority map intentionally keeps the
    first verse for legacy ownership decisions, while the shared-grid map
    records every rendered verse.  Only this admitted, rhythm-aligned source
    shape lets the complete map contribute lyric clearance to the profile.
    """
    if (
        not uses_primary_dual_verse_compound_grid
        or len(rows) != 2
        or list(visible_lyric_rows) != [True, False]
        or not shared_measure_durations_match(rows)
        or len({shared_row_rhythm_signature(row) for row in rows}) != 1
    ):
        return False
    primary_voice = rows[0][0].voice
    return any(
        len(texts) >= 2 and any(texts[1:])
        for texts in grid_lyric_text_by_voice.get(primary_voice, {}).values()
    )


def uses_compound_dual_verse_terminal_reserve_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    *,
    uses_compound_dual_verse_lyric_profile_grid: bool,
) -> bool:
    """Return whether a dual-verse owner keeps its continuation terminal reserve."""
    return (
        uses_compound_dual_verse_lyric_profile_grid
        and len(rows) == 2
        and all(row[-1].event.code == "|y" for row in rows)
        and all(
            row[-2].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and ")" in row[-2].event.code
            and "ykh" not in row[-2].event.decorations
            for row in rows
        )
        and len({row[-2].event.code for row in rows}) == 1
    )


def uses_three_voice_interleaved_lyric_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], Sequence[str]]],
) -> bool:
    """Return whether a three-row group has the measured interleaved lyric shape.

    The event-keyed union grid is authoritative for the three-row shape with
    lyric owners on the outside rows and a lyricless middle row. Equal
    measure durations are part of the source topology; other three-row lyric
    arrangements remain on the legacy projection until separately evidenced.
    """
    if len(rows) != 3 or any(not row for row in rows):
        return False
    if not shared_measure_durations_match(rows):
        return False
    visible_lyric_rows = tuple(
        any(
            bool(text)
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
        )
        for row in rows
    )
    return visible_lyric_rows == (True, False, True)


def uses_three_voice_dotted_primary_lyric_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], Sequence[str]]],
) -> bool:
    """Return whether a dotted primary row owns the measured three-row grid."""
    if len(rows) != 3 or any(not row for row in rows):
        return False
    if not shared_measure_durations_match(rows):
        return False
    visible_lyric_rows = tuple(
        any(
            bool(text)
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
        )
        for row in rows
    )
    return (
        visible_lyric_rows == (True, True, False)
        and "." in rows[0][0].event.code
    )


def uses_four_voice_majority_beat_grid(
    rows: Sequence[Sequence[LayoutEvent]],
    lyric_text_by_voice: Mapping[int, Mapping[tuple[int, int], Sequence[str]]],
) -> bool:
    """Return whether one overfull row inherits the three-row beat majority.

    This is a direct-grid policy for a lossless source shape: exactly one row
    owns visible lyrics, the four rows have one common event count per measure,
    and the exact beat analysis has three identical shapes plus one shape with
    one extra beat in one measure.  The projection keeps the outlier's source
    event order but uses the majority partition.
    """
    if len(rows) != 4 or any(not row for row in rows):
        return False
    visible_lyric_rows = tuple(
        any(
            bool(text)
            for texts in lyric_text_by_voice.get(row[0].voice, {}).values()
            for text in texts
        )
        for row in rows
    )
    return sum(visible_lyric_rows) == 1 and four_voice_majority_beat_shape(
        tuple(tuple(item.event for item in row) for row in rows)
    ) is not None


def _timed_measure_signature(
    row: Sequence[LayoutEvent],
) -> tuple[tuple[Fraction, ...], tuple[int, ...]]:
    durations: list[Fraction] = []
    counts: list[int] = []
    for measure in split_measures(row):
        durations.append(
            sum(
                (event_duration_fraction(item.event) for item in measure),
                start=Fraction(),
            )
        )
        counts.append(sum(item.event.kind in TIMED_KINDS for item in measure))
    return tuple(durations), tuple(counts)


def uses_two_voice_terminal_duration_swap_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    """Return whether a lyric pair swaps one terminal beat-grid event.

    The reference uses one direct grid for a two-row lyric pair whose first
    three measures have the same duration, while the final measure is a
    half-beat longer in one row.  The rows keep the same total event count by
    exchanging one timed event between the final two measures.  This is a
    source-topology rule; shared-system admission still owns origin, voice,
    barline, and block safety checks.
    """
    if (
        len(rows) != 2
        or list(visible_lyric_rows) != [True, True]
        or len({row[0].voice for row in rows}) != 2
        or any(item.block is not None for row in rows for item in row)
        or any(not row or row[-1].event.kind != MusicTokenKind.BARLINE for row in rows)
    ):
        return False
    signatures = [_timed_measure_signature(row) for row in rows]
    if len(signatures[0][0]) != 4 or len(signatures[1][0]) != 4:
        return False
    if len(rows[0]) != len(rows[1]):
        return False
    durations = [signature[0] for signature in signatures]
    counts = [signature[1] for signature in signatures]
    count_deltas = tuple(left - right for left, right in zip(counts[0], counts[1], strict=True))
    return (
        durations[0][:-1] == durations[1][:-1]
        and abs(durations[0][-1] - durations[1][-1]) == Fraction(1, 2)
        and count_deltas[:2] == (0, 0)
        and sorted(count_deltas[2:]) == [-1, 1]
    )


def uses_two_voice_single_lyric_event_swap_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    """Return whether one lyric owner has one timed-event partition swap.

    This narrow six-measure family keeps the source duration of every measure
    equal while one row carries exactly one additional timed event in one
    measure.  The direct union grid reconciles that source partition without
    treating a same-voice sequence as a shared system.
    """
    if (
        len(rows) != 2
        or list(visible_lyric_rows) != [True, False]
        or len({row[0].voice for row in rows}) != 2
        or any(item.block is not None for row in rows for item in row)
        or any(not row or row[-1].event.kind != MusicTokenKind.BARLINE for row in rows)
        or abs(len(rows[0]) - len(rows[1])) != 1
    ):
        return False
    signatures = [_timed_measure_signature(row) for row in rows]
    if any(len(signature[0]) != 6 for signature in signatures):
        return False
    durations = [signature[0] for signature in signatures]
    counts = [signature[1] for signature in signatures]
    count_deltas = tuple(left - right for left, right in zip(counts[0], counts[1], strict=True))
    return (
        durations[0] == durations[1]
        and abs(sum(count_deltas)) == 1
        and sum(delta != 0 for delta in count_deltas) == 1
    )


def uses_two_voice_four_measure_compound_event_swap_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    """Return whether a four-measure compound pair needs primary reserves.

    This source shape keeps the legacy shared projection, but the primary row's
    compound-beat boundary reserves are part of the shared denominator.  One
    sparse measure exchanges two timed events with its sibling while preserving
    the four-measure duration signature.  It is intentionally separate from
    the direct union event-swap rule above: the sparse row's barline onset is
    authoritative for this family.
    """
    if (
        len(rows) != 2
        or list(visible_lyric_rows) != [True, False]
        or any(not row for row in rows)
        or len({row[0].voice for row in rows}) != 2
        or any(item.block is not None for row in rows for item in row)
        or any(
            item.event.kind == MusicTokenKind.HIDDEN_REST
            for row in rows
            for item in row
        )
        or any(row[-1].event.kind != MusicTokenKind.BARLINE for row in rows)
        or abs(len(rows[0]) - len(rows[1])) != 2
    ):
        return False
    signatures = [_timed_measure_signature(row) for row in rows]
    durations = [signature[0] for signature in signatures]
    counts = [signature[1] for signature in signatures]
    count_deltas = tuple(
        left - right for left, right in zip(counts[0], counts[1], strict=True)
    )
    return (
        all(len(duration) == 4 for duration in durations)
        and durations[0]
        == durations[1]
        == (Fraction(3), Fraction(9, 2), Fraction(3), Fraction(9, 2))
        and sum(abs(delta) for delta in count_deltas) == 2
        and sum(delta != 0 for delta in count_deltas) == 1
    )


def synthetic_hidden_rest_pre_barline_release_index(
    row: Sequence[LayoutEvent],
) -> int | None:
    """Return the index of a released alignment placeholder, if present."""
    return next(
        (
            index
            for index, item in enumerate(row)
            if is_synthetic_hidden_rest_placeholder(item.event)
            and index > 0
            and index + 1 < len(row)
            and row[index - 1].event.kind
            in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and row[index - 1].event.duration_slashes == 1
            and row[index + 1].event.kind == MusicTokenKind.BARLINE
            and item.block is None
        ),
        None,
    )


def uses_synthetic_hidden_rest_pre_barline_release(row: Sequence[LayoutEvent]) -> bool:
    """Return whether a grid row has a released alignment placeholder.

    A synthetic hidden-rest slot immediately after a slashed note and before
    a barline is a row-topology alignment placeholder, not a second timed
    beat.  In the direct event-keyed grid, the reference keeps its visual
    column seven rendered units left of the shared next-beat column and
    carries that release through the row's remaining non-final events.  The
    caller applies this only after shared-grid projection, so the common
    denominator and all sibling rows remain unchanged.
    """
    return synthetic_hidden_rest_pre_barline_release_index(row) is not None


def uses_lyric_unequal_slot_duration_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    if len(rows) != 2 or list(visible_lyric_rows) != [True, True]:
        return False
    uses_leading_rest = (
        rows[0][0].event.kind in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
        and rows[1][0].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
    )
    uses_dual_parenthesized_openers = all(
        row[0].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and "(" in row[0].event.code
        for row in rows
    )
    uses_two_slash_terminal_closer = (
        rows[1][-2].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and ")" in rows[1][-2].event.code
        and rows[1][-2].event.duration_slashes == 2
    )
    uses_matching_opener_terminal = (
        rows[0][0].event.code == rows[1][0].event.code
        and uses_two_slash_terminal_closer
    )
    uses_rest_owned_terminal = (
        all(row[0].event.kind == MusicTokenKind.REST and row[0].event.code == "0" for row in rows)
        and sum(row[-2].event.kind == MusicTokenKind.REST for row in rows) == 1
    )
    uses_parenthesized_opener_rest_tail = (
        rows[0][0].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and "(" in rows[0][0].event.code
        and rows[1][0].event.kind == MusicTokenKind.REST
        and rows[1][-2].event.kind == MusicTokenKind.REST
    )
    return (
        ((uses_leading_rest or uses_dual_parenthesized_openers) and uses_two_slash_terminal_closer)
        or uses_matching_opener_terminal
        or uses_rest_owned_terminal
        or (
            uses_parenthesized_opener_rest_tail
            and rows[0][-2].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        )
    )


def uses_single_lyric_unequal_slot_duration_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    if len(rows) != 2 or list(visible_lyric_rows) != [True, False]:
        return False
    if len({len(row) for row in rows}) == 1 or not shared_measure_durations_match(rows):
        return False
    if any(row[-1].event.kind != MusicTokenKind.BARLINE for row in rows):
        return False
    uses_slash_started_rest_tail = (
        all(
            row[0].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and row[0].event.duration_slashes == 1
            for row in rows
        )
        and all(
            row[-2].event.kind in {MusicTokenKind.REST, MusicTokenKind.EXTENSION}
            and row[-2].event.code == "-"
            for row in rows
        )
    )
    uses_matching_dotted_closers = (
        rows[0][0].event.code == rows[1][0].event.code
        and all(
            row[-2].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            and "." in row[-2].event.code
            and ")" in row[-2].event.code
            for row in rows
        )
    )
    return uses_slash_started_rest_tail or uses_matching_dotted_closers


def uses_single_lyric_compound_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    if len(rows) != 2 or list(visible_lyric_rows) != [True, False]:
        return False
    bar_slots = {
        tuple(index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE)
        for row in rows
    }
    return (
        len({len(row) for row in rows}) == 1
        and len(bar_slots) == 1
        and min((len(slots) for slots in bar_slots), default=0) >= 2
    )


def uses_alternating_four_voice_lyric_grid(
    rows: Sequence[Sequence[LayoutEvent]], visible_lyric_rows: Sequence[bool]
) -> bool:
    return (
        len(rows) == 4
        and list(visible_lyric_rows) == [True, False, True, False]
        and len({len(row) for row in rows}) == 1
        and len(
            {
                tuple(
                    index
                    for index, item in enumerate(row)
                    if item.event.kind == MusicTokenKind.BARLINE
                )
                for row in rows
            }
        )
        == 1
        and min(sum(item.event.kind == MusicTokenKind.BARLINE for item in row) for row in rows) >= 8
        and all(row[0].event.kind != MusicTokenKind.BARLINE for row in rows)
        and shared_measure_durations_match(rows)
    )


__all__ = [
    *[name for name in globals() if name.startswith("uses_")],
    "synthetic_hidden_rest_pre_barline_release_index",
]
