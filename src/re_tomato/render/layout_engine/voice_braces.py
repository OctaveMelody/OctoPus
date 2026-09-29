"""Voice-brace geometry and voice captions for multi-voice systems."""

from __future__ import annotations

import re

from re_tomato.normalization.types import SystemModel
from re_tomato.render.core.layout_types import (
    LayoutEvent,
    LayoutPage,
    LayoutVoiceBrace,
    LayoutVoiceCaption,
)

from ...parser.ast import MusicTokenKind

# A barline followed by a postfix accidental pulls the brace left by five
# natural units; captions remain on the unshifted system anchor.
VOICE_BRACE_ACCIDENTAL_INDENT = 5.0
_POSTFIX_ACCIDENTAL_RE = re.compile(r"[0-9][#$=]")


def collect_voice_braces(
    layout: LayoutPage,
    system: SystemModel,
    system_events: list[LayoutEvent],
    system_left: float,
) -> None:
    """Append contiguous non-primary voice runs as brace geometry.

    Each brace run also yields one right-aligned caption per line, at the
    reference offset of 35 px left of the brace. Numbered voice lines without
    a declared label still emit an empty caption.
    """

    rows: dict[int, float] = {}
    first_x: dict[int, float] = {}
    scale_by_line: dict[int, float | None] = {}
    voice_by_line: dict[int, int] = {}
    source_line_by_line: dict[int, int] = {}
    for event in system_events:
        if event.voice >= len(system.voices):
            continue
        if event.line not in scale_by_line:
            scale_by_line[event.line] = event.projection_scale
        if system.voices[event.voice].voice == 0:
            continue
        if event.line not in rows:
            rows[event.line] = event.y
            first_x[event.line] = event.x
            voice_by_line[event.line] = event.voice
            source_line_by_line[event.line] = event.event.span.start.line
    if len(rows) < 2:
        return

    accidental_indent_scale = _accidental_indent_scale(system_events, scale_by_line)

    run: list[int] = []
    previous_line: int | None = None
    for line in sorted(rows):
        if previous_line is not None and line != previous_line + 1:
            _append_voice_brace(
                layout,
                system,
                rows,
                first_x,
                voice_by_line,
                source_line_by_line,
                run,
                system_left,
                accidental_indent_scale,
            )
            run = []
        run.append(line)
        previous_line = line
    _append_voice_brace(
        layout,
        system,
        rows,
        first_x,
        voice_by_line,
        source_line_by_line,
        run,
        system_left,
        accidental_indent_scale,
    )


def _accidental_indent_scale(
    system_events: list[LayoutEvent],
    scale_by_line: dict[int, float | None],
) -> float | None:
    """Return the projection scale for a qualifying first content token."""
    first_content_seen: set[int] = set()
    barline_seen: set[int] = set()
    for event in system_events:
        line = event.line
        if line in first_content_seen:
            continue
        if event.event.kind is MusicTokenKind.BARLINE:
            barline_seen.add(line)
            continue
        first_content_seen.add(line)
        if (
            event.event.kind is not MusicTokenKind.NOTE
            or line not in barline_seen
            or not _POSTFIX_ACCIDENTAL_RE.search(event.event.raw)
        ):
            continue
        scale = scale_by_line.get(line)
        return scale if scale is not None else next(
            (value for value in scale_by_line.values() if value is not None),
            None,
        )
    return None


def _append_voice_brace(
    layout: LayoutPage,
    system: SystemModel,
    rows: dict[int, float],
    first_x: dict[int, float],
    voice_by_line: dict[int, int],
    source_line_by_line: dict[int, int],
    run: list[int],
    system_left: float,
    accidental_indent_scale: float | None,
) -> None:
    if len(run) < 2:
        return
    anchor_x = min(min(first_x[line] for line in run), system_left)
    brace_x = (
        anchor_x - VOICE_BRACE_ACCIDENTAL_INDENT * accidental_indent_scale
        if accidental_indent_scale is not None
        else anchor_x
    )
    layout.voice_braces.append(
        LayoutVoiceBrace(
            x=brace_x,
            y_top=rows[run[0]],
            y_bottom=rows[run[-1]],
            line_start=run[0],
            line_end=run[-1],
        )
    )
    for line in run:
        voice_index = voice_by_line[line]
        voice = system.voices[voice_index]
        name_by_line = dict(voice.line_names)
        layout.voice_captions.append(
            LayoutVoiceCaption(
                x=anchor_x - 35,
                y=rows[line],
                text=name_by_line.get(source_line_by_line[line], ""),
                voice=voice_index,
                line=line,
            )
        )


__all__ = ["collect_voice_braces"]
