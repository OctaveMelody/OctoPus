"""Pitch-mark candidates that a rule rejected, and why (plan §6 step 1).

A missed octave dot and a deliberately rejected octave dot used to be indistinguishable from
outside `note_modifiers()`: every rejection path returned a plain number. These records turn each
silent path into a named bucket carrying the measurements the candidate failed, so a development
harness can attribute a gold-adjudicated mark to the rule that dropped it.

This module is a leaf on purpose (`marks` cannot import `observations`, which reaches `marks`
through `text`/`glyphs`/`decorations`), and it is observation only: no rule, compilation step or
renderer reads it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .components import Box


class MarkRejection(StrEnum):
    """The silent rejection paths of the octave-dot and accidental readers, named."""

    SIZE_WINDOW = "size_window"
    FILL_RATIO = "fill_ratio"
    INK_CORRELATION = "ink_correlation"
    INSIDE_FERMATA_DOT = "inside_fermata_dot"
    LINE_NEAR_MISS = "line_near_miss"
    EMISSION = "emission"
    LINE_CAP = "line_cap"
    HORIZONTAL_OFFSET = "horizontal_offset"
    OUT_OF_REACH = "out_of_reach"
    ABOVE_AND_BELOW = "above_and_below"
    JOINED_BEAM_OWNED = "joined_beam_owned"
    DURATION_DOT_LIMIT = "duration_dot_limit"
    ACCIDENTAL_SIZE = "accidental_size"
    ACCIDENTAL_UNCLASSIFIED = "accidental_unclassified"
    ACCIDENTAL_VERTICAL_OFFSET = "accidental_vertical_offset"
    ACCIDENTAL_AMBIGUOUS_MULTIPLE = "accidental_ambiguous_multiple"


@dataclass(frozen=True, slots=True)
class PitchMarkCandidate:
    """One rejected octave-dot or accidental candidate, with the measurements it failed."""

    box: Box
    kind: str            # "octave_dot" | "duration_dot" | "accidental"
    stage: MarkRejection
    note_index: int = -1    # index of the note whose window held the candidate; -1 when none
    features: str = ""      # "key=value,…" dump of the measured geometry and scores
