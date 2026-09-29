"""Source-row topology helpers for the normalized score model.

Keeping these evidence-oriented helpers separate prevents the core normalizer
from accumulating snapshot and grouping policy while preserving its public
model API through compatibility imports in :mod:`re_tomato.model`.
"""

from __future__ import annotations

from typing import Any

from re_tomato._json import json_value
from re_tomato.normalization.types import (
    MusicRowAddress,
    ScoreModel,
    UnresolvedSpanState,
    VoiceGroupModel,
)
from re_tomato.parser.ast import MusicLine, MusicToken, MusicTokenKind, PageBreakLine
from re_tomato.parser.source import SourceSpan


def derive_voice_groups(
    page_index: int,
    system_index: int,
    lines: list[Any],
) -> tuple[VoiceGroupModel, ...]:
    """Derive source-declared horizontal groups from physical Q rows.

    ``Q:`` and ``Q1:`` rows start a group; ``Q2:`` and higher rows continue
    the current group. Repeated starters remain separate groups, including
    repeated unnumbered rows used by DSB streams.
    """
    groups: list[list[MusicRowAddress]] = []
    current: list[MusicRowAddress] | None = None
    music_lines = [line for line in lines if isinstance(line, MusicLine)]
    for row_index, line in enumerate(music_lines):
        continuation = line.voice >= 2 and current is not None
        if current is None or not continuation:
            current = []
            groups.append(current)
        current.append(
            MusicRowAddress(
                page_index=page_index,
                system_index=system_index,
                row_index=row_index,
                voice=line.voice,
                source_line=line.span.start.line,
                continuation=continuation,
            )
        )
    return tuple(
        VoiceGroupModel(
            index=index,
            rows=tuple(rows),
            source_span=_combine_spans(
                music_lines[rows[0].row_index].span,
                music_lines[rows[-1].row_index].span,
            )
            if rows
            else None,
        )
        for index, rows in enumerate(groups)
    )


def collect_unresolved_span_states(lines: tuple[Any, ...]) -> tuple[UnresolvedSpanState, ...]:
    """Retain unmatched delimiter state with parser-owned source identity."""

    stacks: dict[int, list[tuple[MusicToken, int, str, int]]] = {}
    page_index = 1
    closer_openers = {
        MusicTokenKind.SPAN_END: {
            MusicTokenKind.SPAN_START,
            MusicTokenKind.TUPLET_START,
        }
    }
    for line in lines:
        if isinstance(line, PageBreakLine):
            page_index += 1
            continue
        if not isinstance(line, MusicLine):
            continue
        source_voice = line.source_voice if line.source_voice is not None else line.voice
        stack = stacks.setdefault(source_voice, [])
        prior_span_count = 0
        for token in line.tokens:
            if token.kind in {MusicTokenKind.SPAN_START, MusicTokenKind.TUPLET_START}:
                family = "tuplet" if token.kind == MusicTokenKind.TUPLET_START else "span"
                stack.append((token, page_index, family, prior_span_count))
                if family == "span":
                    prior_span_count += 1
                continue
            allowed = closer_openers.get(token.kind)
            if allowed is None:
                continue
            while stack and stack[-1][0].kind not in allowed:
                stack.pop()
            if stack:
                stack.pop()
    return tuple(
        UnresolvedSpanState(
            source_voice=source_voice,
            source_span=token.span,
            page_index=opener_page,
            prior_span_count=opener_prior_span_count,
            family=family,
        )
        for source_voice, stack in sorted(stacks.items())
        for token, opener_page, family, opener_prior_span_count in stack
    )


def topology_to_dict(
    model: ScoreModel, *, include_diagnostics: bool = False
) -> dict[str, Any]:
    """Serialize source row groups without provenance by default."""
    pages: list[dict[str, Any]] = []
    for page in model.pages:
        systems: list[dict[str, Any]] = []
        for system in page.systems:
            groups = [
                {
                    "index": group.index,
                    "source_span": json_value(group.source_span)
                    if group.source_span is not None
                    else None,
                    "rows": [
                        {
                            "page_index": row.page_index,
                            "system_index": row.system_index,
                            "row_index": row.row_index,
                            "voice": row.voice,
                            "source_line": row.source_line,
                            "continuation": row.continuation,
                        }
                        for row in group.rows
                    ],
                }
                for group in system.voice_groups
            ]
            systems.append({"index": system.index, "voice_groups": groups})
        pages.append({"index": page.index, "systems": systems})
    result: dict[str, Any] = {"schema_version": 1, "pages": pages}
    if include_diagnostics:
        result["source_key"] = model.source_key
    return result


def strip_internal_construct_metadata(value: Any) -> Any:
    """Keep compatibility snapshots free of renderer-only topology fields."""
    if isinstance(value, dict):
        return {
            key: strip_internal_construct_metadata(item)
            for key, item in value.items()
            if key
            not in {
                "constructs",
                "construct_ids",
                "construct_roles",
                "singleton_parenthesis_provenance",
                "voice_groups",
                "source_voice_by_line",
                "unresolved_span_states",
            }
        }
    if isinstance(value, list):
        return [strip_internal_construct_metadata(item) for item in value]
    return value


def _combine_spans(
    start: SourceSpan | None,
    end: SourceSpan | None,
) -> SourceSpan | None:
    if start is None or end is None:
        return start or end
    return SourceSpan(start.start, end.end)


__all__ = [
    "collect_unresolved_span_states",
    "derive_voice_groups",
    "strip_internal_construct_metadata",
    "topology_to_dict",
]
