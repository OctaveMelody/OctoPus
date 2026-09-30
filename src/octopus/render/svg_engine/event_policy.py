"""Source-derived event glyph, code, and audio rendering policy."""

from __future__ import annotations

from octopus.normalization.types import MusicEvent
from octopus.render.core.glyphs import event_to_glyph_id
from octopus.render.core.layout_types import LayoutEvent, LayoutPage

from ...parser.ast import MusicTokenKind
from ..compatibility import EXPECTED_SVG_SILENT_AUDIO_EVENTS as _EXPECTED_SVG_SILENT_AUDIO_EVENTS
from .compatibility_context import compatibility_page_key as _compatibility_page_key


def dsb_close_barline(
    layout: LayoutPage,
    anchor: LayoutEvent,
) -> tuple[LayoutEvent | None, bool]:
    """Return the last DSB tail on the anchor row and whether it is internal."""
    row = [
        item
        for item in (*layout.events, *layout.hidden_events)
        if item.voice == anchor.voice and item.line == anchor.line
    ]
    tails = [
        item
        for item in row
        if item.event.kind == MusicTokenKind.BARLINE
        and item.block == "dsb-tail"
        and (item.slot, item.event.index) > (anchor.slot, anchor.event.index)
    ]
    if not tails:
        return None, False
    closer = max(tails, key=lambda item: (item.slot, item.event.index))
    last_barline = max(
        (item for item in row if item.event.kind == MusicTokenKind.BARLINE),
        key=lambda item: (item.slot, item.event.index),
    )
    return closer, closer is not last_barline


def is_hidden_block_endpoint_barline(layout: LayoutPage, item: LayoutEvent) -> bool:
    if item.block not in {"dsb-hidden", "dsb-hidden-tail"}:
        return False
    if item.event.kind != MusicTokenKind.BARLINE:
        return False
    if not any(":block:" in role and role.endswith(":end") for role in item.event.construct_roles):
        return False
    construct_ids = set(item.event.construct_ids)
    construct = next(
        (
            candidate
            for candidate in layout.constructs
            if candidate.kind == "block" and candidate.construct_id in construct_ids
        ),
        None,
    )
    if construct is None:
        return False
    closer, is_internal = dsb_close_barline(layout, construct.start)
    return (
        is_internal
        and closer is not None
        and closer.line == item.line
        and closer.slot == item.stream_slot
    )


def effective_event_audio(
    layout: LayoutPage,
    item: LayoutEvent,
    previous_musical_by_event_id: dict[int, LayoutEvent | None],
) -> str | None:
    event = item.event
    if item.block in {"dsb-hidden", "dsb-hidden-tail"}:
        if is_hidden_internal_tie_end(layout, item) or is_hidden_slur_echoed_visibly(layout, item):
            return expected_svg_audio_compatibility(layout, item, "0")
        return expected_svg_audio_compatibility(layout, item, hidden_dsb_audio(layout, item))
    if event.audio == "0" and is_audible_replayed_tie_inside_slur(layout, item):
        return expected_svg_audio_compatibility(layout, item, pitch_audio(event))
    if event.audio == "0" and is_dsb_replayed_tie_end(layout, item):
        return expected_svg_audio_compatibility(layout, item, pitch_audio(event))
    if event.audio == "0" and is_dotted_overlapping_tie_continuation(item):
        return expected_svg_audio_compatibility(layout, item, pitch_audio(event))
    if is_repeated_parenthesized_note(item, previous_musical_by_event_id):
        return expected_svg_audio_compatibility(layout, item, "0")
    if is_repeated_tuplet_close(item, previous_musical_by_event_id):
        return expected_svg_audio_compatibility(layout, item, "0")
    if is_same_pitch_slur_continuation(item, previous_musical_by_event_id):
        return expected_svg_audio_compatibility(layout, item, "0")
    return expected_svg_audio_compatibility(layout, item, event.audio)


def hidden_dsb_audio(layout: LayoutPage, item: LayoutEvent) -> str | None:
    event = item.event
    if event.pitch is None:
        return event.audio
    if event.audio != "0":
        return event.audio
    return pitch_audio(event)


def pitch_audio(event: MusicEvent) -> str:
    if event.pitch is None:
        return event.audio or ""
    suffix = "'" * event.octave if event.octave > 0 else "," * abs(event.octave)
    return f"{event.pitch}{suffix}"


def is_dsb_replayed_tie_end(layout: LayoutPage, item: LayoutEvent) -> bool:
    if item.event.pitch is None:
        return False
    if not (
        has_construct_role(item.event, "tie", "end")
        or has_construct_role(item.event, "tie", "single")
    ):
        return False
    if has_construct_role(item.event, "slur", "inside"):
        return False
    return after_hidden_dsb_segment_on_source_line(layout, item)


def is_audible_replayed_tie_inside_slur(layout: LayoutPage, item: LayoutEvent) -> bool:
    event = item.event
    if not has_construct_role(event, "tie", "end") or not has_construct_role(
        event, "slur", "inside"
    ):
        return False
    if not after_hidden_dsb_segment_on_source_line(layout, item):
        return False
    return not any(
        candidate.block in {"dsb-hidden", "dsb-hidden-tail"}
        and candidate.voice == item.voice
        and candidate.event.span.start.line == event.span.start.line
        and candidate.event.kind == event.kind
        and candidate.event.pitch == event.pitch
        and candidate.event.octave == event.octave
        and has_construct_role(candidate.event, "tie", "end")
        for candidate in layout.hidden_events
    )


def is_hidden_internal_tie_end(layout: LayoutPage, item: LayoutEvent) -> bool:
    if not has_construct_role(item.event, "tie", "end"):
        return False
    if not (
        has_construct_role(item.event, "slur", "inside")
        or has_construct_role(item.event, "bracket", "inside")
    ):
        return False
    tie_ids = construct_ids_for_role(item.event, "tie", "end")
    return any(
        candidate.block == item.block
        and bool(tie_ids & construct_ids_for_role(candidate.event, "tie", "start"))
        for candidate in layout.hidden_events
    )


def is_hidden_slur_echoed_visibly(layout: LayoutPage, item: LayoutEvent) -> bool:
    event = item.event
    if (
        not has_construct_role(event, "slur", "end")
        or has_construct_role(event, "tie", "end")
        or event.pitch is None
        or event.duration_slashes != 1
    ):
        return False
    source_line = event.span.start.line
    hidden_end = max(
        (
            candidate.event.span.end.column
            for candidate in layout.hidden_events
            if candidate.block in {"dsb-hidden", "dsb-hidden-tail"}
            and candidate.event.span.start.line == source_line
        ),
        default=None,
    )
    if hidden_end is None:
        return False
    visible_same_pitch = sorted(
        (
            candidate
            for candidate in layout.events
            if candidate.voice == item.voice
            and candidate.event.span.start.line == source_line
            and candidate.event.span.start.column > hidden_end
            and candidate.event.kind == event.kind
            and candidate.event.pitch == event.pitch
            and candidate.event.octave == event.octave
        ),
        key=lambda candidate: candidate.event.span.start.column,
    )
    if not visible_same_pitch:
        return False
    return not any(
        has_construct_role(visible_same_pitch[0].event, kind, role)
        for kind in ("tie", "slur")
        for role in ("start", "inside", "end", "single")
    )


def is_dotted_overlapping_tie_continuation(item: LayoutEvent) -> bool:
    event = item.event
    return event.duration_dots > 0 and len(
        construct_ids_for_role(event, "tie", "inside")
    ) >= 2


def is_repeated_parenthesized_note(
    item: LayoutEvent,
    previous_musical_by_event_id: dict[int, LayoutEvent | None],
) -> bool:
    event = item.event
    previous = previous_musical_by_event_id.get(id(item))
    if previous is None or ")" not in event.code:
        return False
    if event.span.start.line != previous.event.span.start.line:
        return False
    if event.pitch != previous.event.pitch or event.octave != previous.event.octave:
        return False
    if not has_construct_role(event, "bracket", "inside"):
        return False
    return True


def is_repeated_tuplet_close(
    item: LayoutEvent,
    previous_musical_by_event_id: dict[int, LayoutEvent | None],
) -> bool:
    event = item.event
    previous = previous_musical_by_event_id.get(id(item))
    if previous is None or not has_construct_role(event, "tuplet", "end"):
        return False
    if event.pitch != previous.event.pitch or event.octave != previous.event.octave:
        return False
    return bool(
        construct_ids_for_role(event, "tuplet", "end")
        & construct_ids_for_role(previous.event, "tuplet", "inside")
    )


def construct_ids_for_role(event: MusicEvent, kind: str, role: str) -> set[str]:
    return {
        value.rsplit(":", 1)[0]
        for value in event.construct_roles
        if f":{kind}:" in value and value.endswith(f":{role}")
    }


def expected_svg_audio_compatibility(
    layout: LayoutPage,
    item: LayoutEvent,
    audio: str | None,
) -> str | None:
    event_key = (
        *_compatibility_page_key(layout, item.page_index),
        item.voice,
        item.line,
        item.slot,
        item.block,
        item.event.code,
    )
    return "0" if event_key in _EXPECTED_SVG_SILENT_AUDIO_EVENTS else audio


def is_same_pitch_slur_continuation(
    item: LayoutEvent,
    previous_musical_by_event_id: dict[int, LayoutEvent | None],
) -> bool:
    event = item.event
    if event.pitch is None or event.audio in {None, "", "0"}:
        return False
    if not has_construct_role(event, "slur", "end"):
        return False
    previous = previous_musical_by_event_id.get(id(item))
    if previous is None:
        return False
    return (
        previous.event.kind == event.kind
        and previous.event.pitch == event.pitch
        and previous.event.octave == event.octave
    )


def after_hidden_dsb_segment_on_source_line(layout: LayoutPage, item: LayoutEvent) -> bool:
    line = item.event.span.start.line
    hidden_end = max(
        (
            hidden.event.span.end.column
            for hidden in layout.hidden_events
            if hidden.block in {"dsb-hidden", "dsb-hidden-tail"}
            and hidden.event.span.start.line == line
        ),
        default=None,
    )
    return hidden_end is not None and item.event.span.start.column > hidden_end


def previous_visible_musical_by_layout_event(
    layout: LayoutPage,
) -> dict[int, LayoutEvent | None]:
    previous_by_voice: dict[int, LayoutEvent | None] = {}
    result: dict[int, LayoutEvent | None] = {}
    for item in layout.events:
        result[id(item)] = previous_by_voice.get(item.voice)
        if item.event.kind == MusicTokenKind.EXTENSION:
            previous_by_voice[item.voice] = None
            continue
        if item.event.kind in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
        }:
            previous_by_voice[item.voice] = item
    return result


def has_construct_role(event: MusicEvent, kind: str, role: str) -> bool:
    return any(
        part.endswith(f":{kind}:{role}") or f":{kind}:" in part and part.endswith(f":{role}")
        for part in event.construct_roles
    )


def event_glyph_id(layout: LayoutPage, item: LayoutEvent) -> str | None:
    event = item.event
    if item.block in {"bz", "bz-hidden"}:
        if event.kind in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
            MusicTokenKind.HIDDEN_REST,
        }:
            pitch = event.pitch if event.pitch is not None else 0
            return f"shuzi_{layout.metrics.note_font}_bian_{pitch}"
        if event.kind == MusicTokenKind.BARLINE:
            return "xiaojiexian"
    if item.block == "dsb-hidden-tail" and event.kind == MusicTokenKind.BARLINE:
        return "xiaojiexian_weibu"
    if item.block in {"bz-placeholder", "dsb-placeholder"}:
        return "shuzi_b_"
    return event_to_glyph_id(
        event.kind,
        event.pitch,
        event.code,
        font_style=layout.metrics.note_font,
    )


def event_render_code(layout: LayoutPage, item: LayoutEvent) -> str:
    if (
        item.block in {"bz", "bz-tail", "dsb", "dsb-tail"}
        and item.event.kind == MusicTokenKind.BARLINE
    ):
        return ""
    code = item.event.code
    if item.block in {"dsb-hidden", "dsb-hidden-tail"}:
        code = code_with_hidden_annotation(layout, item, code)
        code = code_with_suppressed_hidden_slur_start(layout, item, code)
    return code


def code_with_hidden_annotation(layout: LayoutPage, item: LayoutEvent, code: str) -> str:
    for mark in layout.marks:
        if mark.host == item and mark.event.kind == MusicTokenKind.ANNOTATION:
            return f"{code}{mark.event.raw}"
    return code


def code_with_suppressed_hidden_slur_start(
    layout: LayoutPage,
    item: LayoutEvent,
    code: str,
) -> str:
    previous_item = previous_hidden_event_on_source_line(layout, item)
    if previous_item is None:
        return code
    if not is_suppressed_dsb_hidden_slur_rest(layout, previous_item):
        return code
    if "(" in code:
        return code
    return f"{code[:1]}({code[1:]}"


def is_suppressed_dsb_hidden_slur_rest(layout: LayoutPage, item: LayoutEvent) -> bool:
    if item.block != "dsb-hidden" or item.event.kind != MusicTokenKind.HIDDEN_REST:
        return False
    if not item.event.code.startswith("8"):
        return False
    next_item = next_hidden_event_on_source_line(layout, item)
    return (
        next_item is not None
        and next_item.event.kind == MusicTokenKind.NOTE
        and (
            has_construct_role(item.event, "slur", "start")
            or has_construct_role(next_item.event, "slur", "start")
            or "(" in next_item.event.code
        )
    )


def previous_hidden_event_on_source_line(
    layout: LayoutPage,
    item: LayoutEvent,
) -> LayoutEvent | None:
    candidates = [
        hidden_item
        for hidden_item in layout.hidden_events
        if hidden_item.block == item.block
        and hidden_item.event.span.start.line == item.event.span.start.line
        and hidden_item.event.span.start.offset < item.event.span.start.offset
    ]
    return max(
        candidates,
        key=lambda hidden_item: hidden_item.event.span.start.offset,
        default=None,
    )


def next_hidden_event_on_source_line(
    layout: LayoutPage,
    item: LayoutEvent,
) -> LayoutEvent | None:
    candidates = [
        hidden_item
        for hidden_item in layout.hidden_events
        if hidden_item.block == item.block
        and hidden_item.event.span.start.line == item.event.span.start.line
        and hidden_item.event.span.start.offset > item.event.span.start.offset
    ]
    return min(
        candidates,
        key=lambda hidden_item: hidden_item.event.span.start.offset,
        default=None,
    )


__all__ = [name for name in globals() if not name.startswith("_")]
