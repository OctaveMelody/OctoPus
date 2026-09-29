"""Pure SVG construct geometry and element construction.

Page-level construct grouping and compatibility replay stay in ``render.svg``.
This module owns the geometry for slurs, ties, blocks, and endings. Tuplet
geometry lives in ``tuplets.py``; slur/tie style selection lives in
``slur_style.py``.
"""

from __future__ import annotations

from re_tomato.render.core.elements import SvgElement, _format_reference_number
from re_tomato.render.core.layout_types import LayoutConstruct, LayoutMark, PageMetrics

from ...parser.ast import MusicTokenKind
from .marks import score_text_attrs as _score_text_attrs
from .nested_slurs import endpoint_slur_lift as _endpoint_slur_lift
from .nested_slurs import octave_stack_lift as _octave_stack_lift
from .nested_slurs import slur_stack_anchor as _slur_stack_anchor
from .primitives import attrs as _attrs
from .primitives import text_element as _text_element
from .primitives import use_element as _use_element
from .slur_style import slur_uses_path as _slur_uses_path
from .tuplets import tuplet_elements as _tuplet_elements


def _construct_element(
    construct: LayoutConstruct,
    metrics: PageMetrics | None = None,
    *,
    ending_label: LayoutMark | None = None,
    ending_chain_terminal_end_x: float | None = None,
) -> list[SvgElement]:
    x1 = construct.start.x
    raw_x2 = construct.end.x
    x2 = max(raw_x2, x1 + 12)
    if construct.kind == "slur":
        if construct.start.event.index >= 0 and _path_slur_style(construct, metrics):
            # _slur_path adds nine pixels to its input.  The reference path
            # baseline is ten pixels below the shared note-relative stack
            # anchor, so its input is anchor + one.
            y = _slur_stack_anchor(construct) + 1 + _vertical_offset(
                construct, construct.start.line
            )
            # Reference paths stop one pixel inside each note centerline.
            path_x1 = x1 + 1
            if construct.start.line == construct.end.line and raw_x2 - 1 > path_x1:
                path_x2 = raw_x2 - 1
            else:
                # Retain the legacy fallback for degenerate and cross-row paths.
                path_x2 = max(x2 - 1, path_x1 + 12)
            return [_slur_path(path_x1, y, path_x2, construct)]
        return _endpoint_slur_elements(
            construct,
            x1,
            raw_x2,
            construct.start.y - 16 + _vertical_offset(construct, construct.start.line),
            metrics,
        )
    if construct.kind == "block":
        return _block_construct_elements(construct)
    if construct.kind == "ending":
        return _ending_construct_elements(
            construct,
            ending_label,
            metrics=metrics,
            ending_chain_terminal_end_x=ending_chain_terminal_end_x,
        )
    if construct.kind == "tuplet":
        if construct.lianyinxian_type == "2":
            return _endpoint_slur_elements(
                construct,
                x1,
                raw_x2,
                construct.start.y - 16,
                metrics,
            )
        return _tuplet_elements(construct, metrics)
    x1 += 2
    x2 = max(x2 - 2, x1 + 12)
    y = min(construct.start.y, construct.end.y) - 25
    return [
        SvgElement(
            tag="path",
            layer="construct",
            source_event_index=construct.start.event.index,
            attrs=_attrs(
                (
                    "d",
                    f"M {_format_reference_number(x1)} {_format_reference_number(y + 8)} "
                    f"L {_format_reference_number(x1)} {_format_reference_number(y)} "
                    f"L {_format_reference_number(x2)} {_format_reference_number(y)} "
                    f"L {_format_reference_number(x2)} {_format_reference_number(y + 8)}",
                ),
                ("fill", "none"),
                ("stroke", "#1b1b1b"),
                ("data-construct", construct.kind),
            ),
        )
    ]


def _ending_construct_elements(
    construct: LayoutConstruct,
    label: LayoutMark | None,
    *,
    metrics: PageMetrics | None = None,
    ending_chain_terminal_end_x: float | None = None,
) -> list[SvgElement]:
    # Legacy multi-system voltas expose only their opening and closing row
    # fragments.  Fully interior systems carry semantic span membership but
    # do not serialize an additional horizontal rule.
    if not construct.ending_is_first_segment and not construct.ending_is_last_segment:
        return []
    # A leading-barline opener (``|/[``) puts the left corner six pixels left
    # of the barline; a plain opener puts it two pixels right.
    is_leading_opener = (construct.start.event.code or "").startswith("|n")
    if construct.ending_is_first_segment:
        x1 = construct.start.x - 6 if is_leading_opener else construct.start.x + 2
    else:
        # Continuations open at the row origin, even when a leading reserve
        # shifts the first note. Metrics-free diagnostic callers retain their
        # supplied anchor; normal page rendering always provides page metrics.
        row_origin = metrics.note_start_x if metrics is not None else construct.start.x
        x1 = row_origin - 7
    # A segment that carries the closer stops two pixels short of it; an
    # opening-only segment (the ending continues below) runs one pixel past
    # the row's last event.
    raw_x2 = construct.end.x
    if construct.ending_is_first_segment and not construct.ending_is_last_segment:
        x2 = raw_x2 + 1
    else:
        x2 = max(raw_x2 - 2, x1 + 12)
    # Ending brackets occupy the dedicated ten-pixel row-above-note lane.
    # Keep the top and bottom tied to the host row rather than to the
    # construct's source span or page profile.
    lane_offset = 10 * max(construct.ending_plus_count, 0)
    y = min(construct.start.y, construct.end.y) - 30 - lane_offset
    bottom_y = y + 10
    elements: list[SvgElement] = []
    if (
        ending_chain_terminal_end_x is not None
        and construct.start.line != construct.end.line
        and construct.ending_is_first_segment
        and construct.ending_is_last_segment
        and metrics is not None
    ):
        elements.append(
            _line_element(
                x1=x1,
                y1=bottom_y,
                x2=x1,
                y2=y,
                source_event_index=construct.start.event.index,
                construct_ids=construct.start.event.construct_ids,
            )
        )
        elements.append(
            _line_element(
                x1=x1,
                y1=y,
                x2=ending_chain_terminal_end_x,
                y2=y,
                source_event_index=construct.start.event.index,
                construct_ids=construct.start.event.construct_ids,
            )
        )
        final_x1 = metrics.note_start_x - 7
        final_y = construct.end.y - 30 - lane_offset
        final_x2 = max(raw_x2 - 2, final_x1 + 12)
        elements.append(
            _line_element(
                x1=final_x1,
                y1=final_y,
                x2=final_x2,
                y2=final_y,
                source_event_index=construct.start.event.index,
                construct_ids=construct.start.event.construct_ids,
            )
        )
        elements.append(
            _line_element(
                x1=final_x2,
                y1=final_y + 10,
                x2=final_x2,
                y2=final_y,
                source_event_index=construct.start.event.index,
                construct_ids=construct.start.event.construct_ids,
            )
        )
        if label is not None:
            elements.extend(_ending_label_element(label))
        return elements
    if construct.ending_is_first_segment:
        elements.append(
            _line_element(
                x1=x1,
                y1=bottom_y,
                x2=x1,
                y2=y,
                source_event_index=construct.start.event.index,
                construct_ids=construct.start.event.construct_ids,
            )
        )
    elements.append(
        _line_element(
            x1=x1,
            y1=y,
            x2=x2,
            y2=y,
            source_event_index=construct.start.event.index,
            construct_ids=construct.start.event.construct_ids,
        )
    )
    # The right corner is drawn only when the segment carries an explicit
    # bracket close; a ``|]/`` closer (slash after the bracket) leaves the
    # frame open on the right.
    if construct.ending_is_last_segment and construct.ending_explicit_close:
        elements.append(
            _line_element(
                x1=x2,
                y1=bottom_y,
                x2=x2,
                y2=y,
                source_event_index=construct.start.event.index,
                construct_ids=construct.start.event.construct_ids,
            )
        )
    if label is not None:
        elements.extend(_ending_label_element(label))
    return elements


def _line_element(
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    source_event_index: int | None,
    construct_ids: tuple[str, ...] = (),
    data_construct: str | None = None,
    stroke_width: int = 1,
) -> SvgElement:
    attrs = [
        ("x1", _format_reference_number(x1)),
        ("y1", _format_reference_number(y1)),
        ("x2", _format_reference_number(x2)),
        ("y2", _format_reference_number(y2)),
        ("stroke-width", str(stroke_width)),
        ("stroke", "#1b1b1b"),
        ("fill", "none"),
    ]
    if data_construct is not None:
        attrs.append(("data-construct", data_construct))
    return SvgElement(
        tag="line",
        layer="construct",
        source_event_index=source_event_index,
        construct_ids=construct_ids,
        attrs=_attrs(*attrs),
    )


def _ending_label_element(mark: LayoutMark) -> list[SvgElement]:
    event = mark.event
    text = event.value or event.raw.strip('"')
    # A leading-barline opener (``|/[``) anchors the label eight pixels left
    # of a plain opener's anchor, matching its shifted bracket corner.
    is_leading_opener = (mark.host.event.code or "").startswith("|n")
    label_x = mark.host.x - 3 if is_leading_opener else mark.host.x + 5
    return [
        _text_element(
            x=_format_reference_number(label_x),
            y=_format_reference_number(
                mark.host.y - 20 - 10 * max(mark.ending_plus_count, 0)
            ),
            text=text,
            layer="mark",
            source_event_index=event.index,
            construct_ids=event.construct_ids,
            extra_attrs=_score_text_attrs(4.026),
        )
    ]


def _block_construct_elements(construct: LayoutConstruct) -> list[SvgElement]:
    # A ``{bz ...}`` block carries no frame of its own.  Its raised bian notes
    # and any attached ``zkh``/octave accessories are emitted by the event and
    # accessory streams; the authoritative corpus has no rectangle for the
    # hidden alternate span.
    if construct.start.block in {"bz", "bz-hidden"}:
        return []
    y = min(construct.start.y, construct.end.y) - 25
    elements = [
        _use_element(
            "dakuohu_zuo_2",
            x=_format_reference_number(construct.start.x),
            y=_format_reference_number(y),
            layer="construct",
            source_event_index=construct.start.event.index,
            extra_attrs=(("data-construct", "block"),),
        )
    ]
    return elements


def _path_slur_style(
    construct: LayoutConstruct,
    metrics: PageMetrics | None = None,
) -> bool:
    # Keep the private signature compatible with existing internal callers;
    # page metrics and source text are not style inputs.
    del metrics
    return _slur_uses_path(construct)


def _slur_path(x1: float, y: float, x2: float, construct: LayoutConstruct) -> SvgElement:
    base_y = y + 9
    span = x2 - x1
    control_offset = 0.3 * span - 0.4
    number = _format_reference_number
    return SvgElement(
        tag="path",
        layer="construct",
        source_event_index=construct.start.event.index,
        attrs=_attrs(
            (
                "d",
                f"M {number(x1)},{number(base_y)} "
                f"C {number(x1 + control_offset)},{number(base_y - 10)},"
                f"{number(x2 - control_offset)},{number(base_y - 10)},"
                f"{number(x2)},{number(base_y)} "
                f"M {number(x2)},{number(base_y)} "
                f"C  {number(x2 - control_offset)},{number(base_y - 9)},"
                f"{number(x1 + control_offset)},{number(base_y - 9)},"
                f"{number(x1)},{number(base_y)}",
            ),
            ("stroke-width", "0.5"),
            ("stroke", "#1b1b1b"),
            ("data-construct", "tuplet" if construct.kind == "tuplet" else "slur"),
        ),
        construct_ids=construct.start.event.construct_ids,
    )


def _endpoint_slur_elements(
    construct: LayoutConstruct,
    x1: float,
    x2: float,
    y: float,
    metrics: PageMetrics | None,
) -> list[SvgElement]:
    left_x = _endpoint_slur_anchor_x(x1, direction="left")
    right_x = _endpoint_slur_anchor_x(x2, direction="right")
    start_y = _endpoint_slur_anchor_y(
        construct.start.y
        + _vertical_offset(construct, construct.start.line)
        - _endpoint_slur_lift(construct.start.event),
        construct.start.event.octave,
    )
    if construct.start.line == construct.end.line:
        end_y = _endpoint_slur_anchor_y(
            construct.end.y
            + _vertical_offset(construct, construct.end.line)
            - _endpoint_slur_lift(construct.end.event),
            construct.end.event.octave,
        )
        shared_y = min(start_y, end_y)
        y_use = shared_y + 0.05
        connector_y = shared_y + 0.8
        start_barline = construct.start.event.kind == MusicTokenKind.BARLINE
        end_barline = construct.end.event.kind == MusicTokenKind.BARLINE
        elements: list[SvgElement] = []
        if not start_barline:
            elements.append(
                _use_element(
                    "lianyinxian_zuo",
                    x=_format_reference_number(left_x),
                    y=_format_reference_number(y_use),
                    layer="construct",
                    source_event_index=construct.start.event.index,
                )
            )
        if not end_barline:
            elements.append(
                _use_element(
                    "lianyinxian_you",
                    x=_format_reference_number(right_x),
                    y=_format_reference_number(y_use),
                    layer="construct",
                    source_event_index=construct.start.event.index,
                )
            )
        line_x1 = x1 + 6.8 if start_barline else left_x + 0.8
        line_x2 = x2 - 5.0 if end_barline else right_x + 1.0
        elements.append(
            _plain_construct_line(line_x1, connector_y, line_x2, connector_y, construct)
        )
        return elements

    y_use = start_y + 0.05
    y_line = start_y + 0.8
    left_edge = float(metrics.note_start_x if metrics is not None else min(x1, x2))
    right_edge = float(
        metrics.width - metrics.margin_right - 2 if metrics is not None else max(x1, x2)
    )
    end_y = _endpoint_slur_anchor_y(
        construct.end.y
        + _vertical_offset(construct, construct.end.line)
        - _endpoint_slur_lift(construct.end.event),
        construct.end.event.octave,
    )
    end_y_use = end_y + 0.05
    end_y_line = end_y + 0.8
    return [
        _use_element(
            "lianyinxian_zuo",
            x=_format_reference_number(left_x),
            y=_format_reference_number(y_use),
            layer="construct",
            source_event_index=construct.start.event.index,
        ),
        _plain_construct_line(left_x + 0.8, y_line, right_edge, y_line, construct),
        _use_element(
            "lianyinxian_you",
            x=_format_reference_number(right_x),
            y=_format_reference_number(end_y_use),
            layer="construct",
            source_event_index=construct.start.event.index,
        ),
        _plain_construct_line(left_edge, end_y_line, right_x + 1.0, end_y_line, construct),
    ]


def _endpoint_slur_anchor_y(note_y: float, octave: int) -> float:
    return note_y - _octave_stack_lift(octave)


def _endpoint_slur_anchor_x(note_x: float, *, direction: str) -> float:
    return note_x + 12 if direction == "left" else note_x - 12


def _vertical_offset(construct: LayoutConstruct, line: int) -> float:
    return construct.row_vertical_offsets.get(line, construct.vertical_offset)




def _plain_construct_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    construct: LayoutConstruct,
) -> SvgElement:
    return SvgElement(
        tag="line",
        layer="construct",
        source_event_index=construct.start.event.index,
        attrs=_attrs(
            ("x1", _format_reference_number(x1)),
            ("y1", _format_reference_number(y1)),
            ("x2", _format_reference_number(x2)),
            ("y2", _format_reference_number(y2)),
            ("stroke-width", "1.2"),
            ("stroke", "#1b1b1b"),
            ("fill", "none"),
        ),
    )


__all__ = [
    "_block_construct_elements",
    "_construct_element",
    "_endpoint_slur_anchor_x",
    "_endpoint_slur_anchor_y",
    "_endpoint_slur_elements",
    "_ending_construct_elements",
    "_ending_label_element",
    "_line_element",
    "_path_slur_style",
    "_plain_construct_line",
    "_slur_path",
]
