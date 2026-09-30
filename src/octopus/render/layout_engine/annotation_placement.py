"""Annotation (quoted lyric text) placement rules.

Reference behavior, verified across the corpus:

- Text: the quoted JPS payload with the quotes removed, half-width (``0x20``)
  spaces removed, and full-width spaces (``U+3000``) preserved.
- X: the annotation is right-aligned to the centre of the syllable that shares
  its anchor event. Full-width characters count as the lyric size, every other
  character as half of it. When the anchor event carries no syllable of the
  current verse the reference falls back to a quarter-size offset.
"""

from __future__ import annotations

import unicodedata

from ..core.layout_types import LayoutEvent, LayoutLyric, LayoutPage


def annotation_text(raw: str) -> str:
    """Unquote an annotation payload and drop half-width spaces only."""
    return raw.strip('"').replace(" ", "")


def syllable_width(text: str, lyric_size: int) -> float:
    """Reference text width: full-width chars = lyric size, others half."""
    width = 0.0
    for character in text:
        if unicodedata.east_asian_width(character) in {"W", "F"}:
            width += lyric_size
        else:
            width += lyric_size / 2
    return width


def fixup_annotation_x(
    layout: LayoutPage,
    events: list[LayoutEvent],
    verse: int,
    annotations: list[LayoutLyric],
) -> None:
    """Resolve each annotation's right edge from its anchor event."""
    if not annotations:
        return
    lyric_size = layout.metrics.lyric_size
    syllable_by_cipos = {
        item.cipos: item
        for item in layout.lyrics
        if item.cipos is not None and not item.annotation and item.verse == verse
    }
    anchor_by_cipos = {event.address.notepos: event for event in events}
    for annotation in annotations:
        anchor = anchor_by_cipos.get(annotation.anchor_cipos or "")
        if anchor is None:
            continue
        syllable = syllable_by_cipos.get(annotation.anchor_cipos or "")
        if syllable is not None and syllable.text:
            offset = syllable_width(syllable.text, lyric_size) / 2
        else:
            offset = lyric_size / 4
        annotation.x = anchor.x - offset


__all__ = ["annotation_text", "fixup_annotation_x", "syllable_width"]
