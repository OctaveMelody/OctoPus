"""Stable records shared by image recognition and transcription assembly."""

from __future__ import annotations

from dataclasses import dataclass

from .components import Box
from .decorations import Hairpin
from .ornaments import EndingSegment, GraceGroup
from .text import TextMergeConflict, TextSpan
from .voices import DsbOverlay, VoiceGroup


@dataclass(frozen=True, slots=True)
class Note:
    digit: str
    box: Box
    confidence: float
    octave: int = 0
    duration_slashes: int = 0
    duration_dots: int = 0
    accidental: str = ""
    decorations: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MusicRow:
    notes: tuple[Note, ...]
    barlines: tuple[int, ...]
    box: Box
    unresolved_marks: tuple[Box, ...]
    # Indices address notes only; None marks an endpoint cut at a row barline.
    slurs: tuple[tuple[int | None, int | None], ...] = ()
    graces: tuple[GraceGroup, ...] = ()
    endings: tuple[EndingSegment, ...] = ()
    parentheses: tuple[tuple[int, str], ...] = ()
    hairpins: tuple[Hairpin, ...] = ()
    decoration_regions: tuple[Box, ...] = ()
    score_directions: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class BzOverlay:
    anchor: int
    row: MusicRow


@dataclass(frozen=True, slots=True)
class PageObservation:
    width: int
    height: int
    rows: tuple[MusicRow, ...]
    candidate_digits: int
    text_spans: tuple[TextSpan, ...] = ()
    text_source: str = "unavailable"
    voice_groups: tuple[VoiceGroup, ...] = ()
    dsb_overlays: tuple[DsbOverlay, ...] = ()
    bz_overlays: tuple[BzOverlay, ...] = ()
    unresolved_braces: tuple[Box, ...] = ()
    excluded_regions: tuple[Box, ...] = ()
    native_text_spans: tuple[TextSpan, ...] | None = None
    ocr_text_spans: tuple[TextSpan, ...] | None = None
    text_merge_conflicts: tuple[TextMergeConflict, ...] = ()
