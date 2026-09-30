"""Beat-grid value types, event keys, timed kinds, and spacing constants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TypeAlias

from octopus.normalization.types import MusicEvent
from octopus.parser.ast import MusicTokenKind

PLAIN_NOTE_STEP = 37.5


UNDERLINED_NOTE_STEP = 25.0


BARLINE_GAP = 35.0


# A meter-change annotation (``|"p:2/4"``) reserves one within-beat step of
# width after its barline even though no glyph is drawn for the label.
METER_LABEL_WIDTH = 25.0


FINAL_SYMBOL_WIDTH = 14.0


PUNCTUATION = set("，。！？；：,.!?;:")


# Layout structure: a line is a list of measures, a measure a list of beats,
# and a beat a list of (event, lyric_overflow) items.
BeatItem = tuple[MusicEvent, float]


Beat = list[BeatItem]


Measure = list[Beat]


Line = list[Measure]


BeatShape = tuple[tuple[int, ...], ...]


# Events that advance the beat grid (reference 'note' + 'sustain'). A hidden
# rest '8' is a reference 'note' (sound 'rest'), so it is timed like a note.
TIMED_KINDS = frozenset(
    {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.HIDDEN_REST,
        MusicTokenKind.EXTENSION,
    }
)


# Events that consume a lyric syllable (reference 'note' only; sustain does not).
SYLLABLE_KINDS = frozenset(
    {
        MusicTokenKind.NOTE,
        MusicTokenKind.REST,
        MusicTokenKind.RHYTHM_NOTE,
        MusicTokenKind.HIDDEN_REST,
    }
)


@dataclass(frozen=True)
class BeatGridLayout:
    """Natural (uncompressed) layout of a voice group.

    ``bar_x_offsets`` are the barline x offsets from the group start,
    ``note_x_offsets[line]`` the natural note-column x offset for line ``line``
    (in source order), and ``end_offset`` the final barline x offset.
    """

    bar_x_offsets: tuple[float, ...]
    note_x_offsets: tuple[tuple[float, ...], ...]
    end_offset: float


@dataclass(frozen=True, order=True, slots=True)
class GridEventKey:
    """Stable identity for an event in a shared voice grid.

    ``MusicEvent.index`` is only unique within a normalized voice stream, so
    the source line and the caller-owned voice index are part of the key.  A
    key is deliberately independent of list position: rows may be reordered
    or may contain events spanning several physical source lines without
    changing the resulting projection.
    """

    voice_index: int
    source_line: int
    event_index: int

    @classmethod
    def for_event(cls, event: MusicEvent, voice_index: int) -> GridEventKey:
        return cls(voice_index, event.span.start.line, event.index)


LyricTextByEvent: TypeAlias = Mapping[tuple[int, int], Sequence[str]]


@dataclass(frozen=True, slots=True)
class SharedGridRow:
    """One voice stream participating in an event-keyed shared projection."""

    voice_index: int
    events: tuple[MusicEvent, ...]
    lyric_text_by_event: LyricTextByEvent = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Accept lists from normalizer/layout callers while keeping the
        # projection's public value immutable and deterministic.
        object.__setattr__(self, "events", tuple(self.events))


@dataclass(frozen=True, slots=True)
class SharedGridProjection:
    """Natural shared-grid geometry keyed by stable event identities.

    All geometry and musical onsets are exact ``Fraction`` values.  Consumers
    can convert to floats only at the final SVG serialization boundary.  The
    range for measure ``i`` is ``(start_x, barline_x)``; the next measure starts
    after :data:`BARLINE_GAP`, matching the existing renderer convention.
    """

    event_x_offsets: Mapping[GridEventKey, Fraction]
    event_onsets: Mapping[GridEventKey, Fraction]
    lyric_overflows: Mapping[GridEventKey, Fraction]
    barline_x_offsets: tuple[Fraction, ...]
    measure_ranges: tuple[tuple[Fraction, Fraction], ...]
    measure_widths: tuple[Fraction, ...]
    natural_width: Fraction
    # Stretched-space (unscaled) shifts caused by unquoted grace markers, see
    # MusicEvent.grace_reservation.  Event x = left + offset * scale + shift.
    event_grace_shifts: Mapping[GridEventKey, int] = field(default_factory=dict)
    # Per-row barline shifts keyed by (voice_index, barline_ordinal); the
    # final barline is right-edge pinned and never uses these.
    barline_grace_shifts: Mapping[tuple[int, int], int] = field(default_factory=dict)
    # Total stretched units reserved by counting markers; the caller reduces
    # the available width by this amount when solving the compression scale.
    grace_reservation_total: int = 0
    # Stretched units the system's left edge moves right for a marker on its
    # first column (see _grace_marker_shifts).
    grace_left_delta: int = 0

    def x_offset(self, key: GridEventKey) -> Fraction:
        return self.event_x_offsets[key]


@dataclass(frozen=True, slots=True)
class _ExactGridItem:
    event: MusicEvent
    overflow: Fraction
    onset: Fraction
    tied: bool = False


_ExactBeat = list[_ExactGridItem]


_ExactMeasure = list[_ExactBeat]


_ExactLine = list[_ExactMeasure]
