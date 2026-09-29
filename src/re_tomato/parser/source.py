"""Source positions and spans shared by parser and normalized model values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePosition:
    line: int
    column: int
    offset: int


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: SourcePosition
    end: SourcePosition

    @classmethod
    def on_line(
        cls,
        line: int,
        start_column: int,
        end_column: int,
        line_offset: int,
    ) -> SourceSpan:
        return cls(
            SourcePosition(line, start_column, line_offset + start_column - 1),
            SourcePosition(line, end_column, line_offset + end_column - 1),
        )
