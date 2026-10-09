"""Typed contracts for shared-system layout admission and projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType

from octopus.render.core.layout_types import LayoutEvent, PageMetrics
from octopus.render.layout_engine.grid.beat_grid import GridEventKey, SharedGridProjection

from ..profiles import LegacyIntrinsicProfile, SharedGraceReserve

LyricTextByVoice = Mapping[int, Mapping[tuple[int, int], tuple[str, ...]]]
LyricGapByVoice = Mapping[int, Mapping[tuple[int, int], int]]
GraceRawByVoice = Mapping[int, Mapping[int, str]]


@dataclass(frozen=True, slots=True)
class SharedSystemRequest:
    events: Sequence[LayoutEvent]
    left: float
    lyric_text_by_voice: LyricTextByVoice
    lyric_gap_by_voice: LyricGapByVoice
    grace_raw_by_voice: GraceRawByVoice
    system_row_count: int | None
    authoritative_group_index: int | None = None
    grid_lyric_text_by_voice: LyricTextByVoice | None = None
    hidden_events: Sequence[LayoutEvent] = ()


@dataclass(frozen=True, slots=True)
class SharedSystemAdmission:
    rows: tuple[list[LayoutEvent], ...]
    voice_rows: tuple[list[list[LayoutEvent]], ...]
    lyric_text_by_voice: LyricTextByVoice
    lyric_gap_by_voice: LyricGapByVoice
    grace_raw_by_voice: GraceRawByVoice
    allows_two_voice_unequal_slot_grid: bool
    uses_mixed_note_origins: bool
    mixed_origin_four_voice_grid: bool
    uses_shared_first_onset_grace_anchor: bool
    first_onset_grace_anchor_width: float
    uses_merged_four_row_grid: bool
    uses_leading_two_voice_grid: bool


@dataclass(frozen=True, slots=True)
class SharedSystemClassificationRequest:
    admission: SharedSystemAdmission
    metrics: PageMetrics
    left: float
    primary_system_verse_count: int
    system_row_count: int | None


@dataclass(frozen=True, slots=True)
class SharedSystemClassification:
    visible_lyric_rows: tuple[bool, ...]
    dual_verse_ascii_authority_indices: tuple[int, ...]
    multi_voice_ascii_authority_indices: tuple[int, ...]
    shared_leading_accidental_reserve: float
    uses_directive_origin_grid: bool
    uses_lyricless_four_voice_grid: bool
    uses_alternating_cjk_four_voice_grid: bool
    uses_unequal_slot_duration_grid: bool
    uses_single_authority_four_voice_grid: bool
    uses_two_voice_dual_verse_ascii_grid: bool
    uses_multi_voice_ascii_mixed_rhythm_grid: bool
    uses_multi_voice_heterogeneous_authority_grid: bool
    uses_primary_compound_beat_grid: bool
    uses_primary_dual_verse_compound_grid: bool


@dataclass(frozen=True, slots=True)
class SharedProjectionPolicy:
    """Immutable projection policy values assembled from semantic owners."""

    mixed_origin_four_voice_grid: bool = False
    uses_primary_modified_ending_grid: bool = False
    uses_primary_parallel_voice_denominator: bool = False
    uses_dominant_primary_lyric_grid: bool = False
    uses_primary_lyric_parallel_grid: bool = False
    uses_two_voice_tied_response_lyric_grid: bool = False
    primary_call_response_starts_with_two_rests: bool = False
    uses_compound_aligned_two_voice_lyric_grid: bool = False
    uses_compact_four_voice_grid: bool = False
    uses_shared_first_onset_grace_anchor: bool = False
    first_onset_grace_anchor_width: float = 0.0
    uses_multi_lyric_three_voice_grid: bool = False
    uses_three_authority_dotted_grid: bool = False
    uses_two_voice_five_measure_lyric_grid: bool = False
    uses_primary_compound_beat_grid: bool = False
    uses_four_beat_refinement_grid: bool = False
    uses_lyricless_coarse_secondary_grid: bool = False
    uses_single_lyric_aligned_slot_grid: bool = False


@dataclass(frozen=True, slots=True)
class SharedProjectionRequest:
    rows: list[list[LayoutEvent]]
    profiles: list[LegacyIntrinsicProfile]
    reconciled_widths: list[tuple[float, ...]]
    metrics: PageMetrics
    left: float
    lyric_text_by_voice: LyricTextByVoice
    shared_grace_raw: GraceRawByVoice
    skip_indices_by_row: list[frozenset[int]]
    shared_leading_accidental_reserve: float
    policy: SharedProjectionPolicy = field(default_factory=SharedProjectionPolicy)
    origin_offset: float = 0.0


@dataclass(frozen=True, slots=True)
class DsbShadowGridProjection:
    projection: SharedGridProjection
    visible_event_adjustments: Mapping[GridEventKey, Fraction]
    barline_adjustments: tuple[Fraction, ...]
    hidden_event_offsets: Mapping[tuple[int, int, int], Fraction]
    total_reserve: Fraction
    hidden_event_right_pins: frozenset[tuple[int, int, int]] = frozenset()
    visible_event_offsets: Mapping[GridEventKey, Fraction] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class SharedProjectionPlan:
    request: SharedProjectionRequest
    reconciled_widths: list[tuple[float, ...]]
    grace_timeline: tuple[SharedGraceReserve, ...]
    profile_denominators: tuple[float, ...]
    right: float
    scale: float
    shared_anchor_offset: float
    uses_measure_origin_spacing: bool
    grid_projection: SharedGridProjection | None = None
    grid_owned: bool = False
    dsb_union_grid: bool = False
    dsb_shadow_grid: DsbShadowGridProjection | None = None


__all__ = [
    "GraceRawByVoice",
    "DsbShadowGridProjection",
    "LyricGapByVoice",
    "LyricTextByVoice",
    "SharedSystemAdmission",
    "SharedSystemClassification",
    "SharedSystemClassificationRequest",
    "SharedSystemRequest",
    "SharedProjectionPolicy",
    "SharedProjectionPlan",
    "SharedProjectionRequest",
]
