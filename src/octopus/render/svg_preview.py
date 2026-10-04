"""Build inert preview pages with a conservative custom-SVG allowlist."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import escape

from octopus.normalization.types import ScoreModel
from octopus.render.svg_engine.custom import custom_elements

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
MAX_CUSTOM_SVG_BYTES = 1024 * 1024
MAX_CUSTOM_ELEMENTS = 10_000
MAX_CUSTOM_DEPTH = 128

_SAFE_TAGS = {
    "circle",
    "ellipse",
    "g",
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
    "text",
    "tspan",
}
_SAFE_ATTRIBUTES = {
    "alignment-baseline",
    "cx",
    "cy",
    "d",
    "dx",
    "dy",
    "fill",
    "fill-opacity",
    "fill-rule",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "height",
    "letter-spacing",
    "opacity",
    "points",
    "r",
    "rx",
    "ry",
    "stroke",
    "stroke-dasharray",
    "stroke-dashoffset",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-opacity",
    "stroke-width",
    "text-anchor",
    "transform",
    "width",
    "word-spacing",
    "x",
    "x1",
    "x2",
    "y",
    "y1",
    "y2",
}
_SAFE_STYLE_ATTRIBUTES = _SAFE_ATTRIBUTES - {
    "cx",
    "cy",
    "d",
    "dx",
    "dy",
    "height",
    "points",
    "r",
    "rx",
    "ry",
    "width",
    "x",
    "x1",
    "x2",
    "y",
    "y1",
    "y2",
}
_SVG_ID_RE = re.compile(r"^[A-Za-z_][\w:.-]*$", re.UNICODE)
_COLOR_RE = re.compile(r"^(?:#[\da-fA-F]{3,8}|[A-Za-z][A-Za-z0-9-]*)$")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_LENGTH_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:%|px|pt|pc|mm|cm|in|em|ex)?$"
)
_NUMBER_LIST_RE = re.compile(r"^[+\-\d.eE,%\s]+$")
_PATH_DATA_RE = re.compile(r"^[A-Za-z+\-\d.eE,\s]*$")
_TRANSFORM_RE = re.compile(
    r"^(?:(?:matrix|translate|scale|rotate|skewX|skewY)\s*"
    r"\(\s*[+\-\d.eE,\s]+\)\s*)+$"
)
_LOCAL_URL_RE = re.compile(r"^url\(\s*(['\"]?)#([A-Za-z_][\w:.-]*)\1\s*\)$")
_STYLE_SPLIT_RE = re.compile(r"\s*;\s*")


def add_safe_custom_markup(model: ScoreModel, pages: list[str]) -> tuple[list[str], bool]:
    """Insert sanitized page-specific custom markup; report whether any was omitted."""
    if not model.custom_code.strip():
        return pages, False
    if not pages:
        return pages, True

    output: list[str] = []
    omitted = False
    for page_index, page in enumerate(pages):
        safe_page, page_omitted = add_safe_custom_page_markup(model, page_index, page)
        omitted |= page_omitted
        output.append(safe_page)
    extra = next(
        (item.text for item in custom_elements(model, len(pages)) if item.tag == "raw"),
        None,
    )
    if extra is not None:
        extra_markup, extra_omitted = _sanitize_custom_group(extra, "")
        omitted |= extra_omitted or extra_markup is not None
    return output, omitted


def add_safe_custom_page_markup(model: ScoreModel, page_index: int, page: str) -> tuple[str, bool]:
    """Insert only this page's sanitized custom markup into its SVG."""
    raw = next(
        (item.text for item in custom_elements(model, page_index) if item.tag == "raw"),
        None,
    )
    if raw is None:
        return page, False
    safe_markup, omitted = _sanitize_custom_group(raw, page)
    placeholder = '<g id="custom"></g>'
    if safe_markup is None or page.count(placeholder) != 1:
        return page, omitted or safe_markup is not None
    return page.replace(placeholder, safe_markup, 1), omitted


def _sanitize_custom_group(markup: str, page: str) -> tuple[str | None, bool]:
    if len(markup.encode("utf-8")) > MAX_CUSTOM_SVG_BYTES:
        return None, True
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", markup, flags=re.IGNORECASE):
        return None, True
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(markup, parser=parser)
    except (ET.ParseError, RecursionError, ValueError):
        return None, True
    if _element_name(root.tag) != ("g", "") or root.get("id") != "custom":
        return None, True
    if not _within_tree_limits(root):
        return None, True
    if not len(root) and not (root.text or "").strip():
        return None, False

    core_ids = set(re.findall(r'\bid="([^"\s]+)"', page))
    custom_ids: set[str] = set()
    for element in _allowed_elements(root):
        identifier = element.get("id")
        if identifier and _SVG_ID_RE.fullmatch(identifier):
            custom_ids.add(identifier)
    prefix = "jps-ui-custom-"
    while any(prefix + identifier in core_ids for identifier in custom_ids):
        prefix += "x-"
    id_map = {identifier: prefix + identifier for identifier in custom_ids}
    emitted_ids: set[str] = set()
    serialized, omitted = _serialize_element(root, core_ids, id_map, emitted_ids)
    if serialized is None:
        return None, True
    return serialized, omitted


def _element_name(tag: object) -> tuple[str, str] | None:
    if not isinstance(tag, str):
        return None
    if tag.startswith("{"):
        namespace, separator, local = tag[1:].partition("}")
        return (local, namespace) if separator else None
    return tag, ""


def _within_tree_limits(root: ET.Element) -> bool:
    stack: list[tuple[ET.Element, int]] = [(root, 0)]
    count = 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_CUSTOM_ELEMENTS or depth > MAX_CUSTOM_DEPTH:
            return False
        stack.extend((child, depth + 1) for child in element)
    return True


def _allowed_elements(root: ET.Element) -> list[ET.Element]:
    result: list[ET.Element] = []
    stack = list(reversed(list(root)))
    while stack:
        element = stack.pop()
        name = _element_name(element.tag)
        if name and name[1] in ("", SVG_NAMESPACE) and name[0] in _SAFE_TAGS:
            result.append(element)
            stack.extend(reversed(list(element)))
    return result


def _serialize_element(
    element: ET.Element,
    core_ids: set[str],
    id_map: dict[str, str],
    emitted_ids: set[str],
) -> tuple[str | None, bool]:
    name = _element_name(element.tag)
    if name is None or name[1] not in ("", SVG_NAMESPACE):
        return None, True
    tag = name[0]
    if tag not in _SAFE_TAGS:
        return None, True

    attrs: list[tuple[str, str]] = []
    omitted = False
    for key, value in element.attrib.items():
        if key == "id":
            if not _SVG_ID_RE.fullmatch(value) or value in emitted_ids:
                omitted = True
                continue
            emitted_ids.add(value)
            attrs.append((key, id_map.get(value, value)))
            continue
        if key == "style":
            style, style_omitted = _sanitize_style(value, core_ids, id_map)
            omitted |= style_omitted
            if style:
                attrs.append((key, style))
            continue
        if key not in _SAFE_ATTRIBUTES:
            omitted = True
            continue
        safe_value = _sanitize_attribute(key, value, core_ids, id_map)
        if safe_value is None:
            omitted = True
            continue
        attrs.append((key, safe_value))

    opening = "<" + tag + "".join(f' {key}="{escape(value, quote=True)}"' for key, value in attrs)
    children: list[str] = []
    for child in element:
        child_svg, child_omitted = _serialize_element(child, core_ids, id_map, emitted_ids)
        omitted |= child_omitted
        if child_svg is None:
            omitted = True
        else:
            children.append(child_svg)
        if child.tail:
            children.append(escape(child.tail))
    text = escape(element.text or "")
    if not children and not text:
        return opening + "/>", omitted
    return opening + ">" + text + "".join(children) + f"</{tag}>", omitted


def _sanitize_style(value: str, core_ids: set[str], id_map: dict[str, str]) -> tuple[str, bool]:
    declarations: list[str] = []
    omitted = False
    for declaration in _STYLE_SPLIT_RE.split(value.strip()):
        if not declaration:
            continue
        key, separator, raw_value = declaration.partition(":")
        key = key.strip().lower()
        raw_value = raw_value.strip()
        if not separator or key not in _SAFE_STYLE_ATTRIBUTES:
            omitted = True
            continue
        safe_value = _sanitize_attribute(key, raw_value, core_ids, id_map)
        if safe_value is None:
            omitted = True
            continue
        declarations.append(f"{key}:{safe_value}")
    return ";".join(declarations), omitted


def _sanitize_attribute(
    name: str, value: str, core_ids: set[str], id_map: dict[str, str]
) -> str | None:
    if len(value) > 8192 or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        return None
    if name in ("fill", "stroke"):
        if "url" in value.lower():
            match = _LOCAL_URL_RE.fullmatch(value.strip())
            if not match:
                return None
            identifier = match.group(2)
            if identifier not in core_ids and identifier not in id_map and identifier != "custom":
                return None
            return f"url(#{id_map.get(identifier, identifier)})"
        return value if _COLOR_RE.fullmatch(value.strip()) else None
    if name in ("opacity", "fill-opacity", "stroke-opacity"):
        return value if _NUMBER_RE.fullmatch(value.strip()) else None
    if name in ("fill-rule",):
        return value if value in ("nonzero", "evenodd") else None
    if name in ("stroke-linecap",):
        return value if value in ("butt", "round", "square") else None
    if name in ("stroke-linejoin",):
        return value if value in ("miter", "round", "bevel") else None
    if name in ("font-style",):
        return value if value in ("normal", "italic", "oblique") else None
    if name in ("font-weight",):
        return (
            value
            if value in ("normal", "bold", "bolder", "lighter")
            or re.fullmatch(r"(?:[1-9]\d{0,2}|1000)", value)
            else None
        )
    if name in ("text-anchor",):
        return value if value in ("start", "middle", "end") else None
    if name in ("font-family",):
        return value if re.fullmatch(r"[\w ,_-]+", value, flags=re.UNICODE) else None
    if name == "transform":
        return value if _TRANSFORM_RE.fullmatch(value.strip()) else None
    if name in ("d", "points"):
        pattern = _PATH_DATA_RE if name == "d" else _NUMBER_LIST_RE
        return value if pattern.fullmatch(value.strip()) else None
    if name in ("stroke-dasharray",):
        return value if value == "none" or _NUMBER_LIST_RE.fullmatch(value.strip()) else None
    if name in ("stroke-width", "stroke-dashoffset", "font-size", "letter-spacing", "word-spacing"):
        return value if _LENGTH_RE.fullmatch(value.strip()) else None
    if name in ("alignment-baseline",):
        return value if re.fullmatch(r"[A-Za-z-]+", value) else None
    if name in (
        "x",
        "y",
        "x1",
        "x2",
        "y1",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "width",
        "height",
        "dx",
        "dy",
    ):
        return value if _LENGTH_RE.fullmatch(value.strip()) else None
    return None


__all__ = ["add_safe_custom_markup"]
