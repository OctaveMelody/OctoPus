"""Identify compact accompaniment rows without requiring a smaller printed font."""

from __future__ import annotations

from statistics import median

from PIL import Image

from .components import Box, Component
from .marks import row_parentheses, vertical_bend
from .voices import VoiceGroup


def bracketed_row_centers(
    components: list[Component], height: int, gray: Image.Image,
) -> tuple[float, ...]:
    """Seed short accompaniment rows missed by the full-width digit-template gate."""
    centers = []
    braces = [component for component in components if (
        component.box[0] < gray.width * 0.22
        and height * 0.25 <= component.width <= height * 1.5
        and component.height >= height * 3
        and component.height >= component.width * 6
    )]
    for bracket in components:
        if not (height * 0.9 <= bracket.height <= height * 2.2
                and bracket.width <= height * 0.65
                and bracket.area <= bracket.width * bracket.height * 0.6):
            continue
        bend = vertical_bend(bracket, gray)
        if bend is None or abs(bend) < max(1.25, bracket.width * 0.25):
            continue
        if not any(0 < brace.box[1] - bracket.center_y < height * 3.5
                   and brace.box[2] < bracket.box[0] for brace in braces):
            continue
        glyphs = sorted((component for component in components if (
            height * 0.8 <= component.height <= height * 1.2
            and height * 0.2 <= component.width <= height
            and abs(component.center_y - bracket.center_y) <= height * 0.5
            and (component.box[0] >= bracket.box[2] if bend < 0
                 else component.box[2] <= bracket.box[0])
        )), key=lambda component: component.box[0])
        if len(glyphs) < 4:
            continue
        xs = [(component.box[0] + component.box[2]) / 2 for component in glyphs]
        if median(b - a for a, b in zip(xs, xs[1:], strict=False)) <= height * 1.7:
            centers.append(median(component.center_y for component in glyphs))
    return tuple(dict.fromkeys(centers))


def compact_accompaniment_owner(
    notes: tuple[Box, ...], rows: tuple[tuple[Box, ...], ...],
    groups: tuple[VoiceGroup, ...], components: list[Component], gray: Image.Image,
) -> int | None:
    """Require a dense bracketed row above the first voice of a printed system.

    A scan can print accompaniment and melody digits at the same height. Size alone
    cannot determine ownership; the nearby enclosing parenthesis, tighter spacing
    and independently observed system brace supply that evidence instead.
    """
    if len(notes) < 4:
        return None
    height = median(box[3] - box[1] for box in notes)
    centers = [(box[0] + box[2]) / 2 for box in notes]
    spacing = median(b - a for a, b in zip(centers, centers[1:], strict=False))
    if spacing > height * 1.7 or not row_parentheses(notes, height, components, gray):
        return None
    y = median((box[1] + box[3]) / 2 for box in notes)
    owners = []
    for group in groups:
        index = group.rows[0]
        host = rows[index]
        if len(host) < 2:
            continue
        host_height = median(box[3] - box[1] for box in host)
        host_y = median((box[1] + box[3]) / 2 for box in host)
        host_centers = [(box[0] + box[2]) / 2 for box in host]
        host_spacing = median(b - a for a, b in zip(
            host_centers, host_centers[1:], strict=False,
        ))
        if (
            host_height * 1.3 < host_y - y < host_height * 3.5
            and height <= host_height * 1.15
            and spacing < host_spacing * 0.7
            and host[0][0] - host_height * 0.6 <= notes[0][0] < host[-1][2]
            and notes[-1][2] <= host[-1][2] + host_height * 1.5
            and y < group.box[1]
        ):
            owners.append((host_y - y, index))
    return min(owners)[1] if owners else None
