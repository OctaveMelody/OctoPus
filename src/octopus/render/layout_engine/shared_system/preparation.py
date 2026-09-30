"""Admission and classification entry point for the shared-system pipeline."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from ...core.layout_types import PageMetrics
from .admission import admit_shared_system
from .classification import classify_shared_system
from .models import (
    SharedSystemAdmission,
    SharedSystemClassification,
    SharedSystemClassificationRequest,
    SharedSystemRequest,
)


def prepare_shared_system(
    request: SharedSystemRequest,
    *,
    metrics: PageMetrics,
    primary_system_verse_count: int,
) -> tuple[SharedSystemAdmission, SharedSystemClassification] | None:
    admission = admit_shared_system(request)
    if admission is None:
        return None
    classification = classify_shared_system(
        SharedSystemClassificationRequest(
            admission=admission,
            metrics=metrics,
            left=request.left,
            primary_system_verse_count=primary_system_verse_count,
            system_row_count=request.system_row_count,
        )
    )
    if classification is None:
        return None
    row_voices = {row[0].voice for row in admission.rows}
    admission = replace(
        admission,
        lyric_text_by_voice=MappingProxyType(
            {
                voice: admission.lyric_text_by_voice.get(voice, MappingProxyType({}))
                for voice in row_voices
            }
        ),
        lyric_gap_by_voice=MappingProxyType(
            {
                voice: admission.lyric_gap_by_voice.get(voice, MappingProxyType({}))
                for voice in row_voices
            }
        ),
    )
    return admission, classification


__all__ = ["prepare_shared_system"]
