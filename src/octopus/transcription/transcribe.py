"""Produce a reviewable JPS draft from raster pages, with unresolved evidence."""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from statistics import median

from . import text
from .decorations import decoration_token, text_decorations
from .headers import extract_headers, printed_key_span, stacked_meter_span
from .image import MusicRow, PageObservation, _read_page, recognize_image
from .lyrics import extract_lyrics
from .margins import filter_document_margins
from .marks import row_sustains
from .review import RowBinding, finite_confidence, note_confidence_findings, render_back_findings
from .text import (
    TextSpan,
    image_annotation_text,
    image_lyric_text,
    image_text,
    merge_text,
    pdf_text,
    scale_pdf_text,
)

MAX_PDF_BYTES = 100_000_000
MAX_PDF_PAGES = 200
MAX_PDF_RASTER_PIXELS = 7_000_000


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    page: int
    detail: str
    regions: tuple[tuple[int, int, int, int], ...] = ()
    # Unicode codepoint offsets into Draft.jps; end is exclusive. Classifier
    # agreement is evidence for review, not a calibrated probability.
    confidence: float | None = None
    source_start: int | None = None
    source_end: int | None = None


@dataclass(frozen=True, slots=True)
class Draft:
    jps: str
    pages: tuple[PageObservation, ...]
    issues: tuple[Issue, ...]

    def issue_json(self) -> str:
        return json.dumps(
            {
                "status": "review_required",
                "note_confidence_kind": "uncalibrated_classifier_agreement",
                "pages": [
                    {
                        "width": page.width,
                        "height": page.height,
                        "music_rows": len(page.rows),
                        "candidate_digits": page.candidate_digits,
                        "text_spans": len(page.text_spans),
                        "text_source": page.text_source,
                        "voice_groups": [list(group.rows) for group in page.voice_groups],
                        "dsb_overlays": [asdict(overlay) for overlay in page.dsb_overlays],
                        "bz_overlays": [
                            {"anchor": overlay.anchor, "box": overlay.row.box}
                            for overlay in page.bz_overlays
                        ],
                        "unresolved_braces": list(page.unresolved_braces),
                        "excluded_regions": list(page.excluded_regions),
                        "note_confidence": [
                            {"row": row_index, "note": note_index, "digit": note.digit,
                             "box": note.box, "confidence": finite_confidence(note.confidence),
                             "stream": "main" if row_index < len(page.rows) else "bz"}
                            for row_index, row in enumerate(
                                (*page.rows, *(bz.row for bz in page.bz_overlays))
                            ) for note_index, note in enumerate(row.notes)
                        ],
                    }
                    for page in self.pages
                ],
                "issues": [asdict(issue) for issue in self.issues],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"


def _bar_marks(
    row: MusicRow, music_positions: tuple[float, ...], endings: tuple[tuple[float, str], ...],
) -> list[tuple[float, str]]:
    """Compile nearby strokes as one bar, with exclusively owned repeat dots and endings."""
    if not row.barlines:
        return []
    digit_height = median(note.box[3] - note.box[1] for note in row.notes)
    row_y = median((note.box[1] + note.box[3]) / 2 for note in row.notes)
    groups: list[list[int]] = []
    for x in sorted(set(row.barlines)):
        if (
            groups and x - groups[-1][-1] <= digit_height * 0.65
            and not any(groups[-1][-1] < position < x for position in music_positions)
        ):
            groups[-1].append(x)
        else:
            groups.append([x])
    dots = [
        box for box in row.unresolved_marks
        if box[2] - box[0] <= digit_height * 0.4
        and box[3] - box[1] <= max(4, digit_height * 0.5)
        and abs((box[1] + box[3]) / 2 - row_y) <= digit_height * 1.1
    ]
    owners = {
        box: min(range(len(groups)), key=lambda index: min(
            abs((box[0] + box[2]) / 2 - x) for x in groups[index]
        )) for box in dots
    }
    marks: list[tuple[float, str]] = []
    for index, group in enumerate(groups):
        repeats = []
        for edge, direction in ((group[0], -1), (group[-1], 1)):
            side = sorted((box for box in dots if owners[box] == index
                           and 1 < direction * ((box[0] + box[2]) / 2 - edge)
                           <= digit_height * 0.8), key=lambda box: box[1])
            repeat = False
            if len(side) == 2:
                first, second = side
                repeat = (
                    abs(first[0] + first[2] - second[0] - second[2]) <= digit_height * 0.6
                    and second[1] - first[1] >= digit_height * 0.2
                )
            repeats.append(repeat)
        left, right = repeats
        token = (":|:" if left and right else ":|" if left else "|:" if right
                 else "||" if len(group) > 1 else "|")
        ending = "".join(token for anchor, token in endings if anchor in group)
        marks.append((group[0], token + ending))
    return marks


def _row_marks(
    row: MusicRow, endings: tuple[tuple[float, str], ...] = (),
    *, synchronized_head_bar: bool = False,
) -> list[tuple[float, str]]:
    graces: dict[int, str] = {}
    for group in row.graces:
        graces[group.host] = graces.get(group.host, "") + group.body
    event_marks = [
        (
            note.box,
            note.digit + note.accidental
            + ("'" * note.octave if note.octave > 0 else "," * -note.octave)
            + "/" * note.duration_slashes + "." * note.duration_dots
            + "".join("&" + token for token in note.decorations)
            + "".join(note.annotations)
            + graces.get(index, ""),
        )
        for index, note in enumerate(row.notes)
    ]
    event_marks.extend((box, "-") for box in row_sustains(
        tuple(note.box for note in row.notes), row.unresolved_marks,
    ))
    # Keep dash ordering stable at a shared x-coordinate. Slur endpoints index notes
    # only; accompaniment brackets and hairpins still use the complete event stream.
    event_marks.sort(key=lambda item: item[0])
    marks: list[tuple[float, str]] = [(box[0], body) for box, body in event_marks]
    note_indices = {note.box: index for index, note in enumerate(row.notes)}
    note_marks = {
        note_indices[box]: index for index, (box, _) in enumerate(event_marks)
        if box in note_indices
    }
    for pin in row.hairpins:
        if 0 <= pin.start <= pin.end < len(marks):
            x, body = marks[pin.start]
            marks[pin.start] = (x, body + pin.code)
            x, body = marks[pin.end]
            marks[pin.end] = (x, body + "!")
    for index, token in row.parentheses:
        x, body = marks[index]
        marks[index] = (x, body + token)
    left_cut = right_cut = 0
    for start_index, end_index in row.slurs:
        if start_index is not None:
            mark_index = note_marks[start_index]
            x, body = marks[mark_index]
            marks[mark_index] = (x, "(" + body)
        else:
            left_cut += 1
        if end_index is not None:
            mark_index = note_marks[end_index]
            x, body = marks[mark_index]
            marks[mark_index] = (x, body + ")")
        else:
            right_cut += 1
    bars = _bar_marks(row, tuple(x for x, _ in marks), endings)
    if right_cut and bars:
        x, body = bars[-1]
        bars[-1] = (x, body + ")" * right_cut)
    marks.extend(bars)
    if left_cut:
        marks.append((row.box[0] - 0.5, "(" * left_cut))
    if left_cut or synchronized_head_bar:
        marks.append((row.box[0] - 0.5, "|/"))
    marks.extend((x, "|/" + token) for x, token in endings if x not in row.barlines)
    return marks


def _row_tokens(
    row: MusicRow,
    endings: tuple[tuple[float, str], ...] = (),
    *,
    synchronized_head_bar: bool = False,
) -> str:
    return " ".join(token for _, token in sorted(_row_marks(
        row, endings, synchronized_head_bar=synchronized_head_bar,
    )))


def _synchronized_head_bar_rows(page: PageObservation) -> set[int]:
    """Share a hidden head bar among simultaneous voices and DSB branches."""
    synchronized: set[int] = set()

    def align_head(rows: set[int]) -> None:
        if len(rows) < 2:
            return
        first_x = min(page.rows[index].box[0] for index in rows)
        note_heights = [
            note.box[3] - note.box[1]
            for index in rows for note in page.rows[index].notes
        ]
        if not note_heights:
            return
        tolerance = median(note_heights) * 1.5
        head_rows = {
            index for index in rows
            if page.rows[index].box[0] <= first_x + tolerance
        }
        if len(head_rows) > 1 and any(
            start is None
            for index in head_rows
            for start, _ in page.rows[index].slurs
        ):
            synchronized.update(head_rows)

    groups = []
    for group in page.voice_groups:
        rows = set(group.rows)
        rows.update(
            branch for overlay in page.dsb_overlays
            if overlay.anchor in group.rows and not overlay.standalone
            for branch in (overlay.upper, overlay.lower)
        )
        groups.append(rows)
        align_head(rows)
    for overlay in page.dsb_overlays:
        branches = {overlay.upper, overlay.lower}
        if not any(branches <= rows for rows in groups):
            align_head(branches)
    return synchronized


def _row_cut_issues(pages: tuple[PageObservation, ...]) -> list[Issue]:
    """Flag only row-end cuts that lack a detected barline for local serialization."""
    issues: list[Issue] = []
    for page_index, page in enumerate(pages, start=1):
        rows = [*page.rows, *(overlay.row for overlay in page.bz_overlays)]
        issues.extend(Issue(
            "slur_cut_barline_missing", page_index,
            "A row-cut closer has no detected barline; check its cross-row continuation.",
            (row.box,),
        ) for row in rows if not row.barlines
            and any(last is None and first is not None for first, last in row.slurs))
    return issues


def _ending_marks(
    pages: tuple[PageObservation, ...],
) -> tuple[dict[tuple[int, int], tuple[tuple[float, str], ...]], list[Issue]]:
    """Pair continuation frames in printed order within their owning voice."""
    voices: dict[int, list[tuple[int, int, MusicRow]]] = {}
    for page_index, page in enumerate(pages):
        numbers = {
            row_index: number for group in page.voice_groups
            for number, row_index in enumerate(group.rows, start=1)
        }
        for row_index, row in enumerate(page.rows):
            voices.setdefault(numbers.get(row_index, 0), []).append((page_index, row_index, row))
    found: dict[tuple[int, int], tuple[tuple[float, str], ...]] = {}
    issues: list[Issue] = []
    for rows in voices.values():
        active = False
        for position, (page_index, row_index, row) in enumerate(rows):
            height = median(note.box[3] - note.box[1] for note in row.notes)
            marks: dict[float, str] = {}
            for segment in row.endings:
                left, _, right, _ = segment.box
                if not segment.opens and not active:
                    issues.append(Issue(
                        "ending_continuation_unresolved", page_index + 1,
                        "A continuation frame has no observed opener in this voice.",
                        (segment.box,),
                    ))
                    continue
                issues.append(Issue(
                    "ending_attachment_review", page_index + 1,
                    "Check ending label, barline attachment, continuation and bracket height.",
                    (segment.box,),
                ))
                if segment.opens:
                    start: float = min(row.barlines, key=lambda x: abs(x - left), default=left)
                    if start not in row.barlines or abs(start - left) > height * 0.65:
                        start = row.box[0] - height
                    label = f'"{segment.label}"' if segment.label else ""
                    marks[start] = marks.get(start, "") + "[" + label
                    active = True
                end = (
                    min((x for x in row.barlines if x >= right), default=
                        min(row.barlines, key=lambda x: abs(x - right), default=right))
                    if not segment.closed else
                    min(row.barlines, key=lambda x: abs(x - right), default=right)
                )
                continuation = False
                if not segment.closed and right >= max((row.box[2], *row.barlines)) - height * 0.5:
                    following = next((
                        (later_position, item)
                        for later_position, (_, _, later) in enumerate(
                            rows[position + 1:], start=position + 1,
                        )
                        for item in later.endings
                    ), None)
                    continuation = following is not None and not following[1].opens
                    if continuation and following is not None:
                        for gap_page, _, gap_row in rows[position + 1:following[0]]:
                            issues.append(Issue(
                                "ending_continuation_gap_review", gap_page + 1,
                                "Paired ending frames span this unframed music row; "
                                "confirm their extent against the source.", (gap_row.box,),
                            ))
                if not continuation:
                    marks[end] = marks.get(end, "") + ("]" if segment.closed else "]/")
                    active = False
            found[page_index, row_index] = tuple(marks.items())
    return found, issues


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
    if not page.rows:
        return spans
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
        return spans
    if page.voice_groups and not any(
        any("\u3400" <= char <= "\u9fff" for char in span.text)
        and span.center_y > page.rows[0].box[3] for span in spans
    ):
        return spans
    if note_height >= 16:
        # Large merged lyric rows need crops only when whole-page OCR exceeds its safe size.
        ocr_limit = getattr(text._ocr_engine(), "max_side_len", 2000)
        if not merged_lyrics or max(page.width, page.height) <= ocr_limit:
            return spans
    lyrics = image_lyric_text(
        path, tuple(row.box for row in page.rows), small_page=note_height < 16,
        recover_sparse=bool(page.voice_groups),
    )
    if not lyrics:
        return spans
    lyric_duplicates = _bz_duplicate_text_spans(page, lyrics)
    lyrics = tuple(span for span in lyrics if span not in lyric_duplicates)
    if page.voice_groups:
        # Crops can also contain the next voice's digits or performance marks.
        # Replace only corroborated lyric baselines, retaining all other text.
        lyrics = tuple(span for span in lyrics if span.confidence >= 0.72
                       and any("\u3400" <= char <= "\u9fff" for char in span.text)
                       and all("\u3400" <= char <= "\u9fff" or char.isspace()
                               or char in "，。！？、,.!?；;：:" for char in span.text))
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


def _compile(pages: tuple[PageObservation, ...]) -> Draft:
    source = ["# Image transcription draft; review the adjacent .issues.json before use."]
    pages, ignored_margins = filter_document_margins(pages)
    issues = _row_cut_issues(pages)
    issues.extend(Issue(
        "margin_text_ignored", page_number,
        "Excluded isolated margin pagination or a recurring document header/footer.", regions,
    ) for page_number, regions in ignored_margins)
    bindings: list[RowBinding] = []
    ending_marks, ending_issues = _ending_marks(pages)
    issues.extend(ending_issues)
    for page_number, page in enumerate(pages, start=1):
        if page.excluded_regions:
            issues.append(Issue(
                "non_score_graphics_ignored", page_number,
                "Excluded QR graphics and their adjacent publishing panel from transcription.",
                page.excluded_regions,
            ))
        if page_number == 1:
            head = extract_headers(
                page.text_spans,
                page.width,
                page.rows[0].box[1] if page.rows else page.height,
            )
            source.extend(head.lines)
            issues.append(Issue(
                "header_fields_review", page_number,
                "Verify title, credits, key accidentals, stacked meter and tempo against the page.",
                head.regions,
            ))
            if head.missing:
                issues.append(Issue(
                    "header_fields_unresolved",
                    page_number,
                    f"Required visible header fields need review: {', '.join(head.missing)}.",
                    head.regions,
                ))
        if page_number > 1:
            source.extend(("", "[fenye]"))
        if page.text_source == "unavailable":
            issues.append(Issue(
                "text_ocr_unavailable", page_number,
                "Install the transcription extra to recognize text in raster pages.",
            ))
        if not page.rows:
            issues.append(
                Issue("no_music_rows", page_number, "No complete music row was detected.")
            )
        voice_numbers = {
            row_index: number
            for group in page.voice_groups
            for number, row_index in enumerate(group.rows, start=1)
        }
        synchronized_head_rows = _synchronized_head_bar_rows(page)
        for group in page.voice_groups:
            issues.append(Issue(
                "voice_group_review", page_number,
                "Verify simultaneous voice identity and order across this bracketed system.",
                (group.box,),
            ))
        overlay_by_anchor = {overlay.anchor: overlay for overlay in page.dsb_overlays}
        branch_rows = {
            index for overlay in page.dsb_overlays
            for index in ((overlay.lower,) if overlay.standalone
                          else (overlay.upper, overlay.lower))
        }
        for dsb in page.dsb_overlays:
            issues.append(Issue(
                "dsb_overlay_review", page_number,
                "Check temporary voice extent, branches and timing against the image.",
                (dsb.box, page.rows[dsb.upper].box, page.rows[dsb.lower].box),
            ))
        for brace in page.unresolved_braces:
            issues.append(Issue(
                "unpaired_voice_brace", page_number,
                "A printed brace has no recoverable pair of note branches; check the source page.",
                (brace,),
            ))
        bz_by_anchor: dict[int, list[MusicRow]] = {}
        for bz in page.bz_overlays:
            bz_by_anchor.setdefault(bz.anchor, []).append(bz.row)
            issues.append(Issue(
                "bz_overlay_review", page_number,
                "Check the bounded accompaniment extent and anchor against the image.",
                (bz.row.box, page.rows[bz.anchor].box),
            ))
        for row_index, row in enumerate(page.rows):
            if row_index in branch_rows:
                continue
            voice = voice_numbers.get(row_index)
            overlay = overlay_by_anchor.get(row_index)
            row_for_marks = row
            if overlay is not None and overlay.continuation:
                brace_left, _, brace_right, _ = overlay.box
                row_for_marks = replace(row, barlines=tuple(
                    x for x in row.barlines if not brace_left <= x <= brace_right
                ))
            marks = _row_marks(
                row_for_marks,
                ending_marks.get((page_number - 1, row_index), ()),
                synchronized_head_bar=row_index in synchronized_head_rows,
            )
            for small in bz_by_anchor.get(row_index, []):
                anchor_x = min(
                    (note.box[0] for note in row.notes),
                    key=lambda x: abs(x - small.box[0]),
                )
                note_height = row.notes[0].box[3] - row.notes[0].box[1]
                insertion_x = (
                    anchor_x if abs(anchor_x - small.box[0]) <= note_height * 1.5
                    else small.box[0]
                )
                marks.append((insertion_x - 0.5, f"{{bz {_row_tokens(small)} }}"))
            if overlay is not None:
                upper = _row_tokens(
                    page.rows[overlay.upper],
                    ending_marks.get((page_number - 1, overlay.upper), ()),
                    synchronized_head_bar=overlay.upper in synchronized_head_rows,
                )
                lower = _row_tokens(
                    page.rows[overlay.lower],
                    ending_marks.get((page_number - 1, overlay.lower), ()),
                    synchronized_head_bar=overlay.lower in synchronized_head_rows,
                )
                block = f"{{dsb {upper} }} {lower}"
                if overlay.standalone:
                    marks = [(overlay.box[0] - 0.5, block)]
                elif overlay.continuation:
                    branch_start = min(
                        page.rows[overlay.upper].box[0],
                        page.rows[overlay.lower].box[0],
                    )
                    marks.append((branch_start - 0.5, block))
                elif overlay.closing_x is not None:
                    marks = [
                        mark for mark in marks
                        if not overlay.box[0] <= mark[0] <= overlay.closing_x
                    ]
                    marks.append((overlay.box[0] - 0.5, block))
                else:
                    marks.append((overlay.box[0] - 0.5, block))
            music = " ".join(token for _, token in sorted(marks))
            if voice is None or voice == 1:
                source.append("")
            source.append(f"Q{voice or ''}: {music}")
            bindings.append(RowBinding(
                page_number, row_index, len(source),
                overlay is None and not bz_by_anchor.get(row_index),
            ))
            if row.decoration_regions:
                issues.append(Issue(
                    "decoration_attachment_review", page_number,
                    "Performance instructions and wedge/fermata ownership are provisional; "
                    "confirm each recovered mark against the source.", row.decoration_regions,
                ))
            if row.graces:
                issues.append(Issue(
                    "grace_attachment_review", page_number,
                    "Check small-note pitch, octave, beams and pre/post host attachment.",
                    tuple(group.box for group in row.graces),
                ))
            issues.append(
                Issue(
                    "row_semantics_unresolved",
                    page_number,
                    "Digits, octave/duration dots, underlines and barlines are provisional; "
                    "remaining rhythm, accidentals, ornaments, slurs, lyric alignment and voice "
                    "identity need review.",
                    row.unresolved_marks or (row.box,),
                )
            )
            lyric_band_after = (
                overlay.lower if overlay is not None and not overlay.continuation else None
            )
            for lyric in extract_lyrics(page, row_index, lyric_band_after):
                source.append(f"C{voice or ''}: {lyric.body}")
                issues.append(Issue(
                    "lyric_alignment_review", page_number,
                    "Check lyric characters, skips and ownership against the image.",
                    lyric.regions,
                ))
                if lyric.slot_constrained:
                    issues.append(Issue(
                        "lyric_slots_constrained", page_number,
                        "An adjacent lyric collision was assigned to the measure's note "
                        "slots using matching syllable counts and bounded movement. "
                        "Verify these inferred character positions against the scan.",
                        lyric.regions,
                    ))
        issues.append(Issue(
            "lyrics_coverage_unverified", page_number,
            "Confirm every printed lyric row and its voice ownership."
        ))
    code = "\n".join(source) + "\n"
    findings = (
        *note_confidence_findings(code, pages, tuple(bindings)),
        *render_back_findings(code, pages, tuple(bindings)),
    )
    issues.extend(Issue(
        item.code, item.page, item.detail, item.regions, item.confidence,
        item.source_start, item.source_end,
    ) for item in findings)
    return Draft(code, pages, tuple(issues))


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
            text_spans = merge_text(native_spans, ocr_spans or ())
            original_spans = text_spans
            if not native_spans and ocr_spans is not None:
                text_spans = _lyric_baseline_text(image_path, observation, text_spans)
            if page_number == 1:
                text_spans = _header_spans(image_path, observation, text_spans)
            text_source = (
                "pdf_text+ocr" if native_spans and ocr_spans is not None
                else "pdf_text" if native_spans else "ocr" if ocr_spans is not None
                else "unavailable"
            )
            observations.append(
                _performance_text(image_path, _score_text(replace(
                    observation, text_spans=text_spans, text_source=text_source,
                )), original_spans)
            )
            image_path.unlink()
            if progress:
                progress(page_number, count, "recognizing")
    return tuple(observations)


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
        if text_spans is not None:
            text_spans = _lyric_baseline_text(path, observation, text_spans)
            text_spans = _header_spans(path, observation, text_spans)
        if progress:
            progress(1, 1, "compiling")
        return _compile((_performance_text(path, _score_text(replace(
            observation,
            text_spans=text_spans or (),
            text_source="ocr" if text_spans is not None else "unavailable",
        )), original_spans),))
    if suffix == ".pdf":
        pages = _pdf_pages(path, progress)
        if progress:
            progress(len(pages), len(pages), "compiling")
        return _compile(pages)
    raise ValueError("transcription input must be PNG, JPG, JPEG or PDF")
