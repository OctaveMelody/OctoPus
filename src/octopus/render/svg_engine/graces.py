"""Pure grace-glyph construction helpers."""

from __future__ import annotations

import html

from octopus.normalization.types import MusicEvent, ScoreModel
from octopus.render.core.elements import SvgElement, _format_reference_number
from octopus.render.core.layout_types import LayoutGrace, LayoutPage

from ...parser.ast import MusicTokenKind
from .primitives import use_element as _use_element
from .types import GraceGlyphNote, GraceRenderItem, GraceRenderPlan


def parse_catalog_grace_notes(raw: str) -> tuple[GraceGlyphNote, ...]:
    """Parse the compact catalog grace spelling into glyph-note metadata."""

    content = raw.removeprefix("[").removesuffix("]")
    content = content.removeprefix("h")
    notes: list[GraceGlyphNote] = []
    index = 0
    while index < len(content):
        char = content[index]
        if char not in "1234567":
            index += 1
            continue
        pitch = int(char)
        index += 1
        octave = 0
        duration_slashes = 0
        while index < len(content) and content[index] in "',/":
            marker = content[index]
            if marker == "'":
                octave += 1
            elif marker == ",":
                octave -= 1
            else:
                duration_slashes += 1
            index += 1
        notes.append(GraceGlyphNote(pitch, octave, duration_slashes))
    return tuple(notes)


def generated_grace_glyph(
    glyph_id: str,
    children: tuple[GraceGlyphNote, ...],
    *,
    connector_glyph: str = "yiyinxian_qian",
) -> str:
    """Serialize one generated grace glyph definition."""

    parts: list[str] = [f'<g id="{html.escape(glyph_id)}">']
    if children:
        max_beam_count = max(1, max((child.duration_slashes + 1 for child in children), default=1))
        for beam_index in range(1, max_beam_count + 1):
            parts.extend(generated_grace_beam_lines(children, beam_index))
        for index, child in enumerate(children):
            x = index * 7
            parts.extend(generated_grace_octave_uses(x, child.octave, child.duration_slashes))
            parts.append(
                f'<use x="{format_grace_number(x)}" y="-17" '
                f'xlink:href="#yiyin_shuzi_{child.pitch}" '
                'xmlns:xlink="http://www.w3.org/1999/xlink" ></use>'
            )
    connector_x = {1: -0.5, 2: 3, 3: 6.5}.get(len(children), max(len(children) - 1, 0) * 3.5)
    connector_y = -17 if not children else -15
    if len(children) == 1:
        child = children[0]
        if child.octave < 0:
            lower_y = grace_lower_octave_y(child.duration_slashes)
            connector_y = lower_y + (abs(child.octave) - 1) * 3
            if abs(child.octave) == 1:
                connector_y -= 1
        else:
            connector_y = -17 + child.duration_slashes * 2
    elif any(child.octave < 0 for child in children):
        connector_y = -11
    elif not any(child.duration_slashes for child in children):
        connector_y = -17
    parts.append(
        f'<use x="{format_grace_number(connector_x)}" '
        f'y="{format_grace_number(connector_y)}" '
        f'xlink:href="#{connector_glyph}" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" ></use>'
    )
    parts.append("</g>")
    return "".join(parts)


def generated_grace_beam_lines(
    children: tuple[GraceGlyphNote, ...],
    beam_index: int,
) -> list[str]:
    lines: list[str] = []
    start: int | None = None
    for index, child in enumerate(children):
        if beam_index <= child.duration_slashes + 1:
            if start is None:
                start = index
            continue
        if start is not None:
            lines.append(generated_grace_beam_line(start, index - 1, beam_index))
            start = None
    if start is not None:
        lines.append(generated_grace_beam_line(start, len(children) - 1, beam_index))
    return lines


def generated_grace_beam_line(start_index: int, end_index: int, beam_index: int) -> str:
    y = -10.5 + (beam_index - 1) * 2
    return (
        f'<line x1="{format_grace_number(start_index * 7 - 3.5)}" '
        f'y1="{format_grace_number(y)}" '
        f'x2="{format_grace_number(end_index * 7 + 3.5)}" '
        f'y2="{format_grace_number(y)}" stroke-width="1" stroke="#1b1b1b" ></line>'
    )


def generated_grace_octave_uses(x: int, octave: int, duration_slashes: int) -> list[str]:
    glyph_id = "yiyin_yingao_gao" if octave > 0 else "yiyin_yingao_di"
    y = -18 if octave > 0 else grace_lower_octave_y(duration_slashes)
    return [
        f'<use x="{format_grace_number(x)}" '
        f'y="{format_grace_number(y + step * (-4 if octave > 0 else 3))}" '
        f'xlink:href="#{glyph_id}" xmlns:xlink="http://www.w3.org/1999/xlink" ></use>'
        for step in range(abs(octave))
    ]


def grace_lower_octave_y(duration_slashes: int) -> int:
    return -12 + duration_slashes * 2


def format_grace_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"




_SIMPLE_GRACE_GLYPHS: dict[str, str] = {
    "[1/]": "qy0_0",
    "[1]": "qy1_0",
    "[h1]": "hy2_0",
    "[h1/]": "hy3_0",
    "[1,/]": "qy4_0",
    "[1,]": "qy5_0",
    "[h1,,]": "hy6_0",
    "[h1,,/]": "hy7_0",
    "[1'/]": "qy8_0",
    "[1'']": "qy9_0",
    "[h1']": "hy10_0",
    "[h1''/]": "hy11_0",
    "[23]": "qy84_0",
    "[23/4]": "qy85_0",
    "[3/4/]": "qy86_0",
    "[45/]": "qy87_0",
    "[5/6]": "qy88_0",
    "[1/2/3/]": "qy89_0",
    "[5/67/]": "qy90_0",
    "[h23]": "hy91_0",
    "[h23/4]": "hy92_0",
    "[h3/4/]": "hy93_0",
    "[h45/]": "hy94_0",
    "[h5/6]": "hy95_0",
    "[h1/2/3/]": "hy96_0",
    "[h5/67/]": "hy97_0",
}
for _pitch in range(2, 8):
    _base = (_pitch - 1) * 12
    _SIMPLE_GRACE_GLYPHS.update(
        {
            f"[{_pitch}]": f"qy{_base}_0",
            f"[{_pitch}/]": f"qy{_base + 1}_0",
            f"[h{_pitch}]": f"hy{_base + 2}_0",
            f"[h{_pitch}/]": f"hy{_base + 3}_0",
            f"[{_pitch},]": f"qy{_base + 4}_0",
            f"[{_pitch},,/]": f"qy{_base + 5}_0",
            f"[h{_pitch},]": f"hy{_base + 6}_0",
            f"[h{_pitch},,/]": f"hy{_base + 7}_0",
            f"[{_pitch}']": f"qy{_base + 8}_0",
            f"[{_pitch}''/]": f"qy{_base + 9}_0",
            f"[h{_pitch}']": f"hy{_base + 10}_0",
            f"[h{_pitch}''/]": f"hy{_base + 11}_0",
        }
    )
del _pitch, _base


_generated_grace_glyph_impl = generated_grace_glyph
_parse_catalog_grace_notes_impl = parse_catalog_grace_notes


def _grace_elements(plan: GraceRenderPlan) -> list[SvgElement]:
    return [
        element
        for elements in _grace_elements_by_host(plan).values()
        for element in elements
    ]


def _grace_elements_by_host(
    plan: GraceRenderPlan,
) -> dict[tuple[int, int, int], tuple[SvgElement, ...]]:
    grouped: dict[tuple[int, int, int], list[SvgElement]] = {}
    for item in plan.items:
        grace = item.grace
        host_key = (grace.host.voice, grace.host.line, grace.host.slot)
        if item.uses_catalog_glyph:
            x = (
                grace.host.x + 15
                if grace.raw.startswith("[h")
                else grace.host.x - 5 - 7 * item.child_count
            )
        else:
            x = grace.host.x - (5 + 7 * item.child_count)
        y = grace.host.y
        grouped.setdefault(host_key, []).append(
            _use_element(
                item.glyph_id,
                x=_format_reference_number(x),
                y=_format_reference_number(y),
                layer="grace",
                source_event_index=grace.host.event.index,
                construct_ids=grace.host.event.construct_ids,
                extra_attrs=(("data-construct", "grace"),),
            )
        )
    return {host_key: tuple(items) for host_key, items in grouped.items()}


def _grace_group_glyph_id(raw: str) -> str | None:
    return _SIMPLE_GRACE_GLYPHS.get(raw)


def _grace_render_plan(
    model: ScoreModel,
    layout: LayoutPage,
    page_index: int,
) -> GraceRenderPlan:
    if _uses_catalog_grace_glyphs(layout):
        items = tuple(
            GraceRenderItem(grace, glyph_id, _grace_note_count(grace), uses_catalog_glyph=True)
            for grace in layout.graces
            if (glyph_id := _grace_group_glyph_id(grace.raw)) is not None
        )
        return GraceRenderPlan(items)
    return _normal_grace_render_plan(layout, page_index)


def _normal_grace_render_plan(layout: LayoutPage, page_index: int) -> GraceRenderPlan:
    items: list[GraceRenderItem] = []
    defs: list[str] = []
    for index, grace in enumerate(layout.graces):
        children = tuple(
            GraceGlyphNote(child.pitch, child.octave, child.duration_slashes)
            for child in _valid_grace_children(grace)
            if child.pitch is not None
        )
        if not children:
            continue
        glyph_id = f"qy{index}_{page_index}"
        items.append(GraceRenderItem(grace, glyph_id, max(len(children), 1)))
        defs.append(_generated_grace_glyph_impl(glyph_id, children))
    return GraceRenderPlan(tuple(items), tuple(defs))


def _uses_catalog_grace_glyphs(layout: LayoutPage) -> bool:
    """Recognize a complete homogeneous grace sample row from its structure."""

    musical_host_keys = {
        (item.voice, item.line, item.slot)
        for item in layout.events
        if item.event.kind
        in {
            MusicTokenKind.NOTE,
            MusicTokenKind.REST,
            MusicTokenKind.RHYTHM_NOTE,
            MusicTokenKind.HIDDEN_REST,
            MusicTokenKind.EXTENSION,
        }
    }
    raw_values = tuple(grace.raw for grace in layout.graces)
    hosts = tuple(
        (grace.host.voice, grace.host.line, grace.host.slot)
        for grace in layout.graces
    )
    if (
        not raw_values
        or set(hosts) != musical_host_keys
        or len(set(raw_values)) != len(raw_values)
        or not all(raw in _SIMPLE_GRACE_GLYPHS for raw in raw_values)
    ):
        return False

    coverage = {
        (raw.startswith("[h"), len(parse_catalog_grace_notes(raw)))
        for raw in raw_values
    }
    max_arity = max((arity for _, arity in coverage), default=0)
    if max_arity < 2:
        return False
    required_coverage = {
        (is_half, arity)
        for arity in range(1, max_arity + 1)
        for is_half in (False, True)
    }
    return coverage == required_coverage


def _valid_grace_children(grace: LayoutGrace) -> tuple[MusicEvent, ...]:
    return tuple(child for child in grace.children if child.pitch not in {None, 8, 9})


def _grace_note_count(grace: LayoutGrace) -> int:
    return max(len(_valid_grace_children(grace)), 1)


def _catalog_grace_defs_by_id() -> dict[str, str]:
    return {
        glyph_id: _generated_grace_glyph_impl(
            glyph_id,
            _parse_catalog_grace_notes_impl(raw),
            connector_glyph="yiyinxian_hou" if raw.startswith("[h") else "yiyinxian_qian",
        )
        for raw, glyph_id in _SIMPLE_GRACE_GLYPHS.items()
    }


__all__ = [
    "format_grace_number",
    "generated_grace_beam_line",
    "generated_grace_beam_lines",
    "generated_grace_glyph",
    "generated_grace_octave_uses",
    "grace_lower_octave_y",
    "parse_catalog_grace_notes",
]
