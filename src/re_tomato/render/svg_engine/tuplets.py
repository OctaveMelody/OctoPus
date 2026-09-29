"""Reference-compatible planning and SVG construction for explicit tuplets."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.elements import SvgElement, _format_reference_number
from ..core.layout_types import LayoutConstruct, PageMetrics
from .primitives import attrs as _attrs
from .primitives import use_element as _use_element


@dataclass(frozen=True, slots=True)
class TupletGeometry:
    """Resolved reference coordinates for one visible tuplet."""

    path_x1: float
    path_x2: float
    path_y: float
    number_x: float
    number_y: float


def plan_tuplet_geometry(
    construct: LayoutConstruct,
    metrics: PageMetrics | None,
) -> TupletGeometry | None:
    """Return visible tuplet geometry, or ``None`` for style-2 suppression."""

    if metrics is not None and metrics.lianyinxian_type == "2":
        return None

    raw_x2 = max(construct.end.x, construct.start.x + 12)
    path_x1 = construct.start.x + 1
    path_x2 = max(raw_x2 - 1, path_x1 + 12)
    octave_clearance = 5 * max(
        construct.start.event.octave,
        construct.end.event.octave,
        0,
    )
    note_y = min(construct.start.y, construct.end.y)
    return TupletGeometry(
        path_x1=path_x1,
        path_x2=path_x2,
        path_y=note_y - 16 - octave_clearance,
        number_x=(path_x1 + path_x2) / 2,
        number_y=note_y - 23 - octave_clearance,
    )


def tuplet_elements(
    construct: LayoutConstruct,
    metrics: PageMetrics | None,
) -> list[SvgElement]:
    """Build the reference-visible path and number for one explicit tuplet."""

    geometry = plan_tuplet_geometry(construct, metrics)
    if geometry is None:
        return []
    return [
        _tuplet_path(construct, geometry),
        _use_element(
            "lianyin_shuzi_3",
            x=_format_reference_number(geometry.number_x),
            y=_format_reference_number(geometry.number_y),
            layer="construct",
            source_event_index=construct.start.event.index,
            construct_ids=construct.start.event.construct_ids,
        ),
    ]


def _tuplet_path(construct: LayoutConstruct, geometry: TupletGeometry) -> SvgElement:
    x1 = geometry.path_x1
    x2 = geometry.path_x2
    base_y = geometry.path_y
    control_offset = 0.3 * (x2 - x1) - 0.4
    number = _format_reference_number
    path = (
        f"M {number(x1)},{number(base_y)} "
        f"C {number(x1 + control_offset)},{number(base_y - 10)},"
        f"{number(x2 - control_offset)},{number(base_y - 10)},"
        f"{number(x2)},{number(base_y)} "
        f"M {number(x2)},{number(base_y)} "
        f"C  {number(x2 - control_offset)},{number(base_y - 9)},"
        f"{number(x1 + control_offset)},{number(base_y - 9)},"
        f"{number(x1)},{number(base_y)}"
    )
    return SvgElement(
        tag="path",
        layer="construct",
        source_event_index=construct.start.event.index,
        attrs=_attrs(
            ("d", path),
            ("stroke-width", "0.5"),
            ("stroke", "#1b1b1b"),
        ),
        construct_ids=construct.start.event.construct_ids,
    )


__all__ = ["TupletGeometry", "plan_tuplet_geometry", "tuplet_elements"]
