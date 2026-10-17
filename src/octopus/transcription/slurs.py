"""Recognize slurs and recover connected or broken curve ink."""

from __future__ import annotations

from collections import Counter
from math import ceil
from statistics import median
from typing import cast

from PIL import Image

from .components import Box, Component, connected_components


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
    joined_ink: dict[tuple[int | None, int | None], set[Box]] = {}
    for joined, fragments in _joined_curve_fragments(components, row_top, height):
        # Independently complete neighboring arches are separate marks, not fragments.
        if all(_complete_curve_component(part, gray, height, 2) for part in fragments):
            continue
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
        if any(fragment.height < max(2, height * 0.15) for fragment in fragments):
            apex_supported = _short_fragments_form_curve_apex(fragments, gray, height)
            joined_spans = tuple(span for span in joined_spans if (
                apex_supported or span[0] is None and span[1] is not None
                and any(existing_end == span[1] for _, existing_end in found)
            ))
        joined_spans = _split_curve_at_cusps(notes, joined, isolated, height, joined_spans)
        joined_spans = tuple(span for span in joined_spans if not any(
            part.box in joined_ink.get(span, set()) for part in fragments
        ))
        for span in joined_spans:
            joined_ink.setdefault(span, set()).update(part.box for part in fragments)
        joined_spans = tuple(span for span in joined_spans if not any(
            existing == span and box[0] <= joined.box[0] and joined.box[2] <= box[2]
            and box[1] <= joined.box[1] and joined.box[3] <= box[3]
            for existing, box in recovered_fragments
        ))
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
                    _complete_curve_component(
                        fragment, gray, height,
                        max(2, interval_count),
                    ),
                ))
    # A broken shallow curve can make each half look like a shorter slur. Once its
    # fragments reconnect into a wider span, keep that complete span alone.
    found_counts = Counter(found)
    for span, fragment_box, joined_box, complete_curve in fragment_spans:
        if any(
            (parent_start if parent_start is not None else -1)
            <= (span[0] if span[0] is not None else -1)
            and (span[1] if span[1] is not None else len(notes))
            <= (parent_end if parent_end is not None else len(notes))
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
    for component in components:
        for span in _detached_row_slurs(notes, row_top, height, [component], gray, barlines):
            nested = Counter(_nested_shorter_slurs(notes, height, component, gray, span))
            recovered.extend((nested - (Counter(found) | Counter(recovered))).elements())
    recovered.extend(_head_parallel_slurs(
        notes, row_top, height, components, gray, barlines, (*found, *recovered),
        recovered_fragments,
    ))
    faint_curves = _faint_curve_bridges(notes, components, gray, row_top, height, barlines)
    # A complete, reconnected arch supersedes only the incomplete pieces of its own ink.
    for parent, parent_box in faint_curves:
        for component in components:
            left, top, right, bottom = component.box
            if not (parent_box[0] <= left and right <= parent_box[2]
                    and parent_box[1] <= top and bottom <= parent_box[3]):
                continue
            own_ink = _component_ink(component, gray, 160)
            if own_ink is not None and _complete_curve_component(component, own_ink, height, 2):
                continue
            for span in _detached_row_slurs(
                notes, row_top, height, [component], gray, barlines,
            ):
                if span != parent and span in found:
                    found.remove(span)
        for span, box in recovered_fragments:
            if (span != parent and parent_box[0] <= box[0] and box[2] <= parent_box[2]
                    and parent_box[1] <= box[1] and box[3] <= parent_box[3]
                    and not _complete_curve_component(Component(box, 0), gray, height, 2)
                    and span in recovered):
                recovered.remove(span)
    faint: Counter[tuple[int | None, int | None]] = Counter(span for span, _ in faint_curves)
    missing = (Counter(recovered) | faint) - Counter(found)
    merged = found
    for pair in (*recovered, *faint.elements()):
        if missing[pair]:
            merged.append(pair)
            missing[pair] -= 1
    return tuple(merged)


def _split_curve_at_cusps(
    notes: tuple[Box, ...], component: Component, gray: Image.Image, height: float,
    spans: tuple[tuple[int | None, int | None], ...],
) -> tuple[tuple[int | None, int | None], ...]:
    """A downward cusp on a note separates consecutive arches sharing one stroke."""
    left, top, right, bottom = component.box
    profile = {x: max(ink) for x in range(left, right)
               if (ink := [y for y in range(top, bottom)
                           if cast(int, gray.getpixel((x, y))) < 170])}
    cusps = []
    for index, box in enumerate(notes):
        center = (box[0] + box[2]) / 2
        peak = [y for x, y in profile.items() if abs(x - center) <= height * 0.25]
        before = [y for x, y in profile.items()
                  if center - height * 1.3 <= x <= center - height * 0.5]
        after = [y for x, y in profile.items()
                 if center + height * 0.5 <= x <= center + height * 1.3]
        if (peak and before and after
                and max(peak) - max(min(before), min(after)) >= max(2, height * 0.2)):
            cusps.append(index)
    result: list[tuple[int | None, int | None]] = []
    for start, end in spans:
        anchors = [start, *(index for index in cusps
                           if (start is None or start < index)
                           and (end is None or index < end)), end]
        result.extend(zip(anchors, anchors[1:], strict=False))
    return tuple(result)


def _component_ink(component: Component, gray: Image.Image, threshold: int) -> Image.Image | None:
    """Isolate an eight-connected stroke from other marks sharing its bounding box."""
    left, top, _, _ = component.box
    bridged = Image.new("L", gray.size, 255)
    crop = gray.crop(component.box)
    visited: set[tuple[int, int]] = set()
    stroke: set[tuple[int, int]] = set()
    for seed_y in range(crop.height):
        seed = (0, seed_y)
        if seed in visited or cast(int, crop.getpixel(seed)) >= threshold:
            continue
        pending = [seed]
        stroke = {seed}
        while pending:
            x, y = pending.pop()
            for nx in range(max(0, x - 1), min(crop.width, x + 2)):
                for ny in range(max(0, y - 1), min(crop.height, y + 2)):
                    if ((nx, ny) not in stroke
                            and cast(int, crop.getpixel((nx, ny))) < threshold):
                        stroke.add((nx, ny))
                        pending.append((nx, ny))
        visited.update(stroke)
        if len(stroke) == component.area:
            break
    if len(stroke) != component.area:
        return None
    for x, y in stroke:
        bridged.putpixel((left + x, top + y), 0)
    return bridged


def _faint_curve_bridges(
    notes: tuple[Box, ...], components: list[Component], gray: Image.Image,
    row_top: int, height: float, barlines: tuple[int, ...] = (),
) -> tuple[tuple[tuple[int | None, int | None], Box], ...]:
    """Recover complete arches from faint bridges or ink touching a barline."""
    if row_top <= max(1, round(height * 0.2)):
        return ()
    upper = max(0, round(row_top - height * 2.5))
    band = gray.crop((0, upper, gray.width, row_top - max(1, round(height * 0.2))))

    def source_parts(threshold: int, inset: int = 0) -> list[Component]:
        if inset >= band.height:
            return []
        local = band.crop((0, inset, band.width, band.height))
        return [Component((part.box[0], part.box[1] + upper + inset,
                           part.box[2], part.box[3] + upper + inset), part.area)
                for part in connected_components(local, threshold)]

    dark_parts = source_parts(160)
    recovered: list[tuple[tuple[int | None, int | None], Box]] = []
    for threshold, component in (
        (level, part) for level in (180, 200)
        for inset in (0, round(height * 0.9)) for part in source_parts(level, inset)
    ):
        left, top, right, bottom = component.box
        if not (component.width >= height * 0.8
                and max(3, height * 0.15) <= component.height <= height
                and row_top - height * 2.5 < top < row_top - height * 0.4
                and bottom < row_top):
            continue
        pieces = {part for part in dark_parts if (
            left <= part.box[0] and part.box[2] <= right
            and top <= part.box[1] and part.box[3] <= bottom
        )}
        # Marks owned by symbols, hairpins or endings must stay excluded.
        permitted = all(any(
            mark.box[0] <= part.box[0] and part.box[2] <= mark.box[2]
            and mark.box[1] <= part.box[1] and part.box[3] <= mark.box[3]
            for mark in components
        ) for part in pieces)
        clipped = any(part not in components for part in pieces)
        touches_bar = any(
            mark.box[0] <= bar < mark.box[2] and mark.box[3] > row_top + height
            and mark.box[0] <= left and right <= mark.box[2]
            for mark in components for bar in barlines
        )
        clipped_above = any(
            mark.box[0] <= left and right <= mark.box[2]
            and mark.box[1] < upper and bottom <= mark.box[3] < row_top
            for mark in components
        )
        if not pieces or not permitted or clipped and not (touches_bar or clipped_above):
            continue
        bridged = _component_ink(component, gray, threshold)
        if bridged is None:
            continue
        complete = _complete_curve_component(component, bridged, height, 2)
        right_cut = bool(barlines) and abs(right - max(barlines)) <= height * 0.5
        spans = _detached_row_slurs(notes, row_top, height, [component], bridged, barlines)
        left_cut = any(start is None for start, _ in spans)
        if not complete and not right_cut and not left_cut:
            continue
        # Touching arches can join at this threshold. Recover one stroke only;
        # merged/nested layers retain their existing topology-based detector.
        branched = 0
        for x in range(left, right):
            ink = [y for y in range(top, bottom) if bridged.getpixel((x, y)) == 0]
            branched += int(any(b - a > 1 for a, b in zip(ink, ink[1:], strict=False)))
        if branched > component.width * 0.05:
            continue
        for start, end in _detached_row_slurs(
            notes, row_top, height, [component], bridged, barlines,
        ):
            if ((start is None and left_cut or start is not None
                 and abs((notes[start][0] + notes[start][2]) / 2 - left) <= height * 0.75)
                    and (end is None and right_cut or end is not None and (complete or left_cut)
                         and abs((notes[end][0] + notes[end][2]) / 2 - right) <= height * 0.75)):
                if not any(all(
                    abs(a - b) <= max(2, height * 0.15)
                    for a, b in zip(box, component.box, strict=True)
                ) for span, box in recovered):
                    recovered.extend((span, component.box) for span in _split_curve_at_cusps(
                        notes, component, bridged, height, ((start, end),),
                    ))
    return tuple(recovered)


def _nested_shorter_slurs(
    notes: tuple[Box, ...], height: float, component: Component, gray: Image.Image,
    parent: tuple[int | None, int | None],
) -> tuple[tuple[int | None, int | None], ...]:
    """Recover a shorter arch that shares a head with a longer, merged arch."""
    start, end = parent
    if start is None or end is None or end - start < 2:
        return ()
    left, top, right, bottom = component.box
    centers = [(box[0] + box[2]) / 2 for box in notes]
    pixels = gray.load()
    assert pixels is not None
    step = max(1, round(height * 0.15))

    def profile(x: int) -> list[float]:
        runs: list[list[int]] = []
        for y in range(top, min(bottom, gray.height)):
            if cast(int, pixels[x, y]) >= 160:
                continue
            if not runs or y - runs[-1][-1] > max(1, round(height * 0.08)):
                runs.append([])
            runs[-1].append(y)
        return [sum(run) / len(run) for run in runs]

    for candidate in range(start + 1, end):
        endpoint = centers[candidate]
        before = list(range(
            max(left + round((right - left) * 0.08), left + round(height * 0.5)),
            max(left + round((right - left) * 0.08), round(endpoint - height * 0.35)),
            step,
        ))
        after = list(range(
            round(endpoint + height * 0.45),
            min(
                right - round(height * 0.1),
                round(centers[candidate + 1] - height * 0.25),
            ),
            step,
        ))
        if len(before) < 6 or len(after) < 6:
            continue
        before_profiles = [(x, profile(x)) for x in before]
        doubled = [(x, rows) for x, rows in before_profiles if len(rows) >= 2]
        if len(doubled) < len(before_profiles) * 0.5:
            continue
        if abs(doubled[-1][0] - endpoint) > height * 1.5:
            continue
        after_profiles = [profile(x) for x in after]
        if sum(len(rows) <= 1 for rows in after_profiles) < len(after_profiles) * 0.55:
            continue
        separation = median(rows[-1] - rows[0] for _, rows in doubled)
        if separation >= max(2, height * 0.12):
            return ((start, candidate),)
    return ()


def _short_fragments_form_curve_apex(
    fragments: tuple[Component, ...], gray: Image.Image, height: float,
) -> bool:
    """Keep a short interior fragment only when it joins both sides of an arch."""
    edge = max(1, ceil(height * 0.08))
    pixels = gray.load()
    assert pixels is not None
    for index, fragment in enumerate(fragments):
        if fragment.height >= max(2, height * 0.15):
            continue
        if index == 0 or index == len(fragments) - 1:
            return False
        left, bridge, right = fragments[index - 1:index + 2]
        if (bridge.box[0] - left.box[2] > edge
                or right.box[0] - bridge.box[2] > edge):
            return False

        def peak(component: Component, from_right: bool) -> int | None:
            x0, y0, x1, y1 = component.box
            xs = range(max(x0, x1 - edge), x1) if from_right else range(x0, min(x1, x0 + edge))
            ink = [y for x in xs for y in range(y0, y1) if cast(int, pixels[x, y]) < 170]
            return min(ink) if ink else None

        apex = min(y for x in range(bridge.box[0], bridge.box[2])
                   for y in range(bridge.box[1], bridge.box[3])
                   if cast(int, pixels[x, y]) < 170)
        left_peak, right_peak = peak(left, True), peak(right, False)
        if (left_peak is None or right_peak is None
                or abs(apex - left_peak) > edge or abs(apex - right_peak) > edge):
            return False
    return True


def _head_parallel_slurs(
    notes: tuple[Box, ...], row_top: int, height: float,
    components: list[Component], gray: Image.Image, barlines: tuple[int, ...],
    found: tuple[tuple[int | None, int | None], ...],
    recovered_fragments: list[tuple[tuple[int | None, int | None], Box]],
) -> tuple[tuple[int | None, int | None], ...]:
    """Complete a nested head-cut curve when its parallel layer is scan-occluded."""
    if len(notes) < 2 or not any(start is None and end is not None for start, end in found):
        return ()
    centers = [(box[0] + box[2]) / 2 for box in notes]
    observed = set(found)
    parents = list(recovered_fragments)
    for component in components:
        left, top, right, bottom = component.box
        if not (
            height * 0.8 <= component.width <= gray.width
            and max(3, height * 0.15) <= component.height <= height
            and component.area <= component.width * max(4, height * 0.2)
            and row_top - height * 2 < top < row_top - height * 0.4
            and bottom < row_top
        ):
            continue
        parents.extend(
            (span, component.box)
            for span in _detached_row_slurs(notes, row_top, height, [component], gray, barlines)
            if span[0] is None and span[1] is not None
        )
    fragments = [component for component in components if (
        height * 2 <= component.width < gray.width
        and max(3, height * 0.15) <= component.height <= height
        and component.area <= component.width * max(4, height * 0.2)
        and row_top - height * 2 < component.box[1] < row_top - height * 0.4
        and component.box[3] < row_top
        and _left_curve_rise(component, gray, height)
    )]
    recovered: list[tuple[int | None, int | None]] = []
    for (start, end), parent in parents:
        if start is not None or end is None or end == 0 or (0, end) in observed:
            continue
        left, top, right, bottom = parent
        if (abs(centers[end] - right) > height * 1.5
                or abs(centers[0] - left) > height * 1.5):
            continue
        for fragment in fragments:
            f_left, f_top, f_right, f_bottom = fragment.box
            if (fragment.box == parent or abs(f_left - left) > height * 0.5
                    or f_right <= (centers[0] + centers[end]) / 2
                    or not height * 0.5 <= right - f_right <= height * 4
                    or fragment.width < (right - left) * 0.5
                    or max(0, f_top - bottom, top - f_bottom) > height * 0.5):
                continue
            recovered.append((0, end))
            break
    return tuple(recovered)


def _left_curve_rise(component: Component, gray: Image.Image, height: float) -> bool:
    left, top, right, bottom = component.box
    edge = max(1, ceil(height * 0.08))
    pixels = gray.load()
    assert pixels is not None
    left_ink = [y for y in range(top, bottom) for x in range(left, left + edge)
                if cast(int, pixels[x, y]) < 170]
    center_ink = [y for y in range(top, bottom)
                  for x in range(left + round((right - left) * 0.4),
                                 left + round((right - left) * 0.6))
                  if cast(int, pixels[x, y]) < 170]
    return bool(left_ink and center_ink and max(left_ink) >= min(center_ink) + 2)


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
        and max(1, height * 0.08) <= component.height <= height
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
            (not left_curves or left < notes[0][0] - height * 0.25
             and tops[0] - tops[1] <= max(2, height * 0.2))
            and left <= notes[0][0] + height and right_curves
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
