"""Locate main note digits and barlines in raster Jianpu pages."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from functools import cache
from itertools import product
from math import ceil, floor
from pathlib import Path
from statistics import linear_regression, median
from typing import cast

from PIL import Image, ImageOps

from .accompaniment import bracketed_row_centers, compact_accompaniment_owner
from .components import Box, Component, connected_components
from .decorations import Hairpin, row_hairpins, symbol_decorations
from .glyphs import (
    DigitMatch,
    classify_accidental,
    classify_digit,
    classify_mordent,
    digit_shape_similarity,
    match_page_digit,
    page_digit_templates,
)
from .marks import (
    curve_core_parts,
    note_modifiers,
    row_parentheses,
    row_slurs,
    row_sustains,
    vertical_bend,
)
from .ornaments import EndingSegment, GraceGroup, row_endings, row_graces, voice_components
from .text import TextSpan, image_digit, music_characters
from .voices import DsbOverlay, VoiceGroup, recognize_dsb_overlays, recognize_voice_groups

MAX_PAGE_PIXELS = 40_000_000
MIN_WORKING_GLYPH_HEIGHT = 24


@dataclass(frozen=True, slots=True)
class Note:
    digit: str
    box: Box
    confidence: float
    octave: int = 0
    duration_slashes: int = 0
    duration_dots: int = 0
    accidental: str = ""
    decorations: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MusicRow:
    notes: tuple[Note, ...]
    barlines: tuple[int, ...]
    box: Box
    unresolved_marks: tuple[Box, ...]
    # Indices address the ordered notes and sustain dashes; None is a row-cut end.
    slurs: tuple[tuple[int | None, int | None], ...] = ()
    graces: tuple[GraceGroup, ...] = ()
    endings: tuple[EndingSegment, ...] = ()
    parentheses: tuple[tuple[int, str], ...] = ()
    hairpins: tuple[Hairpin, ...] = ()
    decoration_regions: tuple[Box, ...] = ()


@dataclass(frozen=True, slots=True)
class BzOverlay:
    anchor: int
    row: MusicRow


@dataclass(frozen=True, slots=True)
class PageObservation:
    width: int
    height: int
    rows: tuple[MusicRow, ...]
    candidate_digits: int
    text_spans: tuple[TextSpan, ...] = ()
    text_source: str = "unavailable"
    voice_groups: tuple[VoiceGroup, ...] = ()
    dsb_overlays: tuple[DsbOverlay, ...] = ()
    bz_overlays: tuple[BzOverlay, ...] = ()
    unresolved_braces: tuple[Box, ...] = ()
    excluded_regions: tuple[Box, ...] = ()


def _qr_regions(gray: Image.Image) -> tuple[Box, ...]:
    """Locate a non-score QR panel using the OCR extra's existing OpenCV dependency."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return ()
    # ponytail: one readable QR panel per page; use decodeMulti for multiple panels.
    detector = cv2.QRCodeDetector()
    payload, corners, _ = detector.detectAndDecode(np.asarray(gray))
    scale = 1
    if not payload and gray.width * gray.height * 4 <= MAX_PAGE_PIXELS:
        # Low-resolution QR modules need crisp enlargement, just like small score digits.
        enlarged = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.NEAREST)
        payload, corners, _ = detector.detectAndDecode(np.asarray(enlarged))
        scale = 2
    if not payload or corners is None:
        return ()
    points = corners.reshape(-1, 2) / scale
    return ((
        max(0, floor(float(points[:, 0].min()))),
        max(0, floor(float(points[:, 1].min()))),
        min(gray.width, ceil(float(points[:, 0].max())) + 1),
        min(gray.height, ceil(float(points[:, 1].max())) + 1),
    ),)


def _score_components(
    gray: Image.Image, excluded: tuple[Box, ...],
) -> list[Component]:
    return [
        component for component in connected_components(gray)
        if not any(
            left <= (component.box[0] + component.box[2]) / 2 <= right
            and top <= component.center_y <= bottom
            for left, top, right, bottom in excluded
        )
    ]


def _working_scale(components: list[Component], width: int, height: int) -> int:
    shapes = Counter(
        component.height for component in components
        if 8 <= component.height <= 75
        and component.height * 0.2 <= component.width <= component.height
        and component.area >= max(18, component.height)
    )
    if not shapes:
        return 1
    glyph_height, count = shapes.most_common(1)[0]
    if count < 12 or glyph_height >= 16:
        return 1
    scale = min(4, ceil(MIN_WORKING_GLYPH_HEIGHT / glyph_height))
    while width * height * scale * scale > MAX_PAGE_PIXELS:
        scale -= 1
    return scale


def _source_box(box: Box, scale: int) -> Box:
    return (
        floor(box[0] / scale), floor(box[1] / scale),
        ceil(box[2] / scale), ceil(box[3] / scale),
    )


def _source_row(row: MusicRow, scale: int) -> MusicRow:
    return replace(
        row,
        notes=tuple(replace(note, box=_source_box(note.box, scale)) for note in row.notes),
        barlines=tuple(round(x / scale) for x in row.barlines),
        box=_source_box(row.box, scale),
        unresolved_marks=tuple(_source_box(box, scale) for box in row.unresolved_marks),
        graces=tuple(replace(group, box=_source_box(group.box, scale)) for group in row.graces),
        endings=tuple(replace(frame, box=_source_box(frame.box, scale)) for frame in row.endings),
    )


def _source_coordinates(
    page: PageObservation, scale: int, size: tuple[int, int]
) -> PageObservation:
    if scale == 1:
        return page
    return replace(
        page,
        width=size[0], height=size[1],
        rows=tuple(_source_row(row, scale) for row in page.rows),
        voice_groups=tuple(
            replace(group, box=_source_box(group.box, scale)) for group in page.voice_groups
        ),
        dsb_overlays=tuple(
            replace(
                overlay, box=_source_box(overlay.box, scale),
                closing_x=round(overlay.closing_x / scale)
                if overlay.closing_x is not None else None,
            )
            for overlay in page.dsb_overlays
        ),
        bz_overlays=tuple(
            replace(overlay, row=_source_row(overlay.row, scale)) for overlay in page.bz_overlays
        ),
        unresolved_braces=tuple(_source_box(box, scale) for box in page.unresolved_braces),
        excluded_regions=tuple(_source_box(box, scale) for box in page.excluded_regions),
    )


def _read_page(path: Path) -> Image.Image:
    with Image.open(path) as source:
        if source.width * source.height > MAX_PAGE_PIXELS:
            raise ValueError("image exceeds the 40-million-pixel page limit")
        oriented = ImageOps.exif_transpose(source).convert("RGBA")
    white = Image.new("RGBA", oriented.size, "white")
    white.alpha_composite(oriented)
    return white.convert("L")


def _barline(
    component: Component, row_y: float, digit_height: int, gray: Image.Image,
    *, shared: bool = False,
) -> bool:
    if not (
        component.width <= max(3, component.height * 0.22)
        and digit_height * 1.25 <= component.height <= digit_height * 5.2
        and (
            abs(component.center_y - row_y) <= digit_height * 0.8
            or component.height > digit_height * 3
            and component.box[1] < row_y < component.box[3]
            and component.box[3] - row_y <= digit_height * 1.4
            or shared and component.box[1] < row_y < component.box[3]
            and row_y - component.box[1] <= digit_height * 1.7
        )
    ):
        return False
    bend = vertical_bend(component, gray)
    return bend is not None and abs(bend) <= max(1, component.width * 0.2)


def _fragmented_vertical_barlines(
    components: list[Component], digit_height: int, gray: Image.Image,
) -> list[Component]:
    """Reconnect thin barline fragments split by scan noise or JPEG artifacts."""
    x_tolerance = max(2, round(digit_height * 0.08))
    gap_tolerance = max(2, round(digit_height * 0.18))
    fragments = sorted(
        (
            component for component in components
            if 1 <= component.height < digit_height * 1.25
            and component.width <= max(3, round(digit_height * 0.15))
            and component.width <= max(2, component.height * 0.75)
        ),
        key=lambda component: (
            (component.box[0] + component.box[2]) / 2, component.box[1],
        ),
    )
    columns: list[list[Component]] = []
    for component in fragments:
        center_x = (component.box[0] + component.box[2]) / 2
        if (
            not columns
            or center_x - (columns[-1][0].box[0] + columns[-1][0].box[2]) / 2
            > x_tolerance
        ):
            columns.append([component])
        else:
            columns[-1].append(component)

    recovered = []
    for column in columns:
        run: list[Component] = []
        run_bottom = 0
        run_center_x = 0.0
        for component in sorted(column, key=lambda item: item.box[1]):
            center_x = (component.box[0] + component.box[2]) / 2
            if run and (
                component.box[1] - run_bottom <= gap_tolerance
                and abs(center_x - run_center_x / len(run)) <= x_tolerance
            ):
                run.append(component)
                run_bottom = max(run_bottom, component.box[3])
                run_center_x += center_x
            else:
                if run:
                    candidate = _barline_from_fragments(run, digit_height, gray)
                    if candidate is not None:
                        recovered.append(candidate)
                run = [component]
                run_bottom = component.box[3]
                run_center_x = center_x
        if run:
            candidate = _barline_from_fragments(run, digit_height, gray)
            if candidate is not None:
                recovered.append(candidate)
    return recovered


def _barline_from_fragments(
    run: list[Component], digit_height: int, gray: Image.Image,
) -> Component | None:
    if len(run) < 3:
        return None
    box = (
        min(component.box[0] for component in run),
        min(component.box[1] for component in run),
        max(component.box[2] for component in run),
        max(component.box[3] for component in run),
    )
    candidate = Component(box, sum(component.area for component in run))
    if not (
        digit_height * 1.25 <= candidate.height <= digit_height * 5.2
        and candidate.width <= max(3, round(digit_height * 0.22))
        and candidate.area >= candidate.height * 0.3
    ):
        return None
    bend = vertical_bend(candidate, gray)
    if bend is not None and abs(bend) <= max(1, candidate.width * 0.2):
        return candidate
    return None


def _music_row(
    group: list[tuple[Component, DigitMatch]],
    components: list[Component], digit_height: int, gray: Image.Image,
    *, joined_underlines: bool = False,
    accompaniment: bool = False,
    barline_candidates: list[Component] | None = None,
) -> MusicRow:
    group.sort(key=lambda pair: pair[0].box[0])
    row_y = sum(component.center_y for component, _ in group) / len(group)
    bar_height = max(digit_height, round(median(component.height for component, _ in group)))

    def is_bar(component: Component) -> bool:
        # A system brace can be as tall as an extended accompaniment bar, but
        # stands to the left of every note. Ordinary leading measure bars remain.
        if component.height > bar_height * 3 and component.box[2] < group[0][0].box[0]:
            return False
        return _barline(component, row_y, bar_height, gray, shared=accompaniment)

    nearby = [
        component for component in components
        if abs(component.center_y - row_y) <= digit_height * 1.2
        or is_bar(component)
    ]
    modifier_components = [
        component for component in components
        if abs(component.center_y - row_y) <= digit_height * 1.6
    ]
    bars = sorted({
        component.box[0]
        for component in (*nearby, *(barline_candidates or ()))
        if is_bar(component)
    })
    notes = []
    used_marks: set[Box] = set()
    for index, (component, match) in enumerate(group):
        right_limit = min(
            ([group[index + 1][0].box[0]] if index + 1 < len(group) else [])
            + [x for x in bars if x > component.box[2]],
            default=None,
        )
        octave, slashes, dots, marks = note_modifiers(
            component.box, modifier_components, digit_height,
            gray if joined_underlines else None, right_limit,
            duration_gray=gray, barlines=tuple(bars),
        )
        signs = [
            (sign, accidental) for sign in modifier_components
            if digit_height * 0.55 <= sign.height <= digit_height * 1.3
            and sign.width <= digit_height * 0.6
            and 0 <= component.box[0] - sign.box[2] <= digit_height * 0.6
            and abs(sign.center_y - component.center_y) <= digit_height * 0.5
            and (accidental := classify_accidental(gray, sign)) is not None
        ]
        accidental = signs[0][1] if len(signs) == 1 else ""
        mordents = [
            mark for mark in nearby
            if digit_height * 0.35 <= mark.width <= digit_height * 1.3
            and digit_height * 0.08 <= mark.height <= digit_height * 0.5
            and 0 <= component.box[1] - mark.box[3] <= digit_height * 0.8
            and component.box[0] <= (mark.box[0] + mark.box[2]) / 2 <= component.box[2]
            and classify_mordent(gray, mark)
        ]
        decorations = ("sby",) if len(mordents) == 1 else ()
        notes.append(Note(
            match[0], component.box, match[1], octave, slashes, dots, accidental, decorations,
        ))
        if decorations:
            marks.add(mordents[0].box)
        if accidental:
            marks.add(signs[0][0].box)
        used_marks.update(marks)
    note_boxes = {note.box for note in notes}
    unresolved = tuple(
        component.box for component in nearby
        if component.box not in note_boxes
        and component.box not in used_marks
        and not _barline(component, row_y, digit_height, gray)
        and component.area >= 3
    )
    return MusicRow(
        tuple(notes), tuple(bars),
        (
            min(note.box[0] for note in notes),
            min(note.box[1] for note in notes),
            max(note.box[2] for note in notes),
            max(note.box[3] for note in notes),
        ),
        unresolved,
    )


def _groups(
    candidates: list[tuple[Component, DigitMatch]], height: int,
) -> list[list[tuple[Component, DigitMatch]]]:
    groups: list[list[tuple[Component, DigitMatch]]] = []
    for candidate in sorted(candidates, key=lambda pair: pair[0].box[3]):
        if groups and candidate[0].box[3] - groups[-1][0][0].box[3] <= max(7, height * 0.75):
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    # A tilted scan may split one baseline into disjoint left/right fragments.
    # Merge only fragments explained by one shallow line, never stacked voices.
    merged: list[list[tuple[Component, DigitMatch]]] = []
    for group in groups:
        if merged:
            previous = merged[-1]
            left = max(min(item.box[0] for item, _ in previous),
                       min(item.box[0] for item, _ in group))
            right = min(max(item.box[2] for item, _ in previous),
                        max(item.box[2] for item, _ in group))
            combined = [*previous, *group]
            xs = [(item.box[0] + item.box[2]) / 2 for item, _ in combined]
            ys = [float(item.box[3]) for item, _ in combined]
            if (right <= left + height * 0.2 and left - right <= height * 8
                    and max(xs) - min(xs) >= height * 5):
                fit = linear_regression(xs, ys)
                residuals = [abs(y - (fit.slope * x + fit.intercept))
                             for x, y in zip(xs, ys, strict=True)]
                local_slopes = []
                for fragment in (previous, group):
                    local_xs = [(item.box[0] + item.box[2]) / 2 for item, _ in fragment]
                    if len(fragment) >= 3 and max(local_xs) - min(local_xs) >= height * 3:
                        local_slopes.append(linear_regression(
                            local_xs, [float(item.box[3]) for item, _ in fragment],
                        ).slope)
                tilted = any(abs(slope) >= 0.008 and slope * fit.slope > 0
                             and abs(slope - fit.slope) <= 0.012 for slope in local_slopes)
                if (tilted and abs(fit.slope) <= 0.055 and median(residuals) <= height * 0.2
                        and max(residuals) <= height * 0.5
                        and max(ys) - min(ys) <= height * 1.6):
                    previous.extend(group)
                    continue
        merged.append(group)
    return merged


def _split_digit_cluster(
    gray: Image.Image, component: Component,
    owned: list[tuple[str, float, float]], height: int,
) -> list[tuple[Component, DigitMatch]]:
    """Fit pixel-owned glyphs around OCR character centers; reject the entire bad partition."""
    left, upper, right, lower = component.box
    pixels = gray.load()
    assert pixels is not None
    # ponytail: four touching digits; use dynamic programming if larger clusters need recovery.
    if not 1 <= len(owned) <= 4 or component.width > height and len(owned) < 2:
        return []
    seams = []
    for a, b in zip(owned, owned[1:], strict=False):
        cut_range = range(max(left + 1, ceil(a[2] + height * 0.15)),
                          min(right, floor(b[2] - height * 0.15) + 1))
        if not cut_range:
            break
        seams.append(cut_range)
    if len(seams) != len(owned) - 1:
        return []

    @cache
    def piece_at(digit: str, start: int, end: int) -> tuple[Component | None, float]:
        ink = gray.crop((start, upper, end, lower)).point(
            lambda value: 255 if value < 160 else 0,
        )
        box = ink.getbbox()
        if box is None:
            return None, 0.0
        piece = Component(
            (start + box[0], upper + box[1], start + box[2], upper + box[3]),
            ink.histogram()[255],
        )
        if (not height * 0.2 <= piece.width <= height
                or abs(piece.height - height) > max(3, height * 0.12)):
            return None, 0.0
        return piece, digit_shape_similarity(gray, piece, digit)

    def fit(cuts: tuple[int, ...]) -> tuple[float, float, int]:
        bounds = (left, *cuts, right)
        scores = [piece_at(digit, start, end)[1]
                  for (digit, _, _), start, end in zip(
                      owned, bounds, bounds[1:], strict=False)]
        return (min(scores), sum(scores), -sum(
            cast(int, pixels[x, y]) < 160 for x in cuts for y in range(upper, lower)
        ))

    cuts = max(product(*seams), key=fit)
    if fit(cuts)[0] < 0.6:
        return []
    bounds = (left, *cuts, right)
    pieces = []
    for (digit, score, _), start, end in zip(owned, bounds, bounds[1:], strict=False):
        piece, _ = piece_at(digit, start, end)
        assert piece is not None
        pieces.append((piece, (digit, score, True)))
    return pieces


def _recover_row_digits(
    group: list[tuple[Component, DigitMatch]], components: list[Component],
    height: int, gray: Image.Image, claimed: set[Box],
    templates: tuple[tuple[str, int], ...] = (),
) -> list[tuple[Component, DigitMatch]]:
    """Recover unresolved row ink without changing already accepted note glyphs."""
    height = round(median(component.height for component, _ in group))
    center_y = sum(component.center_y for component, _ in group) / len(group)
    unresolved = [component for component in components
                  if component.box not in claimed
                  and abs(component.center_y - center_y) <= height * 0.3
                  and abs(component.height - height) <= max(3, height * 0.12)
                  and height * 0.2 <= component.width <= height * 6]
    if not unresolved:
        return []
    found = []
    for component in unresolved:
        if component.width <= height and (page_match := match_page_digit(
            gray, component, templates,
        )) is not None:
            found.append((component, page_match))
            claimed.add(component.box)
    unresolved = [component for component in unresolved if component.box not in claimed]
    if not unresolved:
        return found
    top = min(component.box[1] for component, _ in group)
    bottom = max(component.box[3] for component, _ in group)
    characters: list[tuple[str, float, float]] = []
    for item in music_characters(gray, (0, top, gray.width, bottom)):
        if characters and item[2] - characters[-1][2] <= height * 0.2:
            characters[-1] = max(characters[-1], item, key=lambda value: value[1])
        else:
            characters.append(item)
    if sum(any(digit == match[0] and component.box[0] <= center <= component.box[2]
               for digit, _, center in characters) for component, match in group) < 3:
        return found
    for component in unresolved:
        left, upper, right, lower = component.box
        owned = [(digit, score, center) for digit, score, center in characters
                 if left <= center < right]
        if component.width <= height and len(owned) > 1:
            single = [item for item in owned
                      if digit_shape_similarity(gray, component, item[0]) >= 0.6]
            if single:
                owned = [max(single, key=lambda item: item[1])]
        if (component.width <= height and len(owned) <= 1
                and (not owned or digit_shape_similarity(gray, component, owned[0][0]) < 0.6)):
            match = image_digit(gray, component.box, tight_padding=True)
            if match is not None:
                owned = [(match[0], match[1], (left + right) / 2)]
        pieces = _split_digit_cluster(gray, component, owned, height)
        if pieces:
            components.remove(component)
            components.extend(piece for piece, _ in pieces)
            found.extend(pieces)
            claimed.update(piece.box for piece, _ in pieces)
    return found


def _by_local_brace(
    group: list[tuple[Component, DigitMatch]],
    components: list[Component], width: int, digit_height: int,
) -> bool:
    left = min(component.box[0] for component, _ in group)
    right = max(component.box[2] for component, _ in group)
    top = min(component.box[1] for component, _ in group)
    bottom = max(component.box[3] for component, _ in group)
    center_y = sum(component.center_y for component, _ in group) / len(group)

    def touches_branch_edge(brace: Component) -> bool:
        tolerance = digit_height * 0.5
        return (
            abs(center_y - brace.box[1]) <= digit_height * 1.25
            and top <= brace.box[1] + tolerance
            and bottom >= brace.box[1] - tolerance
            or abs(center_y - brace.box[3]) <= digit_height * 1.25
            and top <= brace.box[3] + tolerance
            and bottom >= brace.box[3] - tolerance
        )

    return any(
        width * 0.10 < component.box[0] < width * 0.85
        and (
            component.box[2] < left <= component.box[2] + digit_height * 3
            or right < component.box[0] <= right + width * 0.17
        )
        and (component.box[1] < center_y < component.box[3]
             or touches_branch_edge(component))
        and digit_height * 2.5 <= component.height <= digit_height * 6
        and component.height >= component.width * 5
        for component in components
    )


def _compact_bracketed_group(
    group: list[tuple[Component, DigitMatch]], components: list[Component], gray: Image.Image,
) -> bool:
    if len(group) < 3:
        return False
    boxes = tuple(component.box for component, _ in sorted(group, key=lambda pair: pair[0].box[0]))
    height = median(box[3] - box[1] for box in boxes)
    centers = [(box[0] + box[2]) / 2 for box in boxes]
    return (
        median(b - a for a, b in zip(centers, centers[1:], strict=False)) <= height * 1.7
        and bool(row_parentheses(boxes, height, components, gray))
    )


def _compact_accompaniment_group(
    group: list[tuple[Component, DigitMatch]], components: list[Component],
    gray: Image.Image, host: MusicRow,
) -> bool:
    """Accept a small BZ row when notation or its host gives independent support."""
    if len(group) < 3:
        return False
    boxes = tuple(component.box for component, _ in sorted(group, key=lambda pair: pair[0].box[0]))
    height = median(box[3] - box[1] for box in boxes)
    centers = [(box[0] + box[2]) / 2 for box in boxes]
    if median(b - a for a, b in zip(centers, centers[1:], strict=False)) > height * 4.5:
        return False
    if row_parentheses(boxes, height, components, gray):
        return True

    first, last = centers[0], centers[-1]
    boundaries = (host.box[0], *host.barlines, host.box[2])
    confined_to_measure = any(
        left <= first and last <= right
        for left, right in zip(boundaries, boundaries[1:], strict=False)
    )
    if not confined_to_measure:
        return False
    host_centers = [(note.box[0] + note.box[2]) / 2 for note in host.notes]
    support_x = (*host_centers, *host.barlines)
    return any(abs(center - support) <= height * 0.85
               for center in centers for support in support_x)


def recognize_image(path: Path) -> PageObservation:
    source_gray = _read_page(path)
    excluded = _qr_regions(source_gray)
    components = _score_components(source_gray, excluded)
    source_components = components
    scale = _working_scale(components, *source_gray.size)
    gray = source_gray
    if scale > 1:
        gray = source_gray.resize(
            (source_gray.width * scale, source_gray.height * scale), Image.Resampling.LANCZOS
        )
        excluded = tuple(
            (box[0] * scale, box[1] * scale, box[2] * scale, box[3] * scale)
            for box in excluded
        )
        components = _score_components(gray, excluded)
    trusted = [
        (component, match)
        for component in components
        if (match := classify_digit(gray, component, allow_ocr=False)) is not None
    ]
    known_boxes = {component.box for component, _ in trusted}
    trusted_heights = Counter(round(component.height / 3) * 3 for component, _ in trusted)
    trusted_height = trusted_heights.most_common(1)[0][0] if trusted_heights else 0
    trusted_main = [
        (component, match) for component, match in trusted
        if abs(component.height - trusted_height) <= max(3, trusted_height * 0.12)
    ]
    trusted_rows = [
        sum(component.center_y for component, _ in group) / len(group)
        for group in _groups(trusted_main, trusted_height)
        if len(group) >= 3 and (
            max(component.box[2] for component, _ in group)
            - min(component.box[0] for component, _ in group) >= gray.width * 0.12
            or _compact_bracketed_group(group, components, gray)
        )
    ] if trusted_height else []
    if trusted_height:
        trusted_rows.extend(bracketed_row_centers(components, trusted_height, gray))
    possible_bars = [
        component for component in components
        if component.width <= max(8, component.height * 0.2)
        and 25 <= component.height <= 180
    ]
    fallback_heights = Counter(
        round(component.height / 3) * 3 for component in components
        if not trusted_rows and 16 <= component.height <= 75
        and component.height * 0.2 <= component.width <= component.height
        and component.area >= max(18, component.height)
    )
    fallback_height, fallback_count = (
        fallback_heights.most_common(1)[0] if fallback_heights else (0, 0)
    )
    candidates = list(trusted)
    for component in components:
        if component.box in known_boxes:
            continue
        # Use the same music-height band as row grouping when no template row is available.
        anchor_height = fallback_height if fallback_count >= 12 and (
            abs(component.height - fallback_height) <= max(3, fallback_height * 0.12)
        ) else component.height
        if not (
            any(_barline(bar, component.center_y, component.height, gray)
                or _barline(bar, component.center_y, anchor_height, gray) for bar in possible_bars)
            or any(abs(component.center_y - y) <= component.height * 0.4 for y in trusted_rows)
        ):
            continue
        match = classify_digit(gray, component)
        if match is not None:
            candidates.append((component, match))
    if not candidates:
        return PageObservation(*source_gray.size, (), 0, excluded_regions=tuple(
            _source_box(box, scale) for box in excluded
        ))
    heights = Counter(round(component.height / 3) * 3 for component, _ in candidates)
    digit_height = (
        trusted_height if trusted_rows else
        fallback_height if fallback_count >= 12 else heights.most_common(1)[0][0]
    )
    barline_candidates = [
        *possible_bars, *_fragmented_vertical_barlines(components, digit_height, gray),
    ]
    main = [
        (component, match)
        for component, match in candidates
        if abs(component.height - digit_height) <= max(3, digit_height * 0.12)
    ]
    alternate = [
        (component, match) for component, match in candidates
        if digit_height * 0.75 <= component.height < digit_height
        and abs(component.height - digit_height) > max(3, digit_height * 0.12)
    ]
    for group in _groups(alternate, digit_height):
        first_main = min((
            base.box[0] for base, _ in main
            if abs(base.center_y - group[0][0].center_y) <= digit_height * 0.3
        ), default=None)
        prefix = [pair for pair in group if first_main is None or pair[0].box[0] < first_main]
        admitted = group if len(prefix) >= 3 else [
            pair for pair in group if first_main is not None and pair[0].box[0] > first_main
        ]
        if admitted and sum(
            _barline(bar, group[0][0].center_y, digit_height, gray)
            and bar.height >= digit_height * 1.5 for bar in possible_bars
        ) >= 2:
            main.extend(admitted)
    known_boxes = {component.box for component, _ in main}
    templates = page_digit_templates(gray, main)
    for group in _groups(main, digit_height):
        # Glyph recovery fills an established staff; it must not create a fragmentary row.
        established = (max(component.box[2] for component, _ in group)
                       - min(component.box[0] for component, _ in group) >= gray.width * 0.12
                       or _by_local_brace(group, components, gray.width, digit_height))
        if established and len(group) >= 3 and any(
            _barline(bar, group[0][0].center_y, digit_height, gray) for bar in possible_bars
        ):
            recovered = _recover_row_digits(
                group, components, digit_height, gray, known_boxes, templates,
            )
            main.extend(recovered)
            candidates.extend(recovered)
    rows = []
    main_groups = _groups(main, digit_height)
    candidate_rows = []
    for group in main_groups:
        group.sort(key=lambda pair: pair[0].box[0])
        local_branch = _by_local_brace(group, components, gray.width, digit_height)
        row = _music_row(
            group, components, digit_height, gray, joined_underlines=scale > 1,
            barline_candidates=barline_candidates,
        )
        candidate_rows.append(row)
        sustained_row = len(row.barlines) >= 2 and len(row_sustains(
            tuple(note.box for note in row.notes), row.unresolved_marks,
        )) >= 3
        if (
            len(group) < 3 and not local_branch and not sustained_row
            or group[-1][0].box[0] - group[0][0].box[0] < gray.width * 0.12
            and not local_branch
        ):
            continue
        if all(match[2] for _, match in group) and not row.barlines:
            continue
        rows.append(row)
    row_boxes = tuple(row.box for row in rows)
    initial_groups = recognize_voice_groups(
        voice_components(components, row_boxes, digit_height, gray),
        row_boxes, gray.width, digit_height, set(),
    )
    compact_overlays = []
    converted_rows: set[int] = set()
    for candidate in candidate_rows:
        if sum(note.duration_slashes > 0 for note in candidate.notes) < len(candidate.notes) * 0.6:
            continue
        owner = compact_accompaniment_owner(
            tuple(note.box for note in candidate.notes),
            tuple(tuple(note.box for note in row.notes) for row in rows),
            initial_groups, components, gray,
        )
        if owner is not None:
            converted_rows.add(id(candidate))
            group = next(group for group, row in zip(main_groups, candidate_rows, strict=True)
                         if row is candidate)
            recovered = _recover_row_digits(
                group, components, digit_height, gray, known_boxes, templates,
            )
            if recovered:
                group.extend(recovered)
                candidates.extend(recovered)
            candidate = _music_row(
                group, components, digit_height, gray, joined_underlines=scale > 1,
                accompaniment=True, barline_candidates=barline_candidates,
            )
            compact_overlays.append((rows[owner], candidate))
    rows = [row for row in rows if id(row) not in converted_rows]
    row_boxes = tuple(row.box for row in rows)
    overlays = recognize_dsb_overlays(components, row_boxes, gray.width, digit_height)
    voice_groups = recognize_voice_groups(
        voice_components(components, row_boxes, digit_height, gray),
        row_boxes, gray.width, digit_height,
        {index for overlay in overlays
         for index in ((overlay.lower,) if overlay.standalone
                       else (overlay.upper, overlay.lower))},
    )
    used_braces = {overlay.box for overlay in overlays} | {group.box for group in voice_groups}
    closing_braces = {overlay.closing_x for overlay in overlays}
    unresolved_braces = tuple(
        component.box for component in components
        if gray.width * 0.10 <= component.box[0] <= gray.width * 0.85
        and digit_height * 0.2 - 1 <= component.width <= digit_height * 1.5
        and digit_height * 2.5 <= component.height <= digit_height * 6
        and component.height >= component.width * 5
        and component.area <= component.width * component.height * 0.62
        and component.box not in used_braces
        and component.box[0] not in closing_braces
        and any(component.box[1] < (box[1] + box[3]) / 2 < component.box[3]
                for box in row_boxes)
    )
    bz_rows = [BzOverlay(rows.index(host), accompaniment)
               for host, accompaniment in compact_overlays]
    main_boxes = {note.box for row in rows for note in row.notes}
    main_boxes.update(note.box for overlay in bz_rows for note in overlay.row.notes)
    smaller = [
        (component, match)
        for component in components
        if component.box not in main_boxes
        and digit_height * 0.65 <= component.height <= digit_height * 0.87
        and any(
            digit_height * 1.3
            < (row.box[1] + row.box[3]) / 2 - component.center_y
            < digit_height * 3.5
            and row.box[0] < component.box[0] < row.box[2]
            for row in rows
        )
        and (match := classify_digit(gray, component, min_score=0.78)) is not None
    ]
    known_boxes.update(component.box for component, _ in smaller)
    for group in _groups(smaller, round(digit_height * 0.78)):
        if len(group) < 3:
            continue
        group.sort(key=lambda pair: pair[0].box[0])
        group_y = sum(component.center_y for component, _ in group) / len(group)
        group_x = (group[0][0].box[0] + group[-1][0].box[2]) / 2
        host_candidates = [
            (index, (row.box[1] + row.box[3]) / 2 - group_y)
            for index, row in enumerate(rows)
            if digit_height * 1.3 < (row.box[1] + row.box[3]) / 2 - group_y
            < digit_height * 3.5
            and row.box[0] < group_x < row.box[2]
        ]
        if not host_candidates:
            continue
        host_index = min(host_candidates, key=lambda pair: pair[1])[0]
        # OCR fallback can mistake sparse lyric glyphs for note digits. A compact run
        # needs either visible parentheses or a nearby onset/barline on a single host bar.
        if not _compact_accompaniment_group(group, components, gray, rows[host_index]):
            continue
        recovered = _recover_row_digits(
            group, components, round(digit_height * 0.78), gray, known_boxes,
        )
        group.extend(recovered)
        candidates.extend(recovered)
        group.sort(key=lambda pair: pair[0].box[0])
        if group[-1][0].box[0] - group[0][0].box[0] < digit_height * 3:
            continue
        small = _music_row(
            group, components, round(digit_height * 0.78), gray,
            joined_underlines=scale > 1, barline_candidates=barline_candidates,
        )
        y = (small.box[1] + small.box[3]) / 2
        anchors = [
            (index, (row.box[1] + row.box[3]) / 2 - y)
            for index, row in enumerate(rows)
            if digit_height * 1.3 < (row.box[1] + row.box[3]) / 2 - y < digit_height * 3.5
            and row.box[0] < small.box[0] < row.box[2]
        ]
        if anchors:
            bz_rows.append(BzOverlay(min(anchors, key=lambda pair: pair[1])[0], small))
    page = PageObservation(
        *gray.size, tuple(rows), len(candidates),
        voice_groups=voice_groups, dsb_overlays=overlays, bz_overlays=tuple(bz_rows),
        unresolved_braces=unresolved_braces,
        excluded_regions=excluded,
    )
    def with_ornaments(row: MusicRow, height: int) -> MusicRow:
        boxes = tuple(note.box for note in row.notes)
        graces = row_graces(boxes, components, gray)
        notes = row.notes
        unresolved_marks = row.unresolved_marks
        if graces:
            # Keep the scale and baseline used when the row's main modifiers were read.
            row_y = sum((note.box[1] + note.box[3]) / 2 for note in notes) / len(notes)
            grace_marks = {
                component.box for component in components
                if any(
                    left <= (component.box[0] + component.box[2]) / 2 <= right
                    and top <= component.center_y <= bottom
                    for left, top, right, bottom in (grace.box for grace in graces)
                )
            }
            score_marks = [
                component for component in components
                if abs(component.center_y - row_y) <= height * 1.6
                and component.box not in grace_marks
            ]
            notes = tuple(replace(note, duration_dots=note_modifiers(
                note.box, score_marks, height, gray if scale > 1 else None,
                min(([notes[index + 1].box[0]] if index + 1 < len(notes) else [])
                    + [x for x in row.barlines if x > note.box[2]], default=None),
            )[2]) for index, note in enumerate(notes))
            unresolved_marks = tuple(mark for mark in unresolved_marks if mark not in grace_marks)
        return replace(
            row,
            notes=notes,
            unresolved_marks=unresolved_marks,
            graces=graces,
            endings=row_endings(boxes, row.barlines, components, gray, graces),
        )

    page = replace(
        page,
        rows=tuple(with_ornaments(row, digit_height) for row in page.rows),
        bz_overlays=tuple(
            replace(overlay, row=with_ornaments(overlay.row, round(median(
                note.box[3] - note.box[1] for note in overlay.row.notes
            ))))
            for overlay in page.bz_overlays
        ),
    )
    page = _source_coordinates(page, scale, source_gray.size)

    def with_slurs(row: MusicRow) -> MusicRow:
        notes = tuple(note.box for note in row.notes)
        height = median(box[3] - box[1] for box in notes)
        others = tuple(other.box for other in (*page.rows, *(bz.row for bz in page.bz_overlays))
                       if other is not row)
        symbols = symbol_decorations(source_gray, notes, source_components, other_rows=others)
        symbol_regions = tuple(symbol.box for symbol in symbols)
        marks = [component for component in source_components if not any(
            left <= (component.box[0] + component.box[2]) / 2 <= right
            and top <= component.center_y <= bottom
            for left, top, right, bottom in symbol_regions
        )]
        parts, core = curve_core_parts(marks, source_gray, row.box[1], height)
        working_marks = [component for component in components if not any(
            left <= (component.box[0] + component.box[2]) / (2 * scale) <= right
            and top <= component.center_y / scale <= bottom
            for left, top, right, bottom in symbol_regions
        )] if symbols else []
        recovered_notes = []
        for index, note in enumerate(row.notes):
            owned = tuple(symbol.token for symbol in symbols if symbol.note_index == index)
            # Tiny dots were read in the enlarged working image. Keep that scale when
            # excluding a fermata's dot, or a genuine two-pixel octave disappears.
            working_box = cast(Box, tuple(coordinate * scale for coordinate in note.box))
            octave = (note_modifiers(working_box, working_marks, round(height * scale))[0]
                      if owned
                      else note.octave or note_modifiers(
                          note.box, parts, round(height), duration_gray=core,
                      )[0])
            recovered_notes.append(replace(
                note, octave=octave, decorations=tuple(dict.fromkeys((*note.decorations, *owned))),
            ))
        unresolved = tuple(box for box in row.unresolved_marks if not any(
            left <= (box[0] + box[2]) / 2 <= right
            and top <= (box[1] + box[3]) / 2 <= bottom
            for left, top, right, bottom in symbol_regions
        ))
        music = tuple(sorted((*notes, *row_sustains(notes, unresolved))))
        hairpins = row_hairpins(source_gray, notes, marks, other_rows=others, music_boxes=music)
        return replace(
            row,
            notes=tuple(recovered_notes), unresolved_marks=unresolved,
            slurs=row_slurs(music, row.box[1], height, marks, source_gray),
            parentheses=row_parentheses(music, height, marks, source_gray),
            hairpins=hairpins, decoration_regions=(*symbol_regions, *(pin.box for pin in hairpins)),
        )

    return replace(
        page, rows=tuple(with_slurs(row) for row in page.rows),
        bz_overlays=tuple(
            replace(overlay, row=with_slurs(overlay.row)) for overlay in page.bz_overlays
        ),
    )
