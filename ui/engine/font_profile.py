"""Explicit reference fonts for source tests and bundled fonts for release workers."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
from functools import cache, lru_cache
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
_RELEASE_FAMILIES = {
    "Noto Sans SC", "Noto Serif SC", "Liberation Sans", "LXGW WenKai",
    "SimZhiSong", "LXGW Neo XiHei",
}
_FONT_ROLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "heiti": ("SimHei", "LXGW Neo XiHei", ("simhei.ttf",)),
    "songti": ("SimSun", "SimZhiSong", ("simsun.ttc", "simsun.ttf")),
    "kaiti": ("KaiTi", "LXGW WenKai", ("simkai.ttf", "kaiti.ttf")),
}


@cache
def system_font_path(family: str) -> Path | None:
    """Locate an installed matching family, never accept fontconfig's substitute."""
    role = next((entry for entry in _FONT_ROLES.values() if entry[0] == family), None)
    if role is None:
        return None
    if sys.platform == "win32":
        roots = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            roots.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
        for root in roots:
            for filename in role[2]:
                path = root / filename
                if path.is_file():
                    return path
    elif not release_profile():
        try:
            result = subprocess.check_output(
                ["fc-match", "-f", "%{family}|%{file}", family], text=True,
            )
            names, filename = result.split("|", 1)
            if family.casefold() in {name.casefold() for name in names.split(",")}:
                path = Path(filename)
                if path.is_file():
                    return path
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
    return None


def role_family(role: str) -> str:
    system, fallback, _ = _FONT_ROLES[role]
    return system if system_font_path(system) is not None else fallback


def release_profile() -> bool:
    # Frozen workers always use the application policy, including Windows system preference.
    if getattr(sys, "frozen", False):
        return True
    profile = os.environ.get("OCTOPUS_FONT_PROFILE", "reference")
    if profile not in {"reference", "release"}:
        raise ValueError("OCTOPUS_FONT_PROFILE must be reference or release")
    return profile == "release"


def release_family(family: str) -> str:
    first = html.unescape(family).split(",", 1)[0].strip().strip("\"'")
    role = {"黑体": "heiti", "宋体": "songti", "楷体": "kaiti"}.get(
        first, first.casefold(),
    )
    if role in _FONT_ROLES:
        return role_family(role)
    canonical = {name.casefold(): name for name in _RELEASE_FAMILIES}
    if first.casefold() in canonical:
        return canonical[first.casefold()]
    if first.casefold() in {"simsun", "nsimsun", "serif"}:
        return role_family("songti")
    if first.casefold() in {"arial", "liberation sans"}:
        return "Liberation Sans"
    return role_family("heiti")


def apply_svg_fonts(svg: str) -> str:
    """Change text font requests only; preserve reference output and document settings."""
    release = release_profile()
    if not release and not re.search(r"(?:HeiTi|SongTi|KaiTi)", svg, re.IGNORECASE):
        return svg
    bundled_fonts()  # Fail explicitly when release assets are missing/corrupt.

    def rewrite_attribute(match: re.Match[str]) -> str:
        name, equal, quote, value, closing = match.groups()
        def resolve(request: str) -> str:
            first = request.split(",", 1)[0].strip().strip("\"'").casefold()
            return release_family(request) if release or first in _FONT_ROLES else request
        if name == "font-family":
            value = resolve(value)
        elif name == "style":
            value = _FAMILY_STYLE.sub(lambda item: item[1] + resolve(item[2]), value)
        return name + equal + quote + value + closing

    mapped = _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(rewrite_attribute, tag[0]), svg)
    coverage = font_coverage()

    def contains(family: str, text: str) -> bool:
        return all(char.isspace() or ord(char) in coverage[family] for char in text)

    def fallback_text(match: re.Match[str]) -> str:
        text = html.unescape(_SVG_TAG.sub("", match[1]))
        element = match[0]
        for family in coverage:
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
    coverage = {family: frozenset(code for start, end in ranges for code in range(start, end + 1))
                for family, ranges in manifest["coverage"].items()}
    if release_profile():
        for family, _, _ in _FONT_ROLES.values():
            path = system_font_path(family)
            if path is not None and path.is_file():
                # Installed Windows versions vary; inspect the selected file's actual cmap.
                from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]

                font = TTFont("octopus-system-coverage", str(path))
                coverage[family] = frozenset(font.face.charToGlyph)
    return coverage


class RasterFontOptions(TypedDict, total=False):
    skip_system_fonts: bool
    font_files: list[str]
    font_family: str
    sans_serif_family: str
    serif_family: str


def raster_font_options() -> RasterFontOptions:
    paths = [str(face[3]) for face in bundled_fonts()]
    paths.extend(str(path) for system, _, _ in _FONT_ROLES.values()
                 if (path := system_font_path(system)) is not None)
    if not release_profile():
        return {"skip_system_fonts": False, "font_files": paths}
    return {
        "skip_system_fonts": True,
        "font_files": paths,
        "font_family": role_family("heiti"),
        "sans_serif_family": role_family("heiti"),
        "serif_family": role_family("songti"),
    }


def register_pdf_fonts() -> None:
    from svglib.fonts import get_global_font_map  # type: ignore[import-untyped]

    font_map = get_global_font_map()
    faces = list(bundled_fonts())
    for family, _, _ in _FONT_ROLES.values():
        path = system_font_path(family)
        if path is not None:
            faces.append((family, "normal", "normal", path))
    single_faces = {"LXGW WenKai", "SimZhiSong", "LXGW Neo XiHei", "SimHei", "SimSun", "KaiTi"}
    for family, weight, style, path in faces:
        _, success = font_map.register_font(family, str(path), weight=weight, style=style)
        if not success:
            raise ValueError(f"could not register bundled PDF font: {path.name}")
        if family in single_faces:
            for other_weight in ("normal", "bold"):
                for other_style in ("normal", "italic"):
                    font_map.register_font(
                        family, str(path), weight=other_weight, style=other_style,
                    )
