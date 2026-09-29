"""Partition voice events into floating or exact onset-based beat grids."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from re_tomato.normalization.types import MusicEvent
from re_tomato.parser.ast import MusicTokenKind
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import (
    _associated_overflow,
    lyric_overflow,
)
from re_tomato.render.layout_engine.beat_grid_engine.spacing import (
    duration_beats,
    duration_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    SYLLABLE_KINDS,
    TIMED_KINDS,
    BeatShape,
    Line,
    LyricTextByEvent,
    Measure,
    _ExactGridItem,
    _ExactLine,
    _ExactMeasure,
)


def analyze_line(
    events: Sequence[MusicEvent], overflows: Sequence[float]
) -> Line:
    """Return a line's measures for an event stream.

    ``overflows`` holds one overflow per lyric syllable (in order); the
    syllable-consuming events index into it sequentially.
    """
    measures: Line = []
    beats: Measure = []
    beat = -1
    measure_time = 0.0
    previous_natural: int | None = None
    note_index = 0
    next_boundary: str | None = None
    for event in events:
        if event.kind == MusicTokenKind.BARLINE:
            if beats:
                measures.append(beats)
            beats, beat, measure_time, previous_natural = [], -1, 0.0, None
            next_boundary = None
            continue
        if event.kind not in TIMED_KINDS:
            continue
        overflow = (
            overflows[note_index]
            if event.kind in SYLLABLE_KINDS and note_index < len(overflows)
            else 0.0
        )
        if event.kind in SYLLABLE_KINDS:
            note_index += 1
        natural = int(measure_time + 1e-9)
        if next_boundary == "split":
            begins = True
        elif next_boundary == "join":
            begins = beat < 0
        else:
            begins = beat < 0 or (previous_natural is not None and natural != previous_natural)
        if begins:
            beat += 1
        current = max(0, beat)
        while len(beats) <= current:
            beats.append([])
        beats[current].append((event, overflow))
        previous_natural = natural
        measure_time += duration_beats(event)
        raw = event.raw or ""
        if raw.endswith("~"):
            next_boundary = "join"
        elif raw.endswith("^"):
            next_boundary = "split"
        else:
            next_boundary = None
    if beats:
        measures.append(beats)
    return measures


def analyze_line_with_lyric_text(
    events: Sequence[MusicEvent],
    lyric_text_by_event: Mapping[tuple[int, int], Sequence[str]],
) -> Line:
    """Analyze a line using the already-associated normalized lyric events.

    The renderer associates lyric tokens with music events before shared-grid
    layout.  Keeping this adapter keyed by ``(source line, event index)`` is
    important: rescanning a raw lyric line loses skips, annotations, and verse
    alignment.  Multiple verses use the widest associated syllable on an
    event, matching the union rule used by the renderer's intrinsic profile.
    """
    overflows = [
        max(
            (
                lyric_overflow(text)
                for text in lyric_text_by_event.get(
                    (event.span.start.line, event.index), ()
                )
            ),
            default=0.0,
        )
        for event in events
        if event.kind in SYLLABLE_KINDS
    ]
    return analyze_line(events, overflows)


def _analyze_line_exact(
    events: Sequence[MusicEvent], lyric_text_by_event: LyricTextByEvent
) -> _ExactLine:
    """Analyze one row while retaining exact musical onsets."""
    measures: _ExactLine = []
    beats: _ExactMeasure = []
    beat = -1
    measure_time = Fraction(0, 1)
    absolute_time = Fraction(0, 1)
    previous_natural: int | None = None
    next_boundary: str | None = None
    for event in events:
        if event.kind == MusicTokenKind.BARLINE:
            if beats:
                measures.append(beats)
            elif not measures:
                # A barline that opens the row renders at the system's left edge;
                # model it as an empty measure.  Whether the following notes start
                # one BARLINE_GAP later (plain ``|``, NITD p3/p4) or directly on top
                # of the barline (``|/``, zero-width — oracle-verified 2026-08-23
                # across As-Wished, Azalea, Edelweiss x4, Evening-Bell-Zhuo-Yiting,
                # Flowers-Fall-Again-Choir, Horizon, I-Like, I-Want-You, Love-You x2,
                # Moon-Full-On-West-Tower x2, Oh-Sea x2, Watching-Sunset) is resolved
                # in project_shared_grid via the zero_gap_leading flag.
                measures.append([])
            beats, beat, measure_time, previous_natural = [], -1, Fraction(0, 1), None
            next_boundary = None
            continue
        if event.kind not in TIMED_KINDS:
            continue
        duration = duration_fraction(event)
        natural = measure_time.numerator // measure_time.denominator
        # Oracle-verified 2026-08-23 (JingleBells-Choir p1, Farewell-Choir p2):
        # a note that starts mid-beat and extends past its starting beat's
        # boundary anchors to the next beat. A dotted quarter at t=1.5 therefore
        # shares the t=2 column of the other rows, while a plain eighth ending
        # exactly on the boundary (t=1.5..2) stays in its starting beat.
        # Rests, hidden rests, and sustain dashes keep the floor-based beat
        # regardless (AuldLangSyne-Choir p1 grid 0).
        if (
            event.kind == MusicTokenKind.NOTE
            and measure_time.denominator != 1
            and duration > 0
            and measure_time + duration > natural + 1
        ):
            natural += 1
        if next_boundary == "split":
            begins = True
        elif next_boundary == "join":
            begins = beat < 0
        else:
            begins = beat < 0 or (
                previous_natural is not None and natural != previous_natural
            )
        # A tie-joined event sits in its host's beat even when its own onset
        # already lies in a later beat; it must not move the beat cursor, or a
        # following rest at that later floor would be swallowed into the host
        # beat (oracle-verified 2026-08-23, Looking-Back p2 L47 m0:
        # `(5/~ 6/)~ 5/ 5,/~` keeps `5,/~` in its own beat).
        joined = not begins and next_boundary == "join"
        if begins:
            beat += 1
        current = max(0, beat)
        while len(beats) <= current:
            beats.append([])
        # The rendered code carries the tie even when it trails the note as
        # its own modifier token (span-closing ``(3. 3)~`` or post-grace
        # ``6[5]~``); oracle-verified 2026-08-23 (probes P1/P2, Looking-Back
        # p1 rows 14-17): the reference treats such hosts as tied — underlined
        # within-beat base and a joined following event.
        tied = (event.code or "").endswith("~")
        beats[current].append(
            _ExactGridItem(
                event=event,
                overflow=_associated_overflow(event, lyric_text_by_event),
                onset=absolute_time,
                tied=tied,
            )
        )
        if not joined:
            previous_natural = natural
        measure_time += duration
        absolute_time += duration
        if tied:
            next_boundary = "join"
        elif (event.raw or "").endswith("^"):
            next_boundary = "split"
        else:
            next_boundary = None
    if beats:
        measures.append(beats)
    return measures


def four_voice_majority_beat_shape(
    rows: Sequence[Sequence[MusicEvent]],
) -> BeatShape | None:
    """Return the majority beat partition for one measured four-row shape.

    A source row can have the same timed-event counts as its siblings while a
    fractional duration makes one local beat boundary fall later.  The
    reference keeps the three-row majority partition for that topology.  This
    helper only recognizes the narrow, lossless form: four rows, three equal
    exact shapes, one shape with one additional beat in one measure, and equal
    timed-event counts per measure.  It returns no shape for any other rhythm.
    """
    if len(rows) != 4 or any(not row for row in rows):
        return None
    exact_lines = [_analyze_line_exact(row, {}) for row in rows]
    shapes = tuple(
        tuple(
            tuple(len(beat) for beat in measure)
            for measure in line
        )
        for line in exact_lines
    )
    shape_counts = {shape: shapes.count(shape) for shape in set(shapes)}
    majority_shape, majority_count = max(
        shape_counts.items(), key=lambda item: item[1]
    )
    if majority_count != 3 or len(shape_counts) != 2:
        return None
    outlier_shape = next(shape for shape in shapes if shape != majority_shape)
    if len(outlier_shape) != len(majority_shape):
        return None
    beat_count_differences = [
        (len(majority_measure), len(outlier_measure))
        for majority_measure, outlier_measure in zip(
            majority_shape, outlier_shape, strict=True
        )
        if len(majority_measure) != len(outlier_measure)
    ]
    if (
        len(beat_count_differences) != 1
        or beat_count_differences[0][1] != beat_count_differences[0][0] + 1
    ):
        return None
    event_counts = tuple(
        tuple(sum(len(beat) for beat in measure) for measure in line)
        for line in exact_lines
    )
    if len(set(event_counts)) != 1:
        return None
    return majority_shape


def _repartition_exact_lines(
    exact_lines: Sequence[_ExactLine], target_shape: BeatShape
) -> list[_ExactLine]:
    """Apply a validated majority beat partition without changing event order."""
    repartitioned: list[_ExactLine] = []
    for line in exact_lines:
        if len(line) != len(target_shape):
            return list(exact_lines)
        new_line: _ExactLine = []
        for measure, target_beats in zip(line, target_shape, strict=True):
            items = [item for beat in measure for item in beat]
            if len(items) != sum(target_beats):
                return list(exact_lines)
            cursor = 0
            new_measure: _ExactMeasure = []
            for item_count in target_beats:
                new_measure.append(items[cursor : cursor + item_count])
                cursor += item_count
            new_line.append(new_measure)
        repartitioned.append(new_line)
    return repartitioned
