"""Stable records shared by transcription assembly and review."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

from .image import PageObservation
from .lyrics import LyricDraft


def finite_confidence(value: float) -> float:
    """Export a finite agreement score; it is not a calibrated probability."""
    return min(1.0, max(0.0, value)) if math.isfinite(value) else 0.0


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    page: int
    detail: str
    regions: tuple[tuple[int, int, int, int], ...] = ()
    # Unicode codepoint offsets into Draft.jps; end is exclusive. Classifier
    # agreement is evidence for review, not a calibrated probability.
    confidence: float | None = None
    source_start: int | None = None
    source_end: int | None = None


@dataclass(frozen=True, slots=True)
class Draft:
    jps: str
    pages: tuple[PageObservation, ...]
    issues: tuple[Issue, ...]

    def issue_json(self) -> str:
        return json.dumps(
            {
                "status": "review_required",
                "note_confidence_kind": "uncalibrated_classifier_agreement",
                "pages": [
                    {
                        "width": page.width,
                        "height": page.height,
                        "music_rows": len(page.rows),
                        "candidate_digits": page.candidate_digits,
                        "text_spans": len(page.text_spans),
                        "text_source": page.text_source,
                        "voice_groups": [list(group.rows) for group in page.voice_groups],
                        "dsb_overlays": [asdict(overlay) for overlay in page.dsb_overlays],
                        "bz_overlays": [
                            {"anchor": overlay.anchor, "box": overlay.row.box}
                            for overlay in page.bz_overlays
                        ],
                        "unresolved_braces": list(page.unresolved_braces),
                        "excluded_regions": list(page.excluded_regions),
                        "note_confidence": [
                            {"row": row_index, "note": note_index, "digit": note.digit,
                             "box": note.box, "confidence": finite_confidence(note.confidence),
                             "stream": "main" if row_index < len(page.rows) else "bz"}
                            for row_index, row in enumerate(
                                (*page.rows, *(bz.row for bz in page.bz_overlays))
                            ) for note_index, note in enumerate(row.notes)
                        ],
                    }
                    for page in self.pages
                ],
                "issues": [asdict(issue) for issue in self.issues],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"


@dataclass(frozen=True, slots=True)
class RowBinding:
    page: int
    row: int
    source_line: int
    simple: bool
    lyric_bindings: tuple[tuple[int, LyricDraft], ...] = ()
