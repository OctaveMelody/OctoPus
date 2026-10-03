"""Joint legacy cell projection for multi-row ordinary systems.

Reference oracle decode (2026-09-06, probe series recorded in
IMPLEMENTATION_PLAN.md item 18): when a visual system's rows fall back to
the ordinary projection, the reference does not weight each row by note
duration independently.  It lays every row out from a shared table of
class-based cell widths and then scales the whole system:

* the gap after an event carries a natural weight that depends only on the
  class pair (previous event class, next event class); dotted notes are
  worth 50, barlines 35, tied events 25, plain quarter rests 62.5 and so on;
* an unquoted ``[n]`` bracket mark reserves 7 units on the marked note's
  incoming gap; when the marked note is tied, the reservation is paid back
  on the first gap after the tie group ends (the reference keeps the mark
  inside the beat it belongs to);
* marks are shared across rows whose measures carry the same event-class
  signature, so both rows of a system indent identically; sharing is
  self-inclusive (a mark also reserves on its own row's matching column) —
  the only engaging corpus system (Looking-Back p1 sys2, spy-verified: 548
  calls, one engagement) carries marks on one row only, so the
  both-rows-marked case is unverified against REF; probe before trusting it
* the whole system is scaled by ``k = (L - c) / W`` where ``W`` is the
  largest row weight sum plus an absorber allowance of 25 and
  ``c = -14 + 7 * mark_count``;
* the final gap of each row absorbs the remainder so the last barline sits
  exactly on the system's right edge.

The pass only engages when every row of the system uses the ordinary
projection (catalog-grace template rows are stamped separately), there are
at least two rows, every event classifies into the table, and the computed
scale is at most one; anything else is left untouched.
"""

from __future__ import annotations

from ...model.model_normalize import MusicEvent
from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutEvent

_BARLINE = "barline"
_HIDDEN = "hidden"
_REST = "rest"
_TIED_REST = "tied-rest"
_TIED = "tied"
_DOTTED = "dotted"
_QUARTER = "quarter"
_EIGHTH = "eighth"

# Natural cell weight of the gap that follows an event, by class pair.
_CELL_WEIGHTS: dict[tuple[str, str], float] = {
    (_DOTTED, _DOTTED): 50.0,
    (_DOTTED, _TIED): 50.0,
    (_DOTTED, _QUARTER): 50.0,
    (_DOTTED, _EIGHTH): 50.0,
    (_DOTTED, _REST): 50.0,
    (_DOTTED, _TIED_REST): 50.0,
    (_DOTTED, _BARLINE): 47.5,
    (_BARLINE, _DOTTED): 35.0,
    (_BARLINE, _TIED): 35.0,
    (_BARLINE, _QUARTER): 35.0,
    (_BARLINE, _EIGHTH): 35.0,
    (_BARLINE, _REST): 35.0,
    (_BARLINE, _TIED_REST): 35.0,
    (_TIED, _EIGHTH): 25.0,
    (_TIED, _DOTTED): 25.0,
    (_TIED, _TIED): 25.0,
    (_TIED, _QUARTER): 25.0,
    (_EIGHTH, _BARLINE): 35.0,
    (_EIGHTH, _TIED): 37.5,
    (_EIGHTH, _DOTTED): 37.5,
    (_EIGHTH, _HIDDEN): 37.5,
    (_EIGHTH, _EIGHTH): 25.0,
    (_QUARTER, _EIGHTH): 37.5,
    (_REST, _EIGHTH): 62.5,
    (_TIED_REST, _EIGHTH): 25.0,
    (_HIDDEN, _BARLINE): 35.0,
}

# Extra weight the final (absorbing) gap of a row contributes to W.
_ABSORBER_EXTRA = 25.0
# Constant offset applied to the system's available length before scaling.
_BASE_OFFSET = -14.0
# Width reserved by one unquoted bracket mark.
_MARK_RESERVE = 7.0
# The cell model is a compression model; never expand beyond natural width.
_MAX_SCALE = 1.0

# Dynamics are the only decorations observed to be width-neutral in the
# decoded systems; anything else declines the pass.
_NEUTRAL_DECORATIONS = frozenset({"p", "mp", "mf", "f", "ff", "fff"})


def _event_code(event: MusicEvent) -> str:
    return event.render_code or event.code or ""


def _classify(event: MusicEvent) -> str | None:
    """Map an event onto its cell-model class, or ``None`` if unsupported."""
    kind = event.kind
    if kind == MusicTokenKind.BARLINE:
        return _BARLINE
    if kind == MusicTokenKind.HIDDEN_REST:
        return _HIDDEN
    tied = _tied_forward(event)
    if kind == MusicTokenKind.REST:
        return _TIED_REST if tied else _REST
    if kind != MusicTokenKind.NOTE:
        return None
    if tied:
        return _TIED
    if event.duration_dots > 0:
        return _DOTTED
    if event.duration_slashes > 0:
        return _EIGHTH
    return _QUARTER


def _is_placeholder_hidden_rest(item: LayoutEvent) -> bool:
    return (
        item.event.index < 0 and item.event.kind == MusicTokenKind.HIDDEN_REST
    )


def _tied_forward(event: MusicEvent) -> bool:
    return _event_code(event).rstrip().endswith("~")


def _tie_group_end(row: list[LayoutEvent], start: int) -> int:
    """Last index of the forward-tie run starting at ``start``.

    Degenerate case: if ``row[start]`` is not tied forward, returns
    ``start`` unchanged (a one-event "group"); callers must guard with
    ``_tied_forward``. Note the stricter endswith-``~`` test — the
    shared-grace walk uses a substring check instead; the only corpus
    event with a mid-code ``~`` (Autumn-Cicada p1 sys1, code ``1(~/``)
    is not a grace host, so the divergence is dormant.
    """
    index = start
    while index < len(row) - 1 and _tied_forward(row[index].event):
        index += 1
    return index


def _row_measures(row: list[LayoutEvent]) -> list[list[int]]:
    measures: list[list[int]] = []
    current: list[int] = []
    for index, item in enumerate(row):
        current.append(index)
        if item.event.kind == MusicTokenKind.BARLINE:
            measures.append(current)
            current = []
    if current:
        measures.append(current)
    return measures


def _row_supported(row: list[LayoutEvent]) -> bool:
    """Whether this row's shape matches the oracle's cell-table assumptions.

    Requires at least four events, a barline-terminated row starting with a
    note or rest, every event classified into the weight table, only neutral
    decorations, ordinary projection kind, and placeholder hidden rests only
    directly before a barline (their insertion position).
    """
    if len(row) < 4 or row[-1].event.kind != MusicTokenKind.BARLINE:
        return False
    if row[0].event.kind not in (MusicTokenKind.NOTE, MusicTokenKind.REST):
        return False
    for index, item in enumerate(row):
        if _is_placeholder_hidden_rest(item):
            # Placeholders are inserted directly before a barline.
            if index >= len(row) - 1:
                return False
            if row[index + 1].event.kind != MusicTokenKind.BARLINE:
                return False
            continue
        if item.projection_kind != "ordinary":
            return False
        if _classify(item.event) is None:
            return False
        if not frozenset(item.event.decorations) <= _NEUTRAL_DECORATIONS:
            return False
    return True


def reproject_legacy_cell_rows(
    events: list[LayoutEvent],
    *,
    left: float,
    right: float,
) -> bool:
    """Re-project a system's ordinary rows with the legacy cell model.

    Returns ``True`` when the model engaged and rewrote row positions.
    """
    by_line: dict[int, list[LayoutEvent]] = {}
    for item in events:
        by_line.setdefault(item.line, []).append(item)
    rows: list[list[LayoutEvent]] = []
    for line in sorted(by_line):
        row = sorted(by_line[line], key=lambda item: item.slot)
        if _row_supported(row):
            rows.append(row)
    if len(rows) < 2 or right - left <= 0:
        return False

    classes: list[list[str]] = []
    weights: list[list[float]] = []
    measures: list[list[list[int]]] = []
    for row in rows:
        raw_classes = [_classify(item.event) for item in row]
        cls: list[str] = [cls_item for cls_item in raw_classes if cls_item is not None]
        if len(cls) != len(raw_classes):
            return False
        weights_row: list[float] = []
        for prev_class, next_class in zip(cls, cls[1:], strict=False):
            edge_weight = _CELL_WEIGHTS.get((prev_class, next_class))
            if edge_weight is None:
                return False
            weights_row.append(edge_weight)
        classes.append(cls)
        weights.append(weights_row)
        measures.append(_row_measures(row))

    # Bracket-mark reservations, shared across rows with matching measure
    # signatures (the reference indents both rows of a system identically).
    reserves: list[list[float]] = [[0.0] * (len(row) - 1) for row in rows]
    mark_count = 0
    for row_index, row in enumerate(rows):
        for index, item in enumerate(row):
            if item.event.grace_reservation <= 0 or index == 0:
                continue
            mark_count += 1
            measure_positions = measures[row_index]
            measure_position = next(
                position
                for position, members in enumerate(measure_positions)
                if index in members
            )
            column = measure_positions[measure_position].index(index)
            signature = tuple(classes[row_index][i] for i in measure_positions[measure_position])
            tied_mark = _tied_forward(item.event)
            # Self-inclusive on purpose: other_index == row_index applies the
            # reserve to the mark's own row as well (module docstring caveat).
            for other_index, other_row in enumerate(rows):
                other_members = measures[other_index][measure_position]
                if tuple(classes[other_index][i] for i in other_members) != signature:
                    continue
                if column >= len(other_members) or other_members[column] == 0:
                    continue
                target = other_members[column]
                reserves[other_index][target - 1] += _MARK_RESERVE
                if tied_mark:
                    group_end = _tie_group_end(other_row, target)
                    if group_end < len(other_row) - 1:
                        reserves[other_index][group_end] -= _MARK_RESERVE

    system_weight = max(sum(row_weights) + _ABSORBER_EXTRA for row_weights in weights)
    offset = _BASE_OFFSET + _MARK_RESERVE * mark_count
    scale = (right - left - offset) / system_weight
    if not 0.0 < scale <= _MAX_SCALE:
        return False

    for row, row_weights, row_reserves in zip(rows, weights, reserves, strict=True):
        row[0].x = float(left)
        row[0].style_x = row[0].x
        row[-1].x = float(right)
        row[-1].style_x = row[-1].x
        running_x = float(left)
        for index in range(len(row) - 2):
            running_x += row_weights[index] * scale + row_reserves[index]
            row[index + 1].x = running_x
            row[index + 1].style_x = running_x
    return True


__all__ = ["reproject_legacy_cell_rows"]
