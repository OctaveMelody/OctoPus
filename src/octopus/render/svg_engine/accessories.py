"""Event accessory and decoration rendering policy.

This module owns only per-event element construction.  Page-level ordering,
standalone marks, and compatibility reordering remain in ``render.svg``.
"""

from __future__ import annotations

from dataclasses import dataclass

from octopus.normalization.types import MusicEvent

from ...parser.ast import MusicTokenKind
from ..core.elements import SvgElement, _format_reference_number
from ..core.glyphs import get_accidental_glyph, get_decoration_glyph
from ..core.layout_types import LayoutEvent
from .primitives import use_element


@dataclass(frozen=True, slots=True)
class DecorationPlacement:
    """Host-relative coordinates for a score decoration.

    Decoration X is host-relative.  The postfix hairpin terminator is the one
    source-owned dynamic exception: its mark shares the terminator's left lane.
    """

    x_offset: float = 0.0
    y_offset: int = 0


def upper_clearance_levels(event: MusicEvent, *, starts_upper_span: bool = False) -> int:
    """Return semantic clearance levels above a note for attached marks.

    Positive octave marks occupy one 8px lane each.  An opening tie or slur
    occupies one additional lane.  Modifier constructs whose source contains
    an explicit span opener pass ``starts_upper_span`` because that opener is a
    separate parser event rather than a role on the host note.
    """

    role_start = any(
        role.split(":")[-1] == "start"
        and any(part in {"tie", "slur"} for part in role.split(":")[:-1])
        for role in event.construct_roles
    )
    return max(event.octave, 0) + int(starts_upper_span or role_start)


def decoration_placement(
    event: MusicEvent,
    decoration: str,
    *,
    decorations: tuple[str, ...] = (),
    starts_upper_span: bool = False,
) -> DecorationPlacement:
    """Resolve one decoration's host-relative SVG placement.

    This is shared by inline note decorations, late dynamics, and standalone
    decoration marks.  The reference uses a small set of semantic lanes:
    dynamics sit three pixels above the host, while octave/span clearance
    moves them another eight pixels per occupied lane.
    """

    if is_dynamic_decoration(decoration):
        if event.raw.endswith(">"):
            return DecorationPlacement(x_offset=-25.0, y_offset=-18)
        return DecorationPlacement(
            y_offset=-3 - 8 * upper_clearance_levels(
                event,
                starts_upper_span=starts_upper_span,
            )
        )
    positive_octaves = max(event.octave, 0)
    if decoration == "sby":
        return DecorationPlacement(y_offset=-8 * positive_octaves)
    if decoration == "yc":
        stacked_offset = 12 if "sby" in decorations else 0
        return DecorationPlacement(y_offset=-max(8 * positive_octaves, stacked_offset))
    return DecorationPlacement()


def event_accessory_item_elements(
    item: LayoutEvent,
    event: MusicEvent,
    *,
    include_decorations: bool,
) -> list[SvgElement]:
    """Build the accessory/decorative elements for one event."""

    if include_decorations:
        return event_decoration_item_elements(item, event, phase="all")
    return [
        *event_pitch_accessory_item_elements(item, event),
        *event_augmentation_dot_item_elements(item, event),
    ]


def event_pitch_accessory_item_elements(
    item: LayoutEvent,
    event: MusicEvent,
) -> list[SvgElement]:
    """Build octave and accidental elements emitted before the event glyph."""

    elements: list[SvgElement] = []
    # The reference renders the octave dot of a ``4`` two-and-a-half pixels to
    # the right of the note anchor while every other digit keeps the dot on the
    # anchor (census 2026-08-23: all 200 reference dots on ``4'``/``4,`` sit at
    # note_x + 2.5 px; all 4,685 dots on other digits sit at note_x exactly).
    x = item.x + (2.5 if (event.code or "").startswith("4") else 0.0)
    y = int(item.y) + (2 if item.block in {"bz", "bz-hidden"} else 0)

    if event.octave > 0:
        for offset in range(event.octave):
            elements.append(
                use_element(
                    "yingao_gao",
                    x=_format_reference_number(x),
                    y=y - 8 * offset,
                    layer="accessory",
                    source_event_index=event.index,
                )
            )
    elif event.octave < 0:
        # The reference stacks low-octave dots six pixels apart (census
        # 2026-08-23: all 28 double ``yingao_di`` notes in the corpus sit at
        # note_y + 1 + 4*slashes and +6 below it), unlike the eight-pixel
        # lanes used for high-octave dots.
        for offset in range(-event.octave):
            elements.append(
                use_element(
                    "yingao_di",
                    x=_format_reference_number(x),
                    y=y + 1 + 4 * event.duration_slashes + 6 * offset,
                    layer="accessory",
                    source_event_index=event.index,
                )
            )
    if "ykh" in event.decorations:
        return elements
    accidental_element = _accidental_item_element(item, event)
    if accidental_element is not None:
        elements.append(accidental_element)
    return elements


def event_deferred_accidental_item_elements(
    item: LayoutEvent,
    event: MusicEvent,
) -> list[SvgElement]:
    """Build the accidental deferred after a right-hook decoration."""

    if "ykh" not in event.decorations or not event.accidental:
        return []
    accidental_element = _accidental_item_element(item, event)
    return [accidental_element] if accidental_element is not None else []


def _accidental_item_element(item: LayoutEvent, event: MusicEvent) -> SvgElement | None:
    """Build one note accidental at the host note's SVG coordinate."""

    if not event.accidental:
        return None
    accidental = get_accidental_glyph(event.accidental)
    if accidental is None:
        return None
    return use_element(
        accidental,
        x=_format_reference_number(item.x),
        y=int(item.y),
        layer="accessory",
        source_event_index=event.index,
    )


def event_augmentation_dot_item_elements(
    item: LayoutEvent,
    event: MusicEvent,
) -> list[SvgElement]:
    """Build duration-dot elements in source decoration order."""

    elements: list[SvgElement] = []
    x = item.x
    y = int(item.y)
    for offset in range(event.duration_dots):
        elements.append(
            use_element(
                "fudian",
                x=_format_reference_number(x + offset * 6),
                y=y,
                layer="accessory",
                source_event_index=event.index,
                extra_attrs=(("data-construct", "augmentation-dot"),),
            )
        )
    return elements


def event_decoration_item_elements(
    item: LayoutEvent,
    event: MusicEvent,
    *,
    phase: str,
) -> list[SvgElement]:
    """Build decorations for the opening, deferred, or complete phase."""

    elements: list[SvgElement] = []
    x = item.x
    y = int(item.y)
    for decoration in ordered_decorations(event.decorations):
        if phase == "opening" and decoration != "zkh":
            continue
        if phase == "deferred" and decoration == "zkh":
            continue
        if phase in {"opening", "deferred"} and is_dynamic_decoration(decoration):
            continue
        if decoration == "zkh":
            elements.append(
                use_element(
                    left_parenthesis_glyph_id(item, event),
                    x=_format_reference_number(x),
                    y=y,
                    layer="decoration",
                    source_event_index=event.index,
                )
            )
            continue
        if decoration == "ykh":
            elements.append(
                use_element(
                    "kuohu_you",
                    x=_format_reference_number(x),
                    y=y,
                    layer="decoration",
                    source_event_index=event.index,
                )
            )
            continue
        glyph_id = get_decoration_glyph(decoration)
        if glyph_id:
            placement = decoration_placement(
                event,
                decoration,
                decorations=event.decorations,
            )
            elements.append(
                use_element(
                    glyph_id,
                    x=_format_reference_number(x + placement.x_offset),
                    y=y + placement.y_offset,
                    layer="decoration",
                    source_event_index=event.index,
                )
            )
    return elements


def event_dynamic_decoration_item_elements(
    item: LayoutEvent,
    event: MusicEvent,
) -> list[SvgElement]:
    """Build late dynamic markings such as ``mp`` and ``rit``.

    A hairpin attached to the same note occupies the mark's lane, so the
    reference slides the dynamic twenty-five pixels left and seven more up
    (Looking-Back - Choir p2/p3: all three corpus ``&mf>`` notes place their
    ``mf`` at note_x - 25 / row_y - 18 instead of the plain lane).
    """

    elements: list[SvgElement] = []
    for decoration in event.decorations:
        if not is_dynamic_decoration(decoration):
            continue
        glyph_id = get_decoration_glyph(decoration)
        if glyph_id is None:
            continue
        placement = decoration_placement(
            event,
            decoration,
            decorations=event.decorations,
        )
        elements.append(
            use_element(
                glyph_id,
                x=_format_reference_number(item.x + placement.x_offset),
                y=int(item.y) + placement.y_offset,
                layer="decoration",
                source_event_index=event.index,
            )
        )
    return elements


def ordered_decorations(decorations: tuple[str, ...]) -> tuple[str, ...]:
    """Keep opening hooks before closing hooks and other decorations."""

    ordered = sorted(
        enumerate(decorations),
        key=lambda item: decoration_order_key(item[1], item[0]),
    )
    return tuple(decoration for _index, decoration in ordered)


def decoration_order_key(decoration: str, index: int) -> tuple[int, int]:
    if decoration == "zkh":
        return (0, index)
    if decoration == "ykh":
        return (1, index)
    return (2, index)


def is_dynamic_decoration(decoration: str) -> bool:
    glyph_id = get_decoration_glyph(decoration)
    return glyph_id is not None and glyph_id.startswith("lidu_")


def left_parenthesis_glyph_id(item: LayoutEvent, event: MusicEvent) -> str:
    if item.block in {"bz", "bz-hidden"}:
        return "kuohu_zuo_bian"
    accessory_glyph_id = event_glyph_id_for_accessory(item, event)
    if event.pitch is not None and accessory_glyph_id.startswith("shuzi_b_bian_"):
        return "kuohu_zuo_bian"
    return "kuohu_zuo"


def event_glyph_id_for_accessory(item: LayoutEvent, event: MusicEvent) -> str:
    if item.block in {"bz", "bz-hidden"} and event.kind in {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.HIDDEN_REST,
    }:
        pitch = event.pitch if event.pitch is not None else 0
        return f"shuzi_b_bian_{pitch}"
    return ""


__all__ = [
    "DecorationPlacement",
    "decoration_placement",
    "decoration_order_key",
    "event_accessory_item_elements",
    "event_augmentation_dot_item_elements",
    "event_decoration_item_elements",
    "event_deferred_accidental_item_elements",
    "event_dynamic_decoration_item_elements",
    "event_glyph_id_for_accessory",
    "event_pitch_accessory_item_elements",
    "is_dynamic_decoration",
    "left_parenthesis_glyph_id",
    "ordered_decorations",
    "upper_clearance_levels",
]
