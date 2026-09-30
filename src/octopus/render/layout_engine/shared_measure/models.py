"""Typed contracts shared by measure reconciliation stages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...core.layout_types import LayoutEvent


@dataclass(frozen=True, slots=True)
class MeasureSlice:
    """One voice's interval-width slice for a shared measure."""

    start: int
    end: int
    widths: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SharedMeasurePolicies:
    """Normalized per-row policy vectors used by shared-measure reconciliation."""

    punctuation_indices_by_row: tuple[frozenset[int], ...]
    terminal_punctuation_by_row: tuple[bool, ...]
    skip_indices_by_row: tuple[frozenset[int], ...]
    skip_connector_indices_by_row: tuple[frozenset[int], ...]


@dataclass(frozen=True, slots=True)
class MeasureReconciliationContext:
    """Immutable row and policy context for one shared-measure replacement."""

    target_row: Sequence[LayoutEvent]
    current_row: Sequence[LayoutEvent]
    target_start: int
    target_end: int
    current_start: int
    current_end: int
    target_voice_index: int
    current_voice_index: int
    bar_ordinal: int
    final_bar_ordinal: int
    deficit: float
    punctuation_voice: int | None
    terminal_punctuation_by_row: Sequence[bool]
    punctuation_indices_by_row: Sequence[frozenset[int]]
    skip_indices_by_row: Sequence[frozenset[int]]
    uses_shifted_voice_grid: bool
    uses_compact_four_voice_grid: bool
    uses_primary_spanning_hook_grid: bool
    uses_primary_parallel_voice_denominator: bool
    allows_partial_boundaries: bool
    allows_shorter_measure_projection: bool
    terminal_cap: float


__all__ = ["MeasureReconciliationContext", "MeasureSlice", "SharedMeasurePolicies"]
