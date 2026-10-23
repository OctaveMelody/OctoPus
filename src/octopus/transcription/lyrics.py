"""Place printed lyric words under their visible music row."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from statistics import linear_regression, median

from .components import Box
from .decorations import score_text_kind
from .image import MusicRow, PageObservation
from .text import MIN_TEXT_SPAN_CONFIDENCE, TextSpan

_DYNAMICS = {
    "ppp", "pp", "p", "mp", "mf", "f", "ff", "fff", "rit", "dim", "cresc",
    "d.s", "d.c", "d.s. fine", "d.c. fine",
}
_CJK_CHARACTERS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PERFORMER = re.compile(r"[（(]\s*([女男合])\s*[）)]")
_ANNOTATION = re.compile(r"[（(]\s*[女男合]\s*[）)]|[①-⑳]|(?<!\d)\d+[.．](?!\d)")
_PAGINATION = re.compile(
    r"(?:第\s*\d+\s*页\s*)?共\s*\d+\s*页|第\s*\d+\s*页|page\s+\d+(?:\s+of\s+\d+)?",
    re.I,
)
_MIN_BASELINE_TOLERANCE = 9
_LYRIC_PUNCTUATION = frozenset("，。！？、,.!?；;：:")


@dataclass(frozen=True, slots=True)
class LyricDraft:
    body: str
    regions: tuple[Box, ...]
    slot_constrained: bool = False
    accepted_slot_groups: tuple[tuple[str, ...] | None, ...] = ()


def _is_lyric_text(value: str) -> bool:
    text = value.strip()
    return score_text_kind(text) is None and text.lower().rstrip(".．") not in _DYNAMICS and (
        any("\u3400" <= character <= "\u9fff" for character in text)
        or _ANNOTATION.fullmatch(text) is not None
        or any(character.isalpha() for character in text)
    )


def _is_lyric_punctuation(value: str) -> bool:
    text = value.strip()
    return bool(text) and all(character in _LYRIC_PUNCTUATION for character in text)


def _lyric_units(span: TextSpan) -> list[tuple[str, float]]:
    text = span.text.strip()
    if not text:
        return []
    if any("\u3400" <= character <= "\u9fff" for character in text) or _ANNOTATION.fullmatch(text):
        units: list[tuple[str, float]] = []
        width = span.box[2] - span.box[0]
        for match in re.finditer(_ANNOTATION.pattern + "|.", text):
            word = match.group()
            if word.isspace():
                continue
            label = _PERFORMER.fullmatch(word)
            x = (
                sum(span.character_centers[match.start():match.end()]) / len(word)
                if len(span.character_centers) == len(text)
                else span.box[0] + width * (match.start() + len(word) / 2) / len(text)
            )
            if label:
                units.append((f'"({label.group(1)})"', x))
            elif _ANNOTATION.fullmatch(word):
                units.append((f'"{word}"', x))
            elif word in "，。！？、,.!?；;：:" and units:
                previous, position = units[-1]
                units[-1] = (previous + word, position)
            else:
                units.append((word, x))
        return units
    width = span.box[2] - span.box[0]
    return [
        (
            f'"{match.group()}"' if _ANNOTATION.fullmatch(match.group()) else match.group(),
            sum(span.character_centers[match.start():match.end()]) / len(match.group())
            if len(span.character_centers) == len(text)
            else span.box[0] + width * (match.start() + len(match.group()) / 2) / len(text),
        )
        for match in re.finditer(_ANNOTATION.pattern + r"|\S+", text)
    ]


def _deduplicate_overlapping_glyphs(spans: list[TextSpan]) -> tuple[TextSpan, ...]:
    """Keep the clearer reading of the same ink across lyric baselines."""
    selected: list[TextSpan | None] = [None] * len(spans)
    occupied: list[tuple[Box, int, TextSpan, str]] = []
    ambiguous = _multibaseline_glyphs(spans)
    order = sorted(range(len(spans)), key=lambda index: (
        -spans[index].confidence, spans[index].box, spans[index].text, index,
    ))
    for span_index in order:
        span = spans[span_index]
        boxes = span.character_boxes
        if len(boxes) != len(span.text):
            selected[span_index] = span
            continue

        kept: list[int] = []
        for index, box in enumerate(boxes):
            left, top, right, bottom = box
            if right <= left or bottom <= top:
                kept.append(index)
                continue
            if (span_index, index) in ambiguous:
                continue
            center_y = (top + bottom) / 2
            duplicate = any(
                abs(center_y - (other_box[1] + other_box[3]) / 2) <= max(
                    9, min(bottom - top, other_box[3] - other_box[1]) * 0.42,
                )
                and _overlapping_readings_share_ink(
                    span.text[index], other_character, box, other_box,
                )
                for other_box, other_index, other, other_character in occupied
                if other_index != span_index
            )
            if not duplicate:
                kept.append(index)
                occupied.append((box, span_index, span, span.text[index]))

        while kept and span.text[kept[0]].isspace():
            kept.pop(0)
        while kept and span.text[kept[-1]].isspace():
            kept.pop()
        if not kept:
            continue
        if kept == list(range(len(span.text))):
            selected[span_index] = span
            continue

        character_boxes = tuple(boxes[index] for index in kept)
        centers = (
            tuple(span.character_centers[index] for index in kept)
            if len(span.character_centers) == len(span.text)
            else tuple((box[0] + box[2]) / 2 for box in character_boxes)
        )
        selected[span_index] = replace(
            span,
            text="".join(span.text[index] for index in kept),
            box=(min(box[0] for box in character_boxes),
                 min(box[1] for box in character_boxes),
                 max(box[2] for box in character_boxes),
                 max(box[3] for box in character_boxes)),
            character_centers=centers,
            character_boxes=character_boxes,
        )
    return tuple(span for span in selected if span is not None)


def _multibaseline_glyphs(spans: list[TextSpan]) -> set[tuple[int, int]]:
    """Find tall OCR boxes that cover glyphs on two separate lyric baselines."""
    glyphs = tuple(
        (span_index, index, box)
        for span_index, span in enumerate(spans)
        if len(span.character_boxes) == len(span.text)
        for index, box in enumerate(span.character_boxes)
        if box[2] > box[0] and box[3] > box[1]
    )
    ambiguous: set[tuple[int, int]] = set()
    for span_index, character_index, box in glyphs:
        box_height = box[3] - box[1]
        overlapping = tuple(
            (other_span_index, other_index, other_box)
            for other_span_index, other_index, other_box in glyphs
            if other_span_index != span_index and _glyph_boxes_overlap(box, other_box)
        )
        for position, (first_span, _, first_box) in enumerate(overlapping):
            first_center = (first_box[1] + first_box[3]) / 2
            first_height = first_box[3] - first_box[1]
            for second_span, _, second_box in overlapping[position + 1:]:
                if first_span == second_span:
                    continue
                second_center = (second_box[1] + second_box[3]) / 2
                second_height = second_box[3] - second_box[1]
                baseline_tolerance = max(9, min(first_height, second_height) * 0.42)
                if (abs(first_center - second_center) <= baseline_tolerance
                        or box_height < max(first_height, second_height) * 1.5
                        or box[1] > min(first_center, second_center)
                        or box[3] < max(first_center, second_center)):
                    continue
                ambiguous.add((span_index, character_index))
                break
            if (span_index, character_index) in ambiguous:
                break
    return ambiguous


def _glyph_boxes_overlap(first: Box, second: Box) -> bool:
    first_width = first[2] - first[0]
    second_width = second[2] - second[0]
    first_height = first[3] - first[1]
    second_height = second[3] - second[1]
    if min(first_width, second_width, first_height, second_height) <= 0:
        return False
    overlap_x = max(0, min(first[2], second[2]) - max(first[0], second[0]))
    overlap_y = max(0, min(first[3], second[3]) - max(first[1], second[1]))
    return (overlap_x * 2 >= min(first_width, second_width)
            and overlap_y * 2 >= min(first_height, second_height))


def _overlapping_readings_share_ink(
    first_character: str, second_character: str, first: Box, second: Box,
) -> bool:
    """Distinguish duplicate glyphs from different characters in a merged tall box."""
    if not _glyph_boxes_overlap(first, second):
        return False
    if first_character == second_character:
        return True

    overlap_width = max(0, min(first[2], second[2]) - max(first[0], second[0]))
    overlap_height = max(0, min(first[3], second[3]) - max(first[1], second[1]))
    overlap_area = overlap_width * overlap_height
    larger_area = max(
        (first[2] - first[0]) * (first[3] - first[1]),
        (second[2] - second[0]) * (second[3] - second[1]),
    )
    # Conflicting OCR readings can represent one glyph when their boxes are nearly
    # coextensive. A tall box spanning adjacent lyric rows is not that evidence.
    return overlap_area * 2 >= larger_area


def _assemble(spans: list[TextSpan], notes: MusicRow) -> str:
    return _assemble_with_slots(spans, notes)[0]


def _assemble_with_slots(
    spans: list[TextSpan], notes: MusicRow,
) -> tuple[str, tuple[tuple[str, ...] | None, ...], bool]:
    centers = [(note.box[0] + note.box[2]) / 2 for note in notes.notes]
    if not centers:
        return "", (), False
    assigned: dict[int, list[str]] = {}
    units = [
        unit for span in sorted(spans, key=lambda item: item.box[0])
        for unit in _lyric_units(span)
    ]
    # OCR without character boxes estimates evenly spaced character centers. When
    # this creates an adjacent collision and an empty note in a closed measure,
    # the measure's one-syllable-per-note slot count is a conservative prior.
    # Exact character evidence, rests, genuine extra syllables and large movement
    # remain on the ordinary nearest-column path (including legitimate ~ joins).
    constrained = _measure_slot_priors(spans, units, notes, centers)
    for position, (word, x) in enumerate(units):
        target_position = position
        if word.startswith('"'):
            target_position, x = next(
                ((later_position, later_x)
                 for later_position, (later_word, later_x) in enumerate(
                     units[position + 1:], start=position + 1,
                 ) if not later_word.startswith('"')), (position, x),
            )
        index = constrained.get(target_position, min(
            range(len(centers)), key=lambda position: abs(centers[position] - x),
        ))
        assigned.setdefault(index, []).append(word)
    accepted = tuple(
        tuple(words) if (words := assigned.get(index)) is not None else None
        for index in range(len(centers))
    )
    if not assigned:
        return "", accepted, bool(constrained)
    body = []
    previous_words: list[str] | None = None
    for index in range(max(assigned) + 1):
        words = assigned.get(index)
        if words is None:
            body.append("@")
            previous_words = None
        else:
            lyric_words = [word for word in words if not word.startswith('"')]
            if (previous_words and lyric_words
                    and any(character.isalpha() for character in previous_words[-1])
                    and not _CJK_CHARACTERS.search(previous_words[-1])
                    and any(character.isalpha() for character in lyric_words[0])
                    and not _CJK_CHARACTERS.search(lyric_words[0])):
                body.append("/")
            body.append("".join(
                ("~" if index and not word.startswith('"')
                 and not words[index - 1].startswith('"') else "") + word
                for index, word in enumerate(words)
            ))
            previous_words = lyric_words
    return "".join(body), accepted, bool(constrained)


def _measure_slot_priors(
    spans: list[TextSpan], units: list[tuple[str, float]], row: MusicRow, centers: list[float],
) -> dict[int, int]:
    """Repair only bounded adjacent collisions with a corroborated syllable count."""
    if any(span.character_centers for span in spans) or any(
        span.confidence < 0.9 for span in spans
    ):
        return {}
    result: dict[int, int] = {}
    bars = sorted(set(row.barlines))
    for left, right in zip(bars, bars[1:], strict=False):
        slots = [index for index, x in enumerate(centers) if left < x < right]
        words = [index for index, (word, x) in enumerate(units)
                 if left < x < right and not word.startswith('"')]
        if len(slots) < 2 or len(slots) != len(words) or any(
            row.notes[index].digit == "0" for index in slots
        ):
            continue
        # The prior is for single Chinese syllables, with attached punctuation.
        # Latin words have no reliable syllable count without linguistic analysis.
        if any(not re.fullmatch(r"[\u3400-\u9fff][，。！？、,.!?；;：:]*", units[index][0])
               for index in words):
            continue
        nearest = [min(slots, key=lambda slot: abs(centers[slot] - units[index][1]))
                   for index in words]
        if len(set(nearest)) == len(slots):
            continue
        if any(
            abs(centers[slot] - units[word][1]) >
            (row.notes[slot].box[3] - row.notes[slot].box[1]) * 0.75
            or abs(nearest[index] - slot) > 1
            or abs(centers[nearest[index]] - centers[slot]) >
            (row.notes[slot].box[3] - row.notes[slot].box[1]) * 1.5
            for index, (word, slot) in enumerate(zip(words, slots, strict=True))
        ):
            continue
        result.update(zip(words, slots, strict=True))
    return result


def extract_lyrics(
    page: PageObservation, row_index: int, band_after_index: int | None = None,
) -> tuple[LyricDraft, ...]:
    row = page.rows[row_index]
    after_index = band_after_index if band_after_index is not None else row_index
    after = page.rows[after_index]
    digit_height = max(16, round(sum(note.box[3] - note.box[1] for note in row.notes) /
                                 len(row.notes)))
    next_index = max(row_index, after_index) + 1
    continuation = next((overlay for overlay in page.dsb_overlays
                         if overlay.anchor == row_index and overlay.continuation), None)
    alignment_row = row
    overlay = next((overlay for overlay in page.dsb_overlays
                    if overlay.anchor == row_index), None)
    if overlay is not None:
        # The emitted JPS lyric stream includes the lower DSB branch, even when
        # the observed anchor row starts after a closing brace. Keep its note
        # slots so later syllables receive the necessary skips; upper notes are
        # a parallel stream, and sustain dashes do not consume lyric slots.
        lower = page.rows[overlay.lower]
        main_notes = tuple(note for note in row.notes if not (
            overlay.standalone or overlay.closing_x is not None
            and overlay.box[0] <= note.box[0] <= overlay.closing_x
        ))
        main_bars = tuple(x for x in row.barlines if not (
            overlay.standalone or overlay.closing_x is not None
            and overlay.box[0] <= x <= overlay.closing_x
        ))
        alignment_row = replace(
            row, notes=tuple(sorted((*main_notes, *lower.notes), key=lambda note: note.box[0])),
            barlines=tuple(sorted(set((*main_bars, *lower.barlines)))),
        )
    branch_boxes = tuple(
        page.rows[index].box for index in (continuation.upper, continuation.lower)
    ) if continuation else ()
    if continuation and next_index in {continuation.upper, continuation.lower}:
        next_index = max(continuation.upper, continuation.lower) + 1
    next_top = page.rows[next_index].box[1] if next_index < len(page.rows) else page.height
    top = after.box[3] + max(7, digit_height * 0.18)
    ordinary_bottom = min(next_top - 7, after.box[3] + digit_height * 4.6)
    bottom = next_top - 7
    xs = [(note.box[0] + note.box[2]) / 2 for note in after.notes]
    ys = [(note.box[1] + note.box[3]) / 2 for note in after.notes]
    slope = linear_regression(xs, ys).slope if len(set(xs)) > 1 else 0
    # Smaller drift already fits one lyric band and can reflect unequal numeral ink heights.
    if abs(slope) * (max(xs) - min(xs)) <= _MIN_BASELINE_TOLERANCE:
        slope = 0

    def baseline(span: TextSpan) -> float:
        return span.center_y - slope * span.center_x

    lyric_spans = []
    punctuation_spans = []
    for span in page.text_spans:
        if (span.confidence < MIN_TEXT_SPAN_CONFIDENCE
                or not (span.height >= digit_height * 0.58
                        or span.text == "一" and span.confidence >= 0.95
                        or _is_lyric_punctuation(span.text))
                or not top <= span.center_y < bottom
                or not (_is_lyric_text(span.text) or _is_lyric_punctuation(span.text))
                or any(left <= span.center_x <= right and upper <= span.center_y <= lower
                       for left, upper, right, lower in branch_boxes)
                or (next_index == len(page.rows)
                    and span.box[3] >= page.height - digit_height
                    and _PAGINATION.fullmatch(span.text.strip()))
                or (span.box[0] > page.width * 0.6
                    and span.box[2] > page.width * 0.9
                    and span.box[3] > page.height - digit_height)):
            continue
        if _is_lyric_punctuation(span.text):
            punctuation_spans.append(span)
        else:
            lyric_spans.append(span)

    # A cropped reading can leave a source-supported comma as its own span.
    # Attach it only to a preceding lyric glyph on the same baseline and nearby.
    for punctuation in sorted(punctuation_spans, key=lambda span: span.box[0]):
        punctuation_start = len(punctuation.text) - len(punctuation.text.lstrip())
        punctuation_end = len(punctuation.text.rstrip())
        punctuation_text = punctuation.text[punctuation_start:punctuation_end]
        punctuation_centers = (
            punctuation.character_centers[punctuation_start:punctuation_end]
            if len(punctuation.character_centers) == len(punctuation.text)
            else tuple(punctuation.center_x for _ in punctuation_text)
        )
        punctuation_boxes = (
            punctuation.character_boxes[punctuation_start:punctuation_end]
            if len(punctuation.character_boxes) == len(punctuation.text) else ()
        )
        owners = []
        for index, span in enumerate(lyric_spans):
            if abs(baseline(span) - baseline(punctuation)) > max(
                _MIN_BASELINE_TOLERANCE,
                min(span.height, punctuation.height) * 0.42,
            ):
                continue
            end_center = (
                span.character_centers[-1]
                if len(span.character_centers) == len(span.text) else span.box[2]
            )
            center_gap = punctuation_centers[0] - end_center
            position_tolerance = max(8.0, min(span.height, punctuation.height) * 0.75)
            box_gap = max(
                span.box[0] - punctuation.box[2],
                punctuation.box[0] - span.box[2], 0,
            )
            box_tolerance = max(4.0, min(span.height, punctuation.height) * 0.25)
            if (-position_tolerance * 0.25 <= center_gap <= position_tolerance
                    and box_gap <= box_tolerance):
                owners.append((abs(center_gap), -span.confidence, index))
        if not owners:
            continue
        _, _, owner_index = min(owners)
        owner = lyric_spans[owner_index]
        duplicate_count = 0
        for count in range(min(len(owner.text), len(punctuation_text)), 0, -1):
            if owner.text[-count:] != punctuation_text[:count]:
                continue
            if len(owner.character_boxes) == len(owner.text) and len(punctuation_boxes) == len(
                punctuation_text
            ):
                duplicate = all(
                    _glyph_boxes_overlap(first, second)
                    for first, second in zip(
                        owner.character_boxes[-count:], punctuation_boxes[:count], strict=True,
                    )
                )
            elif (len(owner.character_centers) == len(owner.text)
                  and len(punctuation_centers) == len(punctuation_text)):
                tolerance = max(2.0, min(owner.height, punctuation.height) * 0.2)
                duplicate = all(
                    abs(first - second) <= tolerance
                    for first, second in zip(
                        owner.character_centers[-count:], punctuation_centers[:count],
                        strict=True,
                    )
                )
            else:
                duplicate = False
            if duplicate:
                duplicate_count = count
                break
        punctuation_text = punctuation_text[duplicate_count:]
        punctuation_centers = punctuation_centers[duplicate_count:]
        punctuation_boxes = punctuation_boxes[duplicate_count:]
        if not punctuation_text:
            continue
        punctuation_box = punctuation.box
        if duplicate_count and punctuation_boxes:
            punctuation_box = (
                min(box[0] for box in punctuation_boxes), min(box[1] for box in punctuation_boxes),
                max(box[2] for box in punctuation_boxes), max(box[3] for box in punctuation_boxes),
            )
        centers = (
            (*owner.character_centers, *punctuation_centers)
            if len(owner.character_centers) == len(owner.text) else ()
        )
        boxes = (
            (*owner.character_boxes, *punctuation_boxes)
            if (len(owner.character_boxes) == len(owner.text)
                and len(punctuation_boxes) == len(punctuation_text))
            else ()
        )
        lyric_spans[owner_index] = TextSpan(
            owner.text + punctuation_text,
            (min(owner.box[0], punctuation_box[0]), min(owner.box[1], punctuation_box[1]),
             max(owner.box[2], punctuation_box[2]), max(owner.box[3], punctuation_box[3])),
            min(owner.confidence, punctuation.confidence), centers, owner.lyric_baselines, boxes,
        )
    # A right-aligned footer touching the page edge is outside the lyric band.
    # Resolve duplicates across the complete lyric region before dividing it into
    # baselines. A tall page-OCR box can sit between two rows and otherwise be
    # grouped with just one row, stealing a distinct glyph from that reading.
    spans = list(_deduplicate_overlapping_glyphs(lyric_spans))
    bands: list[list[TextSpan]] = []
    for span in sorted((span for span in spans if not span.lyric_baselines),
                       key=baseline):
        if bands and abs(baseline(span) - baseline(bands[-1][0])) <= max(
            _MIN_BASELINE_TOLERANCE, min(span.height, bands[-1][0].height) * 0.42
        ):
            bands[-1].append(span)
        else:
            bands.append([span])
    drafts = []
    previous_band: list[TextSpan] = []
    for band in bands:
        syllables = [word for span in band for word, _ in _lyric_units(span)
                     if not word.startswith('"')]
        # A line with more sung units than available note slots is likely prose,
        # a credit, or an OCR merge; leave it for text-ownership review.
        if not syllables or len(syllables) > len(alignment_row.notes):
            continue
        # Additional verses need a continuous lyric baseline, bounded by the next music row.
        if min(span.center_y for span in band) >= ordinary_bottom:
            if (not previous_band
                    or baseline(band[0]) - baseline(previous_band[0])
                    > min(median(span.height for span in band),
                          median(span.height for span in previous_band)) * 1.5):
                continue
        previous_band = list(band)
        band.extend(span for span in spans if any(
            abs(baseline - band[0].center_y) <= digit_height * 0.5
            for baseline in span.lyric_baselines
        ))
        body, accepted_slot_groups, constrained = _assemble_with_slots(band, alignment_row)
        if body:
            drafts.append(LyricDraft(
                body, tuple(span.box for span in band), constrained, accepted_slot_groups,
            ))
    return tuple(drafts)
