"""Semantic-construct projection into layout objects."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from octopus.normalization.types import MusicEvent, SemanticConstruct
from octopus.render.core.layout_types import (
    LayoutConstruct,
    LayoutEvent,
    LayoutGrace,
    LayoutHairpinMark,
    LayoutMark,
    LayoutPage,
)

from ...parser.ast import MusicTokenKind
from ..svg_engine.slur_style import slur_uses_path as _slur_uses_path
from .parenthesis_chains import project_parenthesis_chains


def collect_constructs(
    layout: LayoutPage,
    constructs: tuple[SemanticConstruct, ...],
    source_events: tuple[MusicEvent, ...],
    laid_out: list[LayoutEvent],
    hidden_events: list[LayoutEvent],
) -> None:
    by_index = {item.event.index: item for item in [*laid_out, *hidden_events]}
    source_by_index = {event.index: event for event in source_events}
    if layout.metrics.lianyinxian_type != "2":
        constructs = project_parenthesis_chains(constructs, source_events, by_index)
    brackets = tuple(construct for construct in constructs if construct.kind == "bracket")
    for block in (construct for construct in constructs if construct.kind == "block"):
        _collect_block(layout, block, by_index, laid_out)

    for construct in constructs:
        if construct.render_suppressed:
            # Middle member of a shared-endpoint chain displaced by an
            # EOL-dangling outer span: the model keeps it for role and
            # signature stability, but layout (lanes, emission) must not see
            # it — the reference engraver never draws it.
            continue
        if construct.kind in {"tie", "slur", "tuplet", "bracket"}:
            _collect_line_construct(layout, construct, by_index)
        elif construct.kind == "grace" and construct.host_event_index is not None:
            _collect_grace(layout, construct, by_index, source_by_index)
        elif construct.kind in {"annotation", "decoration"}:
            _collect_mark(layout, construct, brackets, by_index, source_by_index)
        elif construct.kind == "modifier" and construct.value in {"<", ">"}:
            _collect_hairpin_mark(
                layout,
                construct,
                constructs,
                by_index,
                source_events,
                laid_out,
            )


def _collect_block(
    layout: LayoutPage,
    block: SemanticConstruct,
    by_index: dict[int, LayoutEvent],
    laid_out: list[LayoutEvent],
) -> None:
    block_name = block.value or "dsb"
    block_count = 0
    for event_index in block.event_indices:
        item = by_index.get(event_index)
        if item is None:
            continue
        if item.event.kind != MusicTokenKind.BARLINE:
            block_count += 1
        if item.block not in {"bz-hidden", "dsb-hidden", "dsb-hidden-tail"}:
            item.block = block_name
            item.block_index = block_count
    tail = first_barline_after(block.end_event_index, laid_out)
    if tail is not None:
        tail.block = f"{block_name}-tail"
    start = by_index.get(block.start_event_index) if block.start_event_index is not None else None
    end = (
        by_index.get(block.end_event_index) if block.end_event_index is not None else None
    ) or tail
    if (
        end is not None
        and end.block == "bz-hidden"
        and end.event.kind == MusicTokenKind.BARLINE
        and tail is not None
    ):
        end = tail
    if start is not None and end is not None:
        layout.constructs.append(
            LayoutConstruct(
                "block",
                start,
                end,
                layout.metrics.lianyinxian_type,
                construct_id=block.construct_id,
            )
        )


def _collect_line_construct(
    layout: LayoutPage,
    construct: SemanticConstruct,
    by_index: dict[int, LayoutEvent],
) -> None:
    logical_start = (
        by_index.get(construct.start_event_index)
        if construct.start_event_index is not None
        else None
    )
    logical_end = (
        by_index.get(construct.end_event_index)
        if construct.end_event_index is not None
        else None
    )
    if logical_start is None or logical_end is None:
        return
    visual_start_index = construct.visual_start_event_index
    visual_end_index = construct.visual_end_event_index
    start = (
        by_index.get(visual_start_index)
        if visual_start_index is not None
        else None
    )
    if start is None:
        start = logical_start
    end = (
        by_index.get(visual_end_index)
        if visual_end_index is not None
        else None
    )
    if end is None:
        end = logical_end
    kind = "ending" if construct.kind == "bracket" else (
        "slur" if construct.kind == "tie" else construct.kind
    )
    layout_construct = LayoutConstruct(
        kind,
        start,
        end,
        layout.metrics.lianyinxian_type,
        source_kind=construct.kind,
        source_text=construct.source_text,
        construct_id=construct.construct_id,
        logical_start=logical_start,
        logical_end=logical_end,
        visual_only=construct.visual_only,
        semantic_parent_id=construct.semantic_parent_id,
        visual_start_event_index=construct.visual_start_event_index,
        visual_end_event_index=construct.visual_end_event_index,
        ending_plus_count=construct.ending_plus_count,
        ending_is_first_segment=construct.ending_is_first_segment,
        ending_is_last_segment=construct.ending_is_last_segment,
        ending_explicit_close=construct.ending_explicit_close,
        ending_reserves_clearance=construct.ending_reserves_clearance,
        inside_dangling_span=construct.inside_dangling_span,
    )
    layout.constructs.append(layout_construct)


def retarget_unresolved_endpoint_starts(layout: LayoutPage) -> None:
    """Repair endpoint starts after the final shared-grid coordinates settle."""

    layout.constructs[:] = [
        _retarget_unresolved_endpoint_start(layout, construct, layout.events)
        for construct in layout.constructs
    ]


def _retarget_unresolved_endpoint_start(
    layout: LayoutPage,
    construct: LayoutConstruct,
    laid_out: list[LayoutEvent],
) -> LayoutConstruct:
    """Use the first content note for a later endpoint of an open outer span."""

    if construct.source_kind != "slur" or _slur_uses_path(construct):
        return construct
    source_line = construct.start.event.span.start.line
    source_voice = layout.source_voice_by_line.get(source_line)
    if source_voice is None:
        return construct
    for state in layout.unresolved_span_states:
        if (
            state.page_index != layout.page_index
            or state.family != "span"
            or state.source_voice != source_voice
            or state.source_span.start.line != source_line
            or construct.start.event.span.start.offset <= state.source_span.start.offset
        ):
            continue
        has_prior_path = any(
            item.start.event.span.start.line == source_line
            and state.source_span.start.offset < item.start.event.span.start.offset
            < construct.start.event.span.start.offset
            and _slur_uses_path(item)
            for item in layout.constructs
        )
        if not has_prior_path:
            continue
        anchor = next(
            (
                item
                for item in laid_out
                if item.event.span.start.line == source_line
                and item.event.span.start.offset > state.source_span.end.offset
                and item.event.kind
                in {
                    MusicTokenKind.NOTE,
                    MusicTokenKind.REST,
                    MusicTokenKind.RHYTHM_NOTE,
                    MusicTokenKind.HIDDEN_REST,
                    MusicTokenKind.BARLINE,
                    MusicTokenKind.EXTENSION,
                }
            ),
            None,
        )
        if anchor is not None:
            return replace(construct, start=anchor)
    return construct


def _attach_hairpin_modifier(
    construct: SemanticConstruct,
    by_index: dict[int, LayoutEvent],
) -> None:
    """Record a standalone ``<``/``>`` modifier on its host event.

    Hairpins that open after a paren group closes — ``(3' 2')<`` or
    ``(6, - | 6,)>`` — lex as a separate MODIFIER token rather than as part
    of the host note's raw.  The renderer needs the direction to emit the
    wedge (see ``svg_engine.duration_lines``).
    """

    value = construct.value or ""
    if "<" not in value and ">" not in value:
        return
    host = (
        by_index.get(construct.host_event_index)
        if construct.host_event_index is not None
        else None
    )
    if host is not None:
        host.hairpin_opener = "<" if "<" in value else ">"


def _collect_grace(
    layout: LayoutPage,
    construct: SemanticConstruct,
    by_index: dict[int, LayoutEvent],
    source_by_index: dict[int, MusicEvent],
) -> None:
    host = (
        by_index.get(construct.host_event_index)
        if construct.host_event_index is not None
        else None
    )
    event = _source_event_for_construct(source_by_index, construct)
    if host is not None and event is not None:
        layout.graces.append(LayoutGrace(host, event.raw, event.children))


def _collect_mark(
    layout: LayoutPage,
    construct: SemanticConstruct,
    brackets: Iterable[SemanticConstruct],
    by_index: dict[int, LayoutEvent],
    source_by_index: dict[int, MusicEvent],
) -> None:
    host = (
        by_index.get(construct.host_event_index)
        if construct.host_event_index is not None
        else None
    )
    event = _mark_event_for_construct(source_by_index, construct)
    if host is None or event is None:
        return
    label_bracket = (
        _ending_label_bracket(construct, brackets, source_by_index)
        if event.kind == MusicTokenKind.ANNOTATION
        else None
    )
    if label_bracket is not None:
        bracket_host = (
            by_index.get(label_bracket.start_event_index)
            if label_bracket.start_event_index is not None
            else None
        )
        if bracket_host is not None:
            layout.marks.append(
                LayoutMark(
                    bracket_host,
                    event,
                    "ending-label",
                    ending_plus_count=label_bracket.ending_plus_count,
                )
            )
            return
    layout.marks.append(
        LayoutMark(
            host,
            event,
            "above",
            starts_upper_span=_mark_starts_upper_span(
                construct,
                tuple(sorted(source_by_index.values(), key=lambda item: item.index)),
            ),
        )
    )


def _collect_hairpin_mark(
    layout: LayoutPage,
    construct: SemanticConstruct,
    constructs: tuple[SemanticConstruct, ...],
    by_index: dict[int, LayoutEvent],
    source_events: tuple[MusicEvent, ...],
    laid_out: list[LayoutEvent],
) -> None:
    """Project standalone source hairpin modifiers into visual row metadata."""

    if construct.host_event_index is None or construct.start_event_index is None:
        return
    host = by_index.get(construct.host_event_index)
    marker = source_events_by_index(source_events).get(construct.start_event_index)
    if host is None or marker is None or construct.value not in {"<", ">"}:
        return
    if construct.value == ">":
        boundary = next(
            (
                item
                for item in sorted(
                    laid_out,
                    key=lambda candidate: (
                        candidate.slot,
                        candidate.x,
                        candidate.event.index,
                    ),
                )
                if item.event.index > marker.index
            ),
            None,
        )
    else:
        boundary = _opening_hairpin_boundary(
            host,
            marker,
            constructs,
            by_index,
            source_events,
        )
    if boundary is not None:
        layout.hairpin_marks.append(LayoutHairpinMark(host, construct.value, boundary))


def _opening_hairpin_boundary(
    host: LayoutEvent,
    marker: MusicEvent,
    constructs: tuple[SemanticConstruct, ...],
    by_index: dict[int, LayoutEvent],
    source_events: tuple[MusicEvent, ...],
) -> LayoutEvent | None:
    """Find the source-owned endpoint for a detached opening modifier."""

    closing_event = next(
        (
            event
            for event in source_events
            if event.index > marker.index and ">" in event.raw
        ),
        None,
    )
    if closing_event is not None:
        previous = next(
            (
                event
                for event in reversed(source_events)
                if (
                    event.index < closing_event.index
                    and event.index in by_index
                    and event.kind != MusicTokenKind.BARLINE
                )
            ),
            None,
        )
        if previous is not None:
            return by_index[previous.index]

    enclosing = [
        candidate
        for candidate in constructs
        if candidate.kind in {"tie", "slur"}
        and candidate.semantic_parent_id is None
        and candidate.start_event_index is not None
        and candidate.end_event_index is not None
        and candidate.start_event_index <= marker.index < candidate.end_event_index
    ]
    if not enclosing:
        return None
    end_index = max(
        candidate.end_event_index
        for candidate in enclosing
        if candidate.end_event_index is not None
    )
    if end_index == host.event.index:
        return None
    return by_index.get(end_index)


def source_events_by_index(source_events: tuple[MusicEvent, ...]) -> dict[int, MusicEvent]:
    return {event.index: event for event in source_events}


def _mark_starts_upper_span(
    construct: SemanticConstruct,
    source_events: tuple[MusicEvent, ...],
) -> bool:
    """Whether a mark's host is immediately followed by a span opener.

    A modifier such as ``1(.&f`` is represented by a note, a separate
    ``SPAN_START`` event, and then a modifier construct.  The host note cannot
    carry a slur role in this form, so preserve the semantic opener while
    projecting the modifier into a ``LayoutMark``.
    """

    host_index = construct.host_event_index
    mark_index = construct.start_event_index
    if host_index is None or mark_index is None or mark_index <= host_index:
        return False
    return any(
        event.kind == MusicTokenKind.SPAN_START
        for event in source_events
        if host_index < event.index < mark_index
    )


def first_barline_after(
    event_index: int | None,
    laid_out: list[LayoutEvent],
) -> LayoutEvent | None:
    if event_index is None:
        return None
    return next(
        (
            item
            for item in laid_out
            if item.event.index > event_index and item.event.kind == MusicTokenKind.BARLINE
        ),
        None,
    )


def _source_event_for_construct(
    source_by_index: dict[int, MusicEvent],
    construct: SemanticConstruct,
) -> MusicEvent | None:
    if construct.start_event_index is None:
        return None
    return source_by_index.get(construct.start_event_index)


def _mark_event_for_construct(
    source_by_index: dict[int, MusicEvent],
    construct: SemanticConstruct,
) -> MusicEvent | None:
    event = _source_event_for_construct(source_by_index, construct)
    if event is None or event.kind != MusicTokenKind.GRACE_GROUP:
        return event
    kind = {
        "annotation": MusicTokenKind.ANNOTATION,
        "decoration": MusicTokenKind.DECORATION,
    }.get(construct.kind)
    if kind is None:
        return event
    value = construct.value or event.value or event.raw
    return replace(event, kind=kind, raw=value, value=value, code=value, render_code=value)


def _ending_label_bracket(
    annotation: SemanticConstruct,
    brackets: Iterable[SemanticConstruct],
    source_by_index: dict[int, MusicEvent],
) -> SemanticConstruct | None:
    for bracket in brackets:
        if not (
            bracket.source_span.start.offset <= annotation.source_span.start.offset
            and annotation.source_span.end.offset <= bracket.source_span.end.offset
        ):
            continue
        first_visible = _first_event_after_bracket_start(bracket, source_by_index)
        if (
            first_visible is not None
            and annotation.source_span.end.offset <= first_visible.span.start.offset
        ):
            return bracket
    return None


def _first_event_after_bracket_start(
    bracket: SemanticConstruct,
    source_by_index: dict[int, MusicEvent],
) -> MusicEvent | None:
    events = [
        event
        for event_index in bracket.event_indices
        if (event := source_by_index.get(event_index)) is not None
        and event.span.start.offset > bracket.source_span.start.offset
    ]
    return min(events, key=lambda event: event.span.start.offset, default=None)
