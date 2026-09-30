"""Primitive SVG element constructors shared by render passes."""

from __future__ import annotations

from ..core.elements import SvgElement


def attrs(*items: tuple[str, object | None]) -> tuple[tuple[str, str], ...]:
    """Convert optional SVG attribute values to serialized string pairs."""

    return tuple((key, str(value)) for key, value in items if value is not None)


def text_element(
    *,
    x: str | float,
    y: str | float,
    text: str,
    layer: str,
    source_event_index: int | None = None,
    construct_ids: tuple[str, ...] = (),
    synthetic: bool = False,
    extra_attrs: tuple[tuple[str, str], ...] = (),
) -> SvgElement:
    """Construct an SVG ``text`` element without serializing it."""

    return SvgElement(
        tag="text",
        layer=layer,
        source_event_index=source_event_index,
        attrs=(("x", str(x)), ("y", str(y)), *extra_attrs),
        text=text,
        construct_ids=construct_ids,
        synthetic=synthetic,
    )


def use_element(
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
    """Construct an SVG ``use`` element without serializing it."""

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


__all__ = ["attrs", "text_element", "use_element"]
