"""Layout-only projection of verified adjacent parenthesis chains."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from octopus.normalization.types import MusicEvent, SemanticConstruct
from octopus.render.core.layout_types import LayoutEvent

from ...parser.ast import MusicTokenKind

SPAN_KINDS = {"tie", "slur"}
MUSICAL_KINDS = {MusicTokenKind.NOTE, MusicTokenKind.REST, MusicTokenKind.RHYTHM_NOTE}


def project_parenthesis_chains(
    constructs: tuple[SemanticConstruct, ...],
    source_events: tuple[MusicEvent, ...],
    by_index: Mapping[int, LayoutEvent],
) -> tuple[SemanticConstruct, ...]:
    """Project within one voice/system, without changing normalized objects.

    Only endpoint repairs activate; already-correct chains retain their order.
    Each bundle replaces consumed members at their first original occurrence.
    """
    by_id = {item.construct_id: item for item in constructs}
    bundles: dict[str, tuple[SemanticConstruct, ...]] = {}
    owners: dict[str, str] = {}
    for parent in constructs:
        result = _chain_bundle(parent, constructs, source_events, by_index, by_id)
        if result is None:
            continue
        bundle, consumed = result
        if any(identifier in owners for identifier in consumed):
            continue
        bundles[parent.construct_id] = bundle
        owners.update((identifier, parent.construct_id) for identifier in consumed)
    if not bundles:
        return constructs
    result_items: list[SemanticConstruct] = []
    emitted: set[str] = set()
    for item in constructs:
        owner = owners.get(item.construct_id)
        if owner is None:
            result_items.append(item)
        elif owner not in emitted:
            result_items.extend(bundles[owner])
            emitted.add(owner)
    return tuple(result_items)


def _chain_bundle(
    parent: SemanticConstruct,
    constructs: tuple[SemanticConstruct, ...],
    source_events: tuple[MusicEvent, ...],
    by_index: Mapping[int, LayoutEvent],
    by_id: Mapping[str, SemanticConstruct],
) -> tuple[tuple[SemanticConstruct, ...], set[str]] | None:
    start, end = parent.start_event_index, parent.end_event_index
    if parent.visual_only or parent.kind not in SPAN_KINDS or start is None or end is None:
        return None
    children = [
        item
        for item in constructs
        if item.semantic_parent_id == parent.construct_id and item.kind in SPAN_KINDS
    ]
    if any(not child.visual_only for child in children):
        return None
    # Both representations describe source anchors, regardless of pitch.
    anchors: list[tuple[int, int | None, SemanticConstruct | None]] = [
        (child.source_span.start.offset, child.end_event_index, child) for child in children
    ]
    anchors.extend(
        (item.source_span.start.offset, item.end_event_index, None)
        for item in parent.singleton_parenthesis_provenance
    )
    anchors.sort(key=lambda item: item[0])
    endpoints = [start, *[index for _, index, _ in anchors], end]
    if len(endpoints) < 3 or any(index is None or index not in by_index for index in endpoints):
        return None
    indexes = [index for index in endpoints if index is not None]
    hosts = [by_index[index] for index in indexes]
    rows = {(host.page_index, host.voice, host.line) for host in hosts}
    if len(rows) != 1 or any(a.slot >= b.slot for a, b in zip(hosts, hosts[1:], strict=False)):
        return None
    if any(a >= b for a, b in zip(indexes, indexes[1:], strict=False)):
        return None
    row = next(iter(rows))
    previous = max(
        (
            by_index[event.index].slot
            for event in source_events
            if event.kind in MUSICAL_KINDS
            and event.index in by_index
            and (
                by_index[event.index].page_index,
                by_index[event.index].voice,
                by_index[event.index].line,
            )
            == row
            and by_index[event.index].slot < hosts[-1].slot
        ),
        default=None,
    )
    if previous != hosts[-2].slot:
        return None
    outer = by_id.get(parent.semantic_parent_id or "")
    if parent.semantic_parent_id is not None:
        if (
            outer is None
            or outer.visual_only
            or outer.kind not in SPAN_KINDS
            or outer.semantic_parent_id is not None
            or (outer.start_event_index, outer.end_event_index) != (start, end)
            or [
                item.construct_id
                for item in constructs
                if item.semantic_parent_id == outer.construct_id and item.kind in SPAN_KINDS
            ]
            != [parent.construct_id]
        ):
            return None
    needs_repair = bool(parent.singleton_parenthesis_provenance)
    for index, (_, _, child) in enumerate(anchors):
        if child is not None:
            old = (
                child.visual_start_event_index
                if child.visual_start_event_index is not None
                else child.start_event_index,
                child.visual_end_event_index
                if child.visual_end_event_index is not None
                else child.end_event_index,
            )
            needs_repair |= old != (indexes[index], indexes[index + 1])
    needs_repair |= (parent.visual_start_event_index, parent.visual_end_event_index) != (
        indexes[-2],
        end,
    )
    if not needs_repair:
        return None
    links = []
    for index, (_, _, child) in enumerate(anchors):
        template = child or parent
        links.append(
            replace(
                template,
                kind=parent.kind,
                visual_only=True,
                construct_id=(
                    child.construct_id
                    if child is not None
                    else f"{parent.construct_id}:visual-chain:{index}"
                ),
                visual_start_event_index=indexes[index],
                visual_end_event_index=indexes[index + 1],
                semantic_parent_id=parent.construct_id,
                singleton_parenthesis_provenance=(),
            )
        )
    final = replace(parent, visual_start_event_index=indexes[-2], visual_end_event_index=end)
    bundle = (links[0], *((outer,) if outer is not None else ()), *links[1:], final)
    consumed = {parent.construct_id, *(child.construct_id for child in children)}
    if outer is not None:
        consumed.add(outer.construct_id)
    return bundle, consumed


__all__ = ["project_parenthesis_chains"]
