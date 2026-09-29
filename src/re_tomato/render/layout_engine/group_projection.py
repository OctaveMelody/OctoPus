"""Project authoritative voice groups and aligned lyricless row runs."""

from __future__ import annotations

from re_tomato.normalization.types import VoiceGroupModel
from re_tomato.parser.ast import MusicTokenKind
from re_tomato.render.core.layout_types import (
    LayoutEvent,
    PageMetrics,
)
from re_tomato.render.layout_engine.grid.beat_grid import TIMED_KINDS
from re_tomato.render.layout_engine.shared_system.models import SharedSystemRequest
from re_tomato.render.layout_engine.shared_system.pipeline import (
    SharedSystemPipelineRequest,
    run_shared_system_pipeline,
)
from re_tomato.render.layout_engine.shared_system.projection import SharedProjectionPlan


def _is_direct_grid_candidate(
    events: list[LayoutEvent],
) -> bool:
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
    hidden_events: list[LayoutEvent] | None = None,
) -> SharedProjectionPlan | None:
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
            group_hidden_events = tuple(
                item
                for item in hidden_events or ()
                if item.voice in group_voices
                and item.event.span.start.line in source_lines
            )
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
                        hidden_events=group_hidden_events,
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
                hidden_events=tuple(hidden_events or ()),
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
