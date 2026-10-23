"""Review evidence from classifier scores and the draft's own render topology."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from statistics import median

from octopus.model import normalize_code
from octopus.parser import parse_code
from octopus.parser.ast import HeaderLine, MusicLine, MusicToken, MusicTokenKind
from octopus.render.core.layout_types import LayoutPage
from octopus.render.svg import render_score_model_page_with_layout

from .components import Box
from .image import MusicRow, PageObservation
from .results import RowBinding, finite_confidence

LOW_NOTE_CONFIDENCE = 0.90
_NOTES = {MusicTokenKind.NOTE, MusicTokenKind.REST}
_VISIBLE_BARS = {"|", "||", "|:", ":|", ":|:", "||/"}
_TEMP_METER = re.compile(r"p\s*:\s*(\d{1,2})\s*/\s*(\d{1,2})")


@dataclass(frozen=True, slots=True)
class _Measure:
    duration: Fraction
    meter: tuple[int, int] | None
    left_bar: int
    right_bar: int
    left_x: int | None
    right_x: int | None
    first_for_voice: bool
    ending: bool
    uncertain: bool

    @property
    def expected(self) -> Fraction | None:
        if self.meter is None or self.meter[1] <= 0:
            return None
        return Fraction(self.meter[0] * 4, self.meter[1])


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    code: str
    page: int
    detail: str
    regions: tuple[Box, ...] = ()
    confidence: float | None = None
    source_start: int | None = None
    source_end: int | None = None


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


def _meter(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", value)
    if match is None:
        return None
    numerator, denominator = (int(part) for part in match.groups())
    return (numerator, denominator) if numerator > 0 and denominator > 0 else None


def _token_duration(token: MusicToken) -> Fraction | None:
    if token.kind in {MusicTokenKind.NOTE, MusicTokenKind.REST, MusicTokenKind.RHYTHM_NOTE}:
        return Fraction(
            2 ** (token.duration_dots + 1) - 1,
            2 ** (token.duration_slashes + token.duration_dots),
        )
    if token.kind == MusicTokenKind.EXTENSION:
        return Fraction(max(token.raw.count("-"), 1))
    return None


def _measure_regions(row: MusicRow, measure: _Measure) -> tuple[Box, ...]:
    if measure.left_x is None or measure.right_x is None:
        return (row.box,)
    selected = tuple(
        note.box for note in row.notes
        if measure.left_x < (note.box[0] + note.box[2]) / 2 < measure.right_x
    )
    return selected or (row.box,)


def _measure_source_range(line: MusicLine, measure: _Measure) -> tuple[int, int] | None:
    visible_bars = tuple(
        index for index, token in enumerate(line.tokens)
        if token.kind == MusicTokenKind.BARLINE and token.raw in _VISIBLE_BARS
    )
    if measure.left_bar >= len(visible_bars) or measure.right_bar >= len(visible_bars):
        return None
    tokens = line.tokens[
        visible_bars[measure.left_bar] + 1:visible_bars[measure.right_bar]
    ]
    if not tokens:
        return None
    return tokens[0].span.start.offset, tokens[-1].span.end.offset


def _line_measures(
    line: MusicLine,
    meter: tuple[int, int] | None,
    completed_by_voice: dict[int, int],
    row: object | None,
) -> tuple[tuple[_Measure, ...], tuple[int, int] | None]:
    measures: list[_Measure] = []
    visible_bars: list[int] = []
    visible_bar_count = sum(
        token.kind == MusicTokenKind.BARLINE and token.raw in _VISIBLE_BARS
        for token in line.tokens
    )
    left_bar: int | None = None
    duration = Fraction()
    has_timed_content = False
    ending = bool(getattr(row, "endings", ()))
    uncertain = False
    meter_for_measure = meter

    for index, token in enumerate(line.tokens):
        if token.kind == MusicTokenKind.BARLINE:
            if token.raw not in _VISIBLE_BARS:
                continue
            right_bar = len(visible_bars)
            visible_bars.append(index)
            if left_bar is not None and has_timed_content:
                left_x = right_x = None
                row_bars = tuple(sorted(row.barlines)) if isinstance(row, MusicRow) else ()
                if len(row_bars) == visible_bar_count:
                    left_x, right_x = row_bars[left_bar], row_bars[right_bar]
                first = completed_by_voice.get(line.voice, 0) == 0
                completed_by_voice[line.voice] = completed_by_voice.get(line.voice, 0) + 1
                measures.append(_Measure(
                    duration, meter_for_measure, left_bar, right_bar, left_x, right_x,
                    first, ending, uncertain,
                ))
            left_bar = right_bar
            duration = Fraction()
            has_timed_content = False
            ending = bool(getattr(row, "endings", ()))
            uncertain = False
            continue

        if token.kind == MusicTokenKind.ANNOTATION:
            match = _TEMP_METER.search(token.raw)
            if match is not None:
                meter = (int(match.group(1)), int(match.group(2)))
                if meter[0] <= 0 or meter[1] <= 0:
                    meter = None
                meter_for_measure = meter
            continue
        if token.kind == MusicTokenKind.GRACE_GROUP:
            continue
        if token.kind in {MusicTokenKind.BRACKET_START, MusicTokenKind.BRACKET_END}:
            ending = True
            continue
        amount = _token_duration(token)
        if amount is not None:
            duration += amount
            has_timed_content = True
        elif token.kind in {
            MusicTokenKind.BLOCK_START,
            MusicTokenKind.BLOCK_END,
            MusicTokenKind.HIDDEN_REST,
            MusicTokenKind.TUPLET_START,
            MusicTokenKind.UNKNOWN,
        }:
            uncertain = True
            has_timed_content = True
    return tuple(measures), meter


def musical_consistency_findings(
    code: str, pages: tuple[PageObservation, ...], bindings: tuple[RowBinding, ...],
) -> tuple[ReviewFinding, ...]:
    """Flag clear closed-measure and aligned-voice duration mismatches without edits.

    The first complete measure in each voice is exempt for pickups. Only spans between
    visible barlines are checked, so cut row edges stay silent; volta measures and
    blocks/tuplets/hidden rests are skipped. Grace groups contribute no main-stream time.
    """
    document = parse_code(code)
    initial_meter = next((
        _meter(line.value) for line in document.lines
        if isinstance(line, HeaderLine) and line.prefix == "P"
    ), None)
    by_line = {binding.source_line: binding for binding in bindings}
    by_location = {(binding.page, binding.row): binding for binding in bindings}
    completed_by_voice: dict[int, int] = {}
    measures_by_row: dict[tuple[int, int], tuple[_Measure, ...]] = {}
    lines_by_row: dict[tuple[int, int], MusicLine] = {}
    active_meter = initial_meter
    for line in document.lines:
        if not isinstance(line, MusicLine):
            continue
        binding = by_line.get(line.span.start.line)
        row = None
        if binding is not None and 1 <= binding.page <= len(pages):
            page = pages[binding.page - 1]
            if 0 <= binding.row < len(page.rows):
                row = page.rows[binding.row]
        measures, active_meter = _line_measures(line, active_meter, completed_by_voice, row)
        if binding is not None:
            key = (binding.page, binding.row)
            measures_by_row[key] = measures
            lines_by_row[key] = line

    result: list[ReviewFinding] = []
    for (page_number, row_index), measures in measures_by_row.items():
        binding = by_location.get((page_number, row_index))
        if binding is None or not binding.simple:
            continue
        row = pages[page_number - 1].rows[row_index]
        line = lines_by_row[page_number, row_index]
        for measure in measures:
            expected = measure.expected
            meter = measure.meter
            if (
                measure.first_for_voice or measure.ending or measure.uncertain
                or expected is None or meter is None or measure.duration == expected
            ):
                continue
            source_range = _measure_source_range(line, measure)
            result.append(ReviewFinding(
                "measure_duration_review", page_number,
                f"A closed measure totals {measure.duration} quarter-note beats, while "
                f"meter {meter[0]}/{meter[1]} calls for {expected}. "
                "Check the scan; this finding does not change the notes or durations.",
                _measure_regions(row, measure),
                source_start=source_range[0] if source_range is not None else None,
                source_end=source_range[1] if source_range is not None else None,
            ))

    for page_index, page in enumerate(pages, start=1):
        for group in page.voice_groups:
            rows = [
                index for index in group.rows
                if (page_index, index) in measures_by_row
                and 0 <= index < len(page.rows)
                and (binding := by_location.get((page_index, index))) is not None
                and binding.simple
            ]
            for position, left_index in enumerate(rows):
                for right_index in rows[position + 1:]:
                    left_row, right_row = page.rows[left_index], page.rows[right_index]
                    heights = [
                        note.box[3] - note.box[1]
                        for row in (left_row, right_row) for note in row.notes
                    ]
                    if not heights:
                        continue
                    tolerance = max(3.0, median(heights) * 0.65)
                    right_measures = measures_by_row[page_index, right_index]
                    for left_measure in measures_by_row[page_index, left_index]:
                        expected = left_measure.expected
                        if (
                            left_measure.first_for_voice or left_measure.ending
                            or left_measure.uncertain or expected is None
                            or left_measure.left_x is None or left_measure.right_x is None
                        ):
                            continue
                        match = next((candidate for candidate in right_measures
                                      if not candidate.first_for_voice and not candidate.ending
                                      and not candidate.uncertain
                                      and candidate.expected == expected
                                      and candidate.left_x is not None
                                      and candidate.right_x is not None
                                      and abs(left_measure.left_x - candidate.left_x) <= tolerance
                                      and abs(left_measure.right_x - candidate.right_x)
                                      <= tolerance), None)
                        if match is None or left_measure.duration == match.duration:
                            continue
                        left_voice = lines_by_row[page_index, left_index].voice
                        right_voice = lines_by_row[page_index, right_index].voice
                        # The two voice spans are disjoint in JPS source. A single
                        # offset range would include unrelated lines, so use image regions.
                        result.append(ReviewFinding(
                            "cross_voice_measure_duration_review", page_index,
                            f"Aligned voices Q{left_voice} and Q{right_voice} total "
                            f"{left_measure.duration} and {match.duration} quarter-note "
                            f"beats over the same measure. Check both rows against the scan; "
                            "this finding does not change either voice.",
                            (*_measure_regions(left_row, left_measure),
                             *_measure_regions(right_row, match)),
                        ))
    return tuple(result)


def _sung_lyric_text(value: str) -> str:
    start, end = 0, len(value)
    while start < end and (
        value[start].isspace() or unicodedata.category(value[start]).startswith("P")
    ):
        start += 1
    while end > start and (
        value[end - 1].isspace() or unicodedata.category(value[end - 1]).startswith("P")
    ):
        end -= 1
    return value[start:end]


def render_back_findings(
    code: str, pages: tuple[PageObservation, ...], bindings: tuple[RowBinding, ...],
) -> tuple[ReviewFinding, ...]:
    """Diagnose dropped/wrapped/reordered notes and severe within-measure spacing drift.

    Engraving changes scale and spacing, so absolute pixel differences are not errors.
    Hidden branches and grace streams have separate ownership and are deliberately not
    compared with a main-row projection. Findings never alter recognized notation.
    """
    consistency = musical_consistency_findings(code, pages, bindings)
    if not bindings:
        return consistency
    checking_page = 1
    try:
        model = normalize_code(code)
        rendered_by_line: dict[int, dict[int, tuple[float, float]]] = {}
        rendered_layouts: dict[int, LayoutPage] = {}
        for page_index in range(len(model.pages)):
            checking_page = min(page_index + 1, len(pages))
            _svg, layout = render_score_model_page_with_layout(model, page_index)
            rendered_layouts[page_index] = layout
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
        ), *consistency)
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
        bound_layout = rendered_layouts.get(binding.page - 1)
        if bound_layout is None:
            continue
        note_events = tuple(sorted(
            (item for item in bound_layout.events
             if item.event.span.start.line == binding.source_line
             and item.event.kind in _NOTES and item.block is None),
            key=lambda item: item.event.span.start.offset,
        ))
        if len(note_events) != len(row.notes):
            continue
        event_index = {item.address.notepos: index for index, item in enumerate(note_events)}
        events_by_address = {item.address.notepos: item for item in note_events}
        source_lines = code.splitlines(keepends=True)
        for lyric_source_line, lyric_draft in binding.lyric_bindings:
            accepted = lyric_draft.accepted_slot_groups
            if not accepted or len(accepted) != len(note_events):
                continue
            actual_groups: list[list[tuple[int, str]]] = [
                [] for _ in note_events
            ]
            foreign_host = False
            for lyric in bound_layout.lyrics:
                if not any(span.start.line == lyric_source_line for span in lyric.source_spans):
                    continue
                if lyric.annotation or lyric.cipos is None:
                    continue
                text = _sung_lyric_text(lyric.text)
                if not text:
                    continue
                host = events_by_address.get(lyric.cipos)
                if host is None or host.event.span.start.line != binding.source_line:
                    foreign_host = True
                    continue
                if (lyric.voice, lyric.line, lyric.slot) != (
                    host.voice, host.line, host.slot,
                ):
                    foreign_host = True
                    continue
                source_offset = min(
                    span.start.offset for span in lyric.source_spans
                    if span.start.line == lyric_source_line
                )
                actual_groups[event_index[lyric.cipos]].append((source_offset, text))
            expected_text = tuple("".join(
                _sung_lyric_text(unit)
                for unit in (group or ())
                if not unit.startswith('"')
            ) for group in accepted)
            actual_text = tuple("".join(
                text for _, text in sorted(group)
            ) for group in actual_groups)
            if not foreign_host and actual_text == expected_text:
                continue
            source_start = source_end = None
            if 1 <= lyric_source_line <= len(source_lines):
                source_start = sum(len(line) for line in source_lines[:lyric_source_line - 1])
                source_end = source_start + len(source_lines[lyric_source_line - 1].rstrip("\r\n"))
            result.append(ReviewFinding(
                "render_back_lyric_preservation", binding.page,
                "The emitted lyric lost, merged, reordered, or moved accepted text between "
                "note hosts. Check the C line against the source lyric row.",
                lyric_draft.regions,
                source_start=source_start,
                source_end=source_end,
            ))
    return (*result, *consistency)
