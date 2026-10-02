"""Load packaged glyph definitions and map normalized events to glyph IDs."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ...parser.ast import MusicTokenKind

# Assets live at the octopus package root (octopus/assets/glyphs) — this
# module sits two levels below it now that the render kernel is in core/.
_GLYPH_DIR = Path(__file__).parent.parent.parent / "assets" / "glyphs"
_REGISTRY: dict[str, str] | None = None
_GLYPH_CACHE: dict[str, str] | None = None
_SMALL_NOTE_GLYPH = re.compile(r"shuzi_([abc])_bian_([0-9x])")


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
        generated = _missing_note_glyph(glyph_id)
        if generated is not None:
            _GLYPH_CACHE[glyph_id] = generated
        return generated
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


def _missing_note_glyph(glyph_id: str) -> str | None:
    """Complete digit families from packaged outlines without changing existing assets."""
    if re.fullmatch(r"shuzi_[abc]_x", glyph_id):
        # JPS 9 is the rhythm cross, distinct from a numeric meter digit 9.
        style = glyph_id.split("_")[1]
        slant = ' transform="skewX(-12)"' if style == "c" else ""
        weight = "3" if style == "b" else "2"
        return (
            f'<g id="{glyph_id}"><path d="M-5,-8 L5,8 M5,-8 L-5,8" '
            f'fill="none" stroke="#1b1b1b" stroke-width="{weight}"{slant}/></g>'
        )
    if glyph_id in {"shuzi_a_0", "shuzi_c_0"}:
        # Use the catalog's regular rest when a style has no separate rest
        # outline. It also supplies that style's reduced BZ rest.
        source = load_glyph("shuzi_b_0")
        if source is None:
            return None
        return source.replace('id="shuzi_b_0"', f'id="{glyph_id}"', 1)
    match = _SMALL_NOTE_GLYPH.fullmatch(glyph_id)
    if match is None:
        return None
    style, digit = match.groups()
    source = load_glyph(f"shuzi_{style}_{digit}") or load_glyph(f"shuzi_b_{digit}")
    if source is None:
        # 8 and 9 are meter digits, with only reduced outlines in the catalog.
        if style != "b" and (source := load_glyph(f"shuzi_b_bian_{digit}")) is not None:
            return source.replace(f'id="shuzi_b_bian_{digit}"', f'id="{glyph_id}"', 1)
        return None
    outline = ET.fromstring(source)
    outline.attrib.pop("id", None)
    for child in list(outline):
        if child.tag == "rect" and child.attrib.get("fill") in {"#ffffff", "white"}:
            # Ordinary notes have an opaque erasing box; small BZ notes must
            # leave neighboring accompaniment symbols and underlines visible.
            outline.remove(child)
    reduced = ET.Element("g", {"id": glyph_id, "transform": "scale(0.8)"})
    reduced.append(outline)
    return re.sub(r"\s+/>", "/>", ET.tostring(reduced, encoding="unicode"))


def load_all_glyphs() -> dict[str, str]:
    registry = _load_registry()
    result: dict[str, str] = {}
    for gid in registry:
        xml = load_glyph(gid)
        if xml is not None:
            result[gid] = xml
    for style in "abc":
        for digit in range(10):
            for gid in (f"shuzi_{style}_{digit}", f"shuzi_{style}_bian_{digit}"):
                if gid not in result and (xml := load_glyph(gid)) is not None:
                    result[gid] = xml
        for gid in (f"shuzi_{style}_x", f"shuzi_{style}_bian_x"):
            if (xml := load_glyph(gid)) is not None:
                result[gid] = xml
    return result


def note_glyph_id(pitch: int, font_style: str = "b") -> str:
    return f"shuzi_{font_style}_{'x' if pitch == 9 else pitch}"


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
        for index, digit in enumerate(num):
            d = digit.strip()
            if d.isdigit():
                gid = f"shuzi_{font_style}_bian_{d}"
                offset = offset_base + 10 + (index - (len(num) - 1) / 2) * 9
                offset = int(offset) if offset.is_integer() else offset
                items.append({"glyph": gid, "offset_x": offset, "is_numerator": True})
        for index, digit in enumerate(den):
            d = digit.strip()
            if d.isdigit():
                gid = f"shuzi_{font_style}_bian_{d}"
                offset = offset_base + 10 + (index - (len(den) - 1) / 2) * 9
                offset = int(offset) if offset.is_integer() else offset
                items.append({"glyph": gid, "offset_x": offset, "is_denominator": True})
    return items
