"""Typed intermediate values shared by SVG rendering stages."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.layout_types import LayoutGrace


@dataclass(frozen=True, slots=True)
class GraceRenderItem:
    grace: LayoutGrace
    glyph_id: str
    child_count: int
    uses_catalog_glyph: bool = False


@dataclass(frozen=True, slots=True)
class GraceRenderPlan:
    items: tuple[GraceRenderItem, ...]
    defs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GraceGlyphNote:
    pitch: int
    octave: int
    duration_slashes: int


__all__ = ["GraceGlyphNote", "GraceRenderItem", "GraceRenderPlan"]
