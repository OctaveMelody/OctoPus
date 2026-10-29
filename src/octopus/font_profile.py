"""Resolve source/reference assets and platform fonts for bundle-free desktop releases."""

from __future__ import annotations

import hashlib
import html
import importlib
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

from .system_fonts import font_face, mac_font_assets, mac_font_roots

_SVG_TAG = re.compile(r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')+>")
_ATTRIBUTE = re.compile(r"([\w:-]+)(\s*=\s*)([\"'])(.*?)(\3)", re.DOTALL)
_FAMILY_STYLE = re.compile(r"(font-family\s*:\s*)([^;}]+)", re.IGNORECASE)
_TEXT_ELEMENT = re.compile(r"<text\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>(.*?)</text\s*>", re.DOTALL)
_RELEASE_FAMILIES = {
    "Noto Sans SC",
    "Noto Serif SC",
    "Liberation Sans",
    "LXGW WenKai",
    "SimZhiSong",
    "LXGW Neo XiHei",
    "MiSans",
    "Zhuque Fangsong (technical preview)",
}
_FONT_ROLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "heiti-1": ("Microsoft YaHei", "MiSans", ("msyh.ttc", "msyh.ttf")),
    "heiti-2": ("SimHei", "LXGW Neo XiHei", ("simhei.ttf",)),
    "fangsong": (
        "FangSong",
        "Zhuque Fangsong (technical preview)",
        ("simfang.ttf", "fangsong.ttf"),
    ),
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

_WINDOWS_FONT_FILES: dict[str, tuple[str, ...]] = {
    "Microsoft YaHei": ("msyh.ttc", "msyh.ttf"),
    "Microsoft YaHei UI": ("msyh.ttc", "msyh.ttf"),
    "SimHei": ("simhei.ttf",),
    "FangSong": ("simfang.ttf", "fangsong.ttf"),
    "SimSun": ("simsun.ttc", "simsun.ttf"),
    "KaiTi": ("simkai.ttf", "kaiti.ttf"),
    "DengXian": ("Deng.ttf", "Dengb.ttf"),
}

_MAC_FONT_FILES = {family: filenames for family, filenames in _MAC_ROLES.values()}

_WINDOWS_ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "heiti-1": ("Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei"),
    "heiti-2": ("SimHei", "Microsoft YaHei", "DengXian"),
    "songti": ("SimSun", "Microsoft YaHei", "SimHei"),
    "kaiti": ("KaiTi", "SimSun", "Microsoft YaHei"),
    "fangsong": ("FangSong", "SimSun", "Microsoft YaHei"),
}

_MAC_ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "heiti-1": ("PingFang SC", "Heiti SC", "Songti SC"),
    "heiti-2": ("Heiti SC", "PingFang SC", "Songti SC"),
    "songti": ("Songti SC", "PingFang SC", "Heiti SC"),
    "kaiti": ("Kaiti SC", "PingFang SC", "Songti SC"),
    "fangsong": ("STFangsong", "Songti SC", "PingFang SC"),
}

_GENERIC_FAMILIES = {
    "heiti-1": "sans-serif",
    "heiti-2": "sans-serif",
    "songti": "serif",
    "kaiti": "serif",
    "fangsong": "serif",
}
_FONT_ROLE_ALIASES = {
    "heiti": "heiti-2",
    "heiti-1": "heiti-1",
    "heiti-2": "heiti-2",
    "sans-serif": "heiti-2",
    "sans": "heiti-2",
    "黑体": "heiti-2",
    "黑体-1": "heiti-1",
    "黑体-2": "heiti-2",
    "microsoft yahei": "heiti-1",
    "microsoft yahei ui": "heiti-1",
    "微软雅黑": "heiti-1",
    "simhei": "heiti-2",
    "宋体": "songti",
    "songti": "songti",
    "simsun": "songti",
    "nsimsun": "songti",
    "serif": "songti",
    "fangsong": "fangsong",
    "楷体": "kaiti",
    "仿宋": "fangsong",
}
for _role, (_family, _fallback, _files) in _FONT_ROLES.items():
    _FONT_ROLE_ALIASES[_family.casefold()] = _role
for _role, (_family, _files) in _MAC_ROLES.items():
    _FONT_ROLE_ALIASES[_family.casefold()] = _role


def preferred_system_family(role: str) -> str:
    return _MAC_ROLES[role][0] if sys.platform == "darwin" else _FONT_ROLES[role][0]


def selected_system_fonts(*, require_truetype: bool = False) -> list[tuple[str, Path]]:
    if release_profile() and sys.platform == "linux":
        return []
    result: list[tuple[str, Path]] = []
    for role in _FONT_ROLES:
        resolved = _resolve_system_role(role, require_truetype=require_truetype)
        if resolved is not None and resolved not in result:
            result.append(resolved)
    return result


def _bundled_fonts_enabled() -> bool:
    """Reference source keeps assets; release profiles bundle them only on Linux."""
    return not release_profile() or sys.platform == "linux"


def _system_role_candidates(role: str) -> tuple[str, ...]:
    if sys.platform == "darwin":
        preferred = preferred_system_family(role)
        alternatives = (family for family in _MAC_ROLE_CANDIDATES[role] if family != preferred)
        return (preferred, *alternatives)
    if sys.platform == "win32":
        preferred = preferred_system_family(role)
        return (
            preferred,
            *(family for family in _WINDOWS_ROLE_CANDIDATES[role] if family != preferred),
        )
    return (preferred_system_family(role),)


def _resolve_system_role(
    role: str,
    *,
    require_truetype: bool = False,
) -> tuple[str, Path] | None:
    """Choose an installed preferred family, then a compatible OS family for the role."""
    for family in _system_role_candidates(role):
        path = system_font_path(family)
        if path is None:
            continue
        if require_truetype:
            try:
                face = font_face(path, family)
            except OSError:
                continue
            if face is None or face[1]:
                continue
        return family, path
    return None


@cache
def system_font_path(family: str) -> Path | None:
    """Locate an installed matching family, never accept fontconfig's substitute."""
    if sys.platform == "darwin":
        filenames = _MAC_FONT_FILES.get(family)
        if filenames is None:
            return None
        for root in mac_font_roots():
            candidates = [root / name for name in filenames]
            candidates.extend(
                path
                for path in root.glob("*")
                if path.suffix.lower() in {".ttf", ".ttc", ".otf"} and path not in candidates
            )
            for path in candidates:
                if path.is_file():
                    try:
                        if font_face(path, family) is not None:
                            return path
                    except (OSError, ValueError):
                        continue
        for path in mac_font_assets(filenames):
            if path.is_file():
                try:
                    if font_face(path, family) is not None:
                        return path
                except (OSError, ValueError):
                    continue
        return None
    role = next((entry for entry in _FONT_ROLES.values() if entry[0] == family), None)
    if sys.platform == "win32":
        filenames = _WINDOWS_FONT_FILES.get(family)
        if filenames is None:
            return None
        roots = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            roots.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
        for root in roots:
            for filename in filenames:
                path = root / filename
                if path.is_file():
                    try:
                        if font_face(path, family) is not None:
                            return path
                    except (OSError, ValueError):
                        continue
        # Windows can register per-user or supplemental fonts under arbitrary filenames.
        # The standard-name fast path above is cheap, but it must not decide that a family is
        # absent when the installed-font registry points to a differently named face.
        try:
            winreg = importlib.import_module("winreg")
        except ImportError:
            return None
        registry_key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, registry_key)
            except OSError:
                continue
            try:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if family.casefold() not in str(name).casefold():
                        continue
                    value = os.path.expandvars(str(value))
                    registered_path = Path(value)
                    candidates = (
                        (registered_path,)
                        if registered_path.is_absolute()
                        else tuple(root / registered_path for root in roots)
                    )
                    for path in candidates:
                        if not path.is_file():
                            continue
                        try:
                            if font_face(path, family) is not None:
                                return path
                        except (OSError, ValueError):
                            continue
            finally:
                winreg.CloseKey(key)
    else:
        if role is None:
            return None
        try:
            result = subprocess.check_output(
                ["fc-match", "-f", "%{family}|%{file}", family],
                text=True,
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
    force_bundle = (sources or {}).get(role) == "fallback"
    if release_profile() and sys.platform == "linux":
        force_bundle = True
    if not force_bundle:
        resolved = _resolve_system_role(role)
        if resolved is not None:
            return resolved[0]
    if _bundled_fonts_enabled():
        return fallback
    return _GENERIC_FAMILIES[role]


def system_font_availability() -> dict[str, dict[str, str | bool]]:
    """Report preferred and effective families, independently for every selectable role."""
    result: dict[str, dict[str, str | bool]] = {}
    linux_bundle = release_profile() and sys.platform == "linux"
    for role, entry in _FONT_ROLES.items():
        preferred = preferred_system_family(role)
        preferred_available = not linux_bundle and system_font_path(preferred) is not None
        resolved = (
            None if linux_bundle else _resolve_system_role(role)
        )
        if linux_bundle:
            bundled_fonts()  # Fail the handshake rather than reporting missing release assets.
            effective = entry[1]
            source = "bundled"
        elif resolved is not None:
            effective = resolved[0]
            source = "system" if preferred_available else "system-fallback"
        else:
            effective = entry[1] if _bundled_fonts_enabled() else _GENERIC_FAMILIES[role]
            source = "bundled" if _bundled_fonts_enabled() else "generic-fallback"
        result[role] = {
            "family": preferred,
            "fallback": effective,
            "resolved_family": effective,
            "available": preferred_available,
            "preferred_available": preferred_available,
            "resolved": resolved is not None or source == "bundled",
            "source": source,
        }
    return result


def font_roles_in_svg(svg: str) -> list[str]:
    """Return symbolic score-font roles requested by rendered text, if recognized."""
    roles: set[str] = set()
    for tag in _SVG_TAG.findall(svg):
        for attribute in _ATTRIBUTE.finditer(tag):
            name, _, _, value, _ = attribute.groups()
            requests = [value] if name.casefold() == "font-family" else []
            if name.casefold() == "style":
                requests.extend(match.group(2) for match in _FAMILY_STYLE.finditer(value))
            for request in requests:
                first = html.unescape(request).split(",", 1)[0].strip().strip("\"'").casefold()
                role = _FONT_ROLE_ALIASES.get(first)
                if role is not None:
                    roles.add(role)
    return sorted(roles)


def release_profile() -> bool:
    # Frozen workers always use application policy, including installed OS font preference.
    if getattr(sys, "frozen", False):
        return True
    profile = os.environ.get("OCTOPUS_FONT_PROFILE", "reference")
    if profile not in {"reference", "release"}:
        raise ValueError("OCTOPUS_FONT_PROFILE must be reference or release")
    return profile == "release"


def font_runtime_status() -> dict[str, str]:
    """Identify the active platform font policy for the desktop UI."""
    platform = {
        "win32": "windows",
        "darwin": "macos",
        "linux": "linux",
    }.get(sys.platform, "other")
    if not release_profile():
        policy = "reference"
    elif platform == "linux":
        policy = "bundled"
    else:
        policy = "system"
    return {"policy": policy, "platform": platform}


def release_family(family: str, sources: dict[str, str] | None = None) -> str:
    first = html.unescape(family).split(",", 1)[0].strip().strip("\"'")
    canonical = {name.casefold(): name for name in _RELEASE_FAMILIES}
    if first.casefold() in canonical:
        selected = canonical[first.casefold()]
        if _bundled_fonts_enabled():
            return selected
        family_roles = {
            "noto sans sc": "heiti-2",
            "noto serif sc": "songti",
            "liberation sans": "heiti-1",
            "lxgw wenkai": "kaiti",
            "simzhisong": "songti",
            "lxgw neo xihei": "heiti-2",
            "misans": "heiti-1",
            "zhuque fangsong (technical preview)": "fangsong",
        }
        return role_family(family_roles[first.casefold()], sources)
    role = _FONT_ROLE_ALIASES.get(first.casefold(), first.casefold())
    if role in _FONT_ROLES:
        return role_family(role, sources)
    if first.casefold() in {"arial", "liberation sans"}:
        return "Liberation Sans"
    return role_family("heiti-2", sources)


def apply_svg_fonts(svg: str, sources: dict[str, str] | None = None) -> str:
    """Change text font requests only; preserve reference output and document settings."""
    if sources is not None and (
        not isinstance(sources, dict)
        or any(
            role not in _FONT_ROLES or choice not in ("system", "fallback")
            for role, choice in sources.items()
        )
    ):
        raise ValueError("invalid font source preferences")
    release = release_profile() or sources is not None
    if not release and not re.search(
        r"(?:HeiTi(?:-[12])?|SongTi|KaiTi|FangSong)",
        svg,
        re.IGNORECASE,
    ):
        return svg
    bundled_fonts()  # Strictly verifies Linux release assets; is empty for bundle-free releases.

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
        glyphs = coverage.get(family)
        return glyphs is not None and all(char.isspace() or ord(char) in glyphs for char in text)

    def fallback_text(match: re.Match[str]) -> str:
        text = html.unescape(_SVG_TAG.sub("", match[1]))
        element = match[0]
        for family in coverage:
            if family in element and not contains(family, text):
                replacements = ["Noto Sans SC", "Noto Serif SC"]
                replacements.extend(family for family, _ in selected_system_fonts())
                replacement = next(
                    (candidate for candidate in replacements if contains(candidate, text)),
                    family,
                )

                # Restrict replacement to font attributes/styles, never visible text/metadata.
                def replace_request(
                    attribute: re.Match[str],
                    family: str = family,
                    replacement: str = replacement,
                ) -> str:
                    name, equal, quote, value, closing = attribute.groups()
                    if name == "font-family" and html.unescape(value).strip("\"' ") == family:
                        value = replacement
                    elif name == "style":
                        value = _FAMILY_STYLE.sub(
                            lambda item: (
                                item[1]
                                + (
                                    replacement
                                    if html.unescape(item[2]).strip("\"' ") == family
                                    else item[2]
                                )
                            ),
                            value,
                        )
                    return name + equal + quote + value + closing

                element = _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(replace_request, tag[0]), element)
        return element

    return _TEXT_ELEMENT.sub(fallback_text, mapped)


@lru_cache(maxsize=1)
def bundled_fonts() -> tuple[tuple[str, str, str, Path], ...]:
    if not _bundled_fonts_enabled():
        return ()
    root = (
        Path(sys.executable).resolve().parent.parent / "fonts"
        if getattr(sys, "frozen", False)
        else Path(str(files(font_assets)))
    )
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
    faces = bundled_fonts()
    coverage: dict[str, frozenset[int]] = {}
    if faces:
        root = faces[0][3].parent
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        coverage.update(
            {
                family: frozenset(code for start, end in ranges for code in range(start, end + 1))
                for family, ranges in manifest["coverage"].items()
            }
        )
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
    if not release_profile() or sys.platform != "linux":
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
        "LXGW WenKai",
        "SimZhiSong",
        "LXGW Neo XiHei",
        "MiSans",
        "Zhuque Fangsong (technical preview)",
        "SimHei",
        "SimSun",
        "KaiTi",
        "Microsoft YaHei",
        "FangSong",
    }
    for family, weight, style, path in faces:
        _, success = font_map.register_font(family, str(path), weight=weight, style=style)
        if not success:
            raise ValueError(f"could not register bundled PDF font: {path.name}")
        if family in single_faces:
            for other_weight in ("normal", "bold"):
                for other_style in ("normal", "italic"):
                    font_map.register_font(
                        family,
                        str(path),
                        weight=other_weight,
                        style=other_style,
                    )

    import tempfile

    from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

    # svglib's public registration API accepts files but not a TTC face index.
    # Extract the chosen face temporarily, retaining its outlines and metadata.
    with tempfile.TemporaryDirectory(prefix="octopus-pdf-font-") as work:
        extracted: dict[tuple[Path, int], Path] = {}
        for family, path in selected_system_fonts(require_truetype=True):
            for weight in ("normal", "bold"):
                style_path = path
                if family == "Microsoft YaHei" and weight == "bold":
                    for filename in ("msyhbd.ttc", "msyhbd.ttf"):
                        candidate = path.with_name(filename)
                        if candidate.is_file():
                            style_path = candidate
                            break
                for style in ("normal", "italic"):
                    face = font_face(
                        style_path, family, 700 if weight == "bold" else 400, style == "italic"
                    )
                    if face is None or face[1]:
                        continue  # Native exports support CFF; Python PDF uses explicit fallback.
                    key = (style_path, face[0])
                    if key not in extracted:
                        with style_path.open("rb") as stream:
                            collection = stream.read(4) == b"ttcf"
                        if collection:
                            target = Path(work) / f"face-{len(extracted)}.ttf"
                            with TTFont(
                                style_path,
                                fontNumber=face[0],
                                recalcTimestamp=False,
                            ) as font:
                                font.save(target)
                            extracted[key] = target
                        else:
                            extracted[key] = style_path
                    _, success = font_map.register_font(
                        family,
                        str(extracted[key]),
                        weight=weight,
                        style=style,
                    )
                    if not success:
                        raise ValueError(f"could not register selected PDF font: {family}")


def apply_pdf_font_fallbacks(svg: str) -> str:
    """Use an embeddable local face when ReportLab cannot handle an installed CFF outline."""
    fallback = {}
    for role in _FONT_ROLES:
        resolved = _resolve_system_role(role)
        if resolved is None:
            continue
        family, path = resolved
        face = font_face(path, family)
        if face is None or not face[1]:
            continue
        if _bundled_fonts_enabled():
            fallback[family] = _FONT_ROLES[role][1]
            continue
        embeddable = _resolve_system_role(role, require_truetype=True)
        if embeddable is None:
            raise ValueError(f"Python PDF export requires a TrueType font for {family}")
        fallback[family] = embeddable[0]

    def rewrite(match: re.Match[str]) -> str:
        name, equal, quote, value, closing = match.groups()
        if name == "font-family":
            value = fallback.get(value, value)
        elif name == "style":
            value = _FAMILY_STYLE.sub(lambda item: item[1] + fallback.get(item[2], item[2]), value)
        return name + equal + quote + value + closing

    return _SVG_TAG.sub(lambda tag: _ATTRIBUTE.sub(rewrite, tag[0]), svg)
