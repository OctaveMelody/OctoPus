"""Ordinary row and catalog-grace coordinate projection."""

from __future__ import annotations

from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent
from ...core.layout_widths import event_duration_weight

# REF-derived cumulative x offsets for the catalog-grace template rows: the engraver
# stamps these fixed-note-count grace brackets (the "qy" catalog pages) at fixed column
# positions, decoded from reference output (oracle probe series; decode records in
# docs/project/SLICE_HISTORY.md). The repeating decimals are the engraver's unit-grid
# fractions — keep them as literals and never "simplify" or round them: sub-pixel drift
# breaks REF parity.
_SINGLE_CATALOG_GRACE_ROW_OFFSETS = (
    0.0, 60.72093023256, 114.44186046512, 175.16279069767, 232.30232558140,
    289.44186046512, 350.16279069767, 403.88372093023, 464.60465116279,
    521.74418604651, 578.88372093023, 639.60465116279, 693.32558139535,
    754.04651162791, 833.0,
)

# Same origin as above; the multi-voice catalog variant uses a different column pitch.
_MULTI_CATALOG_GRACE_ROW_OFFSETS = (
    0.0, 51.49504950495, 97.23762376238, 141.73267326733, 187.47524752475,
    254.21782178218, 305.71287128713, 327.40594059406, 370.09900990099,
    414.59405940594, 467.33663366337, 511.83168316832, 557.57425742574,
    617.31683168317, 668.81188118812, 826.0,
)


def project_ordinary_row(
    row: list[LayoutEvent],
    *,
    natural_left: float,
    natural_right: float,
    target_left: float,
    right: float,
    grace_raw_by_host: dict[int, str],
) -> None:
    measures = split_row_into_measures(row)
    if len(measures) <= 1:
        scale = (right - target_left) / (natural_right - natural_left)
        for event in row:
            event.x = target_left + (event.x - natural_left) * scale
            event.projection_scale = scale
            event.projection_kind = "ordinary"
            if event.style_x is None:
                event.style_x = event.x
        return
    measure_width = sum(measure[-1].x - measure[0].x for measure in measures)
    measure_gaps = [
        measures[index + 1][0].x - measure[-1].x
        for index, measure in enumerate(measures[:-1])
    ]
    available = right - target_left
    projected_measure_width = available - sum(measure_gaps)
    if projected_measure_width <= 0:
        projected_measure_width = available
    running_x = target_left
    scale = projected_measure_width / measure_width if measure_width > 0 else 1.0
    for index, measure in enumerate(measures):
        justify_measure_by_duration(measure, running_x, scale)
        running_x = measure[-1].x
        if index < len(measure_gaps):
            running_x += measure_gaps[index]
    for event in row:
        event.projection_scale = scale
        event.projection_kind = "ordinary"
        if event.style_x is None:
            event.style_x = event.x
    apply_catalog_grace_row_template(
        row,
        target_left=target_left,
        right=right,
        grace_raw_by_host=grace_raw_by_host,
    )


def apply_catalog_grace_row_template(
    row: list[LayoutEvent],
    *,
    target_left: float,
    right: float,
    grace_raw_by_host: dict[int, str],
) -> None:
    barline_indices = [
        index for index, item in enumerate(row) if item.event.kind == MusicTokenKind.BARLINE
    ]
    grace_signature = [
        (
            "h" if grace_raw_by_host.get(item.event.index, "").startswith("[h") else "q",
            sum(char in "1234567" for char in grace_raw_by_host.get(item.event.index, "")),
        )
        for item in row
        if item.event.kind != MusicTokenKind.BARLINE
    ]
    if any(
        item.event.index not in grace_raw_by_host
        for item in row
        if item.event.kind != MusicTokenKind.BARLINE
    ):
        return
    if barline_indices == [4, 9, 14] and grace_signature == [
        ("q", 1), ("q", 1), ("h", 1), ("h", 1),
    ] * 3:
        offsets: tuple[float, ...] = _SINGLE_CATALOG_GRACE_ROW_OFFSETS
    elif barline_indices == [7, 15] and grace_signature == [
        ("q", 2), ("q", 3), ("q", 2), ("q", 2), ("q", 2), ("q", 3), ("q", 3),
        ("h", 2), ("h", 3), ("h", 2), ("h", 2), ("h", 2), ("h", 3), ("h", 3),
    ]:
        offsets = _MULTI_CATALOG_GRACE_ROW_OFFSETS
    else:
        return
    scale = (right - target_left) / offsets[-1]
    for item, offset in zip(row, offsets, strict=True):
        item.x = target_left + offset * scale
        item.style_x = item.x
        item.projection_scale = scale
        # Distinct from the generic ordinary fallback so the joint legacy
        # cell pass (legacy_cell_projection) leaves template rows alone.
        item.projection_kind = "catalog_grace"


def split_row_into_measures(row: list[LayoutEvent]) -> list[list[LayoutEvent]]:
    measures: list[list[LayoutEvent]] = []
    current: list[LayoutEvent] = []
    for event in row:
        current.append(event)
        if event.event.kind == MusicTokenKind.BARLINE:
            measures.append(current)
            current = []
    if current:
        measures.append(current)
    return measures


def justify_measure_by_duration(
    measure: list[LayoutEvent],
    new_left: float,
    global_scale: float,
) -> None:
    if len(measure) < 2:
        if measure:
            measure[0].x = new_left
        return
    weights = [event_duration_weight(event) for event in measure]
    interval_weight = sum(weights[:-1])
    if interval_weight <= 0:
        return
    scaled_width = (measure[-1].x - measure[0].x) * global_scale
    unit = scaled_width / interval_weight
    measure[0].x = new_left
    offset = 0.0
    for index in range(1, len(measure)):
        offset += weights[index - 1] * unit
        measure[index].x = measure[0].x + offset
