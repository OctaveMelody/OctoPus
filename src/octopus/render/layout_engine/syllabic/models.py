"""Typed contracts for ordered syllabic-row planning and projection."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ...core.layout_types import LayoutEvent, PageMetrics
from ..profiles import LegacyIntrinsicProfile


@dataclass(frozen=True, slots=True)
class SyllabicRowRequest:
    row: list[LayoutEvent]
    metrics: PageMetrics
    left: float
    right: float
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]]
    requested_scale: float | None
    ragged: bool
    grace_host_indices: frozenset[int]
    grace_raw_by_host: dict[int, str]
    reserves_lyric_dotted_notes: bool
    uses_numbered_cjk_verse_label: bool
    intrinsic_width_adjustment: float
    uses_lyricless_cross_row_cursor: bool
    terminal_cross_row_hook: bool
    localizes_cross_row_hook_opener: bool
    uses_lyricless_cross_row_compound_grid: bool
    uses_undivided_cross_row_hook_transfer: bool


@dataclass(frozen=True, slots=True)
class SyllabicReservePlan:
    profile: LegacyIntrinsicProfile
    intrinsic_width: float
    leading_accidental_reserve: float
    dotted_hook_positions: frozenset[int]
    dsb_anchor_positions: frozenset[int]
    fixed_lyric_connector_positions: frozenset[int]
    bz_overlay_positions: frozenset[int]
    subdivided_tie_release_index: int | None
    dual_verse_middle_bar_reserve_index: int | None
    dotted_lyric_terminal_release_indices: tuple[int, ...] | None
    leading_first_ending_sentinel_release_index: int | None


@dataclass(frozen=True, slots=True)
class SyllabicProfileState:
    profile: LegacyIntrinsicProfile
    intrinsic_width: float
    uses_compound_meter: bool
    compound_tied_dotted_closers: tuple[int, ...]
    uses_compound_half_beat_spanning_hook: bool
    uses_leading_hook_dsb_tail_grid: bool
    subdivided_tie_release_index: int | None
    dual_verse_middle_bar_reserve_index: int | None
    dotted_lyric_terminal_release_indices: tuple[int, ...] | None
    leading_first_ending_sentinel_release_index: int | None


@dataclass(frozen=True, slots=True)
class SyllabicGraceState:
    intrinsic_width: float
    leading_accidental_reserve: float
    dotted_hook_positions: frozenset[int]
    dsb_anchor_positions: frozenset[int]
    fixed_lyric_connector_positions: frozenset[int]
    width_by_position: dict[int, float]
    expiry_by_position: dict[int, Fraction]
    replacement_by_position: dict[int, int]
    rhythmic_onsets: tuple[Fraction, ...]
    fixed_width: float
    row_lyric_verse_count: int


@dataclass(frozen=True)
class SyllabicGraceReserveState:
    intrinsic_width: float
    leading_accidental_reserve: float
    dotted_hook_positions: frozenset[int]
    dsb_anchor_positions: frozenset[int]


@dataclass(frozen=True, slots=True)
class SyllabicGracePlan:
    width_by_position: dict[int, float]
    expiry_by_position: dict[int, Fraction]
    replacement_by_position: dict[int, int]
    rhythmic_onsets: tuple[Fraction, ...]
    fixed_width: float

    def cursor_width(self, index: int, row_length: int) -> float:
        return sum(
            width
            for position, width in self.width_by_position.items()
            if position <= index
            and not (
                position in self.expiry_by_position
                and self.rhythmic_onsets[index] >= self.expiry_by_position[position]
            )
            and self.replacement_by_position.get(position, row_length) > index
        )


@dataclass(frozen=True, slots=True)
class SyllabicProjectionFlags:
    uses_ascii_lyrics: bool
    uses_cjk_dual_verse_four_four_grid: bool
    uses_compact_latin_bilingual_profile: bool
    uses_compact_terminal_lyric_run: bool
    uses_compound_meter: bool
    uses_dotted_open_extension_tail: bool
    uses_iterative_spacing: bool
    uses_local_scale: bool
    uses_low_pickup_parenthesized_ending_grid: bool
    uses_second_ending_grace_spacing: bool
    uses_special_leading_grid: bool


@dataclass(frozen=True, slots=True)
class SyllabicProjectionPlan:
    request: SyllabicRowRequest
    reserves: SyllabicReservePlan
    grace: SyllabicGracePlan
    flags: SyllabicProjectionFlags
    style_positions: tuple[float, ...]
    distributed_width: float
    leading_width: float
    scale: float
    row_lyric_verse_count: int
    duration_group_members: frozenset[int]
    duration_group_terminals: frozenset[int]
    first_row_bar_index: int


@dataclass(slots=True)
class SyllabicProjectionState:
    iterative_x: float
    expired_grace_positions: set[int]


__all__ = [
    "SyllabicGracePlan",
    "SyllabicGraceState",
    "SyllabicProfileState",
    "SyllabicProjectionFlags",
    "SyllabicProjectionPlan",
    "SyllabicProjectionState",
    "SyllabicReservePlan",
    "SyllabicRowRequest",
]
