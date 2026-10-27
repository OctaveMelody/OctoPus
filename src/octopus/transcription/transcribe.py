"""Orchestrate image/PDF transcription and its final review stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import compilation, page_text, pdf_source
from .image import recognize_image
from .observations import PageObservation
from .results import Draft, Issue, RowBinding
from .review import note_confidence_findings, render_back_findings
from .text import image_text

MAX_PDF_BYTES = pdf_source.MAX_PDF_BYTES
MAX_PDF_PAGES = pdf_source.MAX_PDF_PAGES
MAX_PDF_RASTER_PIXELS = pdf_source.MAX_PDF_RASTER_PIXELS
_pdf_pages = pdf_source._pdf_pages
_pdf_raster_options = pdf_source._pdf_raster_options
_bar_marks = compilation._bar_marks
_row_marks = compilation._row_marks
_row_tokens = compilation._row_tokens
_synchronized_head_bar_rows = compilation._synchronized_head_bar_rows


def _review_assembled(
    draft: Draft, bindings: tuple[RowBinding, ...],
) -> Draft:
    """Append review-only findings after notation and row bindings are complete."""
    findings = (
        *note_confidence_findings(draft.jps, draft.pages, bindings),
        *render_back_findings(draft.jps, draft.pages, bindings),
    )
    issues = (*draft.issues, *(Issue(
        item.code, item.page, item.detail, item.regions, item.confidence,
        item.source_start, item.source_end,
    ) for item in findings))
    return replace(draft, issues=issues)


def _draft_from_pages(pages: tuple[PageObservation, ...]) -> Draft:
    """Assemble notation first, then run the read-only final review pass."""
    assembled, bindings = compilation.assemble(pages)
    return _review_assembled(assembled, bindings)


def _compile(pages: tuple[PageObservation, ...]) -> Draft:
    """Compatibility entry point returning an assembled and reviewed draft."""
    return _draft_from_pages(pages)


def transcribe(
    path: Path, *, progress: Callable[[int, int, str], None] | None = None,
) -> Draft:
    """Use only the supplied image/PDF, never a paired source or reference file."""
    return _transcribe(path, progress=progress)


def _transcribe(
    path: Path, *, progress: Callable[[int, int, str], None] | None = None,
) -> Draft:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        if progress:
            progress(0, 1, "recognizing")
        observation = recognize_image(path)
        text_spans = image_text(path)
        original_spans = text_spans or ()
        page = replace(
            observation,
            text_spans=text_spans or (),
            text_source="ocr" if text_spans is not None else "unavailable",
        )

        def text_ready() -> None:
            if progress:
                progress(1, 1, "compiling")

        enriched = page_text.enrich_page_text(
            path,
            page,
            original_spans,
            first_page=True,
            on_text_ready=text_ready,
        )
        return _draft_from_pages((enriched,))
    if suffix == ".pdf":
        pages = _pdf_pages(path, progress)
        if progress:
            progress(len(pages), len(pages), "compiling")
        return _draft_from_pages(pages)
    raise ValueError("transcription input must be PNG, JPG, JPEG or PDF")
