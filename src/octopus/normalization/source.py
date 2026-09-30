"""Preserve source metadata and formatting helpers during model normalization."""

from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from octopus.normalization.types import IgnoredTextModel
from octopus.parser.ast import MusicLine, MusicTokenKind, ScoreDocument
from octopus.parser.source import SourceSpan


def combine_spans(start: SourceSpan | None, end: SourceSpan | None) -> SourceSpan | None:
    if start is None or end is None:
        return start or end
    return SourceSpan(start.start, end.end)


def source_key_from_path(source_path: str | None) -> str | None:
    if source_path is None:
        return None
    return jps_key(Path(source_path).name)


def jps_key(filename: str) -> str:
    while filename.casefold().endswith(".jps"):
        filename = filename[:-4]
    return filename.strip()


def collect_ignored_text(
    document: ScoreDocument,
) -> tuple[IgnoredTextModel, ...]:
    ignored: list[IgnoredTextModel] = []
    for line in document.lines:
        if not isinstance(line, MusicLine):
            continue
        for token in line.tokens:
            if token.kind != MusicTokenKind.IGNORED_TEXT:
                continue
            ignored.append(
                IgnoredTextModel(
                    identifier=None,
                    voice=line.voice,
                    line=token.span.start.line,
                    raw=token.raw,
                    span=token.span,
                )
            )
    return tuple(ignored)


def fraction_to_text(value: Fraction) -> str:
    remainder = value.denominator
    for factor in (2, 5):
        while remainder % factor == 0:
            remainder //= factor
    if remainder != 1:
        return format(float(value), ".2f")
    with localcontext() as context:
        context.prec = 50
        decimal = Decimal(value.numerator) / Decimal(value.denominator)
        text = format(decimal.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
