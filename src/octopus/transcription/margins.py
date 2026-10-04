"""Exclude corroborated document pagination without identifying a score by name."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import replace
from statistics import median

from .components import Box
from .image import PageObservation
from .text import TextSpan

_PAGE_NUMBER = re.compile(
    r"(?:[-–—－·•⋅・]\s*)?\d{1,4}(?:\s*[-–—－·•⋅・])?"
    r"|第\s*\d{1,4}\s*页(?:\s*共\s*\d{1,4}\s*页)?"
    r"|共\s*\d{1,4}\s*页"
    r"|page\s+\d{1,4}(?:\s+of\s+\d{1,4})?",
    re.I,
)


def _normalized(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def _pagination(span: TextSpan, page_index: int, side: str) -> bool:
    value = unicodedata.normalize("NFKC", span.text).strip()
    # A numeric first-page title, opus number or tempo is valid header content.
    # Plain numbers become pagination only in bottom margins or on continuation
    # pages; explicit separators/"page" labels also corroborate top pagination.
    return bool(_PAGE_NUMBER.fullmatch(value)) and not (
        page_index == 0 and side == "top" and value.isdecimal()
    )


def _margin(span: TextSpan, page: PageObservation) -> str | None:
    # Restrict recurrence to small running matter, outside the observed score and
    # its lyric/ornament bands. A repeated sung refrain is still score content.
    if span.confidence < 0.85 or span.height <= 0 or span.height > page.height * 0.045:
        return None
    if span.box[3] <= page.height * 0.10:
        side = "top"
    elif span.box[1] >= page.height * 0.90:
        side = "bottom"
    else:
        return None
    page_number = _PAGE_NUMBER.fullmatch(unicodedata.normalize("NFKC", span.text).strip())
    for row in (*page.rows, *(overlay.row for overlay in page.bz_overlays)):
        if not row.notes:
            continue
        height = median(note.box[3] - note.box[1] for note in row.notes)
        # A bare pagination digit may itself have become an isolated candidate row.
        inside = all(
            span.box[0] <= note.box[0] and note.box[2] <= span.box[2]
            and span.box[1] <= note.box[1] and note.box[3] <= span.box[3]
            for note in row.notes
        )
        if page_number and inside and len(row.notes) <= 4 and not (
            row.barlines or row.unresolved_marks or row.slurs or row.graces
            or any(note.octave or note.duration_slashes or note.duration_dots
                   or note.decorations or note.accidental for note in row.notes)
        ):
            continue
        if row.box[1] - height * 2 <= span.center_y <= row.box[3] + height * 3.6:
            return None
    return side


def filter_document_margins(
    pages: tuple[PageObservation, ...],
) -> tuple[tuple[PageObservation, ...], tuple[tuple[int, tuple[Box, ...]], ...]]:
    """Remove margin page numbers and running strings seen on distinct pages.

    Page one's title/credits remain available to header extraction. Continuation
    headers must recur in the same margin or match a first-page title candidate;
    textual identity is evidence within this document, never a filename branch.
    """
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    classified: list[list[tuple[TextSpan, str]]] = []
    for index, page in enumerate(pages):
        values = [(span, side) for span in page.text_spans
                  if (side := _margin(span, page)) is not None]
        classified.append(values)
        for span, side in values:
            occurrences[side, _normalized(span.text)].add(index)
    title_candidates = {
        _normalized(span.text) for span, side in classified[0] if side == "top"
    } if classified else set()
    result = []
    excluded = []
    for index, page in enumerate(pages):
        remove = {
            span for span, side in classified[index]
            if _pagination(span, index, side)
            or (side == "bottom" or index > 0)
            and (len(occurrences[side, _normalized(span.text)]) >= 2
                 or side == "top" and _normalized(span.text) in title_candidates)
        }
        regions = tuple(span.box for span in page.text_spans if span in remove)
        # Remove only unowned, undecorated isolated digits wholly inside a confirmed
        # pagination span. The remaining row indices and all voice/branch owners
        # are rebuilt together; full music rows are never removed by text alone.
        owned = {row for group in page.voice_groups for row in group.rows}
        owned.update(row for overlay in page.dsb_overlays
                     for row in (overlay.anchor, overlay.upper, overlay.lower))
        owned.update(overlay.anchor for overlay in page.bz_overlays)
        removed_rows = {
            row_index for row_index, row in enumerate(page.rows)
            if row_index not in owned and 0 < len(row.notes) <= 4
            and not (row.barlines or row.unresolved_marks or row.slurs or row.graces)
            and not any(note.octave or note.duration_slashes or note.duration_dots
                        or note.decorations or note.accidental for note in row.notes)
            and any(_PAGE_NUMBER.fullmatch(
                unicodedata.normalize("NFKC", span.text).strip(),
            ) and all(
                span.box[0] <= note.box[0] and note.box[2] <= span.box[2]
                and span.box[1] <= note.box[1] and note.box[3] <= span.box[3]
                for note in row.notes
            ) for span in remove)
        }
        mapping = {old: new for new, old in enumerate(
            old for old in range(len(page.rows)) if old not in removed_rows
        )}
        result.append(replace(
            page, text_spans=tuple(span for span in page.text_spans if span not in remove),
            rows=tuple(row for row_index, row in enumerate(page.rows)
                       if row_index not in removed_rows),
            voice_groups=tuple(replace(group, rows=tuple(mapping[row] for row in group.rows))
                               for group in page.voice_groups),
            dsb_overlays=tuple(replace(overlay, anchor=mapping[overlay.anchor],
                                      upper=mapping[overlay.upper], lower=mapping[overlay.lower])
                               for overlay in page.dsb_overlays),
            bz_overlays=tuple(replace(overlay, anchor=mapping[overlay.anchor])
                              for overlay in page.bz_overlays),
        ))
        if regions:
            excluded.append((index + 1, regions))
    return tuple(result), tuple(excluded)
