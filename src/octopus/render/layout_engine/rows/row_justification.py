"""Horizontal row justification for laid-out systems.

Split from ``render/layout.py`` (item 24, TD-2 ceiling ratchet) as a pure move:
these six functions take a system's laid-out events and fit each voice row to
the available page width — legacy syllabic rows keep their own scale chain,
shared-intrinsic groups project on the shared grid, lyricless aligned runs
inherit group scales, and every generated projection plan is registered for the
later lyric/secondary passes. No state escapes this module except the mutated
event x coordinates and the shared-projection-plan registry.
"""

from __future__ import annotations

from dataclasses import replace

from ....model.model_normalize import VoiceGroupModel
from ....parser.ast import MusicTokenKind
from ...core.layout_types import LayoutEvent, PageMetrics
from ..cross_row_hooks import plan_cross_row_hooks as _plan_cross_row_hooks
from ..grid.beat_grid import TIMED_KINDS
from ..grid.grid_policies import (
    lyricless_alternating_extension_reserve_count as _alternating_extension_reserve_count,
)
from ..grid.grid_policies import (
    uses_lyricless_intrinsic_entry_grid as _uses_lyricless_intrinsic_entry_grid,
)
from ..grid.grid_policies import (
    uses_ykh_closer_syllabic_grid as _uses_ykh_closer_syllabic_grid,
)
from ..intrinsic.builder import _uses_cjk_dual_verse_four_four_grid
from ..reserves.interval_reserves import (
    alternating_extension_hook_reserve as _alternating_extension_hook_reserve,
)
from ..shared_system.models import SharedSystemRequest
from ..shared_system.pipeline import (
    SharedSystemPipelineRequest,
    run_shared_system_pipeline,
)
from ..shared_system.projection import SharedProjectionPlan
from ..streams import uses_compound_meter as _uses_compound_meter
from ..syllabic.models import SyllabicRowRequest
from ..syllabic.planning import build_syllabic_projection_plan
from ..syllabic.projection import project_syllabic_row
from .row_projection import project_ordinary_row as _project_ordinary_row


def _justify_voice_rows(
    events: list[LayoutEvent],
    metrics: PageMetrics,
    *,
    note_start_x: float | None = None,
    grace_host_indices: frozenset[int] = frozenset(),
    grace_raw_by_host: dict[int, str] | None = None,
    reserves_lyric_dotted_notes: bool = False,
    legacy_intrinsic_source_lines: frozenset[int] = frozenset(),
    numbered_lyric_source_lines: frozenset[int] = frozenset(),
    legacy_lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]] | None = None,
    selects_structural_intrinsic_entries: bool = True,
) -> None:
    """Fit every source row of a laid-out system to the page width.

    Per row (grouped by ``event.line``), one of four strategies runs, in
    priority order:

    1. *Legacy syllabic chain* — rows whose first source line is a legacy
       intrinsic line, structural-intrinsic entry grid, or lyric-less &ykh
       closer row with four or more extension dashes. Cross-row hook reserves
       (zkh openers/terminals facing ykh rows), the CJK dual-verse −9.0
       continuation adjustment, and alternating-extension reserves are folded
       into the syllabic intrinsic width before projection.
    2. *Scale inheritance* — ``|j`` closing rows that follow a legacy row
       first try the previous row's scale ragged (keeping their natural
       width when it fits); if that yields no plan they re-fit freely and
       their scale becomes the next row's inheritance.
    3. *Plain shift* — short ``|j`` rows that fit under the target left are
       just shifted onto it (no re-scaling).
    4. *Ordinary projection* — everything else goes through
       :func:`row_projection.project_ordinary_row`.

    Rows shorter than two events or with non-positive natural width are
    skipped; short legacy rows get a ``style_x`` copy of their positions so
    the syllabic style pass can read them. ``previous_legacy_scale`` is the
    only state carried between consecutive rows.
    """
    by_line: dict[int, list[LayoutEvent]] = {}
    for event in events:
        by_line.setdefault(event.line, []).append(event)
    left = metrics.note_start_x if note_start_x is None else note_start_x
    right = float(metrics.width - metrics.margin_right + 3)
    previous_legacy_scale: float | None = None
    rows = list(by_line.values())
    hook_plan = _plan_cross_row_hooks(rows, legacy_lyric_text_by_event or {})
    lyricless_cross_row_hook_indices = hook_plan.lyricless_rows
    lyricless_cross_row_hook_width_adjustments = hook_plan.width_adjustments
    lyric_to_lyricless_hook_width_adjustments = hook_plan.lyric_to_lyricless_adjustments
    lyric_to_lyricless_hook_openers = hook_plan.lyric_to_lyricless_openers
    uses_lyricless_cross_row_cursor = hook_plan.uses_lyricless_cursor
    for row_index, row in enumerate(rows):
        if len(row) < 2:
            continue
        natural_left = row[0].x
        natural_right = row[-1].x
        if natural_right <= natural_left:
            continue
        target_left = (
            left
            + (10 if "zkh" in row[0].event.decorations else 0)
            + (
                7 * (1 + row[0].event.duration_slashes)
                if row[0].event.index in grace_host_indices
                else 0
            )
        )
        legacy_short_row = natural_right - natural_left < (right - left) * 0.7
        if legacy_short_row:
            legacy_shift = target_left - natural_left
            for event in row:
                event.style_x = event.x + legacy_shift
        alternating_extension_reserve_count = (
            _alternating_extension_reserve_count(
                row,
                legacy_lyric_text_by_event or {},
            )
            if selects_structural_intrinsic_entries
            else 0
        )
        uses_structural_intrinsic_entry_grid = (
            selects_structural_intrinsic_entries
            and _uses_lyricless_intrinsic_entry_grid(
                row,
                legacy_lyric_text_by_event or {},
            )
        )
        # A lyric-less &ykh closer row takes the width-fitted syllabic grid
        # only when it carries four or more plain '-' extension dashes; rows
        # with fewer keep the ordinary per-measure projection (see
        # uses_ykh_closer_syllabic_grid for the oracle probe evidence).
        # Lyric-bearing ykh rows already route here through
        # legacy_intrinsic_source_lines.
        ykh_closer_row = (
            selects_structural_intrinsic_entries
            and _uses_ykh_closer_syllabic_grid(row)
        )
        if (
            row[0].event.span.start.line in legacy_intrinsic_source_lines
            or uses_structural_intrinsic_entry_grid
            or ykh_closer_row
        ):
            opening_cross_row_hook_reserve = (
                9.0
                if "zkh" in row[0].event.decorations
                and row[0].event.duration_slashes
                and (
                    row[0].event.octave < 0
                    or row[0].event.kind == MusicTokenKind.REST
                    or (
                        _uses_compound_meter(metrics.time_sig)
                        and len(row) > 1
                        and row[1].event.kind == MusicTokenKind.BARLINE
                    )
                )
                and not any(
                    text
                    for item in row
                    for text in (legacy_lyric_text_by_event or {}).get(
                        (item.event.span.start.line, item.event.index),
                        (),
                    )
                )
                and not any("ykh" in item.event.decorations for item in row)
                and row_index + 1 < len(rows)
                and any(
                    "ykh" in item.event.decorations
                    for item in rows[row_index + 1]
                )
                else 0.0
            )
            terminal_cross_row_hook = bool(
                "zkh" in row[-2].event.decorations
                and not row[-2].event.duration_slashes
                and not any("ykh" in item.event.decorations for item in row)
                and any(
                    "ykh" in item.event.decorations
                    for later_row in rows[row_index + 1 :]
                    for item in later_row
                )
            )
            # REF only compresses rest-free (dense) continuation rows on the
            # CJK dual-verse 4/4 grid. Oracle probes on Half-Pot p1 kept its
            # rest-bearing L9/L12 rows at the unadjusted denominator even when
            # their first measure was reshaped to mirror Auld-Lang-Syne's
            # firing rows, while every Auld-Lang-Syne continuation row that
            # takes the -9 carries zero rests (probe series B/H/T in
            # docs/SLICE_HISTORY.md, item 10).
            dual_verse_continuation_adjustment = (
                -9.0
                if row_index > 0
                and row[-1].event.code == "|"
                and "zkh" not in row[0].event.decorations
                and not any(item.event.kind == MusicTokenKind.REST for item in row)
                and _uses_cjk_dual_verse_four_four_grid(
                    metrics,
                    legacy_lyric_text_by_event or {},
                )
                else 0.0
            )
            previous_legacy_scale = _justify_legacy_syllabic_row(
                row,
                metrics=metrics,
                left=left,
                right=right,
                lyric_text_by_event=legacy_lyric_text_by_event or {},
                grace_host_indices=grace_host_indices,
                grace_raw_by_host=grace_raw_by_host or {},
                reserves_lyric_dotted_notes=reserves_lyric_dotted_notes,
                uses_numbered_cjk_verse_label=(
                    row[0].event.span.start.line in numbered_lyric_source_lines
                ),
                intrinsic_width_adjustment=(
                    opening_cross_row_hook_reserve
                    + (9.0 if terminal_cross_row_hook else 0.0)
                    + dual_verse_continuation_adjustment
                    + lyricless_cross_row_hook_width_adjustments.get(row_index, 0.0)
                    + lyric_to_lyricless_hook_width_adjustments.get(row_index, 0.0)
                    + _alternating_extension_hook_reserve(
                        alternating_extension_reserve_count
                    )
                    + (
                        20.0
                        if row[0].event.span.start.line
                        in numbered_lyric_source_lines
                        else 0.0
                    )
                ),
                uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                terminal_cross_row_hook=terminal_cross_row_hook,
                localizes_cross_row_hook_opener=(
                    row_index in lyric_to_lyricless_hook_openers
                ),
                uses_lyricless_cross_row_compound_grid=(
                    row_index in lyricless_cross_row_hook_indices
                ),
                uses_undivided_cross_row_hook_transfer=(
                    row_index in lyricless_cross_row_hook_width_adjustments
                ),
            )
            continue
        if (
            row[-1].event.code == "|j"
            and previous_legacy_scale is not None
        ):
            if natural_right - natural_left <= right - target_left:
                inherited_scale = _justify_legacy_syllabic_row(
                    row,
                    metrics=metrics,
                    left=left,
                    right=right,
                    lyric_text_by_event=legacy_lyric_text_by_event or {},
                    scale=previous_legacy_scale,
                    ragged=True,
                    grace_host_indices=grace_host_indices,
                    grace_raw_by_host=grace_raw_by_host or {},
                    uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                )
                if inherited_scale is not None:
                    continue
                previous_legacy_scale = _justify_legacy_syllabic_row(
                    row,
                    metrics=metrics,
                    left=left,
                    right=right,
                    lyric_text_by_event=legacy_lyric_text_by_event or {},
                    grace_host_indices=grace_host_indices,
                    grace_raw_by_host=grace_raw_by_host or {},
                    uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
                )
                continue
            previous_legacy_scale = _justify_legacy_syllabic_row(
                row,
                metrics=metrics,
                left=left,
                right=right,
                lyric_text_by_event=legacy_lyric_text_by_event or {},
                grace_host_indices=grace_host_indices,
                grace_raw_by_host=grace_raw_by_host or {},
                uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
            )
            continue
        previous_legacy_scale = None
        if (
            row[-1].event.code == "|j"
            and natural_right - natural_left <= right - target_left
        ):
            shift = target_left - natural_left
            for event in row:
                event.x += shift
            continue
        _project_ordinary_row(
            row,
            natural_left=natural_left,
            natural_right=natural_right,
            target_left=target_left,
            right=right,
            grace_raw_by_host=grace_raw_by_host or {},
        )


def _justify_legacy_syllabic_row(
    row: list[LayoutEvent],
    *,
    metrics: PageMetrics,
    left: float,
    right: float,
    lyric_text_by_event: dict[tuple[int, int], tuple[str, ...]],
    scale: float | None = None,
    ragged: bool = False,
    grace_host_indices: frozenset[int] = frozenset(),
    grace_raw_by_host: dict[int, str] | None = None,
    reserves_lyric_dotted_notes: bool = False,
    uses_numbered_cjk_verse_label: bool = False,
    intrinsic_width_adjustment: float = 0.0,
    uses_lyricless_cross_row_cursor: bool = False,
    terminal_cross_row_hook: bool = False,
    localizes_cross_row_hook_opener: bool = False,
    uses_lyricless_cross_row_compound_grid: bool = False,
    uses_undivided_cross_row_hook_transfer: bool = False,
) -> float | None:
    """Fit one row on the legacy syllabic scale chain; returns its scale.

    Two-phase: a *style pass* first re-projects a copy of the row (trailing
    ``|w`` events excluded from the style source) to read natural positions,
    then :func:`build_syllabic_projection_plan` derives interval widths and
    the scale from those positions against the requested left/right bounds,
    and :func:`project_syllabic_row` writes the final x coordinates. Returns
    the fitted scale (for ``|j`` continuation inheritance) or ``None`` when
    the plan builder rejects the row (the caller then falls back to a free
    re-fit).
    """
    request = SyllabicRowRequest(
        row=row,
        metrics=metrics,
        left=left,
        right=right,
        lyric_text_by_event=lyric_text_by_event,
        requested_scale=scale,
        ragged=ragged,
        grace_host_indices=grace_host_indices,
        grace_raw_by_host=grace_raw_by_host or {},
        reserves_lyric_dotted_notes=reserves_lyric_dotted_notes,
        uses_numbered_cjk_verse_label=uses_numbered_cjk_verse_label,
        intrinsic_width_adjustment=intrinsic_width_adjustment,
        uses_lyricless_cross_row_cursor=uses_lyricless_cross_row_cursor,
        terminal_cross_row_hook=terminal_cross_row_hook,
        localizes_cross_row_hook_opener=localizes_cross_row_hook_opener,
        uses_lyricless_cross_row_compound_grid=uses_lyricless_cross_row_compound_grid,
        uses_undivided_cross_row_hook_transfer=uses_undivided_cross_row_hook_transfer,
    )
    style_row = [replace(item) for item in row]
    style_source_row = (
        style_row[:-1]
        if style_row[-1].event.code == "|w"
        else style_row
    )
    _justify_voice_rows(
        style_source_row,
        metrics,
        note_start_x=left,
        selects_structural_intrinsic_entries=False,
    )
    style_positions = [
        item.style_x if item.style_x is not None else item.x
        for item in style_row
    ]
    projection_plan = build_syllabic_projection_plan(request, tuple(style_positions))
    if projection_plan is None:
        return None
    project_syllabic_row(projection_plan)
    return projection_plan.scale


def _is_direct_grid_candidate(
    events: list[LayoutEvent],
) -> bool:
    """Whether a four-voice group may project directly on the shared grid."""
    # Any four-voice group may own its x on the shared duration grid when it
    # is projected alone; the pipeline's eligibility check makes the final
    # call.  Span/annotation tokens are invisible to the grid's x projection,
    # and decorations (dynamics, accidentals) no longer disqualify a group:
    # the grid carries accidental-aware phantom columns and terminal
    # reserves, while dynamics do not affect width.  Lyric coverage is not
    # required: reference systems carry lyrics on any subset of their rows.
    # Oracle-verified 2026-08-23 on Looking-Back p4 L128-L133 / L138-L143:
    # consecutive voice groups in one source system are separate reference
    # systems, each laid out on the shared grid with its own scale.
    if len({item.voice for item in events}) != 4:
        return False
    allowed = {
        MusicTokenKind.BARLINE,
        *TIMED_KINDS,
        MusicTokenKind.SPAN_START,
        MusicTokenKind.SPAN_END,
        MusicTokenKind.ANNOTATION,
        MusicTokenKind.GRACE_GROUP,
    }
    return not any(item.event.kind not in allowed for item in events)


def _justify_shared_intrinsic_voice_rows(
    events: list[LayoutEvent],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]],
    lyric_gap_by_voice: dict[int, dict[tuple[int, int], int]],
    grace_raw_by_voice: dict[int, dict[int, str]] | None = None,
    primary_system_verse_count: int = 0,
    system_row_count: int | None = None,
    authoritative_groups: tuple[VoiceGroupModel, ...] = (),
    projection_plans: dict[tuple[int, int], SharedProjectionPlan] | None = None,
    grid_lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]] | None = None,
) -> SharedProjectionPlan | None:
    """Project the system (or its qualifying voice groups) on the shared grid.

    Each authoritative multi-row group that passes :func:`_is_direct_grid_candidate`
    is run through the shared-system pipeline with *its own* events and only
    the lyric metadata of the voices it contains — a sibling group's lyrics
    must not make this group look like it is missing a lyric-bearing voice
    (admission would reject it). Every admitted plan is registered in
    ``projection_plans`` for the later lyric/secondary passes, and the first
    admitted plan is returned. If no group qualifies, the whole system's
    events are projected as one group instead; the pipeline returns ``None``
    when its eligibility check declines (the caller keeps the natural pass).
    """
    multi_voice_groups = tuple(
        group
        for group in authoritative_groups
        if len(group.rows) >= 2
    )
    candidate_groups = tuple(
        group
        for group in multi_voice_groups
        if _is_direct_grid_candidate(
            [
                item
                for item in events
                if item.event.span.start.line in frozenset(
                    group.source_lines
                )
            ]
        )
    )
    if candidate_groups:
        first_plan: SharedProjectionPlan | None = None
        for group in candidate_groups:
            source_lines = frozenset(group.source_lines)
            group_events = [
                item for item in events if item.event.span.start.line in source_lines
            ]
            if not group_events:
                continue
            # Lyric metadata belongs to the voice that owns it; a sibling
            # group's lyrics must not make this group look like it is missing
            # a lyric-bearing voice (admission would reject it).
            group_voices = {item.voice for item in group_events}
            group_plan = run_shared_system_pipeline(
                SharedSystemPipelineRequest(
                    system=SharedSystemRequest(
                        events=group_events,
                        left=left,
                        lyric_text_by_voice={
                            voice: text
                            for voice, text in lyric_text_by_voice.items()
                            if voice in group_voices
                        },
                        lyric_gap_by_voice={
                            voice: gaps
                            for voice, gaps in lyric_gap_by_voice.items()
                            if voice in group_voices
                        },
                        grace_raw_by_voice=grace_raw_by_voice or {},
                        system_row_count=len(group.rows)
                        or system_row_count,
                        authoritative_group_index=group.index,
                        grid_lyric_text_by_voice=grid_lyric_text_by_voice,
                    ),
                    metrics=metrics,
                    primary_system_verse_count=primary_system_verse_count,
                )
            )
            if group_plan is not None:
                first_plan = first_plan or group_plan
                if projection_plans is not None:
                    _register_shared_projection_plan(projection_plans, group_plan)
        if first_plan is not None:
            return first_plan
    return run_shared_system_pipeline(
        SharedSystemPipelineRequest(
            system=SharedSystemRequest(
                events=events,
                left=left,
                lyric_text_by_voice=lyric_text_by_voice,
                lyric_gap_by_voice=lyric_gap_by_voice,
                grace_raw_by_voice=grace_raw_by_voice or {},
                system_row_count=system_row_count,
                grid_lyric_text_by_voice=grid_lyric_text_by_voice,
            ),
            metrics=metrics,
            primary_system_verse_count=primary_system_verse_count,
        )
    )








def _justify_lyricless_aligned_row_runs(
    events: list[LayoutEvent],
    *,
    metrics: PageMetrics,
    left: float,
    lyric_voices: frozenset[int] = frozenset(),
    projection_plans: dict[tuple[int, int], SharedProjectionPlan] | None = None,
    grid_lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]]
    | None = None,
) -> None:
    """Justify consecutive lyric-less rows as aligned shared-grid runs.

    Scans the system's rows for maximal runs of consecutive source lines
    where every row starts at the note start x and belongs to a voice without
    lyrics; each run of two or more distinct voices is projected through the
    shared pipeline with *empty* lyric maps so the sibling rows share one
    grid (and one scale) even though none carries text. Runs are justified
    independently, and the system-wide ``grid_lyric_text_by_voice`` map is
    still passed through: a run can contain rows whose C lines the model
    assigned to another voice (stacked verses), and that overflow belongs on
    the grid (AuldLangSyne-Choir p1 grid 0).
    """
    rows_by_line: dict[int, list[LayoutEvent]] = {}
    for item in events:
        rows_by_line.setdefault(item.line, []).append(item)
    if not any(
        sum(row[0].voice == voice for row in rows_by_line.values()) > 1
        for voice in {row[0].voice for row in rows_by_line.values() if row}
    ):
        return

    run: list[list[LayoutEvent]] = []

    def justify_run() -> None:
        if len(run) < 2 or len({row[0].voice for row in run}) != len(run):
            return
        run_events = [item for row in run for item in row]
        empty_lyrics: dict[int, dict[tuple[int, int], tuple[str, ...]]] = {
            row[0].voice: {} for row in run
        }
        _register_shared_projection_plan(
            projection_plans if projection_plans is not None else {},
            _justify_shared_intrinsic_voice_rows(
                run_events,
                metrics=metrics,
                left=left,
                lyric_text_by_voice=empty_lyrics,
                lyric_gap_by_voice={voice: {} for voice in empty_lyrics},
                # A run can contain rows whose C lines the model assigned to a
                # different voice (stacked verses); the system-wide grid map
                # still carries their overflow (AuldLangSyne-Choir p1 grid 0).
                grid_lyric_text_by_voice=grid_lyric_text_by_voice,
            ),
        )

    previous_line: int | None = None
    for line, row in sorted(rows_by_line.items()):
        eligible = (
            bool(row)
            and row[0].x == left
            and row[0].voice not in lyric_voices
        )
        if not eligible or (previous_line is not None and line != previous_line + 1):
            justify_run()
            run = []
        if eligible:
            run.append(row)
            previous_line = line
        else:
            previous_line = None
    justify_run()


def _register_shared_projection_plan(
    plans: dict[tuple[int, int], SharedProjectionPlan],
    plan: SharedProjectionPlan | None,
) -> None:
    """Record a generated projection plan keyed by (voice, line) per row.

    Grid-owned plans own the group's x values and always win; a legacy cursor
    plan may only fill keys no grid plan claimed. Later lyric/secondary passes
    look up this registry instead of re-projecting.
    """
    if plan is None:
        return
    for row in plan.request.rows:
        if row:
            key = (row[0].voice, row[0].line)
            # A directly projected event-keyed plan owns the group's x values;
            # later lyricless/secondary passes must not replace it with a
            # legacy cursor plan.
            if plan.grid_owned or key not in plans or not plans[key].grid_owned:
                plans[key] = plan
