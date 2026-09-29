"""Typed provenance for ordered construct emission.

The legacy renderer still has measured replay tables for a few late construct
families.  This module describes the ordinary semantic emission stream without
consulting those tables, so the two streams can be compared before replay is
generalized.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..core.elements import SvgElement
from ..core.layout_types import LayoutConstruct, LayoutPage
from .serialize import render_svg_element
from .slur_style import slur_uses_path


class ConstructEmissionKind(StrEnum):
    """Geometry family selected by the normalized construct configuration."""

    PATH = "path"
    ENDPOINT = "endpoint"


@dataclass(frozen=True, slots=True)
class ConstructEmission:
    """One ordinary late-stream construct occurrence."""

    construct: LayoutConstruct
    emission_kind: ConstructEmissionKind
    ordinal: int

    @property
    def construct_id(self) -> str:
        return construct_identity(self.construct)


@dataclass(frozen=True, slots=True)
class ConstructOccurrence:
    """One occurrence of a construct in an ordered SVG emission stream.

    A semantic construct may occur more than once in the legacy stream.  The
    occurrence index preserves that distinction without making the identity
    itself depend on a source filename or page-specific compatibility key.
    """

    construct_id: str
    occurrence_index: int
    emission_kind: ConstructEmissionKind
    serialized_elements: tuple[str, ...]

    @property
    def identity(self) -> tuple[str, int]:
        return self.construct_id, self.occurrence_index


@dataclass(frozen=True, slots=True)
class ConstructEmissionPlan:
    """Immutable ordinary construct stream in source/layout order."""

    late: tuple[ConstructEmission, ...]

    @property
    def construct_ids(self) -> tuple[str, ...]:
        return tuple(item.construct_id for item in self.late)


@dataclass(frozen=True, slots=True)
class ConstructTopology:
    """Source-independent visual topology for one layout construct."""

    construct_id: str
    kind: str
    source_kind: str | None
    start_address: tuple[int, int, int, int]
    end_address: tuple[int, int, int, int]
    start_event_index: int
    end_event_index: int

    @property
    def crosses_visual_rows(self) -> bool:
        """Whether the construct endpoints occupy different voice/row slots."""

        return self.start_address[:3] != self.end_address[:3]

    @property
    def spans_event_stream(self) -> bool:
        """Whether the construct covers more than one normalized event."""

        return self.start_event_index != self.end_event_index


@dataclass(frozen=True, slots=True)
class ConstructEmissionComparison:
    """Comparison between semantic and legacy construct occurrence streams."""

    planned_occurrences: tuple[ConstructOccurrence, ...]
    replayed_occurrences: tuple[ConstructOccurrence, ...]

    @property
    def planned_ids(self) -> tuple[str, ...]:
        """Return construct identities in planned order."""

        return tuple(item.construct_id for item in self.planned_occurrences)

    @property
    def replayed_ids(self) -> tuple[str, ...]:
        """Return construct identities in replayed order."""

        return tuple(item.construct_id for item in self.replayed_occurrences)

    @property
    def missing_ids(self) -> tuple[str, ...]:
        replayed = {item.identity for item in self.replayed_occurrences}
        return tuple(
            item.construct_id for item in self.planned_occurrences if item.identity not in replayed
        )

    @property
    def is_covered(self) -> bool:
        return not self.missing_ids

    @property
    def is_exact(self) -> bool:
        """Whether identity, occurrence order, and serialized elements match."""

        return self.planned_occurrences == self.replayed_occurrences

    @property
    def first_difference_index(self) -> int | None:
        """Return the first differing occurrence, or ``None`` for an exact match."""

        for index, (planned, replayed) in enumerate(
            zip(self.planned_occurrences, self.replayed_occurrences, strict=False)
        ):
            if planned != replayed:
                return index
        if len(self.planned_occurrences) != len(self.replayed_occurrences):
            return min(len(self.planned_occurrences), len(self.replayed_occurrences))
        return None

    @property
    def duplicate_ids(self) -> tuple[str, ...]:
        """Return replay identities occurring more than once, in first-seen order."""

        counts: dict[str, int] = {}
        for identifier in self.replayed_ids:
            counts[identifier] = counts.get(identifier, 0) + 1
        return tuple(
            identifier for identifier in dict.fromkeys(self.replayed_ids) if counts[identifier] > 1
        )


def construct_identity(construct: LayoutConstruct) -> str:
    """Return a stable identity without page or source-file provenance."""

    if construct.construct_id:
        return construct.construct_id
    logical_start = (
        construct.logical_start if construct.logical_start is not None else construct.start
    )
    logical_end = construct.logical_end if construct.logical_end is not None else construct.end
    return ":".join(
        (
            construct.kind,
            construct.source_kind or "",
            str(logical_start.event.index),
            str(logical_end.event.index),
            str(logical_start.event.span.start.line),
        )
    )


def construct_topology(construct: LayoutConstruct) -> ConstructTopology:
    """Extract layout topology without source-file or page-table identity."""

    start = construct.start
    end = construct.end
    return ConstructTopology(
        construct_id=construct_identity(construct),
        kind=construct.kind,
        source_kind=construct.source_kind,
        start_address=(start.page_index, start.voice, start.line, start.slot),
        end_address=(end.page_index, end.voice, end.line, end.slot),
        start_event_index=start.event.index,
        end_event_index=end.event.index,
    )


def late_construct_emission_plan(
    layout: LayoutPage,
    *,
    constructs: Sequence[LayoutConstruct] | None = None,
) -> ConstructEmissionPlan:
    """Plan late constructs, correcting only verified shared-end tie pairs.

    ``constructs`` lets rendering consume resolved construct copies while
    keeping the original layout as the stable source of all other page data.
    Existing callers omit it and use the layout-backed stream. Source ordinals
    remain provenance even when a pair's emission order changes.
    """

    emissions: list[ConstructEmission] = []
    source_constructs = layout.constructs if constructs is None else constructs
    for ordinal, construct in enumerate(source_constructs):
        if construct.kind in {"block", "ending"}:
            continue
        emission_kind = _emission_kind(construct)
        emissions.append(ConstructEmission(construct, emission_kind, ordinal))
    return ConstructEmissionPlan(_order_shared_end_ties(emissions, source_constructs))


def _order_shared_end_ties(
    emissions: Sequence[ConstructEmission],
    constructs: Sequence[LayoutConstruct],
) -> tuple[ConstructEmission, ...]:
    """Emit a root tie before its sole later-start, shared-end child.

    Normalization records closing-token order (child first). The reference
    paints these adjacent depth-two path ties in start order. Keep all other
    topology and existing replay multiplicity untouched; see the E3a controls.
    """
    child_counts = Counter(c.semantic_parent_id for c in constructs if c.semantic_parent_id)
    ordered = list(emissions)
    index = 0
    while index + 1 < len(ordered):
        child_emission, parent_emission = ordered[index : index + 2]
        child, parent = child_emission.construct, parent_emission.construct
        endpoints = (parent.start, parent.end, child.start, child.end)
        same_row = len({(e.page_index, e.voice, e.line) for e in endpoints}) == 1
        if (
            parent_emission.ordinal == child_emission.ordinal + 1
            and child_emission.emission_kind
            == parent_emission.emission_kind
            == ConstructEmissionKind.PATH
            and child.kind == parent.kind == "slur"
            and child.source_kind == parent.source_kind == "tie"
            and parent.construct_id is not None
            and child.construct_id is not None
            and child.semantic_parent_id == parent.construct_id
            and parent.semantic_parent_id is None
            and child_counts[parent.construct_id] == 1
            and child_counts[child.construct_id] == 0
            and not any(
                c.visual_only
                or c.visual_start_event_index is not None
                or c.visual_end_event_index is not None
                for c in (parent, child)
            )
            and same_row
            and parent.start.event.index < child.start.event.index < child.end.event.index
            and parent.end.event.index == child.end.event.index
        ):
            ordered[index : index + 2] = (parent_emission, child_emission)
            index += 2
        else:
            index += 1
    return tuple(ordered)


def topology_late_construct_emission_plan(layout: LayoutPage) -> ConstructEmissionPlan:
    """Build a stable candidate order from endpoint topology only.

    This is deliberately a shadow plan.  It has one occurrence per semantic
    construct and therefore cannot represent a legacy duplicate pass until a
    separate rule establishes ownership for that pass.
    """

    plan = late_construct_emission_plan(layout)
    emissions = sorted(plan.late, key=_topology_emission_sort_key)
    return ConstructEmissionPlan(tuple(emissions))


def _topology_emission_sort_key(
    emission: ConstructEmission,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], str, str, int]:
    topology = construct_topology(emission.construct)
    return (
        topology.start_address,
        topology.end_address,
        topology.kind,
        topology.source_kind or "",
        emission.ordinal,
    )


def compare_legacy_replay_coverage(
    plan: ConstructEmissionPlan,
    replayed_constructs: Sequence[LayoutConstruct],
) -> ConstructEmissionComparison:
    """Check that legacy replay still covers every semantic construct."""

    return compare_legacy_replay_order(plan, replayed_constructs)


def compare_legacy_replay_order(
    plan: ConstructEmissionPlan,
    replayed_constructs: Sequence[LayoutConstruct],
) -> ConstructEmissionComparison:
    """Compare construct occurrence order without requiring rendered elements."""

    planned = _occurrences_from_emissions(plan.late)
    replayed = _occurrences_from_constructs(replayed_constructs)
    return ConstructEmissionComparison(planned, replayed)


def compare_legacy_replay_stream(
    plan: ConstructEmissionPlan,
    rendered: Sequence[tuple[LayoutConstruct, Sequence[SvgElement]]],
    replayed_constructs: Sequence[LayoutConstruct],
    replayed_rendered: Sequence[tuple[LayoutConstruct, Sequence[SvgElement]]] | None = None,
) -> ConstructEmissionComparison:
    """Compare construct order and exact serialized element sequences.

    ``rendered`` is keyed by object identity because the retained replay tables
    intentionally replay the same layout construct more than once.  The
    serialized payload excludes internal provenance fields while preserving
    tag, attribute order, attribute values, text, and SVG serializer syntax.
    """

    planned_elements_by_object_id = {
        id(construct): tuple(elements) for construct, elements in rendered
    }
    planned = _occurrences_from_emissions(plan.late, planned_elements_by_object_id)
    replayed_elements_by_object_id = planned_elements_by_object_id
    if replayed_rendered is not None:
        replayed_elements_by_object_id = {
            id(construct): tuple(elements) for construct, elements in replayed_rendered
        }
    replayed = _occurrences_from_constructs(replayed_constructs, replayed_elements_by_object_id)
    return ConstructEmissionComparison(planned, replayed)


def _occurrences_from_emissions(
    emissions: Sequence[ConstructEmission],
    elements_by_object_id: dict[int, tuple[SvgElement, ...]] | None = None,
) -> tuple[ConstructOccurrence, ...]:
    counts: dict[str, int] = {}
    occurrences: list[ConstructOccurrence] = []
    for emission in emissions:
        identifier = emission.construct_id
        occurrence_index = counts.get(identifier, 0)
        counts[identifier] = occurrence_index + 1
        elements = (
            ()
            if elements_by_object_id is None
            else elements_by_object_id.get(id(emission.construct), ())
        )
        occurrences.append(
            _occurrence_from_construct(
                emission.construct,
                emission.emission_kind,
                occurrence_index,
                elements,
            )
        )
    return tuple(occurrences)


def _occurrences_from_constructs(
    constructs: Sequence[LayoutConstruct],
    elements_by_object_id: dict[int, tuple[SvgElement, ...]] | None = None,
) -> tuple[ConstructOccurrence, ...]:
    counts: dict[str, int] = {}
    occurrences: list[ConstructOccurrence] = []
    for construct in constructs:
        identifier = construct_identity(construct)
        occurrence_index = counts.get(identifier, 0)
        counts[identifier] = occurrence_index + 1
        elements = (
            () if elements_by_object_id is None else elements_by_object_id.get(id(construct), ())
        )
        occurrences.append(
            _occurrence_from_construct(
                construct,
                _emission_kind(construct),
                occurrence_index,
                elements,
            )
        )
    return tuple(occurrences)


def _occurrence_from_construct(
    construct: LayoutConstruct,
    emission_kind: ConstructEmissionKind,
    occurrence_index: int,
    elements: Sequence[SvgElement] = (),
) -> ConstructOccurrence:
    return ConstructOccurrence(
        construct_id=construct_identity(construct),
        occurrence_index=occurrence_index,
        emission_kind=emission_kind,
        serialized_elements=tuple(render_svg_element(element) for element in elements),
    )


def _emission_kind(construct: LayoutConstruct) -> ConstructEmissionKind:
    if construct.kind in {"slur", "tie"}:
        return (
            ConstructEmissionKind.PATH
            if slur_uses_path(construct)
            else ConstructEmissionKind.ENDPOINT
        )
    return (
        ConstructEmissionKind.ENDPOINT
        if construct.lianyinxian_type == "2"
        else ConstructEmissionKind.PATH
    )


__all__ = [
    "ConstructEmission",
    "ConstructEmissionComparison",
    "ConstructEmissionKind",
    "ConstructEmissionPlan",
    "ConstructOccurrence",
    "ConstructTopology",
    "construct_identity",
    "construct_topology",
    "compare_legacy_replay_coverage",
    "compare_legacy_replay_order",
    "compare_legacy_replay_stream",
    "late_construct_emission_plan",
    "topology_late_construct_emission_plan",
]
