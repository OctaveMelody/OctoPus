"""Shared grace-marker width reserves for legacy shared-system rows.

The grid path carries reservations on host events (see
``octopus.model_grace``); these helpers serve the legacy interval-based
projection, where grace markers widen the cursor as it walks each row.
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from octopus.normalization.types import MusicEvent

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from ..profiles import SharedGraceReserve
from .models import GraceRawByVoice


def shared_grace_timeline(
    rows: list[list[LayoutEvent]],
    grace_raw_by_voice: GraceRawByVoice,
    *,
    tied_expiry_beat: Fraction | None = None,
) -> tuple[SharedGraceReserve, ...]:
    """Build the per-onset grace reserve records for a set of legacy rows.

    Walks each row accumulating Fraction onsets (barlines do not advance
    time), and for every grace host emits a :class:`SharedGraceReserve`:
    width 7.0 per digit of the raw catalog value, expiry at the next barline
    after the host (or end of row), the tied flag, and — for bracket-marked
    tied hosts — the payback onset (first gap after the tie group ends,
    unless that gap crosses a barline). Reserves sharing an onset merge: the
    wider one wins and the host-voice sets union. Result is sorted by onset.
    """
    reserves_by_onset: dict[Fraction, SharedGraceReserve] = {}
    for row in rows:
        grace_raw_by_host = grace_raw_by_voice.get(row[0].voice, {})
        onset = Fraction()
        bar_onsets: list[Fraction] = []
        onset_by_event_index: dict[int, Fraction] = {}
        event_by_index: dict[int, MusicEvent] = {}
        for item in row:
            onset_by_event_index[item.event.index] = onset
            event_by_index[item.event.index] = item.event
            if item.event.kind == MusicTokenKind.BARLINE:
                bar_onsets.append(onset)
            else:
                onset += event_duration_fraction(item.event)
        for event_index, raw in grace_raw_by_host.items():
            host = event_by_index.get(event_index)
            host_onset = onset_by_event_index.get(event_index)
            if host is None or host_onset is None:
                continue
            expiry = next((bar for bar in bar_onsets if bar > host_onset), onset)
            payback_onset: Fraction | None = None
            if "~" in host.code:
                position = next(
                    i for i, item in enumerate(row) if item.event.index == event_index
                )
                group_end = position
                while group_end < len(row) - 1 and "~" in row[group_end].event.code:
                    group_end += 1
                if (
                    group_end + 1 < len(row)
                    and row[group_end + 1].event.kind != MusicTokenKind.BARLINE
                ):
                    payback_onset = onset_by_event_index.get(
                        row[group_end + 1].event.index
                    )
            if tied_expiry_beat is not None and "~" in host.code:
                expiry = (
                    host_onset // tied_expiry_beat + 1
                ) * tied_expiry_beat
            reserve = SharedGraceReserve(
                onset=host_onset,
                width=7.0 * sum(char in "1234567" for char in raw),
                expiry=expiry,
                tied="~" in host.code,
                expires_in_host_voice=(
                    host.octave < 0
                    and host.duration_dots > 0
                    and host.duration_slashes == 1
                    and any(
                        ":slur:" in role and role.endswith(":start")
                        for role in host.construct_roles
                    )
                    and any(
                        ":modifier:" in role and role.endswith(":host")
                        for role in host.construct_roles
                    )
                ),
                subdivision=raw.count("/"),
                host_voices=frozenset({row[0].voice}),
                payback_onset=payback_onset,
            )
            previous = reserves_by_onset.get(host_onset)
            if previous is not None:
                reserve = replace(
                    reserve if reserve.width >= previous.width else previous,
                    host_voices=previous.host_voices | reserve.host_voices,
                )
            reserves_by_onset[host_onset] = reserve
    return tuple(reserve for _, reserve in sorted(reserves_by_onset.items()))


def shared_grace_cursor_width(
    timeline: tuple[SharedGraceReserve, ...],
    *,
    voice: int,
    onset: Fraction,
    at_barline: bool,
) -> float:
    """Total grace width active on this voice's cursor at this onset.

    A reserve contributes when the cursor is past its onset (a barline exactly
    at the onset does not count — the marker opens the gap, not the barline)
    and either it is non-tied / not host-voice-restricted (plain expiry rule)
    or it is a tied host-voice reserve still before its payback onset. Tied
    reserves subtract their width at/after the payback onset: the reference
    keeps the full cell and pays back a flat amount on the first gap after
    the tie group ends.
    """
    width = 0.0
    for reserve in timeline:
        if onset < reserve.onset or at_barline and onset == reserve.onset:
            continue
        if (
            not (reserve.tied or reserve.expires_in_host_voice)
            or voice not in reserve.host_voices
            or onset < reserve.expiry
        ):
            width += reserve.width
            # A bracket-marked tied note pays its reservation back on the
            # first gap after the tie group ends (oracle-verified 2026-09-06,
            # Looking-Back p1 system 3: 27u cell minus a flat 7px, with the
            # pinned closing barline absorbing the remainder).
            if reserve.payback_onset is not None and onset >= reserve.payback_onset:
                width -= reserve.width
    return width


def shared_grace_denominator_adjustment(
    rows: list[list[LayoutEvent]], grace_raw_by_voice: GraceRawByVoice
) -> float:
    """Denominator deduction keeping scale and cursor consistent with the reserves.

    9.0 per grace host whose raw catalog width is exactly as long as its
    slash count (a full-width marker on a single-slash note): the cursor gains
    the reserve's width, so the row denominator must lose the matching amount
    or every later column would scale too small.
    """
    adjusted_onsets: set[Fraction] = set()
    for row in rows:
        grace_raw_by_host = grace_raw_by_voice.get(row[0].voice, {})
        onset = Fraction()
        for item in row:
            raw = grace_raw_by_host.get(item.event.index)
            if (
                raw is not None
                and item.event.duration_slashes == 1
                and raw.count("/") == item.event.duration_slashes
            ):
                adjusted_onsets.add(onset)
            if item.event.kind != MusicTokenKind.BARLINE:
                onset += event_duration_fraction(item.event)
    return 9.0 * len(adjusted_onsets)
