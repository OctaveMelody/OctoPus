"""Immutable mathematical profiles used while extracting layout stages."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import fsum, isclose, isfinite

from ..core.layout_types import GEOMETRY_EPSILON


@dataclass(frozen=True)
class LegacyIntrinsicProfile:
    """Legacy intrinsic row profile retained as a typed migration boundary."""

    interval_widths: tuple[float, ...]
    raw_terminal_width: float
    terminal_width: float
    final_bar_width: float
    denominator_adjustment: float = 0.0

    @property
    def denominator(self) -> float:
        return fsum(
            (
                *self.interval_widths,
                self.terminal_width,
                self.final_bar_width,
                self.denominator_adjustment,
            )
        )


@dataclass(frozen=True)
class SharedGraceReserve:
    """One shared onset-zero grace reserve in the row timeline."""

    onset: Fraction
    width: float
    expiry: Fraction
    tied: bool
    expires_in_host_voice: bool
    subdivision: int
    host_voices: frozenset[int]
    # When a bracket-marked note is tied, the reference pays the reservation
    # back on the first gap after the tie group ends — but only when that gap
    # stays inside the measure (a group ending at a barline keeps the reserve
    # across the boundary; oracle-verified 2026-09-06 on Looking-Back p1
    # system 3 vs City-of-Light p1, where the same shape ends at a barline).
    payback_onset: Fraction | None = None


@dataclass(frozen=True, slots=True)
class MeasureGrid:
    """One measure's exact ordered rhythmic boundaries, including zero and its end."""

    measure_index: int
    boundaries: tuple[Fraction, ...]

    def __post_init__(self) -> None:
        if self.measure_index < 0:
            raise ValueError("measure_index must be non-negative")
        if not self.boundaries or self.boundaries[0] != 0:
            raise ValueError("measure boundaries must start at zero")
        if any(boundary < 0 for boundary in self.boundaries):
            raise ValueError("measure boundaries must be non-negative")
        if any(
            left >= right
            for left, right in zip(self.boundaries, self.boundaries[1:], strict=False)
        ):
            raise ValueError("measure boundaries must be strictly increasing")

    @property
    def segment_durations(self) -> tuple[Fraction, ...]:
        return tuple(
            right - left
            for left, right in zip(self.boundaries, self.boundaries[1:], strict=False)
        )

    @property
    def duration(self) -> Fraction:
        return self.boundaries[-1]


@dataclass(frozen=True, slots=True)
class RowWidthAllocation:
    """Projected row widths and reserves governed by one conservation equation."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    fixed_gap_width: float
    available_width: float

    def __post_init__(self) -> None:
        values = (
            *self.interval_widths,
            self.terminal_reserve,
            self.fixed_gap_width,
            self.available_width,
        )
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("row widths and reserves must be finite and non-negative")

    @property
    def occupied_width(self) -> float:
        return fsum(
            (
                *self.interval_widths,
                self.terminal_reserve,
                self.fixed_gap_width,
            )
        )

    @property
    def residual(self) -> float:
        return self.available_width - self.occupied_width

    def is_conserved(self, *, tolerance: float = GEOMETRY_EPSILON) -> bool:
        return isclose(
            self.occupied_width,
            self.available_width,
            rel_tol=0.0,
            abs_tol=tolerance,
        )

    def require_conserved(self, *, tolerance: float = GEOMETRY_EPSILON) -> None:
        if not self.is_conserved(tolerance=tolerance):
            raise ValueError(f"row width allocation residual is {self.residual}")


@dataclass(frozen=True, slots=True)
class SystemSpacingProfile:
    """Source-line baselines with explicit physical chunk ownership."""

    source_lines: tuple[int, ...]
    chunk_counts: tuple[int, ...]
    line_gaps: tuple[float, ...]
    chunk_spacing: float
    incoming_clearance: float = 0.0
    outgoing_clearance: float = 0.0

    def __post_init__(self) -> None:
        if not self.source_lines:
            raise ValueError("system spacing requires at least one source line")
        if len(self.source_lines) != len(self.chunk_counts):
            raise ValueError("source_lines and chunk_counts must have equal lengths")
        if len(self.line_gaps) != len(self.source_lines) - 1:
            raise ValueError("line_gaps must describe every adjacent source-line pair")
        if any(count < 1 for count in self.chunk_counts):
            raise ValueError("every source line must own at least one physical chunk")
        if len(set(self.source_lines)) != len(self.source_lines):
            raise ValueError("source lines must be unique")
        spacings = (
            *self.line_gaps,
            self.chunk_spacing,
            self.incoming_clearance,
            self.outgoing_clearance,
        )
        if any(not isfinite(value) or value < 0 for value in spacings):
            raise ValueError("system spacings must be finite and non-negative")

    @property
    def physical_row_count(self) -> int:
        return sum(self.chunk_counts)

    @property
    def visual_row_offsets(self) -> tuple[int, ...]:
        offsets: list[int] = []
        next_offset = 0
        for chunk_count in self.chunk_counts:
            offsets.append(next_offset)
            next_offset += chunk_count
        return tuple(offsets)

    @property
    def source_line_y_offsets(self) -> tuple[float, ...]:
        offsets = [self.incoming_clearance]
        for index, line_gap in enumerate(self.line_gaps):
            offsets.append(
                offsets[-1]
                + (self.chunk_counts[index] - 1) * self.chunk_spacing
                + line_gap
            )
        return tuple(offsets)

    @property
    def total_height(self) -> float:
        return (
            self.source_line_y_offsets[-1]
            + (self.chunk_counts[-1] - 1) * self.chunk_spacing
            + self.outgoing_clearance
        )


@dataclass(frozen=True, slots=True)
class SystemAnchorProfile:
    """Row origins and first-onset grace reserves for one admitted shared grid."""

    left: float
    row_origins: tuple[float, ...]
    first_onset_grace_widths: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.row_origins) != len(self.first_onset_grace_widths):
            raise ValueError("row origins and grace widths must have equal lengths")
        if any(
            not isfinite(value)
            for value in (self.left, *self.row_origins, *self.first_onset_grace_widths)
        ):
            raise ValueError("system anchor values must be finite")
        if any(width < 0.0 for width in self.first_onset_grace_widths):
            raise ValueError("first-onset grace widths must be non-negative")

    @property
    def shared_first_onset_grace_width(self) -> float:
        """Return the unique grace reserve that exactly explains one shifted origin."""
        shifted_indices = tuple(
            index
            for index, origin in enumerate(self.row_origins)
            if origin != self.left
        )
        if len(shifted_indices) != 1:
            return 0.0
        owner = shifted_indices[0]
        width = self.first_onset_grace_widths[owner]
        if width <= 0.0 or self.row_origins[owner] != self.left + width:
            return 0.0
        return width


@dataclass(frozen=True, slots=True)
class SystemEntranceProfile:
    """Overlapping clearance demands applied at the start of a page."""

    incoming_construct_clearance: float
    terminal_mark_clearance: float

    def __post_init__(self) -> None:
        clearances = (self.incoming_construct_clearance, self.terminal_mark_clearance)
        if any(not isfinite(value) or value < 0 for value in clearances):
            raise ValueError("system entrance clearances must be finite and non-negative")

    @property
    def page_leading_clearance(self) -> float:
        return max(0.0, self.incoming_construct_clearance - self.terminal_mark_clearance)

    @property
    def first_system_clearance(self) -> float:
        return self.page_leading_clearance + self.terminal_mark_clearance


@dataclass(frozen=True, slots=True)
class SystemTransitionProfile:
    """Ordered vertical components between adjacent multi-voice systems."""

    base_tail_height: float
    incoming_construct_clearance: float
    dsb_transition_clearance: float
    hidden_rest_transition_clearance: float
    outgoing_dsb_clearance: float

    def __post_init__(self) -> None:
        components = (
            self.base_tail_height,
            self.incoming_construct_clearance,
            self.dsb_transition_clearance,
            self.hidden_rest_transition_clearance,
            self.outgoing_dsb_clearance,
        )
        if any(not isfinite(value) or value < 0 for value in components):
            raise ValueError("system transition components must be finite and non-negative")

    @property
    def total_height(self) -> float:
        return (
            self.base_tail_height
            + self.incoming_construct_clearance
            + self.dsb_transition_clearance
            + self.hidden_rest_transition_clearance
            + self.outgoing_dsb_clearance
        )


@dataclass(frozen=True, slots=True)
class PageFitProfile:
    """Page overflow decision and affine vertical projection."""

    bottom: float
    start: float
    lyric_tolerance: float
    non_lyric_positions: tuple[float, ...]
    lyric_positions: tuple[float, ...]

    @property
    def positions(self) -> tuple[float, ...]:
        return (*self.non_lyric_positions, *self.lyric_positions)

    @property
    def max_position(self) -> float:
        return max(self.positions, default=self.bottom)

    @property
    def max_non_lyric(self) -> float:
        return max(self.non_lyric_positions, default=self.bottom)

    @property
    def max_lyric(self) -> float:
        return max(self.lyric_positions, default=self.bottom)

    @property
    def scale(self) -> float | None:
        if not self.positions or self.max_position <= self.bottom:
            return None
        tolerated_bottom = self.bottom + self.lyric_tolerance
        if self.max_non_lyric <= tolerated_bottom and self.max_lyric <= tolerated_bottom:
            return None
        denominator = self.max_position - self.start
        if denominator <= 0:
            return None
        return (self.bottom - self.start) / denominator

    def project_y(self, value: float) -> float:
        scale = self.scale
        if scale is None:
            return value
        return self.start + (value - self.start) * scale


__all__ = [
    "MeasureGrid",
    "LegacyIntrinsicProfile",
    "PageFitProfile",
    "RowWidthAllocation",
    "SystemAnchorProfile",
    "SystemEntranceProfile",
    "SystemSpacingProfile",
    "SystemTransitionProfile",
    "SharedGraceReserve",
]
