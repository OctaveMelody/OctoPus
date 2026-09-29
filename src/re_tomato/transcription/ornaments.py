"""Read small grace groups and repeat-ending frames beside established music rows."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from statistics import median
from typing import cast

from PIL import Image

from .components import Box, Component, connected_components
from .glyphs import classify_digit
from .text import image_digit


@dataclass(frozen=True, slots=True)
class GraceGroup:
    host: int
    body: str
    box: Box


@dataclass(frozen=True, slots=True)
class EndingSegment:
    box: Box
    opens: bool
    closed: bool
    label: str = ""


def _horizontal_rows(
    gray: Image.Image, component: Component, top: int, bottom: int,
) -> list[int]:
    return [
        y for y in range(max(component.box[1], top), min(component.box[3], bottom))
        if sum(_dark(gray, x, y) for x in range(component.box[0], component.box[2]))
        >= component.width * 0.85
    ]


def voice_components(
    components: list[Component], rows: tuple[Box, ...], height: int, gray: Image.Image,
) -> list[Component]:
    """Recover the narrow brace when a horizontal ending frame touches it."""
    found = []
    for component in components:
        left, top, right, bottom = component.box
        if (component.width > height * 3 and component.height > height * 2
                and any(left < box[0] < left + height * 2
                        and top < box[1] < bottom for box in rows)):
            if not any(_horizontal_rows(
                gray, component, floor(box[1] - height * 3.5), ceil(box[1] - height * 0.5),
            ) for box in rows):
                found.append(component)
                continue
            strip = gray.crop((left, top, min(right, left + round(height * 0.8)), bottom))
            brace = max(connected_components(strip), key=lambda item: item.height, default=None)
            if brace is not None and brace.height >= component.height * 0.8:
                found.append(Component(
                    (left + brace.box[0], top + brace.box[1],
                     left + brace.box[2], top + brace.box[3]), brace.area,
                ))
                continue
        found.append(component)
    return found


def row_endings(
    notes: tuple[Box, ...], barlines: tuple[int, ...], components: list[Component],
    gray: Image.Image, graces: tuple[GraceGroup, ...] = (),
) -> tuple[EndingSegment, ...]:
    """Read straight frames, including a line interrupted by its printed numeric label."""
    height = median(box[3] - box[1] for box in notes)
    top = median(box[1] for box in notes)
    strokes = []
    for component in components:
        left, upper, right, bottom = component.box
        if not (
            component.width >= height * 0.9
            and upper <= top - height * 0.5 and bottom >= top - height * 3.5
            and (component.height <= height * 0.9
                 or component.width > height * 3 and component.height > height * 2)
        ):
            continue
        horizontal = _horizontal_rows(
            gray, component, floor(top - height * 3.5), ceil(top - height * 0.5),
        )
        if not horizontal or horizontal[-1] - horizontal[0] > max(2, height * 0.12):
            continue
        line_bottom = horizontal[-1] + 1
        corner_bottom = min(bottom, line_bottom + ceil(height * 0.9))
        hooks = [
            sum(any(_dark(gray, x, y) for x in range(start, end))
                for y in range(line_bottom, corner_bottom)) >= max(2, height * 0.2)
            and not (corner_bottom < bottom and any(
                _dark(gray, x, corner_bottom) for x in range(start, end)
            ))
            for start, end in ((left, min(right, left + max(2, round(height * 0.12)))),
                               (max(left, right - max(2, round(height * 0.12))), right))
        ]
        strokes.append(EndingSegment(
            (left, horizontal[0], right, corner_bottom), hooks[0], hooks[1],
        ))
    merged: list[EndingSegment] = []
    for stroke in sorted(strokes, key=lambda item: (round(item.box[1] / max(2, height * 0.15)),
                                                   item.box[0])):
        if merged and (
            abs(stroke.box[1] - merged[-1].box[1]) <= max(2, height * 0.12)
            and 0 <= stroke.box[0] - merged[-1].box[2] <= height * 4
            and not merged[-1].closed and not stroke.opens
        ):
            previous = merged.pop()
            merged.append(EndingSegment(
                (previous.box[0], min(previous.box[1], stroke.box[1]), stroke.box[2],
                 max(previous.box[3], stroke.box[3])), previous.opens, stroke.closed,
            ))
        else:
            merged.append(stroke)
    found = []
    for segment in merged:
        left, upper, right, _ = segment.box
        starts_at_row = -height * 0.3 <= notes[0][0] - left <= height * 1.5
        ends_at_row = right >= max((notes[-1][2], *barlines)) - height * 0.5
        if not (
            right - left >= height * 2
            and (starts_at_row or any(abs(x - left) <= height * 0.65 for x in barlines))
            and (ends_at_row or segment.opens and not segment.closed
                 and any(x >= right for x in barlines) or any(
                abs(x - right) <= height * (0.65 if segment.closed else 2.5)
                and not any(right < box[0] < x for box in notes)
                for x in barlines
            ))
        ):
            continue
        label = ""
        if segment.opens:
            # ponytail: numeric labels only; keep other text in review until ownership is reliable.
            letters = [
                component for component in components
                if left + height * 0.15 < component.box[0] < min(right, left + height * 4)
                and upper - height <= component.box[1] < upper + height * 0.6
                and height * 0.4 <= component.height <= height
                and component.width <= height
                and not any(
                    group.box[0] <= component.box[0] and component.box[2] <= group.box[2]
                    and group.box[1] <= component.box[1] <= group.box[3]
                    for group in graces
                )
            ]
            parts = []
            complete = True
            previous_letter: Component | None = None
            for component in sorted(letters, key=lambda item: item.box[0]):
                if previous_letter is not None and (
                    component.box[0] - previous_letter.box[2] > height * 0.7
                    or abs(component.center_y - previous_letter.center_y) > height * 0.3
                ):
                    break
                match = image_digit(gray, component.box, "0123456789")
                if match is None:
                    complete = False
                    break
                parts.append(match[0])
                punctuation = [
                    mark for mark in components
                    if component.box[2] <= mark.box[0] <= component.box[2] + height * 0.7
                    and component.box[3] - height * 0.5 <= mark.box[1] < component.box[3]
                    and 1 <= mark.width <= height * 0.35
                    and 1 <= mark.height <= height * 0.35
                ]
                if punctuation:
                    parts.append(".")
                previous_letter = component
            label = "".join(parts) if complete else ""
        if segment.opens or segment.closed or starts_at_row:
            found.append(EndingSegment(segment.box, segment.opens, segment.closed, label))
    return tuple(found)


def _dark(gray: Image.Image, x: int, y: int) -> bool:
    return cast(int, gray.getpixel((x, y))) < 170


def row_graces(
    notes: tuple[Box, ...], components: list[Component], gray: Image.Image,
) -> tuple[GraceGroup, ...]:
    """Require small digits, an eighth-note beam and a directed grace connector."""
    height = median(box[3] - box[1] for box in notes)
    top = median(box[1] for box in notes)
    candidates = [
        (component, match[0]) for component in components
        if height * 0.35 <= component.height <= height * 0.75
        and top - height * 1.1 <= component.box[1] <= top - height * 0.3
        and (match := classify_digit(gray, component, min_score=0.78, grace=True)) is not None
    ]
    groups: list[list[tuple[Component, str]]] = []
    for candidate in sorted(candidates, key=lambda pair: pair[0].box[0]):
        component = candidate[0]
        if groups and (
            component.box[0] - groups[-1][-1][0].box[2] <= component.height * 0.55
            and abs(component.box[3] - groups[-1][-1][0].box[3]) <= max(2, height * 0.08)
        ):
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    found = []
    for group in groups:
        left = group[0][0].box[0]
        right = group[-1][0].box[2]
        bottom = max(component.box[3] for component, _ in group)
        small_height = median(component.height for component, _ in group)
        # The connector bends toward its host; this also excludes isolated annotation digits.
        directions = []
        for mark in components:
            if not (
                left - small_height * 0.4 <= mark.box[0]
                and mark.box[2] <= right + small_height * 0.4
                and bottom < mark.box[1] < bottom + small_height * 2
                and small_height * 0.3 <= mark.width <= right - left + small_height * 0.8
                and small_height * 0.2 <= mark.height <= small_height * 1.2
            ):
                continue
            beam_bottom = max((
                y for y in range(mark.box[1], min(mark.box[3],
                                                 mark.box[1] + round(small_height * 0.3)))
                if sum(_dark(gray, x, y) for x in range(mark.box[0], mark.box[2]))
                >= mark.width * 0.8
            ), default=mark.box[1] - 1)
            centers = []
            for y in (beam_bottom + 1, mark.box[3] - 1):
                xs = [x for x in range(mark.box[0], mark.box[2]) if _dark(gray, x, y)]
                if xs:
                    centers.append(sum(xs) / len(xs))
            if len(centers) == 2 and abs(centers[1] - centers[0]) >= max(1, small_height * 0.06):
                directions.append(centers[1] < centers[0])
        if not directions or len(set(directions)) != 1:
            continue
        post = directions[0]
        hosts = [
            index for index, box in enumerate(notes)
            if box[2] < left and left - box[2] <= height * 1.5
        ] if post else [
            index for index, box in enumerate(notes)
            if box[0] > right and box[0] - right <= height * 1.5
        ]
        if not hosts:
            continue
        host = min(hosts, key=lambda index: abs((notes[index][0] + notes[index][2]) / 2
                                              - (left + right) / 2))
        body = []
        for component, digit in group:
            center = (component.box[0] + component.box[2]) / 2
            # Sample the digit's central span, wide enough to exclude round octave dots.
            radius = max(component.width * 0.35, small_height * 0.25)
            beam_left = max(0, round(center - radius))
            beam_right = min(gray.width, round(center + radius) + 1)
            beam_rows = [
                y for y in range(bottom + 1, min(gray.height, bottom + round(small_height * 0.65)))
                if sum(_dark(gray, x, y) for x in range(beam_left, beam_right))
                >= (beam_right - beam_left) * 0.85
            ]
            if not beam_rows:
                break
            beams = 1 + sum(b - a > 1 for a, b in zip(beam_rows, beam_rows[1:], strict=False))
            dots = [
                mark for mark in components
                if 1 <= mark.width <= ceil(small_height * 0.35)
                and 1 <= mark.height <= ceil(small_height * 0.35)
                and mark.area >= mark.width * mark.height * 0.45
                and abs((mark.box[0] + mark.box[2]) / 2 - center) <= max(2, component.width * 0.3)
            ]
            above = sum(0 < component.box[1] - mark.box[3] <= small_height for mark in dots)
            below = sum(0 < mark.box[1] - beam_rows[-1] <= small_height for mark in dots)
            # A scan can join a round lower-octave dot to the connector through a thin neck.
            dot_size = ceil(small_height * 0.35)
            for mark in components:
                if not (0 < mark.box[1] - beam_rows[-1] <= small_height
                        and dot_size < mark.height <= small_height * 1.2
                        and abs(mark.box[0] - center) <= small_height * 0.4
                        and mark.box[2] <= right + small_height * 0.4):
                    continue
                head = [sum(_dark(gray, x, y) for x in range(mark.box[0], mark.box[2]))
                        for y in range(mark.box[1], mark.box[1] + dot_size)]
                width = max(head)
                if (small_height * 0.2 <= width <= dot_size
                        and head[0] < width and max(head[-2:]) <= width * 0.5
                        and sum(head) >= width * dot_size * 0.6):
                    below += 1
            if above and below:
                break
            body.append(digit + "'" * above + "," * below + "/" * (beams - 1))
        if len(body) != len(group):
            continue
        found.append(GraceGroup(
            host, "[" + ("h" if post else "") + "".join(body) + "]",
            (left, min(component.box[1] for component, _ in group), right,
             min(gray.height, bottom + round(small_height * 2))),
        ))
    return tuple(found)
