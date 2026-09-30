"""Public normalization entry points from files, code, and parsed documents."""

from __future__ import annotations

from pathlib import Path

from octopus.jps import JpsDocument, load_jps
from octopus.normalization import brackets as model_brackets
from octopus.normalization.constructs import _annotate_construct_roles
from octopus.normalization.pages import _build_pages
from octopus.normalization.source import collect_ignored_text as _collect_ignored_text
from octopus.normalization.source import source_key_from_path as _source_key_from_path
from octopus.normalization.topology import (
    collect_unresolved_span_states as _collect_unresolved_span_states,
)
from octopus.normalization.types import ScoreHeader, ScoreModel
from octopus.parser.ast import (
    HeaderLine,
    MusicLine,
    ScoreDocument,
)
from octopus.parser.grammar import parse_code, parse_document


def normalize_jps(path: Path) -> ScoreModel:
    source = load_jps(path)
    document = parse_document(source)
    return normalize_document(document, source=source)


def normalize_code(code: str, source_path: str | None = None) -> ScoreModel:
    document = parse_code(code, source_path=source_path)
    return normalize_document(document)


def normalize_document(document: ScoreDocument, source: JpsDocument | None = None) -> ScoreModel:
    source_path = source.path.as_posix() if source is not None else document.source_path
    source_key = source.key if source is not None else _source_key_from_path(source_path)
    original_code = source.original_code if source is not None else document.code
    custom_code = source.custom_code if source is not None else ""
    page_config = dict(source.page_config) if source is not None else {}
    record = dict(source.record) if source is not None else {}
    json_wrapped = source.json_wrapped if source is not None else False
    encoding_repaired = source.encoding_repaired if source is not None else False
    headers = tuple(
        ScoreHeader(line.prefix, line.value, line.span)
        for line in document.lines
        if isinstance(line, HeaderLine)
    )
    ignored_text = _collect_ignored_text(document)
    pages = _build_pages(document)
    model_brackets.reconcile_document_brackets(pages, document.lines, _annotate_construct_roles)
    return ScoreModel(
        source_path=source_path,
        source_key=source_key,
        code=document.code,
        original_code=original_code,
        custom_code=custom_code,
        page_config=page_config,
        record=record,
        json_wrapped=json_wrapped,
        encoding_repaired=encoding_repaired,
        headers=headers,
        ignored_text=ignored_text,
        pages=tuple(page.finalize() for page in pages),
        diagnostics=document.diagnostics,
        source_voice_by_line=tuple(
            (line.span.start.line, line.source_voice)
            for line in document.lines
            if isinstance(line, MusicLine) and line.source_voice is not None
        ),
        unresolved_span_states=_collect_unresolved_span_states(document.lines),
    )
