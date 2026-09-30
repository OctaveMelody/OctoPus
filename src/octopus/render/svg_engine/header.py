"""SVG page-header rendering."""

from __future__ import annotations

import re
from decimal import Decimal

from ..core.elements import SvgElement
from ..core.glyphs import get_key_glyphs, get_time_signature_glyphs
from ..core.layout_types import LayoutPage


def _attrs(*items: tuple[str, object | None]) -> tuple[tuple[str, str], ...]:
    return tuple((key, str(value)) for key, value in items if value is not None)


def _dy(coefficient: float, size: int) -> str:
    """Reference vertical offset: ``coefficient × size``, exact decimal, trailing zeros stripped."""
    text = format(Decimal(str(coefficient)) * size, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# Reference header text sizes. Tempo and credits do not scale with ``geci_size``;
# they use a fixed 16 px (19 px when the lyric font is KaiTi).
HEADER_TEXT_SIZE = 16
KAITI_TEXT_SIZE = 19


def _use_element(
    glyph_id: str,
    *,
    x: str | float,
    y: str | float,
    layer: str,
    source_event_index: int | None = None,
    construct_ids: tuple[str, ...] = (),
    synthetic: bool = False,
    extra_attrs: tuple[tuple[str, str], ...] = (),
) -> SvgElement:
    return SvgElement(
        tag="use",
        layer=layer,
        source_event_index=source_event_index,
        attrs=(
            ("x", str(x)),
            ("y", str(y)),
            ("xlink:href", f"#{glyph_id}"),
            *extra_attrs,
            ("xmlns:xlink", "http://www.w3.org/1999/xlink"),
        ),
        construct_ids=construct_ids,
        synthetic=synthetic,
    )


def _text_element(
    *,
    x: str | float,
    y: str | float,
    text: str,
    layer: str,
    synthetic: bool = False,
    extra_attrs: tuple[tuple[str, str], ...] = (),
) -> SvgElement:
    return SvgElement(
        tag="text",
        layer=layer,
        source_event_index=None,
        attrs=(
            ("x", str(x)),
            ("y", str(y)),
            *extra_attrs,
        ),
        text=text,
        synthetic=synthetic,
    )


def header_elements(layout: LayoutPage) -> list[SvgElement]:
    header = layout.header
    metrics = layout.metrics
    font = metrics.title_font
    elements: list[SvgElement] = []
    if header.title:
        elements.append(
            _text_element(
                x=f"{metrics.width / 2:.0f}",
                y=metrics.title_y,
                text=header.title,
                layer="header",
                synthetic=True,
                extra_attrs=_attrs(
                    ("dy", _dy(0.8355, metrics.title_size)),
                    ("text-anchor", "middle"),
                    ("fill", "#1b1b1b"),
                    ("style", "font-weight:bold;"),
                    ("font-size", metrics.title_size),
                    ("font-family", font),
                ),
            )
        )
    if header.subtitle:
        elements.append(
            _text_element(
                x=f"{metrics.width / 2:.0f}",
                y=metrics.title_y + 56 + metrics.header_content_offset_y,
                text=header.subtitle,
                layer="header",
                synthetic=True,
                extra_attrs=_attrs(
                    ("dy", _dy(0.8355, metrics.subtitle_size)),
                    ("text-anchor", "middle"),
                    ("fill", "#1b1b1b"),
                    ("font-size", metrics.subtitle_size),
                    ("font-family", font),
                ),
            )
        )
    if header.key or header.time_sig:
        elements.extend(key_sig_elements(layout, header.key, header.time_sig))
    if header.tempo:
        elements.extend(tempo_elements(layout, header.tempo))
    # Composer/lyricist credits use a fixed size (16, or 19 for KaiTi), not geci_size.
    author_size = KAITI_TEXT_SIZE if metrics.lyric_font == "KaiTi" else HEADER_TEXT_SIZE
    # The credit block's bottom sits 30 px higher when the header has no tempo line.
    credit_bottom = metrics.credit_y - (0 if header.tempo else 30)
    for index, (label, value) in enumerate(reversed(header.credits)):
        y = credit_bottom - index * 21
        text = f"{value} {label}" if label else value
        elements.append(
            _text_element(
                x=metrics.width - metrics.margin_right,
                y=y,
                text=text,
                layer="header",
                synthetic=True,
                extra_attrs=_attrs(
                    ("dy", _dy(-0.1645, author_size)),
                    ("text-anchor", "end"),
                    ("fill", "#1b1b1b"),
                    ("font-size", author_size),
                    ("font-family", metrics.lyric_font),
                ),
            )
        )
    return elements


def key_sig_elements(layout: LayoutPage, key: str, time_sig: str) -> list[SvgElement]:
    metrics = layout.metrics
    elements: list[SvgElement] = []
    x = metrics.margin_left
    y = metrics.key_y
    key_glyphs = get_key_glyphs(key)
    for glyph in key_glyphs:
        glyph_id = glyph["glyph"]
        offset_x = glyph.get("offset_x", 0)
        extra_attrs: tuple[tuple[str, str], ...] = ()
        if "data-diaohao" in glyph:
            extra_attrs = (("code", key), ("data-diaohao", "true"))
        elements.append(
            _use_element(
                glyph_id,
                x=x + offset_x,
                y=y,
                layer="header",
                synthetic=True,
                extra_attrs=extra_attrs,
            )
        )
    if time_sig:
        # Reference places the fraction bar ten pixels past the last key-signature
        # glyph (the letter sits 40 px from the key mark, 45 px with an accidental).
        last_key_offset = max((g.get("offset_x", 0) for g in key_glyphs), default=40)
        ts_x = x + last_key_offset + 10
        for glyph in get_time_signature_glyphs(time_sig, metrics.note_font):
            glyph_id = glyph["glyph"]
            glyph_x = ts_x + glyph.get("offset_x", 0)
            glyph_y = y
            extra_attrs = ()
            if glyph.get("is_numerator"):
                glyph_y = y - 12
            elif glyph.get("is_denominator"):
                glyph_y = y + 12
                extra_attrs = (("fill", "#414141"),)
            elements.append(
                _use_element(
                    glyph_id,
                    x=glyph_x,
                    y=glyph_y,
                    layer="header",
                    synthetic=True,
                    extra_attrs=extra_attrs,
                )
            )
    return elements


def tempo_elements(layout: LayoutPage, tempo: str) -> list[SvgElement]:
    metrics = layout.metrics
    if not re.fullmatch(r"\d+(?:\.\d+)?", tempo.strip()):
        return [
            _text_element(
                x=metrics.margin_left,
                y=metrics.tempo_y + 1,
                text=tempo,
                layer="header",
                synthetic=True,
                extra_attrs=_attrs(
                    ("dy", _dy(0.3355, HEADER_TEXT_SIZE)),
                    ("fill", "#1b1b1b"),
                    ("font-size", HEADER_TEXT_SIZE),
                    ("font-family", metrics.lyric_font),
                ),
            )
        ]
    return [
        _use_element(
            "jiepaifu",
            x=metrics.margin_left,
            y=metrics.tempo_y,
            layer="header",
            synthetic=True,
        ),
        _text_element(
            x=metrics.margin_left + 32,
            y=metrics.tempo_y + 1,
            text=tempo,
            layer="header",
            synthetic=True,
            extra_attrs=_attrs(
                ("dy", _dy(0.3355, HEADER_TEXT_SIZE)),
                ("fill", "#1b1b1b"),
                ("font-size", HEADER_TEXT_SIZE),
                ("font-family", metrics.lyric_font),
                ("data-jiepai", tempo),
            ),
        ),
    ]

__all__ = ["header_elements","key_sig_elements","tempo_elements"]
