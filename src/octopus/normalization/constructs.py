"""Pair source constructs, recover visual endpoints, and assign event roles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from octopus.normalization import brackets as model_brackets
from octopus.normalization.ties import (
    _first_musical_token_with_index,
    _previous_musical_token_with_index,
    _same_tie_note,
    _span_close_is_tie,
)
from octopus.normalization.types import (
    MusicEvent,
    SemanticConstruct,
    SingletonParenthesisProvenance,
)
from octopus.normalization.visual_chains import (
    _attach_singleton_provenance,
    _discarded_singleton_provenance,
    _first_visible_event_index,
    _previous_visible_event_index,
    _visible_event_indices,
)
from octopus.parser.ast import (
    MusicToken,
    MusicTokenKind,
)
from octopus.parser.source import SourceSpan


def _extract_semantic_constructs(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    construct_prefix: Callable[[MusicToken], str] | str,
) -> list[SemanticConstruct]:
    constructs: list[SemanticConstruct] = []
    discarded_singletons: list[SingletonParenthesisProvenance] = []
    rescuable_singletons: list[SingletonParenthesisProvenance] = []
    pair_stack: list[tuple[int, MusicTokenKind]] = []
    pair_openers = {
        MusicTokenKind.SPAN_START,
        MusicTokenKind.TUPLET_START,
        MusicTokenKind.BLOCK_START,
        MusicTokenKind.BRACKET_START,
    }
    closer_openers = {
        MusicTokenKind.SPAN_END: {
            MusicTokenKind.SPAN_START,
            MusicTokenKind.TUPLET_START,
        },
        MusicTokenKind.BLOCK_END: {MusicTokenKind.BLOCK_START},
        MusicTokenKind.BRACKET_END: {MusicTokenKind.BRACKET_START},
    }
    counters: dict[tuple[str, str], int] = {}
    def next_id(kind: str, token: MusicToken | None = None) -> str:
        prefix = (
            construct_prefix(token)
            if callable(construct_prefix) and token is not None
            else construct_prefix
            if isinstance(construct_prefix, str)
            else "construct"
        )
        key = (prefix, kind)
        counters[key] = counters.get(key, 0) + 1
        return f"{prefix}:{kind}:{counters[key]}"
    for token_index, token in enumerate(tokens):
        if token.kind in pair_openers:
            pair_stack.append((token_index, token.kind))
            continue
        if token.kind in closer_openers:
            allowed = closer_openers[token.kind]
            while pair_stack and pair_stack[-1][1] not in allowed:
                pair_stack.pop()
            if not pair_stack:
                if token.kind == MusicTokenKind.SPAN_END:
                    rescue_candidate = (
                        rescuable_singletons[-1] if rescuable_singletons else None
                    )
                    rescued = _rescue_discarded_singleton(
                        tokens,
                        token_to_event_index,
                        token_index,
                        rescuable_singletons,
                        next_id,
                    )
                    if rescued is not None:
                        constructs.append(rescued)
                        if rescue_candidate is not None:
                            discarded_singletons.remove(rescue_candidate)
                continue
            opener_index, opener_kind = pair_stack.pop()
            outer_pair_index = next(
                (
                    index
                    for index, kind in reversed(pair_stack)
                    if kind in {MusicTokenKind.SPAN_START, MusicTokenKind.TUPLET_START}
                ),
                None,
            )
            construct = _paired_construct(
                tokens,
                token_to_event_index,
                opener_index,
                token_index,
                opener_kind,
                next_id,
                outer_pair_index=outer_pair_index,
            )
            if construct is not None:
                constructs.append(construct)
            else:
                singleton = _discarded_singleton_provenance(
                    tokens,
                    token_to_event_index,
                    opener_index,
                    token_index,
                    opener_kind,
                )
                if singleton is not None:
                    discarded_singletons.append(singleton)
                    if outer_pair_index is None:
                        rescuable_singletons.append(singleton)
            continue
        if token.kind == MusicTokenKind.GRACE_GROUP:
            host = _previous_visible_event_index(tokens, token_to_event_index, token_index)
            mark_kind = _mark_only_grace_group_kind(token)
            if host is not None and mark_kind is not None:
                constructs.append(
                    SemanticConstruct(
                        construct_id=next_id(mark_kind, token),
                        kind=mark_kind,
                        source_span=token.span,
                        start_event_index=token_to_event_index.get(token_index),
                        host_event_index=host,
                        event_indices=(host,),
                        value=_mark_only_grace_group_value(token),
                        role_by_event_index=((host, "host"),),
                    )
                )
            elif host is not None and _grace_group_has_musical_child(token):
                constructs.append(
                    SemanticConstruct(
                        construct_id=next_id("grace", token),
                        kind="grace",
                        source_span=token.span,
                        start_event_index=token_to_event_index.get(token_index),
                        host_event_index=host,
                        event_indices=(host,),
                        value=token.raw,
                        role_by_event_index=((host, "host"),),
                    )
                )
            continue
        if token.kind in {
            MusicTokenKind.ANNOTATION,
            MusicTokenKind.DECORATION,
            MusicTokenKind.MODIFIER,
        }:
            host = _previous_visible_event_index(tokens, token_to_event_index, token_index)
            if host is not None:
                kind = (
                    "annotation"
                    if token.kind == MusicTokenKind.ANNOTATION
                    else "decoration"
                    if token.kind == MusicTokenKind.DECORATION
                    else "modifier"
                )
                constructs.append(
                    SemanticConstruct(
                        construct_id=next_id(kind, token),
                        kind=kind,
                        source_span=token.span,
                        start_event_index=token_to_event_index.get(token_index),
                        host_event_index=host,
                        event_indices=(host,),
                        value=token.value or token.raw,
                        role_by_event_index=((host, "host"),),
                    )
                )
    constructs, discarded_singletons = _promote_singleton_anchor(
        tokens,
        token_to_event_index,
        constructs,
        discarded_singletons,
        next_id,
    )
    dangling_span_openers = [
        (tokens[index].span.start.line, tokens[index].span.start.offset)
        for index, kind in pair_stack
        if kind == MusicTokenKind.SPAN_START
    ]
    if dangling_span_openers:
        constructs = [
            replace(construct, inside_dangling_span=True)
            if construct.kind in {"slur", "tie"}
            and any(
                line == construct.source_span.start.line
                and offset < construct.source_span.start.offset
                for line, offset in dangling_span_openers
            )
            else construct
            for construct in constructs
        ]
    return _attach_singleton_provenance(constructs, discarded_singletons)


def _grace_group_has_musical_child(token: MusicToken) -> bool:
    return any(
        child.kind in {MusicTokenKind.NOTE, MusicTokenKind.RHYTHM_NOTE}
        and child.pitch not in {None, 8, 9}
        for child in token.children
    )


def _mark_only_grace_group_kind(token: MusicToken) -> str | None:
    mark_children = [
        child
        for child in token.children
        if child.kind
        in {
            MusicTokenKind.ANNOTATION,
            MusicTokenKind.DECORATION,
            MusicTokenKind.MODIFIER,
        }
    ]
    if not mark_children or len(mark_children) != len(token.children):
        return None
    first = mark_children[0]
    if first.kind == MusicTokenKind.ANNOTATION:
        return "annotation"
    if first.kind == MusicTokenKind.DECORATION:
        return "decoration"
    return "modifier"


def _mark_only_grace_group_value(token: MusicToken) -> str:
    first = token.children[0]
    return first.value or first.raw


def _paired_construct(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    opener_index: int,
    closer_index: int,
    opener_kind: MusicTokenKind,
    next_id: Callable[[str, MusicToken | None], str],
    *,
    outer_pair_index: int | None = None,
) -> SemanticConstruct | None:
    if opener_kind == MusicTokenKind.BRACKET_START and tokens[opener_index].attached_to_previous:
        start = _previous_visible_event_index(tokens, token_to_event_index, opener_index)
    else:
        start = _first_visible_event_index(
            tokens, token_to_event_index, opener_index + 1, closer_index
        )
    end = _previous_visible_event_index(tokens, token_to_event_index, closer_index + 1)
    if opener_kind == MusicTokenKind.TUPLET_START:
        kind = "tuplet"
    elif opener_kind == MusicTokenKind.SPAN_START:
        close_note = _previous_musical_token_with_index(tokens, closer_index + 1)
        kind = (
            "tie"
            if close_note is not None
            and _span_close_is_tie(tokens, opener_index, close_note[0], close_note[1])
            else "slur"
        )
    elif opener_kind == MusicTokenKind.BLOCK_START:
        kind = "block"
    else:
        kind = "bracket"
    if start is None or end is None:
        return None
    visual_endpoints: tuple[int, int] | None = None
    rescued_singleton = False
    source_closer_index = closer_index
    if opener_kind == MusicTokenKind.SPAN_START and start == end:
        visual_endpoints = _attached_inner_span_visual_endpoints(
            tokens,
            token_to_event_index,
            opener_index,
            closer_index,
            outer_pair_index=outer_pair_index,
        )
        if visual_endpoints is None and outer_pair_index is None:
            recovered = _unmatched_singleton_span_visual_endpoints(
                tokens,
                token_to_event_index,
                opener_index,
                closer_index,
            )
            if recovered is not None:
                visual_endpoints, source_closer_index = recovered
                if _has_dotted_orphan_close(tokens, source_closer_index):
                    kind = "tie"
                    rescued_singleton = True
        if visual_endpoints is None:
            return None
        start, end = visual_endpoints
    event_indices = _visible_event_indices(
        tokens,
        token_to_event_index,
        opener_index + 1,
        source_closer_index,
    )
    if start not in event_indices:
        event_indices.insert(0, start)
    if end not in event_indices:
        event_indices.append(end)
    roles: list[tuple[int, str]] = []
    for event_index in event_indices:
        if event_index == start:
            roles.append((event_index, "start"))
        elif event_index == end:
            roles.append((event_index, "end"))
        else:
            roles.append((event_index, "inside"))
    if start == end:
        roles = [(start, "single")]
    opener = tokens[opener_index]
    closer = tokens[source_closer_index]
    is_bracket = opener_kind == MusicTokenKind.BRACKET_START
    construct_id = next_id(kind, opener)
    return SemanticConstruct(
        construct_id=construct_id,
        kind=kind,
        source_span=SourceSpan(opener.span.start, closer.span.end),
        start_event_index=start,
        end_event_index=end,
        event_indices=tuple(event_indices),
        value=opener.value,
        source_text="".join(
            token.raw for token in tokens[opener_index : source_closer_index + 1]
        ),
        role_by_event_index=tuple(roles),
        visual_only=visual_endpoints is not None and not rescued_singleton,
        ending_plus_count=(
            model_brackets.leading_bracket_plus_count(tokens, opener_index, closer_index)
            if is_bracket
            else 0
        ),
    )


def _attached_inner_span_visual_endpoints(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    opener_index: int,
    closer_index: int,
    *,
    outer_pair_index: int | None,
) -> tuple[int, int] | None:
    if outer_pair_index is None:
        return None
    previous_note = _previous_musical_token_with_index(tokens, opener_index)
    current_note = _previous_musical_token_with_index(tokens, closer_index + 1)
    if previous_note is None or current_note is None:
        return None
    previous_note_index, previous_note_token = previous_note
    current_note_index, current_note_token = current_note
    if previous_note_index == current_note_index:
        return None
    if not _same_tie_note(previous_note_token, current_note_token):
        return None
    start = token_to_event_index.get(previous_note_index)
    end = token_to_event_index.get(current_note_index)
    if start is None or end is None:
        return None
    return start, end


def _rescue_discarded_singleton(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    closer_index: int,
    discarded_singletons: list[SingletonParenthesisProvenance],
    next_id: Callable[[str, MusicToken | None], str],
) -> SemanticConstruct | None:
    """Recover the dotted orphan-close form without promoting plain singletons."""
    if not discarded_singletons:
        return None
    if not _has_dotted_orphan_close(tokens, closer_index):
        return None
    singleton = discarded_singletons[-1]
    end_event_index = _previous_visible_event_index(
        tokens,
        token_to_event_index,
        closer_index,
    )
    if end_event_index is None or end_event_index == singleton.start_event_index:
        return None
    start_token_index = next(
        (
            index
            for index, event_index in token_to_event_index.items()
            if event_index == singleton.start_event_index
        ),
        None,
    )
    end_token_index = next(
        (
            index
            for index, event_index in token_to_event_index.items()
            if event_index == end_event_index
        ),
        None,
    )
    if start_token_index is None or end_token_index is None:
        return None
    event_indices = _visible_event_indices(
        tokens,
        token_to_event_index,
        start_token_index,
        end_token_index + 1,
    )
    if singleton.start_event_index not in event_indices:
        event_indices.insert(0, singleton.start_event_index)
    if end_event_index not in event_indices:
        event_indices.append(end_event_index)
    roles = tuple(
        (
            event_index,
            "start"
            if event_index == singleton.start_event_index
            else "end"
            if event_index == end_event_index
            else "inside",
        )
        for event_index in event_indices
    )
    opener_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if token.span.start.offset == singleton.source_span.start.offset
        ),
        None,
    )
    if opener_index is None:
        return None
    discarded_singletons.pop()
    closer = tokens[closer_index]
    return SemanticConstruct(
        construct_id=next_id("tie", closer),
        kind="tie",
        source_span=SourceSpan(singleton.source_span.start, closer.span.end),
        start_event_index=singleton.start_event_index,
        end_event_index=end_event_index,
        event_indices=tuple(event_indices),
        source_text="".join(token.raw for token in tokens[opener_index : closer_index + 1]),
        role_by_event_index=roles,
    )


def _has_dotted_orphan_close(tokens: tuple[MusicToken, ...], closer_index: int) -> bool:
    suffix_index = closer_index + 1
    if suffix_index >= len(tokens):
        return False
    suffix = tokens[suffix_index]
    return (
        suffix.kind == MusicTokenKind.MODIFIER
        and suffix.raw == "."
        and suffix.attached_to_previous
    )


def _promote_singleton_anchor(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    constructs: list[SemanticConstruct],
    discarded_singletons: list[SingletonParenthesisProvenance],
    next_id: Callable[[str, MusicToken | None], str],
) -> tuple[list[SemanticConstruct], list[SingletonParenthesisProvenance]]:
    """Draw a lone same-pitch singleton as the enclosing span's visual anchor."""
    for singleton in tuple(discarded_singletons):
        parents = [
            parent
            for parent in constructs
            if parent.kind in {"tie", "slur"}
            and not parent.visual_only
            and parent.start_event_index is not None
            and parent.end_event_index is not None
            and parent.source_span.start.offset < singleton.source_span.start.offset
            and singleton.source_span.end.offset < parent.source_span.end.offset
            and parent.start_event_index <= singleton.start_event_index
            and singleton.end_event_index <= parent.end_event_index
        ]
        if not parents:
            continue
        parent = min(
            parents,
            key=lambda item: item.source_span.end.offset - item.source_span.start.offset,
        )
        parent_start = parent.start_event_index
        parent_end = parent.end_event_index
        if parent_start is None or parent_end is None:
            continue
        siblings = [
            item
            for item in discarded_singletons
            if parent.source_span.start.offset < item.source_span.start.offset
            and item.source_span.end.offset < parent.source_span.end.offset
            and parent_start <= item.start_event_index
            and item.end_event_index <= parent_end
        ]
        if len(siblings) != 1:
            continue
        has_other_child = any(
            item is not parent
            and item.kind in {"tie", "slur"}
            and parent.source_span.start.offset < item.source_span.start.offset
            and item.source_span.end.offset < parent.source_span.end.offset
            for item in constructs
        )
        if has_other_child:
            continue
        start_token_index = next(
            (
                index
                for index, event_index in token_to_event_index.items()
                if event_index == parent.start_event_index
            ),
            None,
        )
        end_token_index = next(
            (
                index
                for index, event_index in token_to_event_index.items()
                if event_index == singleton.start_event_index
            ),
            None,
        )
        opener_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if token.span.start.offset == singleton.source_span.start.offset
            ),
            None,
        )
        if (
            start_token_index is None
            or end_token_index is None
            or opener_index is None
            or parent_start == singleton.start_event_index
            or not _same_tie_note(tokens[start_token_index], tokens[end_token_index])
        ):
            continue
        constructs.append(
            SemanticConstruct(
                construct_id=next_id("tie", tokens[opener_index]),
                kind="tie",
                source_span=singleton.source_span,
                start_event_index=parent_start,
                end_event_index=singleton.start_event_index,
                event_indices=(parent_start, singleton.start_event_index),
                source_text=singleton.source_text,
                role_by_event_index=(
                    (parent_start, "start"),
                    (singleton.start_event_index, "end"),
                ),
                visual_only=True,
            )
        )
        discarded_singletons.remove(singleton)
    return constructs, discarded_singletons


def _unmatched_singleton_span_visual_endpoints(
    tokens: tuple[MusicToken, ...],
    token_to_event_index: dict[int, int],
    opener_index: int,
    closer_index: int,
) -> tuple[tuple[int, int], int] | None:
    """Recover a same-pitch span closed on the immediately following note.

    A legacy export can encode ``(note) same-note)`` as a singleton span plus
    an attached close on the following note.  The first close is paired by the
    parser, leaving the attached close unmatched even though the reference
    draws the segment between the two notes.  Keep this recovery narrow:
    there must be one following musical token, its attached tokens must begin
    with a span close, and both notes must have the same pitch/octave.
    """

    start_token = _first_musical_token_with_index(tokens, opener_index + 1, closer_index)
    if start_token is None:
        return None
    next_token = _first_musical_token_with_index(tokens, closer_index + 1, len(tokens) - 1)
    if next_token is None:
        return None
    start_index, start_note = start_token
    next_index, next_note = next_token
    if start_index == next_index or not _same_tie_note(start_note, next_note):
        return None
    if next_index != closer_index + 1:
        return None
    attached_close_index = next_index + 1
    if attached_close_index >= len(tokens):
        return None
    attached_close = tokens[attached_close_index]
    if (
        attached_close.kind != MusicTokenKind.SPAN_END
        or not attached_close.attached_to_previous
    ):
        return None
    start = token_to_event_index.get(start_index)
    end = token_to_event_index.get(next_index)
    if start is None or end is None:
        return None
    return (start, end), attached_close_index


def _annotate_construct_roles(
    events: list[MusicEvent],
    constructs: list[SemanticConstruct],
) -> list[MusicEvent]:
    by_event: dict[int, list[tuple[str, str]]] = {}
    for construct in constructs:
        if construct.visual_only:
            continue
        role_map = dict(construct.role_by_event_index)
        for event_index in construct.event_indices:
            role = role_map.get(event_index, "inside")
            by_event.setdefault(event_index, []).append((construct.construct_id, role))
        if construct.host_event_index is not None:
            by_event.setdefault(construct.host_event_index, []).append(
                (construct.construct_id, "host")
            )
    annotated: list[MusicEvent] = []
    for event in events:
        refs = by_event.get(event.index, [])
        if not refs:
            annotated.append(event)
            continue
        annotated.append(
            replace(
                event,
                construct_ids=tuple(construct_id for construct_id, _role in refs),
                construct_roles=tuple(f"{construct_id}:{role}" for construct_id, role in refs),
            )
        )
    return annotated
