"""Enrich page text and assign recovered performance text to score owners."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median

from . import text
from .components import Box
from .decorations import decoration_token, text_decorations
from .headers import extract_headers, printed_key_span, stacked_meter_span
from .image import MusicRow, PageObservation, _read_page
from .text import (
    TextMergeResult,
    TextSpan,
    image_annotation_text,
    image_lyric_text,
    merge_text,
)


@dataclass(frozen=True, slots=True)
class _LyricRecovery:
    """Page text and localized lyric crops selected for one recovery attempt."""

    text_spans: tuple[TextSpan, ...]
    note_height: float | None
    lyrics: tuple[TextSpan, ...] | None


def _header_spans(
    path: Path, page: PageObservation, spans: tuple[TextSpan, ...]
) -> tuple[TextSpan, ...]:
    if not page.rows:
        return spans
    key = printed_key_span(path, page.rows[0].box[1], page.excluded_regions)
    if key is not None:
        # Whole-page OCR can omit a raised accidental while accepting the key letter.
        spans = (key, *(span for span in spans if "D" in extract_headers(
            (span,), page.width, page.rows[0].box[1],
        ).missing))
    if "P" not in extract_headers(spans, page.width, page.rows[0].box[1]).missing:
        return spans
    meter = stacked_meter_span(path, spans, page.rows[0].box[1])
    if meter is None:
        return spans
    # Remove a merged fraction digit so it cannot become part of a nearby subtitle.
    spans = tuple(span for span in spans if not (
        span.text.isdecimal() and meter.box[0] <= span.center_x <= meter.box[2]
        and meter.box[1] <= span.center_y <= meter.box[3]
    ))
    return (*spans, meter)


def _lyric_baseline_text(
    path: Path, page: PageObservation, spans: tuple[TextSpan, ...]
) -> tuple[TextSpan, ...]:
    recovery = _lyric_recovery(path, page, spans)
    spans, note_height, lyrics = (
        recovery.text_spans, recovery.note_height, recovery.lyrics,
    )
    if not lyrics or note_height is None:
        return spans
    if page.voice_groups:
        # Crops can also contain the next voice's digits or performance marks.
        # Replace only corroborated lyric baselines, retaining all other text.
        def same_baseline(first: TextSpan, second: TextSpan) -> bool:
            return (abs(first.center_y - second.center_y)
                    <= max(9, min(first.height, second.height) * 0.42)
                    or first.height >= note_height * 1.8
                    and first.box[2] - first.box[0] < first.height
                    and sum("\u3400" <= char <= "\u9fff" for char in first.text) >= 2)

        def chinese_centers(span: TextSpan) -> tuple[float, ...]:
            return tuple(
                span.character_centers[index] if len(span.character_centers) == len(span.text)
                else span.box[0] + (span.box[2] - span.box[0]) * (index + 0.5) / len(span.text)
                for index, char in enumerate(span.text) if "\u3400" <= char <= "\u9fff"
            )

        retained: set[TextSpan] = set()
        for span in spans:
            if (span.confidence < 0.9 or len(span.character_centers) != len(span.text)
                    or span.height >= note_height * 1.8
                    and span.box[2] - span.box[0] < span.height
                    and sum("\u3400" <= char <= "\u9fff" for char in span.text) >= 2):
                continue
            original_centers = chinese_centers(span)
            recovered_centers = tuple(x for lyric in lyrics if same_baseline(span, lyric)
                                      for x in chinese_centers(lyric))
            if any(not any(abs(x - y) <= note_height for y in recovered_centers)
                   for x in original_centers):
                # A crop can omit a previously confident isolated glyph. Retain it;
                # conflicting partial readings fall back to the original span too.
                retained.add(span)
                lyrics = tuple(lyric for lyric in lyrics if not (
                    same_baseline(span, lyric) and any(
                        abs(x - y) <= note_height
                        for x in original_centers for y in chinese_centers(lyric)
                    )
                ))
        return (
            *(span for span in spans if span in retained or not any(
                span.box[1] < lyric.box[3] and span.box[3] > lyric.box[1]
                and span.box[0] < lyric.box[2] and span.box[2] > lyric.box[0]
                and same_baseline(span, lyric)
                and any("\u3400" <= char <= "\u9fff" for char in span.text)
                for lyric in lyrics
            )),
            *lyrics,
        )
    return (
        *(span for span in spans if span.box[3] < page.rows[0].box[1]),
        *lyrics,
    )


def _lyric_recovery(
    path: Path, page: PageObservation, spans: tuple[TextSpan, ...],
) -> _LyricRecovery:
    if not page.rows:
        return _LyricRecovery(spans, None, None)
    bz_duplicates = _bz_duplicate_text_spans(page, spans)
    spans = tuple(span for span in spans if span not in bz_duplicates)
    note_height = median(note.box[3] - note.box[1] for row in page.rows for note in row.notes)
    merged_lyrics = any(
        span.height >= note_height * 1.8
        and span.box[2] - span.box[0] < span.height
        and sum("\u3400" <= char <= "\u9fff" for char in span.text) >= 2
        and any(row.box[3] < span.center_y < row.box[3] + note_height * 4.6
                for row in page.rows)
        for span in spans
    )
    if (page.dsb_overlays or page.unresolved_braces
            or page.bz_overlays and not page.voice_groups):
        return _LyricRecovery(spans, note_height, None)
    if page.voice_groups and not any(
        any("\u3400" <= char <= "\u9fff" for char in span.text)
        and span.center_y > page.rows[0].box[3] for span in spans
    ):
        return _LyricRecovery(spans, note_height, None)
    if note_height >= 16:
        # Large merged lyric rows need crops only when whole-page OCR exceeds its safe size.
        ocr_limit = getattr(text._ocr_engine(), "max_side_len", 2000)
        if not merged_lyrics or max(page.width, page.height) <= ocr_limit:
            return _LyricRecovery(spans, note_height, None)
    lyrics = image_lyric_text(
        path, tuple(row.box for row in page.rows), small_page=note_height < 16,
        recover_sparse=bool(page.voice_groups),
    )
    if not lyrics:
        return _LyricRecovery(spans, note_height, None)
    lyric_duplicates = _bz_duplicate_text_spans(page, lyrics)
    lyrics = tuple(span for span in lyrics if span not in lyric_duplicates)
    if page.voice_groups:
        # Crops can also contain the next voice's digits or performance marks.
        # Replace only corroborated lyric baselines, retaining all other text.
        lyrics = tuple(span for span in lyrics if span.confidence >= 0.72
                       and any("\u3400" <= char <= "\u9fff" for char in span.text)
                       and all("\u3400" <= char <= "\u9fff" or char.isspace()
                               or char in "，。！？、,.!?；;：:" for char in span.text))
    return _LyricRecovery(spans, note_height, lyrics)


def _boxes_intersect(first: Box, second: Box) -> bool:
    return (first[0] < second[2] and second[0] < first[2]
            and first[1] < second[3] and second[1] < first[3])


def _reading_recovered(span: TextSpan, lyrics: tuple[TextSpan, ...]) -> bool:
    """Whether ordered crop readings account for every character in a page OCR span."""
    source = text._text_key(span.text)
    recovered = "".join(
        text._text_key(lyric.text)
        for lyric in sorted(lyrics, key=lambda lyric: (lyric.box[1], lyric.box[0]))
    )
    if not source or not recovered:
        return False
    recovered_chars = iter(recovered)
    return all(any(candidate == character for candidate in recovered_chars)
               for character in source)


def _pdf_lyric_baseline_text(
    path: Path, page: PageObservation, spans: tuple[TextSpan, ...],
) -> TextMergeResult:
    """Replace page OCR only in crop-owned lyric regions, retaining native text."""
    recovery = _lyric_recovery(path, page, spans)
    native = page.native_text_spans or ()
    original_ocr = page.ocr_text_spans or ()
    if not recovery.lyrics:
        return TextMergeResult(
            spans if native else recovery.text_spans,
            page.text_merge_conflicts,
            native,
            original_ocr,
        )

    lyrics = recovery.lyrics
    page_ocr = tuple(
        span for span in original_ocr
        if not (
            any(_boxes_intersect(span.box, lyric.box) for lyric in lyrics)
            and _reading_recovered(span, lyrics)
        )
    )
    inputs = (*native, *page_ocr, *lyrics)
    bz_duplicates = set(_bz_duplicate_text_spans(page, inputs))
    native = tuple(span for span in native if span not in bz_duplicates)
    page_ocr = tuple(span for span in page_ocr if span not in bz_duplicates)
    lyrics = tuple(span for span in lyrics if span not in bz_duplicates)

    resolved = merge_text(native, (*page_ocr, *lyrics))
    existing_conflicts = tuple(
        conflict for conflict in page.text_merge_conflicts
        if not (
            any(_boxes_intersect(conflict.box, lyric.box) for lyric in recovery.lyrics)
            and _reading_recovered(conflict.ocr_span, recovery.lyrics)
        )
    )
    return TextMergeResult(
        resolved.spans,
        tuple(dict.fromkeys((*existing_conflicts, *resolved.conflicts))),
        page.native_text_spans or (),
        page.ocr_text_spans or (),
    )


def _performance_text(
    path: Path, page: PageObservation, original: tuple[TextSpan, ...],
) -> PageObservation:
    """Preserve instructions omitted by whole-page or lyric-focused OCR."""
    if not page.rows:
        return page
    gray = _read_page(path)
    all_rows = (*page.rows, *(bz.row for bz in page.bz_overlays))
    cropped = image_annotation_text(path, tuple(row.box for row in all_rows)) or ()
    candidates = tuple(dict.fromkeys((*page.text_spans, *original, *cropped)))
    bz_duplicates = _bz_duplicate_text_spans(page, candidates)
    duplicate_boxes = tuple(span.box for span in bz_duplicates)
    candidates = tuple(span for span in candidates if (
        span not in bz_duplicates
        and not (decoration_token(span.text) is not None
                 and any(_box_coverage(span.box, box) >= 0.7 for box in duplicate_boxes))
    ))
    candidates = _score_text(replace(page, text_spans=candidates)).text_spans
    consumed: set[TextSpan] = set()

    def decorate(row: MusicRow) -> MusicRow:
        found = text_decorations(
            tuple(note.box for note in row.notes), candidates, gray=gray,
            other_rows=tuple(other.box for other in all_rows if other is not row),
        )
        notes = []
        for index, note in enumerate(row.notes):
            tokens = [item.token for item in found if item.note_index == index]
            notes.append(replace(
                note,
                decorations=tuple(dict.fromkeys((*note.decorations,
                                                 *(t for t in tokens if not t.startswith('"'))))),
                annotations=tuple(dict.fromkeys((*note.annotations,
                                                *(t for t in tokens if t.startswith('"'))))),
            ))
        consumed.update(span for item in found for span in item.source_spans)
        return replace(row, notes=tuple(notes), decoration_regions=(
            *row.decoration_regions, *(item.box for item in found),
        ))

    rows = tuple(decorate(row) for row in page.rows)
    overlays = tuple(replace(bz, row=decorate(bz.row)) for bz in page.bz_overlays)
    removed = consumed | set(bz_duplicates)
    return replace(page, rows=rows, bz_overlays=overlays, text_spans=tuple(
        span for span in page.text_spans if span not in removed
    ))


def _bz_duplicate_text_spans(
    page: PageObservation, spans: tuple[TextSpan, ...],
) -> tuple[TextSpan, ...]:
    """Exclude OCR text that repeats the recognized notes inside a BZ overlay."""
    duplicated: set[TextSpan] = set()
    ordered_spans = tuple(dict.fromkeys(spans))
    for overlay in page.bz_overlays:
        note_digits = "".join(note.digit for note in overlay.row.notes)
        if len(note_digits) < 4:
            continue
        left, top, right, bottom = overlay.row.box
        height = bottom - top
        center_y = (top + bottom) / 2
        local = [span for span in ordered_spans if (
            abs(span.center_y - center_y) <= height * 1.4
            and span.box[2] >= left - height * 3
            and span.box[0] <= right + height * 3
        )]
        groups: list[list[TextSpan]] = []
        for span in sorted(local, key=lambda item: (item.center_y, item.box[0])):
            group = next((items for items in groups if any(
                abs(span.center_y - item.center_y) <= max(height * 0.65,
                                                         min(span.height, item.height) * 0.25)
                and max(item.box[0] - span.box[2], span.box[0] - item.box[2], 0)
                <= height * 2
                for item in items
            )), None)
            if group is None:
                groups.append([span])
            else:
                group.append(span)
        for group in groups:
            digits = "".join(
                character
                for span in sorted(group, key=lambda item: item.box[0])
                for character in span.text
                if character.isascii() and character.isdecimal()
            )
            if digits != note_digits:
                continue
            group_box = (
                min(span.box[0] for span in group), min(span.box[1] for span in group),
                max(span.box[2] for span in group), max(span.box[3] for span in group),
            )
            if _box_coverage(overlay.row.box, group_box) >= 0.7:
                duplicated.update(span for span in group if (
                    any(character.isascii() and character.isdecimal() for character in span.text)
                    or left <= span.center_x <= right and top <= span.center_y <= bottom
                ))
    return tuple(span for span in ordered_spans if span in duplicated)


def _box_coverage(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> float:
    """Return what fraction of a smaller box is covered by another box."""
    intersection = max(0, min(inner[2], outer[2]) - max(inner[0], outer[0])) * max(
        0, min(inner[3], outer[3]) - max(inner[1], outer[1]),
    )
    area = max(1, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return intersection / area


def _score_text(page: PageObservation) -> PageObservation:
    """Keep QR-adjacent publishing text out of title, credits and lyric ownership."""
    excluded = []
    regions = list(page.excluded_regions)
    for span in page.text_spans:
        # Explicit lyricist/composer credits remain score content even beside a QR panel.
        if re.search(r"(?:词|曲|作词|作曲)\s*$", span.text):
            continue
        if any(
            max(left - span.box[2], span.box[0] - right, 0) <= span.height
            and max(top - span.box[3], span.box[1] - bottom, 0) <= span.height
            for left, top, right, bottom in page.excluded_regions
        ):
            excluded.append(span)
            regions.append(span.box)
    return replace(
        page, text_spans=tuple(span for span in page.text_spans if span not in excluded),
        excluded_regions=tuple(regions),
    )



def enrich_page_text(
    path: Path,
    page: PageObservation,
    original_spans: tuple[TextSpan, ...],
    *,
    first_page: bool,
    on_text_ready: Callable[[], None] | None = None,
) -> PageObservation:
    """Apply the shared page-text policy, preserving each input path's stage order."""
    is_pdf = page.native_text_spans is not None
    if is_pdf:
        if page.ocr_text_spans is not None:
            recovered = _pdf_lyric_baseline_text(path, page, page.text_spans)
            page = replace(
                page,
                text_spans=recovered.spans,
                text_merge_conflicts=recovered.conflicts,
            )
        if first_page:
            page = replace(page, text_spans=_header_spans(path, page, page.text_spans))
    elif page.text_source != "unavailable":
        spans = _lyric_baseline_text(path, page, page.text_spans)
        if first_page:
            spans = _header_spans(path, page, spans)
        page = replace(page, text_spans=spans)

    if on_text_ready is not None:
        on_text_ready()
    page = _score_text(page)
    return _performance_text(path, page, original_spans)
