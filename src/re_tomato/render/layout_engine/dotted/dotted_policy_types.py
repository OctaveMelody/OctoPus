"""Typed value objects shared by dotted reserve classifiers and mutations."""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite

from ...core.layout_types import GEOMETRY_EPSILON
from ..keys import SourceEventKey


@dataclass(frozen=True, slots=True)
class SourceIntervalRetention:
    """One stable event owner and its measured dotted reserve retention."""

    event_key: SourceEventKey
    expected_width: float
    retained_width: float

    def __post_init__(self) -> None:
        if not isfinite(self.expected_width) or not isfinite(self.retained_width):
            raise ValueError("dotted interval widths must be finite")
        if self.expected_width < 0 or self.retained_width < 0:
            raise ValueError("dotted interval widths must be non-negative")
        if self.retained_width > self.expected_width:
            raise ValueError("dotted retention must not exceed expected width")


@dataclass(frozen=True, slots=True)
class DottedSecondEndingRelease:
    """Two source-owned interval releases in the simple-meter second ending."""

    retentions: tuple[SourceIntervalRetention, ...]
    source_domain_change: float = -7.2

    def __post_init__(self) -> None:
        if len(self.retentions) != 2:
            raise ValueError("dotted second-ending release requires two retentions")
        keys = tuple(retention.event_key for retention in self.retentions)
        if len(set(keys)) != len(keys):
            raise ValueError("dotted second-ending retention keys must be unique")
        if not isfinite(self.source_domain_change):
            raise ValueError("source-domain denominator change must be finite")
        if abs(self.source_domain_change - (-7.2)) > GEOMETRY_EPSILON:
            raise ValueError("dotted second-ending source-domain change must be -7.2")

    @property
    def denominator_change(self) -> float:
        return fsum(
            retention.retained_width - retention.expected_width
            for retention in self.retentions
        )


@dataclass(frozen=True, slots=True)
class SourceIntervalAdjustment:
    """One stable event owner and its measured shared-grid adjustment."""

    event_key: SourceEventKey
    expected_width: float
    adjusted_width: float

    def __post_init__(self) -> None:
        if not isfinite(self.expected_width) or not isfinite(self.adjusted_width):
            raise ValueError("shared dotted interval widths must be finite")
        if self.expected_width < 0 or self.adjusted_width < 0:
            raise ValueError("shared dotted interval widths must be non-negative")

    @property
    def delta(self) -> float:
        return self.adjusted_width - self.expected_width


@dataclass(frozen=True, slots=True)
class SharedDottedSystemReserve:
    """Measured source-owned adjustments for one DSB shared-grid family."""

    retentions: tuple[SourceIntervalAdjustment, ...]
    additions: tuple[SourceIntervalAdjustment, ...]
    denominator_event_key: SourceEventKey
    expected_denominator: float
    final_denominator: float

    def __post_init__(self) -> None:
        if len(self.retentions) != 3 or len(self.additions) != 2:
            raise ValueError("shared dotted system reserve has an invalid owner count")
        all_keys = tuple(item.event_key for item in (*self.retentions, *self.additions))
        if len(set(all_keys)) != len(all_keys):
            raise ValueError("shared dotted system reserve keys must be unique")
        if not isfinite(self.expected_denominator) or not isfinite(self.final_denominator):
            raise ValueError("shared dotted system denominators must be finite")

    @property
    def denominator_change(self) -> float:
        return self.final_denominator - self.expected_denominator


__all__ = [
    "DottedSecondEndingRelease",
    "SharedDottedSystemReserve",
    "SourceIntervalAdjustment",
    "SourceIntervalRetention",
]
