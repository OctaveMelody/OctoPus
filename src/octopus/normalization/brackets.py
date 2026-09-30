"""Document-level repeat-ending topology reconciliation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from octopus.normalization.types import MusicEvent, SemanticConstruct
from octopus.parser.ast import LineNode, MusicLine, MusicToken, MusicTokenKind
from octopus.parser.source import SourceSpan


class MutableVoiceBuilder(Protocol):
    events: list[MusicEvent]
    constructs: list[SemanticConstruct]


class SystemBuilderView(Protocol):
    @property
    def voices(self) -> Mapping[int, MutableVoiceBuilder]: ...


class PageBuilderView(Protocol):
    @property
    def systems(self) -> Sequence[SystemBuilderView]: ...


AnnotateConstructRoles = Callable[
    [list[MusicEvent], list[SemanticConstruct]],
    list[MusicEvent],
]


def reconcile_document_brackets(
    pages: Sequence[PageBuilderView],
    lines: Sequence[LineNode],
    annotate_construct_roles: AnnotateConstructRoles,
) -> None:
    """Pair repeat endings across system/page boundaries and project local segments."""

    pairs_by_voice: dict[
        int, list[tuple[MusicToken, MusicToken, int, str, int, bool]]
    ] = {}
    stacks: dict[int, list[MusicToken]] = {}
    token_streams: dict[int, list[MusicToken]] = {}
    pair_number = 0
    for line in lines:
        if not isinstance(line, MusicLine):
            continue
        stack = stacks.setdefault(line.voice, [])
        stream = token_streams.setdefault(line.voice, [])
        for token_index, token in enumerate(line.tokens):
            if token.kind == MusicTokenKind.BRACKET_START:
                stack.append(token)
            elif token.kind == MusicTokenKind.BRACKET_END and stack:
                opener = stack.pop()
                pair_number += 1
                opener_index = next(
                    index
                    for index in range(len(stream) - 1, -1, -1)
                    if stream[index] is opener
                )
                following = (
                    line.tokens[token_index + 1]
                    if token_index + 1 < len(line.tokens)
                    else None
                )
                slash_after_closer = bool(
                    following
                    and following.kind == MusicTokenKind.MODIFIER
                    and following.raw == "/"
                )
                pairs_by_voice.setdefault(line.voice, []).append(
                    (
                        opener,
                        token,
                        pair_number,
                        "".join(item.raw for item in stream[opener_index:]) + token.raw,
                        leading_bracket_plus_count(tuple(stream), opener_index, len(stream)),
                        not slash_after_closer,
                    )
                )
            stream.append(token)

    builders_by_voice: dict[int, list[MutableVoiceBuilder]] = {}
    for page in pages:
        for system in page.systems:
            for voice_number, voice in system.voices.items():
                builders_by_voice.setdefault(voice_number, []).append(voice)

    for voice_number, pairs in pairs_by_voice.items():
        builders = builders_by_voice.get(voice_number, [])
        recognized_spans = {
            (construct.source_span.start.offset, construct.source_span.end.offset)
            for voice in builders
            for construct in voice.constructs
            if construct.kind == "bracket"
        }
        for voice in builders:
            voice.constructs = [
                construct for construct in voice.constructs if construct.kind != "bracket"
            ]
        all_events = sorted(
            (event for voice in builders for event in voice.events),
            key=lambda event: event.span.start.offset,
        )
        visible_events = [event for event in all_events if _is_visible_music_event(event)]
        for opener, closer, ordinal, source_text, plus_count, explicit_close in pairs:
            _project_document_bracket(
                builders,
                visible_events,
                opener,
                closer,
                ordinal,
                source_text,
                plus_count,
                (opener.span.start.offset, closer.span.end.offset) in recognized_spans,
                explicit_close,
            )
        for voice in builders:
            voice.events = annotate_construct_roles(voice.events, voice.constructs)


def _project_document_bracket(
    builders: list[MutableVoiceBuilder],
    visible_events: list[MusicEvent],
    opener: MusicToken,
    closer: MusicToken,
    ordinal: int,
    source_text: str,
    plus_count: int,
    reserves_clearance: bool,
    explicit_close: bool = True,
) -> None:
    opener_offset = opener.span.start.offset
    closer_offset = closer.span.end.offset
    inside = [
        event
        for event in visible_events
        if opener_offset <= event.span.start.offset < closer_offset
    ]
    if opener.attached_to_previous:
        previous = next(
            (
                event
                for event in reversed(visible_events)
                if event.span.end.offset <= opener_offset
            ),
            None,
        )
        if previous is not None:
            inside.insert(0, previous)
    if not inside:
        return

    construct_id = f"document:bracket:{ordinal}"
    source_span = SourceSpan(opener.span.start, closer.span.end)
    owner_by_event_id = {
        id(event): voice for voice in builders for event in voice.events
    }
    by_builder: dict[int, list[MusicEvent]] = {}
    for event in inside:
        owner = owner_by_event_id.get(id(event))
        if owner is not None:
            by_builder.setdefault(id(owner), []).append(event)

    for voice in builders:
        segment = by_builder.get(id(voice), [])
        if not segment:
            continue
        # A bracket that spans several source lines inside one system is
        # projected as one segment per line, mirroring the cross-system case
        # (corpus-verified: Horizon p1 draws a per-line segment for each of
        # its two bracket lines; wrapped rows of one source line stay a
        # single segment anchored at the first row, As-Wished - Choir p2).
        line_segments: list[list[MusicEvent]] = []
        for event in segment:
            if (
                not line_segments
                or line_segments[-1][-1].span.start.line != event.span.start.line
            ):
                line_segments.append([event])
            else:
                line_segments[-1].append(event)
        for sub_segment in line_segments:
            is_first_segment = sub_segment[0] is inside[0]
            is_last_segment = sub_segment[-1] is inside[-1]
            start = sub_segment[0]
            end = sub_segment[-1]
            roles = tuple(
                (
                    event.index,
                    "start"
                    if event is start
                    else "end" if event is end else "inside",
                )
                for event in sub_segment
            )
            voice.constructs.append(
                SemanticConstruct(
                    construct_id=construct_id,
                    kind="bracket",
                    source_span=source_span,
                    start_event_index=start.index,
                    end_event_index=end.index,
                    event_indices=tuple(event.index for event in sub_segment),
                    source_text=source_text,
                    role_by_event_index=roles,
                    ending_plus_count=plus_count,
                    ending_is_first_segment=is_first_segment,
                    ending_is_last_segment=is_last_segment,
                    ending_explicit_close=explicit_close,
                    ending_reserves_clearance=reserves_clearance,
                )
            )


def leading_bracket_plus_count(
    tokens: tuple[MusicToken, ...],
    opener_index: int,
    closer_index: int,
) -> int:
    """Count leading repeat-ending modifiers before its first visible event."""

    count = 0
    for token in tokens[opener_index + 1 : closer_index]:
        if is_visible_music_token(token):
            break
        if token.kind == MusicTokenKind.MODIFIER:
            count += token.raw.count("+")
    return count


def _is_visible_music_event(event: MusicEvent) -> bool:
    return event.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.BARLINE,
        MusicTokenKind.EXTENSION,
    }


def is_visible_music_token(token: MusicToken) -> bool:
    return token.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.BARLINE,
        MusicTokenKind.EXTENSION,
    }


__all__ = [
    "is_visible_music_token",
    "leading_bracket_plus_count",
    "reconcile_document_brackets",
]
