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
from .decorations import text_decorations
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
        and box[3] - box[1] <= max(4, digit_height * 0.35)
        and abs((box[1] + box[3]) / 2 - row_y) <= digit_height * 0.8
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
) -> list[tuple[float, str]]:
    graces: dict[int, str] = {}
    for group in row.graces:
        graces[group.host] = graces.get(group.host, "") + group.body
    marks: list[tuple[float, str]] = [
        (
            note.box[0],
            note.digit + note.accidental
            + ("'" * note.octave if note.octave > 0 else "," * -note.octave)
            + "/" * note.duration_slashes + "." * note.duration_dots
            + "".join("&" + token for token in note.decorations)
            + "".join(note.annotations)
            + graces.get(index, ""),
        )
        for index, note in enumerate(row.notes)
    ]
    marks.extend((box[0], "-") for box in row_sustains(
        tuple(note.box for note in row.notes), row.unresolved_marks,
    ))
    marks.sort()
    for pin in row.hairpins:
        if 0 <= pin.start <= pin.end < len(marks):
            x, body = marks[pin.start]
            marks[pin.start] = (x, body + pin.code)
            x, body = marks[pin.end]
            marks[pin.end] = (x, body + "!")
    for index, token in row.parentheses:
        x, body = marks[index]
        marks[index] = (x, body + token)
    for start_index, end_index in row.slurs:
        if start_index is not None:
            x, body = marks[start_index]
            marks[start_index] = (x, "(" + body)
        if end_index is not None:
            x, body = marks[end_index]
            marks[end_index] = (x, body + ")")
    marks.extend(_bar_marks(row, tuple(x for x, _ in marks), endings))
    marks.extend((x, "|/" + token) for x, token in endings if x not in row.barlines)
    return marks


def _row_tokens(row: MusicRow, endings: tuple[tuple[float, str], ...] = ()) -> str:
    return " ".join(token for _, token in sorted(_row_marks(row, endings)))


def _slur_continuations(
    pages: tuple[PageObservation, ...],
) -> tuple[tuple[PageObservation, ...], list[Issue]]:
    """Emit row-cut curves only when an observed mate exists in the same voice."""
    active: dict[tuple[str, int], list[tuple[int, int, int]]] = {}
    paired: set[tuple[int, int, int]] = set()
    for page_index, page in enumerate(pages):
        numbers = {index: number for group in page.voice_groups
                   for number, index in enumerate(group.rows, start=1)}
        owners = {index: ("main", numbers.get(index, 0)) for index in range(len(page.rows))}
        for overlay in page.dsb_overlays:
            voice = numbers.get(overlay.anchor, 0)
            owners[overlay.upper] = ("dsb_upper", voice)
            owners[overlay.lower] = ("dsb_lower", voice)
        for row_index, row in enumerate(page.rows):
            stack = active.setdefault(owners[row_index], [])
            for index, (first, last) in sorted(
                enumerate(row.slurs),
                key=lambda item: item[1][0] if item[1][0] is not None else item[1][1] or 0,
            ):
                location = (page_index, row_index, index)
                if first is not None and last is None:
                    stack.append(location)
                elif first is None and last is not None and stack:
                    paired.update((stack.pop(), location))
    issues = []
    result = []
    for page_index, page in enumerate(pages):
        rows = []
        for row_index, row in enumerate(page.rows):
            slurs = tuple(pair for index, pair in enumerate(row.slurs)
                          if None not in pair or (page_index, row_index, index) in paired)
            if len(slurs) != len(row.slurs):
                issues.append(Issue(
                    "slur_continuation_unresolved", page_index + 1,
                    "A curved row-cut endpoint has no observed mate in this voice.", (row.box,),
                ))
            rows.append(replace(row, slurs=slurs))
        # Small accompaniment overlays have no cross-system voice identity.
        bz = tuple(replace(overlay, row=replace(
            overlay.row, slurs=tuple(pair for pair in overlay.row.slurs if None not in pair),
        )) for overlay in page.bz_overlays)
        for accompaniment in page.bz_overlays:
            if any(None in pair for pair in accompaniment.row.slurs):
                issues.append(Issue(
                    "slur_continuation_unresolved", page_index + 1,
                    "An accompaniment row-cut curve has no established continuation voice.",
                    (accompaniment.row.box,),
                ))
        result.append(replace(page, rows=tuple(rows), bz_overlays=bz))
    return tuple(result), issues


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
    note_height = median(note.box[3] - note.box[1] for row in page.rows for note in row.notes)
    merged_lyrics = any(
        span.height >= note_height * 1.8
        and span.box[2] - span.box[0] < span.height
        and sum("\u3400" <= char <= "\u9fff" for char in span.text) >= 2
        and any(row.box[3] < span.center_y < row.box[3] + note_height * 4.6
                for row in page.rows)
        for span in spans
    )
    if note_height >= 16:
        # ponytail: large-page crops need one owner; polyphony needs voice-specific crops.
        ocr_limit = getattr(text._ocr_engine(), "max_side_len", 2000)
        if (not merged_lyrics or page.voice_groups or page.dsb_overlays or page.bz_overlays
                or page.unresolved_braces
                or max(page.width, page.height) <= ocr_limit):
            return spans
    lyrics = image_lyric_text(
        path, tuple(row.box for row in page.rows), small_page=note_height < 16,
    )
    if not lyrics:
        return spans
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
    return replace(page, rows=rows, bz_overlays=overlays, text_spans=tuple(
        span for span in page.text_spans if span not in consumed
    ))


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
    pages, issues = _slur_continuations(pages)
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
            marks = _row_marks(row, ending_marks.get((page_number - 1, row_index), ()))
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
            overlay = overlay_by_anchor.get(row_index)
            if overlay is not None:
                upper = _row_tokens(
                    page.rows[overlay.upper],
                    ending_marks.get((page_number - 1, overlay.upper), ()),
                )
                lower = _row_tokens(
                    page.rows[overlay.lower],
                    ending_marks.get((page_number - 1, overlay.lower), ()),
                )
                block = f"{{dsb {upper} }} {lower}"
                if overlay.standalone:
                    marks = [(overlay.box[0] - 0.5, block)]
                elif overlay.continuation:
                    marks.append((row.box[0] - 0.5, block))
                elif overlay.closing_x is not None:
                    marks = [
                        mark for mark in marks
                        if not overlay.box[0] <= mark[0] <= overlay.closing_x
                    ]
                    marks.append((overlay.box[0] - 0.5, block))
                else:
                    marks.append((row.box[2] + 0.5, block))
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
            for lyric in extract_lyrics(
                page, row_index, overlay.lower if overlay is not None else None
            ):
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
    page_sizes = {
        int(number): (float(width), float(height))
        for number, width, height in re.findall(
            r"Page\s+(\d+)\s+size:\s+([\d.]+) x ([\d.]+) pts", metadata
        )
    }
    if progress:
        progress(0, count, "recognizing")
    observations = []
    native_text = pdf_text(path)
    with tempfile.TemporaryDirectory(prefix="jianpu-transcribe-") as temporary:
        raster = Path(temporary) / "page"
        for page_number in range(1, count + 1):
            page_width, page_height = page_sizes.get(page_number, (750.0, 1061.25))
            dpi = min(203, max(1, math.floor(72 * math.sqrt(
                7_000_000 / (page_width * page_height)
            ))))
            subprocess.run(
                [
                    "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                    "-singlefile", "-r", str(dpi), "-png", str(path), str(raster),
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
    ocr_backend: text.OcrBackend = "rapidocr-onnxruntime",
) -> Draft:
    """Use only the supplied image/PDF, never a paired source or reference file."""
    with text.using_ocr_backend(ocr_backend):
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
