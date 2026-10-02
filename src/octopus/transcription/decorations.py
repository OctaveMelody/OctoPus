"""Recognize bounded performance instructions by their ink and note ownership."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from statistics import linear_regression, median
from typing import cast

from PIL import Image

from .components import Box, Component
from .glyphs import (
    GLYPHS,
    _glyph_template,
    _normalized_black_pixels,
    _similarity,
    classify_mordent,
)
from .text import TextSpan

_GLYPH_WORDS = frozenset({"p", "pp", "mp", "mf", "f", "ff", "rit", "dim", "yc"})
_DYNAMIC_WORDS = frozenset({"p", "pp", "mp", "mf", "f", "ff"})
_ANNOTATION_WORDS = frozenset({
    "cres", "cresc", "crescendo", "decres", "decresc", "decrescendo", "rall",
    "rallentando", "ritardando", "accelerando", "accel", "a tempo", "fff", "sf", "fp", "sfp",
    "慢", "渐慢", "渐快", "渐强", "渐弱", "稍慢", "稍快", "延长",
})
_ABBREVIATION_FAMILIES = (
    frozenset({"cres", "cresc", "crescendo"}),
    frozenset({"decres", "decresc", "decrescendo"}),
    frozenset({"rit", "ritardando"}),
    frozenset({"rall", "rallentando"}),
    frozenset({"accel", "accelerando"}),
)


@dataclass(frozen=True, slots=True)
class TextDecoration:
    """A supported glyph name, or a complete quoted JPS note annotation."""

    note_index: int
    token: str
    box: Box
    source_spans: tuple[TextSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class Hairpin:
    start: int
    end: int
    code: str
    box: Box


def decoration_token(value: str) -> str | None:
    """Require a whole known instruction; never turn a substring into a dynamic."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    lower = re.sub(r"\s+", " ", normalized).lower()
    word = lower.rstrip(".")
    if word in _GLYPH_WORDS:
        return word
    if word in _ANNOTATION_WORDS:
        return '"' + lower + '"'
    return None


def _union(boxes: tuple[Box, ...]) -> Box:
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def _above_row(
    box: Box, notes: tuple[Box, ...], height: float, other_rows: tuple[Box, ...],
) -> bool:
    top = median(note[1] for note in notes)
    center_y = (box[1] + box[3]) / 2
    if not (
        top - height * 2.6 <= box[1]
        and box[3] <= top + height * 0.08
        and center_y <= top - height * 0.12
        and box[2] >= notes[0][0] - height
        and box[0] <= notes[-1][2] + height
    ):
        return False
    # Printed lyrics just under another voice/row must not migrate upward or downward.
    return not any(
        box[2] > other[0] and box[0] < other[2] and (
            other[1] <= center_y <= other[3] + height * 1.25
            or center_y < other[1] < top
        )
        for other in other_rows
    )


def _text_owner(
    box: Box, token: str, notes: tuple[Box, ...], height: float,
) -> int | None:
    x = box[0] + min(height * 0.45, (box[2] - box[0]) / 2) if token.startswith('"') \
        else (box[0] + box[2]) / 2
    index = min(range(len(notes)), key=lambda i: abs((notes[i][0] + notes[i][2]) / 2 - x))
    return index if abs((notes[index][0] + notes[index][2]) / 2 - x) <= height * 1.15 \
        else None


def _lyric_character(
    span: TextSpan, spans: tuple[TextSpan, ...], height: float, other_rows: tuple[Box, ...],
) -> bool:
    """A lone Chinese instruction word can also be a character in a sung phrase."""
    word = span.text.strip()
    if (len(word) != 1 or not "\u3400" <= word <= "\u9fff" or not any(
        other[3] < span.center_y and other[0] < span.box[2] and span.box[0] < other[2]
        for other in other_rows
    )):
        return False
    context = tuple(other for other in spans if (
        other is not span and other.confidence >= 0.8
        and any("\u3400" <= char <= "\u9fff" for char in other.text)
        and decoration_token(other.text) is None
        and abs(other.center_y - span.center_y) <= height * 0.3
        and max(other.box[0] - span.box[2], span.box[0] - other.box[2], 0) <= height * 3
    ))
    return (any(word in other.text and len(other.text.strip()) > 1
                and other.box[0] <= span.center_x <= other.box[2] for other in context)
            or any(other.box[2] <= span.box[0] for other in context)
            and any(other.box[0] >= span.box[2] for other in context))


def text_decorations(
    note_boxes: tuple[Box, ...], spans: tuple[TextSpan, ...],
    *, other_rows: tuple[Box, ...] = (), gray: Image.Image | None = None,
) -> tuple[TextDecoration, ...]:
    """Associate exact OCR instructions above a note, including compact split words."""
    if not note_boxes:
        return ()
    height = median(box[3] - box[1] for box in note_boxes)
    candidates = sorted((span for span in spans if (
        span.confidence >= (0.55 if gray is not None else 0.8)
        and height * 0.2 <= span.height <= height * 1.25
        and _above_row(span.box, note_boxes, height, other_rows)
        and not _lyric_character(span, spans, height, other_rows)
    )), key=lambda span: (span.box[0], span.box[1]))
    found: list[TextDecoration] = []
    consumed: set[TextSpan] = set()
    for start, span in enumerate(candidates):
        if span in consumed:
            continue
        group = [span]
        # Prefer a contiguous recognized pair (m + p, f + f, rit + .) to two marks.
        for later in candidates[start + 1:start + 3]:
            previous = group[-1]
            if (later in consumed or len(group) >= 3
                    or not -height * 0.08 <= later.box[0] - previous.box[2]
                    <= height * 0.24
                    or abs(later.center_y - previous.center_y) > height * 0.2
                    or not re.fullmatch(r"[A-Za-z.．]+", later.text.strip())
                    or not re.fullmatch(r"[A-Za-z.．]+", previous.text.strip())):
                break
            group.append(later)
        choices = [tuple(group[:length]) for length in range(len(group), 0, -1)]
        for selected in choices:
            value = "".join(item.text.strip() for item in selected)
            token = decoration_token(value)
            if token is None:
                continue
            box = _union(tuple(item.box for item in selected))
            if box[2] - box[0] > height * 9:
                continue
            glyph = _glyph_reading(gray, box) if gray is not None and token in _GLYPH_WORDS \
                else None
            if token in _DYNAMIC_WORDS and glyph in _DYNAMIC_WORDS:
                # Italic double f/p often receives a confident one-letter OCR reading.
                token = glyph
            confidence = min(item.confidence for item in selected)
            threshold = 0.88 if len(value.strip(".．")) == 1 else 0.8
            if confidence < threshold and glyph != token:
                continue
            index = _text_owner(box, token, note_boxes, height)
            if index is not None:
                duplicate = next((item for item in found if (
                    item.note_index == index and (
                        item.token in _DYNAMIC_WORDS and token in _DYNAMIC_WORDS
                        and _overlap(item.box, box) >= 0.6
                        or _same_instruction(item.token, token)
                        and _overlap(item.box, box) >= 0.6
                    )
                )), None)
                if duplicate is not None:
                    found.remove(duplicate)
                    keep_previous = _prefer_previous(duplicate, token, box, confidence)
                    selected = tuple(dict.fromkeys((*duplicate.source_spans, *selected)))
                    if keep_previous:
                        token, box = duplicate.token, duplicate.box
                found.append(TextDecoration(index, token, box, selected))
                consumed.update(selected)
                break
    return tuple(found)


def _area(box: Box) -> int:
    return (box[2] - box[0]) * (box[3] - box[1])


def _overlap(first: Box, second: Box) -> float:
    intersection = max(0, min(first[2], second[2]) - max(first[0], second[0])) \
        * max(0, min(first[3], second[3]) - max(first[1], second[1]))
    return intersection / max(1, min(_area(first), _area(second)))


def _instruction_word(token: str) -> str:
    return token.strip('"').rstrip(".")


def _same_instruction(first: str, second: str) -> bool:
    a, b = _instruction_word(first), _instruction_word(second)
    return first == second or any(a in family and b in family
                                 for family in _ABBREVIATION_FAMILIES)


def _prefer_previous(
    previous: TextDecoration, token: str, box: Box, confidence: float,
) -> bool:
    if previous.token != token and _same_instruction(previous.token, token):
        matching = [span.confidence for span in previous.source_spans
                    if decoration_token(span.text) == previous.token]
        prior_confidence = max(matching or [span.confidence for span in previous.source_spans])
        if abs(prior_confidence - confidence) > 0.08:
            return prior_confidence > confidence
        prior_length = len(_instruction_word(previous.token))
        current_length = len(_instruction_word(token))
        if prior_length != current_length:
            return prior_length > current_length
    return _area(previous.box) > _area(box)


def _glyph_reading(gray: Image.Image, box: Box) -> str | None:
    crop = gray.crop(box)
    ink_box = crop.point(lambda value: 255 if value < 160 else 0).getbbox()
    if ink_box is None:
        return None
    crop = crop.crop(ink_box)
    candidate = _normalized_black_pixels(crop)
    scores = {word: _similarity(candidate, _glyph_template("lidu_" + word))
              for word in _GLYPH_WORDS if word != "yc"}
    if crop.height <= 16:
        # Rasterization at a small printed size changes thin italic strokes. Compare
        # the same canonical glyphs at their native size without lowering the proof gate.
        for word, template in _small_glyph_templates():
            scores[word] = max(scores[word], _similarity(candidate, template))
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[0][0] if ranked[0][1] >= 0.78 \
        and ranked[0][1] - ranked[1][1] >= 0.12 else None


@lru_cache(maxsize=1)
def _small_glyph_templates() -> tuple[tuple[str, int], ...]:
    import resvg_py  # type: ignore[import-untyped]

    templates = []
    for word in sorted(_GLYPH_WORDS - {"yc"}):
        asset = GLYPHS / f"lidu_{word}.svg"
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
               'viewBox="-50 -50 100 100">' + asset.read_text(encoding="utf-8") + "</svg>")
        rgba = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        gray = white.convert("L")
        box = gray.point(lambda value: 255 if value < 160 else 0).getbbox()
        if box is not None:
            templates.append((word, _normalized_black_pixels(gray.crop(box))))
    return tuple(templates)


def _two_branches(gray: Image.Image, box: Box, height: float) -> str | None:
    """Distinguish two straight, diverging arms from slurs, rules and underlines."""
    pixels = gray.load()
    assert pixels is not None
    left, top, right, bottom = box
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    columns = 0
    for x in range(left, right):
        ink = [y for y in range(top, bottom) if cast(int, pixels[x, y]) < 160]
        if not ink:
            continue
        runs: list[list[int]] = [[ink[0]]]
        for y in ink[1:]:
            if y > runs[-1][-1] + 1:
                runs.append([])
            runs[-1].append(y)
        if len(runs) == 2 and max(map(len, runs)) <= max(3, height * 0.16):
            upper.append((float(x), sum(runs[0]) / len(runs[0])))
            lower.append((float(x), sum(runs[1]) / len(runs[1])))
        elif len(runs) > 2:
            return None
        columns += 1
    width = right - left
    if columns < width * 0.9 or len(upper) < width * 0.62:
        return None
    first = linear_regression([x for x, _ in upper], [y for _, y in upper])
    second = linear_regression([x for x, _ in lower], [y for _, y in lower])
    if first.slope * second.slope >= 0 or min(abs(first.slope), abs(second.slope)) < 0.008:
        return None
    for points, fit in ((upper, first), (lower, second)):
        residual = sum(abs(y - fit.slope * x - fit.intercept) for x, y in points) / len(points)
        if residual > max(0.9, height * 0.04):
            return None
    gaps = [second.slope * x + second.intercept - first.slope * x - first.intercept
            for x in (left, right - 1)]
    narrow, wide = sorted(gaps)
    if not -2 <= narrow <= max(4, height * 0.16) or wide < height * 0.2 \
            or wide - narrow < height * 0.18:
        return None
    return "<" if gaps[0] < gaps[1] else ">"


def row_hairpins(
    gray: Image.Image, note_boxes: tuple[Box, ...], components: list[Component],
    *, other_rows: tuple[Box, ...] = (), music_boxes: tuple[Box, ...] | None = None,
) -> tuple[Hairpin, ...]:
    """Return only complete above-row wedges with visible, note-owned endpoints."""
    if len(note_boxes) < 2:
        return ()
    height = median(box[3] - box[1] for box in note_boxes)
    arms = [component for component in components if (
        component.width >= height * 1.8 and 2 <= component.height <= height * 1.1
        and component.area <= component.width * max(6, height * 0.24)
        and _above_row(component.box, note_boxes, height, other_rows)
    )]
    boxes = [arm.box for arm in arms]
    # Scans can leave the vertex disconnected; both arms must share their full span.
    boxes.extend(_union((a.box, b.box)) for a, b in combinations(arms, 2) if (
        min(a.box[2], b.box[2]) - max(a.box[0], b.box[0])
        >= max(a.width, b.width) * 0.85
        and abs(a.box[0] - b.box[0]) <= height * 0.2
        and abs(a.box[2] - b.box[2]) <= height * 0.2
        and max(a.box[3], b.box[3]) - min(a.box[1], b.box[1]) <= height * 1.1
    ))
    centers = [(box[0] + box[2]) / 2 for box in (music_boxes or note_boxes)]
    found: list[Hairpin] = []
    for box in dict.fromkeys(boxes):
        code = _two_branches(gray, box, height)
        if code is None:
            continue
        start = min(range(len(centers)), key=lambda i: abs(centers[i] - box[0]))
        end = min(range(len(centers)), key=lambda i: abs(centers[i] - box[2]))
        if start < end and max(abs(centers[start] - box[0]), abs(centers[end] - box[2])) \
                <= height * 1.15:
            found.append(Hairpin(start, end, code, box))
    return tuple(found)


def symbol_decorations(
    gray: Image.Image, note_boxes: tuple[Box, ...], components: list[Component],
    *, other_rows: tuple[Box, ...] = (),
) -> tuple[TextDecoration, ...]:
    """Recognize a fermata only from a short arch and its separate centered dot."""
    if not note_boxes:
        return ()
    height = median(box[3] - box[1] for box in note_boxes)
    pixels = gray.load()
    assert pixels is not None
    found: list[TextDecoration] = []
    for arch in components:
        if not (
            height * 0.5 <= arch.width <= height * 1.65
            and height * 0.15 <= arch.height <= height * 0.65
            and arch.area <= arch.width * max(5, height * 0.22)
            and _above_row(arch.box, note_boxes, height, other_rows)
        ):
            continue
        left, top, right, bottom = arch.box
        center_x = (left + right) / 2
        dots = [component for component in components if (
            height * 0.05 <= component.width <= height * 0.25
            and height * 0.05 <= component.height <= height * 0.25
            and component.area >= max(2, component.width * component.height * 0.45)
            and left + arch.width * 0.15
            <= (component.box[0] + component.box[2]) / 2 <= right - arch.width * 0.15
            and top + arch.height * 0.25 < component.box[1]
            and component.box[3] <= bottom + height * 0.1
        )]
        if len(dots) != 1:
            continue
        dot = dots[0]
        dot_x = (dot.box[0] + dot.box[2]) / 2
        arch_box = arch.box
        if abs(dot_x - center_x) > arch.width * 0.18 or not _arch_rises(gray, arch_box):
            # A tiny fermata may touch the neighboring slur. Its inner dot defines a
            # bounded local arch; require both ends to drop below the local crown.
            if arch.width < height * 0.9:
                continue
            arch_box = (max(left, round(dot_x - height * 0.35)), top,
                        min(right, round(dot_x + height * 0.35)), bottom)
            ink = [(x, y) for x in range(arch_box[0], arch_box[2])
                   for y in range(top, bottom) if cast(int, pixels[x, y]) < 160]
            if not ink:
                continue
            arch_box = (min(x for x, _ in ink), min(y for _, y in ink),
                        max(x for x, _ in ink) + 1, max(y for _, y in ink) + 1)
            if arch_box[2] - arch_box[0] < height * 0.5 or not _arch_rises(gray, arch_box):
                continue
        if _body_below_arch(gray, arch_box, arch, dot, components, height):
            # CJK roofs (for example 今/念) can resemble an arch and inner dot.
            # Their immediate broad character strokes are absent from a fermata.
            continue
        index = _text_owner(dot.box, "yc", note_boxes, height)
        if index is not None and abs((note_boxes[index][0] + note_boxes[index][2]) / 2
                                     - dot_x) <= height * 0.4:
            found.append(TextDecoration(index, "yc", _union((arch_box, dot.box))))
    return tuple(found)


def _body_below_arch(
    gray: Image.Image, box: Box, arch: Component, dot: Component,
    components: list[Component], height: float,
) -> bool:
    left, _, right, bottom = box
    width = right - left
    center_x = (left + right) / 2
    return any(
        component != arch and component != dot
        and component.width >= width * 0.3
        and component.height >= max(3, height * 0.12)
        and bottom - height * 0.05 <= component.box[1] <= bottom + height * 0.25
        and abs((component.box[0] + component.box[2]) / 2 - center_x) <= width * 0.4
        # A separately proven mordent can share the same host below a fermata.
        and not classify_mordent(gray, component)
        for component in components
    )


def _arch_rises(gray: Image.Image, box: Box) -> bool:
    left, top, right, bottom = box
    width = right - left
    pixels = gray.load()
    assert pixels is not None
    samples = []
    for start, end in ((left, left + max(1, round(width * 0.12))),
                       (left + round(width * 0.4), left + round(width * 0.6)),
                       (right - max(1, round(width * 0.12)), right)):
        ys = [y for x in range(start, end) for y in range(top, bottom)
              if cast(int, pixels[x, y]) < 160]
        if not ys:
            return False
        samples.append(min(ys))
    return min(samples[0], samples[2]) >= samples[1] + max(2, round((bottom - top) * 0.35))
