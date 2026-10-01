"""Associate simple detached octave dots and duration lines with main digits."""

from __future__ import annotations

from math import ceil
from statistics import correlation, linear_regression, median
from typing import cast

from PIL import Image

from .components import Box, Component, connected_components


def vertical_bend(component: Component, gray: Image.Image) -> float | None:
    """Measure a vertical stroke's middle against its two ends, preserving scan tilt."""
    pixels = gray.load()
    assert pixels is not None
    left, top, right, _ = component.box
    centers = []
    for start, end in ((0.0, 0.2), (0.4, 0.6), (0.8, 1.0)):
        xs = [x for y in range(top + round(component.height * start),
                              top + round(component.height * end))
              for x in range(left, right) if cast(int, pixels[x, y]) < 160]
        if not xs:
            return None
        centers.append(sum(xs) / len(xs))
    return centers[1] - (centers[0] + centers[2]) / 2


def curve_core_parts(
    components: list[Component], gray: Image.Image, row_top: int, height: float,
) -> tuple[list[Component], Image.Image]:
    """Separate dark ink where grey scan bridges join a long curve to octave dots."""
    compounds = [component for component in components if (
        component.width >= height * 1.8
        and 3 <= component.height <= height
        and row_top - height * 2.5 < component.box[1] < row_top - height * 0.4
        and component.box[3] < row_top
        and component.area > component.width * max(4, height * 0.2)
    )]
    if not compounds:
        return [], gray
    core = gray.point(lambda value: 0 if value < 60 else 255)
    parts: list[Component] = []
    for component in compounds:
        left, top, _, _ = component.box
        separated = [Component((left + part.box[0], top + part.box[1],
                                left + part.box[2], top + part.box[3]), part.area)
                     for part in connected_components(core.crop(component.box))]
        # A bridge must actually split; darkening one unchanged mark is not new evidence.
        if sum(part.area >= 3 for part in separated) >= 2:
            parts.extend(separated)
    return parts, core


def row_slurs(
    notes: tuple[Box, ...], row_top: int, height: float,
    components: list[Component], gray: Image.Image,
) -> tuple[tuple[int | None, int | None], ...]:
    found = _detached_row_slurs(notes, row_top, height, components, gray)
    parts, core = curve_core_parts(components, gray, row_top, height)
    recovered = _detached_row_slurs(notes, row_top, height, parts, core)
    return tuple(dict.fromkeys((*found, *recovered)))


def _detached_row_slurs(
    notes: tuple[Box, ...], row_top: int, height: float,
    components: list[Component], gray: Image.Image,
) -> tuple[tuple[int | None, int | None], ...]:
    """Attach curved ends to music events; a flat cut end continues on another row."""
    if len(notes) < 2:
        return ()
    centers = [(box[0] + box[2]) / 2 for box in notes]
    pixels = gray.load()
    assert pixels is not None
    pairs: list[tuple[int | None, int | None]] = []
    for component in components:
        left, top, right, bottom = component.box
        width = right - left
        if not (
            height * 0.8 <= width <= gray.width
            and 3 <= bottom - top <= height
            and component.area <= width * max(4, height * 0.2)
            and row_top - height * 2.5 < top < row_top - height * 0.4
            and bottom < row_top
        ):
            continue
        if width <= height * 2 and component.area > width * max(6, height * 0.16):
            branched = 0
            for x in range(left, right):
                runs = 0
                previous = False
                for y in range(top, bottom):
                    dark_pixel = cast(int, pixels[x, y]) < 160
                    runs += int(dark_pixel and not previous)
                    previous = dark_pixel
                branched += int(runs > 1)
            if branched > width * 0.5:
                continue
        tops = []
        edge = max(1, ceil(height * 0.08))
        for start, end in ((left, left + edge),
                           (left + round(width * 0.4), left + round(width * 0.6)),
                           (right - edge, right)):
            dark = [
                y for y in range(top, bottom)
                for x in range(start, end)
                if cast(int, pixels[x, y]) < 170
            ]
            if not dark:
                break
            tops.append(min(dark))
        if len(tops) != 3 or not (
            min(tops[0], tops[2]) >= tops[1]
            and max(tops[0], tops[2]) >= tops[1] + 1
        ):
            continue
        first_anchor = min(range(len(notes)), key=lambda index: abs(centers[index] - left))
        last_anchor = min(range(len(notes)), key=lambda index: abs(centers[index] - right))
        # Short overlapping arches can hide one curved end at their shared endpoint.
        first = first_anchor if (tops[0] > tops[1] or width <= height * 6
                                 and abs(centers[first_anchor] - left) <= height) else None
        last = last_anchor if (tops[2] > tops[1] or width <= height * 6
                               and abs(centers[last_anchor] - right) <= height) else None
        if (
            (first is None or last is None or first < last)
            and (abs(centers[first] - left) <= height if first is not None
                 else left <= notes[0][0] + height)
            and (abs(centers[last] - right) <= height if last is not None
                 else right >= notes[-1][2] - height)
        ):
            pairs.append((first, last))
    return tuple(dict.fromkeys(pairs))


def row_sustains(notes: tuple[Box, ...], marks: tuple[Box, ...]) -> tuple[Box, ...]:
    """Share sustain ownership between mark recognition and the JPS compiler."""
    height = median(box[3] - box[1] for box in notes)
    digit_width = median(box[2] - box[0] for box in notes)
    xs = [(box[0] + box[2]) / 2 for box in notes]
    ys = [(box[1] + box[3]) / 2 for box in notes]
    slope, intercept = linear_regression(xs, ys) if len(set(xs)) > 1 else (0, ys[0])
    return tuple(box for box in marks if (
        digit_width * 0.5 <= box[2] - box[0] <= height * 1.5
        and box[2] - box[0] >= (box[3] - box[1]) * 2
        and box[3] - box[1] <= max(4, height * 0.3)
        and box[2] >= min(note[0] for note in notes) - height * 1.5
        and not any(other != box
                    and abs(other[0] - box[0]) <= digit_width * 0.15
                    and abs(other[2] - box[2]) <= digit_width * 0.15
                    and 0 < abs(other[1] - box[1]) <= height * 0.5
                    and other[3] - other[1] <= max(4, height * 0.3)
                    for other in marks)
        and abs((box[1] + box[3]) / 2 - (slope * (box[0] + box[2]) / 2 + intercept))
        <= height * 0.35
    ))


def row_parentheses(
    notes: tuple[Box, ...], height: float,
    components: list[Component], gray: Image.Image,
) -> tuple[tuple[int, str], ...]:
    """Attach tall curved accompaniment brackets, excluding straight bars and voice braces."""
    found = []
    for component in components:
        if not (height * 0.9 <= component.height <= height * 2.2
                and component.width <= height * 0.65
                and component.area <= component.width * component.height * 0.6
                and not any(box[0] <= (component.box[0] + component.box[2]) / 2 <= box[2]
                            and box[1] <= component.center_y <= box[3] for box in notes)):
            continue
        bend = vertical_bend(component, gray)
        if bend is None or abs(bend) < max(1.25, component.width * 0.25):
            continue
        opens = bend < 0
        owners = [
            (index, box[0] - component.box[2] if opens else component.box[0] - box[2])
            for index, box in enumerate(notes)
        ]
        nearby = []
        for index, gap in owners:
            neighbors = notes[max(0, index - 1):index] + notes[index + 1:index + 2]
            spacing = max((abs(box[0] - notes[index][0]) for box in neighbors), default=0)
            if (0 <= gap <= max(height * 1.3, spacing)
                    and abs(component.center_y - (notes[index][1] + notes[index][3]) / 2)
                    <= height * 0.5):
                nearby.append((index, gap))
        if nearby:
            owner = min(nearby, key=lambda item: item[1])[0]
            found.append((owner, "&zkh" if opens else "&ykh"))
    return tuple(found)


def _overlap(left: int, right: int, other_left: int, other_right: int) -> int:
    return max(0, min(right, other_right) - max(left, other_left))


def _inside_fermata_dot(dot: Component, components: list[Component], digit_width: int) -> bool:
    center = (dot.box[0] + dot.box[2]) / 2
    return any(
        mark.box != dot.box
        and mark.width >= digit_width * 0.9
        and mark.width <= digit_width * 2.5
        and mark.box[0] < center < mark.box[2]
        and mark.box[1] <= dot.box[1]
        and mark.box[3] >= dot.box[3]
        for mark in components
    )


def _joined_underline_and_dot(
    note: Box, component: Component, gray: Image.Image, digit_height: int
) -> tuple[int, bool]:
    """Read a shallow underline blob whose low octave dots touch the stroke."""
    left, _, right, bottom = note
    if not (
        component.width >= digit_height * 1.3
        and component.height <= digit_height * 0.6
        and 0 < component.box[1] - bottom <= digit_height * 0.5
        and _overlap(left, right, component.box[0], component.box[2]) >= (right - left) * 0.65
    ):
        return 0, False
    pixels = gray.load()
    assert pixels is not None
    horizontal_rows = [
        y for y in range(component.box[1], component.box[3])
        if sum(cast(int, pixels[x, y]) < 160 for x in range(component.box[0], component.box[2]))
        >= component.width * 0.7
    ]
    if not horizontal_rows:
        return 0, False
    line_count = 1 + sum(
        right_y - left_y > 1
        for left_y, right_y in zip(horizontal_rows, horizontal_rows[1:], strict=False)
    )
    center = (left + right) / 2
    radius = max(4, (right - left) * 0.35)
    dot_rows = [
        y for y in range(horizontal_rows[-1] + 1, component.box[3])
        if any(
            cast(int, pixels[x, y]) < 160
            for x in range(max(component.box[0], round(center - radius)),
                           min(component.box[2], round(center + radius) + 1))
        )
    ]
    return line_count, len(dot_rows) >= 2


def _joined_duration_lines(
    note: Box, component: Component, gray: Image.Image, digit_height: int,
    barlines: tuple[int, ...], threshold: int = 160,
) -> int:
    """Separate long, thin stroke bands while ignoring bridges between scanned beams."""
    left, _, right, bottom = note
    if not (
        component.width >= digit_height * 1.3
        and not any(component.box[0] < bar < component.box[2] for bar in barlines)
        and component.height <= digit_height * 0.6
        and 0 < component.box[1] - bottom <= digit_height * 0.72
        and _overlap(left, right, component.box[0], component.box[2]) >= (right - left) * 0.65
    ):
        return 0
    pixels = gray.load()
    assert pixels is not None
    stroke_rows: list[tuple[int, int, int]] = []
    spans_component = False
    for y in range(component.box[1], component.box[3]):
        run_start = component.box[0]
        stroke_span = None
        for x in range(component.box[0], component.box[2] + 1):
            if x < component.box[2] and cast(int, pixels[x, y]) < threshold:
                continue
            width = x - run_start
            spans_component |= width >= component.width * 0.7
            if (width >= max(10, digit_height * 1.5)
                    and _overlap(left, right, run_start, x) >= (right - left) * 0.65):
                stroke_span = (run_start, x)
            run_start = x + 1
        if stroke_span is not None:
            stroke_rows.append((y, *stroke_span))
    bands: list[list[tuple[int, int, int]]] = []
    for stroke in stroke_rows:
        if (not bands or stroke[0] > bands[-1][-1][0] + 1
                or max(stroke[1] - bands[-1][-1][1], bands[-1][-1][2] - stroke[2])
                > digit_height * 0.5):
            bands.append([])
        bands[-1].append(stroke)
    for index in range(len(bands) - 1, 0, -1):
        # A one-row contraction is a ragged stroke edge, not another duration tier.
        if len(bands[index]) == 1 and bands[index][0][0] == bands[index - 1][-1][0] + 1:
            bands[index - 1].extend(bands.pop(index))
    if any(len(band) > max(4, digit_height * 0.17) for band in bands) and threshold == 160:
        # Dark cores can separate beams whose grey scan bridges join at the ordinary cutoff.
        return _joined_duration_lines(note, component, gray, digit_height, barlines, threshold // 2)
    if (not spans_component or not 1 <= len(bands) <= 4
            or any(len(band) > max(4, digit_height * 0.17) for band in bands)):
        return 0
    return len(bands)


def note_modifiers(
    note: Box, components: list[Component], digit_height: int,
    gray: Image.Image | None = None, right_limit: int | None = None,
    *, duration_gray: Image.Image | None = None, barlines: tuple[int, ...] = (),
) -> tuple[int, int, int, set[Box]]:
    """Return octave, duration slashes/dots and used boxes for a main digit."""
    left, top, right, bottom = note
    center = (left + right) / 2
    dots_above: list[Component] = []
    dots_below: list[Component] = []
    duration_dots: list[Component] = []
    lines: list[Component] = []
    joined_lines = 0
    joined_dot_boxes: set[Box] = set()
    used_joined: set[Box] = set()
    dot_reach = digit_height * (0.55 if gray is not None else 0.8)
    line_reach = digit_height * (0.55 if gray is not None else 0.72)
    for component in components:
        if component.box == note:
            continue
        c_left, c_top, c_right, c_bottom = component.box
        round_dot = (
            3 <= component.width <= digit_height * 0.32
            and 3 <= component.height <= digit_height * 0.32
            and component.area >= component.width * component.height * 0.45
        )
        dot_image = gray if gray is not None else duration_gray
        if round_dot and dot_image is not None:
            ink = [(x, y) for x in range(c_left, c_right) for y in range(c_top, c_bottom)
                   if cast(int, dot_image.getpixel((x, y))) < 160]
            if ink:
                xs, ys = zip(*ink, strict=True)
                round_dot = (len(set(xs)) > 1 and len(set(ys)) > 1
                             and abs(correlation(xs, ys)) <= 0.6)
            else:
                round_dot = False
        if round_dot and _inside_fermata_dot(component, components, right - left):
            continue
        dot = round_dot and (
            abs((c_left + c_right) / 2 - center) <= max(4, (right - left) * 0.23)
        )
        if dot and 0 < top - c_bottom <= dot_reach:
            dots_above.append(component)
        elif dot and 0 < c_top - bottom <= dot_reach:
            dots_below.append(component)
        elif (
            round_dot and 0 < c_left - right <= digit_height * 0.8
            and abs((c_top + c_bottom - top - bottom) / 2) <= digit_height * 0.25
            and (right_limit is None or c_right < right_limit)
            and not any(
                other.box != component.box
                and 3 <= other.width <= digit_height * 0.32
                and 3 <= other.height <= digit_height * 0.32
                and abs(other.box[0] - c_left) <= digit_height * 0.15
                and digit_height * 0.2 <= abs(other.center_y - component.center_y)
                <= digit_height * 0.9
                for other in components
            )
        ):
            duration_dots.append(component)
        elif (
            0 < c_top - bottom <= line_reach
            and component.height <= max(4, digit_height * 0.17)
            and component.width >= max(10, round((right - left) * 0.8))
            and _overlap(left, right, c_left, c_right) >= (right - left) * 0.65
        ):
            lines.append(component)
        elif gray is not None:
            count, has_dot = _joined_underline_and_dot(note, component, gray, digit_height)
            if count:
                joined_lines += count
                if has_dot:
                    joined_dot_boxes.add(component.box)
                used_joined.add(component.box)
        elif duration_gray is not None:
            count = _joined_duration_lines(note, component, duration_gray, digit_height, barlines)
            if count:
                joined_lines += count
                used_joined.add(component.box)
    # Above and below marks on one digit are ambiguous; keep them for review.
    if dots_above and dots_below:
        dots_above.clear()
        dots_below.clear()
    if len(lines) > 4:
        lines.clear()
    if len(duration_dots) > 2:
        duration_dots.clear()
    # Global pixels inside a joined beam's bounds can include an already detached dot.
    # Count that physical mark once, while retaining a second dot outside those bounds.
    joined_dot = any(not any(
        left <= (dot.box[0] + dot.box[2]) / 2 < right
        and top <= dot.center_y < bottom
        for dot in dots_below
    ) for left, top, right, bottom in joined_dot_boxes)
    octave = len(dots_above) - len(dots_below) - int(joined_dot)
    used = {
        component.box for component in (*dots_above, *dots_below, *duration_dots, *lines)
    }
    used.update(used_joined)
    return octave, len(lines) + joined_lines, len(duration_dots), used
