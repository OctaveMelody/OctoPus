"""Place printed lyric words under their visible music row."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .components import Box
from .image import MusicRow, PageObservation
from .text import TextSpan

_DYNAMICS = {"pp", "p", "mp", "mf", "f", "ff", "rit", "dim", "cresc", "d.s.", "d.c."}
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


def _is_lyric_text(value: str) -> bool:
    text = value.strip()
    return text.lower() not in _DYNAMICS and (
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
    for position, (word, x) in enumerate(units):
        if word.startswith('"'):
            x = next((later_x for later_word, later_x in units[position + 1:]
                      if not later_word.startswith('"')), x)
        index = min(range(len(centers)), key=lambda position: abs(centers[position] - x))
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
            drafts.append(LyricDraft(body, tuple(span.box for span in band)))
    return tuple(drafts)
