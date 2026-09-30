"""Stable entry points; implementations live in the focused modules below."""

from octopus.normalization.types import (
    LyricLineModel,
    MusicEvent,
    ScoreModel,
    SystemModel,
    VoiceGroupModel,
    VoiceModel,
)
from octopus.parser.ast import MusicTokenKind
from octopus.render.compatibility_identity import compatibility_profile_key
from octopus.render.core.layout_metrics import (
    DEFAULT_PAGE_HEIGHT,
    DEFAULT_PAGE_WIDTH,
    page_metrics,
)
from octopus.render.core.layout_types import (
    DEFAULT_NOTE_START_OFFSET,
    LayoutAddress,
    LayoutConstruct,
    LayoutEvent,
    LayoutGrace,
    LayoutHeader,
    LayoutLyric,
    LayoutMark,
    LayoutPage,
    LayoutVoiceBrace,
    PageMetrics,
    RowLayoutInput,
)
from octopus.render.core.layout_widths import (
    BARLINE_EXTRA_GAP,
    BARLINE_WIDTH,
    EXTENSION_WIDTH,
    INLINE_TIME_SIGNATURE_WIDTH,
    MEASURE_GAP,
    NOTE_WIDTH,
    REST_WIDTH,
    compute_event_width,
)
from octopus.render.layout_engine.event_selection import (
    visible_events_for_layout as _visible_events_for_layout,
)
from octopus.render.layout_engine.grid.beat_grid import TIMED_KINDS
from octopus.render.layout_engine.header import compute_header
from octopus.render.layout_engine.hidden.hidden_rest_slots import reconcile_hidden_rest_slots
from octopus.render.layout_engine.hidden.hidden_stream_layout import (
    hidden_dsb_events_for_layout,
    lower_aligned_visible_dsb_targets,
)
from octopus.render.layout_engine.page import layout_page
from octopus.render.layout_engine.parallel_sustain import align_parallel_sustain_sentinel_rows
from octopus.render.layout_engine.profiles import SystemSpacingProfile
from octopus.render.layout_engine.shared_system.hidden_projection import (
    reproject_hidden_dsb_events,
)
from octopus.render.layout_engine.shared_system.models import SharedSystemRequest
from octopus.render.layout_engine.shared_system.parallel_refrain import (
    align_parallel_refrain_rows,
    uses_parallel_refrain_rows,
)
from octopus.render.layout_engine.shared_system.pipeline import (
    SharedSystemPipelineRequest,
    run_shared_system_pipeline,
)
from octopus.render.layout_engine.shared_system.projection import SharedProjectionPlan
from octopus.render.layout_engine.syllabic.models import SyllabicRowRequest
from octopus.render.layout_engine.syllabic.planning import build_syllabic_projection_plan
from octopus.render.layout_engine.syllabic.projection import project_syllabic_row
from octopus.render.layout_engine.system_state import (
    BZ_PLACEHOLDER_INDEX_START,
    DSB_BRACKET_OVERLAP,
    DSB_GENERATED_TAIL_PLACEHOLDER_INDEX_START,
    DSB_INCOMING_CLEARANCE,
    DSB_PLACEHOLDER_INDEX_START,
    REPEAT_ENDING_CLEARANCE,
    SHARED_DSB_PLACEHOLDER_RESERVE,
    TERMINAL_MARK_CLEARANCE,
)

from .layout_engine.grid.shared_grid_policies import (  # noqa: F401 - compatibility re-export
    uses_alternating_four_voice_lyric_grid as _uses_alternating_four_voice_lyric_grid,
)
from .layout_engine.grid.shared_grid_policies import (  # noqa: F401 - compatibility re-export
    uses_lyric_unequal_slot_duration_grid as _uses_lyric_unequal_slot_duration_grid,
)
from .layout_engine.grid.shared_grid_policies import (  # noqa: F401 - compatibility re-export
    uses_single_lyric_compound_grid as _uses_single_lyric_compound_grid,
)
from .layout_engine.grid.shared_grid_policies import (  # noqa: F401 - compatibility re-export
    uses_single_lyric_unequal_slot_duration_grid as _uses_single_lyric_unequal_slot_duration_grid,
)
from .layout_engine.hidden.hidden_streams import (
    bz_placeholder_event as _bz_placeholder_event,  # noqa: F401 - compatibility re-export
)
from .layout_engine.intrinsic.builder import (  # noqa: F401 - compatibility re-export
    build_legacy_intrinsic_profile as _legacy_intrinsic_profile,
)
from .layout_engine.profile_widths import (  # noqa: F401 - compatibility re-export
    transfer_non_partitioned_terminal_reserves as _transfer_non_partitioned_terminal_reserves,
)
from .layout_engine.rows.row_signatures import (  # noqa: F401 - compatibility re-export
    shared_measure_durations_match as _shared_measure_durations_match,
)
from .layout_engine.shared_system.post_authority import (  # noqa: F401
    _redistribute_compound_dotted_pair_reserves,
)

__all__ = [
    "BARLINE_EXTRA_GAP",
    "BARLINE_WIDTH",
    "BZ_PLACEHOLDER_INDEX_START",
    "DEFAULT_NOTE_START_OFFSET",
    "DEFAULT_PAGE_HEIGHT",
    "DEFAULT_PAGE_WIDTH",
    "DSB_BRACKET_OVERLAP",
    "DSB_GENERATED_TAIL_PLACEHOLDER_INDEX_START",
    "DSB_INCOMING_CLEARANCE",
    "DSB_PLACEHOLDER_INDEX_START",
    "EXTENSION_WIDTH",
    "INLINE_TIME_SIGNATURE_WIDTH",
    "LayoutAddress",
    "LayoutConstruct",
    "LayoutEvent",
    "LayoutGrace",
    "LayoutHeader",
    "LayoutLyric",
    "LayoutMark",
    "LayoutPage",
    "LayoutVoiceBrace",
    "LyricLineModel",
    "MEASURE_GAP",
    "MusicEvent",
    "MusicTokenKind",
    "NOTE_WIDTH",
    "PageMetrics",
    "REPEAT_ENDING_CLEARANCE",
    "REST_WIDTH",
    "RowLayoutInput",
    "SHARED_DSB_PLACEHOLDER_RESERVE",
    "ScoreModel",
    "SharedProjectionPlan",
    "SharedSystemPipelineRequest",
    "SharedSystemRequest",
    "SyllabicRowRequest",
    "SystemModel",
    "SystemSpacingProfile",
    "TERMINAL_MARK_CLEARANCE",
    "TIMED_KINDS",
    "VoiceGroupModel",
    "VoiceModel",
    "align_parallel_refrain_rows",
    "align_parallel_sustain_sentinel_rows",
    "build_syllabic_projection_plan",
    "compatibility_profile_key",
    "compute_event_width",
    "compute_header",
    "hidden_dsb_events_for_layout",
    "layout_page",
    "lower_aligned_visible_dsb_targets",
    "page_metrics",
    "project_syllabic_row",
    "reconcile_hidden_rest_slots",
    "reproject_hidden_dsb_events",
    "run_shared_system_pipeline",
    "uses_parallel_refrain_rows",
]

visible_events_for_layout = _visible_events_for_layout
__all__.append("visible_events_for_layout")
