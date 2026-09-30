"""Explicit reference fonts for source tests and bundled fonts for release workers."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import TypedDict

from octopus.assets import fonts as font_assets

_SVG_TAG = re.compile(r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')+>")
_ATTRIBUTE = re.compile(r"([\w:-]+)(\s*=\s*)([\"'])(.*?)(\3)", re.DOTALL)
_FAMILY_STYLE = re.compile(r"(font-family\s*:\s*)([^;}]+)", re.IGNORECASE)
_TEXT_ELEMENT = re.compile(
    r"<text\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>(.*?)</text\s*>", re.DOTALL
)
_RELEASE_FAMILIES = {"Noto Sans SC", "Noto Serif SC", "Liberation Sans"}


def release_profile() -> bool:
    # Packaged releases cannot accidentally select proprietary host fonts.
    if getattr(sys, "frozen", False):
        return True
    profile = os.environ.get("OCTOPUS_FONT_PROFILE", "reference")
    if profile not in {"reference", "release"}:
        raise ValueError("OCTOPUS_FONT_PROFILE must be reference or release")
    return profile == "release"


def release_family(family: str) -> str:
    first = html.unescape(family).split(",", 1)[0].strip().strip("\"'")
    canonical = {name.casefold(): name for name in _RELEASE_FAMILIES}
    if first.casefold() in canonical:
        return canonical[first.casefold()]
    if first.casefold() in {"simsun", "nsimsun", "kaiti", "serif"}:
        return "Noto Serif SC"
    if first.casefold() in {"arial", "liberation sans"}:
        return "Liberation Sans"
    return "Noto Sans SC"


def apply_svg_fonts(svg: str) -> str:
    """Change text font requests only; preserve reference output and document settings."""
    if not release_profile():
        return svg
    bundled_fonts()  # Fail explicitly when release assets are missing/corrupt.

    def rewrite_attribute(match: re.Match[str]) -> str:
        name, equal, quote, value, closing = match.groups()
        if name == "font-family":
            value = release_family(value)
        elif name == "style":
            value = _FAMILY_STYLE.sub(lambda item: item[1] + release_family(item[2]), value)
        return name + equal + quote + value + closing

    mapped = _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(rewrite_attribute, tag[0]), svg)
    coverage = font_coverage()

    def contains(family: str, text: str) -> bool:
        return all(char.isspace() or ord(char) in coverage[family] for char in text)

    def fallback_text(match: re.Match[str]) -> str:
        text = html.unescape(_SVG_TAG.sub("", match[1]))
        element = match[0]
        for family in _RELEASE_FAMILIES:
            if family in element and not contains(family, text):
                replacement = next((candidate for candidate in ("Noto Sans SC", "Noto Serif SC")
                                    if contains(candidate, text)), "Noto Sans SC")
                # Restrict replacement to font attributes/styles, never visible text/metadata.
                def replace_request(
                    attribute: re.Match[str], family: str = family, replacement: str = replacement,
                ) -> str:
                    name, equal, quote, value, closing = attribute.groups()
                    if name == "font-family" and value == family:
                        value = replacement
                    elif name == "style":
                        value = _FAMILY_STYLE.sub(
                            lambda item: item[1] + (replacement if item[2] == family else item[2]),
                            value,
                        )
                    return name + equal + quote + value + closing
                element = _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(replace_request, tag[0]), element)
        return element

    return _TEXT_ELEMENT.sub(fallback_text, mapped)


@lru_cache(maxsize=1)
def bundled_fonts() -> tuple[tuple[str, str, str, Path], ...]:
    root = Path(str(files(font_assets)))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    result: list[tuple[str, str, str, Path]] = []
    for face in manifest["faces"]:
        path = root / face["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != face["sha256"]:
            raise ValueError(f"bundled font checksum mismatch: {path.name}")
        result.append((face["family"], face["weight"], face["style"], path))
    return tuple(result)


@lru_cache(maxsize=1)
def font_coverage() -> dict[str, frozenset[int]]:
    root = bundled_fonts()[0][3].parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return {family: frozenset(code for start, end in ranges for code in range(start, end + 1))
            for family, ranges in manifest["coverage"].items()}


class RasterFontOptions(TypedDict, total=False):
    skip_system_fonts: bool
    font_files: list[str]
    font_family: str
    sans_serif_family: str
    serif_family: str


def raster_font_options() -> RasterFontOptions:
    if not release_profile():
        return {}
    return {
        "skip_system_fonts": True,
        "font_files": [str(face[3]) for face in bundled_fonts()],
        "font_family": "Noto Sans SC",
        "sans_serif_family": "Noto Sans SC",
        "serif_family": "Noto Serif SC",
    }


def register_pdf_fonts() -> None:
    if not release_profile():
        return
    from svglib.fonts import get_global_font_map  # type: ignore[import-untyped]

    font_map = get_global_font_map()
    for family, weight, style, path in bundled_fonts():
        _, success = font_map.register_font(family, str(path), weight=weight, style=style)
        if not success:
            raise ValueError(f"could not register bundled PDF font: {path.name}")
