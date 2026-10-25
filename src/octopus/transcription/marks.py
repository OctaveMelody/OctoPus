"""Associate simple detached octave dots and duration lines with main digits."""

from __future__ import annotations

from math import ceil
from statistics import correlation, linear_regression, median
from typing import cast

from PIL import Image

from . import slurs
from .components import Box, Component, connected_components

curve_core_parts = slurs.curve_core_parts
row_slurs = slurs.row_slurs
_left_curve_rise = slurs._left_curve_rise
_faint_curve_bridges = slurs._faint_curve_bridges


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
) -> tuple[int, bool, tuple[float, ...]]:
    """Read a shallow underline blob whose low octave dots touch the stroke."""
    left, _, right, bottom = note
    if not (
        component.width >= digit_height * 1.3
        and component.height <= digit_height * 0.6
        and _overlap(left, right, component.box[0], component.box[2]) >= (right - left) * 0.65
    ):
        return 0, False, ()
    pixels = gray.load()
    assert pixels is not None
    columns = [(x, [y for y in range(component.box[1], component.box[3])
                    if cast(int, pixels[x, y]) < 160])
               for x in range(component.box[0], component.box[2])]
    columns = [(x, ys) for x, ys in columns if ys]
    local_ink = [y for x, ys in columns if left <= x < right for y in ys]
    if not local_ink or not 0 <= min(local_ink) - bottom <= digit_height * 0.5:
        return 0, False, ()
    wide_rows = [
        y for y in range(component.box[1], component.box[3])
        if sum(cast(int, pixels[x, y]) < 160 for x in range(component.box[0], component.box[2]))
        >= component.width * 0.7
    ]
    if not wide_rows:
        return 0, False, ()
    horizontal_rows = []
    for y in range(component.box[1], component.box[3]):
        if (sum(cast(int, pixels[x, y]) < 160
                for x in range(max(left, component.box[0]), min(right, component.box[2])))
                < (right - left) * 0.65):
            continue
        start = component.box[0]
        for x in range(component.box[0], component.box[2] + 1):
            if x < component.box[2] and cast(int, pixels[x, y]) < 160:
                continue
            if x - start >= max(10, round((right - left) * 0.65)):
                horizontal_rows.append(y)
                break
            start = x + 1
    local_rows = set(horizontal_rows)
    minimum_local_run = max(2, round((right - left) * 0.65))
    for y in wide_rows:
        run_start = None
        longest_run = 0
        for x in range(max(left, component.box[0]), min(right, component.box[2])):
            if cast(int, pixels[x, y]) < 210:
                run_start = x if run_start is None else run_start
                longest_run = max(longest_run, x - run_start + 1)
            else:
                run_start = None
        if longest_run >= minimum_local_run:
            local_rows.add(y)
    local_bands: list[list[int]] = []
    for y in sorted(local_rows):
        if not local_bands or y > local_bands[-1][-1] + 1:
            local_bands.append([])
        local_bands[-1].append(y)
    local_centers = tuple((band[0] + band[-1]) / 2 for band in local_bands)
    horizontal_rows = horizontal_rows or wide_rows
    line_count = max(1 + sum(right_y - left_y > 1
                            for left_y, right_y in zip(rows, rows[1:], strict=False))
                     for rows in (wide_rows, horizontal_rows))
    center = (left + right) / 2
    radius = max(4, (right - left) * 0.35)
    # Only ink below the local last tier is a dot; tilted tails and short tiers remain beams.
    dot_rows = {y for x, ys in columns if abs(x - center) <= radius for y in ys
                if y > max(horizontal_rows[-1], wide_rows[-1])}
    return line_count, len(dot_rows) >= 2, local_centers


def _joined_duration_bands(
    note: Box, component: Component, gray: Image.Image, digit_height: int,
    barlines: tuple[int, ...], threshold: int = 160,
) -> list[list[tuple[int, int, int]]] | None:
    """Separate long, thin stroke bands while ignoring bridges between scanned beams."""
    left, _, right, bottom = note
    if not (
        component.width >= digit_height * 1.3
        and not any(component.box[0] < bar < component.box[2] for bar in barlines)
        and component.height <= digit_height * 0.6
        and 0 < component.box[1] - bottom <= digit_height * 0.72
        and _overlap(left, right, component.box[0], component.box[2]) >= (right - left) * 0.65
    ):
        return None
    pixels = gray.load()
    assert pixels is not None
    minimum_stroke_width = max(10, round((right - left) * 0.65))
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
            if (width >= minimum_stroke_width
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
        return _joined_duration_bands(note, component, gray, digit_height, barlines, threshold // 2)
    if (not spans_component or not 1 <= len(bands) <= 4
            or any(len(band) > max(4, digit_height * 0.17) for band in bands)):
        return None
    return bands


def _joined_duration_lines(
    note: Box, component: Component, gray: Image.Image, digit_height: int,
    barlines: tuple[int, ...], threshold: int = 160,
) -> int:
    bands = _joined_duration_bands(note, component, gray, digit_height, barlines, threshold)
    return len(bands) if bands is not None else 0


def _dark_core_duration_bands(
    note: Box, component: Component, gray: Image.Image, digit_height: int,
    candidate_band: tuple[int, int],
) -> tuple[tuple[int, int], ...]:
    """Find separated dark horizontal rows inside one validated joined-beam band."""
    left, _, right, bottom = note
    minimum_run = ceil((right - left) * 0.65)
    first = max(bottom + 1, candidate_band[0], component.box[1])
    last = min(bottom + round(digit_height * 0.6), candidate_band[1], component.box[3] - 1)
    if minimum_run <= 0 or last < first:
        return ()
    supported_rows = []
    for y in range(first, last + 1):
        run = longest = 0
        for x in range(left, right):
            if cast(int, gray.getpixel((x, y))) < 80:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        if longest >= minimum_run:
            supported_rows.append(y)
    groups: list[list[int]] = []
    for y in supported_rows:
        if groups and y == groups[-1][-1] + 1:
            groups[-1].append(y)
        else:
            groups.append([y])
    maximum_thickness = max(4, round(digit_height * 0.17))
    return tuple(
        (rows[0], rows[-1]) for rows in groups
        if 2 <= len(rows) <= maximum_thickness
    )


def _add_duration_band(bands: list[tuple[int, int]], candidate: tuple[int, int]) -> None:
    """Merge overlapping band observations so one physical stroke counts once."""
    first, last = candidate
    index = 0
    while index < len(bands):
        previous_first, previous_last = bands[index]
        if max(first, previous_first) <= min(last, previous_last):
            first = min(first, previous_first)
            last = max(last, previous_last)
            bands.pop(index)
            index = 0
        else:
            index += 1
    bands.append((first, last))


def _local_duration_tiers(
    note: Box, gray: Image.Image, digit_height: int, barlines: tuple[int, ...],
    required: int, confirmed_centers: tuple[float, ...] = (),
) -> int:
    """Count joined beam tiers only where their own bands reach the note."""
    left, _, right, bottom = note
    top = min(gray.height, bottom + 1)
    # Joined beams can continue below the first-tier search window. The candidate
    # itself must start nearby and remain compact in _joined_duration_bands.
    lower = min(gray.height, bottom + round(digit_height * 1.32) + 1)
    if lower <= top or right <= left:
        return 0
    minimum_columns = max(2, round((right - left) * 0.12))
    supported_centers: list[float] = []
    for center in confirmed_centers:
        if not any(abs(center - previous) <= max(1, digit_height * 0.1)
                   for previous in supported_centers):
            supported_centers.append(center)
    dark_bands: list[tuple[int, int]] = []
    crop_box = (
        max(0, left - digit_height * 3), top,
        min(gray.width, right + digit_height * 3), lower,
    )
    for component in connected_components(gray.crop(crop_box), 210):
        box = (component.box[0] + crop_box[0], component.box[1] + crop_box[1],
               component.box[2] + crop_box[0], component.box[3] + crop_box[1])
        candidate = Component(box, component.area)
        for threshold in (160, 210):
            joined = _joined_duration_bands(
                note, candidate, gray, digit_height, barlines, threshold,
            )
            if joined is None:
                continue
            for band in joined:
                first, last = band[0][0], band[-1][0]
                for dark_band in _dark_core_duration_bands(
                    note, candidate, gray, digit_height, (first, last),
                ):
                    _add_duration_band(dark_bands, dark_band)
                if any(
                    sum(cast(int, gray.getpixel((x, y))) < 210 for x in range(left, right))
                    >= minimum_columns
                    for y in range(first, last + 1)
                ):
                    center = (first + last) / 2
                    if not any(abs(center - previous) <= max(1, digit_height * 0.1)
                               for previous in supported_centers):
                        supported_centers.append(center)
    confirmed = min(required, len(supported_centers))
    if confirmed >= required:
        return min(4, confirmed)
    return min(4, required, max(confirmed, len(dark_bands)))


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
    bridged_lines = 0
    clipped_candidates: list[Component] = []
    clipped_duration_total = 0
    joined_local_centers: list[float] = []
    joined_dot_boxes: set[Box] = set()
    used_joined: set[Box] = set()
    bridged: set[Box] = set()
    if gray is not None:
        # A faint two-pixel break near a beam's end can isolate a short fragment
        # that resembles a low octave dot. Corroborate it against the collinear
        # long stroke, using the original pixels and preserving every owned box.
        for line in components:
            if line.box in bridged or not (line.width >= digit_height * 1.3
                    and line.height <= max(4, digit_height * 0.17)):
                continue
            for stub in components:
                if (stub.box == line.box or stub.box in bridged
                        or not 3 <= stub.width <= digit_height * 0.6
                        or stub.height > max(4, digit_height * 0.17)
                        or not 0 <= stub.box[0] - line.box[2] <= digit_height * 0.15
                        or abs(stub.center_y - line.center_y) > digit_height * 0.12):
                    continue
                box = (line.box[0], min(line.box[1], stub.box[1]), stub.box[2],
                       max(line.box[3], stub.box[3]))
                if any(box[0] < bar < box[2] for bar in barlines):
                    continue
                fused = Component(box, line.area + stub.area)
                count, has_dot, local_centers = _joined_underline_and_dot(
                    note, fused, gray, digit_height,
                )
                if count and not has_dot:
                    joined_lines += count
                    bridged_lines += count
                    joined_local_centers.extend(local_centers)
                    bridged.update((line.box, stub.box))
                    used_joined.update((line.box, stub.box))
                    break
    dot_reach = digit_height * (0.55 if gray is not None else 0.8)
    line_reach = digit_height * (0.55 if gray is not None else 0.72)
    for component in components:
        if component.box == note:
            continue
        if component.box in bridged:
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
            and top + (bottom - top) * 0.25 <= component.center_y <= bottom
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
            and component.width >= max(10, round((right - left) * 0.65))
            and _overlap(left, right, c_left, c_right) >= (right - left) * 0.65
        ):
            joined = (_joined_duration_bands(
                note, component, duration_gray, digit_height, barlines,
            ) if duration_gray is not None else None)
            count = len(joined) if joined is not None else 0
            if count > 1:
                joined_lines += count
                joined_local_centers.extend(
                    (band[0][0] + band[-1][0]) / 2 for band in joined
                )
                used_joined.add(component.box)
            else:
                lines.append(component)
        elif gray is not None:
            count, has_dot, local_centers = _joined_underline_and_dot(
                note, component, gray, digit_height,
            )
            if count:
                joined_lines += count
                joined_local_centers.extend(local_centers)
                if has_dot:
                    joined_dot_boxes.add(component.box)
                used_joined.add(component.box)
            elif (
                duration_gray is not None
                and c_top <= bottom < c_bottom
                and component.width >= digit_height * 1.3
                and component.height <= digit_height * 0.6
                and c_bottom - bottom <= digit_height * 0.72
                and not any(c_left < bar < c_right for bar in barlines)
                and _overlap(left, right, c_left, c_right) >= (right - left) * 0.65
            ):
                clipped_candidates.append(component)
                used_joined.add(component.box)
        elif duration_gray is not None:
            joined = _joined_duration_bands(
                note, component, duration_gray, digit_height, barlines,
            )
            count = len(joined) if joined is not None else 0
            if count:
                joined_lines += count
                joined_local_centers.extend(
                    (band[0][0] + band[-1][0]) / 2 for band in joined
                )
                used_joined.add(component.box)
    # Above and below marks on one digit are ambiguous; keep them for review.
    if dots_above and dots_below:
        dots_above.clear()
        dots_below.clear()
    if len(lines) > 4:
        lines.clear()
    if clipped_candidates and duration_gray is not None:
        clipped_centers = [*joined_local_centers, *(line.center_y for line in lines)]
        clipped_centers = [center for center in clipped_centers
                           if bottom < center <= bottom + round(digit_height * 0.6)]
        clipped_duration_total = _local_duration_tiers(
            note, duration_gray, digit_height, barlines, 4, tuple(clipped_centers),
        )
    if len(duration_dots) > 2:
        duration_dots.clear()
    existing_duration_boxes = [component.box for component in lines]
    existing_duration_boxes.extend(box for box in used_joined)
    faint_bands: list[tuple[int, int, int]] = []
    if gray is not None:
        # A faded beam may have only tiny dark islands, so no long component can
        # seed the continuation rule below. Require dark ink on the same visible band.
        crop_box = (max(0, left - digit_height * 3), min(gray.height, bottom + 1),
                    min(gray.width, right_limit + digit_height if right_limit is not None
                        else right + digit_height * 3),
                    min(gray.height, bottom + round(digit_height * 0.55)))
        for part in connected_components(gray.crop(crop_box), 200):
            # A line continuing beyond this local window can be another voice's
            # slur, rather than a bounded duration beam belonging to this note.
            if part.box[0] == 0 or part.box[2] == crop_box[2] - crop_box[0]:
                continue
            box = (part.box[0] + crop_box[0], part.box[1] + crop_box[1],
                   part.box[2] + crop_box[0], part.box[3] + crop_box[1])
            if any(max(box[1], top) < min(box[3], bottom)
                   for _, top, _, bottom in existing_duration_boxes):
                continue
            dark_columns = sum(any(cast(int, gray.getpixel((x, y))) < 160
                                   for y in range(box[1], box[3]))
                               for x in range(box[0], box[2]))
            if dark_columns < part.width * 0.12:
                continue
            count = _joined_duration_lines(
                note, Component(box, part.area), gray, digit_height, barlines, 200,
            )
            if count:
                faint_bands.append((box[1], box[3], count))
                used_joined.update(component.box for component in components if (
                    box[0] <= component.box[0] and component.box[2] <= box[2]
                    and box[1] <= component.box[1] and component.box[3] <= box[3]
                ))
        for component in components:
            if not (component.width >= max(10, round((right - left) * 0.8))
                    and component.height <= max(4, digit_height * 0.17)
                    and 0 < component.box[1] - bottom <= digit_height * 0.55
                    and (0 < component.box[0] - right <= digit_height * 1.2
                         or 0 < left - component.box[2] <= digit_height * 1.2)):
                continue
            # Recover only a faint continuation of an independently dark beam,
            # never an unsupported grey rule under a quarter note.
            box = (min(left, component.box[0]), component.box[1],
                   max(right, component.box[2]), component.box[3])
            count = _joined_duration_lines(
                note, Component(box, component.area), gray, digit_height, barlines, 210,
            )
            if count:
                used_joined.add(component.box)
                if any(max(top, component.box[1]) < min(bottom, component.box[3])
                       for _, top, _, bottom in existing_duration_boxes):
                    continue
                overlap = next((index for index, (top, bottom, _) in enumerate(faint_bands)
                                if max(top, component.box[1]) < min(bottom, component.box[3])),
                               None)
                if overlap is None:
                    faint_bands.append((component.box[1], component.box[3], count))
                else:
                    band_top, band_bottom, previous_count = faint_bands[overlap]
                    faint_bands[overlap] = (min(band_top, component.box[1]),
                                            max(band_bottom, component.box[3]),
                                            max(previous_count, count))
    # Dark islands in a confirmed faded beam are stroke ink, not octave dots.
    dots_below = [dot for dot in dots_below if dot.box not in used_joined]
    # Global pixels inside a joined beam's bounds can include an already detached dot.
    # Count that physical mark once, while retaining a second dot outside those bounds.
    joined_dot = any(not any(
        left <= (dot.box[0] + dot.box[2]) / 2 < right
        and top <= dot.center_y < bottom
        for dot in dots_below
    ) for left, top, right, bottom in joined_dot_boxes)
    octave = len(dots_above) - len(dots_below) - int(joined_dot)
    remaining_joined_lines = joined_lines - bridged_lines
    if remaining_joined_lines > 0 and duration_gray is not None:
        joined_lines = bridged_lines + _local_duration_tiers(
            note, duration_gray, digit_height, barlines, remaining_joined_lines,
            tuple(joined_local_centers),
        )
    base_slashes = len(lines) + joined_lines + sum(count for _, _, count in faint_bands)
    slash_count = max(base_slashes, clipped_duration_total)
    used = {
        component.box for component in (*dots_above, *dots_below, *duration_dots, *lines)
    }
    used.update(used_joined)
    return (octave, slash_count, len(duration_dots), used)
