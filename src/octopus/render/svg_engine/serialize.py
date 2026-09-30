"""Exact SVG element serialization rules."""

from __future__ import annotations

import html
from typing import Literal

from ..core.elements import SvgElement

SerializationProfile = Literal["spaced", "compact"]


def _escape_attribute(name: str, value: str, *, escape_code_ampersand: bool = False) -> str:
    """Escape an attribute using the legacy renderer's source conventions.

    The old renderer wrote the source ``code`` payload verbatim.  Those
    payloads intentionally contain parser markers such as ``&ykh`` and
    apostrophes; converting them to HTML entities changes the byte stream
    even though the browser accepts the resulting SVG.  Other attributes use
    normal XML escaping, but apostrophes need no escaping inside our
    double-quoted attributes. The explicit compact profile escapes code
    ampersands like every other attribute.
    """

    if name == "code" and not escape_code_ampersand:
        return value
    return html.escape(value, quote=False)


def _ordered_attributes(element: SvgElement) -> tuple[tuple[str, str], ...]:
    """Return attributes in the legacy event-context order."""

    if element.tag != "use" or not element.attr("notepos"):
        return element.attrs
    code = element.attr("code") or ""
    if not code.startswith("|"):
        return element.attrs
    by_name = dict(element.attrs)
    if not all(name in by_name for name in ("notepos", "time", "audio")):
        return element.attrs
    ordered: list[tuple[str, str]] = []
    inserted = False
    for name, value in element.attrs:
        if name in {"time", "audio", "notepos"}:
            if not inserted:
                ordered.extend((name, by_name[name]) for name in ("notepos", "time", "audio"))
                inserted = True
            continue
        ordered.append((name, value))
    return tuple(ordered)


# Internal-only attributes: they identify construct elements for the renderer
# and audit tooling but never appear in the reference byte stream.
_INTERNAL_ONLY_ATTRIBUTES = frozenset({"data-construct", "data-source-key"})


def render_svg_element(element: SvgElement, *, compact_profile: bool = False) -> str:
    """Serialize one element without normalizing its legacy formatting.

    ``compact_profile`` selects the compact serialization profile, which omits
    the space before a closing bracket and escapes ``code`` ampersands like
    every other attribute. The default is the spaced profile. The ``<rect>``
    close form does NOT follow the profile: body rects are always
    self-closing (general rule, owner decision 2026-09-17).
    """
    if element.tag == "raw":
        return element.text or ""
    def attribute_pair(key: str, value: str) -> str:
        escaped = _escape_attribute(key, value, escape_code_ampersand=compact_profile)
        return f'{html.escape(key, quote=False)}="{escaped}"'

    attrs = " ".join(
        attribute_pair(key, value)
        for key, value in _ordered_attributes(element)
        if key not in _INTERNAL_ONLY_ATTRIBUTES
    )
    attrs_text = f" {attrs}" if attrs else ""
    gap = "" if compact_profile else " "
    if element.tag == "rect":
        # General rule (owner decision 2026-09-17): the close form never
        # follows the export profile or document identity. The page background
        # is the only emitted body rect; it keeps the spaced self-closing form
        # used by 2,005 of the 2,028 corpus references.
        close = " />" if element.layer == "background" else "/>"
        return f"<{element.tag}{attrs_text}{close}"
    if element.tag in {"path", "line"}:
        # Body constructs use explicit empty tags (``<line ...></line>``).
        # Defs glyph XML is assembled separately and never reaches here.
        return f"<{element.tag}{attrs_text}{gap}></{element.tag}>"
    if element.tag == "use":
        return f"<use{attrs_text}{gap}></use>"
    # Text content is not an attribute: apostrophes are valid XML text and
    # the reference keeps them literal.  Keep escaping ampersands and angle
    # brackets so arbitrary annotation text remains well-formed.
    text = html.escape(element.text or "", quote=False)
    if element.layer == "custom":
        return f"<{element.tag}{attrs_text}>{text}</{element.tag}>"
    return f"<{element.tag}{attrs_text}{gap}>{text}</{element.tag}>"


__all__ = ["render_svg_element"]
