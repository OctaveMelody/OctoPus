"""Immutable intermediate SVG element records and reference-number formatting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def _format_reference_number(value: float) -> str:
    decimal_value = Decimal(str(value))
    if decimal_value.is_zero():
        return "0"
    quantum = Decimal(1).scaleb(decimal_value.adjusted() - 13)
    text = format(decimal_value.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _optional_attrs(
    *items: tuple[str, object | None],
) -> tuple[tuple[str, str], ...]:
    return tuple((key, str(value)) for key, value in items if value is not None)


@dataclass(frozen=True, slots=True)
class SvgElement:
    tag: str
    source_event_index: int | None
    layer: str
    attrs: tuple[tuple[str, str], ...] = ()
    text: str | None = None
    construct_ids: tuple[str, ...] = ()
    synthetic: bool = False

    @property
    def glyph_id(self) -> str | None:
        href = self.attr("xlink:href") or self.attr("href")
        return href.removeprefix("#") if href is not None else None

    @property
    def x(self) -> float:
        return float(self.attr("x") or 0)

    @property
    def y(self) -> float:
        return float(self.attr("y") or 0)

    @property
    def time(self) -> str | None:
        return self.attr("time")

    @property
    def audio(self) -> str | None:
        return self.attr("audio")

    @property
    def notepos(self) -> str | None:
        return self.attr("notepos")

    @property
    def code(self) -> str | None:
        return self.attr("code")

    @property
    def attributes(self) -> tuple[tuple[str, str], ...]:
        compatibility_names = {
            "x",
            "y",
            "xlink:href",
            "href",
            "time",
            "audio",
            "notepos",
            "code",
            "xmlns:xlink",
        }
        return tuple((key, value) for key, value in self.attrs if key not in compatibility_names)

    def attr(self, name: str) -> str | None:
        for key, value in self.attrs:
            if key == name:
                return value
        return None


class RenderElement(SvgElement):
    __slots__ = ()

    def __init__(
        self,
        glyph_id: str,
        code: str | None,
        time: str | None,
        audio: str | None,
        x: float,
        y: float,
        notepos: str | None,
        source_event_index: int | None,
        layer: str,
        construct_ids: tuple[str, ...] = (),
        synthetic: bool = False,
        attributes: tuple[tuple[str, str], ...] = (),
    ) -> None:
        attrs = (
            ("x", _format_reference_number(x)),
            ("y", str(int(y))),
            ("xlink:href", f"#{glyph_id}"),
            *_optional_attrs(
                ("time", time),
                ("audio", audio),
                ("notepos", notepos),
                ("code", code),
            ),
            *attributes,
            ("xmlns:xlink", "http://www.w3.org/1999/xlink"),
        )
        object.__setattr__(self, "tag", "use")
        object.__setattr__(self, "layer", layer)
        object.__setattr__(self, "source_event_index", source_event_index)
        object.__setattr__(self, "attrs", attrs)
        object.__setattr__(self, "text", None)
        object.__setattr__(self, "construct_ids", construct_ids)
        object.__setattr__(self, "synthetic", synthetic)
