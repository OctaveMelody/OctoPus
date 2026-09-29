"""Measured dotted reserve mutation for shared systems."""

from __future__ import annotations

from dataclasses import replace

from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..dotted.shared_dotted_reserves import (
    shared_dotted_system_reserve,
)
from ..keys import resolve_source_event_key_indices, source_event_key
from ..profiles import LegacyIntrinsicProfile
from ..reserves.interval_reserves import allocate_dotted_onset_reserves
from .models import LyricTextByVoice


def apply_shared_dotted_system_reserve(
    rows: list[list[LayoutEvent]],
    profiles: list[LegacyIntrinsicProfile],
    reconciled_widths: list[tuple[float, ...]],
    *,
    lyric_text_by_voice: LyricTextByVoice,
    time_sig: str,
) -> tuple[list[LegacyIntrinsicProfile], list[tuple[float, ...]]]:
    policy = shared_dotted_system_reserve(
        rows,
        lyric_text_by_voice,
        time_sig=time_sig,
    )
    if policy is None:
        return profiles, reconciled_widths
    primary = rows[0]
    retention_indices = resolve_source_event_key_indices(
        primary,
        tuple(item.event_key for item in policy.retentions),
    )
    addition_indices = resolve_source_event_key_indices(
        primary,
        tuple(item.event_key for item in policy.additions),
    )
    base_widths = reconciled_widths[0]
    for indices, adjustments in (
        (retention_indices, policy.retentions),
        (addition_indices, policy.additions),
    ):
        for index, adjustment in zip(indices, adjustments, strict=True):
            actual_width = base_widths[index]
            if abs(actual_width - adjustment.expected_width) > GEOMETRY_EPSILON:
                raise ValueError(
                    "shared dotted base width drift for "
                    f"{adjustment.event_key}: expected {adjustment.expected_width}, "
                    f"actual {actual_width}"
                )
    allocation = allocate_dotted_onset_reserves(
        base_widths,
        retained_width_by_index={
            index: adjustment.adjusted_width
            for index, adjustment in zip(retention_indices, policy.retentions, strict=True)
        },
        added_width_by_index={
            index: adjustment.adjusted_width - adjustment.expected_width
            for index, adjustment in zip(addition_indices, policy.additions, strict=True)
        },
        terminal_reserve=profiles[0].terminal_width,
        terminal_increase=0.0,
    )
    if allocation.terminal_reserve != profiles[0].terminal_width:
        raise ValueError("shared dotted reserve changed terminal ownership")
    changed_indices = {*retention_indices, *addition_indices}
    if any(
        allocation.interval_widths[index] != width
        for index, width in enumerate(base_widths)
        if index not in changed_indices
    ):
        raise ValueError("shared dotted reserve changed an unrelated interval")
    base_denominator = max(
        sum(
            (
                *widths,
                profile.terminal_width,
                profile.final_bar_width,
                profile.denominator_adjustment,
            )
        )
        for widths, profile in zip(reconciled_widths, profiles, strict=True)
    )
    if abs(base_denominator - policy.expected_denominator) > GEOMETRY_EPSILON:
        raise ValueError(
            "shared dotted base denominator drift: "
            f"expected {policy.expected_denominator}, actual {base_denominator}"
        )
    denominator_row_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and source_event_key(row[0]) == policy.denominator_event_key
        ),
        None,
    )
    if denominator_row_index is None:
        raise ValueError("shared dotted denominator owner is absent")
    adjusted_profiles = list(profiles)
    adjusted_profiles[denominator_row_index] = replace(
        adjusted_profiles[denominator_row_index],
        denominator_adjustment=(
            adjusted_profiles[denominator_row_index].denominator_adjustment
            + policy.denominator_change
        ),
    )
    adjusted_widths = [allocation.interval_widths, *reconciled_widths[1:]]
    final_denominator = max(
        sum(
            (
                *widths,
                profile.terminal_width,
                profile.final_bar_width,
                profile.denominator_adjustment,
            )
        )
        for widths, profile in zip(adjusted_widths, adjusted_profiles, strict=True)
    )
    if abs(final_denominator - policy.final_denominator) > GEOMETRY_EPSILON:
        raise ValueError(
            "shared dotted final denominator is inconsistent: "
            f"expected {policy.final_denominator}, actual {final_denominator}"
        )
    return adjusted_profiles, adjusted_widths


__all__ = ["apply_shared_dotted_system_reserve"]
