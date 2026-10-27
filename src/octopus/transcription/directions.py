"""Recognize score-navigation words and attach them to row-ending barlines."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from statistics import median

from .observations import MusicRow
from .text import MIN_TEXT_SPAN_CONFIDENCE, TextSpan

_DIRECTION_CODES = {
    "ds": ("ds",),
    "dc": ("dc.",),
    "fine": ("fine",),
    "dsfine": ("ds", "fine"),
    "dcfine": ("dc.", "fine"),
}
_DIRECTION_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:D\s*[.．]?\s*S\s*[.．]?|D\s*[.．]?\s*C\s*[.．]?|Fine\.?)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _DirectionSource:
    span: TextSpan
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _DirectionReading:
    span: TextSpan
    tokens: tuple[str, ...]
    sources: tuple[_DirectionSource, ...]


def _direction_tokens(value: str) -> tuple[str, ...]:
    original = unicodedata.normalize("NFKC", value).strip()
    normalized = original.casefold()
    if not re.fullmatch(r"[a-z.\s]+", normalized):
        return ()
    letters = re.sub(r"[.\s]+", "", normalized)
    if letters == "fine" and not original[0].isupper():
        return ()
    return _DIRECTION_CODES.get(letters, ())


def _embedded_direction_spans(
    span: TextSpan,
) -> tuple[_DirectionReading, ...]:
    """Isolate a direction beside lyric text using observed or estimated positions."""
    normalized = unicodedata.normalize("NFKC", span.text)
    if len(normalized) != len(span.text):
        return ()
    found = []
    centers = _character_centers(span)
    matches = tuple(_DIRECTION_PATTERN.finditer(normalized))
    has_navigation_target = any(
        token in {"ds", "dc."}
        for match in matches
        for token in _direction_tokens(match.group())
    )
    for match in matches:
        tokens = _direction_tokens(match.group())
        if not tokens:
            continue
        if tokens == ("fine",) and not has_navigation_target:
            continue
        start, end = match.span()
        left = (
            round((centers[start - 1] + centers[start]) / 2) if start else span.box[0]
        )
        right = (
            round((centers[end - 1] + centers[end]) / 2)
            if end < len(centers)
            else span.box[2]
        )
        found.append(_DirectionReading(
            TextSpan(
                match.group(), (left, span.box[1], right, span.box[3]), span.confidence,
                centers[start:end],
            ),
            tokens,
            (_DirectionSource(span, start, end),),
        ))
    return tuple(found)


def _direction_spans(
    spans: tuple[TextSpan, ...],
    height: float,
) -> tuple[_DirectionReading, ...]:
    """Keep exact OCR words and rejoin adjacent OCR fragments such as ``D.`` + ``S.``."""
    ordered = tuple(sorted(set(spans), key=lambda item: (item.center_y, item.box[0])))
    found: list[_DirectionReading] = []
    for span in ordered:
        if span.confidence < MIN_TEXT_SPAN_CONFIDENCE:
            continue
        tokens = _direction_tokens(span.text)
        if tokens:
            found.append(_DirectionReading(
                span, tokens, (_DirectionSource(span, 0, len(span.text)),),
            ))
        else:
            found.extend(_embedded_direction_spans(span))
    fragments = sorted((
        span
        for span in ordered
        if (
            span.confidence >= MIN_TEXT_SPAN_CONFIDENCE
            and re.fullmatch(r"[A-Za-z.．]+", span.text.strip())
        )
    ), key=lambda item: (item.box[0], item.center_y))
    for start, first in enumerate(fragments):
        group = [first]
        for later in fragments[start + 1 :]:
            previous = group[-1]
            gap = later.box[0] - previous.box[2]
            if gap > height * 0.35:
                break
            if (gap < -height * 0.2
                    or abs(later.center_y - previous.center_y) > height * 0.35):
                continue
            if sum(len(item.text.strip()) for item in (*group, later)) > 12:
                break
            group.append(later)
            value = "".join(item.text.strip() for item in group)
            tokens = _direction_tokens(value)
            if tokens:
                box = (
                    min(item.box[0] for item in group),
                    min(item.box[1] for item in group),
                    max(item.box[2] for item in group),
                    max(item.box[3] for item in group),
                )
                span = TextSpan(value, box, min(item.confidence for item in group))
                found.append(_DirectionReading(
                    span,
                    tokens,
                    tuple(_DirectionSource(item, 0, len(item.text)) for item in group),
                ))
    return tuple(found)


def _row_direction_distance(
    row: MusicRow,
    span: TextSpan,
    *,
    height: float,
    lower_bound: float,
) -> tuple[float, int] | None:
    if not row.barlines:
        return None
    endpoint = max(row.barlines)
    if span.box[1] < row.box[3] - height * 0.25 or span.box[3] > lower_bound:
        return None
    horizontal_gap = max(span.box[0] - endpoint, endpoint - span.box[2], 0)
    if horizontal_gap > height * 1.8:
        return None
    return max(0, span.center_y - row.box[3]) / height + horizontal_gap / height, endpoint


def attach_score_directions(
    rows: tuple[MusicRow, ...],
    spans: tuple[TextSpan, ...],
    *,
    page_height: int | None = None,
) -> tuple[tuple[MusicRow, ...], tuple[_DirectionSource, ...]]:
    """Attach exact D.S., D.C. and Fine readings to their nearest terminal barline."""
    if not rows:
        return rows, ()
    heights = tuple(
        note.box[3] - note.box[1]
        for row in rows
        for note in row.notes
        if note.box[3] > note.box[1]
    )
    height = median(heights) if heights else 1.0
    candidates = _direction_spans(spans, height)
    attached: list[list[tuple[float, int, str]]] = [[] for _ in rows]
    consumed: set[_DirectionSource] = set()
    for reading in candidates:
        span = reading.span
        owners = []
        for index, row in enumerate(rows):
            lower_rows = [
                other.box[1] for other_index, other in enumerate(rows)
                if other_index != index and other.box[1] >= row.box[3] - height * 0.25
                and other.box[0] < span.box[2] + height
                and other.box[2] > span.box[0] - height
            ]
            page_bound = page_height if page_height is not None else row.box[3] + height * 5
            lower_bound = min(lower_rows, default=page_bound) - height * 0.2
            lower_bound = max(row.box[3], lower_bound)
            distance = _row_direction_distance(
                row, span, height=height, lower_bound=lower_bound,
            )
            if distance is not None:
                owners.append((distance[0], index, distance[1]))
        if not owners:
            continue
        _, owner, endpoint = min(owners)
        attached[owner].extend(
            (span.center_y, endpoint, token) for token in reading.tokens
        )
        consumed.update(reading.sources)

    updated = []
    for row, marks in zip(rows, attached, strict=True):
        existing = list(row.score_directions)
        existing.extend(
            (endpoint, token)
            for _, endpoint, token in sorted(marks)
            if (endpoint, token) not in existing
        )
        updated.append(replace(row, score_directions=tuple(existing)))
    return tuple(updated), tuple(sorted(
        consumed, key=lambda item: (item.span.box, item.start, item.end),
    ))


def remove_attached_direction_text(
    spans: tuple[TextSpan, ...], sources: tuple[_DirectionSource, ...],
) -> tuple[TextSpan, ...]:
    """Remove only accepted direction characters, keeping positioned lyric text."""
    ranges: dict[TextSpan, list[tuple[int, int]]] = {}
    for source in sources:
        ranges.setdefault(source.span, []).append((source.start, source.end))
    retained = []
    for span in spans:
        consumed = sorted(set(ranges.get(span, ())))
        projected = []
        if not consumed:
            centers = _character_centers(span)
            for source in sources:
                source_text = source.span.text[source.start:source.end]
                source_tokens = _direction_tokens(source_text)
                if not any(token in {"ds", "dc."} for token in source_tokens):
                    continue
                for match in _DIRECTION_PATTERN.finditer(span.text):
                    match_tokens = _direction_tokens(match.group())
                    if (len(match_tokens) != 1 or match_tokens[0] not in {"ds", "dc."}
                            or match_tokens[0] not in source_tokens):
                        continue
                    start, end = match.span()
                    left = (round((centers[start - 1] + centers[start]) / 2)
                            if start else span.box[0])
                    right = (round((centers[end - 1] + centers[end]) / 2)
                             if end < len(centers) else span.box[2])
                    overlap = max(0, min(right, source.span.box[2])
                                  - max(left, source.span.box[0]))
                    if overlap >= (right - left) * 0.5:
                        projected.append((start, end))
            consumed = sorted(set(projected))
        if not consumed:
            retained.append(span)
            continue
        if len(span.character_centers) != len(span.text):
            span = replace(span, character_centers=_character_centers(span))
        merged: list[list[int]] = []
        for start, end in consumed:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        if len(span.character_centers) != len(span.text):
            if merged[0][0] == 0 and merged[-1][1] == len(span.text):
                continue
            retained.append(span)
            continue
        cursor = 0
        for start, end in merged:
            if cursor < start:
                residual = _text_slice(span, cursor, start)
                if residual is not None:
                    retained.append(residual)
            cursor = end
        if cursor < len(span.text):
            residual = _text_slice(span, cursor, len(span.text))
            if residual is not None:
                retained.append(residual)
    return tuple(retained)


def _text_slice(span: TextSpan, start: int, end: int) -> TextSpan | None:
    while start < end and span.text[start].isspace():
        start += 1
    while start < end and span.text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    centers = span.character_centers
    left = span.box[0] if start == 0 else round((centers[start - 1] + centers[start]) / 2)
    right = span.box[2] if end == len(centers) else round((centers[end - 1] + centers[end]) / 2)
    return TextSpan(
        span.text[start:end], (left, span.box[1], right, span.box[3]), span.confidence,
        centers[start:end], span.lyric_baselines,
        span.character_boxes[start:end]
        if len(span.character_boxes) == len(span.text) else (),
    )


def _character_centers(span: TextSpan) -> tuple[float, ...]:
    """Estimate positioned characters for word-level OCR using script widths."""
    if len(span.character_centers) == len(span.text):
        return span.character_centers
    weights = tuple(
        1.0 if unicodedata.east_asian_width(character) in {"W", "F"} else
        0.55 if character.isalnum() else 0.35
        for character in span.text
    )
    total = sum(weights)
    if not total:
        return ()
    width = span.box[2] - span.box[0]
    position = 0.0
    centers = []
    for weight in weights:
        centers.append(span.box[0] + width * (position + weight / 2) / total)
        position += weight
    return tuple(centers)
