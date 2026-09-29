"""Reserve-allocation operations for horizontal row layout."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import fsum

from ...core.layout_types import GEOMETRY_EPSILON
from ..profiles import RowWidthAllocation


@dataclass(frozen=True, slots=True)
class TerminalReserveTransfer:
    """Result of moving terminal excess into the final projected interval."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    transferred_width: float


@dataclass(frozen=True, slots=True)
class ContinuationReserveAllocation:
    """Reserve allocation at a continued ending boundary and terminal."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    boundary_clearance: float
    terminal_transfer: float

    @property
    def denominator_increase(self) -> float:
        return self.boundary_clearance - self.terminal_transfer


@dataclass(frozen=True, slots=True)
class IntervalReserveRelease:
    """Result of capping one interval at its non-style retained width."""

    interval_widths: tuple[float, ...]
    released_width: float


@dataclass(frozen=True, slots=True)
class IntervalReserveAddition:
    """Result of adding source-owned width to one projected interval."""

    interval_widths: tuple[float, ...]
    added_width_by_index: tuple[tuple[int, float], ...]

    @property
    def added_width(self) -> float:
        return fsum(width for _, width in self.added_width_by_index)

    @property
    def denominator_increase(self) -> float:
        return self.added_width


@dataclass(frozen=True, slots=True)
class IntervalTerminalReserveAllocation:
    """Result of adding interval reserves while releasing terminal ownership."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    added_width_by_index: tuple[tuple[int, float], ...]
    terminal_release: float

    @property
    def added_interval_width(self) -> float:
        return fsum(width for _, width in self.added_width_by_index)

    @property
    def denominator_increase(self) -> float:
        return self.added_interval_width - self.terminal_release


@dataclass(frozen=True, slots=True)
class IntervalToTerminalReserveTransfer:
    """Result of moving one interval reserve into the terminal."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    transferred_width: float


@dataclass(frozen=True, slots=True)
class TerminalToIntervalReserveTransfer:
    """Result of moving terminal ownership into one projected interval."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    transferred_width: float


@dataclass(frozen=True, slots=True)
class DottedOnsetReserveAllocation:
    """Result of releasing cross-duration onset reserves and adding terminal ownership."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    released_interval_width: float
    added_interval_width: float
    terminal_increase: float

    @property
    def denominator_change(self) -> float:
        return (
            self.added_interval_width
            + self.terminal_increase
            - self.released_interval_width
        )


@dataclass(frozen=True, slots=True)
class TerminalCadenceReserveAllocation:
    """Result of moving a terminal share into its final occupied interval."""

    interval_widths: tuple[float, ...]
    terminal_reserve: float
    interval_increase: float
    terminal_release: float

    @property
    def denominator_increase(self) -> float:
        return self.interval_increase - self.terminal_release


def transfer_terminal_reserve_excess(
    interval_widths: tuple[float, ...],
    *,
    raw_terminal_reserve: float,
    terminal_reserve: float,
) -> TerminalReserveTransfer:
    """Transfer ``raw - visible`` reserve without changing occupied row width."""

    excess = raw_terminal_reserve - terminal_reserve
    if excess <= GEOMETRY_EPSILON or not interval_widths:
        return TerminalReserveTransfer(interval_widths, terminal_reserve, 0.0)

    available_width = fsum((*interval_widths, terminal_reserve))
    before = RowWidthAllocation(
        interval_widths=interval_widths,
        terminal_reserve=terminal_reserve,
        fixed_gap_width=0.0,
        available_width=available_width,
    )
    before.require_conserved()

    adjusted_widths = (*interval_widths[:-1], interval_widths[-1] + excess)
    after = RowWidthAllocation(
        interval_widths=adjusted_widths,
        terminal_reserve=terminal_reserve - excess,
        fixed_gap_width=0.0,
        available_width=available_width,
    )
    after.require_conserved()
    return TerminalReserveTransfer(
        interval_widths=adjusted_widths,
        terminal_reserve=after.terminal_reserve,
        transferred_width=excess,
    )


def alternating_extension_hook_reserve(
    measure_count: int,
    *,
    reserve_width: float = 9.0,
) -> float:
    """Return the denominator reserve for a sustained alternating-extension row.

    A lyricless zkh row that alternates note-plus-three-dash measures keeps
    one hook reserve in the scale denominator; the reference does not
    compress the sustained measures themselves (oracle probes X1-X3b,
    2026-08-31; corpus instance Night-In-The-Desert p3 L96).
    """

    if measure_count < 0:
        raise ValueError("measure_count must be non-negative")
    if reserve_width < 0:
        raise ValueError("reserve_width must be non-negative")
    return reserve_width if measure_count > 0 else 0.0


def release_interval_reserve_excess(
    interval_widths: tuple[float, ...],
    *,
    interval_index: int,
    retained_width: float,
) -> IntervalReserveRelease:
    """Release an interval's excess above a structurally retained width."""

    if not 0 <= interval_index < len(interval_widths):
        raise ValueError("interval_index must identify an interval")
    if retained_width < 0:
        raise ValueError("retained_width must be non-negative")
    released_width = max(interval_widths[interval_index] - retained_width, 0.0)
    if released_width <= GEOMETRY_EPSILON:
        return IntervalReserveRelease(interval_widths, 0.0)
    adjusted = list(interval_widths)
    adjusted[interval_index] -= released_width
    before = fsum(interval_widths)
    after = fsum(adjusted)
    if abs((before - after) - released_width) > GEOMETRY_EPSILON:
        raise ValueError("interval reserve release is inconsistent")
    return IntervalReserveRelease(tuple(adjusted), released_width)


def add_interval_reserve(
    interval_widths: tuple[float, ...],
    *,
    interval_index: int,
    added_width: float,
) -> IntervalReserveAddition:
    """Add one structurally owned interval reserve and verify its denominator delta."""

    return add_interval_reserves(
        interval_widths,
        added_width_by_index={interval_index: added_width},
    )


def add_interval_reserves(
    interval_widths: tuple[float, ...],
    *,
    added_width_by_index: Mapping[int, float],
) -> IntervalReserveAddition:
    """Add structurally owned reserves and verify their total denominator delta."""

    adjusted = list(interval_widths)
    additions = tuple(sorted(added_width_by_index.items()))
    for interval_index, added_width in additions:
        if not 0 <= interval_index < len(interval_widths):
            raise ValueError("interval_index must identify an interval")
        if added_width < 0:
            raise ValueError("added_width must be non-negative")
        adjusted[interval_index] += added_width
    allocation = IntervalReserveAddition(tuple(adjusted), additions)
    if (
        abs(
            (fsum(adjusted) - fsum(interval_widths))
            - allocation.denominator_increase
        )
        > GEOMETRY_EPSILON
    ):
        raise ValueError("interval reserve addition is inconsistent")
    return allocation


def allocate_interval_reserves_with_terminal_release(
    interval_widths: tuple[float, ...],
    *,
    added_width_by_index: Mapping[int, float],
    terminal_reserve: float,
    terminal_release: float,
) -> IntervalTerminalReserveAllocation:
    """Add interval-owned widths, release terminal width, and verify the net delta."""

    if min(terminal_reserve, terminal_release) < 0:
        raise ValueError("terminal reserves must be non-negative")
    if terminal_release > terminal_reserve:
        raise ValueError("terminal release exceeds the terminal reserve")
    interval_addition = add_interval_reserves(
        interval_widths,
        added_width_by_index=added_width_by_index,
    )
    allocation = IntervalTerminalReserveAllocation(
        interval_widths=interval_addition.interval_widths,
        terminal_reserve=terminal_reserve - terminal_release,
        added_width_by_index=interval_addition.added_width_by_index,
        terminal_release=terminal_release,
    )
    before = fsum((*interval_widths, terminal_reserve))
    after = fsum((*allocation.interval_widths, allocation.terminal_reserve))
    if abs((after - before) - allocation.denominator_increase) > GEOMETRY_EPSILON:
        raise ValueError("interval/terminal reserve allocation is inconsistent")
    return allocation


def transfer_interval_reserve_to_terminal(
    interval_widths: tuple[float, ...],
    *,
    interval_index: int,
    terminal_reserve: float,
    transfer_width: float,
) -> IntervalToTerminalReserveTransfer:
    """Move an owned interval reserve to the terminal without changing width."""

    if not 0 <= interval_index < len(interval_widths):
        raise ValueError("interval_index must identify an interval")
    if min(terminal_reserve, transfer_width) < 0:
        raise ValueError("reserves must be non-negative")
    if transfer_width > interval_widths[interval_index]:
        raise ValueError("transfer exceeds the interval reserve")
    adjusted = list(interval_widths)
    adjusted[interval_index] -= transfer_width
    allocation = IntervalToTerminalReserveTransfer(
        interval_widths=tuple(adjusted),
        terminal_reserve=terminal_reserve + transfer_width,
        transferred_width=transfer_width,
    )
    before = fsum((*interval_widths, terminal_reserve))
    after = fsum((*allocation.interval_widths, allocation.terminal_reserve))
    if abs(after - before) > GEOMETRY_EPSILON:
        raise ValueError("interval-to-terminal transfer is not conserved")
    return allocation


def transfer_terminal_reserve_to_interval(
    interval_widths: tuple[float, ...],
    *,
    interval_index: int,
    terminal_reserve: float,
    transfer_width: float,
) -> TerminalToIntervalReserveTransfer:
    """Move terminal ownership into one interval without changing row width."""

    if not 0 <= interval_index < len(interval_widths):
        raise ValueError("interval_index must identify an interval")
    if min(terminal_reserve, transfer_width) < 0:
        raise ValueError("reserves must be non-negative")
    if transfer_width > terminal_reserve:
        raise ValueError("transfer exceeds the terminal reserve")
    adjusted = list(interval_widths)
    adjusted[interval_index] += transfer_width
    allocation = TerminalToIntervalReserveTransfer(
        interval_widths=tuple(adjusted),
        terminal_reserve=terminal_reserve - transfer_width,
        transferred_width=transfer_width,
    )
    before = fsum((*interval_widths, terminal_reserve))
    after = fsum((*allocation.interval_widths, allocation.terminal_reserve))
    if abs(after - before) > GEOMETRY_EPSILON:
        raise ValueError("terminal-to-interval transfer is not conserved")
    return allocation


def allocate_dotted_onset_reserves(
    interval_widths: tuple[float, ...],
    *,
    retained_width_by_index: Mapping[int, float],
    added_width_by_index: Mapping[int, float],
    terminal_reserve: float,
    terminal_increase: float,
) -> DottedOnsetReserveAllocation:
    """Apply an exact dotted-grid reserve allocation and verify its denominator delta."""

    if set(retained_width_by_index) & set(added_width_by_index):
        raise ValueError("retained and added interval ownership must be disjoint")
    if min(terminal_reserve, terminal_increase) < 0:
        raise ValueError("terminal reserves must be non-negative")
    adjusted = list(interval_widths)
    released_widths: list[float] = []
    for index, retained_width in retained_width_by_index.items():
        if not 0 <= index < len(adjusted):
            raise ValueError("retained index must identify an interval")
        if retained_width < 0 or retained_width > adjusted[index] + GEOMETRY_EPSILON:
            raise ValueError("retained width must not exceed its interval")
        released_widths.append(max(adjusted[index] - retained_width, 0.0))
        adjusted[index] = retained_width
    additions: list[float] = []
    for index, added_width in added_width_by_index.items():
        if not 0 <= index < len(adjusted):
            raise ValueError("added index must identify an interval")
        if added_width < 0:
            raise ValueError("added width must be non-negative")
        adjusted[index] += added_width
        additions.append(added_width)

    allocation = DottedOnsetReserveAllocation(
        interval_widths=tuple(adjusted),
        terminal_reserve=terminal_reserve + terminal_increase,
        released_interval_width=fsum(released_widths),
        added_interval_width=fsum(additions),
        terminal_increase=terminal_increase,
    )
    before = fsum((*interval_widths, terminal_reserve))
    after = fsum((*allocation.interval_widths, allocation.terminal_reserve))
    if abs((after - before) - allocation.denominator_change) > GEOMETRY_EPSILON:
        raise ValueError("dotted onset reserve allocation is inconsistent")
    return allocation


def allocate_terminal_cadence_reserve(
    interval_widths: tuple[float, ...],
    *,
    interval_index: int,
    terminal_reserve: float,
    interval_increase: float,
    terminal_release: float,
) -> TerminalCadenceReserveAllocation:
    """Move terminal cadence ownership and verify its denominator increase."""

    if not 0 <= interval_index < len(interval_widths):
        raise ValueError("interval_index must identify an interval")
    if min(terminal_reserve, interval_increase, terminal_release) < 0:
        raise ValueError("cadence reserves must be non-negative")
    if terminal_release > terminal_reserve:
        raise ValueError("terminal release exceeds the terminal reserve")
    adjusted = list(interval_widths)
    adjusted[interval_index] += interval_increase
    allocation = TerminalCadenceReserveAllocation(
        interval_widths=tuple(adjusted),
        terminal_reserve=terminal_reserve - terminal_release,
        interval_increase=interval_increase,
        terminal_release=terminal_release,
    )
    before = fsum((*interval_widths, terminal_reserve))
    after = fsum((*allocation.interval_widths, allocation.terminal_reserve))
    if abs((after - before) - allocation.denominator_increase) > GEOMETRY_EPSILON:
        raise ValueError("terminal cadence allocation is inconsistent")
    return allocation


def allocate_continuation_boundary_reserve(
    interval_widths: tuple[float, ...],
    *,
    boundary_index: int,
    terminal_reserve: float,
    boundary_clearance: float = 14.4,
    terminal_transfer: float = 9.0,
) -> ContinuationReserveAllocation:
    """Place continued-ending clearance and transfer its terminal-owned share."""

    if not 0 <= boundary_index < len(interval_widths):
        raise ValueError("boundary_index must identify an interval")
    if min(terminal_reserve, boundary_clearance, terminal_transfer) < 0:
        raise ValueError("reserves must be non-negative")
    if terminal_transfer > terminal_reserve or terminal_transfer > boundary_clearance:
        raise ValueError("terminal transfer exceeds an available reserve")

    adjusted = list(interval_widths)
    adjusted[boundary_index] += boundary_clearance
    allocation = ContinuationReserveAllocation(
        interval_widths=tuple(adjusted),
        terminal_reserve=terminal_reserve - terminal_transfer,
        boundary_clearance=boundary_clearance,
        terminal_transfer=terminal_transfer,
    )
    before = fsum((*interval_widths, terminal_reserve))
    after = fsum((*allocation.interval_widths, allocation.terminal_reserve))
    if abs((after - before) - allocation.denominator_increase) > GEOMETRY_EPSILON:
        raise ValueError("continuation reserve allocation is not conserved")
    return allocation


__all__ = [
    "ContinuationReserveAllocation",
    "DottedOnsetReserveAllocation",
    "IntervalReserveAddition",
    "IntervalReserveRelease",
    "IntervalTerminalReserveAllocation",
    "IntervalToTerminalReserveTransfer",
    "TerminalCadenceReserveAllocation",
    "TerminalReserveTransfer",
    "TerminalToIntervalReserveTransfer",
    "add_interval_reserve",
    "add_interval_reserves",
    "allocate_interval_reserves_with_terminal_release",
    "allocate_continuation_boundary_reserve",
    "allocate_dotted_onset_reserves",
    "allocate_terminal_cadence_reserve",
    "alternating_extension_hook_reserve",
    "release_interval_reserve_excess",
    "transfer_terminal_reserve_excess",
    "transfer_interval_reserve_to_terminal",
    "transfer_terminal_reserve_to_interval",
]
