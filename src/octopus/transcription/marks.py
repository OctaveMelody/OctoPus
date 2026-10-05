"""Associate simple detached octave dots and duration lines with main digits."""

from __future__ import annotations

from collections import Counter
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
        and max(4, height * 0.15) <= component.height <= height
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
    components: list[Component], gray: Image.Image, barlines: tuple[int, ...] = (),
) -> tuple[tuple[int | None, int | None], ...]:
    found = list(_detached_row_slurs(notes, row_top, height, components, gray, barlines))
    fragment_spans: list[tuple[tuple[int | None, int | None], Box, Box, bool]] = []
    recovered: list[tuple[int | None, int | None]] = []
    recovered_fragments: list[
        tuple[tuple[int | None, int | None], Box]
    ] = []
    centers = [(box[0] + box[2]) / 2 for box in notes]
    for joined, fragments in _joined_curve_fragments(components, row_top, height):
        endpoint_tolerance = height * 1.5
        left_near_note = min(
            abs(center - joined.box[0]) for center in centers
        ) <= endpoint_tolerance
        right_near_note = min(
            abs(center - joined.box[2]) for center in centers
        ) <= endpoint_tolerance
        right_at_barline = bool(barlines) and abs(joined.box[2] - max(barlines)) <= height * 0.5
        if not left_near_note or not (right_near_note or right_at_barline):
            continue
        isolated = Image.new("L", gray.size, 255)
        for fragment in fragments:
            isolated.paste(gray.crop(fragment.box), fragment.box[:2])
        joined_spans = _detached_row_slurs(
            notes, row_top, height, [joined], isolated, barlines,
        )
        recovered.extend(joined_spans)
        recovered_fragments.extend((span, joined.box) for span in joined_spans)
        for fragment in fragments:
            for span in _detached_row_slurs(
                notes, row_top, height, [fragment], isolated, barlines,
            ):
                interval_count = (
                    span[1] - span[0]
                    if span[0] is not None and span[1] is not None else 0
                )
                fragment_spans.append((
                    span, fragment.box, joined.box,
                    _complete_curve_component(fragment, gray, height, interval_count),
                ))
    # A broken shallow curve can make each half look like a shorter slur. Once its
    # fragments reconnect into a wider span, keep that complete span alone.
    found_counts = Counter(found)
    for span, fragment_box, joined_box, complete_curve in fragment_spans:
        if span[0] is None or span[1] is None:
            continue
        if any(
            parent_start is not None and parent_end is not None
            and parent_start <= span[0] and span[1] <= parent_end
            and (parent_start, parent_end) != span
            and joined_box[0] <= fragment_box[0] < fragment_box[2] <= joined_box[2]
            and not complete_curve
            for (parent_start, parent_end), parent_box in recovered_fragments
            if parent_box == joined_box
        ):
            found_counts[span] = max(0, found_counts[span] - 1)
    found = list(found_counts.elements())
    parts, core = curve_core_parts(components, gray, row_top, height)
    recovered.extend(_detached_row_slurs(notes, row_top, height, parts, core, barlines))
    missing = Counter(recovered) - Counter(found)
    merged = found
    for pair in recovered:
        if missing[pair]:
            merged.append(pair)
            missing[pair] -= 1
    return tuple(merged)


def _complete_curve_component(
    component: Component, gray: Image.Image, height: float, interval_count: int,
) -> bool:
    """Keep a fragment span when its own ink has both ends of a shallow arch."""
    left, top, right, bottom = component.box
    width = right - left
    pixels = gray.load()
    assert pixels is not None
    edge = max(1, ceil(height * 0.08))
    samples = ((left, left + edge),
               (left + round(width * 0.4), left + round(width * 0.6)),
               (right - edge, right))
    tops = []
    for index, (start, end) in enumerate(samples):
        dark = [y for y in range(top, bottom) for x in range(start, end)
                if cast(int, pixels[x, y]) < 170]
        if not dark:
            return False
        tops.append(max(dark) if index != 1 else min(dark))
    rises = (tops[0] - tops[1], tops[2] - tops[1])
    if min(rises) < 1:
        return False
    return interval_count <= 1 or min(rises) >= ceil((bottom - top) * 0.4)


def _joined_curve_fragments(
    components: list[Component], row_top: int, height: float,
) -> tuple[tuple[Component, tuple[Component, ...]], ...]:
    """Reconnect thin curve segments interrupted by short scan gaps."""
    parts = sorted((component for component in components if (
        height * 0.8 <= component.width
        and max(2, height * 0.15) <= component.height <= height
        and component.area <= component.width * max(4, height * 0.2)
        and row_top - height * 2 < component.box[1] < row_top - height * 0.4
        and component.box[3] < row_top
    )), key=lambda component: component.box[0])
    joined = []
    for index, first in enumerate(parts):
        chain = [first]
        for candidate in parts[index + 1:]:
            previous = chain[-1]
            gap = candidate.box[0] - previous.box[2]
            if (0 <= gap <= max(2, height * 1.2)
                    and abs(previous.center_y - candidate.center_y) <= height * 0.6):
                chain.append(candidate)
        if len(chain) < 2:
            continue
        joined.append((Component((
            first.box[0], min(item.box[1] for item in chain),
            chain[-1].box[2], max(item.box[3] for item in chain),
        ), sum(item.area for item in chain)), tuple(chain)))
    return tuple(joined)


def _detached_row_slurs(
    notes: tuple[Box, ...], row_top: int, height: float,
    components: list[Component], gray: Image.Image, barlines: tuple[int, ...],
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
            and max(3, height * 0.15) <= bottom - top <= height
            and component.area <= width * max(4, height * 0.2)
            and row_top - height * 2 < top < row_top - height * 0.4
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
        for index, (start, end) in enumerate((
            (left, left + edge),
            (left + round(width * 0.4), left + round(width * 0.6)),
            (right - edge, right),
        )):
            dark = [
                y for y in range(top, bottom)
                for x in range(start, end)
                if cast(int, pixels[x, y]) < 170
            ]
            if not dark:
                break
            tops.append(max(dark) if index != 1 else min(dark))
        if len(tops) != 3:
            continue
        left_curves = tops[0] >= tops[1] + 2
        right_curves = tops[2] >= tops[1] + 2
        first_anchor = min(range(len(notes)), key=lambda index: abs(centers[index] - left))
        last_anchor = min(range(len(notes)), key=lambda index: abs(centers[index] - right))
        endpoint_tolerance = height * 2.5
        first_attached = abs(centers[first_anchor] - left) <= endpoint_tolerance
        last_attached = abs(centers[last_anchor] - right) <= endpoint_tolerance
        short_overlapped_end = (
            width <= height * 6 and first_attached and last_attached
            and left_curves != right_curves
        )
        vertical_ink = max(
            (sum(cast(int, pixels[x, y]) < 160 for y in range(top, bottom))
             for x in range(left, right)),
            default=0,
        )
        left_edge_cut = (
            first_anchor == last_anchor == 0 and left < notes[0][0]
            and right <= notes[0][2] + height * 0.5
            and width <= height * 3 and (left_curves or right_curves)
            and vertical_ink < height * 0.45
        )
        left_cut = left_edge_cut or (
            not left_curves and left <= notes[0][0] + height and right_curves
        )
        right_barline = bool(barlines) and (
            abs(right - max(barlines)) <= height * 0.5
            and right >= notes[-1][2] + height * 0.25
        )
        right_cut = (
            right_barline and left_curves
        )
        if not ((left_curves and right_curves) or short_overlapped_end or left_cut or right_cut):
            continue
        # Short overlapping arches can hide one curved end at their shared endpoint.
        first = (
            None if left_cut else first_anchor
            if (left_curves or short_overlapped_end) and first_attached else None
        )
        last = (
            None if right_cut else last_anchor
            if (right_curves or short_overlapped_end) and last_attached else None
        )
        # A printed slur can continue visually over extension dashes after its last
        # note. JPS spans notes, so attach a clearly curved trailing end to the outer
        # note instead of treating a dash as the endpoint.
        first_reaches_note = first is not None and (
            abs(centers[first] - left) <= endpoint_tolerance
            or first == 0 and left < centers[first] and tops[0] > tops[1]
        )
        last_reaches_note = last is not None and (
            abs(centers[last] - right) <= endpoint_tolerance
            or last == len(notes) - 1 and right > centers[last] and tops[2] > tops[1]
        )
        if (
            (first is None or last is None or first < last)
            and (first_reaches_note if first is not None
                 else left <= notes[0][0] + height)
            and (last_reaches_note if last is not None
                 else right >= notes[-1][2] - height)
        ):
            pairs.extend([(first, last)] * _parallel_curve_count(component, gray))
    return tuple(pairs)


def _parallel_curve_count(component: Component, gray: Image.Image) -> int:
    """Count distinct nested arches merged into one connected scan component."""
    left, top, right, bottom = component.box
    width = right - left
    step = max(1, width // 160)
    pixels = gray.load()
    assert pixels is not None
    profiles: list[tuple[int, list[float]]] = []
    for x in range(left + round(width * 0.18), right - round(width * 0.18), step):
        dark = [y for y in range(top, bottom) if cast(int, pixels[x, y]) < 160]
        runs: list[list[int]] = []
        for y in dark:
            if not runs or y > runs[-1][-1] + 1:
                runs.append([])
            runs[-1].append(y)
        profiles.append((x, [sum(run) / len(run) for run in runs]))
    if len(profiles) < 9:
        return 1

    for count in range(4, 1, -1):
        supported = [item for item in profiles if len(item[1]) >= count]
        if len(supported) < len(profiles) * 0.6:
            continue
        curved_layers = 0
        for layer in range(count):
            positions = [(x, ys[layer]) for x, ys in supported]
            left_y = [y for x, y in positions if x < left + width * 0.34]
            center_y = [y for x, y in positions
                        if left + width * 0.42 <= x <= left + width * 0.58]
            right_y = [y for x, y in positions if x > right - width * 0.34]
            if (left_y and center_y and right_y
                    and (median(left_y) + median(right_y)) / 2 - median(center_y) >= 1):
                curved_layers += 1
        if curved_layers == count:
            return count
    return 1


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
                count, has_dot = _joined_underline_and_dot(note, fused, gray, digit_height)
                if count and not has_dot:
                    joined_lines += count
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
    existing_duration_boxes = [component.box for component in lines]
    existing_duration_boxes.extend(box for box in used_joined)
    faint_bands: list[tuple[int, int, int]] = []
    if gray is not None:
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
    return (octave, len(lines) + joined_lines + sum(count for _, _, count in faint_bands),
            len(duration_dots), used)
