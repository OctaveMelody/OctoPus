"""Place printed lyric words under their visible music row."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .components import Box
from .image import MusicRow, PageObservation
from .text import TextSpan

_DYNAMICS = {"ppp", "pp", "p", "mp", "mf", "f", "ff", "fff", "rit", "dim", "cresc", "d.s", "d.c"}
_PERFORMER = re.compile(r"[（(]\s*([女男合])\s*[）)]")
_ANNOTATION = re.compile(r"[（(]\s*[女男合]\s*[）)]|[①-⑳]|(?<!\d)\d+[.．](?!\d)")
_RETURN = re.compile(r"\s*D\s*[.]\s*[SC]\s*[.:]?\s*$", re.I)
_PAGINATION = re.compile(
    r"(?:第\s*\d+\s*页\s*)?共\s*\d+\s*页|第\s*\d+\s*页|page\s+\d+(?:\s+of\s+\d+)?",
    re.I,
)


@dataclass(frozen=True, slots=True)
class LyricDraft:
    body: str
    regions: tuple[Box, ...]
    slot_constrained: bool = False


def _is_lyric_text(value: str) -> bool:
    text = value.strip()
    return text.lower().rstrip(".．") not in _DYNAMICS and (
        any("\u3400" <= character <= "\u9fff" for character in text)
        or _ANNOTATION.fullmatch(text) is not None
        or sum(character.isalpha() for character in text) >= 2
    )


def _lyric_units(span: TextSpan) -> list[tuple[str, float]]:
    text = span.text.strip()
    if not text:
        return []
    if any("\u3400" <= character <= "\u9fff" for character in text) or _ANNOTATION.fullmatch(text):
        units: list[tuple[str, float]] = []
        width = span.box[2] - span.box[0]
        lyric_end = _RETURN.search(text)
        lyric_text = text[:lyric_end.start()] if lyric_end else text
        for match in re.finditer(_ANNOTATION.pattern + "|.", lyric_text):
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


def _assemble(spans: list[TextSpan], notes: MusicRow) -> str:
    centers = [(note.box[0] + note.box[2]) / 2 for note in notes.notes]
    if not centers:
        return ""
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
    if not assigned:
        return ""
    body = []
    for index in range(max(assigned) + 1):
        words = assigned.get(index)
        if words is None:
            body.append("@")
        else:
            body.append("".join(
                ("~" if index and not word.startswith('"')
                 and not words[index - 1].startswith('"') else "") + word
                for index, word in enumerate(words)
            ))
    return "".join(body)


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
    next_top = page.rows[next_index].box[1] if next_index < len(page.rows) else page.height
    top = after.box[3] + max(7, digit_height * 0.18)
    bottom = min(next_top - 7, after.box[3] + digit_height * 4.6)
    # A right-aligned footer touching the page edge is outside the lyric band.
    spans = [
        span
        for span in page.text_spans
        if span.confidence >= 0.72
        and (span.height >= digit_height * 0.58 or span.text == "一" and span.confidence >= 0.95)
        and top <= span.center_y < bottom
        and _is_lyric_text(span.text)
        and not (next_index == len(page.rows) and span.box[3] >= page.height - digit_height
                 and _PAGINATION.fullmatch(span.text.strip()))
        and not (
            span.box[0] > page.width * 0.6
            and span.box[2] > page.width * 0.9
            and span.box[3] > page.height - digit_height
        )
    ]
    bands: list[list[TextSpan]] = []
    for span in sorted((span for span in spans if not span.lyric_baselines),
                       key=lambda value: value.center_y):
        if bands and abs(span.center_y - bands[-1][0].center_y) <= max(
            9, min(span.height, bands[-1][0].height) * 0.42
        ):
            bands[-1].append(span)
        else:
            bands.append([span])
    drafts = []
    for band in bands:
        band.extend(span for span in spans if any(
            abs(baseline - band[0].center_y) <= digit_height * 0.5
            for baseline in span.lyric_baselines
        ))
        body = _assemble(band, row)
        if body:
            units = [unit for span in sorted(band, key=lambda item: item.box[0])
                     for unit in _lyric_units(span)]
            constrained = bool(_measure_slot_priors(
                band, units, row, [(note.box[0] + note.box[2]) / 2 for note in row.notes],
            ))
            drafts.append(LyricDraft(body, tuple(span.box for span in band), constrained))
    return tuple(drafts)
