"""Classify visible title, credit, key, meter and tempo text above the score."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image

from .components import Box, Component, connected_components
from .image import _read_page, _score_components
from .text import TextSpan, image_digit

_KEY = re.compile(r"1\s*[=＝]\s*([b♭#♯$]?)([A-Ga-g])\s*([#♯$♭]?)")
_METER = re.compile(r"(?<!\d)(\d{1,2})\s*[/／]\s*(\d{1,2})(?!\d)")
_TEMPO = re.compile(r"[Jj♩♪]?\s*[=＝:]\s*(\d{2,3})")
_NUMBER = re.compile(r"[Xx]\s*[:：=]\s*(\d+)")


@dataclass(frozen=True, slots=True)
class HeaderResult:
    lines: tuple[str, ...]
    missing: tuple[str, ...]
    regions: tuple[Box, ...]


def printed_key_span(
    path: Path, first_music_top: int, excluded_regions: tuple[Box, ...] = (),
) -> TextSpan | None:
    """Read an isolated 1=letter key anchored by its two equal-sign strokes."""
    gray = _read_page(path)
    components = [component for component in _score_components(gray, excluded_regions)
                  if component.box[3] < first_music_top - 8]
    strokes = [component for component in components
               if 6 <= component.width <= max(40, gray.width * 0.04)
               and component.height <= max(4, component.width * 0.25)]
    for upper in strokes:
        for lower in strokes:
            if not (
                1 <= lower.box[1] - upper.box[3] <= upper.width * 0.5
                and abs(upper.box[0] - lower.box[0]) <= 2
                and abs(upper.width - lower.width) <= 2
            ):
                continue
            height = max(16, round(upper.width * 1.4))
            center_y = (upper.box[1] + lower.box[3]) / 2
            digits = [component for component in components
                      if height * 0.65 <= component.height <= height * 1.5
                      and abs(component.center_y - center_y) <= height * 0.3]
            one = next((component for component in digits
                        if 0 <= upper.box[0] - component.box[2] <= height * 0.7
                        and image_digit(gray, component.box, "1")), None)
            if one is None:
                continue
            for letter in digits:
                if not 0 <= letter.box[0] - upper.box[2] <= height * 1.4:
                    continue
                match = image_digit(gray, letter.box, "ABCDEFG")
                if match:
                    signs = [
                        (sign, reading) for sign in components
                        if sign.box != letter.box
                        and height * 0.35 <= sign.height <= height * 1.3
                        and sign.width <= height * 0.65
                        and abs(sign.center_y - letter.center_y) <= height * 0.9
                        and (upper.box[2] <= (sign.box[0] + sign.box[2]) / 2
                             < (letter.box[0] + letter.box[2]) / 2
                             or 0 <= sign.box[0] - letter.box[2] <= height * 0.6)
                        and (reading := image_digit(gray, sign.box, "b♭#♯$")) is not None
                    ]
                    if letter.box[0] - upper.box[2] > height * 0.7 and len(signs) != 1:
                        continue
                    owned = [one, letter]
                    accidental = ""
                    confidence = match[1]
                    if len(signs) == 1:
                        sign, reading = signs[0]
                        owned.append(sign)
                        accidental = "$" if reading[0] in "b♭$" else "#"
                        confidence = min(confidence, reading[1])
                    return TextSpan(
                        f"1={match[0]}{accidental}",
                        (min(mark.box[0] for mark in owned), min(mark.box[1] for mark in owned),
                         max(mark.box[2] for mark in owned), max(mark.box[3] for mark in owned)),
                        confidence,
                    )
    return None


def _fraction_components(gray: Image.Image, components: list[Component]) -> list[Component]:
    """Separate fraction digits from a rule joined by low-resolution printing ink."""
    found = list(components)
    for component in components:
        left, top, right, bottom = component.box
        if 10 <= component.height <= 40 and 4 <= component.width <= component.height:
            # In a tiny scan the rule can connect both digits, leaving a single
            # component. Require a wider internal rule and visible ink on both sides.
            rule_rows = [
                y for y in range(top + 4, bottom - 4)
                if sum(cast(int, gray.getpixel((x, y))) < 160 for x in range(left, right))
                >= component.width * 0.8
            ]
            if rule_rows and rule_rows[-1] - rule_rows[0] <= 2:
                upper_bottom, lower_top = rule_rows[0], rule_rows[-1] + 1
                upper = connected_components(gray.crop((left, top, right, upper_bottom)))
                lower = connected_components(gray.crop((left, lower_top, right, bottom)))
                if (len(upper) == len(lower) == 1
                        and min(upper[0].height, lower[0].height) >= 4
                        and component.width > max(upper[0].width, lower[0].width)):
                    # Keep the rule's horizontal extent as OCR breathing room.
                    found.extend((
                        Component((left, top + upper[0].box[1], right, upper_bottom),
                                  upper[0].area),
                        Component((left, lower_top, right, bottom), lower[0].area),
                        Component((left, upper_bottom, right, lower_top),
                                  (lower_top - upper_bottom) * component.width),
                    ))
        if not (6 <= component.height <= 40 and component.width >= component.height * 0.65):
            continue
        rows = [y for y in range(bottom - max(2, round(component.height * 0.25)), bottom)
                if sum(cast(int, gray.getpixel((x, y))) < 160 for x in range(left, right))
                >= component.width * 0.9]
        if not rows or rows[-1] < bottom - 2:
            continue
        line_top = rows[0]
        if line_top - top < 6:
            continue
        pieces = connected_components(gray.crop((left, top, right, line_top)))
        if len(pieces) != 1:
            continue
        piece = pieces[0]
        if piece.height < 6:
            continue
        found.extend((Component((left + piece.box[0], top + piece.box[1],
                                 left + piece.box[2], top + piece.box[3]), piece.area),
                      Component((left, line_top, right, rows[-1] + 1),
                                (rows[-1] - line_top + 1) * component.width)))
    return found


def _meter_digit(gray: Image.Image, box: Box) -> tuple[str, float] | None:
    """Read small fraction ink at usable resolution without lowering OCR confidence."""
    digit = image_digit(gray, box, "0123456789")
    height = box[3] - box[1]
    if digit is not None or height >= 12:
        return digit
    crop = gray.crop(box)
    scale = min(4, max(2, (24 + height - 1) // height))
    enlarged = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS)
    return image_digit(enlarged, (0, 0, enlarged.width, enlarged.height), "0123456789")


def stacked_meter_span(
    path: Path, spans: tuple[TextSpan, ...], first_music_top: int
) -> TextSpan | None:
    """Recover a printed fraction beside the key when whole-page OCR merged its digits."""
    key = next((span for span in spans if _KEY.search(span.text)), None)
    if key is None:
        return None
    gray = _read_page(path)
    components = [
        component for component in connected_components(gray)
        if key.box[2] - key.height * 0.7 <= component.box[0] <= key.box[2] + key.height * 1.7
        and key.box[1] - key.height * 0.55 <= component.box[1]
        < component.box[3] < first_music_top - 8
    ]
    components = _fraction_components(gray, components)
    digits = [
        component for component in components
        if 4 <= component.height <= key.height * 0.8
        and component.height * 0.45 <= component.width <= component.height * 1.5
    ]
    for top in digits:
        for bottom in digits:
            if not (
                0 < bottom.box[1] - top.box[3] <= max(6, top.height)
                and abs((top.box[0] + top.box[2] - bottom.box[0] - bottom.box[2]) / 2)
                <= max(4, top.width * 0.5)
            ):
                continue
            separator = any(
                line.box[1] >= top.box[3]
                and line.box[3] <= bottom.box[1] + 1
                and line.height <= max(3, min(top.height, bottom.height) * 0.2)
                and line.width >= max(top.width, bottom.width)
                and line.box[0] <= max(top.box[0], bottom.box[0])
                and line.box[2] >= min(top.box[2], bottom.box[2])
                for line in components
            )
            if not separator:
                continue
            numerator = _meter_digit(gray, top.box)
            denominator = _meter_digit(gray, bottom.box)
            if numerator and denominator and numerator[0] != "0" and denominator[0] != "0":
                return TextSpan(
                    f"{numerator[0]}/{denominator[0]}",
                    (min(top.box[0], bottom.box[0]), top.box[1],
                     max(top.box[2], bottom.box[2]), bottom.box[3]),
                    min(numerator[1], denominator[1]),
                )
    return None


def _join(spans: list[TextSpan]) -> str:
    spans.sort(key=lambda span: span.box[0])
    result = ""
    previous: TextSpan | None = None
    for span in spans:
        gap = span.box[0] - previous.box[2] if previous is not None else 0
        if previous is not None and gap > min(previous.height, span.height) * 0.65:
            if result and result[-1].isascii() and span.text[0].isascii():
                result += " "
        result += span.text
        previous = span
    return result.strip()


def _text_rows(spans: list[TextSpan]) -> list[list[TextSpan]]:
    bands: list[list[TextSpan]] = []
    for span in sorted(spans, key=lambda value: value.center_y):
        if bands and abs(span.center_y - bands[-1][0].center_y) <= max(
            10, min(span.height, bands[-1][0].height) * 0.48
        ):
            bands[-1].append(span)
        else:
            bands.append([span])
    rows: list[list[TextSpan]] = []
    for band in bands:
        for span in sorted(band, key=lambda value: value.box[0]):
            if rows and rows[-1] and rows[-1][0] in band:
                previous = rows[-1][-1]
                if span.box[0] - previous.box[2] <= max(80, 3 * max(span.height, previous.height)):
                    rows[-1].append(span)
                    continue
            rows.append([span])
    return rows


def extract_headers(
    spans: tuple[TextSpan, ...], width: int, first_music_top: int
) -> HeaderResult:
    candidates = [
        span
        for span in spans
        if span.confidence >= 0.75
        and span.box[3] < first_music_top - 8
        and span.text.strip()
    ]
    used: set[TextSpan] = set()
    lines = ["V: 1.0"]

    key = next((span for span in candidates if _KEY.search(span.text)), None)
    if key is not None:
        match = _KEY.search(key.text)
        assert match is not None
        accidental = (match.group(1) or match.group(3)).replace("♯", "#").replace(
            "♭", "$"
        ).replace("b", "$")
        lines.append(f"D: {match.group(2).upper()}{accidental}")
        used.add(key)

    meter = next((span for span in candidates if _METER.search(span.text)), None)
    if meter is not None:
        match = _METER.search(meter.text)
        assert match is not None
        lines.append(f"P: {match.group(1)}/{match.group(2)}")
        used.add(meter)
    elif key is not None:
        digits = [
            span for span in candidates
            if span.text.isdecimal()
            and key.box[2] - 5 <= span.center_x <= key.box[2] + key.height * 1.7
            and abs(span.center_y - key.center_y) <= key.height * 1.2
        ]
        if len(digits) == 2 and digits[0].center_y != digits[1].center_y:
            top, bottom = sorted(digits, key=lambda span: span.center_y)
            lines.append(f"P: {top.text}/{bottom.text}")
            used.update(digits)

    tempo = next((span for span in candidates if _TEMPO.fullmatch(span.text.strip())), None)
    if tempo is not None:
        match = _TEMPO.fullmatch(tempo.text.strip())
        assert match is not None
        lines.append(f"J: {match.group(1)}")
        used.add(tempo)

    number = next((span for span in candidates if _NUMBER.fullmatch(span.text.strip())), None)
    if number is not None:
        match = _NUMBER.fullmatch(number.text.strip())
        assert match is not None
        lines.append(f"X: {match.group(1)}")
        used.add(number)

    remaining = [span for span in candidates if span not in used]
    for row in _text_rows(remaining):
        text = _join(row)
        if not any(character.isalpha() for character in text):
            continue
        center = sum(span.center_x for span in row) / len(row)
        if center >= width * 0.72:
            suffix = next((end for end in ("词曲", "词", "曲") if text.endswith(end)), "")
            credit = f"{text[:-len(suffix)].strip()} {suffix}" if suffix else text
            lines.append(f"Z: {credit}")
            used.update(row)
        elif width * 0.3 <= center <= width * 0.7 and not _KEY.search(text):
            lines.append(f"B: {text}")
            used.update(row)
        elif center <= width * 0.3 and text and not text[0].isdigit() and tempo is None:
            lines.append(f"J: {text}")
            used.update(row)

    # Head fields precede music in the spec; keep repeated B/Z in visible vertical order.
    rank = {"V": 0, "B": 1, "Z": 2, "D": 3, "P": 4, "J": 5, "X": 6}
    lines.sort(key=lambda line: rank[line[0]])
    missing = tuple(field for field in ("B", "D", "P") if not any(
        line.startswith(f"{field}:") for line in lines
    ))
    regions = tuple(span.box for span in candidates)
    return HeaderResult(tuple(lines), missing, regions)
