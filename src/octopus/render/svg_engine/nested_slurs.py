"""Post-layout vertical lanes for genuinely nested slur/tie geometry.

The score's ordinary note Y values are the natural anchor.  Only a semantic
parent that would draw through a child's *interior* is moved; unrelated spans
and endpoint-only contacts stay on their natural lane.  The pass mutates only
``vertical_offset`` on layout constructs, so compatibility replay can render
the exact same resolved geometry more than once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from octopus.normalization.types import MusicEvent
from octopus.render.core.layout_types import LayoutConstruct, LayoutEvent, LayoutPage
from octopus.render.layout_engine.first_tie_lift import first_tie_lift_amount

from ..svg_engine.slur_style import slur_uses_path

PATH_PATH_CLEARANCE = 8.0
ENDPOINT_ENDPOINT_CLEARANCE = 4.0
_EPSILON = 1e-6


def plan_nested_slur_lanes(
    layout: LayoutPage,
    *,
    natural_anchor: Callable[[LayoutConstruct], float] | None = None,
    lane_gap: Callable[[LayoutConstruct, LayoutConstruct], float] | None = None,
) -> None:
    """Resolve nested slur/tie lanes after all event X/Y projection is final."""

    anchor = natural_anchor or _natural_anchor
    gap_for = lane_gap or _natural_lane_gap

    def anchor_for_row(item: LayoutConstruct, row: int) -> float:
        return slur_stack_anchor(item, row) if natural_anchor is None else anchor(item)

    all_slurs = [
        item
        for item in layout.constructs
        if item.kind == "slur" and item.start.event.index >= 0
    ]
    candidates = [item for item in all_slurs if item.semantic_parent_id is not None]
    by_id = {item.construct_id: item for item in all_slurs if item.construct_id}
    for item in all_slurs:
        # Emission can be requested more than once for one layout.  Placement
        # is a pure recomputation from natural geometry, never an accumulator.
        item.vertical_offset = 0.0
        item.row_vertical_offsets.clear()
    children: dict[str, list[LayoutConstruct]] = {}
    for item in candidates:
        parent_id = item.semantic_parent_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None or parent is item:
            continue
        if not _shares_row(parent, item):
            continue
        children.setdefault(parent.construct_id or "", []).append(item)

    # Children are already at natural/resolved geometry when their parent is
    # visited.  Sorting by descending source depth is a stable post-order for
    # nested wrappers without making source identity a rendering rule.
    ordered = sorted(
        all_slurs,
        key=lambda item: (
            _semantic_depth(item, by_id),
            item.start.line,
            item.start.slot,
            item.end.slot,
        ),
        reverse=True,
    )
    for parent in ordered:
        direct_children = children.get(parent.construct_id or "", ())
        if not direct_children:
            continue
        required_by_row: dict[int, float] = {}
        colliding_anchors_by_row: dict[int, set[float]] = {}
        parent_intervals = _rendered_intervals(parent, layout)
        for child in direct_children:
            child_intervals = _rendered_intervals(child, layout)
            if _is_visual_chain_continuation(parent, child, parent_intervals, child_intervals):
                continue
            natural_gap = gap_for(parent, child)
            # A negative offset moves the outer curve upward. Include the
            # child's already-resolved offset in the signed target.
            for parent_line, parent_interval in parent_intervals:
                for child_line, child_interval in child_intervals:
                    if parent_line != child_line:
                        continue
                    if _interior_overlap(parent_interval, child_interval) <= _EPSILON:
                        continue
                    parent_anchor = anchor_for_row(parent, parent_line) + _offset_for_row(
                        parent, parent_line
                    )
                    child_anchor = anchor_for_row(child, child_line) + _offset_for_row(
                        child, child_line
                    )
                    colliding_anchors_by_row.setdefault(parent_line, set()).add(
                        round(child_anchor, 6)
                    )
                    required = parent_anchor - (child_anchor - natural_gap)
                    prior_required = required_by_row.get(parent_line)
                    if prior_required is None or required > prior_required:
                        required_by_row[parent_line] = required
        if parent.start.line == parent.end.line:
            interstitial = _interstitial_lane_offset(
                parent, colliding_anchors_by_row.get(parent.start.line, set())
            )
            if interstitial is not None:
                parent.vertical_offset = interstitial
            elif required_by_row:
                # The reference stack uses the child's target anchor exactly,
                # even when the parent's natural mixed-octave anchor is one
                # pixel above it.  ``required`` is the signed correction from
                # the parent's natural anchor to that target.
                parent.vertical_offset = -max(required_by_row.values())
        else:
            for row, required in required_by_row.items():
                parent.row_vertical_offsets[row] = -required
    _plan_unresolved_span_lanes(layout, all_slurs)


def resolve_nested_slur_lanes(
    layout: LayoutPage,
    *,
    natural_anchor: Callable[[LayoutConstruct], float] | None = None,
    lane_gap: Callable[[LayoutConstruct, LayoutConstruct], float] | None = None,
) -> list[LayoutConstruct]:
    """Return nested-slur-resolved construct copies without mutating ``layout``.

    ``plan_nested_slur_lanes`` remains the historical in-place helper used by
    compatibility callers.  Late rendering uses this pure boundary instead:
    every construct is shallow-copied and its per-row offset mapping gets a
    fresh dictionary before the existing resolver runs on a temporary page.
    Layout events and other immutable/shared layout data remain shared because
    lane planning only changes construct offset fields.
    """

    constructs = [
        replace(construct, row_vertical_offsets=dict(construct.row_vertical_offsets))
        for construct in layout.constructs
    ]
    resolved_layout = replace(layout, constructs=constructs)
    plan_nested_slur_lanes(
        resolved_layout,
        natural_anchor=natural_anchor,
        lane_gap=lane_gap,
    )
    apply_first_tie_lifts(resolved_layout)
    return resolved_layout.constructs


def apply_first_tie_lifts(layout: LayoutPage) -> None:
    """Seat each flagged row's first path-style pair curve on the lifted lane.

    ``layout.first_tie_lift_rows`` is decided at layout time from the source
    line above (see ``layout_engine.first_tie_lift``).  The reference lifts
    the row's leftmost path-form parenthesized pair — tie or slur alike, as
    in I-Like p3 where the lifted curve is the ``(4// 5//)`` slur — so the
    selection ignores the tie/slur distinction.  The amount is eight pixels
    plus three per octave of the curve's highest note (Grandmas-Penghu-Bay
    p1 lifts an octave-one pair by eleven).  The lift only touches a curve
    that the nested-lane pass left at its natural offset, so nested geometry
    keeps precedence.  Later curves on the row stay natural.
    """
    if not layout.first_tie_lift_rows:
        return
    first_by_row: dict[int, LayoutConstruct] = {}
    for construct in layout.constructs:
        if construct.kind != "slur":
            continue
        if construct.start.line != construct.end.line:
            continue
        if construct.start.line not in layout.first_tie_lift_rows:
            continue
        if not slur_uses_path(construct):
            continue
        current = first_by_row.get(construct.start.line)
        if current is None or construct.start.x < current.start.x:
            first_by_row[construct.start.line] = construct
    for construct in first_by_row.values():
        if construct.vertical_offset != 0.0:
            continue
        source_offset = construct.start.event.span.start.offset
        if any(
            state.family == "span"
            and state.page_index == layout.page_index
            and source_offset > state.source_span.start.offset
            for state in layout.unresolved_span_states
        ):
            continue
        octave = max(
            construct.start.event.octave,
            construct.end.event.octave,
        )
        construct.vertical_offset = first_tie_lift_amount(octave)


def _semantic_depth(item: LayoutConstruct, by_id: dict[str, LayoutConstruct]) -> int:
    depth = 0
    seen: set[str] = set()
    current = item
    while current.semantic_parent_id and current.semantic_parent_id not in seen:
        seen.add(current.semantic_parent_id)
        current = by_id.get(current.semantic_parent_id, current)
        depth += 1
    return depth


def _is_visual_chain_continuation(
    parent: LayoutConstruct,
    child: LayoutConstruct,
    parent_intervals: tuple[tuple[int, tuple[float, float]], ...],
    child_intervals: tuple[tuple[int, tuple[float, float]], ...],
) -> bool:
    """Adjacent visual-only links intentionally share one lane."""

    return (
        child.visual_only
        and parent.source_kind == child.source_kind == "tie"
        and parent.visual_start_event_index == child.end.event.index
        and any(
            row == child_row
            and abs(interval[0] - child_interval[0]) <= _EPSILON
            and abs(interval[1] - child_interval[1]) <= _EPSILON
            for row, interval in parent_intervals
            for child_row, child_interval in child_intervals
        )
    )


def _rendered_intervals(
    construct: LayoutConstruct,
    layout: LayoutPage,
) -> tuple[tuple[int, tuple[float, float]], ...]:
    """Return the effective interior X interval, excluding endpoint contact."""

    intervals: list[tuple[int, tuple[float, float]]] = []
    if construct.start.line == construct.end.line:
        intervals.append((construct.start.line, _rendered_interval(construct)))
        return tuple(intervals)
    # Cross-row endpoint constructs emit one horizontal run on each endpoint
    # row.  Their open side is deliberately broad; only a nested child on the
    # same row can trigger a shift.
    left = float(layout.metrics.note_start_x)
    right = float(layout.metrics.width - layout.metrics.margin_right)
    intervals.extend(
        (
            (construct.start.line, (construct.start.x, right)),
            (construct.end.line, (left, construct.end.x)),
        )
    )
    return tuple((line, _inset_interval(interval, construct)) for line, interval in intervals)


def _rendered_interval(construct: LayoutConstruct) -> tuple[float, float]:
    return _inset_interval(
        (min(construct.start.x, construct.end.x), max(construct.start.x, construct.end.x)),
        construct,
    )


def _inset_interval(
    interval: tuple[float, float], construct: LayoutConstruct
) -> tuple[float, float]:
    left, right = interval
    inset = 1.0 if slur_uses_path(construct) else 12.0
    left += inset
    right -= inset
    return left, max(left, right)


def _shares_row(first: LayoutConstruct, second: LayoutConstruct) -> bool:
    first_rows = {first.start.line, first.end.line}
    second_rows = {second.start.line, second.end.line}
    return bool(first_rows.intersection(second_rows))


def _interior_overlap(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return max(0.0, min(first[1], second[1]) - max(first[0], second[0]))


def _natural_anchor(construct: LayoutConstruct) -> float:
    """Return the common note-relative anchor used by both visual styles."""

    return slur_stack_anchor(construct)


def _endpoint_natural_anchor(endpoint: LayoutEvent) -> float:
    return (
        endpoint.y
        - octave_stack_lift(endpoint.event.octave)
        - fermata_lift(endpoint.event)
    )


def _interstitial_lane_offset(
    construct: LayoutConstruct, colliding_anchors: set[float]
) -> float | None:
    """Seat a mixed-octave endpoint parent between two occupied child lanes."""

    if slur_uses_path(construct):
        return None
    start_anchor = _endpoint_natural_anchor(construct.start)
    end_anchor = _endpoint_natural_anchor(construct.end)
    if abs(start_anchor - end_anchor) <= _EPSILON:
        return None
    if start_anchor > end_anchor:
        return None

    def occupied(lane: float) -> bool:
        return any(abs(anchor - lane) <= _EPSILON for anchor in colliding_anchors)

    if not (occupied(start_anchor) and occupied(end_anchor)):
        return None
    lower_y = max(start_anchor, end_anchor)
    lower_event = construct.start if start_anchor >= end_anchor else construct.end
    clearance = ENDPOINT_ENDPOINT_CLEARANCE + 3.0 * max(
        lower_event.event.octave, 0
    )
    return (lower_y - clearance) - min(start_anchor, end_anchor)


def fermata_lift(event: MusicEvent) -> float:
    """Anchor lift for slurs touching a fermata (yanchangfu) note.

    The fermata glyph occupies the default slur lane above its note, so the
    reference engraver raises any slur anchored to such a note by seven
    pixels plus three per positive octave. Corpus-verified on the octave-zero
    controls and the octave-one fermata ties of Looking-Back - Choir p4.
    """
    return 7.0 + 3.0 * max(event.octave, 0) if "yc" in event.decorations else 0.0


def sby_lift(event: MusicEvent) -> float:
    """Return the nine-pixel lane lift for a note with an upper trill mark."""
    return 9.0 if "sby" in event.decorations else 0.0


def endpoint_slur_lift(event: MusicEvent) -> float:
    """Return decoration clearance for an endpoint-style slur lane."""

    return fermata_lift(event) + (9.0 if "sby" in event.decorations else 0.0)


def octave_stack_lift(octave: int) -> float:
    """Return the note-relative lane lift that clears octave dots.

    The first octave dot adds five pixels above the plain 26-pixel lane;
    each further dot adds eight pixels because the glyphs stack vertically.
    This preserves the established 26/31 lanes and models the corpus-proven
    39-pixel lane for a double-octave endpoint.
    """

    if octave <= 0:
        return 26.0
    return 31.0 + 8.0 * (octave - 1)


def slur_stack_anchor(construct: LayoutConstruct, row: int | None = None) -> float:
    """Return the reference stack anchor for selected construct endpoints."""

    endpoints = (construct.start, construct.end)
    selected = tuple(endpoint for endpoint in endpoints if row is None or endpoint.line == row)
    if not selected:
        selected = endpoints
    return min(
        endpoint.y
        - octave_stack_lift(endpoint.event.octave)
        - fermata_lift(endpoint.event)
        - sby_lift(endpoint.event)
        for endpoint in selected
    )


def _natural_lane_gap(parent: LayoutConstruct, child: LayoutConstruct) -> float:
    parent_path = slur_uses_path(parent)
    child_path = slur_uses_path(child)
    child_octave = max(
        child.start.event.octave,
        child.end.event.octave,
        0,
    )
    if parent_path and child_path:
        return PATH_PATH_CLEARANCE + 3 * child_octave
    if not parent_path:
        return ENDPOINT_ENDPOINT_CLEARANCE + 3 * child_octave
    return PATH_PATH_CLEARANCE + 3 * child_octave


def _offset_for_row(construct: LayoutConstruct, row: int) -> float:
    return construct.row_vertical_offsets.get(row, construct.vertical_offset)


def _plan_unresolved_span_lanes(
    layout: LayoutPage,
    all_slurs: list[LayoutConstruct],
) -> None:
    """Carry a confirmed unresolved source span into the next source voice row."""

    path_slurs = [
        construct
        for construct in all_slurs
        if not construct.visual_only
        and slur_uses_path(construct)
    ]
    if not path_slurs or not layout.unresolved_span_states:
        return
    rows: dict[tuple[int, int], list[LayoutConstruct]] = {}
    for construct in path_slurs:
        source_line = construct.start.event.span.start.line
        source_voice = layout.source_voice_by_line.get(source_line)
        if source_voice is None:
            continue
        rows.setdefault((source_voice, source_line), []).append(construct)
    ordered_rows = [
        (key, tuple(sorted(
            constructs,
            key=lambda item: (
                item.start.slot,
                item.end.slot,
                item.start.event.span.start.offset,
            ),
        )))
        for key, constructs in rows.items()
    ]
    ordered_rows.sort(
        key=lambda item: item[1][0].start.event.span.start.offset
    )
    for state in sorted(
        layout.unresolved_span_states,
        key=lambda item: item.source_span.start.offset,
    ):
        same_row_paths = tuple(
            construct
            for construct in path_slurs
            if construct.start.event.span.start.line == state.source_span.start.line
            and construct.start.event.span.start.offset > state.source_span.start.offset
        )
        if (
            state.page_index != layout.page_index
            or state.family != "span"
            or (not same_row_paths and state.prior_span_count > 0)
        ):
            continue
        state_rows: list[tuple[tuple[int, int], tuple[LayoutConstruct, ...]]] = []
        for key, row in ordered_rows:
            after_opener = tuple(
                construct
                for construct in row
                if construct.start.event.span.start.offset > state.source_span.start.offset
            )
            if after_opener:
                state_rows.append((key, after_opener))
        if not state_rows:
            continue
        prime_index = next(
            (
                index
                for index, (key, _row) in enumerate(state_rows)
                if key[0] == state.source_voice
            ),
            None,
        )
        if prime_index is None:
            continue
        last_same_voice = state_rows[prime_index][1]
        for key, row in state_rows[prime_index + 1 :]:
            if key[0] == state.source_voice:
                last_same_voice = row
                continue
            if len(row) < 2:
                continue
            first = row[0]
            if state.source_voice != 1 and (
                first.source_kind != "tie" or first.semantic_parent_id is not None
            ):
                break
            offset = 5.0 if (
                len(last_same_voice) == 1
                and last_same_voice[0].start.slot == first.start.slot
            ) else PATH_PATH_CLEARANCE
            offset += 3.0 * max(
                first.start.event.octave,
                first.end.event.octave,
                0,
            )
            first.vertical_offset = min(first.vertical_offset, -offset)
            break


__all__ = [
    "ENDPOINT_ENDPOINT_CLEARANCE",
    "PATH_PATH_CLEARANCE",
    "octave_stack_lift",
    "endpoint_slur_lift",
    "plan_nested_slur_lanes",
    "resolve_nested_slur_lanes",
    "slur_stack_anchor",
]
