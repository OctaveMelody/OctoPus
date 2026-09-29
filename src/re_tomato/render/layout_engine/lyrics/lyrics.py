"""Lyric association, normalization, and token alignment."""

from __future__ import annotations

import unicodedata

from re_tomato.normalization.types import LyricLineModel, SystemModel
from re_tomato.parser.ast import LyricTokenKind, MusicTokenKind
from re_tomato.parser.source import SourceSpan
from re_tomato.render.core.layout_types import (
    LayoutEvent,
    LayoutHeader,
    LayoutLyric,
    LayoutPage,
    PageMetrics,
)
from re_tomato.render.layout_engine.annotation_placement import annotation_text as _annotation_text
from re_tomato.render.layout_engine.annotation_placement import (
    fixup_annotation_x as _fixup_annotation_x,
)

from .lyric_selection import associate_lyrics as _associate_lyrics
from .lyrics_placement import (
    _aligned_punctuation_lyric,
    _append_empty_lyric_placeholders,
    _floating_punctuation_x,
    _lyric_anchor_x,
    _next_token_is_extend,
    _punctuation_attaches_to_lyric,
    _skip_bare_hidden_rests,
    _skip_implicit_hidden_placeholders,
    _text_attaches_to_previous_ascii_lyric,
    _text_gets_leading_space,
)


def _layout_lyrics(
    layout: LayoutPage,
    system: SystemModel,
    system_line_start: int,
    system_rows: int,
) -> None:
    by_source_line: dict[int, list[LayoutEvent]] = {}
    for event in layout.events:
        if system_line_start <= event.line < system_line_start + system_rows:
            by_source_line.setdefault(event.event.span.start.line, []).append(event)
    lyric_lines = tuple(
        sorted(
            (lyric for voice in system.voices for lyric in voice.lyrics),
            key=lambda lyric: lyric.span.start.offset,
        )
    )
    associations = _associate_lyrics(system.music_line_numbers, lyric_lines)
    for source_line, lyrics in associations.items():
        line_events = by_source_line.get(source_line, [])
        # The reference anchors every verse of a line to the line's bottom row
        # (the lowest rendered note row, dsb sub-rows included).
        bottom_row_y = max((event.y for event in line_events), default=0.0)
        for lyric_index, lyric_line in enumerate(lyrics, start=1):
            _layout_lyric_line(
                layout,
                lyric_line,
                bottom_row_y,
                lyric_index,
                _lyric_consumable_events(line_events),
            )

def _legacy_lyric_text_by_event(
    metrics: PageMetrics,
    header: LayoutHeader,
    events: list[LayoutEvent],
    lyrics_by_music_line: dict[int, list[LyricLineModel]],
    *,
    append_floating_punctuation: bool = True,
) -> dict[tuple[int, int], tuple[str, ...]]:
    """Map music events to their rendered lyric text.

    ``append_floating_punctuation`` keeps the legacy behaviour of folding a
    punctuation mark that renders as its own element (no ``~`` join) into the
    previous event's stored text — dotted-reserve and cross-row-hook
    predicates rely on seeing it there.  The shared-grid path passes
    ``False``: the reference counts only the syllable's first rendered
    element for spacing, so a floating mark must not inflate the grid's
    lyric overflow (oracle-verified 2026-08-23).
    """
    scratch = LayoutPage(metrics=metrics, header=header)
    event_by_address = {item.address.notepos: item for item in events}
    for source_line, lyric_lines in lyrics_by_music_line.items():
        source_events = _lyric_consumable_events(
            [item for item in events if item.event.span.start.line == source_line]
        )
        for verse, lyric_line in enumerate(lyric_lines, start=1):
            _layout_lyric_line(
                scratch,
                lyric_line,
                0.0,
                verse,
                source_events,
                record_skips=True,
            )

    uses_compact_latin_bilingual_profile = (
        metrics.note_start_x == 53.0
        and metrics.lyric_size == 16
        and any(len(lines) >= 2 for lines in lyrics_by_music_line.values())
        and all(
            unicodedata.east_asian_width(character) not in {"W", "F"}
            for lyric in scratch.lyrics
            for character in lyric.text
        )
    )
    result: dict[tuple[int, int], list[str]] = {}
    previous_key: tuple[int, int] | None = None
    for lyric in scratch.lyrics:
        if lyric.cipos is None or lyric.cipos not in event_by_address:
            if (
                append_floating_punctuation
                and previous_key is not None
                and lyric.text in {",", "，", "。", "！", "？", "、", "；", "："}
            ):
                result[previous_key][-1] += lyric.text
            continue
        event = event_by_address[lyric.cipos].event
        key = (event.span.start.line, event.index)
        if uses_compact_latin_bilingual_profile and lyric.profile_continuation:
            continue
        result.setdefault(key, []).append(lyric.text)
        previous_key = key
    if not uses_compact_latin_bilingual_profile:
        return {key: tuple(texts) for key, texts in result.items()}

    event_position_by_key = {
        (item.event.span.start.line, item.event.index): position
        for position, item in enumerate(events)
    }
    normalized: dict[tuple[int, int], tuple[str, ...]] = {}
    for key, texts in result.items():
        stripped = [text.rstrip(",.!?;:") for text in texts]
        position = event_position_by_key[key]
        next_is_extension = (
            position + 1 < len(events)
            and events[position + 1].event.kind == MusicTokenKind.EXTENSION
        )
        preserve_last_punctuation = (
            next_is_extension
            and len(texts) >= 2
            and texts[-1].endswith((",", ".", "!", "?", ";", ":"))
            and _compact_latin_clearance_units(stripped[-1])
            >= _compact_latin_clearance_units(stripped[0])
        )
        if preserve_last_punctuation:
            stripped[-1] = texts[-1]
        normalized[key] = tuple(
            _normalize_compact_latin_clearance_text(text, original=texts[index])
            for index, text in enumerate(stripped)
        )
    return normalized

def _compact_latin_clearance_units(text: str) -> int:
    return sum(1 if character.isascii() else 2 for character in text)

def _normalize_compact_latin_clearance_text(text: str, *, original: str) -> str:
    normalized = "".join(
        character if character.isascii() else "xx"
        for character in text
    )
    return normalized.ljust(3) if len(original) >= 3 and len(normalized) < 3 else normalized

def _legacy_lyric_gap_by_event(
    metrics: PageMetrics,
    header: LayoutHeader,
    events: list[LayoutEvent],
    lyrics_by_music_line: dict[int, list[LyricLineModel]],
) -> dict[tuple[int, int], int]:
    scratch = LayoutPage(metrics=metrics, header=header)
    event_by_address = {item.address.notepos: item for item in events}
    result: dict[tuple[int, int], int] = {}
    for source_line, lyric_lines in lyrics_by_music_line.items():
        source_events = _lyric_consumable_events(
            [item for item in events if item.event.span.start.line == source_line]
        )
        for verse, lyric_line in enumerate(lyric_lines, start=1):
            rendered_start = len(scratch.lyrics)
            _layout_lyric_line(
                scratch,
                lyric_line,
                0.0,
                verse,
                source_events,
                record_skips=True,
            )
            rendered = scratch.lyrics[rendered_start:]
            rendered_index = 0
            for token_index, token in enumerate(lyric_line.tokens):
                if token.kind != LyricTokenKind.TEXT:
                    continue
                while rendered_index < len(rendered):
                    lyric = rendered[rendered_index]
                    rendered_index += 1
                    if (
                        lyric.cipos is not None
                        and lyric.cipos in event_by_address
                        and token.raw in lyric.text
                    ):
                        break
                else:
                    continue
                next_offset = (
                    lyric_line.tokens[token_index + 1].span.start.offset
                    if token_index + 1 < len(lyric_line.tokens)
                    else lyric_line.span.end.offset
                )
                gap = next_offset - token.span.end.offset
                if gap <= 0:
                    continue
                event = event_by_address[lyric.cipos].event
                key = (event.span.start.line, event.index)
                result[key] = max(result.get(key, 0), gap)
    return result

def _lyric_consumable_events(events: list[LayoutEvent]) -> list[LayoutEvent]:
    return [
        event
        for event in events
        if event.event.kind not in {MusicTokenKind.BARLINE, MusicTokenKind.EXTENSION}
    ]

def _layout_lyric_line(
    layout: LayoutPage,
    lyric_line: LyricLineModel,
    y: float,
    verse: int,
    events: list[LayoutEvent],
    *,
    record_skips: bool = False,
) -> None:
    """Place one lyric line's tokens onto its host events, in order.

    Walks lyric tokens and layout events together, handling skips, prefix/suffix
    attachments, and the empty-line placeholder path; REF ordering is load-bearing."""
    if not lyric_line.tokens:
        _append_empty_lyric_placeholders(layout, events, verse, y)
        return

    event_index = 0
    token_index = 0
    pending_prefix = ""
    pending_prefix_spans: list[SourceSpan] = []
    last_lyric: LayoutLyric | None = None
    attach_next_text = False
    previous_alignment_kind: LyricTokenKind | None = None
    annotations: list[LayoutLyric] = []
    while token_index < len(lyric_line.tokens):
        token = lyric_line.tokens[token_index]
        if token.kind == LyricTokenKind.SKIP:
            event_index = _skip_implicit_hidden_placeholders(events, event_index)
            if record_skips and event_index < len(events):
                current_event = events[event_index]
                layout.lyrics.append(
                    LayoutLyric(
                        text="",
                        x=_lyric_anchor_x(current_event, layout.metrics),
                        y=y,
                        cipos=current_event.address.notepos,
                        verse=verse,
                        voice=current_event.voice,
                        line=current_event.line,
                        slot=current_event.slot,
                    )
                )
            event_index += 1
            token_index += 1
            attach_next_text = False
            previous_alignment_kind = token.kind
            continue
        if token.kind == LyricTokenKind.SEPARATOR:
            token_index += 1
            attach_next_text = False
            previous_alignment_kind = token.kind
            continue
        if token.kind == LyricTokenKind.EXTEND:
            token_index += 1
            attach_next_text = True
            previous_alignment_kind = token.kind
            continue
        if token.kind == LyricTokenKind.ANNOTATION:
            if event_index < len(events):
                current_event = events[event_index]
                annotation = LayoutLyric(
                        text=_annotation_text(token.raw),
                        x=current_event.x,
                        y=y
                        + layout.metrics.lyric_offset_y
                        + (verse - 1) * layout.metrics.lyric_line_spacing,
                        cipos=None,
                        verse=verse,
                        annotation=True,
                        voice=current_event.voice,
                        line=current_event.line,
                        slot=current_event.slot,
                        anchor_cipos=current_event.address.notepos,
                        source_spans=(token.span,),
                )
                layout.lyrics.append(annotation)
                annotations.append(annotation)
                last_lyric = annotation
            token_index += 1
            attach_next_text = False
            previous_alignment_kind = token.kind
            continue
        if token.kind == LyricTokenKind.PUNCTUATION:
            if token.raw in {"(", "（"}:
                if _next_token_is_extend(lyric_line.tokens, token_index):
                    pending_prefix += token.raw
                    pending_prefix_spans.append(token.span)
                    token_index += 1
                    previous_alignment_kind = token.kind
                    continue
                if event_index < len(events):
                    punctuation = _aligned_punctuation_lyric(
                        layout,
                        token.raw,
                        events[event_index],
                        verse,
                        y,
                        token.span,
                    )
                    layout.lyrics.append(punctuation)
                    last_lyric = punctuation
                    event_index += 1
                token_index += 1
                previous_alignment_kind = token.kind
                continue
            if (
                previous_alignment_kind in {LyricTokenKind.SEPARATOR, LyricTokenKind.SKIP}
                and event_index < len(events)
            ):
                if previous_alignment_kind == LyricTokenKind.SKIP:
                    event_index = _skip_bare_hidden_rests(events, event_index)
                    event_index = _skip_implicit_hidden_placeholders(events, event_index)
                    if event_index >= len(events):
                        break
                punctuation = _aligned_punctuation_lyric(
                    layout,
                    token.raw,
                    events[event_index],
                    verse,
                    y,
                    token.span,
                )
                layout.lyrics.append(punctuation)
                last_lyric = punctuation
                event_index += 1
                token_index += 1
                attach_next_text = False
                previous_alignment_kind = token.kind
                continue
            if (
                _punctuation_attaches_to_lyric(token.raw, last_lyric, previous_alignment_kind)
                and last_lyric is not None
            ):
                last_lyric.text += token.raw
                last_lyric.source_spans += (token.span,)
                token_index += 1
                attach_next_text = False
                previous_alignment_kind = token.kind
                continue
            if token.raw in {")", "）"} and event_index < len(events):
                punctuation = _aligned_punctuation_lyric(
                    layout,
                    token.raw,
                    events[event_index],
                    verse,
                    y,
                    token.span,
                )
                layout.lyrics.append(punctuation)
                last_lyric = punctuation
                event_index += 1
                token_index += 1
                attach_next_text = False
                previous_alignment_kind = token.kind
                continue
            if last_lyric is not None:
                punctuation = LayoutLyric(
                        text=token.raw,
                        x=last_lyric.x + _floating_punctuation_x(
                            last_lyric.text, token.raw, layout.metrics
                        ),
                        y=last_lyric.y,
                        cipos=None,
                        verse=verse,
                        voice=last_lyric.voice,
                        line=last_lyric.line,
                        slot=last_lyric.slot,
                        source_spans=(token.span,),
                )
                layout.lyrics.append(punctuation)
                last_lyric = punctuation
            token_index += 1
            attach_next_text = False
            previous_alignment_kind = token.kind
            continue
        if token.kind != LyricTokenKind.TEXT:
            token_index += 1
            attach_next_text = False
            previous_alignment_kind = token.kind
            continue
        text = token.raw
        if _text_gets_leading_space(token.raw, previous_alignment_kind):
            text = f" {text}"
        if (
            (
                attach_next_text
                or _text_attaches_to_previous_ascii_lyric(
                    token.raw,
                    last_lyric,
                    previous_alignment_kind,
                    lyric_line.tokens,
                    token_index,
                )
            )
            and last_lyric is not None
            and last_lyric.cipos is not None
        ):
            if (
                not attach_next_text
                and last_lyric.text
                and not text.startswith(" ")
                and not last_lyric.text.endswith((" ", "'", "(", "（"))
            ):
                text = f" {text}"
            last_lyric.text += text
            last_lyric.source_spans += (token.span,)
            attach_next_text = False
            previous_alignment_kind = token.kind
            token_index += 1
            continue
        text_parts = [pending_prefix, text]
        pending_prefix = ""
        lookahead = token_index + 1
        event_index = _skip_bare_hidden_rests(events, event_index)
        event_index = _skip_implicit_hidden_placeholders(events, event_index)
        if event_index >= len(events):
            break
        current_event = events[event_index]
        cipos = current_event.address.notepos
        lyric = LayoutLyric(
                text="".join(text_parts),
                x=_lyric_anchor_x(current_event, layout.metrics),
                y=y
                + layout.metrics.lyric_offset_y
                + (verse - 1) * layout.metrics.lyric_line_spacing,
                cipos=cipos,
                verse=verse,
                voice=current_event.voice,
                line=current_event.line,
                slot=current_event.slot,
                profile_continuation=previous_alignment_kind == LyricTokenKind.TEXT,
                source_spans=(*pending_prefix_spans, token.span),
        )
        layout.lyrics.append(lyric)
        last_lyric = lyric
        pending_prefix_spans.clear()
        event_index += 1
        token_index = lookahead
        attach_next_text = False
        previous_alignment_kind = token.kind
    _append_empty_lyric_placeholders(
        layout,
        events[event_index:],
        verse,
        y,
    )
    _fixup_annotation_x(layout, events, verse, annotations)
