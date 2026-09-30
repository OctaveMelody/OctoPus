"""Classify printed Jianpu note digits against the project's vector glyphs."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .components import Component
from .text import image_digit

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


def classify_mordent(gray: Image.Image, component: Component) -> bool:
    candidate = _normalized_black_pixels(gray.crop(component.box))
    return _similarity(candidate, _glyph_template("boyinfu_shang1")) >= 0.78


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
) -> DigitMatch | None:
    """Return a digit only when its shape beats competing digit classes."""
    height = component.height
    if not ((6 if grace else 16) <= height <= 75
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
        return (ocr[0], ocr[1], True) if ocr else None
    return ranked[0][0], ranked[0][1], False
