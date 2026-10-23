"""Classify printed Jianpu note digits against the project's vector glyphs."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import cast

from PIL import Image

from .components import Component
from .text import image_digit

MIN_NOTE_DIGIT_HEIGHT = 16
MAX_DIGIT_HEIGHT = 75
MIN_PAGE_DIGIT_SUPPORT = 0.86
# Real glyph pixels remain evidence when a neighboring font template scores slightly higher.
MIN_CONTRADICTED_OCR_GLYPH_SUPPORT = 0.4

GLYPHS = Path(__file__).resolve().parents[1] / "assets" / "glyphs"
NORMALIZED_SIZE = (24, 36)
DigitMatch = tuple[str, float, bool]


def _normalized_black_pixels(image: Image.Image) -> int:
    resized = image.resize(NORMALIZED_SIZE, Image.Resampling.NEAREST)
    return int.from_bytes(
        resized.point(lambda value: 255 if value < 160 else 0).tobytes(), "little"
    )


@lru_cache(maxsize=3)
def _templates(
    grace: bool = False, *, accidentals: bool = False,
) -> tuple[tuple[str, str, int], ...]:
    templates = []
    for font in ("",) if accidentals else ("yiyin",) if grace else "abc":
        for digit in "#$=" if accidentals else "1234567" if grace else "01234567":
            stem = (
                "bianyinfu_" + {"#": "sheng", "$": "jiang", "=": "huanyuan"}[digit]
                if accidentals else f"yiyin_shuzi_{digit}" if grace else f"shuzi_{font}_{digit}"
            )
            template = _glyph_template(stem)
            if template:
                templates.append((font, digit, template))
    return tuple(templates)


@lru_cache(maxsize=64)
def _glyph_template(stem: str) -> int:
    import resvg_py  # type: ignore[import-untyped]

    asset = GLYPHS / f"{stem}.svg"
    if not asset.is_file():
        return 0
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
           'viewBox="-50 -50 100 100">' + asset.read_text(encoding="utf-8") + "</svg>")
    raster = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, zoom=2))).convert("RGBA")
    white = Image.new("RGBA", raster.size, "white")
    white.alpha_composite(raster)
    gray = white.convert("L")
    box = gray.point(lambda value: 255 if value < 160 else 0).getbbox()
    return _normalized_black_pixels(gray.crop(box)) if box is not None else 0


def _similarity(candidate: int, template: int) -> float:
    intersection = (candidate & template).bit_count()
    union = (candidate | template).bit_count()
    return intersection / union if union else 0.0


def _digit_scores(
    gray: Image.Image, component: Component, grace: bool = False,
) -> dict[str, float]:
    candidate = _normalized_black_pixels(gray.crop(component.box))
    scores: dict[str, float] = {}
    for _, digit, template in _templates(grace):
        scores[digit] = max(scores.get(digit, 0.0), _similarity(candidate, template))
    return scores


def digit_shape_similarity(gray: Image.Image, component: Component, digit: str) -> float:
    """Corroborate an OCR digit against the existing vector glyph shapes."""
    scores = _digit_scores(gray, component)
    return scores.get(digit, 0.0)


def page_digit_templates(
    gray: Image.Image, accepted: list[tuple[Component, DigitMatch]],
) -> tuple[tuple[str, int], ...]:
    """Use high-confidence glyphs observed on this page as additional font evidence."""
    return tuple((match[0], _normalized_black_pixels(gray.crop(component.box)))
                 for component, match in accepted if match[1] >= 0.95)


def _page_digit_scores(
    gray: Image.Image, component: Component, templates: tuple[tuple[str, int], ...],
) -> dict[str, float]:
    candidate = _normalized_black_pixels(gray.crop(component.box))
    scores: dict[str, list[float]] = {}
    for digit, template in templates:
        scores.setdefault(digit, []).append(_similarity(candidate, template))
    return {digit: sorted(values, reverse=True)[1]
            for digit, values in scores.items() if len(values) >= 2}


def ocr_digit_has_page_conflict(
    gray: Image.Image,
    component: Component,
    reported_digit: str,
    templates: tuple[tuple[str, int], ...],
) -> bool:
    """Reject an OCR label only when independent page and vector evidence disagree."""
    page_scores = _page_digit_scores(gray, component, templates)
    reported_score = page_scores.get(reported_digit)
    competitors = [digit for digit, score in page_scores.items()
                   if digit != reported_digit and score >= MIN_PAGE_DIGIT_SUPPORT]
    if reported_score is None or reported_score >= MIN_PAGE_DIGIT_SUPPORT or not competitors:
        return False
    vector_scores = _digit_scores(gray, component)
    reported_shape = vector_scores.get(reported_digit, 0.0)
    return any(vector_scores.get(digit, 0.0) > reported_shape for digit in competitors)


def match_page_digit(
    gray: Image.Image, component: Component, templates: tuple[tuple[str, int], ...],
) -> DigitMatch | None:
    """Require two agreeing exemplars and separation from every competing digit."""
    ranked = sorted(_page_digit_scores(gray, component, templates).items(),
                    key=lambda item: item[1], reverse=True)
    if (len(ranked) < 2 or ranked[0][1] < MIN_PAGE_DIGIT_SUPPORT
            or ranked[0][1] - ranked[1][1] < 0.1):
        return None
    return ranked[0][0], ranked[0][1], True


def classify_mordent(gray: Image.Image, component: Component) -> bool:
    candidate = _normalized_black_pixels(gray.crop(component.box))
    return (_similarity(candidate, _glyph_template("boyinfu_shang1")) >= 0.78
            or _wavy_mordent_stroke(gray, component))


def _wavy_mordent_stroke(gray: Image.Image, component: Component) -> bool:
    """Recognize a short multi-turn ornament when small raster ink misses the template."""
    left, top, right, bottom = component.box
    width, height = right - left, bottom - top
    if height <= 0 or width < height * 1.2:
        return False
    pixels = gray.load()
    assert pixels is not None
    centers: list[tuple[int, float]] = []
    occupied = 0
    for x in range(left, right):
        ink = [y for y in range(top, bottom) if cast(int, pixels[x, y]) < 160]
        if not ink or len(ink) > max(3, height * 0.4):
            continue
        occupied += 1
        centers.append((x, sum(ink) / len(ink)))
    if occupied < width * 0.7:
        return False
    ordinates = [center for _, center in centers]
    if max(ordinates) - min(ordinates) < max(2, height * 0.25):
        return False
    directions: list[int] = []
    for (left_x, left_y), (right_x, right_y) in zip(centers, centers[1:], strict=False):
        if right_x - left_x > max(2, round(width * 0.12)):
            continue
        delta = right_y - left_y
        if abs(delta) >= max(1, height * 0.06):
            direction = 1 if delta > 0 else -1
            if not directions or directions[-1] != direction:
                directions.append(direction)
    return sum(a != b for a, b in zip(directions, directions[1:], strict=False)) >= 2


def classify_accidental(gray: Image.Image, component: Component) -> str | None:
    candidate = _normalized_black_pixels(gray.crop(component.box))
    ranked = sorted(
        ((symbol, _similarity(candidate, template))
         for _, symbol, template in _templates(accidentals=True)),
        key=lambda item: item[1], reverse=True,
    )
    if ranked[0][1] >= 0.78 and ranked[0][1] - ranked[1][1] >= 0.1:
        return ranked[0][0]
    ocr = image_digit(gray, component.box, "#♯♭♮")
    return {"#": "#", "♯": "#", "♭": "$", "♮": "="}[ocr[0]] if ocr else None


def classify_digit(
    gray: Image.Image, component: Component, min_score: float = 0.83,
    allow_ocr: bool = True, *, grace: bool = False,
    page_templates: tuple[tuple[str, int], ...] = (),
) -> DigitMatch | None:
    """Return a digit only when its shape supports or does not contradict OCR."""
    height = component.height
    if not ((6 if grace else MIN_NOTE_DIGIT_HEIGHT) <= height <= MAX_DIGIT_HEIGHT
            and height * 0.2 <= component.width <= height):
        return None
    if component.area < max(8 if grace else 18, height):
        return None
    by_digit = _digit_scores(gray, component, grace)
    ranked = sorted(by_digit.items(), key=lambda item: item[1], reverse=True)
    if len(ranked) < 2 or ranked[0][1] < min_score or ranked[0][1] - ranked[1][1] < 0.04:
        if not allow_ocr:
            return None
        ocr = image_digit(gray, component.box, "1234567" if grace else "01234567")
        if ocr is None:
            return None
        if not grace:
            best_shape = max(by_digit.values(), default=0.0)
            reported_shape = by_digit.get(ocr[0], 0.0)
            page_match = match_page_digit(gray, component, page_templates)
            contradicted_without_page_match = (
                best_shape - reported_shape > 0.1
                and (page_match is None or page_match[0] != ocr[0])
                and reported_shape < MIN_CONTRADICTED_OCR_GLYPH_SUPPORT
            )
            if reported_shape <= 0 or contradicted_without_page_match:
                return None
        return ocr[0], ocr[1], True
    return ranked[0][0], ranked[0][1], False
