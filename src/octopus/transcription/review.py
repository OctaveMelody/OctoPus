"""Review evidence from classifier scores and the draft's own render topology."""

from __future__ import annotations

import math
from dataclasses import dataclass

from octopus.model import normalize_code
from octopus.parser import parse_code
from octopus.parser.ast import MusicLine, MusicTokenKind
from octopus.render.svg import render_score_model_page_with_layout

from .components import Box
from .image import PageObservation

LOW_NOTE_CONFIDENCE = 0.90
_NOTES = {MusicTokenKind.NOTE, MusicTokenKind.REST}


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    code: str
    page: int
    detail: str
    regions: tuple[Box, ...] = ()
    confidence: float | None = None
    source_start: int | None = None
    source_end: int | None = None


@dataclass(frozen=True, slots=True)
class RowBinding:
    page: int
    row: int
    source_line: int
    simple: bool


def finite_confidence(value: float) -> float:
    """Export a finite agreement score; it is not a calibrated probability."""
    return min(1.0, max(0.0, value)) if math.isfinite(value) else 0.0


def note_confidence_findings(
    code: str, pages: tuple[PageObservation, ...], bindings: tuple[RowBinding, ...],
) -> tuple[ReviewFinding, ...]:
    lines = {line.span.start.line: line for line in parse_code(code).lines
             if isinstance(line, MusicLine)}
    by_row = {(binding.page, binding.row): binding for binding in bindings}
    result = []
    for page_index, page in enumerate(pages, start=1):
        for row_index, row in enumerate((*page.rows, *(bz.row for bz in page.bz_overlays))):
            binding = by_row.get((page_index, row_index))
            tokens = tuple(token for token in lines[binding.source_line].tokens
                           if token.kind in _NOTES) if binding and binding.simple else ()
            mapped = len(tokens) == len(row.notes) and all(
                str(token.pitch) == note.digit
                for token, note in zip(tokens, row.notes, strict=True)
            )
            for index, note in enumerate(row.notes):
                score = finite_confidence(note.confidence)
                if score >= LOW_NOTE_CONFIDENCE:
                    continue
                token = tokens[index] if mapped else None
                result.append(ReviewFinding(
                    "low_note_confidence", page_index,
                    f"Digit {note.digit} has classifier agreement {score:.2f}; "
                    "verify its pitch and modifiers against the scan. "
                    "This score is not a calibrated probability.",
                    (note.box,), score,
                    token.span.start.offset if token else None,
                    token.span.end.offset if token else None,
                ))
    return tuple(result)


def _spacing_mismatch(observed: tuple[float, ...], rendered: tuple[float, ...]) -> bool:
    """Require several large interior discrepancies after removing scale/translation."""
    if len(observed) < 4 or len(observed) != len(rendered):
        return False
    left, right = observed[0], observed[-1]
    render_left, render_right = rendered[0], rendered[-1]
    if right <= left or render_right <= render_left:
        return False
    errors = [abs((x - left) / (right - left)
                  - (rx - render_left) / (render_right - render_left))
              for x, rx in zip(observed[1:-1], rendered[1:-1], strict=True)]
    return bool(errors) and max(errors) > 0.30 and sum(error > 0.20 for error in errors) >= 2


def render_back_findings(
    code: str, pages: tuple[PageObservation, ...], bindings: tuple[RowBinding, ...],
) -> tuple[ReviewFinding, ...]:
    """Diagnose dropped/wrapped/reordered notes and severe within-measure spacing drift.

    Engraving changes scale and spacing, so absolute pixel differences are not errors.
    Hidden branches and grace streams have separate ownership and are deliberately not
    compared with a main-row projection. Findings never alter recognized notation.
    """
    if not bindings:
        return ()
    checking_page = 1
    try:
        model = normalize_code(code)
        rendered_by_line: dict[int, dict[int, tuple[float, float]]] = {}
        for page_index in range(len(model.pages)):
            checking_page = min(page_index + 1, len(pages))
            _svg, layout = render_score_model_page_with_layout(model, page_index)
            for item in layout.events:
                if item.event.kind in _NOTES and item.block is None:
                    rendered_by_line.setdefault(item.event.span.start.line, {})[
                        item.event.span.start.offset
                    ] = (item.x, item.y)
    except (ValueError, RuntimeError, IndexError, ZeroDivisionError) as error:
        return (ReviewFinding(
            "render_back_unavailable", checking_page,
            f"Draft render consistency could not be checked: {type(error).__name__}. "
            "Review parser diagnostics and the rendered result.",
        ),)
    result = []
    for binding in bindings:
        if not binding.simple:
            continue
        row = pages[binding.page - 1].rows[binding.row]
        actual = tuple(position for _, position in sorted(
            rendered_by_line.get(binding.source_line, {}).items()
        ))
        if len(actual) != len(row.notes):
            result.append(ReviewFinding(
                "render_back_note_count", binding.page,
                "The rendered draft contains a different main-note count than the "
                "detected row. Check segmentation and block ownership.", (row.box,),
            ))
            continue
        if len({round(y, 3) for _, y in actual}) > 1:
            result.append(ReviewFinding(
                "render_back_row_split", binding.page,
                "One detected music row wraps into several rendered rows; check note "
                "segmentation, durations and page width.", (row.box,),
            ))
            continue
        if any(right[0] <= left[0] for left, right in zip(actual, actual[1:], strict=False)):
            result.append(ReviewFinding(
                "render_back_note_order", binding.page,
                "Rendered main-note columns overlap or reverse their observed order; "
                "check grouping and rhythm.", (row.box,),
            ))
            continue
        # Compare only interior closed measures with enough note columns. Sparse
        # measures, unobserved boundaries and legal shared-voice spacing stay silent.
        for left, right in zip(row.barlines, row.barlines[1:], strict=False):
            selected = [index for index, note in enumerate(row.notes)
                        if left < (note.box[0] + note.box[2]) / 2 < right]
            if len(selected) < 4:
                continue
            observed = tuple((row.notes[index].box[0] + row.notes[index].box[2]) / 2
                             for index in selected)
            projected = tuple(actual[index][0] for index in selected)
            if _spacing_mismatch(observed, projected):
                result.append(ReviewFinding(
                    "render_back_spacing_review", binding.page,
                    "Several note columns in this measure differ strongly from the "
                    "scan after scale/translation normalization. Check rhythm and "
                    "segmentation; ordinary engraving differences remain possible.",
                    tuple(row.notes[index].box for index in selected),
                ))
    return tuple(result)
