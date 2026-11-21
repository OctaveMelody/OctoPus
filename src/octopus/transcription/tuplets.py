"""Recover numbered tuplet arcs independently of the ordinary slur detector."""

from __future__ import annotations

from statistics import median
from typing import cast

from PIL import Image

from .components import Component
from .glyphs import is_tuplet_number
from .observations import Note


def _arc_flank(gray: Image.Image, component: Component, *, rising: bool) -> bool:
    left, top, right, bottom = component.box
    middle = (left + right) // 2
    pixels = gray.load()
    assert pixels is not None
    halves = [
        [y for x in range(start, end) for y in range(top, bottom)
         if cast(int, pixels[x, y]) < 160]
        for start, end in ((left, middle), (middle, right))
    ]
    if not all(halves):
        return False
    rise = median(halves[0]) - median(halves[1])
    return (rise if rising else -rise) >= max(1, component.height * 0.2)


def row_tuplets(
    gray: Image.Image, notes: tuple[Note, ...], components: list[Component],
    barlines: tuple[int, ...],
) -> tuple[tuple[int, int], ...]:
    """Require two arc flanks and a numeral matching the short notes they enclose."""
    if not notes:
        return ()
    centers = [(note.box[0] + note.box[2]) / 2 for note in notes]
    height = median(note.box[3] - note.box[1] for note in notes)
    top = min(note.box[1] for note in notes)
    band = [
        item for item in components
        if centers[0] - height * 0.4 <= item.box[0]
        and item.box[2] <= centers[-1] + height * 0.4
        and top - height * 1.4 <= item.box[1]
        and item.box[3] <= top - height * 0.12
    ]
    candidates: set[tuple[int, int]] = set()
    for number in band:
        x0, y0, x1, y1 = number.box
        if not height * 0.32 <= number.height <= height * 0.72:
            continue
        center = (x0 + x1) / 2
        wings = [
            part for part in band if part != number
            and part.width >= height * 0.25
            and height * 0.10 <= part.height <= height * 0.58
            and y0 <= part.center_y <= y1 + height * 0.35
        ]
        left_wings = [
            wing for wing in wings if 0 <= x0 - wing.box[2] <= height * 0.45
            and _arc_flank(gray, wing, rising=True)
        ]
        right_wings = [
            wing for wing in wings if 0 <= wing.box[0] - x1 <= height * 0.45
            and _arc_flank(gray, wing, rising=False)
        ]
        for left in left_wings:
            start = min(range(len(notes)), key=lambda i: abs(centers[i] - left.box[0]))
            if abs(centers[start] - left.box[0]) > height * 0.45:
                continue
            for right in right_wings:
                end = min(range(len(notes)), key=lambda i: abs(centers[i] - right.box[2]))
                count = end - start + 1
                if not 2 <= count <= 9 or abs(centers[end] - right.box[2]) > height * 0.45:
                    continue
                wings_limit = height * (1.45 if count <= 3 else count * 0.48)
                if max(left.width, right.width) > wings_limit:
                    continue
                middle = (centers[(start + end) // 2] + centers[(start + end + 1) // 2]) / 2
                if (abs(center - middle) <= height * 0.6
                        and all(note.duration_slashes for note in notes[start:end + 1])
                        and not any(centers[start] < bar < centers[end] for bar in barlines)
                        and is_tuplet_number(gray, number, count)):
                    candidates.add((start, end))
    # Crossing guesses cannot be expressed as nested JPS spans.
    return tuple((start, end) for start, end in sorted(candidates) if not any(
        start < left <= end < right or left < start <= right < end
        for left, right in candidates
    ))
