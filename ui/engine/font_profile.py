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

from .system_fonts import font_face, mac_font_roots

_SVG_TAG = re.compile(r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')+>")
_ATTRIBUTE = re.compile(r"([\w:-]+)(\s*=\s*)([\"'])(.*?)(\3)", re.DOTALL)
_FAMILY_STYLE = re.compile(r"(font-family\s*:\s*)([^;}]+)", re.IGNORECASE)
_TEXT_ELEMENT = re.compile(
    r"<text\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>(.*?)</text\s*>", re.DOTALL
)
_RELEASE_FAMILIES = {
    "Noto Sans SC", "Noto Serif SC", "Liberation Sans", "LXGW WenKai",
    "SimZhiSong", "LXGW Neo XiHei", "MiSans", "Zhuque Fangsong (technical preview)",
}
_FONT_ROLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "heiti-1": ("Microsoft YaHei", "MiSans", ("msyh.ttc", "msyh.ttf")),
    "heiti-2": ("SimHei", "LXGW Neo XiHei", ("simhei.ttf",)),
    "fangsong": ("FangSong", "Zhuque Fangsong (technical preview)",
                 ("simfang.ttf", "fangsong.ttf")),
    "songti": ("SimSun", "SimZhiSong", ("simsun.ttc", "simsun.ttf")),
    "kaiti": ("KaiTi", "LXGW WenKai", ("simkai.ttf", "kaiti.ttf")),
}

_MAC_ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "heiti-1": ("PingFang SC", ("PingFang.ttc",)),
    "heiti-2": ("Heiti SC", ("STHeiti Medium.ttc", "STHeiti Light.ttc")),
    "songti": ("Songti SC", ("Songti.ttc",)),
    "kaiti": ("Kaiti SC", ("Kaiti.ttc", "STKaiti.ttf")),
    "fangsong": ("STFangsong", ("STFangsong.ttf",)),
}


def preferred_system_family(role: str) -> str:
    return _MAC_ROLES[role][0] if sys.platform == "darwin" else _FONT_ROLES[role][0]


def selected_system_fonts() -> list[tuple[str, Path]]:
    result = []
    for role in _FONT_ROLES:
        family = preferred_system_family(role)
        path = system_font_path(family)
        if path is not None:
            result.append((family, path))
    return result


@cache
def system_font_path(family: str) -> Path | None:
    """Locate an installed matching family, never accept fontconfig's substitute."""
    if sys.platform == "darwin":
        entry = next((entry for entry in _MAC_ROLES.values() if entry[0] == family), None)
        if entry is None:
            return None
        for root in mac_font_roots():
            candidates = [root / name for name in entry[1]]
            candidates.extend(path for path in root.glob("*")
                              if path.suffix.lower() in {".ttf", ".ttc", ".otf"}
                              and path not in candidates)
            for path in candidates:
                if path.is_file():
                    try:
                        if font_face(path, family) is not None:
                            return path
                    except (OSError, ValueError):
                        continue
        return None
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
    else:
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


def role_family(role: str, sources: dict[str, str] | None = None) -> str:
    _, fallback, _ = _FONT_ROLES[role]
    system = preferred_system_family(role)
    if (sources or {}).get(role) != "fallback" and system_font_path(system) is not None:
        return system
    return fallback


def system_font_availability() -> dict[str, dict[str, str | bool]]:
    """Report exact host families, independently for every selectable role."""
    return {role: {"family": preferred_system_family(role), "fallback": entry[1],
                   "available": system_font_path(preferred_system_family(role)) is not None}
            for role, entry in _FONT_ROLES.items()}


def release_profile() -> bool:
    # Frozen workers always use application policy, including installed OS font preference.
    if getattr(sys, "frozen", False):
        return True
    profile = os.environ.get("OCTOPUS_FONT_PROFILE", "reference")
    if profile not in {"reference", "release"}:
        raise ValueError("OCTOPUS_FONT_PROFILE must be reference or release")
    return profile == "release"


def release_family(family: str, sources: dict[str, str] | None = None) -> str:
    first = html.unescape(family).split(",", 1)[0].strip().strip("\"'")
    role = {"HeiTi": "heiti-2", "heiti": "heiti-2", "黑体": "heiti-2",
            "黑体-1": "heiti-1", "黑体-2": "heiti-2", "宋体": "songti",
            "楷体": "kaiti", "仿宋": "fangsong", "Microsoft YaHei": "heiti-1",
            "microsoft yahei": "heiti-1", "微软雅黑": "heiti-1", "SimHei": "heiti-2"}.get(
        first, first.casefold(),
    )
    if role in _FONT_ROLES:
        return role_family(role, sources)
    canonical = {name.casefold(): name for name in _RELEASE_FAMILIES}
    if first.casefold() in canonical:
        return canonical[first.casefold()]
    if first.casefold() in {"simsun", "nsimsun", "serif"}:
        return role_family("songti", sources)
    if first.casefold() in {"arial", "liberation sans"}:
        return "Liberation Sans"
    return role_family("heiti-2", sources)


def apply_svg_fonts(svg: str, sources: dict[str, str] | None = None) -> str:
    """Change text font requests only; preserve reference output and document settings."""
    if sources is not None and (not isinstance(sources, dict)
                               or any(role not in _FONT_ROLES
                                      or choice not in ("system", "fallback")
                                      for role, choice in sources.items())):
        raise ValueError("invalid font source preferences")
    release = release_profile() or sources is not None
    if not release and not re.search(
        r"(?:HeiTi(?:-[12])?|SongTi|KaiTi|FangSong)", svg, re.IGNORECASE,
    ):
        return svg
    bundled_fonts()  # Fail explicitly when release assets are missing/corrupt.

    def rewrite_attribute(match: re.Match[str]) -> str:
        name, equal, quote, value, closing = match.groups()
        def resolve(request: str) -> str:
            first = request.split(",", 1)[0].strip().strip("\"'").casefold()
            if release or first in {*_FONT_ROLES, "heiti"}:
                family = release_family(request, sources)
                # Parentheses are CSS tokens unless the family is quoted.
                return f"&quot;{family}&quot;" if "(" in family else family
            return request
        if name == "font-family":
            value = resolve(value)
        elif name == "style":
            value = _FAMILY_STYLE.sub(lambda item: item[1] + resolve(item[2]), value)
        return name + equal + quote + value + closing

    mapped = _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(rewrite_attribute, tag[0]), svg)
    coverage = font_coverage(include_system=sources is not None)

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
                    if name == "font-family" and html.unescape(value).strip("\"' ") == family:
                        value = replacement
                    elif name == "style":
                        value = _FAMILY_STYLE.sub(
                            lambda item: item[1] + (
                                replacement
                                if html.unescape(item[2]).strip("\"' ") == family
                                else item[2]
                            ),
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
def font_coverage(include_system: bool = False) -> dict[str, frozenset[int]]:
    root = bundled_fonts()[0][3].parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    coverage = {family: frozenset(code for start, end in ranges for code in range(start, end + 1))
                for family, ranges in manifest["coverage"].items()}
    if release_profile() or include_system:
        for family, path in selected_system_fonts():
            if path.is_file():
                face = font_face(path, family)
                if face is not None:
                    coverage[family] = face[2]
    return coverage


class RasterFontOptions(TypedDict, total=False):
    skip_system_fonts: bool
    font_files: list[str]
    font_family: str
    sans_serif_family: str
    serif_family: str


def raster_font_options() -> RasterFontOptions:
    paths = [str(face[3]) for face in bundled_fonts()]
    paths.extend(str(path) for _, path in selected_system_fonts())
    if not release_profile():
        return {"skip_system_fonts": False, "font_files": paths}
    return {
        "skip_system_fonts": True,
        "font_files": paths,
        "font_family": role_family("heiti-2"),
        "sans_serif_family": role_family("heiti-2"),
        "serif_family": role_family("songti"),
    }


def register_pdf_fonts() -> None:
    from svglib.fonts import get_global_font_map  # type: ignore[import-untyped]

    font_map = get_global_font_map()
    faces = list(bundled_fonts())
    single_faces = {
        "LXGW WenKai", "SimZhiSong", "LXGW Neo XiHei", "MiSans",
        "Zhuque Fangsong (technical preview)",
        "SimHei", "SimSun", "KaiTi", "Microsoft YaHei", "FangSong",
    }
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

    import tempfile

    from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

    # svglib's public registration API accepts files but not a TTC face index.
    # Extract the chosen face temporarily, retaining its outlines and metadata.
    with tempfile.TemporaryDirectory(prefix="octopus-pdf-font-") as work:
        extracted: dict[tuple[Path, int], Path] = {}
        for family, path in selected_system_fonts():
            for weight in ("normal", "bold"):
                style_path = path
                if family == "Microsoft YaHei" and weight == "bold":
                    for filename in ("msyhbd.ttc", "msyhbd.ttf"):
                        candidate = path.with_name(filename)
                        if candidate.is_file():
                            style_path = candidate
                            break
                for style in ("normal", "italic"):
                    face = font_face(style_path, family, 700 if weight == "bold" else 400,
                                     style == "italic")
                    if face is None or face[1]:
                        continue  # Native exports support CFF; Python PDF uses explicit fallback.
                    key = (style_path, face[0])
                    if key not in extracted:
                        with style_path.open("rb") as stream:
                            collection = stream.read(4) == b"ttcf"
                        if collection:
                            target = Path(work) / f"face-{len(extracted)}.ttf"
                            with TTFont(
                                style_path, fontNumber=face[0], recalcTimestamp=False,
                            ) as font:
                                font.save(target)
                            extracted[key] = target
                        else:
                            extracted[key] = style_path
                    _, success = font_map.register_font(
                        family, str(extracted[key]), weight=weight, style=style,
                    )
                    if not success:
                        raise ValueError(f"could not register selected PDF font: {family}")


def apply_pdf_font_fallbacks(svg: str) -> str:
    """ReportLab cannot embed CFF; native macOS PDF exports retain the selected face."""
    fallback = {}
    for role in _FONT_ROLES:
        family = preferred_system_family(role)
        path = system_font_path(family)
        face = font_face(path, family) if path is not None else None
        if face is not None and face[1]:
            fallback[family] = _FONT_ROLES[role][1]

    def rewrite(match: re.Match[str]) -> str:
        name, equal, quote, value, closing = match.groups()
        if name == "font-family":
            value = fallback.get(value, value)
        elif name == "style":
            value = _FAMILY_STYLE.sub(lambda item: item[1] + fallback.get(item[2], item[2]), value)
        return name + equal + quote + value + closing

    return _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(rewrite, tag[0]), svg)
