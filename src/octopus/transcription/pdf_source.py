"""Admit PDF sources and create enriched page observations."""

from __future__ import annotations

import math
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import page_text
from .image import recognize_image
from .observations import PageObservation
from .text import image_text, merge_text, pdf_text, scale_pdf_text

MAX_PDF_BYTES = 100_000_000
MAX_PDF_PAGES = 200
MAX_PDF_RASTER_PIXELS = 7_000_000


def _pdf_raster_options(width: float, height: float) -> list[str]:
    """Bound rounded raster dimensions, including pages too large for one DPI."""
    longest, shortest = max(width, height), min(width, height)
    aspect = shortest / longest
    side_limit = (
        MAX_PDF_RASTER_PIXELS if aspect <= 1 / MAX_PDF_RASTER_PIXELS
        else math.floor(math.sqrt(MAX_PDF_RASTER_PIXELS / aspect))
    )
    # Rounding a very short side up to one or more pixels can exceed the area budget.
    side_limit = min(side_limit, MAX_PDF_RASTER_PIXELS // max(1, math.ceil(side_limit * aspect)))
    dpi = (
        203 if longest <= side_limit * 72 / 203
        else max(1, math.floor(side_limit * 72 / longest))
    )
    options = ["-r", str(dpi)]
    if longest > side_limit * 72 / dpi:
        # Poppler's explicit output cap takes precedence over the one-DPI minimum.
        options.extend(("-scale-to", str(side_limit)))
    return options


def _pdf_pages(
    path: Path, progress: Callable[[int, int, str], None] | None = None,
) -> tuple[PageObservation, ...]:
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 100 MB input limit")
    metadata = subprocess.run(
        ["pdfinfo", "-f", "1", "-l", str(MAX_PDF_PAGES), "-box", str(path)],
        capture_output=True, text=True, timeout=30, check=True
    ).stdout
    count = next(
        (int(line.split(":", 1)[1]) for line in metadata.splitlines() if line.startswith("Pages:")),
        0,
    )
    if not 1 <= count <= MAX_PDF_PAGES:
        raise ValueError("PDF must have between 1 and 200 pages")
    try:
        page_sizes = {
            int(number): (float(width), float(height))
            for number, width, height in re.findall(
                r"^Page\s+(\d+)\s+size:\s+(\S+) x (\S+) pts", metadata, re.MULTILINE,
            )
        }
        media_sizes = {
            int(number): (float(right) - float(left), float(bottom) - float(top))
            for number, left, top, right, bottom in re.findall(
                r"^Page\s+(\d+)\s+MediaBox:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
                metadata, re.MULTILINE,
            )
        }
    except ValueError as exc:
        raise ValueError("PDF has invalid page dimensions") from exc
    expected_pages = set(range(1, count + 1))
    if set(page_sizes) != expected_pages or set(media_sizes) != expected_pages or any(
        not math.isfinite(value) or value <= 0
        for size in (*page_sizes.values(), *media_sizes.values()) for value in size
    ):
        raise ValueError("PDF has missing or invalid page dimensions")
    if progress:
        progress(0, count, "recognizing")
    observations = []
    native_text = pdf_text(path)
    with tempfile.TemporaryDirectory(prefix="jianpu-transcribe-") as temporary:
        raster = Path(temporary) / "page"
        for page_number in range(1, count + 1):
            subprocess.run(
                [
                    "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                    # Page size describes CropBox; both raster and native text use MediaBox.
                    "-singlefile", *_pdf_raster_options(*media_sizes[page_number]),
                    "-png", str(path), str(raster),
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
            image_path = raster.with_suffix(".png")
            observation = recognize_image(image_path)
            words = native_text[page_number - 1] if page_number <= len(native_text) else ()
            native_spans = scale_pdf_text(words, observation.width, observation.height)
            ocr_spans = image_text(image_path)
            merged_text = merge_text(native_spans, ocr_spans or ())
            text_spans = merged_text.spans
            original_spans = text_spans
            text_source = (
                "pdf_text+ocr" if native_spans and ocr_spans is not None
                else "pdf_text" if native_spans else "ocr" if ocr_spans is not None
                else "unavailable"
            )
            page_observation = replace(
                observation,
                text_spans=text_spans,
                text_source=text_source,
                native_text_spans=merged_text.native_spans,
                ocr_text_spans=ocr_spans,
                text_merge_conflicts=merged_text.conflicts,
            )
            observations.append(page_text.enrich_page_text(
                image_path,
                page_observation,
                original_spans,
                first_page=page_number == 1,
            ))
            image_path.unlink()
            if progress:
                progress(page_number, count, "recognizing")
    return tuple(observations)
