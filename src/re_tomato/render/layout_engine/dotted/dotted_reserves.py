"""Typed dotted-row reserve classifier policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..keys import source_event_key
from ..signatures import (
    construct_role_signature,
    event_signature,
    measure_durations,
    terminal_signature,
)
from ..streams import first_meter
from .dotted_policy_types import (
    DottedSecondEndingRelease,
    SourceIntervalRetention,
)


def dotted_second_ending_release(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
    *,
    time_sig: str,
) -> DottedSecondEndingRelease | None:
    """Admit the simple-meter dotted second-ending interval release family."""

    if (
        first_meter(time_sig) != (2, 4)
        or len(row) != 47
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
        )
        != (3, 7, 10, 14, 18, 21, 24, 28, 32, 35, 38, 42, 46)
        or measure_durations(row) != (Fraction(2),) * 13
        or row[-1].event.code != "|]/"
        or terminal_signature(row)
        != (
            (MusicTokenKind.NOTE, Fraction(1), 0, 0, 0, 0),
            (MusicTokenKind.NOTE, Fraction(3, 4), 1, 1, 0, 0),
            (MusicTokenKind.NOTE, Fraction(1, 4), 0, 2, 0, 0),
        )
    ):
        return None

    row_keys = {
        (item.event.span.start.line, item.event.index)
        for item in row
    }
    row_lyric_text_by_event = {
        key: texts for key, texts in lyric_text_by_event.items() if key in row_keys
    }
    lyric_profiles = tuple(
        row_lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
        for item in row
    )
    if not any(text for texts in lyric_profiles for text in texts) or any(
        len(texts) > 1 for texts in lyric_profiles
    ):
        return None
    if any(
        any(lyric_profiles[index])
        and item.event.kind not in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        for index, item in enumerate(row)
    ):
        return None

    bracket_roles = tuple(item.event.construct_roles for item in row[32:])
    if (
        not any(":bracket:" in role and role.endswith(":start") for role in bracket_roles[0])
        or any(
            not any(":bracket:" in role and role.endswith(":inside") for role in roles)
            for roles in bracket_roles[1:-1]
        )
        or not any(":bracket:" in role and role.endswith(":end") for role in bracket_roles[-1])
    ):
        return None

    first_candidates = tuple(
        index
        for index, item in enumerate(row[:-2])
        if (
            item.event.kind == MusicTokenKind.HIDDEN_REST
            and event_duration_fraction(item.event) == 0
            and row[index + 1].event.kind == MusicTokenKind.NOTE
            and event_duration_fraction(row[index + 1].event) == 1
            and row[index + 1].event.duration_dots == 0
            and row[index + 1].event.duration_slashes == 0
            and row[index + 1].event.decorations
            and "zkh" not in row[index + 1].event.decorations
            and row[index + 2].event.kind == MusicTokenKind.BARLINE
        )
    )
    second_candidates = tuple(
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
    if len(first_candidates) != 1 or len(second_candidates) != 1:
        return None

    first_owner = row[first_candidates[0] + 1]
    second_owner = row[second_candidates[0]]
    terminal_start = max(
        index
        for index, item in enumerate(row[:-1])
        if item.event.kind == MusicTokenKind.BARLINE
    ) + 1
    terminal_hosts = row[terminal_start:-1]
    if any(
        (item.event.span.start.line, item.event.index) not in row_lyric_text_by_event
        or any(
            row_lyric_text_by_event[(item.event.span.start.line, item.event.index)]
        )
        for item in terminal_hosts
    ):
        return None
    # The first owner is a rest-led decorated note: the base width model
    # already retains the plain 25.2 bar step there, so this retention is a
    # no-op pin guarding against drift back to the 27.0 reserve.
    return DottedSecondEndingRelease(
        retentions=(
            SourceIntervalRetention(source_event_key(first_owner), 25.2, 25.2),
            SourceIntervalRetention(source_event_key(second_owner), 36.0, 27.0),
        ),
        source_domain_change=-7.2,
    )


def lyric_owned_hidden_sentinel_reserve_index(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> int | None:
    if (
        len(row) != 44
        or row[-1].event.code != "|]/"
        or len({item.event.span.start.line for item in row}) != 1
        or measure_durations(row) != (Fraction(2),) * 14
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
    note = MusicTokenKind.NOTE
    if terminal_signature(row) != (
        (note, Fraction(3, 2), 1, 0, 0, 1),
        (note, Fraction(1, 2), 0, 1, 0, 0),
    ):
        return None
    sentinel_indices = tuple(
        index
        for index, item in enumerate(row[1:-1], start=1)
        if item.event.kind == MusicTokenKind.HIDDEN_REST
        and event_duration_fraction(item.event) == 0
    )
    if len(sentinel_indices) != 1:
        return None
    sentinel_index = sentinel_indices[0]
    preceding_bar_count = sum(
        item.event.kind == MusicTokenKind.BARLINE for item in row[:sentinel_index]
    )
    return sentinel_index - 1 if preceding_bar_count == 2 else None


def second_ending_dotted_lyric_reserve_indices(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> tuple[int, ...]:
    if (
        len(row) != 38
        or row[0].event.code != "|n['2'"
        or row[-1].event.code != "|]/"
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
        )
        != (0, 10, 16, 26, 37)
        or measure_durations(row)
        != (Fraction(), Fraction(4), Fraction(4), Fraction(4), Fraction(4))
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
    note = MusicTokenKind.NOTE
    terminal_profile = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (note, Fraction(3, 4), 1, 1, 0, 1),
        (note, Fraction(1, 4), 0, 2, 0, 0),
    )
    if terminal_signature(row) != terminal_profile:
        return ()
    reserve_indices = tuple(
        index
        for index, item in enumerate(row[:-1])
        if item.event.kind == note
        and event_duration_fraction(item.event) == Fraction(3, 4)
        and item.event.duration_dots == 1
        and item.event.duration_slashes == 1
        and any(lyric_profiles[index])
    )
    terminal_dotted_index = len(row) - 3
    if reserve_indices != (18, 28) or any(lyric_profiles[terminal_dotted_index]):
        return ()
    return reserve_indices


def lyric_deferred_hook_terminal_transfer_index(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> int | None:
    if (
        len(row) != 33
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
        )
        != (12, 22, 32)
        or measure_durations(row) != (Fraction(4),) * 3
        or "zkh" not in row[0].event.code
    ):
        return None
    lyric_profiles = tuple(
        lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
        for item in row
    )
    if (
        any(len(texts) > 1 for texts in lyric_profiles)
        or any(text for texts in lyric_profiles[:10] for text in texts)
        or not any(lyric_profiles[10])
    ):
        return None
    closer_index = 8
    opener = row[closer_index - 1].event
    closer = row[closer_index].event
    following = row[closer_index + 1].event
    lyric_onset = row[closer_index + 2].event
    if not (
        opener.kind == MusicTokenKind.NOTE
        and event_duration_fraction(opener) == Fraction(1, 4)
        and "(" in opener.code
        and closer.kind == MusicTokenKind.NOTE
        and event_duration_fraction(closer) == Fraction(1)
        and ")" in closer.code
        and "ykh" in closer.code
        and opener.pitch == closer.pitch
        and opener.octave == closer.octave
        and following.kind == MusicTokenKind.REST
        and event_duration_fraction(following) == Fraction(1, 2)
        and lyric_onset.kind == MusicTokenKind.NOTE
        and event_duration_fraction(lyric_onset) == Fraction(1, 4)
    ):
        return None
    note = MusicTokenKind.NOTE
    if terminal_signature(row) != (
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
    ):
        return None
    return closer_index


def dual_verse_middle_bar_reserve_index(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> int | None:
    bar_indices = tuple(
        index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
    )
    if (
        len(row) != 31
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
        or bar_indices != (10, 20, 30)
        or measure_durations(row) != (Fraction(4),) * 3
    ):
        return None
    lyric_profiles = tuple(
        lyric_text_by_event.get((item.event.span.start.line, item.event.index), ())
        for item in row
    )
    if (
        max((len(texts) for texts in lyric_profiles), default=0) != 2
        or any(len(texts) > 2 for texts in lyric_profiles)
        or not any(text for texts in lyric_profiles for text in texts)
    ):
        return None
    note = MusicTokenKind.NOTE
    if terminal_signature(row) != (
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
    ):
        return None
    return bar_indices[1] - 1


def single_verse_cross_bar_dotted_reserve_indices(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> tuple[int, ...]:
    """Return the two dotted intervals owned by a cross-bar single-verse row."""

    if (
        len(row) != 31
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        != (10, 22, 30)
        or measure_durations(row) != (Fraction(4),) * 3
    ):
        return ()

    lyric_profiles = tuple(
        lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
        for item in row
    )
    if (
        max((len(texts) for texts in lyric_profiles), default=0) != 1
        or any(len(texts) > 1 for texts in lyric_profiles)
        or not any(text for texts in lyric_profiles for text in texts)
    ):
        return ()

    note = MusicTokenKind.NOTE
    rest = MusicTokenKind.REST
    barline = MusicTokenKind.BARLINE
    expected_signature = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 2), 0, 1, 0, 1),
        (note, Fraction(1), 0, 0, 0, 0),
        (rest, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (barline, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (barline, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 2), 0, 1, 1, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(3, 4), 1, 1, 1, 0),
        (note, Fraction(3, 2), 1, 0, 0, 1),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (barline, Fraction(), 0, 0, 0, 0),
    )
    if tuple(event_signature(item) for item in row) != expected_signature:
        return ()

    reserve_indices = tuple(
        index
        for index, item in enumerate(row[:-1])
        if item.event.kind == note
        and event_duration_fraction(item.event) == Fraction(3, 4)
        and item.event.duration_dots == 1
        and item.event.duration_slashes == 1
    )
    return reserve_indices if reserve_indices == (1, 27) else ()

def dotted_cross_row_entry_reserve_indices(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> tuple[int, ...]:
    """Return lyric, boundary, and hook reserves for a dotted cross-row entry."""

    if (
        len(row) != 30
        or row[-1].event.code != "|"
        or len({item.event.span.start.line for item in row}) != 1
        or tuple(
            index
            for index, item in enumerate(row)
            if item.event.kind == MusicTokenKind.BARLINE
        )
        != (10, 15, 29)
        or measure_durations(row) != (Fraction(4),) * 3
        or "rit" not in row[4].event.decorations
        or "zkh" not in row[16].event.decorations
    ):
        return ()

    lyric_profiles = tuple(
        lyric_text_by_event.get(
            (item.event.span.start.line, item.event.index),
            (),
        )
        for item in row
    )
    if (
        max((len(texts) for texts in lyric_profiles), default=0) != 1
        or any(len(texts) > 1 for texts in lyric_profiles)
        or not any(lyric_profiles[6])
        or lyric_profiles[24] != ("",)
    ):
        return ()

    note = MusicTokenKind.NOTE
    rest = MusicTokenKind.REST
    extension = MusicTokenKind.EXTENSION
    barline = MusicTokenKind.BARLINE
    expected_signature = (
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (rest, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 0, 0),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (barline, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1), 0, 0, 0, 1),
        (extension, Fraction(1), 0, 0, 0, 0),
        (extension, Fraction(1), 0, 0, 0, 0),
        (rest, Fraction(1), 0, 0, 0, 0),
        (barline, Fraction(), 0, 0, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 2), 0, 1, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(3, 4), 1, 1, 1, 0),
        (note, Fraction(1, 4), 0, 2, 0, 1),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 0, 0),
        (note, Fraction(1, 4), 0, 2, 1, 0),
        (barline, Fraction(), 0, 0, 0, 0),
    )
    if tuple(event_signature(item) for item in row) != expected_signature:
        return ()
    return (6, 15, 24)

__all__ = [
    "dotted_cross_row_entry_reserve_indices",
    "dotted_second_ending_release",
    "dual_verse_middle_bar_reserve_index",
    "lyric_deferred_hook_terminal_transfer_index",
    "lyric_owned_hidden_sentinel_reserve_index",
    "second_ending_dotted_lyric_reserve_indices",
    "single_verse_cross_bar_dotted_reserve_indices",
]
