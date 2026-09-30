"""Ordered intrinsic-profile and reserve mutations for syllabic rows."""

from __future__ import annotations

import unicodedata
from dataclasses import replace

from ....parser.ast import MusicTokenKind
from ...core.layout_types import GEOMETRY_EPSILON, LayoutEvent
from ..dotted.dotted_classifiers import (
    hidden_sentinel_dotted_terminal_reserve_indices as _hidden_sentinel_dotted_correction,
)
from ..dotted.dotted_reserves import (
    dotted_cross_row_entry_reserve_indices as _dotted_cross_row_entry_reserve_indices,
)
from ..dotted.dotted_reserves import (
    dotted_second_ending_release as _dotted_second_ending_release,
)
from ..dotted.dotted_reserves import (
    dual_verse_middle_bar_reserve_index as _dual_verse_middle_bar_reserve_index,
)
from ..dotted.dotted_reserves import (
    lyric_deferred_hook_terminal_transfer_index as _lyric_deferred_hook_transfer_index,
)
from ..dotted.dotted_reserves import (
    lyric_owned_hidden_sentinel_reserve_index as _hidden_sentinel_reserve_index,
)
from ..dotted.dotted_reserves import (
    second_ending_dotted_lyric_reserve_indices as _second_ending_dotted_reserve_indices,
)
from ..dotted.dotted_reserves import (
    single_verse_cross_bar_dotted_reserve_indices as _single_verse_cross_bar_reserve_indices,
)
from ..dotted.dotted_temporary_meter import (
    dotted_temporary_meter_reserve as _dotted_temporary_meter_reserve,
)
from ..dotted.dotted_terminal_transfers import (
    dotted_lyric_terminal_release_indices as _dotted_lyric_terminal_release_indices,
)
from ..dotted.dotted_terminal_transfers import (
    lyricless_dotted_terminal_transfer as _lyricless_dotted_terminal_transfer,
)
from ..hidden.hidden_pickup_reserves import (
    apply_decorated_prebar_reserves as _apply_decorated_prebar_reserves,
)
from ..hidden.hidden_pickup_reserves import (
    apply_hidden_pickup_reserves as _apply_hidden_pickup_reserves,
)
from ..hidden.hidden_pickup_reserves import (
    leading_first_ending_hidden_sentinel_release_index as _leading_first_ending_sentinel_index,
)
from ..intrinsic.builder import build_legacy_intrinsic_profile as _legacy_intrinsic_profile
from ..keys import resolve_source_event_key_indices as _resolve_source_event_key_indices
from ..profiles import LegacyIntrinsicProfile
from ..reserves.compound_reserves import (
    apply_compound_beat_boundary_reserves as _apply_compound_beat_boundary_reserves,
)
from ..reserves.interval_reserves import (
    add_interval_reserve as _add_interval_reserve,
)
from ..reserves.interval_reserves import (
    add_interval_reserves as _add_interval_reserves,
)
from ..reserves.interval_reserves import (
    allocate_dotted_onset_reserves as _allocate_dotted_onset_reserves,
)
from ..reserves.interval_reserves import (
    allocate_interval_reserves_with_terminal_release as _allocate_interval_terminal_reserves,
)
from ..reserves.interval_reserves import (
    release_interval_reserve_excess as _release_interval_reserve_excess,
)
from ..reserves.interval_reserves import (
    transfer_terminal_reserve_to_interval as _transfer_terminal_reserve_to_interval,
)
from ..reserves.reserve_classifiers import (
    subdivided_tie_followup_release_index as _subdivided_tie_release_index,
)
from ..streams import uses_compound_meter as _uses_compound_meter
from .models import SyllabicProfileState, SyllabicRowRequest


def build_syllabic_profile_state(request: SyllabicRowRequest) -> SyllabicProfileState:
    """Build the full syllabic profile state for one row.

    Layers, in order: the base intrinsic profile (compound-meter and hook-grid
    flags), dotted-profile reserves, hidden-pickup reserves, and second-ending
    denominator reconciliation. Returns the state consumed by grace planning and
    projection; None is never returned here — admission failures surface upstream."""
    row = request.row
    lyric_text_by_event = request.lyric_text_by_event
    leading_first_ending_sentinel_release_index = _leading_first_ending_sentinel_index(
        row,
        lyric_text_by_event,
        time_sig=request.metrics.time_sig,
    )
    (
        profile,
        uses_compound_meter,
        compound_tied_dotted_closers,
        uses_compound_half_beat_spanning_hook,
        uses_leading_hook_dsb_tail_grid,
    ) = _build_base_syllabic_profile(request)
    profile = _apply_dotted_profile_reserves(
        row,
        lyric_text_by_event,
        time_sig=request.metrics.time_sig,
        profile=profile,
    )
    profile = _apply_decorated_prebar_reserves(
        row,
        time_sig=request.metrics.time_sig,
        profile=profile,
    )
    subdivided_tie_release_index = _subdivided_tie_release_index(row)
    if (
        subdivided_tie_release_index is not None
        and subdivided_tie_release_index + 1 < len(profile.interval_widths)
    ):
        release = _release_interval_reserve_excess(
            profile.interval_widths,
            interval_index=subdivided_tie_release_index,
            retained_width=profile.interval_widths[subdivided_tie_release_index + 1],
        )
        profile = replace(profile, interval_widths=release.interval_widths)
    hidden_sentinel_reserve_index = _hidden_sentinel_reserve_index(
        row,
        lyric_text_by_event,
    )
    if hidden_sentinel_reserve_index is not None:
        allocation = _add_interval_reserve(
            profile.interval_widths,
            interval_index=hidden_sentinel_reserve_index,
            added_width=9.0,
        )
        profile = replace(profile, interval_widths=allocation.interval_widths)
    second_ending_dotted_reserve_indices = _second_ending_dotted_reserve_indices(
        row,
        lyric_text_by_event,
    )
    if second_ending_dotted_reserve_indices:
        allocation = _add_interval_reserves(
            profile.interval_widths,
            added_width_by_index=dict.fromkeys(second_ending_dotted_reserve_indices, 9.0),
        )
        profile = replace(profile, interval_widths=allocation.interval_widths)
    single_verse_cross_bar_reserve_indices = _single_verse_cross_bar_reserve_indices(
        row,
        lyric_text_by_event,
    )
    if single_verse_cross_bar_reserve_indices:
        allocation = _add_interval_reserves(
            profile.interval_widths,
            added_width_by_index=dict.fromkeys(single_verse_cross_bar_reserve_indices, 9.0),
        )
        profile = replace(profile, interval_widths=allocation.interval_widths)
    dotted_lyric_terminal_release_indices = _dotted_lyric_terminal_release_indices(
        row,
        lyric_text_by_event,
    )
    if dotted_lyric_terminal_release_indices:
        interval_terminal_allocation = _allocate_interval_terminal_reserves(
            profile.interval_widths,
            added_width_by_index=dict.fromkeys(dotted_lyric_terminal_release_indices, 9.0),
            terminal_reserve=profile.terminal_width,
            terminal_release=9.0,
        )
        profile = replace(
            profile,
            interval_widths=interval_terminal_allocation.interval_widths,
            terminal_width=interval_terminal_allocation.terminal_reserve,
        )
    lyricless_dotted_terminal_transfer = _lyricless_dotted_terminal_transfer(
        row,
        lyric_text_by_event,
    )
    if lyricless_dotted_terminal_transfer is not None:
        reserve_indices = _resolve_source_event_key_indices(
            row,
            lyricless_dotted_terminal_transfer.reserve_event_keys,
        )
        lyricless_allocation = _allocate_interval_terminal_reserves(
            profile.interval_widths,
            added_width_by_index=dict.fromkeys(
                reserve_indices, lyricless_dotted_terminal_transfer.reserve_width
            ),
            terminal_reserve=profile.terminal_width,
            terminal_release=lyricless_dotted_terminal_transfer.terminal_release,
        )
        profile = replace(
            profile,
            interval_widths=lyricless_allocation.interval_widths,
            terminal_width=lyricless_allocation.terminal_reserve,
        )
    dotted_cross_row_entry_reserve_indices = _dotted_cross_row_entry_reserve_indices(
        row,
        lyric_text_by_event,
    )
    if dotted_cross_row_entry_reserve_indices:
        cross_row_entry_allocation = _add_interval_reserves(
            profile.interval_widths,
            added_width_by_index=dict.fromkeys(dotted_cross_row_entry_reserve_indices, 9.0),
        )
        profile = replace(
            profile,
            interval_widths=cross_row_entry_allocation.interval_widths,
        )
    hidden_sentinel_dotted_correction = _hidden_sentinel_dotted_correction(
        row,
        lyric_text_by_event,
    )
    if hidden_sentinel_dotted_correction is not None:
        release_index, transfer_index, dotted_index = _resolve_source_event_key_indices(
            row,
            hidden_sentinel_dotted_correction.reserve_event_keys,
        )
        hidden_sentinel_dotted_allocation = _allocate_dotted_onset_reserves(
            profile.interval_widths,
            retained_width_by_index={release_index: 18.0},
            added_width_by_index={transfer_index: 3.6, dotted_index: 9.0},
            terminal_reserve=profile.terminal_width,
            terminal_increase=0.0,
        )
        profile = replace(
            profile,
            interval_widths=hidden_sentinel_dotted_allocation.interval_widths,
        )
    dual_verse_middle_bar_reserve_index = _dual_verse_middle_bar_reserve_index(
        row,
        lyric_text_by_event,
    )
    if dual_verse_middle_bar_reserve_index is not None:
        allocation = _add_interval_reserve(
            profile.interval_widths,
            interval_index=dual_verse_middle_bar_reserve_index,
            added_width=1.8,
        )
        profile = replace(profile, interval_widths=allocation.interval_widths)
    lyric_deferred_hook_transfer_index = _lyric_deferred_hook_transfer_index(
        row,
        lyric_text_by_event,
    )
    if lyric_deferred_hook_transfer_index is not None:
        transfer = _transfer_terminal_reserve_to_interval(
            profile.interval_widths,
            interval_index=lyric_deferred_hook_transfer_index,
            terminal_reserve=profile.terminal_width,
            transfer_width=9.0,
        )
        profile = replace(
            profile,
            interval_widths=transfer.interval_widths,
            terminal_width=transfer.terminal_reserve,
        )
    intrinsic_width = profile.denominator + request.intrinsic_width_adjustment
    return SyllabicProfileState(
        profile=profile,
        intrinsic_width=intrinsic_width,
        uses_compound_meter=uses_compound_meter,
        compound_tied_dotted_closers=tuple(compound_tied_dotted_closers),
        uses_compound_half_beat_spanning_hook=uses_compound_half_beat_spanning_hook,
        uses_leading_hook_dsb_tail_grid=uses_leading_hook_dsb_tail_grid,
        subdivided_tie_release_index=subdivided_tie_release_index,
        dual_verse_middle_bar_reserve_index=dual_verse_middle_bar_reserve_index,
        dotted_lyric_terminal_release_indices=tuple(dotted_lyric_terminal_release_indices),
        leading_first_ending_sentinel_release_index=(
            leading_first_ending_sentinel_release_index
        ),
    )


def _apply_dotted_profile_reserves(
    row: list[LayoutEvent],
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
    *,
    time_sig: str,
    profile: LegacyIntrinsicProfile,
) -> LegacyIntrinsicProfile:
    dotted_second_ending_release = _dotted_second_ending_release(
        row,
        lyric_text_by_event,
        time_sig=time_sig,
    )
    if dotted_second_ending_release is not None:
        base_interval_widths = profile.interval_widths
        base_terminal_width = profile.terminal_width
        base_denominator = profile.denominator
        release_indices = _resolve_source_event_key_indices(
            row,
            tuple(item.event_key for item in dotted_second_ending_release.retentions),
        )
        retained_width_by_index: dict[int, float] = {}
        for index, retention in zip(
            release_indices,
            dotted_second_ending_release.retentions,
            strict=True,
        ):
            actual_width = profile.interval_widths[index]
            if abs(actual_width - retention.expected_width) > GEOMETRY_EPSILON:
                raise ValueError(
                    "dotted second-ending base width drift for "
                    f"{retention.event_key}: expected {retention.expected_width}, "
                    f"actual {actual_width}"
                )
            retained_width_by_index[index] = retention.retained_width
        allocation = _allocate_dotted_onset_reserves(
            profile.interval_widths,
            retained_width_by_index=retained_width_by_index,
            added_width_by_index={},
            terminal_reserve=profile.terminal_width,
            terminal_increase=0.0,
        )
        if allocation.terminal_reserve != base_terminal_width:
            raise ValueError("dotted second-ending release changed terminal ownership")
        if any(
            allocation.interval_widths[index] != width
            for index, width in enumerate(base_interval_widths)
            if index not in release_indices
        ):
            raise ValueError("dotted second-ending release changed an unrelated interval")
        if (
            abs(allocation.denominator_change - dotted_second_ending_release.denominator_change)
            > GEOMETRY_EPSILON
        ):
            raise ValueError("dotted second-ending runtime denominator delta is inconsistent")
        profile = replace(profile, interval_widths=allocation.interval_widths)
        if abs(
            profile.denominator - (base_denominator + allocation.denominator_change)
        ) > GEOMETRY_EPSILON:
            raise ValueError("dotted second-ending final denominator is inconsistent")

    profile = _apply_hidden_pickup_reserves(
        row,
        lyric_text_by_event,
        time_sig=time_sig,
        profile=profile,
    )

    dotted_temporary_meter_reserve = _dotted_temporary_meter_reserve(
        row,
        lyric_text_by_event,
        time_sig=time_sig,
    )
    if dotted_temporary_meter_reserve is not None:
        base_interval_widths = profile.interval_widths
        base_terminal_width = profile.terminal_width
        base_denominator = profile.denominator
        release_indices = _resolve_source_event_key_indices(
            row,
            tuple(item.event_key for item in dotted_temporary_meter_reserve.retentions),
        )
        addition_indices = _resolve_source_event_key_indices(
            row,
            tuple(item.event_key for item in dotted_temporary_meter_reserve.additions),
        )
        temporary_retained_width_by_index: dict[int, float] = {}
        for index, retention in zip(
            release_indices,
            dotted_temporary_meter_reserve.retentions,
            strict=True,
        ):
            actual_width = profile.interval_widths[index]
            if abs(actual_width - retention.expected_width) > GEOMETRY_EPSILON:
                raise ValueError(
                    "temporary-meter dotted base width drift for "
                    f"{retention.event_key}: expected {retention.expected_width}, "
                    f"actual {actual_width}"
                )
            temporary_retained_width_by_index[index] = retention.retained_width
        added_width_by_index: dict[int, float] = {}
        for index, addition in zip(
            addition_indices,
            dotted_temporary_meter_reserve.additions,
            strict=True,
        ):
            actual_width = profile.interval_widths[index]
            if abs(actual_width - addition.expected_width) > GEOMETRY_EPSILON:
                raise ValueError(
                    "temporary-meter dotted base width drift for "
                    f"{addition.event_key}: expected {addition.expected_width}, "
                    f"actual {actual_width}"
                )
            added_width_by_index[index] = addition.adjusted_width - addition.expected_width
        allocation = _allocate_dotted_onset_reserves(
            profile.interval_widths,
            retained_width_by_index=temporary_retained_width_by_index,
            added_width_by_index=added_width_by_index,
            terminal_reserve=profile.terminal_width,
            terminal_increase=0.0,
        )
        if allocation.terminal_reserve != base_terminal_width:
            raise ValueError("temporary-meter dotted reserve changed terminal ownership")
        owner_indices = frozenset((*release_indices, *addition_indices))
        if any(
            allocation.interval_widths[index] != width
            for index, width in enumerate(base_interval_widths)
            if index not in owner_indices
        ):
            raise ValueError("temporary-meter dotted reserve changed an unrelated interval")
        if (
            abs(allocation.denominator_change - dotted_temporary_meter_reserve.denominator_change)
            > GEOMETRY_EPSILON
        ):
            raise ValueError("temporary-meter dotted denominator delta is inconsistent")
        profile = replace(profile, interval_widths=allocation.interval_widths)
        if abs(
            profile.denominator - (base_denominator + allocation.denominator_change)
        ) > GEOMETRY_EPSILON:
            raise ValueError("temporary-meter dotted final denominator is inconsistent")

    return profile


def _build_base_syllabic_profile(
    request: SyllabicRowRequest,
) -> tuple[LegacyIntrinsicProfile, bool, frozenset[int], bool, bool]:
    """Build the base (pre-reserve) syllabic profile for one row.

    Single-row layouts use the full dynamic/ornament mark reserves (27.0 unless a
    rest precedes the note); shared multi-row systems collapse to the plain step via
    the request flags. Also resolves compound-meter handling, tied dotted closers,
    and the hook/DSB grid shape flags carried in the returned state."""
    row = request.row
    metrics = request.metrics
    left = request.left
    lyric_text_by_event = request.lyric_text_by_event
    reserves_lyric_dotted_notes = request.reserves_lyric_dotted_notes
    uses_numbered_cjk_verse_label = request.uses_numbered_cjk_verse_label
    terminal_cross_row_hook = request.terminal_cross_row_hook
    localizes_cross_row_hook_opener = request.localizes_cross_row_hook_opener
    uses_lyricless_cross_row_compound_grid = request.uses_lyricless_cross_row_compound_grid
    # Single-row syllabic layouts use the base width model: dynamic/ornament
    # marks keep the full 27.0 reserve unless a rest precedes the note, and
    # shared multi-row systems collapse to the plain step via the flag.
    profile = _legacy_intrinsic_profile(
        row,
        metrics=metrics,
        left=left,
        lyric_text_by_event=lyric_text_by_event,
    )
    if uses_numbered_cjk_verse_label:
        interval_widths = list(profile.interval_widths)
        remaining_label_width = 20.0
        for index, item in enumerate(row[:-1]):
            texts = lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index),
                (),
            )
            long_texts = [
                text
                for text in texts
                if sum(
                    unicodedata.east_asian_width(character) in {"W", "F"}
                    for character in text.rstrip("，。！？、；：,")
                )
                >= 2
            ]
            if not long_texts or remaining_label_width <= 0:
                continue
            reserve = min(
                20.0
                if any(
                    text.endswith(("，", "。", "！", "？", "、", "；", "："))
                    for text in long_texts
                )
                else 10.0,
                remaining_label_width,
            )
            interval_widths[index] += reserve
            remaining_label_width -= reserve
        distributed_width = 20.0 - remaining_label_width
        if interval_widths and distributed_width:
            interval_widths[-1] -= distributed_width
        profile = replace(profile, interval_widths=tuple(interval_widths))
    if terminal_cross_row_hook and profile.interval_widths:
        interval_widths = list(profile.interval_widths)
        interval_widths[-1] += 9.0
        profile = replace(profile, interval_widths=tuple(interval_widths))
    if localizes_cross_row_hook_opener:
        interval_widths = list(profile.interval_widths)
        opener_index = next(
            (
                index
                for index, item in enumerate(row[:-1])
                if "zkh" in item.event.decorations
            ),
            None,
        )
        if opener_index is not None and opener_index < len(interval_widths):
            interval_widths[opener_index] += 9.0
            profile = replace(profile, interval_widths=tuple(interval_widths))
    uses_internal_temporary_meter = any(
        "'p:" in item.event.code
        for item in row[1:-1]
    )
    uses_meter_led_spanning_hook = (
        "'p:" in row[0].event.code
        and any("zkh" in item.event.decorations for item in row[1:-1])
        and "ykh" in row[-2].event.decorations
        and not any(
            text
            for item in row
            for text in lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index),
                (),
            )
        )
    )
    uses_compound_half_beat_spanning_hook = (
        _uses_compound_meter(metrics.time_sig)
        and "zkh" in row[0].event.decorations
        and any("ykh" in item.event.decorations for item in row[1:])
        and sum(item.event.kind == MusicTokenKind.BARLINE for item in row) >= 4
        and all(
            item.event.kind == MusicTokenKind.BARLINE
            or item.event.duration_slashes == 1
            for item in row
        )
    )
    if (
        uses_lyricless_cross_row_compound_grid
        or uses_internal_temporary_meter
        or uses_meter_led_spanning_hook
        or uses_compound_half_beat_spanning_hook
    ) and _uses_compound_meter(metrics.time_sig):
        profile = _apply_compound_beat_boundary_reserves(
            row,
            profile,
            borrows_following_reserve=uses_internal_temporary_meter,
            keeps_pickup_reserve=(
                len(row) > 1
                and row[1].event.kind == MusicTokenKind.BARLINE
            ),
        )
    uses_compound_meter = _uses_compound_meter(metrics.time_sig)
    compound_tied_dotted_closers = frozenset(
        index
        for index, item in enumerate(row[:-1])
        if uses_compound_meter
        and item.event.duration_dots
        and item.event.duration_slashes
        and ")" in item.event.code
        and "~" in item.event.code
        and row[index + 1].event.kind
        in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
    )
    if compound_tied_dotted_closers:
        interval_widths = list(profile.interval_widths)
        for index in compound_tied_dotted_closers:
            interval_widths[index] += 9.0
        profile = replace(profile, interval_widths=tuple(interval_widths))
    if reserves_lyric_dotted_notes:
        interval_widths = list(profile.interval_widths)
        for index, item in enumerate(row[:-2]):
            texts = lyric_text_by_event.get(
                (item.event.span.start.line, item.event.index),
                (),
            )
            if (
                item.event.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
                and item.event.duration_dots
                and item.event.duration_slashes
                and texts
            ):
                interval_widths[index] += 9.0
        profile = replace(profile, interval_widths=tuple(interval_widths))
    uses_leading_hook_dsb_tail_grid = (
        "zkh" in row[0].event.decorations
        and any("ykh" in item.event.decorations for item in row[1:])
        and any("&dsb_a" in item.event.code for item in row)
        and any(item.block == "dsb-tail" for item in row)
    )
    if uses_leading_hook_dsb_tail_grid:
        interval_widths = list(profile.interval_widths)
        dsb_anchor_index = next(
            index for index, item in enumerate(row) if "&dsb_a" in item.event.code
        )
        tied_span_index = next(
            index
            for index in range(dsb_anchor_index - 1, -1, -1)
            if "(" in row[index].event.code
            and row[index + 1].event.kind == MusicTokenKind.EXTENSION
            and ")" in row[index + 2].event.code
        )
        interval_widths[tied_span_index] -= 18.0
        interval_widths[tied_span_index + 1] -= 18.0
        profile = replace(profile, interval_widths=tuple(interval_widths))
    return (
        profile,
        uses_compound_meter,
        compound_tied_dotted_closers,
        uses_compound_half_beat_spanning_hook,
        uses_leading_hook_dsb_tail_grid,
    )

__all__ = ["build_syllabic_profile_state"]
