"""Shared parsing for inline score annotations used during rendering."""

from __future__ import annotations

import re

from ...parser.ast import MusicTokenKind
from .layout_types import LayoutMark


def _inline_time_signature(mark: LayoutMark) -> tuple[str, str] | None:
    if mark.event.kind != MusicTokenKind.ANNOTATION:
        return None
    value = (mark.event.value or mark.event.raw.strip('"')).strip()
    match = re.fullmatch(r"p:(\d+)/(\d+)", value)
    return (match.group(1), match.group(2)) if match else None
