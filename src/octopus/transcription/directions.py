"""Recognize score-navigation words and attach them to row-ending barlines."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from statistics import median

from .image import MusicRow
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


def _direction_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    if not re.fullmatch(r"[a-z.\s]+", normalized):
        return ()
    letters = re.sub(r"[.\s]+", "", normalized)
    return _DIRECTION_CODES.get(letters, ())


def _embedded_direction_spans(
    span: TextSpan,
) -> tuple[tuple[TextSpan, tuple[str, ...]], ...]:
    """Isolate a direction beside lyric text when OCR returned character centers."""
    if len(span.character_centers) != len(span.text):
        return ()
    normalized = unicodedata.normalize("NFKC", span.text)
    if len(normalized) != len(span.text):
        return ()
    found = []
    centers = span.character_centers
    for match in _DIRECTION_PATTERN.finditer(normalized):
        tokens = _direction_tokens(match.group())
        if not tokens:
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
        found.append(
            (
                TextSpan(
                    match.group(),
                    (left, span.box[1], right, span.box[3]),
                    span.confidence,
                ),
                tokens,
            )
        )
    return tuple(found)


def _direction_spans(
    spans: tuple[TextSpan, ...],
    height: float,
) -> tuple[tuple[TextSpan, tuple[str, ...], tuple[TextSpan, ...]], ...]:
    """Keep exact OCR words and rejoin adjacent OCR fragments such as ``D.`` + ``S.``."""
    ordered = tuple(sorted(set(spans), key=lambda item: (item.center_y, item.box[0])))
    found: list[tuple[TextSpan, tuple[str, ...], tuple[TextSpan, ...]]] = []
    for span in ordered:
        if span.confidence < MIN_TEXT_SPAN_CONFIDENCE:
            continue
        tokens = _direction_tokens(span.text)
        if tokens:
            found.append((span, tokens, (span,)))
        else:
            found.extend(
                (candidate, candidate_tokens, ())
                for candidate, candidate_tokens in _embedded_direction_spans(span)
            )
    fragments = [
        span
        for span in ordered
        if (
            span.confidence >= MIN_TEXT_SPAN_CONFIDENCE
            and re.fullmatch(r"[A-Za-z.．]+", span.text.strip())
        )
    ]
    for start, first in enumerate(fragments):
        group = [first]
        for later in fragments[start + 1 : start + 4]:
            previous = group[-1]
            gap = later.box[0] - previous.box[2]
            if (
                gap > height * 0.35
                or gap < -height * 0.2
                or abs(later.center_y - previous.center_y) > height * 0.35
                or sum(len(item.text.strip()) for item in (*group, later)) > 12
            ):
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
                found.append((span, tokens, tuple(group)))
    return tuple(found)


def _row_direction_distance(
    row: MusicRow,
    span: TextSpan,
    *,
    height: float,
) -> tuple[float, int] | None:
    if not row.barlines:
        return None
    endpoint = max(row.barlines)
    below = span.center_y - row.box[3]
    if not -height * 0.25 <= below <= height * 2.8:
        return None
    horizontal_gap = max(span.box[0] - endpoint, endpoint - span.box[2], 0)
    if horizontal_gap > height * 1.8:
        return None
    return max(0, below) / height + horizontal_gap / height, endpoint


def attach_score_directions(
    rows: tuple[MusicRow, ...],
    spans: tuple[TextSpan, ...],
) -> tuple[tuple[MusicRow, ...], tuple[TextSpan, ...]]:
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
    consumed: set[TextSpan] = set()
    for span, tokens, source_spans in candidates:
        owners = [
            (distance[0], index, distance[1])
            for index, row in enumerate(rows)
            if (distance := _row_direction_distance(row, span, height=height))
            is not None
        ]
        if not owners:
            continue
        _, owner, endpoint = min(owners)
        attached[owner].extend((span.center_y, endpoint, token) for token in tokens)
        consumed.update(source_spans)

    updated = []
    for row, marks in zip(rows, attached, strict=True):
        existing = list(row.score_directions)
        existing.extend(
            (endpoint, token)
            for _, endpoint, token in sorted(marks)
            if (endpoint, token) not in existing
        )
        updated.append(replace(row, score_directions=tuple(existing)))
    return tuple(updated), tuple(span for span in spans if span in consumed)
