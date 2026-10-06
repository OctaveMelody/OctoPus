"""Emit semantic constructs through the renderer's ordered compatibility stream."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from octopus.render.core.elements import SvgElement, _format_reference_number
from octopus.render.core.layout_types import (
    LayoutConstruct,
    LayoutEvent,
    LayoutMark,
    LayoutPage,
    LayoutVoiceBrace,
)

from ...parser.ast import MusicTokenKind
from ..core.layout_widths import NOTE_WIDTH
from ..core.source_timing import duration_fraction, project_source_onset, source_onsets
from .construct_emission import late_construct_emission_plan
from .constructs import _construct_element, _ending_label_element, _line_element
from .event_policy import dsb_close_barline as _dsb_close_barline
from .nested_slurs import resolve_nested_slur_lanes
from .primitives import text_element as _text_element
from .primitives import use_element as _use_element

_DSB_CLOSE_BRACE_BARLINE_CLEARANCE = 8.0


def _construct_elements(layout: LayoutPage) -> list[SvgElement]:
    elements: list[SvgElement] = []
    for construct in layout.constructs:
        elements.extend(_construct_element(construct, layout.metrics))
    return elements


def _early_construct_elements(layout: LayoutPage) -> list[SvgElement]:
    elements: list[SvgElement] = []
    for construct in layout.constructs:
        if construct.kind == "block":
            if construct.start.block in {"bz", "bz-hidden"}:
                elements.extend(
                    _construct_element(construct, layout.metrics)
                )
    elements.extend(_voice_caption_elements(layout))
    for brace in layout.voice_braces:
        elements.extend(_voice_brace_elements(brace))
    return elements


def _late_construct_elements(layout: LayoutPage) -> list[SvgElement]:
    resolved_constructs = resolve_nested_slur_lanes(layout)
    rendered: list[tuple[LayoutConstruct, list[SvgElement]]] = []
    plan = late_construct_emission_plan(layout, constructs=resolved_constructs)
    for emission in plan.late:
        construct = emission.construct
        rendered.append(
            (
                construct,
                _construct_element(construct, layout.metrics),
            )
        )
    elements = _legacy_late_construct_replay_elements(layout, rendered)
    return elements


def _legacy_late_construct_replay_elements(
    layout: LayoutPage,
    rendered: list[tuple[LayoutConstruct, list[SvgElement]]],
) -> list[SvgElement]:
    ordered_constructs = _legacy_replayed_construct_order(layout, rendered)
    elements_by_construct = {
        id(construct): item_elements for construct, item_elements in rendered
    }
    return [
        element
        for construct in ordered_constructs
        for element in elements_by_construct[id(construct)]
    ]


def _slur_row_sort_key(construct: LayoutConstruct) -> tuple[float, float, float]:
    # Rows ascend by y; within a row the reference orders ties by
    # (start.x, end.x), which places a nested outer tie directly after its
    # first inner child.
    return (construct.start.y, construct.start.x, construct.end.x)


def _slur_row_base_ys(layout: LayoutPage) -> dict[tuple[int, int], float]:
    """Return the topmost visible y coordinate for each visual row."""
    base: dict[tuple[int, int], float] = {}
    for item in layout.events:
        key = (item.voice, item.line)
        base[key] = min(base.get(key, item.y), item.y)
    return base


def _batch_slur_row_sort_key(
    construct: LayoutConstruct,
    children_by_parent: dict[str, list[LayoutConstruct]],
    row_base_ys: dict[tuple[int, int], float],
) -> tuple[float, float, float, int]:
    """Sort stacked DSB rows by their shared base and preserve dangling-span order."""
    row_y = row_base_ys.get(
        (construct.start.voice, construct.start.line), construct.start.y
    )
    children = [
        child
        for child in children_by_parent.get(construct.construct_id or "", ())
        if child.start.y == construct.start.y
    ]
    if construct.inside_dangling_span and children:
        return row_y, min(child.start.x for child in children), construct.end.x, 1
    return row_y, construct.start.x, construct.end.x, 0


def _legacy_replayed_construct_order(
    layout: LayoutPage,
    rendered: list[tuple[LayoutConstruct, list[SvgElement]]],
) -> list[LayoutConstruct]:
    semantic = _source_voice_path_replay(layout, rendered)
    if semantic is not None:
        return semantic
    return _cumulative_source_voice_replay(layout, rendered)


def _cumulative_source_voice_replay(
    layout: LayoutPage,
    rendered: list[tuple[LayoutConstruct, list[SvgElement]]],
) -> list[LayoutConstruct]:
    """Replay late constructs in cumulative source-voice batches.

    Hidden-row constructs occur once at the front. Visible constructs are grouped by
    parsed source voice, sorted within each batch by row and anchor geometry, and
    cumulatively replayed in row order.
    """
    hidden_ids = {id(event) for event in layout.hidden_events}
    hidden_constructs = sorted(
        (construct for construct, _ in rendered if id(construct.start) in hidden_ids),
        key=_source_voice_replay_sort_key,
    )
    batches: dict[int, list[LayoutConstruct]] = {}
    for construct, _ in rendered:
        if id(construct.start) in hidden_ids:
            continue
        source_line = construct.start.event.span.start.line
        source_voice = max(1, layout.source_voice_by_line.get(source_line, 0))
        batches.setdefault(source_voice, []).append(construct)

    ordered_batches = sorted(
        batches.values(), key=lambda items: min(construct.start.y for construct in items)
    )
    row_base_ys = _slur_row_base_ys(layout)

    for batch in ordered_batches:
        children_by_parent: dict[str, list[LayoutConstruct]] = {}
        for construct in batch:
            if construct.semantic_parent_id is not None:
                children_by_parent.setdefault(construct.semantic_parent_id, []).append(
                    construct
                )
        batch.sort(
            key=lambda construct: _batch_slur_row_sort_key(
                construct, children_by_parent, row_base_ys
            )
        )

    replayed = list(hidden_constructs)
    for end in range(1, len(ordered_batches) + 1):
        for batch in ordered_batches[:end]:
            replayed.extend(batch)
    return replayed


def _source_voice_path_replay(
    layout: LayoutPage,
    rendered: list[tuple[LayoutConstruct, list[SvgElement]]],
) -> list[LayoutConstruct] | None:
    """Replay eligible late slurs by first tie-bearing source voice.

    Return None for unverified topologies so their existing replay remains intact.
    Source declaration identity is parser-owned; layout voice indices are not stable
    across systems. Endpoint and visual-only constructs use the same ordinary stream;
    DSB-owned constructs remain one-pass before it. A verified parallel DSB child
    topology can also preserve a same-row shared-end child before its endpoint
    parent. See the E6a2, E9a, and E11g controls.
    """
    if not rendered or not layout.source_voice_by_line:
        return None
    ordinary: list[tuple[LayoutConstruct, list[SvgElement]]] = []
    single_pass: list[LayoutConstruct] = []
    for construct, elements in rendered:
        if _source_voice_replay_item_is_eligible(layout, construct, elements):
            ordinary.append((construct, elements))
        elif _source_voice_replay_dsb_item_is_eligible(layout, construct, elements):
            single_pass.append(construct)
        else:
            return None
    if not ordinary:
        return None
    groups: dict[int, list[LayoutConstruct]] = {}
    first_source_line: dict[int, int] = {}
    endpoint_construct_ids = {
        construct.construct_id
        for construct, elements in ordinary
        if construct.construct_id is not None
        and _construct_elements_are_endpoint_slurs(elements)
    }
    for construct, _ in ordinary:
        source_line = construct.start.event.span.start.line
        voice = layout.source_voice_by_line[source_line]
        groups.setdefault(voice, []).append(construct)
        first_source_line[voice] = min(first_source_line.get(voice, source_line), source_line)
    if len(groups) < 2:
        return None
    single_pass.sort(key=_source_voice_replay_sort_key)
    source_kinds_by_line: dict[int, set[str | None]] = {}
    for construct in single_pass:
        source_kinds_by_line.setdefault(
            construct.start.event.span.start.line, set()
        ).add(construct.source_kind)
    source_order_lines = {
        source_line
        for source_line, source_kinds in source_kinds_by_line.items()
        if len(source_kinds) == 1
    }
    # Source-owned snapshots retain source-occurrence bucket order. Within
    # each bucket, the reference uses visual row and anchor order.
    for bucket in groups.values():
        if source_order_lines.intersection(
            construct.start.event.span.start.line for construct in bucket
        ):
            _order_dsb_source_line_constructs(bucket, source_order_lines)
        else:
            bucket.sort(key=_source_voice_replay_sort_key)
        if _source_voice_replay_has_parallel_dsb_children(single_pass):
            _move_shared_end_children_before_endpoint_parents(
                bucket,
                endpoint_construct_ids,
            )
    buckets = [
        groups[voice]
        for voice in sorted(groups, key=lambda item: first_source_line[item])
    ]
    replayed = [
        construct
        for end in range(1, len(buckets) + 1)
        for bucket in buckets[:end]
        for construct in bucket
    ]
    return [*single_pass, *replayed]


def _source_voice_replay_sort_key(
    construct: LayoutConstruct,
) -> tuple[float, float, float]:
    """Return the stable visual order used inside one source replay bucket."""
    return construct.start.y, construct.start.x, construct.end.x


def _order_dsb_source_line_constructs(
    bucket: list[LayoutConstruct],
    source_order_lines: set[int],
) -> None:
    """Keep DSB-sharing source lines ordered without changing other rows."""
    by_line: dict[int, tuple[int, list[LayoutConstruct]]] = {}
    for index, construct in enumerate(bucket):
        source_line = construct.start.event.span.start.line
        by_line.setdefault(source_line, (index, []))[1].append(construct)
    for source_line, (_index, constructs) in by_line.items():
        if source_line not in source_order_lines:
            constructs.sort(key=_source_voice_replay_sort_key)
    bucket[:] = [
        construct
        for _index, constructs in sorted(
            by_line.values(),
            key=lambda item: (
                min(_source_voice_replay_sort_key(construct) for construct in item[1]),
                item[0],
            ),
        )
        for construct in constructs
    ]


def _source_voice_replay_has_parallel_dsb_children(
    single_pass: list[LayoutConstruct],
) -> bool:
    """Return whether DSB replay includes source-owned child constructs."""
    return any(construct.semantic_parent_id is not None for construct in single_pass)


def _move_shared_end_children_before_endpoint_parents(
    bucket: list[LayoutConstruct],
    endpoint_construct_ids: set[str],
) -> None:
    """Keep same-row shared-end child paths before their endpoint parent."""
    for child in tuple(bucket):
        parent_id = child.semantic_parent_id
        if parent_id not in endpoint_construct_ids:
            continue
        parent = next(
            (construct for construct in bucket if construct.construct_id == parent_id),
            None,
        )
        if parent is None:
            continue
        if sum(
            construct.semantic_parent_id == parent_id for construct in bucket
        ) != 1:
            continue
        if (
            child.start.y != parent.start.y
            or child.end.event.index != parent.end.event.index
        ):
            continue
        child_index = bucket.index(child)
        parent_index = bucket.index(parent)
        if child_index > parent_index:
            bucket.pop(child_index)
            bucket.insert(parent_index, child)


def _source_voice_replay_item_is_eligible(
    layout: LayoutPage,
    construct: LayoutConstruct,
    elements: list[SvgElement],
) -> bool:
    """Return whether one ordinary late construct can join source-owned replay."""
    if _construct_is_dsb_owned(construct):
        return False
    if construct.kind == "tuplet" and not _construct_elements_are_tuplet(elements):
        return False
    return _source_voice_replay_topology_is_eligible(layout, construct, elements)


def _source_voice_replay_topology_is_eligible(
    layout: LayoutPage,
    construct: LayoutConstruct,
    elements: list[SvgElement],
) -> bool:
    """Return whether a late slur has the verified page-local topology."""
    start, end = construct.start, construct.end
    if construct.kind == "tuplet":
        if not _construct_elements_are_tuplet(elements):
            return False
    elif construct.kind == "slur" and construct.source_kind in {"tie", "slur"}:
        if not _construct_elements_are_replayable_slurs(elements):
            return False
    else:
        return False
    if (start.page_index, start.voice, start.line) != (end.page_index, end.voice, end.line):
        return False
    if start.event.span.start.line != end.event.span.start.line:
        return False
    if start.event.span.start.line not in layout.source_voice_by_line:
        return False
    return all(
        logical is None
        or (logical.page_index, logical.event.span.start.line)
        == (start.page_index, start.event.span.start.line)
        for logical in (construct.logical_start, construct.logical_end)
    )


def _construct_is_dsb_owned(construct: LayoutConstruct) -> bool:
    """Return whether a slur is owned by a DSB hidden/block stream."""
    return any(
        block in {"dsb", "dsb-hidden"}
        for block in (construct.start.block, construct.end.block)
    )


def _source_voice_replay_dsb_item_is_eligible(
    layout: LayoutPage,
    construct: LayoutConstruct,
    elements: list[SvgElement],
) -> bool:
    """Return whether a DSB construct is safe to emit once before replay."""
    if not _construct_is_dsb_owned(construct):
        return False
    return _source_voice_replay_topology_is_eligible(layout, construct, elements)


def _construct_elements_are_slur_paths(elements: list[SvgElement]) -> bool:
    return bool(elements) and all(
        element.tag == "path" and dict(element.attrs).get("data-construct") == "slur"
        for element in elements
    )


def _construct_elements_are_tuplet(elements: list[SvgElement]) -> bool:
    """Return whether elements are the verified visible three-event tuplet pair."""
    if len(elements) != 2 or elements[0].tag != "path" or elements[1].tag != "use":
        return False
    href = dict(elements[1].attrs).get("href") or dict(elements[1].attrs).get("xlink:href")
    return href == "#lianyin_shuzi_3"


def _construct_elements_are_replayable_slurs(elements: list[SvgElement]) -> bool:
    """Return whether a construct is an ordinary path or endpoint slur stream."""
    return _construct_elements_are_slur_paths(elements) or _construct_elements_are_endpoint_slurs(
        elements
    )


def _construct_elements_are_endpoint_slurs(elements: list[SvgElement]) -> bool:
    """Return whether elements form one complete renderer endpoint-slur stream."""
    glyphs = [
        (
            dict(element.attrs).get("href", "")
            or dict(element.attrs).get("xlink:href", "")
        ).removeprefix("#")
        for element in elements
        if element.tag == "use"
    ]
    if not all(element.tag in {"use", "line"} for element in elements):
        return False
    if len(elements) == 1:
        attributes = dict(elements[0].attrs)
        if elements[0].tag == "use":
            return glyphs[0] in {"lianyinxian_zuo", "lianyinxian_you"}
        return elements[0].tag == "line" and attributes.get("stroke-width") == "1.2"
    if len(elements) == 2:
        return len(glyphs) == 1 and glyphs[0] in {"lianyinxian_zuo", "lianyinxian_you"}
    return (
        len(elements) in {3, 4}
        and len(glyphs) == 2
        and set(glyphs) == {"lianyinxian_zuo", "lianyinxian_you"}
    )


def _late_ending_construct_elements(layout: LayoutPage) -> list[SvgElement]:
    elements: list[SvgElement] = []
    endings = [item for item in layout.constructs if item.kind == "ending"]
    ending_groups: dict[str, list[LayoutConstruct]] = {}
    for construct in endings:
        key = construct.construct_id or f"layout-ending:{id(construct)}"
        ending_groups.setdefault(key, []).append(construct)
    for constructs in sorted(
        ending_groups.values(),
        key=lambda group: (
            group[0].start.voice,
            group[0].start.event.span.start.line,
        ),
    ):
        for construct in constructs:
            chain_terminal = _shared_end_ending_chain_terminal(construct, endings)
            elements.extend(
                _construct_element(
                    construct,
                    layout.metrics,
                    ending_chain_terminal_end_x=(
                        chain_terminal.end.x + 1 if chain_terminal is not None else None
                    ),
                )
            )
        label = _ending_label_mark(layout, constructs[0])
        if label is not None:
            elements.extend(_ending_label_element(label))
    return elements


def _shared_end_ending_chain_terminal(
    construct: LayoutConstruct,
    endings: list[LayoutConstruct],
) -> LayoutConstruct | None:
    """Return the terminal ending for a cross-row shared-end chain."""

    if construct.start.line == construct.end.line:
        return None
    current = construct
    seen = {id(construct)}
    while True:
        successor = next(
            (
                candidate
                for candidate in endings
                if id(candidate) not in seen
                and candidate.start.event.index == current.end.event.index
            ),
            None,
        )
        if successor is None:
            return current if current is not construct else None
        seen.add(id(successor))
        current = successor


def _ending_label_mark(layout: LayoutPage, construct: LayoutConstruct) -> LayoutMark | None:
    for mark in layout.marks:
        if mark.placement == "ending-label" and mark.host == construct.start:
            return mark
    return None


def _block_construct_elements_by_event(
    layout: LayoutPage,
    *,
    placement: str,
) -> dict[int, tuple[SvgElement, ...]]:
    grouped: dict[int, list[SvgElement]] = {}
    last_dsb_inset = 0.0
    for construct in layout.constructs:
        if construct.kind != "block" or construct.start.block in {"bz", "bz-hidden"}:
            continue
        if placement != "after":
            # Closing braces are emitted with their close barline in the
            # "after" pass; nothing is placed before events.
            continue
        if _is_leading_hidden_dsb_block(layout, construct):
            for host, element in _leading_dsb_brace_elements(layout, construct):
                grouped.setdefault(id(host), []).append(element)
            continue
        host = _block_start_anchor(layout, construct)
        is_dsb = construct.start.block in {"dsb", "dsb-hidden"}
        inset = 0.0
        if is_dsb and (host.event.code or "").startswith("|n"):
            # A DSB opening directly on a leading repeat-start barline
            # carries no opening brace (As-Wished p3 rows 2-3).
            pass
        elif is_dsb:
            left_x, y, inset = _dsb_brace_geometry(layout, construct)
            grouped.setdefault(id(host), []).append(
                _use_element(
                    "dakuohu_zuo_2",
                    x=_format_reference_number(left_x),
                    y=_format_reference_number(y),
                    layer="construct",
                    source_event_index=construct.start.event.index,
                    extra_attrs=(("data-construct", "block"),),
                )
            )
        else:
            left_x = construct.start.x
            y = min(construct.start.y, construct.end.y) - 25
            grouped.setdefault(id(host), []).append(
                _use_element(
                    "dakuohu_zuo_2",
                    x=_format_reference_number(left_x),
                    y=_format_reference_number(y),
                    layer="construct",
                    source_event_index=construct.start.event.index,
                    extra_attrs=(("data-construct", "block"),),
                )
            )
        if is_dsb:
            if inset:
                last_dsb_inset = inset
            else:
                inset = last_dsb_inset
            closer, is_internal = _dsb_close_barline(layout, host)
            if closer is not None and is_internal:
                grouped.setdefault(id(closer), []).append(
                    _use_element(
                        "dakuohu_you_2",
                        x=_format_reference_number(closer.x - inset),
                        y=_format_reference_number(closer.y),
                        layer="construct",
                        source_event_index=construct.start.event.index,
                        extra_attrs=(("data-construct", "block"),),
                    )
                )
    return {event_id: tuple(items) for event_id, items in grouped.items()}


def _is_leading_hidden_dsb_block(layout: LayoutPage, construct: LayoutConstruct) -> bool:
    start = construct.start
    block_ids = {item.construct_id for item in layout.constructs if item.kind == "block"}
    has_nested_owner = any(
        construct.construct_id in item.event.construct_ids
        and len(block_ids.intersection(item.event.construct_ids)) > 1
        for item in layout.hidden_events
    )
    return start.block == "dsb-hidden" and not has_nested_owner and not any(
        item.event.span.start.line == start.event.span.start.line
        and item.event.span.end.offset <= start.event.span.start.offset
        for item in layout.events
    )


def _leading_dsb_brace_elements(
    layout: LayoutPage, construct: LayoutConstruct
) -> list[tuple[LayoutEvent, SvgElement]]:
    """Frame the actual overlap, with the system brace owning a leading opening."""
    hidden = sorted(
        (item for item in layout.hidden_events
         if construct.construct_id in item.event.construct_ids
         and item.voice == construct.start.voice and item.line == construct.start.line),
        key=lambda item: item.event.span.start.offset,
    )
    if not hidden:
        return []
    end_offset = max(item.event.span.end.offset for item in hidden)
    targets = sorted(
        (item for item in layout.events
         if item.voice == construct.start.voice
         and item.event.span.start.line == construct.start.event.span.start.line
         and item.event.index >= 0 and item.event.span.start.offset > end_offset),
        key=lambda item: item.event.span.start.offset,
    )
    if not targets:
        return []
    timeline = source_onsets(targets)
    duration = sum((duration_fraction(item.event) for item in hidden), Fraction())
    y = (hidden[0].y + targets[0].y) / 2
    result: list[tuple[LayoutEvent, SvgElement]] = []
    has_system_opening = any(
        brace.line_start <= construct.start.line <= brace.line_end
        for brace in layout.voice_braces
    )
    if not has_system_opening:
        result.append((hidden[0], _use_element(
            "dakuohu_zuo_2",
            x=_format_reference_number(hidden[0].x - NOTE_WIDTH),
            y=_format_reference_number(y),
            layer="construct",
            source_event_index=construct.start.event.index,
            extra_attrs=(("data-construct", "block"),),
        )))
    following = next(
        (item for onset, item in timeline
         if onset >= duration and item.event.kind != MusicTokenKind.BARLINE),
        None,
    )
    if following is None:
        return result
    if hidden[-1].event.kind == MusicTokenKind.BARLINE:
        x, host, _ = project_source_onset(duration, MusicTokenKind.BARLINE, timeline)
        x -= NOTE_WIDTH / 2
    else:
        covered = [item for onset, item in timeline
                   if onset < duration and item.event.kind != MusicTokenKind.BARLINE]
        host = following
        x = (covered[-1].x + following.x) / 2 if covered else following.x - NOTE_WIDTH / 2
    closing_barline = next(
        (item for onset, item in timeline
         if onset == duration and item.event.kind == MusicTokenKind.BARLINE),
        None,
    )
    if closing_barline is not None:
        # Keep the brace left of a boundary barline instead of centering both
        # glyphs on the same stream position.
        x = min(x, closing_barline.x - _DSB_CLOSE_BRACE_BARLINE_CLEARANCE)
    result.append((host, _use_element(
        "dakuohu_you_2",
        x=_format_reference_number(x),
        y=_format_reference_number(y),
        layer="construct",
        source_event_index=construct.start.event.index,
        extra_attrs=(("data-construct", "block"),),
    )))
    return result



def _dsb_brace_geometry(
    layout: LayoutPage,
    construct: LayoutConstruct,
) -> tuple[float, float, float]:
    """Return the opening-brace x, its y, and the brace inset for a DSB block.

    The brace inset is projected from the source block start and anchor
    barline.  Ordinary and extension-ended blocks use the decoded 4/11 and
    -4/7 projection ratios respectively; this preserves the source span's
    width when hidden content is laid out separately. Anchors whose code starts
    with ``|n`` carry no opening brace at all.
    """
    anchor = _block_start_anchor(layout, construct)
    delta = construct.start.x - anchor.x
    if construct.end.event.kind == MusicTokenKind.EXTENSION:
        left_x = anchor.x - delta * (4 / 7)
    else:
        left_x = anchor.x + delta * (4 / 11)
    return left_x, anchor.y, abs(left_x - anchor.x)


def _block_start_anchor(layout: LayoutPage, construct: LayoutConstruct) -> LayoutEvent:
    if construct.start in layout.events:
        return construct.start
    start_span = construct.start.event.span.start
    candidates = [
        item
        for item in layout.events
        if item.event.span.start.line == start_span.line
        and item.event.span.end.column <= start_span.column
    ]
    if candidates:
        return max(candidates, key=lambda item: item.event.span.end.column)
    return construct.end








def _voice_caption_elements(layout: LayoutPage) -> list[SvgElement]:
    """Right-aligned voice labels for brace-run lines (empty when unlabeled)."""
    elements: list[SvgElement] = []
    for caption in layout.voice_captions:
        elements.append(
            _text_element(
                x=_format_reference_number(caption.x),
                y=_format_reference_number(caption.y),
                text=caption.text,
                layer="construct",
                extra_attrs=(
                    ("dy", _caption_dy(layout.metrics.lyric_size)),
                    ("text-anchor", "end"),
                    ("fill", "#101010"),
                    ("font-size", str(layout.metrics.lyric_size)),
                    ("font-family", layout.metrics.lyric_font),
                ),
            )
        )
    return elements

def _caption_dy(font_size: int) -> str:
    text = format(Decimal("0.3355") * font_size, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text

def _voice_brace_elements(brace: LayoutVoiceBrace) -> list[SvgElement]:
    x = _format_reference_number(brace.x)
    return [
        _use_element(
            "shengbufu_shang",
            x=x,
            y=_format_reference_number(brace.y_top),
            layer="construct",
            extra_attrs=(("data-construct", "voice-brace"),),
        ),
        _use_element(
            "shengbufu_xia",
            x=x,
            y=_format_reference_number(brace.y_bottom),
            layer="construct",
            extra_attrs=(("data-construct", "voice-brace"),),
        ),
        _line_element(
            x1=brace.x - 25.5,
            y1=brace.y_top - 6.5,
            x2=brace.x - 25.5,
            y2=brace.y_bottom + 6.5,
            source_event_index=None,
            data_construct="voice-connector",
            stroke_width=4,
        ),
        _line_element(
            x1=brace.x - 21,
            y1=brace.y_top - 8,
            x2=brace.x - 21,
            y2=brace.y_bottom + 8,
            source_event_index=None,
            data_construct="voice-connector",
            stroke_width=2,
        ),
    ]
