"""Load packaged glyph definitions and map normalized events to glyph IDs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ...parser.ast import MusicTokenKind

# Assets live at the octopus package root (octopus/assets/glyphs) — this
# module sits two levels below it now that the render kernel is in core/.
_GLYPH_DIR = Path(__file__).parent.parent.parent / "assets" / "glyphs"
_REGISTRY: dict[str, str] | None = None
_GLYPH_CACHE: dict[str, str] | None = None


def _load_registry() -> dict[str, str]:
    global _REGISTRY
    if _REGISTRY is None:
        reg_path = _GLYPH_DIR / "registry.json"
        _REGISTRY = json.loads(reg_path.read_text(encoding="utf-8"))
    return _REGISTRY  # type: ignore[return-value]


def _replace_final_self_closing_tag(xml: str, replacement: str) -> str:
    """Replace only the FINAL ``/>`` (a blanket replace would corrupt any other
    leaf tags the asset may gain)."""
    index = xml.rfind("/>")
    if index == -1:
        return xml
    return xml[:index] + replacement


def load_glyph(glyph_id: str) -> str | None:
    global _GLYPH_CACHE
    if _GLYPH_CACHE is None:
        _GLYPH_CACHE = {}
    if glyph_id in _GLYPH_CACHE:
        return _GLYPH_CACHE[glyph_id]
    registry = _load_registry()
    if glyph_id not in registry:
        return None
    svg_path = _GLYPH_DIR / f"{glyph_id}.svg"
    if not svg_path.exists():
        return None
    xml = svg_path.read_text(encoding="utf-8")
    # Glyph assets are serialized as compact legacy fragments.  Normalize
    # the optional whitespace before self-closing tags at the asset boundary;
    # page-level background elements retain their separate serializer rule.
    xml = re.sub(r"\s+/>", "/>", xml)
    if glyph_id == "shuzi_null":
        # The null glyph is a bare self-closing <g>; the reference emits it as
        # an explicit empty group: ``/>`` becomes ``></g>`` (the opening tag's
        # closing ``>`` must survive — dropping it breaks the page XML).
        xml = _replace_final_self_closing_tag(xml, "></g>")
    _GLYPH_CACHE[glyph_id] = xml
    return xml


def load_all_glyphs() -> dict[str, str]:
    registry = _load_registry()
    result: dict[str, str] = {}
    for gid in registry:
        xml = load_glyph(gid)
        if xml is not None:
            result[gid] = xml
    return result


def note_glyph_id(pitch: int, font_style: str = "b") -> str:
    return f"shuzi_{font_style}_{pitch}"


def barline_glyph_id(code: str) -> str:
    mapping: dict[str, str] = {
        "|": "xiaojiexian",
        "|n": "xiaojiexian_none",
        "|w": "xiaojiexian_weibu",
        "|s": "xiaojiexian_shuangxian",
        "|l": "xunhuan_zuoyou",
        "|z": "xunhuan_zuo",
        "|y": "xunhuan_you",
        "|j": "jieshufu",
    }
    for prefix in ("|n", "|w", "|s", "|l", "|z", "|y", "|j"):
        if code.startswith(prefix):
            return mapping[prefix]
    return mapping.get(code, "xiaojiexian")


def event_to_glyph_id(
    kind: MusicTokenKind,
    pitch: int | None,
    code: str,
    font_style: str = "b",
) -> str | None:
    if kind == MusicTokenKind.HIDDEN_REST:
        return "shuzi_null"
    if kind in {MusicTokenKind.NOTE, MusicTokenKind.REST, MusicTokenKind.RHYTHM_NOTE}:
        p = pitch if pitch is not None else 0
        return note_glyph_id(p, font_style)
    if kind == MusicTokenKind.BARLINE:
        return barline_glyph_id(code)
    if kind == MusicTokenKind.EXTENSION:
        return "yanyinfu"
    return None


DECORATION_GLYPH_MAP: dict[str, str] = {
    "mp": "lidu_mp",
    "mf": "lidu_mf",
    "f": "lidu_f",
    "p": "lidu_p",
    "ff": "lidu_ff",
    "pp": "lidu_pp",
    "rit": "lidu_rit",
    "dim": "lidu_dim",
    "yc": "yanchang",
    "hs": "xiaojiexian_hs",
    "ds": "xiaojiexian_ds",
    "ty": "xiaojiexian_ty",
    "sby": "boyinfu_shang1",
    "shy": "huayin_shang",
    "xhy": "huayin_xia",
    "bc": "baochifu",
}

ACCIDENTAL_GLYPH_MAP: dict[str, str] = {
    "#": "bianyinfu_sheng",
    "$": "bianyinfu_jiang",
    "b": "bianyinfu_jiang",
    "=": "bianyinfu_huanyuan",
}


def get_decoration_glyph(decoration: str) -> str | None:
    base = decoration.lstrip("&")
    return DECORATION_GLYPH_MAP.get(base)


def get_accidental_glyph(accidental: str) -> str | None:
    return ACCIDENTAL_GLYPH_MAP.get(accidental)


def get_key_glyphs(key_value: str) -> list[dict[str, Any]]:
    key_value = key_value.strip()
    if not key_value:
        return []
    items: list[dict[str, Any]] = [{"glyph": "diaohao_fu", "offset_x": 0}]
    accidental = ""
    if key_value.endswith(("$", "#")):
        accidental = key_value[-1]
        key_value = key_value[:-1]
    elif key_value.endswith("b") and len(key_value) > 1:
        # Flat spelled with a trailing lowercase b (the corpus uses $; accepted
        # for symmetry with ACCIDENTAL_GLYPH_MAP, which maps "b" to the flat).
        accidental = "$"
        key_value = key_value[:-1]
    if not key_value:
        return items  # a bare accidental carries no letter glyph
    if key_value.startswith("b") and len(key_value) > 1:
        accidental = "$"
        letter = key_value[1:].lower()
    elif key_value.startswith("#"):
        letter = key_value[1:].upper()
    else:
        letter = key_value[0].upper()
    if accidental == "$":
        items.append({"glyph": "bianyinfu_jiang", "offset_x": 45})
    elif accidental == "#":
        items.append({"glyph": "bianyinfu_sheng", "offset_x": 45})
    if letter:
        gid = f"diaohao_zimu_{letter.lower()}"
        items.append(
            {
                "glyph": gid,
                "offset_x": 45 if accidental else 40,
                "data-diaohao": True,
            }
        )
    return items


def get_time_signature_glyphs(time_sig: str, font_style: str = "b") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for meter_index, meter in enumerate(time_sig.split()):
        parts = meter.split("/")
        if len(parts) != 2:
            continue
        offset_base = meter_index * 27
        items.append({"glyph": "paihao_xian", "offset_x": offset_base})
        num = parts[0]
        den = parts[1]
        for digit in num:
            d = digit.strip()
            if d.isdigit():
                gid = f"shuzi_{font_style}_bian_{d}"
                items.append({"glyph": gid, "offset_x": offset_base + 10, "is_numerator": True})
        for digit in den:
            d = digit.strip()
            if d.isdigit():
                gid = f"shuzi_{font_style}_bian_{d}"
                items.append({"glyph": gid, "offset_x": offset_base + 10, "is_denominator": True})
    return items
