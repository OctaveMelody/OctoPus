"""Diagnostic values and sinks used by the recovery-oriented parser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .source import SourceSpan


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity
    span: SourceSpan
    raw: str
    recovery: str


class DiagnosticSink:
    def __init__(self) -> None:
        self._items: list[Diagnostic] = []

    def add(
        self,
        code: str,
        message: str,
        severity: DiagnosticSeverity,
        span: SourceSpan,
        raw: str,
        recovery: str,
    ) -> None:
        self._items.append(Diagnostic(code, message, severity, span, raw, recovery))

    @property
    def items(self) -> tuple[Diagnostic, ...]:
        return tuple(self._items)
