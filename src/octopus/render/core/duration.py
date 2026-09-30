"""Duration-line elements: the bracketed duration annotations under note rows."""

from __future__ import annotations

import re
from fractions import Fraction

from ...model.model_normalize import MusicEvent
from ...parser.ast import MusicTokenKind
from .elements import SvgElement, _format_reference_number
from .layout_types import LayoutEvent, LayoutMark, LayoutPage

MAX_DURATION_LINE_LEVEL = 4


def _visible_row_key(item: LayoutEvent) -> tuple[object, ...]:
    return ("visible", item.voice, item.line)


def _hidden_row_key(item: LayoutEvent) -> tuple[object, ...]:
    return (
        "hidden",
        item.block,
        _hidden_block_identity(item),
        item.voice,
        item.line,
        item.event.span.start.line,
    )


def _duration_row_base_ys(layout: LayoutPage) -> dict[tuple[object, ...], float]:
    """Base line y of every duration row key (the row's topmost line).

    Rows with stacked continuation fragments carry events on several visual
    lines; their base is the main line above the fragments.
    """
    base: dict[tuple[object, ...], float] = {}
    for item in layout.events:
        key = _visible_row_key(item)
        if key not in base or item.y < base[key]:
            base[key] = item.y
    for item in layout.hidden_events:
        key = _hidden_row_key(item)
        if key not in base or item.y < base[key]:
            base[key] = item.y
    return base


def duration_line_elements(layout: LayoutPage) -> list[SvgElement]:
    elements: list[SvgElement] = []
    groups = duration_source_groups(layout, include_hidden=True)
    row_base_y = _duration_row_base_ys(layout)
    hidden_ids = {id(item) for item in layout.hidden_events}
    # Rows are ordered by their base line; within one row the groups keep
    # their source-stream order, so a DSB row's stacked continuation groups
    # precede its post-block main groups (Hulunbuir [84]/[100] Q3: echo,
    # continuation, then main — the per-group y sort used to flip the last
    # two).
    def _sort_key(indexed_group: tuple[int, tuple[LayoutEvent, ...]]) -> tuple[float, int]:
        index, group = indexed_group
        first = group[0]
        key = _hidden_row_key(first) if id(first) in hidden_ids else _visible_row_key(first)
        return row_base_y[key], index

    for _index, group in sorted(enumerate(groups), key=_sort_key):
        _flush_duration_group(elements, list(group))
    return elements


def duration_source_groups(
    layout: LayoutPage,
    *,
    include_hidden: bool = False,
) -> list[tuple[LayoutEvent, ...]]:
    groups: list[tuple[LayoutEvent, ...]] = []
    by_row: dict[tuple[object, ...], list[LayoutEvent]] = {}
    for item in layout.events:
        by_row.setdefault(_visible_row_key(item), []).append(item)
    if include_hidden:
        for item in layout.hidden_events:
            by_row.setdefault(_hidden_row_key(item), []).append(item)

    inline_signatures = {
        (mark.host.voice, mark.host.line, mark.host.slot): signature
        for mark in layout.marks
        if (signature := _inline_time_signature(mark)) is not None
    }
    for row in by_row.values():
        beat = _duration_group_limit(layout.header.time_sig)
        sorted_row = sorted(row, key=lambda event: (event.slot, event.x, event.event.index))
        state = _DurationGroupState(beat)
        for item in sorted_row:
            event = item.event
            if event.kind == MusicTokenKind.BARLINE:
                state.on_barline(groups)
                signature = inline_signatures.get((item.voice, item.line, item.slot))
                if signature is not None:
                    state.beat = _duration_group_limit("/".join(signature))
                continue
            raw_duration = event.duration
            duration = (
                Fraction(raw_duration.numerator, raw_duration.denominator)
                if raw_duration is not None
                else Fraction(0, 1)
            )
            if event.kind == MusicTokenKind.HIDDEN_REST:
                # Hidden rests render as null glyphs and never carry beams;
                # a tied one (8~) still isolates its following run.
                state.on_run_break(
                    groups,
                    Fraction(0, 1),
                    tied_rest=_duration_marker_in_event(event, "~"),
                )
                continue
            if event.duration_slashes == 0:
                state.on_run_break(
                    groups,
                    duration,
                    tied_rest=_is_tied_hidden_rest(event),
                    tied_long_note=(
                        _duration_marker_in_event(event, "~")
                        and not _is_tied_hidden_rest(event)
                    ),
                )
                continue
            state.add_short_note(item, _grouping_duration(event), groups)
        state.close_group(groups)
    return groups


def _is_tied_hidden_rest(event: MusicEvent) -> bool:
    """Return True for a zero-duration tied rest such as ``8~``."""
    duration = event.duration
    return (
        event.duration_slashes == 0
        and (duration is None or duration.numerator == 0)
        and _duration_marker_in_event(event, "~")
    )


class _DurationGroupState:
    """Beam-grouping state for one row of a duration line.

    Zhipu beaming policy (proven against the corpus and oracle probes):

    * A beam group is a run of consecutive short notes (one or more slashes).
      Long notes, rests without slashes, hidden rests, and barlines break the
      run. Hidden rests render as null glyphs and never carry beams.
    * Within a run, notes join one group while they end inside the same beat
      window ``[k, k + 1)`` in quarter-beat units (meter-independent); a note
      ending exactly on a window edge belongs to the earlier window.
    * A tied note (``~``) pulls the following short note into its group even
      across a window edge or a hidden-rest break; the pull chains through
      consecutive tied notes and stops at the first non-tied pulled note.
    * A tied note may also join the current group across one beat edge while
      it still ends within the first beat of the group (for example an
      eighth-note run starting on a half-beat offset).
    * A note carrying a ``^`` mark is always rendered as an isolated stub.
    * When a long note whose duration is not a whole number of beats or that
      carries a tie mark appears in a measure, the first short note of every
      following run in that measure is isolated as a stub when its duration
      is at least half a beat and it is not tied. The priming is consumed by
      the first short note it meets.
    * The run immediately after a zero-duration tied rest (``8~``) renders
      all of its notes as isolated stubs, except notes pulled into a group by
      a preceding tie.
    """

    def __init__(self, beat: Fraction) -> None:
        self.beat = beat
        self.onset = Fraction(0, 1)
        self.measure_primed = False
        self.tied_long_note = False
        self.tied_rest_isolation = False
        self.group: list[LayoutEvent] = []
        self.group_start: Fraction = Fraction(0, 1)
        self.group_window: int | None = None

    def on_barline(self, groups: list[tuple[LayoutEvent, ...]]) -> None:
        self.close_group(groups)
        self.onset = Fraction(0, 1)
        self.measure_primed = False
        self.tied_rest_isolation = False

    def on_run_break(
        self,
        groups: list[tuple[LayoutEvent, ...]],
        duration: Fraction,
        *,
        tied_rest: bool = False,
        tied_long_note: bool = False,
    ) -> None:
        self.tied_long_note = tied_long_note
        last_tied = bool(self.group) and _duration_marker_in_event(
            self.group[-1].event, "~"
        )
        if not last_tied:
            self.close_group(groups)
        # A tied rest isolates its following run only when no preceding tie
        # pulls across it; a pending pull takes precedence.
        self.tied_rest_isolation = tied_rest and not last_tied
        # A long note primes the measure when its duration is not a whole
        # number of beats or when it carries a tie mark (oracle probes).
        if duration > 0 and (duration % self.beat != 0 or self.tied_long_note):
            self.measure_primed = True
        self.onset += duration

    def close_group(self, groups: list[tuple[LayoutEvent, ...]]) -> None:
        _append_duration_source_group(groups, self.group)
        self.group_start = Fraction(0, 1)
        self.group_window = None

    def add_short_note(
        self,
        item: LayoutEvent,
        duration: Fraction,
        groups: list[tuple[LayoutEvent, ...]],
    ) -> None:
        event = item.event
        last = self.group[-1] if self.group else None
        if last is not None and _duration_marker_in_event(last.event, "~"):
            # A tied note pulls the next short note into its group; the chain
            # continues only while the pulled notes stay tied.
            self.group.append(item)
            self.measure_primed = False
            if not _duration_marker_in_event(event, "~"):
                self.close_group(groups)
        elif last is None:
            self._start_group(item, duration, groups)
        else:
            end = self.onset + duration
            window = (end - 1) // self.beat if end % self.beat == 0 else end // self.beat
            crosses_window = (
                window != self.group_window
                and _duration_marker_in_event(event, "~")
                and end - self.group_start <= self.beat
            )
            if window == self.group_window or crosses_window:
                # A tied note may join the group across one beat edge while it
                # still ends within the first beat of the group (oracle probes).
                self.group.append(item)
            else:
                self.close_group(groups)
                self._start_group(item, duration, groups)
        if _duration_marker_in_event(event, "^"):
            self.close_group(groups)
        self.onset += duration

    def _start_group(
        self,
        item: LayoutEvent,
        duration: Fraction,
        groups: list[tuple[LayoutEvent, ...]],
    ) -> None:
        event = item.event
        isolated = (
            self.tied_rest_isolation
            or (
                self.measure_primed
                and duration >= Fraction(1, 2)
                and not _duration_marker_in_event(event, "~")
            )
        )
        self.measure_primed = False
        self.tied_rest_isolation = False
        if isolated:
            groups.append((item,))
            return
        end = self.onset + duration
        window = (end - 1) // self.beat if end % self.beat == 0 else end // self.beat
        self.group.append(item)
        self.group_start = self.onset
        self.group_window = window


def _append_duration_source_group(
    groups: list[tuple[LayoutEvent, ...]],
    group: list[LayoutEvent],
) -> None:
    if group:
        groups.append(tuple(group))
        group.clear()


def _grouping_duration(event: MusicEvent) -> Fraction:
    if event.duration is None:
        return Fraction(0, 1)
    duration = Fraction(event.duration.numerator, event.duration.denominator)
    written_duration = Fraction(
        2 ** (event.duration_dots + 1) - 1,
        2 ** (event.duration_slashes + event.duration_dots),
    )
    if (
        duration == written_duration
        and any(":tuplet:" in role for role in event.construct_roles)
    ):
        return duration * Fraction(2, 3)
    return duration


def _hidden_block_identity(item: LayoutEvent) -> tuple[str, ...]:
    return tuple(
        construct_id
        for construct_id in item.event.construct_ids
        if ":block:" in construct_id
    )


def _duration_marker_in_event(event: MusicEvent, marker: str) -> bool:
    return any(
        marker in text
        for text in (event.source_code, event.render_code, event.code, event.raw)
        if text
    )


def _duration_group_limit(time_sig: str) -> Fraction:
    # Oracle probes (4/4, 2/2, 6/8, 9/8): the beat window is always one
    # quarter-note beat, independent of the meter. Notes ending exactly on a
    # window edge belong to the earlier window.
    return Fraction(1, 1)


def _duration_line(items: list[LayoutEvent], level: int) -> SvgElement:
    # A beam whose whole run sits on a bz block's raised bian line is drawn
    # two pixels higher than the standard offset (corpus census 2026-08-28:
    # both Azalea bz beams sit at note_y + 11, every other corpus beam keeps
    # note_y + 13).
    on_bian_line = all(item.block in {"bz", "bz-hidden"} for item in items)
    y = items[0].y + (11 if on_bian_line else 13) + (level - 1) * 3
    x1 = items[0].x - 6
    # A dotted short note that ends a multi-note group extends the beam past
    # its dot (+16); a solo dotted note keeps the standard +6 stub.
    last = items[-1].event
    x2 = items[-1].x + 16 if len(items) > 1 and last.duration_dots > 0 else items[-1].x + 6
    return SvgElement(
        tag="line",
        layer="duration",
        source_event_index=items[0].event.index,
        attrs=(
            ("x1", _format_reference_number(x1)),
            ("y1", f"{y:.0f}"),
            ("x2", _format_reference_number(x2)),
            ("y2", f"{y:.0f}"),
            ("data-type", "jianshixian"),
            ("stroke-width", "2"),
            ("stroke", "#1b1b1b"),
        ),
        construct_ids=items[0].event.construct_ids,
    )


def _flush_duration_group(parts: list[SvgElement], group: list[LayoutEvent]) -> None:
    if not group:
        return
    max_level = min(
        MAX_DURATION_LINE_LEVEL,
        max(item.event.duration_slashes for item in group),
    )
    for level in range(1, max_level + 1):
        run: list[LayoutEvent] = []
        for item in group:
            if item.event.duration_slashes >= level:
                run.append(item)
            elif run:
                parts.append(_duration_line(run, level))
                run = []
        if run:
            parts.append(_duration_line(run, level))
    group.clear()


def _inline_time_signature(mark: LayoutMark) -> tuple[str, str] | None:
    if mark.event.kind != MusicTokenKind.ANNOTATION:
        return None
    value = (mark.event.value or mark.event.raw.strip('"')).strip()
    match = re.fullmatch(r"p:(\d+)/(\d+)", value)
    return (match.group(1), match.group(2)) if match else None
