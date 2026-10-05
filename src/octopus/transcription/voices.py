"""Identify full numbered-voice systems from printed left braces."""

from __future__ import annotations

from dataclasses import dataclass

from .components import Box, Component


@dataclass(frozen=True, slots=True)
class VoiceGroup:
    rows: tuple[int, ...]
    box: Box


@dataclass(frozen=True, slots=True)
class DsbOverlay:
    anchor: int
    upper: int
    lower: int
    box: Box
    closing_x: int | None = None
    continuation: bool = False
    standalone: bool = False


def _gap_branches(
    component: Component,
    rows: tuple[Box, ...],
    digit_height: int,
    *,
    page_width: int,
    branches_right: bool,
) -> tuple[int, int] | None:
    """Find the two note rows whose ink borders a local brace drawn between them."""
    left, top, right, bottom = component.box
    midpoint = (top + bottom) / 2
    vertical_tolerance = digit_height * 0.5
    horizontal_limit = digit_height * 3 if branches_right else page_width * 0.17

    def adjacent(box: Box) -> bool:
        if branches_right:
            return right < box[0] <= right + horizontal_limit
        return left - horizontal_limit <= box[2] < left

    upper = [
        index for index, box in enumerate(rows)
        if adjacent(box)
        and (box[1] + box[3]) / 2 < midpoint
        and box[1] <= top + vertical_tolerance
        and box[3] >= top - vertical_tolerance
        and abs((box[1] + box[3]) / 2 - top) <= digit_height * 1.25
    ]
    lower = [
        index for index, box in enumerate(rows)
        if adjacent(box)
        and (box[1] + box[3]) / 2 > midpoint
        and box[1] <= bottom + vertical_tolerance
        and box[3] >= bottom - vertical_tolerance
        and abs((box[1] + box[3]) / 2 - bottom) <= digit_height * 1.25
    ]
    if len(upper) == len(lower) == 1 and upper[0] < lower[0]:
        return upper[0], lower[0]
    return None


def recognize_dsb_overlays(
    components: list[Component], rows: tuple[Box, ...], page_width: int,
    digit_height: int,
) -> tuple[DsbOverlay, ...]:
    overlays = []
    for component in components:
        left, top, right, bottom = component.box
        if not (
            page_width * 0.10 <= left <= page_width * 0.85
            and digit_height * 0.2 - 1 <= component.width <= digit_height * 1.5
            and digit_height * 2.5 <= component.height <= digit_height * 6
            and component.height >= component.width * 5
            and component.area <= component.width * component.height * 0.62
        ):
            continue
        branches = [
            index for index, box in enumerate(rows)
            if top < (box[1] + box[3]) / 2 < bottom
            and right < box[0] <= right + digit_height * 3
        ]
        if len(branches) != 2:
            gap_pair = _gap_branches(
                component, rows, digit_height, page_width=page_width, branches_right=True,
            )
            branches = list(gap_pair) if gap_pair is not None else []
        if len(branches) != 2:
            continue
        upper, lower = branches
        closing = min(
            (
                other for other in components
                if right + digit_height < other.box[0] < right + page_width * 0.3
                and abs(other.box[1] - top) <= digit_height
                and abs(other.box[3] - bottom) <= digit_height
                and abs(other.width - component.width) <= digit_height * 0.3
                and other.height >= other.width * 5
            ),
            key=lambda other: other.box[0],
            default=None,
        )
        anchors = [
            index for index, box in enumerate(rows)
            if upper != index != lower
            and (rows[upper][1] + rows[upper][3]) / 2
            < (box[1] + box[3]) / 2
            < (rows[lower][1] + rows[lower][3]) / 2
            and (
                box[2] < left
                or closing is not None and box[0] < left and box[2] > closing.box[2]
            )
        ]
        if len(anchors) == 1:
            overlays.append(DsbOverlay(
                anchors[0], upper, lower, component.box,
                closing.box[0] if closing is not None else None,
            ))
    # A page can start inside a temporary voice; its closing brace alone remains visible.
    closing_boxes = {overlay.closing_x for overlay in overlays if overlay.closing_x is not None}
    used_branches = {index for overlay in overlays for index in (overlay.upper, overlay.lower)}
    for component in components:
        left, top, right, bottom = component.box
        if not (
            page_width * 0.10 <= left <= page_width * 0.85
            and left not in closing_boxes
            and digit_height * 0.2 - 1 <= component.width <= digit_height * 1.5
            and digit_height * 2.5 <= component.height <= digit_height * 6
            and component.height >= component.width * 5
            and component.area <= component.width * component.height * 0.62
        ):
            continue
        branches = [
            index for index, box in enumerate(rows)
            if index not in used_branches
            and top < (box[1] + box[3]) / 2 < bottom
            and left - page_width * 0.17 <= box[2] < left
        ]
        if len(branches) != 2:
            gap_pair = _gap_branches(
                component, rows, digit_height, page_width=page_width, branches_right=False,
            )
            branches = [index for index in gap_pair if index not in used_branches] \
                if gap_pair is not None else []
        if len(branches) != 2:
            continue
        upper, lower = branches
        anchors = [
            index for index, box in enumerate(rows)
            if index not in used_branches
            and right < box[0] <= right + digit_height * 3
            and (rows[upper][1] + rows[upper][3]) / 2
            < (box[1] + box[3]) / 2
            < (rows[lower][1] + rows[lower][3]) / 2
        ]
        if len(anchors) == 1:
            overlays.append(DsbOverlay(anchors[0], upper, lower, component.box,
                                       continuation=True))
            used_branches.update(branches)
    for component in components:
        left, top, right, bottom = component.box
        if not (
            page_width * 0.10 <= left <= page_width * 0.85
            and digit_height * 0.2 - 1 <= component.width <= digit_height * 1.5
            and digit_height * 2.5 <= component.height <= digit_height * 6
            and component.height >= component.width * 5
            and component.area <= component.width * component.height * 0.62
            and any(
                outer.box[2] < left
                # A second adjacent staff/group brace is not a standalone DSB opener.
                and left - outer.box[2] >= digit_height
                and outer.box[1] < top < bottom < outer.box[3]
                and outer.height > component.height * 2
                for outer in components
            )
        ):
            continue
        branches = [
            index for index, box in enumerate(rows)
            if index not in used_branches
            and top < (box[1] + box[3]) / 2 < bottom
            and right < box[0] <= right + digit_height * 3
        ]
        if len(branches) != 2:
            gap_pair = _gap_branches(
                component, rows, digit_height, page_width=page_width, branches_right=True,
            )
            branches = [index for index in gap_pair if index not in used_branches] \
                if gap_pair is not None else []
        if len(branches) == 2:
            upper, lower = branches
            overlays.append(DsbOverlay(upper, upper, lower, component.box,
                                       standalone=True))
            used_branches.update(branches)
    return tuple(overlays)


def recognize_voice_groups(
    components: list[Component], rows: tuple[Box, ...], page_width: int, digit_height: int,
    excluded: set[int],
) -> tuple[VoiceGroup, ...]:
    candidates = []
    for component in components:
        left, top, right, bottom = component.box
        if not (
            left < page_width * 0.22
            and digit_height * 0.25 <= component.width <= digit_height * 1.5
            and component.height >= digit_height * 3
            and component.height >= component.width * 6
            and component.area >= component.height * 2
        ):
            continue
        # Printed tips can overlap the end row's digit band while missing its center.
        all_members = tuple(
            index
            for index, box in enumerate(rows)
            if box[1] < bottom and top < box[3]
            and right < box[2]
        )
        members = tuple(index for index in all_members if index not in excluded)
        if len(members) < 2:
            continue
        if not all_members:
            continue
        first = rows[all_members[0]]
        if abs((first[1] + first[3]) / 2 - top) > _tip_tolerance(first, digit_height):
            continue
        last = rows[all_members[-1]]
        if abs(bottom - (last[1] + last[3]) / 2) > _tip_tolerance(last, digit_height):
            continue
        candidates.append(VoiceGroup(members, component.box))
    selected = []
    occupied: set[int] = set()
    for group in sorted(candidates, key=lambda value: (-len(value.rows), value.box[0])):
        if not any(index in occupied for index in group.rows):
            selected.append(group)
            occupied.update(group.rows)
    return tuple(sorted(selected, key=lambda value: value.rows[0]))


def _tip_tolerance(row: Box, digit_height: int) -> float:
    """Allow small scan skew for compact rows, but not oversized row fragments."""
    tolerance = float(digit_height * 2)
    if row[3] - row[1] <= digit_height * 1.5:
        tolerance *= 1.1
    return tolerance
