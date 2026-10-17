"""Assemble enriched page observations into JPS and semantic review records."""

from __future__ import annotations

from dataclasses import replace
from statistics import median

from .headers import extract_headers
from .image import MusicRow, PageObservation
from .lyrics import extract_lyrics
from .margins import filter_document_margins
from .marks import row_sustains
from .results import Draft, Issue, RowBinding


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


def _text_issue_excerpt(value: str) -> str:
    normalized = " ".join(value.split())
    excerpt = normalized if len(normalized) <= 80 else normalized[:79] + "…"
    return repr(excerpt)


def assemble(
    pages: tuple[PageObservation, ...],
) -> tuple[Draft, tuple[RowBinding, ...]]:
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
        for conflict in page.text_merge_conflicts:
            native_reading = " ".join(span.text for span in conflict.native_spans)
            native_excerpt = _text_issue_excerpt(native_reading)
            ocr_excerpt = _text_issue_excerpt(conflict.ocr_span.text)
            issues.append(Issue(
                "pdf_text_conflict", page_number,
                f"PDF text reads {native_excerpt}, while image OCR reads {ocr_excerpt}. "
                "Kept the PDF reading provisionally; verify the marked region.",
                (conflict.box,),
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
    return Draft(code, pages, tuple(issues)), tuple(bindings)
