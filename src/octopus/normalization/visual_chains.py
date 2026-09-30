"""Topology-based visual endpoint resolution for normalized constructs."""

from __future__ import annotations

from dataclasses import replace

from octopus.normalization import brackets as model_brackets
from octopus.normalization.types import (
    MusicEvent,
    SemanticConstruct,
    SingletonParenthesisProvenance,
)
from octopus.parser.ast import MusicToken, MusicTokenKind
from octopus.parser.source import SourceSpan


def _discarded_singleton_provenance(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    opener_index: int,
    closer_index: int,
    opener_kind: MusicTokenKind,
) -> SingletonParenthesisProvenance | None:
    """Describe a discarded same-event span without creating a construct."""

    if opener_kind != MusicTokenKind.SPAN_START:
        return None
    start = _first_visible_event_index(
        tokens, token_to_event_index, opener_index + 1, closer_index
    )
    end = _previous_visible_event_index(tokens, token_to_event_index, closer_index + 1)
    if start is None or end is None or start != end:
        return None
    opener = tokens[opener_index]
    closer = tokens[closer_index]
    return SingletonParenthesisProvenance(
        source_span=SourceSpan(opener.span.start, closer.span.end),
        source_text="".join(token.raw for token in tokens[opener_index : closer_index + 1]),
        start_event_index=start,
        end_event_index=end,
        preceding_event_index=_previous_visible_event_index(
            tokens, token_to_event_index, opener_index
        ),
    )


def _attach_singleton_provenance(
    constructs: list[SemanticConstruct],
    discarded_singletons: list[SingletonParenthesisProvenance],
) -> list[SemanticConstruct]:
    """Attach discarded singleton spans to their nearest enclosing slur/tie."""

    if not discarded_singletons:
        return constructs
    parents = [
        construct
        for construct in constructs
        if construct.kind in {"tie", "slur"} and not construct.visual_only
    ]
    if not parents:
        return constructs
    provenance_by_id: dict[str, list[SingletonParenthesisProvenance]] = {}
    for singleton in discarded_singletons:
        enclosing = [
            parent
            for parent in parents
            if parent.source_span.start.offset < singleton.source_span.start.offset
            and singleton.source_span.end.offset < parent.source_span.end.offset
            and parent.start_event_index is not None
            and parent.end_event_index is not None
            and parent.start_event_index <= singleton.start_event_index
            and singleton.end_event_index <= parent.end_event_index
        ]
        if not enclosing:
            continue
        parent = min(
            enclosing,
            key=lambda candidate: (
                candidate.source_span.end.offset - candidate.source_span.start.offset,
                candidate.source_span.start.offset,
            ),
        )
        provenance_by_id.setdefault(parent.construct_id, []).append(singleton)
    return [
        replace(
            construct,
            singleton_parenthesis_provenance=tuple(
                provenance_by_id.get(construct.construct_id, ())
            ),
        )
        for construct in constructs
    ]


def _visible_event_indices(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    start_index: int,
    end_index: int,
) -> list[int]:
    result: list[int] = []
    for token_index in range(start_index, min(end_index + 1, len(tokens))):
        if model_brackets.is_visible_music_token(tokens[token_index]):
            event_index = token_to_event_index.get(token_index)
            if event_index is not None:
                result.append(event_index)
    return result


def _first_visible_event_index(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    start_index: int,
    end_index: int,
) -> int | None:
    indices = _visible_event_indices(tokens, token_to_event_index, start_index, end_index)
    return indices[0] if indices else None


def _previous_visible_event_index(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    start_index: int,
) -> int | None:
    for token_index in range(min(start_index - 1, len(tokens) - 1), -1, -1):
        if model_brackets.is_visible_music_token(tokens[token_index]):
            return token_to_event_index.get(token_index)
    return None


def resolve_visual_chain_endpoints(
    events: list[MusicEvent],
    constructs: list[SemanticConstruct],
) -> list[SemanticConstruct]:
    """Resolve the drawn segment for a nested tie-chain parent.

    Parentheses can carry a complete logical tie while also containing small
    attached tie spans that identify adjacent visual links. The parent retains
    complete event coverage and roles, but its final drawn segment starts at
    the last direct child endpoint when that child is the immediately
    preceding musical event. This is derived from construct containment and
    normalized event topology, never source spelling.
    """

    visual_children = [
        construct
        for construct in constructs
        if construct.visual_only
        and construct.kind in {"tie", "slur"}
        and construct.start_event_index is not None
        and construct.end_event_index is not None
    ]
    parents = [
        construct
        for construct in constructs
        if not construct.visual_only
        and construct.kind in {"tie", "slur"}
        and construct.start_event_index is not None
        and construct.end_event_index is not None
    ]
    if not visual_children or not parents:
        return _annotate_direct_semantic_parents(constructs)

    direct_children: dict[str, list[SemanticConstruct]] = {}
    for child in visual_children:
        containing = [parent for parent in parents if _strictly_contains(parent, child)]
        if not containing:
            continue
        parent = min(
            containing,
            key=lambda item: (
                item.source_span.end.offset - item.source_span.start.offset,
                item.source_span.start.offset,
            ),
        )
        direct_children.setdefault(parent.construct_id, []).append(child)

    event_by_index = {event.index: event for event in events}
    musical_indices = {
        event.index
        for event in events
        if event.kind
        in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
        }
    }
    resolved: list[SemanticConstruct] = []
    for construct in constructs:
        children = direct_children.get(construct.construct_id, ())
        if (
            construct.kind != "tie"
            or construct.visual_only
            or construct.end_event_index is None
            or not children
        ):
            resolved.append(construct)
            continue
        previous_musical = max(
            (
                index
                for index in musical_indices
                if construct.start_event_index is not None
                and construct.start_event_index < index < construct.end_event_index
            ),
            default=None,
        )
        last_child_end = max(
            (
                child.end_event_index
                for child in children
                if child.end_event_index is not None
            ),
            default=None,
        )
        if last_child_end is None or previous_musical != last_child_end:
            resolved.append(construct)
            continue
        if last_child_end not in event_by_index or construct.end_event_index not in event_by_index:
            resolved.append(construct)
            continue
        resolved.append(
            replace(
                construct,
                visual_start_event_index=last_child_end,
                visual_end_event_index=construct.end_event_index,
            )
        )
    return _annotate_direct_semantic_parents(resolved)


def _annotate_direct_semantic_parents(
    constructs: list[SemanticConstruct],
) -> list[SemanticConstruct]:
    """Attach the nearest enclosing tie/slur to each nested construct."""

    spans = [
        item
        for item in constructs
        if item.kind in {"tie", "slur"}
        and item.start_event_index is not None
        and item.end_event_index is not None
    ]
    annotated: list[SemanticConstruct] = []
    for item in constructs:
        if item not in spans:
            annotated.append(item)
            continue
        parents = [parent for parent in spans if _strictly_contains(parent, item)]
        parent = min(
            parents,
            key=lambda candidate: (
                candidate.source_span.end.offset - candidate.source_span.start.offset,
                candidate.source_span.start.offset,
            ),
            default=None,
        )
        annotated.append(
            replace(item, semantic_parent_id=parent.construct_id if parent else None)
        )
    return annotated


def _strictly_contains(parent: SemanticConstruct, child: SemanticConstruct) -> bool:
    return (
        parent.source_span.start.offset < child.source_span.start.offset
        and child.source_span.end.offset < parent.source_span.end.offset
        and parent.start_event_index is not None
        and parent.end_event_index is not None
        and child.start_event_index is not None
        and child.end_event_index is not None
        and parent.start_event_index <= child.start_event_index
        and child.end_event_index <= parent.end_event_index
    )


__all__ = ["resolve_visual_chain_endpoints"]
