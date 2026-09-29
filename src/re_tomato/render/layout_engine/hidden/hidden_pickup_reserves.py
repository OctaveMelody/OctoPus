"""Reserve policies for lyric-owned hidden pickup and sentinel phrases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..dotted.dotted_policy_types import SourceIntervalRetention
from ..keys import resolve_source_event_key_indices, source_event_key
from ..profiles import LegacyIntrinsicProfile
from ..reserves.interval_reserves import (
    add_interval_reserve,
    allocate_interval_reserves_with_terminal_release,
    release_interval_reserve_excess,
)
from ..reserves.reserve_classifiers import (
    decorated_post_rest_prebar_release_indices,
    four_beat_leading_dotted_tie_reserve_index,
    four_beat_leading_tied_pickup_reserves,
)
from ..signatures import (
    construct_role_signature,
    measure_durations,
    terminal_signature,
)
from ..streams import first_meter
from .hidden_streams import event_duration_fraction


def leading_first_ending_hidden_sentinel_release(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
    *,
    time_sig: str,
) -> SourceIntervalRetention | None:
    """Release the sentinel reserve in a leading first-ending continuation."""

    if (
        first_meter(time_sig) != (2, 4)
        or len(row) < 3
        or len({item.event.span.start.line for item in row}) != 1
        or row[0].event.kind != MusicTokenKind.BARLINE
        or not any(
            ":bracket:" in role and role.endswith(":start")
            for role in row[0].event.construct_roles
        )
        or measure_durations(row) != (Fraction(),) + (Fraction(2),) * 12
        or row[-1].event.code != "|"
        or terminal_signature(row)
        != (
            (MusicTokenKind.NOTE, Fraction(1), 0, 0, 0, 0),
            (MusicTokenKind.NOTE, Fraction(3, 4), 1, 1, 0, 0),
            (MusicTokenKind.NOTE, Fraction(1, 4), 0, 2, 0, 0),
        )
    ):
        return None

    lyric_profiles = tuple(
        lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
        for item in row
    )
    if not any(text for texts in lyric_profiles for text in texts) or any(
        len(texts) > 1 for texts in lyric_profiles
    ):
        return None

    bracket_end_indices = tuple(
        index
        for index, item in enumerate(row[:-1])
        if any(
            ":bracket:" in role and role.endswith(":end")
            for role in item.event.construct_roles
        )
    )
    candidates = tuple(
        index
        for index, item in enumerate(row[1:-1], start=1)
        if (
            item.event.kind == MusicTokenKind.HIDDEN_REST
            and event_duration_fraction(item.event) == 0
            and any(
                ":bracket:" in role and role.endswith(":inside")
                for role in item.event.construct_roles
            )
            and "tie:end" in construct_role_signature(row[index - 1])
            and row[index + 1].event.kind == MusicTokenKind.NOTE
            and "zkh" in row[index + 1].event.decorations
        )
    )
    if (
        len(bracket_end_indices) != 1
        or len(candidates) != 1
        or candidates[0] >= bracket_end_indices[0]
        or sum(item.event.kind == MusicTokenKind.HIDDEN_REST for item in row) != 1
    ):
        return None
    return SourceIntervalRetention(source_event_key(row[candidates[0]]), 36.0, 27.0)


def leading_first_ending_hidden_sentinel_release_index(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
    *,
    time_sig: str,
) -> int | None:
    """Resolve the leading sentinel owner for projection float correction."""

    release = leading_first_ending_hidden_sentinel_release(
        row,
        lyric_text_by_event,
        time_sig=time_sig,
    )
    return (
        resolve_source_event_key_indices(row, (release.event_key,))[0]
        if release is not None
        else None
    )


def repeated_hidden_pickup_releases(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
    *,
    time_sig: str,
) -> tuple[SourceIntervalRetention, ...]:
    """Release duplicated note-owned reserves in two hidden pickup phrases."""

    if (
        first_meter(time_sig) != (2, 4)
        or not row
        or len({item.event.span.start.line for item in row}) != 1
        or row[-1].event.code != "|"
    ):
        return ()
    lyric_profiles = tuple(
        lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
        for item in row
    )
    if not any(text for texts in lyric_profiles for text in texts) or any(
        len(texts) > 1 for texts in lyric_profiles
    ):
        return ()
    candidates = tuple(
        index
        for index, item in enumerate(row[2:-1], start=2)
        if (
            item.event.kind == MusicTokenKind.NOTE
            and item.event.duration_slashes == 2
            and row[index - 1].event.kind == MusicTokenKind.REST
            and row[index - 1].event.duration_slashes == 2
            and row[index - 2].event.kind == MusicTokenKind.HIDDEN_REST
            and event_duration_fraction(row[index - 2].event) == 0
            and row[index + 1].event.kind == MusicTokenKind.BARLINE
        )
    )
    if len(candidates) != 2:
        return ()
    # Rest-led decorated notes already retain the plain 25.2 bar step in the
    # base width model; these retentions pin that value against drift.
    return tuple(
        SourceIntervalRetention(source_event_key(row[index]), 25.2, 25.2)
        for index in candidates
    )


def apply_hidden_pickup_reserves(
    row: list[LayoutEvent],
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
    *,
    time_sig: str,
    profile: LegacyIntrinsicProfile,
) -> LegacyIntrinsicProfile:
    """Apply all admitted hidden-pickup releases with width invariants."""

    releases = repeated_hidden_pickup_releases(
        row,
        lyric_text_by_event,
        time_sig=time_sig,
    )
    leading_release = leading_first_ending_hidden_sentinel_release(
        row,
        lyric_text_by_event,
        time_sig=time_sig,
    )
    if leading_release is not None:
        releases = (leading_release, *releases)
    for retention in releases:
        release_index = resolve_source_event_key_indices(row, (retention.event_key,))[0]
        actual_width = profile.interval_widths[release_index]
        if abs(actual_width - retention.expected_width) > GEOMETRY_EPSILON:
            raise ValueError(
                f"hidden pickup base width drift for {retention.event_key}: expected "
                f"{retention.expected_width}, actual {actual_width}"
            )
        release = release_interval_reserve_excess(
            profile.interval_widths,
            interval_index=release_index,
            retained_width=retention.retained_width,
        )
        profile = replace(profile, interval_widths=release.interval_widths)
    pickup_reserves = four_beat_leading_tied_pickup_reserves(row, time_sig=time_sig)
    if pickup_reserves:
        allocation = allocate_interval_reserves_with_terminal_release(
            profile.interval_widths,
            added_width_by_index=pickup_reserves,
            terminal_reserve=profile.terminal_width,
            terminal_release=sum(pickup_reserves.values()),
        )
        profile = replace(
            profile,
            interval_widths=allocation.interval_widths,
            terminal_width=allocation.terminal_reserve,
        )
    dotted_tie_index = four_beat_leading_dotted_tie_reserve_index(row, time_sig=time_sig)
    if dotted_tie_index is not None:
        dotted_tie_allocation = add_interval_reserve(
            profile.interval_widths,
            interval_index=dotted_tie_index,
            added_width=9.0,
        )
        profile = replace(profile, interval_widths=dotted_tie_allocation.interval_widths)
    return profile


def apply_decorated_prebar_reserves(
    row: list[LayoutEvent],
    *,
    time_sig: str,
    profile: LegacyIntrinsicProfile,
) -> LegacyIntrinsicProfile:
    """Retain ordinary bar width after a rest-led decorated note."""

    for release_index in decorated_post_rest_prebar_release_indices(row, time_sig=time_sig):
        current_width = profile.interval_widths[release_index]
        if abs(current_width - 25.2) <= GEOMETRY_EPSILON:
            continue
        if abs(current_width - 27.0) > GEOMETRY_EPSILON:
            raise ValueError(
                f"decorated pre-bar base width drift at interval {release_index}: "
                f"expected 27.0 or an existing 25.2 retention, actual {current_width}"
            )
        release = release_interval_reserve_excess(
            profile.interval_widths,
            interval_index=release_index,
            retained_width=25.2,
        )
        profile = replace(profile, interval_widths=release.interval_widths)
    return profile


__all__ = [
    "apply_decorated_prebar_reserves",
    "apply_hidden_pickup_reserves",
    "leading_first_ending_hidden_sentinel_release",
    "leading_first_ending_hidden_sentinel_release_index",
    "repeated_hidden_pickup_releases",
]
