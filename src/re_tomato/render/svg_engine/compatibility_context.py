"""Explicit page identity context for the remaining reference compatibility data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.layout_types import LayoutPage


CompatibilityPageKey = tuple[str, int]


@dataclass(frozen=True, slots=True)
class CompatibilityContext:
    """Explicit identity boundary for retained reference compatibility data."""

    profile_key: str
    page_index: int

    @property
    def page_key(self) -> CompatibilityPageKey:
        return self.profile_key, self.page_index

    def for_page(self, page_index: int) -> CompatibilityContext:
        return CompatibilityContext(self.profile_key, page_index)


def compatibility_context_for_layout(
    layout: LayoutPage,
    page_index: int | None = None,
) -> CompatibilityContext:
    """Create compatibility identity at the renderer/compatibility boundary."""

    if page_index is None:
        page_index = layout_page_index(layout)
    return CompatibilityContext(layout.compatibility_key or "", page_index)


def compatibility_page_key(
    layout: LayoutPage,
    page_index: int | None = None,
) -> CompatibilityPageKey:
    """Return the diagnostic page key used by isolated compatibility tables."""

    return compatibility_context_for_layout(layout, page_index).page_key


def layout_page_index(layout: LayoutPage) -> int:
    """Return the stable page index from visible or hidden layout events."""

    if layout.events:
        return layout.events[0].page_index
    if layout.hidden_events:
        return layout.hidden_events[0].page_index
    return 0


__all__ = [
    "CompatibilityContext",
    "CompatibilityPageKey",
    "compatibility_context_for_layout",
    "compatibility_page_key",
    "layout_page_index",
]
