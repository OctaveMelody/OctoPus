"""Pure source-line and lyric-profile selection policies for layout."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence

from re_tomato.normalization.types import LyricLineModel, MusicEvent
from re_tomato.parser.ast import LyricTokenKind, MusicTokenKind
from re_tomato.render.core.layout_types import LayoutEvent


def source_line_groups(events: Sequence[MusicEvent]) -> list[list[MusicEvent]]:
    groups: list[list[MusicEvent]] = []
    current: list[MusicEvent] = []
    current_line: int | None = None
    for event in events:
        event_line = event.span.start.line
        if current and current_line != event_line:
            groups.append(current)
            current = []
        current.append(event)
        current_line = event_line
    if current:
        groups.append(current)
    return groups


def associate_lyrics(
    music_line_numbers: Sequence[int],
    lyrics: Sequence[LyricLineModel],
    *,
    allow_leading: bool = False,
) -> dict[int, list[LyricLineModel]]:
    result: dict[int, list[LyricLineModel]] = {}
    music_lines = sorted(set(music_line_numbers))

    # A voice may be declared after its lyric line in the source (the common
    # Q2-Q4 shape in the choir corpus).  Callers opt into this source-topology
    # rule only when the lyrics are already owned by that explicit voice.  The
    # default remains preceding-only for system-wide and legacy associations.
    if allow_leading and len(music_lines) == 1:
        result[music_lines[0]] = list(lyrics)
        return result

    for lyric in lyrics:
        preceding = [line for line in music_lines if line < lyric.span.start.line]
        if preceding:
            result.setdefault(preceding[-1], []).append(lyric)
            continue
        # Preserve the preceding-line rule whenever possible.  If a lyric
        # precedes every music line, attach it to the nearest following line
        # rather than silently dropping it; this handles source blocks where
        # lyric declarations are emitted before a repeated/multi-line voice.
        following = [line for line in music_lines if line > lyric.span.start.line]
        if allow_leading and following:
            result.setdefault(following[0], []).append(lyric)
    return result


def legacy_intrinsic_source_lines(
    lyrics_by_music_line: dict[int, list[LyricLineModel]],
) -> frozenset[int]:
    result: set[int] = set()
    for source_line, lyric_lines in lyrics_by_music_line.items():
        visible_lines = [line for line in lyric_lines if line.tokens]
        if visible_lines and all(is_supported_legacy_lyric_line(line) for line in visible_lines):
            result.add(source_line)
    return frozenset(result)


def numbered_lyric_source_lines(
    lyrics_by_music_line: dict[int, list[LyricLineModel]],
) -> frozenset[int]:
    return frozenset(
        source_line
        for source_line, lyric_lines in lyrics_by_music_line.items()
        if len(lyric_lines) >= 2
        and any(
            token.kind == LyricTokenKind.ANNOTATION
            and (label := token.raw.strip('"')).endswith(".")
            and label[:-1].isdigit()
            for line in lyric_lines
            for token in line.tokens
        )
        and any(
            token.kind == LyricTokenKind.TEXT
            and any(
                unicodedata.east_asian_width(character) in {"W", "F"}
                for character in token.raw
            )
            for line in lyric_lines
            for token in line.tokens
        )
    )


def include_interior_music_source_lines(
    lyric_source_lines: frozenset[int],
    events: Sequence[LayoutEvent],
    *,
    include_lyricless: bool = False,
) -> frozenset[int]:
    if not lyric_source_lines:
        source_lines = {item.event.span.start.line for item in events}
        if include_lyricless:
            return frozenset(source_lines)
        if (
            events
            and events[0].event.duration_slashes
            and "zkh" in events[0].event.decorations
            and any(
                "ykh" in item.event.decorations
                and item.event.span.start.line != events[0].event.span.start.line
                for item in events
            )
        ):
            return frozenset(source_lines)
        if (
            len(source_lines) == 1
            and events
            and (
                "zkh" in events[0].event.decorations
                or (
                    any("zkh" in item.event.decorations for item in events)
                    and any("ykh" in item.event.decorations for item in events)
                )
            )
        ):
            return frozenset(source_lines)
        return lyric_source_lines
    if len(lyric_source_lines) < 2:
        if not include_lyricless:
            preceding_lines = {
                item.event.span.start.line
                for item in events
                if item.event.span.start.line < min(lyric_source_lines)
            }
            if preceding_lines:
                pickup_line = max(preceding_lines)
                first_pickup_event = next(
                    item.event
                    for item in events
                    if item.event.span.start.line == pickup_line
                )
                if "zkh" in first_pickup_event.decorations:
                    return lyric_source_lines | {pickup_line}
            return lyric_source_lines
        first_line = min(lyric_source_lines)
        return lyric_source_lines | {
            item.event.span.start.line
            for item in events
            if item.event.span.start.line < first_line
        }
    first_line = min(lyric_source_lines)
    last_line = max(lyric_source_lines)
    interior_lines = {
        item.event.span.start.line
        for item in events
        if first_line < item.event.span.start.line < last_line
    }
    preceding_lines = {
        item.event.span.start.line
        for item in events
        if item.event.span.start.line < first_line
    }
    leading_pickup_lines: set[int] = set()
    if include_lyricless:
        leading_pickup_lines.update(preceding_lines)
    elif preceding_lines:
        pickup_line = max(preceding_lines)
        first_pickup_event = next(
            item.event
            for item in events
            if item.event.span.start.line == pickup_line
        )
        if "zkh" in first_pickup_event.decorations:
            leading_pickup_lines.add(pickup_line)
    return lyric_source_lines | interior_lines | leading_pickup_lines


def include_terminal_hidden_rest_source_lines(
    source_lines: frozenset[int],
    events: Sequence[LayoutEvent],
    lyrics_by_music_line: Mapping[int, Sequence[LyricLineModel]],
) -> frozenset[int]:
    """Admit lyricless rows ending in a visible hidden-rest sentinel to the intrinsic path."""
    events_by_source_line: dict[int, list[LayoutEvent]] = {}
    for item in events:
        events_by_source_line.setdefault(item.event.span.start.line, []).append(item)

    result = set(source_lines)
    for source_line, row in events_by_source_line.items():
        if source_line in result or len(row) < 2:
            continue
        if any(line.tokens for line in lyrics_by_music_line.get(source_line, ())):
            continue
        terminal, closing = row[-2:]
        if (
            terminal.event.kind == MusicTokenKind.HIDDEN_REST
            and terminal.event.pitch == 8
            and terminal.event.duration is None
            and "ykh" in terminal.event.decorations
            and closing.event.kind == MusicTokenKind.BARLINE
            and closing.event.code == "|"
        ):
            result.add(source_line)
    return frozenset(result)


def include_trailing_cross_row_hook_source_lines(
    source_lines: frozenset[int],
    events: Sequence[LayoutEvent],
) -> frozenset[int]:
    if not source_lines:
        return source_lines
    events_by_source_line: dict[int, list[LayoutEvent]] = {}
    for item in events:
        events_by_source_line.setdefault(item.event.span.start.line, []).append(item)
    ordered_lines = sorted(events_by_source_line)
    result = set(source_lines)
    for opener_line in sorted(source_lines):
        opener_events = events_by_source_line.get(opener_line, [])
        if not any("zkh" in item.event.decorations for item in opener_events):
            continue
        if any("ykh" in item.event.decorations for item in opener_events):
            continue
        closer_line = next(
            (
                line
                for line in ordered_lines
                if line > opener_line
                and any(
                    "ykh" in item.event.decorations
                    and item.event.kind in {MusicTokenKind.EXTENSION, MusicTokenKind.HIDDEN_REST}
                    for item in events_by_source_line[line]
                )
            ),
            None,
        )
        if closer_line is not None:
            result.update(line for line in ordered_lines if opener_line < line <= closer_line)
    return frozenset(result)


def is_supported_legacy_lyric_line(line: LyricLineModel) -> bool:
    text_tokens = [token for token in line.tokens if token.kind == LyricTokenKind.TEXT]
    return bool(text_tokens) and all(
        token.raw.isascii()
        or (
            len(token.raw) == 1
            and unicodedata.east_asian_width(token.raw) in {"W", "F"}
        )
        for token in text_tokens
    )


def fixed_lyric_connector_positions(
    row: Sequence[LayoutEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> frozenset[int]:
    result: set[int] = set()
    for index, item in enumerate(row[:-1]):
        if index == 0 or row[index + 1].event.kind != MusicTokenKind.BARLINE:
            continue
        previous = row[index - 1]
        texts = lyric_text_by_event.get((previous.event.span.start.line, previous.event.index), ())
        if (
            item.event.duration_dots
            and ")" in item.event.code
            and "(" in previous.event.code
            and len(texts) >= 2
            and all(text.endswith(("，", "。", "！", "？", "、", "；", "：")) for text in texts)
        ):
            result.add(index)
    return frozenset(result)


__all__ = [
    "associate_lyrics",
    "fixed_lyric_connector_positions",
    "include_interior_music_source_lines",
    "include_terminal_hidden_rest_source_lines",
    "include_trailing_cross_row_hook_source_lines",
    "is_supported_legacy_lyric_line",
    "legacy_intrinsic_source_lines",
    "numbered_lyric_source_lines",
    "source_line_groups",
]
