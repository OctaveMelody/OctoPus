"""Lyric placement leaf helpers (split from ``lyrics.py``, item: R5.5 prep).

Pure token-walk support for :func:`lyrics._layout_lyric_line`: skip/attach
predicates, punctuation geometry, and the LayoutLyric constructors it uses.
This module is deliberately a leaf — it imports nothing from ``lyrics`` so
the orchestration (association, legacy text/gap measurement, the placement
walk itself) can grow there without circularity. The split is a pure move:
no behavior change; corpus parity gates cover it.
"""

from __future__ import annotations

from ....model.model_normalize import MusicEvent
from ....parser.ast import LyricTokenKind, MusicTokenKind
from ....parser.source import SourceSpan
from ...core.layout_types import LayoutEvent, LayoutLyric, LayoutPage, PageMetrics
from ..visibility import (
    is_bz_placeholder_event as _is_bz_placeholder_event,
)
from ..visibility import (
    is_dsb_placeholder_event as _is_dsb_placeholder_event,
)
from ..visibility import (
    is_synthetic_hidden_rest_placeholder as _is_synthetic_hidden_rest_placeholder,
)


def _append_empty_lyric_placeholders(
    layout: LayoutPage,
    events: list[LayoutEvent],
    verse: int,
    y: float,
) -> None:
    for current_event in events:
        if not _event_accepts_empty_lyric_placeholder(current_event):
            continue
        layout.lyrics.append(
            LayoutLyric(
                text="",
                x=_lyric_anchor_x(current_event, layout.metrics),
                y=y
                + layout.metrics.lyric_offset_y
                + (verse - 1) * layout.metrics.lyric_line_spacing,
                cipos=current_event.address.notepos,
                verse=verse,
                voice=current_event.voice,
                line=current_event.line,
                slot=current_event.slot,
            )
        )

def _event_accepts_empty_lyric_placeholder(event: LayoutEvent) -> bool:
    return not _is_implicit_hidden_placeholder(event.event)

def _skip_bare_hidden_rests(events: list[LayoutEvent], event_index: int) -> int:
    while event_index < len(events) and _is_bare_hidden_rest(events[event_index].event):
        event_index += 1
    return event_index

def _skip_implicit_hidden_placeholders(
    events: list[LayoutEvent],
    event_index: int,
) -> int:
    while (
        event_index < len(events)
        and _is_implicit_hidden_placeholder(events[event_index].event)
    ):
        event_index += 1
    return event_index

def _is_implicit_hidden_placeholder(event: MusicEvent) -> bool:
    return (
        _is_bz_placeholder_event(event)
        or _is_dsb_placeholder_event(event)
        or _is_synthetic_hidden_rest_placeholder(event)
    )

def _is_bare_hidden_rest(event: MusicEvent) -> bool:
    return event.kind == MusicTokenKind.HIDDEN_REST and event.raw == "8"

def _punctuation_attaches_to_lyric(
    raw: str,
    lyric: LayoutLyric | None,
    previous_alignment_kind: LyricTokenKind | None,
) -> bool:
    if previous_alignment_kind == LyricTokenKind.EXTEND:
        return lyric is not None
    if raw in {")", "）"}:
        return False
    if raw == "'":
        return lyric is not None
    # Every other punctuation mark renders as its own element after the
    # syllable unless a ``~`` (EXTEND) joined it to the preceding text.
    return False


def _floating_punctuation_x(text: str, punct: str, metrics: PageMetrics) -> float:
    """Reference placement of a punctuation mark rendered after a syllable.

    Oracle-verified 2026-08-23 (probed at geci_size 14/16/18/20): the mark
    sits ``sum(char widths) + mark width`` past the syllable's x, where an
    ASCII char is ``size / 4``, a wide char is ``size / 2``, and the mark
    itself is ``size / 2`` plus 3 when it is narrow (ASCII) punctuation.
    Single-wide-char cases collapse to the legacy ``x + size`` placement.
    """
    size = metrics.lyric_size
    width = sum(size / 4 if char.isascii() else size / 2 for char in text)
    mark = size / 2 + 3 if punct.isascii() else size / 2
    return width + mark


def _text_gets_leading_space(
    raw: str,
    previous_alignment_kind: LyricTokenKind | None,
) -> bool:
    return (
        raw.isascii()
        and raw in {"a", "am", "morn-", "take"}
        and previous_alignment_kind in {LyricTokenKind.TEXT, LyricTokenKind.PUNCTUATION}
    )

def _text_attaches_to_previous_ascii_lyric(
    raw: str,
    lyric: LayoutLyric | None,
    previous_alignment_kind: LyricTokenKind | None,
    tokens: tuple[object, ...],
    token_index: int,
) -> bool:
    return bool(
        lyric is not None
        and raw.isascii()
        and lyric.text.isascii()
        and previous_alignment_kind == LyricTokenKind.TEXT
        and _next_tokens_start_contraction(tokens, token_index)
    )

def _next_tokens_start_contraction(tokens: tuple[object, ...], token_index: int) -> bool:
    if token_index + 2 >= len(tokens):
        return False
    return (
        getattr(tokens[token_index + 1], "kind", None) == LyricTokenKind.EXTEND
        and getattr(tokens[token_index + 2], "kind", None) == LyricTokenKind.PUNCTUATION
        and getattr(tokens[token_index + 2], "raw", None) == "'"
    )

def _next_token_is_extend(tokens: tuple[object, ...], token_index: int) -> bool:
    next_index = token_index + 1
    if next_index >= len(tokens):
        return False
    token = tokens[next_index]
    return getattr(token, "kind", None) == LyricTokenKind.EXTEND

def _aligned_punctuation_lyric(
    layout: LayoutPage,
    text: str,
    current_event: LayoutEvent,
    verse: int,
    y: float,
    source_span: SourceSpan | None = None,
) -> LayoutLyric:
    return LayoutLyric(
        text=text,
        x=_lyric_anchor_x(current_event, layout.metrics),
        y=y
        + layout.metrics.lyric_offset_y
        + (verse - 1) * layout.metrics.lyric_line_spacing,
        cipos=current_event.address.notepos,
        verse=verse,
        voice=current_event.voice,
        line=current_event.line,
        slot=current_event.slot,
        source_spans=(source_span,) if source_span is not None else (),
    )

def _lyric_anchor_x(event: LayoutEvent, metrics: PageMetrics) -> float:
    """Center a middle-anchored lyric using the configured lyric size."""
    return event.x - metrics.lyric_size / 2
