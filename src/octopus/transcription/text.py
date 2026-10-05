"""Printed text evidence from local raster OCR or a PDF's own text layer."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

from PIL import Image, ImageOps

from .components import Box, Component, connected_components
from .marks import vertical_bend
from .session_artifacts import track_session_artifact

_XHTML = "{http://www.w3.org/1999/xhtml}"


@dataclass(frozen=True, slots=True)
class TextSpan:
    text: str
    box: Box
    confidence: float
    character_centers: tuple[float, ...] = ()
    lyric_baselines: tuple[float, ...] = ()

    @property
    def center_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


@lru_cache(maxsize=1)
def _cached_ocr_engine() -> object | None:
    try:
        from rapidocr import RapidOCR
    except ImportError:
        return None
    with track_session_artifact():
        return cast(object, RapidOCR(params={
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Global.log_level": "critical",
        }))


def _ocr_engine() -> object | None:
    return _cached_ocr_engine()


def _ocr_call(engine: object, image: Any, **options: Any) -> tuple[list[Any], Any]:
    """Normalize RapidOCR's structured result to the pipeline's row tuples."""
    options.setdefault("use_det", bool(options.get("return_word_box")))
    options.setdefault("use_cls", True)
    options.setdefault("use_rec", True)
    options.setdefault("return_word_box", False)
    options.setdefault("return_single_char_box", False)
    result = engine(image, **options)  # type: ignore[operator]
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if texts is None or scores is None:
        return [], getattr(result, "elapse", None)
    if len(texts) != len(scores):
        raise ValueError("RapidOCR returned mismatched text and confidence counts")
    boxes = getattr(result, "boxes", None)
    word_results = getattr(result, "word_results", ())
    if boxes is None and options.get("return_word_box"):
        # Recognition without detector geometry cannot be anchored safely to a page row.
        return [], getattr(result, "elapse", None)
    if boxes is not None and len(boxes) != len(texts):
        raise ValueError("RapidOCR returned mismatched text and box counts")
    if word_results is None:
        word_results = ()
    rows: list[Any] = []
    for index, (value, confidence) in enumerate(zip(texts, scores, strict=True)):
        text_value, score = str(value), float(confidence)
        if boxes is None:
            rows.append((text_value, score))
            continue
        polygon = boxes[index]
        if hasattr(polygon, "tolist"):
            polygon = polygon.tolist()
        row: tuple[Any, ...] = (polygon, text_value, score)
        char_line = word_results[index] if index < len(word_results) else ()
        char_items = [item for item in char_line if isinstance(item, (tuple, list))
                      and len(item) == 3 and item[2] is not None]
        if char_items:
            char_boxes = [item[2].tolist() if hasattr(item[2], "tolist") else item[2]
                          for item in char_items]
            row += (char_boxes, [str(item[0]) for item in char_items],
                    [float(item[1]) for item in char_items])
        rows.append(row)
    return rows, getattr(result, "elapse", None)


def _character_centers(
    text: str, details: list[object], scale: float = 1.0, offset: float = 0.0,
) -> tuple[float, ...]:
    """Use the recognizer's character positions rather than evenly splitting a text line."""
    if len(details) < 2:
        return ()
    boxes = cast(list[list[list[float]]], details[0])
    characters = "".join(cast(list[str], details[1]))
    if characters.strip() != text or len(boxes) != len(characters):
        return ()
    start = len(characters) - len(characters.lstrip())
    return tuple(sum(point[0] for point in box) / len(box) * scale + offset
                 for box in boxes[start:start + len(text)])


def image_text(path: Path) -> tuple[TextSpan, ...] | None:
    """Return None only when the optional OCR dependency is unavailable."""
    engine = _ocr_engine()
    if engine is None:
        return None
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source).convert("RGBA")
    white = Image.new("RGBA", oriented.size, "white")
    white.alpha_composite(oriented)
    rgb = white.convert("RGB")
    result, _ = _ocr_call(engine, rgb, return_word_box=True, return_single_char_box=True)
    spans = []
    for corners, text, confidence, *details in result or []:
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        box = (round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys)))
        word, score = str(text), float(confidence)
        if len(word) == 1 and "\u3400" <= word <= "\u9fff" and 0.72 <= score < 0.9:
            crop = ImageOps.expand(rgb.crop(box), border=round((box[3] - box[1]) / 2),
                                   fill="white")
            refined, _ = _ocr_call(engine, crop, use_det=False, use_cls=False)
            if refined:
                candidate, confidence = str(refined[0][0]).strip(), float(refined[0][1])
                if len(candidate) == 1 and "\u3400" <= candidate <= "\u9fff" and confidence >= 0.95:
                    word, score = candidate, confidence
        spans.append(
            TextSpan(
                word, box, score, _character_centers(word, details),
            )
        )
    return tuple(spans)


def image_annotation_text(path: Path, rows: tuple[Box, ...]) -> tuple[TextSpan, ...] | None:
    """Read small above-note words in local crops without whole-page OCR downscaling.

    These are candidates only. The decoration recognizer must corroborate vocabulary,
    confidence and note/row ownership before any candidate becomes JPS notation.
    """
    engine = _ocr_engine()
    if engine is None:
        return None
    with Image.open(path) as source:
        rgba = ImageOps.exif_transpose(source).convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    white.alpha_composite(rgba)
    rgb = white.convert("RGB")
    gray = rgb.convert("L")
    spans: list[TextSpan] = []
    seen: set[Box] = set()
    for row in rows:
        height = row[3] - row[1]
        top = max(0, round(row[1] - height * 2.3))
        bottom = max(top, round(row[1] - height * 0.15))
        if bottom <= top:
            continue
        left = max(0, round(row[0] - height * 1.4))
        right = min(rgb.width, round(row[2] + height))
        components = sorted(connected_components(gray.crop((left, top, right, bottom))),
                            key=lambda item: item.box[0])
        groups: list[list[Component]] = []
        for component in components:
            if component.height < max(3, height * 0.24) or component.height > height * 1.4:
                continue
            # Slurs/hairpins can touch the word's crop margin. Their long slender
            # ink must not merge with an adjacent mf/ff into an unreadable text crop.
            if (component.width >= height * 3.5
                    and component.height <= height * 0.9
                    and component.area <= component.width * max(4, height * 0.25)):
                continue
            if groups and component.box[0] - max(item.box[2] for item in groups[-1]) < height * 0.6:
                groups[-1].append(component)
            else:
                groups.append([component])
        for group in groups:
            box = (left + min(item.box[0] for item in group),
                   top + min(item.box[1] for item in group),
                   left + max(item.box[2] for item in group),
                   top + max(item.box[3] for item in group))
            center_y = (box[1] + box[3]) / 2
            if (box in seen or box[2] - box[0] > height * 12 or any(
                other != row and other[1] <= center_y <= other[3] + height * 1.25
                and box[2] > other[0] and box[0] < other[2] for other in rows
            )):
                continue
            seen.add(box)
            padding = max(3, round(height * 0.2))
            crop = ImageOps.expand(rgb.crop(box), border=padding, fill="white")
            factor = max(1, min(4, round(40 / max(1, box[3] - box[1]))))
            crop = crop.resize((crop.width * factor, crop.height * factor),
                               Image.Resampling.LANCZOS)
            result, _ = _ocr_call(engine, crop, use_det=False, use_cls=False)
            for value, confidence, *_ in result or []:
                word = str(value).strip()
                if word:
                    spans.append(TextSpan(word, box, float(confidence)))
    return tuple(spans)


def image_lyric_text(
    path: Path, rows: tuple[Box, ...], *, small_page: bool,
) -> tuple[TextSpan, ...] | None:
    """Read separate lyric baselines when whole-page OCR merges them."""
    engine = _ocr_engine()
    if engine is None:
        return None
    import numpy as np

    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source).convert("RGBA")
    white = Image.new("RGBA", oriented.size, "white")
    white.alpha_composite(oriented)
    rgb = white.convert("RGB")
    dark = np.asarray(rgb.convert("L")) < 170
    gray = rgb.convert("L")
    width, height = rgb.size
    margin = max(2, round(width * 0.02))
    spans: list[TextSpan] = []
    for index, row in enumerate(rows):
        note_height = row[3] - row[1]
        top = row[3] + max(4, round(note_height * 0.4))
        bottom = (rows[index + 1][1] if index + 1 < len(rows) else height) - max(
            6, round(note_height * 0.45)
        )
        if not small_page:
            bottom = min(bottom, row[3] + round(note_height * 4.6))
        if bottom <= top:
            continue
        ink = dark[top:bottom, margin:width - margin].sum(axis=1)
        # A spanning brace must not join two text baselines in a large printed scan.
        active = ink >= max(8, round(width * 0.012),
                            ink.max(initial=0) * 0.12 if not small_page else 0)
        starts = np.flatnonzero(active & ~np.r_[False, active[:-1]])
        ends = np.flatnonzero(active & ~np.r_[active[1:], False]) + 1
        baseline_ranges = [(top + int(start), top + int(end))
                           for start, end in zip(starts, ends, strict=True)
                           if end - start >= max(8, round(note_height * 0.55))]
        row_start = len(spans)
        for start, end in zip(starts, ends, strict=True):
            if end - start < max(8, round(note_height * 0.55)):
                continue
            padding = 2 if small_page else max(2, round(note_height * 0.1))
            crop_top = max(0, top + int(start) - padding)
            crop_bottom = min(height, top + int(end) + padding)
            crop = rgb.crop((margin, crop_top, width - margin, crop_bottom))
            factor = 2 if small_page else 1
            crop = crop.resize((crop.width * factor, crop.height * factor),
                               Image.Resampling.LANCZOS)
            result, _ = _ocr_call(
                engine, np.asarray(crop), return_word_box=True, return_single_char_box=True,
            )
            band_start = len(spans)
            for corners, value, confidence, *details in sorted(
                result or [], key=lambda item: min(point[0] for point in item[0])
            ):
                word = str(value).strip()
                xs = [point[0] / factor + margin for point in corners]
                ys = [point[1] / factor + crop_top for point in corners]
                box = (round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys)))
                centers = _character_centers(word, details, 1 / factor, margin)
                overlap_trimmed = False
                if (not small_page and len(spans) > band_start
                        and centers and spans[-1].character_centers
                        and "\u3400" <= word[0] <= "\u9fff"
                        and box[0] < spans[-1].box[2]
                        and 0 <= centers[0] - spans[-1].character_centers[-1]
                        < note_height * 0.8):
                    # Overlapping detections can read the previous glyph's tail twice.
                    word, centers = word[1:], centers[1:]
                    overlap_trimmed = True
                    if not word:
                        continue
                glyphs: list[tuple[int, int]] = []
                if any("\u3400" <= character <= "\u9fff" for character in word):
                    columns = dark[box[1]:box[3], box[0]:box[2]].any(axis=0)
                    starts = np.flatnonzero(columns & ~np.r_[False, columns[:-1]])
                    ends = np.flatnonzero(columns & ~np.r_[columns[1:], False]) + 1
                    for left, right in zip(starts, ends, strict=True):
                        if glyphs and (
                            left - glyphs[-1][1] <= 2
                            and right - glyphs[-1][0] <= (box[3] - box[1]) * 1.2
                        ):
                            glyphs[-1] = (glyphs[-1][0], int(right))
                        else:
                            glyphs.append((int(left), int(right)))
                    glyphs = [
                        pair for pair in glyphs
                        if pair[1] - pair[0] >= (box[3] - box[1]) * 0.4
                    ]
                    if (
                        not overlap_trimmed and len(word) > 1
                        and len(spans) > band_start
                        and len(glyphs) == len(word) - 1
                        and len(starts) > 0
                        and box[0] < spans[-1].box[2]
                        and ends[0] - starts[0] < (box[3] - box[1]) * 0.4
                        and box[0] + ends[0] <= spans[-1].box[2] + 2
                    ):
                        word = word[1:]
                centers = (
                    tuple(box[0] + (left + right) / 2 for left, right in glyphs)
                    if not overlap_trimmed and len(glyphs) == len(word) else centers
                )
                spans.append(TextSpan(
                    word,
                    box,
                    float(confidence),
                    centers,
                ))
        if not small_page and any(
            any("\u3400" <= char <= "\u9fff" for char in span.text)
            for span in spans[row_start:]
        ):
            components = [Component(
                (mark.box[0] + margin, mark.box[1] + top,
                 mark.box[2] + margin, mark.box[3] + top), mark.area,
            ) for mark in connected_components(gray.crop((margin, top, width - margin, bottom)))]
            for mark in components:
                if (note_height * 0.5 <= mark.width <= note_height * 1.5
                        and mark.height <= note_height * 0.2
                        and any(start <= mark.center_y <= end for start, end in baseline_ranges)
                        and not any(span.box[0] <= (mark.box[0] + mark.box[2]) / 2 <= span.box[2]
                                    for span in spans[row_start:])):
                    following = next((span for span in sorted(spans[row_start:],
                                                             key=lambda item: item.box[0])
                                      if 0 < span.box[0] - mark.box[2] <= note_height
                                      and abs(span.center_y - mark.center_y) <= note_height * 0.5
                                      and "\u3400" <= span.text[0] <= "\u9fff"), None)
                    if following is not None:
                        crop = rgb.crop((mark.box[0], following.box[1],
                                         following.box[2], following.box[3]))
                        crop = ImageOps.expand(crop, border=round(note_height * 0.15), fill="white")
                        result, _ = _ocr_call(engine, np.asarray(crop), use_det=False,
                                              use_cls=False)
                        if (result
                                and str(result[0][0]).strip().startswith("一" + following.text[0])
                                and float(result[0][1]) >= 0.95):
                            spans.append(TextSpan("一", mark.box, float(result[0][1])))
            shared = _shared_lyric_text(gray, components, baseline_ranges, note_height)
            for span in shared:
                spans[row_start:] = [old for old in spans[row_start:]
                                     if old.center_x < span.box[0]]
                spans.append(span)
    return tuple(spans)


def _shared_lyric_text(
    gray: Image.Image, components: list[Component], bands: list[tuple[int, int]],
    height: int,
) -> tuple[TextSpan, ...]:
    """A closing brace explicitly shares its right-hand syllable between two verses."""
    if len(bands) != 2:
        return ()
    stems = [mark for mark in components if height * 0.8 <= mark.height <= height * 1.5
             and mark.width <= height * 0.5]
    for upper in stems:
        for lower in stems:
            if not (0 <= lower.box[1] - upper.box[3] <= max(3, height * 0.1)
                    and abs(upper.box[0] - lower.box[0]) <= height * 0.1):
                continue
            brace = Component((min(upper.box[0], lower.box[0]), upper.box[1],
                               max(upper.box[2], lower.box[2]), lower.box[3]),
                              upper.area + lower.area)
            bend = vertical_bend(brace, gray)
            if (bend is None or abs(bend) < max(1.25, brace.width * 0.15)
                    or abs(brace.box[1] - bands[0][0]) > height * 0.5
                    or abs(brace.box[3] - bands[1][1]) > height * 0.5):
                continue
            left = brace.box[2] + 2
            top = max(0, round(brace.center_y - height * 0.75))
            crop = gray.crop((left, top, left + round(height * 1.8),
                              round(brace.center_y + height * 0.75)))
            ink_box = crop.point(lambda value: 255 if value < 160 else 0).getbbox()
            if ink_box is None:
                continue
            box = (left + ink_box[0], top + ink_box[1], left + ink_box[2], top + ink_box[3])
            reading = image_digit(gray, box, "".join(map(chr, range(0x3400, 0xA000))))
            if reading is not None and reading[1] >= 0.95:
                return (TextSpan(reading[0], box, reading[1], (),
                                 tuple((start + end) / 2 for start, end in bands)),)
    return ()


def image_digit(
    gray: Image.Image, box: Box, allowed_digits: str = "01234567",
    *, tight_padding: bool = False,
) -> tuple[str, float] | None:
    """Read an isolated printed digit without relying on a particular glyph asset."""
    engine = _ocr_engine()
    if engine is None:
        return None
    import numpy as np

    crop = gray.crop(box).convert("RGB")
    if tight_padding:
        padded = ImageOps.expand(crop, border=round(crop.height * 0.2), fill="white")
    else:
        side = round(max(crop.size) * 1.4)
        padded = Image.new("RGB", (side, side), "white")
        padded.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    result, _ = _ocr_call(engine, np.asarray(padded), use_det=False, use_cls=False)
    if not result:
        return None
    digit, confidence = str(result[0][0]).strip(), float(result[0][1])
    if len(digit) == 1 and digit in allowed_digits and confidence >= (
        0.50 if digit == "0" else 0.90
    ):
        return digit, confidence
    return None


def music_characters(gray: Image.Image, box: Box) -> tuple[tuple[str, float, float], ...]:
    """Read row characters with their own confidence and source-space horizontal center."""
    engine = _ocr_engine()
    if engine is None:
        return ()
    import numpy as np

    crop = gray.crop(box)
    found: list[tuple[str, float, float]] = []
    # Context padding changes CTC segmentation; corroborate each reading against glyph ink.
    for ratio in (0.2, 0.3):
        border = max(2, round(crop.height * ratio))
        padded = ImageOps.expand(crop, border=border, fill="white")
        padded = padded.resize((padded.width * 2, padded.height * 2), Image.Resampling.LANCZOS)
        result, _ = _ocr_call(
            engine, np.asarray(padded.convert("RGB")), use_cls=False, return_word_box=True,
            return_single_char_box=True,
        )
        for _, value, _, *details in result or []:
            word = str(value).strip()
            if len(details) < 3 or any(char not in "01234567 .()-|" for char in word):
                continue
            centers = _character_centers(word, details, 0.5, box[0] - border)
            letters = "".join(cast(list[str], details[1]))
            start = len(letters) - len(letters.lstrip())
            scores = cast(list[float], details[2])[start:start + len(word)]
            if len(centers) == len(scores) == len(word):
                found.extend((char, float(score), center)
                             for char, score, center in zip(word, scores, centers, strict=True)
                             if char in "01234567" and score >= (0.5 if char == "0" else 0.9))
    return tuple(sorted(found, key=lambda item: item[2]))


def pdf_text(path: Path) -> tuple[tuple[TextSpan, ...], ...]:
    """Read selectable PDF words; scanned pages simply return empty lists."""
    result = subprocess.run(
        ["pdftotext", "-bbox-layout", str(path), "-"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    root = ElementTree.fromstring(result.stdout)
    pages = []
    for page in root.iter(f"{_XHTML}page"):
        width = float(page.attrib["width"])
        height = float(page.attrib["height"])
        spans = []
        for word in page.iter(f"{_XHTML}word"):
            value = "".join(word.itertext()).strip()
            if not value:
                continue
            left, top, right, bottom = (
                float(word.attrib[key])
                for key in ("xMin", "yMin", "xMax", "yMax")
            )
            # Normalized fractions are mapped to the raster page once its size is known.
            spans.append(
                TextSpan(
                    value,
                    (
                        round(left / width * 1_000_000),
                        round(top / height * 1_000_000),
                        round(right / width * 1_000_000),
                        round(bottom / height * 1_000_000),
                    ),
                    1.0,
                )
            )
        pages.append(tuple(spans))
    return tuple(pages)


def scale_pdf_text(spans: tuple[TextSpan, ...], width: int, height: int) -> tuple[TextSpan, ...]:
    return tuple(
        TextSpan(
            span.text,
            (
                round(span.box[0] * width / 1_000_000),
                round(span.box[1] * height / 1_000_000),
                round(span.box[2] * width / 1_000_000),
                round(span.box[3] * height / 1_000_000),
            ),
            span.confidence,
        )
        for span in spans
    )


def merge_text(
    native: tuple[TextSpan, ...], ocr: tuple[TextSpan, ...]
) -> tuple[TextSpan, ...]:
    """Keep native words where they cover OCR boxes; add raster-only marks."""
    merged = list(native)
    for candidate in ocr:
        left, top, right, bottom = candidate.box
        area = max(1, (right - left) * (bottom - top))
        covered = sum(
            max(0, min(right, word.box[2]) - max(left, word.box[0]))
            * max(0, min(bottom, word.box[3]) - max(top, word.box[1]))
            for word in native
        )
        if covered < area * 0.25:
            merged.append(candidate)
    return tuple(merged)
