"""Stable entry points; implementations live in the focused modules below."""

from re_tomato.normalization.types import MusicEvent as MusicEvent
from re_tomato.parser.ast import MusicTokenKind as MusicTokenKind
from re_tomato.render.layout_engine.beat_grid_engine.analysis import (
    _analyze_line_exact as _analyze_line_exact,
)
from re_tomato.render.layout_engine.beat_grid_engine.analysis import (
    _repartition_exact_lines as _repartition_exact_lines,
)
from re_tomato.render.layout_engine.beat_grid_engine.analysis import analyze_line as analyze_line
from re_tomato.render.layout_engine.beat_grid_engine.analysis import (
    analyze_line_with_lyric_text as analyze_line_with_lyric_text,
)
from re_tomato.render.layout_engine.beat_grid_engine.analysis import (
    four_voice_majority_beat_shape as four_voice_majority_beat_shape,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _accidental_column_reserve as _accidental_column_reserve,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _annotation_widths as _annotation_widths,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _barline_trailing_for_beat as _barline_trailing_for_beat,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _leading_width_fraction as _leading_width_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _phantom_column_step_fraction as _phantom_column_step_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _target_spacing_fraction as _target_spacing_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _trailing_or_overflow_fraction as _trailing_or_overflow_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _within_beat_spacing_fraction as _within_beat_spacing_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.exact_spacing import (
    _within_beat_trailing_fraction as _within_beat_trailing_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.grace import (
    _grace_marker_shifts as _grace_marker_shifts,
)
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import (
    _associated_overflow as _associated_overflow,
)
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import (
    _lyric_overflow_fraction as _lyric_overflow_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import is_cjk as is_cjk
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import lyric_overflow as lyric_overflow
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import lyric_units as lyric_units
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import (
    syllable_overflows as syllable_overflows,
)
from re_tomato.render.layout_engine.beat_grid_engine.lyrics import syllable_texts as syllable_texts
from re_tomato.render.layout_engine.beat_grid_engine.meter import (
    _apply_meter_label_shifts as _apply_meter_label_shifts,
)
from re_tomato.render.layout_engine.beat_grid_engine.natural import (
    compression_scale as compression_scale,
)
from re_tomato.render.layout_engine.beat_grid_engine.natural import natural_layout as natural_layout
from re_tomato.render.layout_engine.beat_grid_engine.natural import (
    natural_measure_widths as natural_measure_widths,
)
from re_tomato.render.layout_engine.beat_grid_engine.natural import (
    natural_measure_widths_for_lines as natural_measure_widths_for_lines,
)
from re_tomato.render.layout_engine.beat_grid_engine.projection import (
    project_event_keyed_grid as project_event_keyed_grid,
)
from re_tomato.render.layout_engine.beat_grid_engine.projection import (
    project_shared_grid as project_shared_grid,
)
from re_tomato.render.layout_engine.beat_grid_engine.spacing import (
    beat_barline_trailing as beat_barline_trailing,
)
from re_tomato.render.layout_engine.beat_grid_engine.spacing import beat_terminal as beat_terminal
from re_tomato.render.layout_engine.beat_grid_engine.spacing import duration_beats as duration_beats
from re_tomato.render.layout_engine.beat_grid_engine.spacing import (
    duration_fraction as duration_fraction,
)
from re_tomato.render.layout_engine.beat_grid_engine.spacing import is_note as is_note
from re_tomato.render.layout_engine.beat_grid_engine.spacing import leading_width as leading_width
from re_tomato.render.layout_engine.beat_grid_engine.spacing import target_spacing as target_spacing
from re_tomato.render.layout_engine.beat_grid_engine.spacing import (
    within_beat_spacing as within_beat_spacing,
)
from re_tomato.render.layout_engine.beat_grid_engine.spacing import (
    within_beat_trailing as within_beat_trailing,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import BARLINE_GAP as BARLINE_GAP
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    FINAL_SYMBOL_WIDTH as FINAL_SYMBOL_WIDTH,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    METER_LABEL_WIDTH as METER_LABEL_WIDTH,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import PLAIN_NOTE_STEP as PLAIN_NOTE_STEP
from re_tomato.render.layout_engine.beat_grid_engine.types import PUNCTUATION as PUNCTUATION
from re_tomato.render.layout_engine.beat_grid_engine.types import SYLLABLE_KINDS as SYLLABLE_KINDS
from re_tomato.render.layout_engine.beat_grid_engine.types import TIMED_KINDS as TIMED_KINDS
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    UNDERLINED_NOTE_STEP as UNDERLINED_NOTE_STEP,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import Beat as Beat
from re_tomato.render.layout_engine.beat_grid_engine.types import BeatGridLayout as BeatGridLayout
from re_tomato.render.layout_engine.beat_grid_engine.types import BeatItem as BeatItem
from re_tomato.render.layout_engine.beat_grid_engine.types import BeatShape as BeatShape
from re_tomato.render.layout_engine.beat_grid_engine.types import GridEventKey as GridEventKey
from re_tomato.render.layout_engine.beat_grid_engine.types import Line as Line
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    LyricTextByEvent as LyricTextByEvent,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import Measure as Measure
from re_tomato.render.layout_engine.beat_grid_engine.types import (
    SharedGridProjection as SharedGridProjection,
)
from re_tomato.render.layout_engine.beat_grid_engine.types import SharedGridRow as SharedGridRow
from re_tomato.render.layout_engine.beat_grid_engine.types import _ExactBeat as _ExactBeat
from re_tomato.render.layout_engine.beat_grid_engine.types import _ExactGridItem as _ExactGridItem
from re_tomato.render.layout_engine.beat_grid_engine.types import _ExactLine as _ExactLine
from re_tomato.render.layout_engine.beat_grid_engine.types import _ExactMeasure as _ExactMeasure

__all__ = [
    "BARLINE_GAP",
    "Beat",
    "BeatGridLayout",
    "BeatItem",
    "BeatShape",
    "FINAL_SYMBOL_WIDTH",
    "GridEventKey",
    "Line",
    "Measure",
    "PLAIN_NOTE_STEP",
    "SharedGridProjection",
    "SharedGridRow",
    "UNDERLINED_NOTE_STEP",
    "analyze_line",
    "analyze_line_with_lyric_text",
    "beat_barline_trailing",
    "beat_terminal",
    "compression_scale",
    "duration_beats",
    "duration_fraction",
    "four_voice_majority_beat_shape",
    "is_cjk",
    "is_note",
    "leading_width",
    "lyric_overflow",
    "lyric_units",
    "natural_layout",
    "natural_measure_widths",
    "natural_measure_widths_for_lines",
    "project_event_keyed_grid",
    "project_shared_grid",
    "syllable_overflows",
    "syllable_texts",
    "target_spacing",
    "within_beat_spacing",
    "within_beat_trailing",
]
