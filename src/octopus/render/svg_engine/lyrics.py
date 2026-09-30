"""Lyric ordering and SVG element construction."""

from __future__ import annotations

from decimal import Decimal

from ..core.elements import SvgElement, _format_reference_number
from ..core.layout_types import LayoutLyric, LayoutPage


def _attrs(*items: tuple[str, object | None]) -> tuple[tuple[str, str], ...]:
    return tuple((key, str(value)) for key, value in items if value is not None)


def _lyric_dy(font_size: int) -> str:
    """Reference baseline nudge: 0.3355 x font-size, exact decimal, trailing zeros stripped."""
    text = format(Decimal("0.3355") * font_size, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _text_element(
    *,
    x: str | float,
    y: str | float,
    text: str,
    layer: str,
    extra_attrs: tuple[tuple[str, str], ...] = (),
) -> SvgElement:
    return SvgElement(
        tag="text",
        layer=layer,
        source_event_index=None,
        attrs=(("x", str(x)), ("y", str(y)), *extra_attrs),
        text=text,
    )


def lyric_host_key(lyric: LayoutLyric) -> tuple[int, int, int]:
    return (lyric.voice, lyric.line, lyric.slot)


def lyric_order_key(lyric: LayoutLyric) -> tuple[int, int, int, int]:
    """Complete each verse at a host before emitting the next verse's text."""
    return (
        lyric.line,
        lyric.slot,
        lyric.verse,
        1 if lyric.annotation else 0,
    )


def lyric_element(layout: LayoutPage, lyric: LayoutLyric) -> SvgElement:
    if lyric.annotation:
        return _text_element(
            x=_format_reference_number(lyric.x),
            y=int(lyric.y),
            text=lyric.text,
            layer="lyric",
            extra_attrs=_attrs(
                ("dy", _lyric_dy(16)),
                ("text-anchor", "end"),
                ("fill", "#101010"),
                ("font-size", "16"),
                ("font-family", layout.metrics.lyric_font),
                ("xml:space", "preserve"),
            ),
        )
    return _text_element(
        x=_format_reference_number(lyric.x),
        y=int(lyric.y),
        text=lyric.text,
        layer="lyric",
        extra_attrs=_attrs(
            ("dy", _lyric_dy(layout.metrics.lyric_size)),
            ("fill", "#101010"),
            ("font-size", layout.metrics.lyric_size),
            ("font-family", layout.metrics.lyric_font),
            ("cipos", lyric.cipos),
        ),
    )


def lyric_elements(layout: LayoutPage) -> list[SvgElement]:
    return [
        lyric_element(layout, lyric)
        for lyric in sorted(layout.lyrics, key=lyric_order_key)
    ]


def lyrics_by_host(layout: LayoutPage) -> dict[tuple[int, int, int], tuple[SvgElement, ...]]:
    grouped: dict[tuple[int, int, int], list[SvgElement]] = {}
    for lyric in sorted(layout.lyrics, key=lyric_order_key):
        grouped.setdefault(lyric_host_key(lyric), []).append(lyric_element(layout, lyric))
    return {key: tuple(value) for key, value in grouped.items()}

__all__ = ["lyric_element","lyric_elements","lyric_host_key","lyric_order_key","lyrics_by_host"]
