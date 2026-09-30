"""Onset alignment for host-local shared grace reserves."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ..hidden.hidden_streams import event_duration_fraction
from .models import SharedProjectionPlan


def align_host_local_grace_measure_onsets(plan: SharedProjectionPlan) -> None:
    """Align a grace host's measure across voices by exact rhythmic onset."""

    for reserve in plan.grace_timeline:
        if not reserve.expires_in_host_voice or len(reserve.host_voices) != 1:
            continue
        host_voice = next(iter(reserve.host_voices))
        host_row = next(
            (row for row in plan.request.rows if row and row[0].voice == host_voice),
            None,
        )
        if host_row is None:
            continue
        host_onsets = _row_onsets(host_row)
        measure_start = max(
            (
                onset
                for item, onset in zip(host_row, host_onsets, strict=True)
                if item.event.kind == MusicTokenKind.BARLINE and onset < reserve.onset
            ),
            default=Fraction(),
        )
        host_by_onset = {
            onset: item
            for item, onset in zip(host_row, host_onsets, strict=True)
            if item.event.kind != MusicTokenKind.BARLINE
            and measure_start <= onset < reserve.expiry
        }
        for row in plan.request.rows:
            if row is host_row:
                continue
            for item, onset in zip(row, _row_onsets(row), strict=True):
                host = host_by_onset.get(onset)
                if (
                    item.event.kind != MusicTokenKind.BARLINE
                    and host is not None
                    and measure_start <= onset < reserve.expiry
                ):
                    item.x = host.x
                    item.style_x = host.x


def _row_onsets(row: Sequence[LayoutEvent]) -> tuple[Fraction, ...]:
    onset = Fraction()
    onsets: list[Fraction] = []
    for item in row:
        onsets.append(onset)
        if item.event.kind != MusicTokenKind.BARLINE:
            onset += event_duration_fraction(item.event)
    return tuple(onsets)


__all__ = ["align_host_local_grace_measure_onsets"]
