"""Reference-derived lift for a row's first tie after a stale-group line.

The reference engraver keeps its group parser in an open state when a music
line ends with exactly one more unquoted opening paren than closing paren.
When that happens on a *numbered* voice line of a multi-voice score, the next
rendered row's first path-form pair curve is seated above its natural lane;
every later curve on that row keeps the natural lane.

Corpus-verified 2026-08 (oracle probe series recorded in
docs/SLICE_HISTORY.md, item 2).  The trigger line must satisfy all of:

1. the score defines at least two distinct numbered voice labels (``Q1``,
   ``Q2``, ...); solo scores with a plain ``Q:`` line never trigger, even
   for identical line content;
2. the line itself carries a numbered label;
3. its unquoted paren count is exactly one open-heavy (the stale group);
4. the stale span — from the last unmatched opening paren to end of line —
   contains at least one complete closed paren group; a bare dangling group
   with only notes or rests inside never triggers;
5. the first unquoted token after the label is not a bare ``(`` and does not
   start with a barline (continuation fragments such as ``Q3"T":  ( |* ...``
   or ``Q4:  |/ ...`` are excluded).

The lift amount is eight pixels plus three per octave of the lifted curve's
highest note: octave-zero curves rise from gap 16 to 24, octave-one curves
from 21 to 32 (Grandmas-Penghu-Bay p1).  The previous flat eight-pixel rule
with its "no barline after the opening paren" clause was a strict subset of
this one; that clause is what blocked Grandmas-Penghu-Bay and
The-World-Gave-Me p2, while conditions 1, 4, and 5 keep every currently
passing page on its natural lane.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...model.model_normalize import ScoreModel
from ..core.layout_types import LayoutPage

_VOICE_LABEL_RE = re.compile(r'^\s*#?\s*(Q\d*)\s*(?:"[^"]*")?\s*:')


def first_tie_lift_amount(octave: int) -> float:
    """Return the negative lane lift for a first tie at the given octave."""

    return -(8.0 + 3.0 * max(octave, 0))


def _unquoted(text: str) -> str:
    """Blank out double-quoted annotation segments; parens there are opaque.

    A line with an odd number of quotes leaves everything after the last one
    blanked; such lines are malformed for this purpose and no corpus file has
    them, so the degenerate reading is acceptable.
    """

    out: list[str] = []
    in_quote = False
    for char in text:
        if char == '"':
            in_quote = not in_quote
            continue
        out.append("\x00" if in_quote else char)
    return "".join(out)


def _voice_label(line_text: str) -> str | None:
    match = _VOICE_LABEL_RE.match(line_text)
    return match.group(1) if match else None


def _dangling_span_has_closed_group(unquoted_line: str) -> bool:
    """True when the stale span holds at least one complete closed group."""

    stack: list[int] = []
    for index, char in enumerate(unquoted_line):
        if char == "(":
            stack.append(index)
        elif char == ")" and stack:
            stack.pop()
    if len(stack) != 1:
        return False
    depth = 0
    for char in unquoted_line[stack[0] + 1 :]:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return True
    return False


def _first_token_blocks(line_text: str) -> bool:
    """True for continuation fragments that start on a bar or bare paren."""

    match = _VOICE_LABEL_RE.match(line_text)
    body = line_text[match.end() :] if match else line_text
    tokens = [token for token in _unquoted(body).split() if token]
    if not tokens:
        return True
    first = tokens[0]
    return first == "(" or first.startswith("|")


def _unquoted_net(line_text: str) -> int:
    """Unquoted paren balance of a source line (opens minus closes)."""

    unquoted_line = _unquoted(line_text)
    return unquoted_line.count("(") - unquoted_line.count(")")


def _labels_equivalent(a: str | None, b: str | None) -> bool:
    """Voice-label identity across the plain/numbered default-voice forms.

    A plain ``Q:`` line and a ``Q1`` line are the same default voice in the
    reference (oracle probes T2/U7/U8: a plain-Q stale state attaches to a
    Q1-first system and vice versa; a numbered label attaches only to the
    same numbered label).
    """
    if a is None or b is None:
        return False
    if {a, b} <= {"Q", "Q1"}:
        return True
    return a == b


def stale_group_lines(source_lines: list[str]) -> frozenset[int]:
    """Return the 1-based line numbers that leave a stale nested group open.

    The scan mirrors the reference's token stream: double-quoted annotation
    segments are opaque, and only unquoted parentheses change depth.  The
    multi-voice check runs over the whole score because the reference only
    applies the lift in scores with numbered voices (oracle probes P1/P2 on
    I-Like content confirm the labels, not the header, decide it).
    """
    labels: set[str] = set()
    for line_text in source_lines:
        label = _voice_label(line_text)
        if label is not None and len(label) > 1:
            labels.add(label)
    if len(labels) < 2:
        return frozenset()

    triggers: set[int] = set()
    for number, line_text in enumerate(source_lines, 1):
        label = _voice_label(line_text)
        if label is None or len(label) < 2:
            continue
        unquoted_line = _unquoted(line_text)
        if unquoted_line.count("(") - unquoted_line.count(")") != 1:
            continue
        if not _dangling_span_has_closed_group(unquoted_line):
            continue
        if _first_token_blocks(line_text):
            continue
        triggers.add(number)
    return frozenset(triggers)


def _rendered_rows(
    layout: LayoutPage, source_lines: list[str]
) -> tuple[list[int], dict[int, float], dict[int, int]]:
    """Rendered rows in y order with their first music source line (1-based)."""

    row_y: dict[int, float] = {}
    row_source_line: dict[int, int] = {}
    for event in layout.events:
        row_y.setdefault(event.line, event.y)
        line_number = event.event.span.start.line
        if not 1 <= line_number <= len(source_lines):
            continue
        text = source_lines[line_number - 1]
        if text.lstrip().startswith(("Q", "#Q")):
            row_source_line.setdefault(event.line, line_number)
    rows = sorted(row_y, key=lambda line: row_y[line])
    return rows, row_y, row_source_line


def _source_segments(source_lines: list[str]) -> list[tuple[int, int]]:
    """Maximal runs of non-separator source lines as inclusive 0-based spans.

    Blank lines and bracket markers (``[fenye]``, ``[pageConfig]`` ...) are
    separators; lyric lines between voice lines are not.
    """
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, text in enumerate(source_lines):
        stripped = text.strip()
        if not stripped or stripped.startswith("["):
            if start is not None:
                segments.append((start, index - 1))
                start = None
        elif start is None:
            start = index
    if start is not None:
        segments.append((start, len(source_lines) - 1))
    return segments


def _block_pending_label(
    block_start: int, lines: list[str], rendered_lines: set[int]
) -> str | None:
    """Voice label of the stale group escaping a block, or None.

    The scan mirrors the reference's cross-line group state (oracle probes
    T/U/V/W/X/Y/Z/AA): a music line whose unquoted paren balance is at
    least +1 sets the pending voice; a later line of a *different* voice
    that carries a complete closed group, or any line with a negative
    balance, consumes it; same-voice lines and paren-free lines leave it
    alone.  Only rendered lines participate (hidden streams neither set nor
    clear the state).
    """
    pending: str | None = None
    for offset, text in enumerate(lines):
        index = block_start + offset + 1
        if index not in rendered_lines:
            continue
        label = _voice_label(text)
        if label is None:
            continue
        unquoted_line = _unquoted(text)
        net = unquoted_line.count("(") - unquoted_line.count(")")
        if net >= 1:
            pending = label
        elif (
            net < 0
            or (
                "(" in unquoted_line
                and ")" in unquoted_line
                and pending is not None
                and not _labels_equivalent(label, pending)
            )
        ):
            pending = None
    return pending


@dataclass(frozen=True, slots=True)
class _ScoreStaleState:
    """Page-independent stale-group state for one score."""

    source_lines: tuple[str, ...]
    triggers: frozenset[int]
    segments: tuple[tuple[int, int], ...]


# Rendering walks every page of a score, and both the trigger scan and the
# segment walk cover the whole file; memoize them on the code text (entries
# are a few KB each; the cache is bounded to the files of one run).
_SCORE_STATE_CACHE: dict[str, _ScoreStaleState] = {}


def _score_stale_state(model: ScoreModel) -> _ScoreStaleState:
    cached = _SCORE_STATE_CACHE.get(model.code)
    if cached is None:
        source_lines = model.code.split("\n")
        cached = _ScoreStaleState(
            source_lines=tuple(source_lines),
            triggers=stale_group_lines(source_lines),
            segments=tuple(_source_segments(source_lines)),
        )
        if len(_SCORE_STATE_CACHE) > 256:
            _SCORE_STATE_CACHE.clear()
        _SCORE_STATE_CACHE[model.code] = cached
    return cached


def cross_system_stale_lift_rows(
    model: ScoreModel, page_index: int, layout: LayoutPage
) -> frozenset[int]:
    """Rows lifted by a stale group that propagated across a system break.

    Oracle-decoded 2026-08-31 (probe series T/U/V/W/X/Y/Z/AA on TWGM/GPB
    content, recorded in docs/SLICE_HISTORY.md, item 9): when the block above ends
    with an open group whose voice survived to the end of the block (see
    ``_block_pending_label``), the reference carries that state into the
    next block.  If the next block's first rendered row carries the same
    voice (plain ``Q:`` and ``Q1`` are the same default voice; numbered
    labels must match exactly), the second rendered row of that block seats
    its first path-form pair curve on the lifted lane.  The state is
    consumed by that next block regardless of whether it attached, so it
    never reaches a further block.

    Attachment is resolved against this page's rendered rows only: the rule
    assumes each source block's rendered rows fit within one page (true for
    every corpus file).  If a block ever spanned a page break, the block's
    true first row would sit on the previous page and the lift could attach
    to the wrong row; revisit this assumption if such content appears.
    """
    if page_index >= len(model.pages):
        return frozenset()
    state = _score_stale_state(model)
    rows, _row_y, row_source_line = _rendered_rows(layout, list(state.source_lines))
    return _cross_system_lift_rows_for_page(
        state,
        rows,
        row_source_line,
    )


def _cross_system_lift_rows_for_page(
    state: _ScoreStaleState,
    rows: list[int],
    row_source_line: dict[int, int],
) -> frozenset[int]:
    source_lines = list(state.source_lines)
    segments = state.segments

    def segment_of(line_number: int) -> int | None:
        index = line_number - 1
        for position, (start, end) in enumerate(segments):
            if start <= index <= end:
                return position
        return None

    row_segment = {
        row: segment_of(line)
        for row, line in row_source_line.items()
    }
    rendered_lines = set(row_source_line.values())

    lift_rows: set[int] = set()
    for position in range(len(segments) - 1):
        start, end = segments[position]
        pending = _block_pending_label(
            start, source_lines[start : end + 1], rendered_lines
        )
        if pending is None:
            continue
        next_rows = [row for row in rows if row_segment.get(row) == position + 1]
        if len(next_rows) < 2:
            continue
        target_label = _voice_label(
            source_lines[row_source_line[next_rows[0]] - 1]
        )
        if not _labels_equivalent(pending, target_label):
            continue
        lift_rows.add(next_rows[1])
    return frozenset(lift_rows)


def plan_first_tie_lift_rows(
    model: ScoreModel, page_index: int, layout: LayoutPage
) -> frozenset[int]:
    """Return the layout rows whose first tie takes the stale-group lift.

    A row qualifies when the nearest visible row above it is sourced from a
    line that leaves a stale nested group open.  Only rendered rows count:
    hidden streams never seat a tie, so they neither trigger nor receive the
    lift.  Rows lifted by cross-system propagation (see
    ``cross_system_stale_lift_rows``) are included as well.

    The whole-file trigger scan and segment walk are memoized per score in
    ``_score_stale_state`` because rendering calls this once per page.
    """
    if page_index >= len(model.pages):
        return frozenset()
    state = _score_stale_state(model)
    source_lines = list(state.source_lines)
    triggers = state.triggers
    rows, _row_y, row_source_line = _rendered_rows(layout, source_lines)
    lift_rows: set[int] = set()
    for position, row in enumerate(rows):
        if position == 0:
            continue
        upper_line = row_source_line.get(rows[position - 1])
        if upper_line is None or upper_line not in triggers:
            continue
        lift_rows.add(row)
    lift_rows |= _cross_system_lift_rows_for_page(state, rows, row_source_line)
    return frozenset(lift_rows)


__all__ = [
    "first_tie_lift_amount",
    "plan_first_tie_lift_rows",
    "stale_group_lines",
]
