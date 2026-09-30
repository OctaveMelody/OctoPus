"""Pure coordinate projection from allocated interval widths."""

from __future__ import annotations

from collections.abc import Sequence
from math import fsum
from typing import Literal

PrefixSumMode = Literal["compensated", "legacy"]


def project_interval_prefix(
    interval_widths: Sequence[float],
    *,
    origin: float,
    scale: float,
    start: int,
    end: int,
    summation: PrefixSumMode,
) -> float:
    """Project one width prefix while preserving the requested summation semantics."""

    if not 0 <= start <= end <= len(interval_widths):
        raise ValueError("projection prefix must be an ordered in-bounds slice")
    widths = interval_widths[start:end]
    prefix = fsum(widths) if summation == "compensated" else sum(widths)
    return origin + prefix * scale


__all__ = ["PrefixSumMode", "project_interval_prefix"]
