"""Stable source identities used by layout policy.

This module owns the identity contract shared by layout classifiers and the
legacy compatibility facade.  Keeping key resolution separate from the
source-shape predicates prevents floating-point cursor corrections from
depending on classifier ordering.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..core.layout_types import LayoutEvent


@dataclass(frozen=True, slots=True)
class SourceEventKey:
    """Stable source identity for one normalized row event."""

    source_line: int
    event_index: int
    canonical_code: str

    def __post_init__(self) -> None:
        if self.source_line < 0 or self.event_index < 0:
            raise ValueError("source event coordinates must be non-negative")
        if not self.canonical_code:
            raise ValueError("source event key requires canonical_code")


def source_event_key(item: LayoutEvent) -> SourceEventKey:
    """Build a stable key for an event within the current row."""

    return SourceEventKey(
        source_line=item.event.span.start.line,
        event_index=item.event.index,
        canonical_code=item.event.code,
    )


def resolve_source_event_key_indices(
    row: Sequence[LayoutEvent],
    keys: Sequence[SourceEventKey],
) -> tuple[int, ...]:
    """Resolve stable source keys to unique current row positions."""

    positions: dict[SourceEventKey, int] = {}
    for position, item in enumerate(row):
        key = source_event_key(item)
        if key in positions:
            raise ValueError(f"duplicate source event key in row: {key}")
        positions[key] = position
    try:
        resolved = tuple(positions[key] for key in keys)
    except KeyError as exc:
        raise ValueError(f"source event key is absent from row: {exc.args[0]}") from exc
    if len(set(resolved)) != len(resolved):
        raise ValueError("source event correction keys must resolve uniquely")
    return resolved


__all__ = [
    "SourceEventKey",
    "resolve_source_event_key_indices",
    "source_event_key",
]
