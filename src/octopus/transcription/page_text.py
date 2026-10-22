"""Enrich page text and assign recovered performance text to score owners."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median

from . import text
from .components import Box
from .decorations import decoration_token, ending_title_text, score_text_kind, text_decorations
from .directions import attach_score_directions, remove_attached_direction_text
from .headers import extract_headers, printed_key_span, stacked_meter_span
from .image import MusicRow, PageObservation, _read_page
from .text import (
    MIN_TEXT_SPAN_CONFIDENCE,
    TextMergeResult,
    TextSpan,
    image_annotation_text,
    image_lyric_text,
    image_score_direction_text,
    merge_text,
)


@dataclass(frozen=True, slots=True)
class _LyricRecovery:
    """Page text and localized lyric crops selected for one recovery attempt."""

    text_spans: tuple[TextSpan, ...]
    note_height: float | None
    lyrics: tuple[TextSpan, ...] | None


def _same_lyric_baseline(first: TextSpan, second: TextSpan, height: float) -> bool:
    baseline_gap = abs(first.center_y - second.center_y)
    horizontal_gap = max(first.box[0] - second.box[2], second.box[0] - first.box[2], 0)
    return (baseline_gap <= max(9, min(first.height, second.height) * 0.42)
            and horizontal_gap <= height * 0.8)


def _lyric_glyph(character: str) -> bool:
    return (character.isalpha()
            or character in "，。！？、,.!?；;：:")


def _contains_in_order(source: str, reading: str) -> bool:
    characters = iter(reading)
    return bool(source) and all(any(candidate == char for candidate in characters)
                                 for char in source)


def _split_stacked_character_spans(
    spans: tuple[TextSpan, ...], first_music_top: int, height: float,
) -> tuple[TextSpan, ...]:
    """Split OCR word boxes when their individual glyph boxes show separate lyric rows."""
    result: list[TextSpan] = []
    for span in spans:
        boxes = span.character_boxes
        if (span.box[3] <= first_music_top or len(boxes) != len(span.text)
                or span.lyric_baselines):
            result.append(span)
            continue
        chinese = [index for index, character in enumerate(span.text)
                   if "\u3400" <= character <= "\u9fff"]
        if len(chinese) < 2:
            result.append(span)
            continue
        centers = [(box[1] + box[3]) / 2 for box in boxes]
        tolerance = max(3.0, height * 0.5)
        groups: list[list[int]] = []
        for index in sorted(chinese, key=lambda item: centers[item]):
            prior_center = median(centers[item] for item in groups[-1]) if groups else 0
            if groups and centers[index] - prior_center <= tolerance:
                groups[-1].append(index)
            else:
                groups.append([index])
        group_centers = [median(centers[index] for index in group) for group in groups]
        if (len(groups) < 2 or min(
            right - left for left, right in zip(
                group_centers, group_centers[1:], strict=False,
            )
        ) < max(7.0, height * 0.65)):
            result.append(span)
            continue

        assigned: list[list[int]] = [[] for _ in groups]
        for index, center in enumerate(centers):
            group_index = min(
                range(len(groups)), key=lambda item: abs(center - group_centers[item]),
            )
            if abs(center - group_centers[group_index]) > max(height, tolerance * 2):
                break
            assigned[group_index].append(index)
        else:
            for indices in assigned:
                indices.sort(key=lambda item: (boxes[item][0] + boxes[item][2]) / 2)
                if not any("\u3400" <= span.text[index] <= "\u9fff" for index in indices):
                    continue
                character_boxes = tuple(boxes[index] for index in indices)
                result.append(TextSpan(
                    "".join(span.text[index] for index in indices),
                    (min(box[0] for box in character_boxes),
                     min(box[1] for box in character_boxes),
                     max(box[2] for box in character_boxes),
                     max(box[3] for box in character_boxes)),
                    span.confidence,
                    tuple((box[0] + box[2]) / 2 for box in character_boxes),
                    (), character_boxes,
                ))
            continue
        result.append(span)
    return tuple(result)


def _character_positions_supported(
    span: TextSpan, lyrics: tuple[TextSpan, ...], height: float,
) -> bool:
    """Confirm a page OCR reading against same-glyph positions in a focused crop."""
    if len(span.character_centers) != len(span.text):
        return False
    crop_characters = tuple(
        (character, lyric.character_centers[index])
        for lyric in lyrics if len(lyric.character_centers) == len(lyric.text)
        for index, character in enumerate(lyric.text)
        if "\u3400" <= character <= "\u9fff"
    )
    source_characters = tuple(
        (character, span.character_centers[index])
        for index, character in enumerate(span.text)
        if "\u3400" <= character <= "\u9fff"
    )
    if not source_characters or not crop_characters:
        return False
    tolerance = max(5.0, height * 0.4)
    return all(any(character == candidate and abs(center - candidate_center) <= tolerance
                   for candidate, candidate_center in crop_characters)
               for character, center in source_characters)


def _reconcile_crop_characters(
    crops: set[TextSpan], spans: tuple[TextSpan, ...], height: float,
) -> tuple[tuple[TextSpan, ...], dict[int, set[int]]]:
    """Resolve overlapping crop glyphs against positioned page OCR characters."""
    def glyph_center_y(span: TextSpan, index: int) -> float:
        if len(span.character_boxes) == len(span.text):
            box = span.character_boxes[index]
            return (box[1] + box[3]) / 2
        return span.center_y

    def glyph_dimensions(span: TextSpan, index: int) -> tuple[int, int]:
        if len(span.character_boxes) == len(span.text):
            left, top, right, bottom = span.character_boxes[index]
            return right - left, bottom - top
        return 0, 0

    def glyph_center_tolerance(
        crop: TextSpan, crop_index: int, source: TextSpan, source_index: int,
        exact_character: bool,
    ) -> float:
        crop_width, crop_height = glyph_dimensions(crop, crop_index)
        source_width, source_height = glyph_dimensions(source, source_index)
        result = max(tolerance, crop_width * 0.5, source_width * 0.5)
        return max(result, crop_height * 0.5, source_height * 0.5) \
            if exact_character else result

    ordered = sorted(crops, key=lambda span: (-span.confidence, span.box, span.text))
    used: set[tuple[int, int]] = set()
    consumed: dict[int, set[int]] = {}
    resolved: list[TextSpan] = []
    tolerance = max(5.0, height * 0.5)
    for crop in ordered:
        if len(crop.character_centers) != len(crop.text):
            resolved.append(crop)
            continue
        characters: list[str] = []
        centers: list[float] = []
        boxes: list[Box] = []
        has_boxes = len(crop.character_boxes) == len(crop.text)
        last_source_center: float | None = None
        for index, character in enumerate(crop.text):
            if not _lyric_glyph(character):
                characters.append(character)
                centers.append(crop.character_centers[index])
                if has_boxes:
                    boxes.append(crop.character_boxes[index])
                continue
            crop_y = glyph_center_y(crop, index)
            candidates = sorted(
                ((abs(crop.character_centers[index] - span.character_centers[source_index]),
                  -span.confidence, span, source_index)
                 for span in spans
                 if len(span.character_centers) == len(span.text)
                 and _same_lyric_baseline(span, crop, height)
                 for source_index, source_character in enumerate(span.text)
                 if _lyric_glyph(source_character)
                 and abs(crop.character_centers[index]
                         - span.character_centers[source_index]) <= glyph_center_tolerance(
                             crop, index, span, source_index,
                             source_character == character,
                         )
                 and abs(crop_y - glyph_center_y(span, source_index))
                 <= max(4.0, height * 0.35)),
                key=lambda item: (item[0], item[1], item[2].box, item[3]),
            )
            exact = [item for item in candidates if item[2].text[item[3]] == character]
            ordered_candidates = [
                item for item in candidates
                if last_source_center is None
                or item[2].character_centers[item[3]] > last_source_center
            ]
            ordered_exact = [item for item in exact if item in ordered_candidates]
            pool = ordered_exact if exact else ordered_candidates
            out_of_order = any(
                (id(item[2]), item[3]) not in used
                and item not in ordered_candidates
                for item in (exact or candidates)
            )
            available = next((item for item in pool
                              if (id(item[2]), item[3]) not in used), None)
            if available is None and candidates and not out_of_order:
                continue
            if available is None:
                characters.append(character)
                centers.append(crop.character_centers[index])
                if has_boxes:
                    boxes.append(crop.character_boxes[index])
                continue
            _, _, source, source_index = available
            used.add((id(source), source_index))
            consumed.setdefault(id(source), set()).add(source_index)
            last_source_center = source.character_centers[source_index]
            source_character = source.text[source_index]
            selected = (source_character if source.confidence >= crop.confidence
                        else character)
            characters.append(selected)
            centers.append(
                source.character_centers[source_index]
                if source.confidence >= crop.confidence
                else crop.character_centers[index]
            )
            if has_boxes:
                source_boxes = source.character_boxes
                boxes.append(source_boxes[source_index]
                             if source.confidence >= crop.confidence
                             and len(source_boxes) == len(source.text)
                             else crop.character_boxes[index])
        if not characters:
            continue
        box = crop.box
        character_boxes = tuple(boxes) if has_boxes and len(boxes) == len(characters) else ()
        if character_boxes:
            box = (min(item[0] for item in character_boxes),
                   min(item[1] for item in character_boxes),
                   max(item[2] for item in character_boxes),
                   max(item[3] for item in character_boxes))
        resolved.append(TextSpan(
            "".join(characters), box, crop.confidence, tuple(centers),
            crop.lyric_baselines, character_boxes,
        ))
    return tuple(resolved), consumed


def _unconsumed_span_fragments(
    span: TextSpan, consumed: set[int],
) -> tuple[TextSpan, ...]:
    """Keep source characters that no accepted crop replaced."""
    if not consumed or len(span.character_centers) != len(span.text):
        return (span,)
    runs: list[list[int]] = []
    current: list[int] = []
    for index in range(len(span.text)):
        if index in consumed or span.text[index].isspace():
            if current:
                runs.append(current)
                current = []
            continue
        current.append(index)
    if current:
        runs.append(current)
    fragments = []
    for indices in runs:
        text_value = "".join(span.text[index] for index in indices)
        centers = tuple(span.character_centers[index] for index in indices)
        character_boxes = tuple(span.character_boxes[index] for index in indices) \
            if len(span.character_boxes) == len(span.text) else ()
        if character_boxes:
            box = (min(item[0] for item in character_boxes),
                   min(item[1] for item in character_boxes),
                   max(item[2] for item in character_boxes),
                   max(item[3] for item in character_boxes))
        else:
            box = span.box
        fragments.append(TextSpan(
            text_value, box, span.confidence, centers, span.lyric_baselines,
            character_boxes,
        ))
    return tuple(fragments)


def _merge_lyric_readings(
    spans: tuple[TextSpan, ...], lyrics: tuple[TextSpan, ...],
    first_music_top: int, height: float,
) -> tuple[TextSpan, ...]:
    """Prefer a crop reading only when baseline and OCR evidence support it."""
    retained: set[TextSpan] = set()
    rejected_crops: set[TextSpan] = set()
    accepted_crops: set[TextSpan] = set()
    for span in spans:
        if span.box[3] < first_music_top or not any(char.isalpha() for char in span.text):
            continue
        related = tuple(sorted(
            (lyric for lyric in lyrics if _same_lyric_baseline(span, lyric, height)),
            key=lambda lyric: lyric.box[0],
        ))
        if not related:
            retained.add(span)
            continue
        original = text._text_key(span.text)
        recovered = "".join(text._text_key(lyric.text) for lyric in related)
        recovered_left = min(lyric.box[0] for lyric in related)
        recovered_right = max(lyric.box[2] for lyric in related)
        horizontal_coverage = max(
            0, min(span.box[2], recovered_right) - max(span.box[0], recovered_left),
        ) / max(1, span.box[2] - span.box[0])
        crop_is_better = (
            (_contains_in_order(original, recovered)
             and (min(lyric.confidence for lyric in related) >= span.confidence
                  or _character_positions_supported(span, related, height)))
            or (original == recovered and any(lyric.character_centers for lyric in related))
            or (horizontal_coverage >= 0.8
                and all(lyric.confidence > span.confidence for lyric in related))
        )
        if crop_is_better:
            accepted_crops.update(related)
            continue
        retained.add(span)
        rejected_crops.update(lyric for lyric in related if (
            lyric.box[0] < span.box[2] and span.box[0] < lyric.box[2]
        ))
    accepted_spans = tuple(span for span in spans if span in retained
                           or span.box[3] < first_music_top
                           or not any(char.isalpha() for char in span.text))
    selected_crops = {lyric for lyric in lyrics
                      if lyric not in rejected_crops or lyric in accepted_crops}
    resolved_crops, consumed = _reconcile_crop_characters(selected_crops, spans, height)
    # Focused OCR boxes are tight around their recognized text. Suppress conflicting
    # page glyphs inside an accepted crop even when their centers are too far apart to
    # pair one-to-one with the crop's character boxes.
    for crop in accepted_crops:
        if len(crop.character_boxes) == len(crop.text):
            crop_glyph_boxes = tuple(
                crop.character_boxes[index] for index, character in enumerate(crop.text)
                if _lyric_glyph(character)
            )
        elif (len(crop.text) == 1
              and crop.box[2] - crop.box[0] <= max(1, crop.height) * 3):
            crop_glyph_boxes = (crop.box,)
        else:
            crop_glyph_boxes = ()
        if not crop_glyph_boxes:
            continue
        for span in spans:
            if (len(span.character_centers) != len(span.text)
                    or not _same_lyric_baseline(span, crop, height)):
                continue
            for index, center in enumerate(span.character_centers):
                source_y = (
                    (span.character_boxes[index][1] + span.character_boxes[index][3]) / 2
                    if len(span.character_boxes) == len(span.text) else span.center_y
                )
                vertical_margin = max(3.0, height * 0.15)
                if (any(left <= center <= right
                        and top - vertical_margin <= source_y <= bottom + vertical_margin
                        for left, top, right, bottom in crop_glyph_boxes)
                        and ("\u3400" <= span.text[index] <= "\u9fff"
                             or span.text[index] in "，。！？、,.!?；;：:")):
                    consumed.setdefault(id(span), set()).add(index)
    source_spans = tuple(
        span for span in spans
        if span in accepted_spans or consumed.get(id(span))
    )
    source_residuals = tuple(
        fragment for span in source_spans
        for fragment in _unconsumed_span_fragments(span, consumed.get(id(span), set()))
    )
    return (*source_residuals, *resolved_crops)


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
    spans = _split_stacked_character_spans(spans, page.rows[0].box[1], note_height)
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
    return _merge_lyric_readings(spans, lyrics, page.rows[0].box[1], note_height)


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
        and sum(char.isalpha() for char in span.text) >= 2
        and any(row.box[3] < span.center_y < row.box[3] + note_height * 4.6
                for row in page.rows)
        for span in spans
    )
    if (page.dsb_overlays or page.unresolved_braces
            or page.bz_overlays and not page.voice_groups):
        return _LyricRecovery(spans, note_height, None)
    if page.voice_groups and not any(
        any(char.isalpha() for char in span.text)
        and span.center_y > page.rows[0].box[3] for span in spans
    ):
        return _LyricRecovery(spans, note_height, None)
    crop_has_lyric_reading = any(
        any(char.isalpha() for char in span.text)
        and any(
            row.box[3] < span.center_y < row.box[3] + note_height * 4.6
            and span.box[0] < row.box[2] + note_height
            and span.box[2] > row.box[0] - note_height
            for row in page.rows
        )
        for span in spans
    )
    if note_height >= 16:
        if page.native_text_spans is not None:
            # Keep the existing PDF gate: native text stays authoritative unless
            # whole-page OCR merges lyrics on a page beyond its safe side length.
            ocr_limit = getattr(text._ocr_engine(), "max_side_len", 2000)
            if not merged_lyrics or max(page.width, page.height) <= ocr_limit:
                return _LyricRecovery(spans, note_height, None)
        elif not merged_lyrics and not crop_has_lyric_reading:
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
        lyrics = tuple(span for span in lyrics
                       if span.confidence >= MIN_TEXT_SPAN_CONFIDENCE
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
    overlay_rows = tuple(bz.row for bz in page.bz_overlays)
    all_rows = (*page.rows, *overlay_rows)
    cropped = image_annotation_text(path, tuple(row.box for row in all_rows)) or ()
    cropped_directions = image_score_direction_text(
        path, tuple((row.box, row.barlines) for row in page.rows),
    ) or ()
    # A valid performance mark can conflict with a native lyric glyph during
    # page-text reconciliation. Keep raw OCR available for geometric ownership.
    candidates = tuple(dict.fromkeys((
        *page.text_spans, *(page.ocr_text_spans or ()), *original, *cropped,
        *cropped_directions,
    )))
    bz_duplicates = _bz_duplicate_text_spans(page, candidates)
    overlay_boxes = tuple(overlay.row.box for overlay in page.bz_overlays)
    candidates = tuple(span for span in candidates if (
        span not in bz_duplicates
        and not (decoration_token(span.text) is not None
                 and any(_box_coverage(span.box, box) >= 0.7 for box in overlay_boxes))
    ))
    candidates = _score_text(replace(page, text_spans=candidates)).text_spans
    rows, direction_sources = attach_score_directions(
        page.rows, candidates, page_height=page.height,
    )
    rows, score_text_spans = _attach_score_text(rows, candidates)
    consumed: set[TextSpan] = set()
    decoration_candidates = tuple(
        span for span in candidates if span not in score_text_spans
    )

    owned_rows = (*rows, *overlay_rows)

    def decorate(row: MusicRow) -> MusicRow:
        found = text_decorations(
            tuple(note.box for note in row.notes), decoration_candidates, gray=gray,
            other_rows=tuple(other.box for other in owned_rows if other is not row),
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

    rows = tuple(decorate(row) for row in rows)
    overlays = tuple(replace(bz, row=decorate(bz.row)) for bz in page.bz_overlays)
    removed = consumed | set(bz_duplicates) | set(score_text_spans)
    retained = remove_attached_direction_text(page.text_spans, direction_sources)
    return replace(page, rows=rows, bz_overlays=overlays, text_spans=tuple(
        span for span in retained if span not in removed
    ))


def _attach_score_text(
    rows: tuple[MusicRow, ...], spans: tuple[TextSpan, ...],
) -> tuple[tuple[MusicRow, ...], tuple[TextSpan, ...]]:
    """Attach ending titles and explicit repeat-lyric instructions by geometry."""
    if not rows:
        return rows, ()
    heights = tuple(note.box[3] - note.box[1] for row in rows for note in row.notes)
    if not heights:
        return rows, ()
    height = median(heights)
    updated = list(rows)
    consumed: set[TextSpan] = set()
    attached_titles: dict[tuple[int, int], list[TextSpan]] = {}
    attached_notes: list[TextSpan] = []
    for span in spans:
        kind = score_text_kind(span.text)
        if kind is None or span.confidence < MIN_TEXT_SPAN_CONFIDENCE:
            continue
        if kind == "instruction_candidate":
            continue
        if kind == "ending_title":
            ending_owner = _ending_text_owner(span, tuple(updated), height)
            if ending_owner is not None:
                owner_titles = attached_titles.setdefault(ending_owner, [])
                if any(_same_score_text_reading(span, previous) for previous in owner_titles):
                    consumed.add(span)
                    continue
                row_index, ending_index = ending_owner
                row = updated[row_index]
                endings = list(row.endings)
                ending = endings[ending_index]
                endings[ending_index] = replace(
                    ending, label=" ".join(filter(None, (
                        ending.label, ending_title_text(span.text) or span.text.strip(),
                    ))),
                )
                updated[row_index] = replace(
                    row, endings=tuple(endings),
                    decoration_regions=(*row.decoration_regions, span.box),
                )
                owner_titles.append(span)
                consumed.add(span)
                continue
        owner = _score_text_owner(span, tuple(updated), height)
        if owner is None:
            continue
        if any(_same_score_text_reading(span, previous) for previous in attached_notes):
            consumed.add(span)
            continue
        row_index, note_index = owner
        row = updated[row_index]
        notes = list(row.notes)
        annotation_text = ending_title_text(span.text) if kind == "ending_title" else None
        annotation = _quoted_score_text(annotation_text or span.text)
        notes[note_index] = replace(
            notes[note_index],
            annotations=tuple(dict.fromkeys((*notes[note_index].annotations, annotation))),
        )
        updated[row_index] = replace(
            row, notes=tuple(notes), decoration_regions=(*row.decoration_regions, span.box),
        )
        attached_notes.append(span)
        consumed.add(span)
    return tuple(updated), tuple(consumed)


def _same_score_text_reading(first: TextSpan, second: TextSpan) -> bool:
    """Match overlapping OCR boxes that describe one score-text reading."""
    first_title = ending_title_text(first.text)
    second_title = ending_title_text(second.text)
    same_reading = (
        first_title is not None and first_title == second_title
        if first_title is not None or second_title is not None
        else text._text_key(first.text) == text._text_key(second.text)
    )
    if not same_reading:
        return False
    overlap = max(0, min(first.box[2], second.box[2]) - max(first.box[0], second.box[0])) * max(
        0, min(first.box[3], second.box[3]) - max(first.box[1], second.box[1]),
    )
    first_area = max(1, (first.box[2] - first.box[0]) * (first.box[3] - first.box[1]))
    second_area = max(1, (second.box[2] - second.box[0]) * (second.box[3] - second.box[1]))
    return overlap / min(first_area, second_area) >= 0.8


def _quoted_score_text(value: str) -> str:
    """Use typographic quotes inside the JPS annotation delimiter."""
    quote_open = True
    content = []
    for character in value.strip():
        if character == '"':
            content.append("“" if quote_open else "”")
            quote_open = not quote_open
        else:
            content.append(character)
    return '"' + "".join(content) + '"'


def _ending_text_owner(
    span: TextSpan, rows: tuple[MusicRow, ...], height: float,
) -> tuple[int, int] | None:
    candidates = []
    for row_index, row in enumerate(rows):
        for ending_index, ending in enumerate(row.endings):
            left, top, right, bottom = ending.box
            horizontal_coverage = max(0, min(span.box[2], right) - max(span.box[0], left))
            horizontal_ratio = horizontal_coverage / max(1, span.box[2] - span.box[0])
            vertical_gap = max(top - span.box[3], span.box[1] - bottom, 0)
            if horizontal_ratio >= 0.65 and vertical_gap <= height * 0.35:
                candidates.append((vertical_gap / height + 1 - horizontal_ratio,
                                   row_index, ending_index))
    if not candidates:
        return None
    _, row_index, ending_index = min(candidates)
    return row_index, ending_index


def _score_text_owner(
    span: TextSpan, rows: tuple[MusicRow, ...], height: float,
) -> tuple[int, int] | None:
    candidates = []
    for row_index, row in enumerate(rows):
        if not row.notes:
            continue
        vertical_gap = max(row.box[1] - span.box[3], span.box[1] - row.box[3], 0)
        if vertical_gap > height * 3.5:
            continue
        horizontal_gap = max(row.box[0] - span.box[2], span.box[0] - row.box[2], 0)
        if horizontal_gap > height * 1.5:
            continue
        text_x = (
            span.character_centers[0]
            if len(span.character_centers) == len(span.text) and span.character_centers
            else span.box[0] + min(height * 0.45, (span.box[2] - span.box[0]) / 2)
        )
        note_index = min(
            range(len(row.notes)),
            key=lambda index: abs((row.notes[index].box[0] + row.notes[index].box[2]) / 2
                                  - text_x),
        )
        note_x = (row.notes[note_index].box[0] + row.notes[note_index].box[2]) / 2
        note_gap = abs(note_x - text_x)
        if note_gap > height * 2.5:
            continue
        candidates.append((vertical_gap / height + horizontal_gap / height + note_gap / height,
                           row_index, note_index))
    if not candidates:
        return None
    _, row_index, note_index = min(candidates)
    return row_index, note_index


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
