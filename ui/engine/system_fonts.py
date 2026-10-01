"""Inspect installed SFNT collections without modifying or redistributing them."""

from __future__ import annotations

from functools import cache
from pathlib import Path


def mac_font_roots() -> tuple[Path, ...]:
    return (Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
            Path("/Library/Fonts"), Path.home() / "Library/Fonts")


@cache
def font_face(
    path: Path, family: str, weight: int = 400, italic: bool = False,
) -> tuple[int, bool, frozenset[int]] | None:
    """Return regular-nearest face index, CFF flag and cmap for an exact family."""
    from fontTools.ttLib import TTCollection, TTFont, TTLibError  # type: ignore[import-untyped]

    with path.open("rb") as stream:
        collection = stream.read(4) == b"ttcf"
    try:
        container = (TTCollection(str(path), lazy=True) if collection
                     else TTFont(str(path), lazy=True))
    except TTLibError:
        return None
    fonts = container.fonts if collection else [container]
    candidates: list[tuple[int, int, bool, frozenset[int]]] = []
    try:
        for index, font in enumerate(fonts):
            names = {name.toUnicode().casefold() for name in font["name"].names
                     if name.nameID in {1, 16}}
            if family.casefold() not in names:
                continue
            actual_weight = font["OS/2"].usWeightClass if "OS/2" in font else 400
            actual_italic = bool(font["OS/2"].fsSelection & 1) if "OS/2" in font else False
            rank = abs(actual_weight - weight) + (1000 if actual_italic != italic else 0)
            candidates.append((rank, index, "CFF " in font or "CFF2" in font,
                               frozenset(font.getBestCmap() or {})))
        if not candidates:
            return None
        _, index, cff, coverage = min(candidates, key=lambda item: (item[0], item[1]))
        return index, cff, coverage
    finally:
        container.close()
