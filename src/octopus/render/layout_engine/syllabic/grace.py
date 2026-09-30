"""Grace timing and additive reserve planning for syllabic rows."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout_engine.hidden.hidden_streams import (
    event_duration_fraction as _event_duration_fraction,
)
from octopus.render.layout_engine.lyrics.lyric_selection import (
    fixed_lyric_connector_positions as _fixed_lyric_connector_positions,
)

from ....parser.ast import MusicTokenKind
from .models import (
    SyllabicGraceReserveState,
    SyllabicGraceState,
    SyllabicProfileState,
    SyllabicRowRequest,
)


def build_syllabic_grace_state(
    request: SyllabicRowRequest,
    profile_state: SyllabicProfileState,
) -> SyllabicGraceState | None:
    reserve_state = _build_grace_reserve_state(request, profile_state)
    return _build_grace_timeline_state(request, profile_state, reserve_state)


def uses_hidden_rest_led_internal_zkh_reserve_release(
    row: Sequence[LayoutEvent],
    index: int,
) -> bool:
    """Identify the first-ending hidden-rest-led hook without its legacy reserve.

    A first-ending opener historically enabled the dotted-hook reserve for every
    internal ``zkh`` event.  The source topology represented by a zero-duration
    hidden-rest sentinel immediately followed by a one-slash tied hook does not
    retain that reserve; the hook's normal event width remains authoritative.
    """
    if index <= 0 or index >= len(row) - 1:
        return False
    opener = row[0].event
    predecessor = row[index - 1].event
    event = row[index].event
    return (
        opener.kind == MusicTokenKind.BARLINE
        and opener.code.startswith("|n[")
        and predecessor.kind == MusicTokenKind.HIDDEN_REST
        and predecessor.code == "8"
        and _event_duration_fraction(predecessor) == 0
        and event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and event.duration_slashes == 1
        and "zkh" in event.decorations
        and "~" in event.code
    )




def _build_grace_reserve_state(
    request: SyllabicRowRequest,
    profile_state: SyllabicProfileState,
) -> SyllabicGraceReserveState:
    """Compute grace-note reserve positions for one row.

    Detects the REF-decoded grace shapes (compound half-beat spanning hooks,
    leading-hook DSB tails, repeated-extension hook openers via the ``zkh``
    decoration signature) and records where leading/dotted/DSB-anchor reserves must
    be inserted so grace notes land on their reference columns."""
    row = request.row
    lyric_text_by_event = request.lyric_text_by_event
    grace_host_indices = request.grace_host_indices
    grace_raw_by_host = request.grace_raw_by_host
    intrinsic_width = profile_state.intrinsic_width
    uses_compound_half_beat_spanning_hook = profile_state.uses_compound_half_beat_spanning_hook
    uses_leading_hook_dsb_tail_grid = profile_state.uses_leading_hook_dsb_tail_grid
    uses_repeated_extension_hook_opener = (
        "zkh" in row[0].event.decorations
        and len(row) >= 6
        and len(row) % 3 == 0
        and all(
            tuple(item.event.kind for item in row[index : index + 3])
            == (
                MusicTokenKind.NOTE,
                MusicTokenKind.EXTENSION,
                MusicTokenKind.BARLINE,
            )
            for index in range(0, len(row), 3)
        )
    )
    high_double_hook_reserve = (
        (
            9.0
            if any("ykh" in item.event.code for item in row[1:])
            else 18.0
        )
        if "zkh" in row[0].event.decorations
        and row[0].event.duration_slashes == 2
        and row[0].event.octave > 1
        else 0.0
    )
    uses_leading_accidental_double_extension_grid = (
        row[0].event.accidental is not None
        and row[0].event.code.count("(") == 0
        and row[0].event.duration_slashes == 1
        and len(row) >= 4
        and row[-3].event.kind == MusicTokenKind.EXTENSION
        and row[-2].event.kind == MusicTokenKind.EXTENSION
        and row[-1].event.kind == MusicTokenKind.BARLINE
    )
    leading_accidental_reserve = (
        2.0 * 3.6 if uses_leading_accidental_double_extension_grid else 0.0
    )
    if uses_repeated_extension_hook_opener or uses_compound_half_beat_spanning_hook:
        intrinsic_width += 9.0
    intrinsic_width += high_double_hook_reserve
    if uses_leading_accidental_double_extension_grid:
        intrinsic_width += leading_accidental_reserve + 9.0
    if uses_leading_hook_dsb_tail_grid:
        intrinsic_width += 9.0
    uses_lyricless_full_row_hook = (
        "zkh" in row[0].event.decorations
        and "ykh" in row[-2].event.decorations
        and row[0].event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and row[1].event.kind == MusicTokenKind.BARLINE
        and row[-1].event.code == "|w"
        and not any(text for texts in lyric_text_by_event.values() for text in texts)
    )
    if uses_lyricless_full_row_hook:
        intrinsic_width += 9.0
    uses_dotted_leading_hook = (
        row[0].event.duration_dots
        and "zkh" in row[0].event.decorations
        and any("ykh" in item.event.decorations for item in row[1:-2])
    )
    if uses_dotted_leading_hook:
        intrinsic_width += 9.0
    hook_closing_hidden_positions = tuple(
        index
        for index, item in enumerate(row[1:-1], start=1)
        if item.event.kind == MusicTokenKind.HIDDEN_REST
        and "ykh" in item.event.decorations
    )
    uses_tied_hidden_hook_closing_run = (
        row[-1].event.code == "|y]"
        and bool(hook_closing_hidden_positions)
        and any(
            item.event.duration_dots and "~" in item.event.code
            for item in row[: hook_closing_hidden_positions[0]]
        )
        and any(
            item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
            for item in row[hook_closing_hidden_positions[-1] + 1 : -1]
        )
    )
    hidden_hook_closing_reserve_positions = frozenset(
        {hook_closing_hidden_positions[0]}
        if uses_tied_hidden_hook_closing_run
        else ()
    )
    # A tied zkh note continues into the following note, so the hook's
    # opening gap is absorbed by the tie and no pre-reserve is added.  The
    # corpus census of every dotted-hook reserve site (seven rows) shows the
    # +9 present for all untied openers and absent for the single tied one
    # (Horizon p1 row `6,/&zkh~`, which otherwise over-advances by 9 units).
    dotted_hook_reserve_positions = frozenset(
        index
        for index, item in enumerate(row[:-1])
        if index > 0
        and "zkh" in item.event.decorations
        and not uses_hidden_rest_led_internal_zkh_reserve_release(row, index)
        and (
            item.event.duration_dots
            or row[0].event.code.startswith("|n[")
        )
    ) | hidden_hook_closing_reserve_positions
    intrinsic_width += 9.0 * len(dotted_hook_reserve_positions)
    dsb_anchor_reserve_positions = frozenset(
        index + 1
        for index, item in enumerate(row[:-1])
        if "&dsb_a" in item.event.code
        and "&bz" not in item.event.code
        and (row[-1].event.code == "|j" or uses_leading_hook_dsb_tail_grid)
        and (
            row[-2].event.kind
            in {MusicTokenKind.REST, MusicTokenKind.HIDDEN_REST}
            or uses_leading_hook_dsb_tail_grid
            and row[-2].event.kind == MusicTokenKind.EXTENSION
        )
    )
    intrinsic_width += 14.4 * len(dsb_anchor_reserve_positions)
    if (
        any(
            sum(char in "1234567" for char in raw) == 1
            for raw in (grace_raw_by_host or {}).values()
        )
        and not any(
            text
            for texts in lyric_text_by_event.values()
            for text in texts
        )
    ):
        intrinsic_width += 9.0
    if (
        row[0].event.index in grace_host_indices
        and row[0].event.duration_dots
    ):
        intrinsic_width -= 9.0
    return SyllabicGraceReserveState(
        intrinsic_width=intrinsic_width,
        leading_accidental_reserve=leading_accidental_reserve,
        dotted_hook_positions=frozenset(dotted_hook_reserve_positions),
        dsb_anchor_positions=frozenset(dsb_anchor_reserve_positions),
    )



def _build_grace_timeline_state(
    request: SyllabicRowRequest,
    profile_state: SyllabicProfileState,
    reserve_state: SyllabicGraceReserveState,
) -> SyllabicGraceState | None:
    """Lay grace notes onto the row timeline using the reserve state.

    Walks the row with the intrinsic cursor, applying compound-meter and dotted
    closer adjustments plus every reserve position from the reserve state; returns
    None when the row has no positive intrinsic width (nothing to place)."""
    row = request.row
    lyric_text_by_event = request.lyric_text_by_event
    grace_host_indices = request.grace_host_indices
    grace_raw_by_host = request.grace_raw_by_host
    uses_compound_meter = profile_state.uses_compound_meter
    compound_tied_dotted_closers = profile_state.compound_tied_dotted_closers
    intrinsic_width = reserve_state.intrinsic_width
    leading_accidental_reserve = reserve_state.leading_accidental_reserve
    dotted_hook_reserve_positions = reserve_state.dotted_hook_positions
    dsb_anchor_reserve_positions = reserve_state.dsb_anchor_positions
    if intrinsic_width <= 0:
        return None
    grace_width_by_position = {
        index: 7.0
        * sum(
            char in "1234567"
            for char in (grace_raw_by_host or {}).get(item.event.index, "")
        )
        for index, item in enumerate(row[:-1])
        if item.event.index in grace_host_indices
    }
    fixed_grace_width = sum(grace_width_by_position.values())
    rhythmic_onsets: list[Fraction] = []
    rhythmic_onset = Fraction()
    for item in row:
        rhythmic_onsets.append(rhythmic_onset)
        if item.event.kind != MusicTokenKind.BARLINE:
            rhythmic_onset += _event_duration_fraction(item.event)
    compound_beat = Fraction(3, 2)
    grace_expiry_by_position = {
        position: (rhythmic_onsets[position] // compound_beat + 1) * compound_beat
        for position in grace_width_by_position
        if uses_compound_meter and "~" in row[position].event.code
    }
    grace_replacement_by_position: dict[int, int] = {}
    latest_grace_position_by_measure_and_raw: dict[tuple[int, str], int] = {}
    grace_positions_by_measure: dict[int, list[int]] = {}
    row_lyric_verse_count = max(
        (
            len(
                lyric_text_by_event.get(
                    (item.event.span.start.line, item.event.index),
                    (),
                )
            )
            for item in row
        ),
        default=0,
    )
    for position in grace_width_by_position:
        raw = (grace_raw_by_host or {}).get(row[position].event.index, "")
        measure = sum(
            item.event.kind == MusicTokenKind.BARLINE
            for item in row[:position]
        )
        key = (measure, raw)
        grace_positions_by_measure.setdefault(measure, []).append(position)
        previous_position = latest_grace_position_by_measure_and_raw.get(key)
        if previous_position is not None:
            replacement_position = position
            if row[position].event.duration_slashes:
                replacement_position = next(
                    (
                        later
                        for later in range(position + 1, len(row))
                        if row[later].event.kind == MusicTokenKind.BARLINE
                    ),
                    position,
                )
            grace_replacement_by_position[previous_position] = replacement_position
        latest_grace_position_by_measure_and_raw[key] = position
    first_grace_measure = min(grace_positions_by_measure, default=None)
    for measure, positions in grace_positions_by_measure.items():
        measure_start = max(
            (
                index + 1
                for index, item in enumerate(row[: positions[0]])
                if item.event.kind == MusicTokenKind.BARLINE
            ),
            default=0,
        )
        uses_generated_tail_grace_expiry = (
            row[-1].event.code == "|w"
            and row_lyric_verse_count >= 2
            and (
                len(positions) >= 2
                or measure == first_grace_measure
                and positions[0] - measure_start >= 3
            )
        )
        if len(positions) < 3 and not uses_generated_tail_grace_expiry:
            continue
        closing_bar = next(
            (
                later
                for later in range(positions[-1] + 1, len(row))
                if row[later].event.kind == MusicTokenKind.BARLINE
            ),
            None,
        )
        if closing_bar is not None:
            grace_replacement_by_position.setdefault(positions[0], closing_bar)
    if 0 in grace_width_by_position and row[0].event.duration_slashes:
        first_bar = next(
            (
                position
                for position, item in enumerate(row[1:], start=1)
                if item.event.kind == MusicTokenKind.BARLINE
            ),
            None,
        )
        if first_bar is not None:
            grace_replacement_by_position.setdefault(0, first_bar)
    if 0 in grace_width_by_position and row[0].event.duration_dots:
        grace_replacement_by_position.clear()
        first_bar = next(
            (
                position
                for position, item in enumerate(row[1:], start=1)
                if item.event.kind == MusicTokenKind.BARLINE
            ),
            None,
        )
        if first_bar is not None:
            grace_replacement_by_position[0] = first_bar

    fixed_lyric_connector_positions = _fixed_lyric_connector_positions(
        row,
        lyric_text_by_event,
    )
    if uses_compound_meter and fixed_lyric_connector_positions:
        terminal_connector = len(row) - 2 in fixed_lyric_connector_positions
        if (
            terminal_connector
            and len(fixed_lyric_connector_positions) == 1
            and not compound_tied_dotted_closers
        ):
            intrinsic_width += 9.0
        elif terminal_connector:
            fixed_lyric_connector_positions = frozenset()
    return SyllabicGraceState(
        intrinsic_width=intrinsic_width,
        leading_accidental_reserve=leading_accidental_reserve,
        dotted_hook_positions=frozenset(dotted_hook_reserve_positions),
        dsb_anchor_positions=frozenset(dsb_anchor_reserve_positions),
        fixed_lyric_connector_positions=fixed_lyric_connector_positions,
        width_by_position=grace_width_by_position,
        expiry_by_position=grace_expiry_by_position,
        replacement_by_position=grace_replacement_by_position,
        rhythmic_onsets=tuple(rhythmic_onsets),
        fixed_width=fixed_grace_width,
        row_lyric_verse_count=row_lyric_verse_count,
    )


__all__ = [
    "build_syllabic_grace_state",
    "uses_hidden_rest_led_internal_zkh_reserve_release",
]
