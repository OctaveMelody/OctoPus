"""Engine operations: dispatch engine requests onto the core octopus pipeline.

This is the single dispatch module shared by every transport (stdio sidecar,
dev HTTP server): a transport reads one raw request line and hands it to
:func:`dispatch`, then writes ``protocol.serialize_response(result)``. One
module for all transports means the dev path and the packaged path cannot
drift.

The core pipeline is never modified or re-implemented here: ops calls exactly
what the CLI calls after ``load_jps`` — ``parse_document`` +
``normalize_document`` + ``render_score_model``. It must **not** call
``normalize_code``: that path drops page-level state (page_config,
custom_code, record, source key) and shifts every row ~10–20 px (HANDOFF
gotcha #1).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from octopus import __version__
from octopus.jps import JpsDocument, jps_key, repair_mojibake
from octopus.model.model_normalize import ScoreModel, normalize_document
from octopus.parser.grammar import parse_document
from octopus.render.core.layout_types import LayoutEvent
from octopus.render.layout import LayoutPage, layout_page
from octopus.render.svg import (
    render_page_elements,
    render_score_model_page_with_layout,
    render_score_model_pages,
)
from ui.engine import documents as docs
from ui.engine import jpg_export, pdf_export
from ui.engine.protocol import (
    STATUS_ERROR,
    STATUS_INTERNAL,
    STATUS_OK,
    STATUS_PARSE_ERROR,
    STATUS_RENDER_ERROR,
    DiagnosticItem,
    DocResponse,
    ExportJpgRequest,
    ExportPdfRequest,
    FileImportRequest,
    FileNewRequest,
    FileReadRequest,
    FileSaveAsRequest,
    FileSaveRequest,
    FilesListRequest,
    HitEntry,
    PingRequest,
    PingResponse,
    ProtocolError,
    RecoveryClearRequest,
    RecoveryGetRequest,
    RecoverySetRequest,
    RenderRequest,
    RenderResponse,
    parse_request,
)

# A rendered element's y is serialized as int(item.y) and its x through the
# 14-significant-digit reference formatter, so the true host layout event is
# always within this distance; distinct rows are tens of pixels apart.
_GEOMETRY_MATCH_TOLERANCE = 1.0


def dispatch(line: str) -> PingResponse | RenderResponse | DocResponse:
    """Dispatch one raw JSON request line; never raises.

    Invalid requests map to a ``parse_error`` response that preserves the
    readable id when one was present (null only when it truly was not),
    pipeline failures to ``render_error``, document-operation failures to
    ``error`` (1.2.0), and anything unexpected to ``internal`` so the
    sidecar process survives every input. The outermost guard catches bugs
    in the engine itself (including non-string lines from a broken
    transport) — a sidecar crash is never an option.
    """
    try:
        return _dispatch_line(line)
    except Exception as exc:  # noqa: BLE001 - last-resort safety net
        return RenderResponse(
            id=None,
            status=STATUS_INTERNAL,
            error=f"internal: {_describe(exc)}",
            version=__version__,
        )


def _dispatch_line(line: str) -> PingResponse | RenderResponse | DocResponse:
    try:
        request = parse_request(line)
    except ProtocolError as exc:
        # Every response carries both versions (PROTOCOL.md §3), so the client
        # can validate even error envelopes.
        return RenderResponse(
            id=exc.request_id,
            status=STATUS_PARSE_ERROR,
            error=str(exc),
            version=__version__,
        )
    if isinstance(request, PingRequest):
        return PingResponse(id=request.id, version=__version__)
    if isinstance(request, RenderRequest):
        return _handle_render(request)
    if isinstance(request, ExportPdfRequest):
        return _handle_export_pdf(request)
    if isinstance(request, ExportJpgRequest):
        return _handle_export_jpg(request)
    return _handle_doc(request)


def model_page_line_spans(model: ScoreModel) -> tuple[tuple[int, int] | None, ...]:
    """1.8.0 (R13): the ``[first_line, last_line]`` source span each page
    renders, or None for a page with no music/lyric lines.

    Derived from the model's page/system assignment: every music and lyric
    line belongs to exactly one system on exactly one page, so the spans are
    disjoint and ordered. The client uses them to resolve which page a cursor
    line belongs to (cross-page preview navigation). Pure model query — no
    layout work, no effect on rendered bytes.
    """
    spans: list[tuple[int, int] | None] = []
    for page in model.pages:
        lines = [
            line
            for system in page.systems
            for line in (*system.music_line_numbers, *system.lyric_line_numbers)
        ]
        spans.append((min(lines), max(lines)) if lines else None)
    return tuple(spans)


def _handle_render(request: RenderRequest) -> RenderResponse:
    try:
        source = _source_document(request)
        model = normalize_document(parse_document(source), source=source)
        page_count = len(model.pages)
        # 1.3.0 (R5.5, PARTIAL_PAGE_LIFECYCLE.md §1): an explicit page_range
        # renders exactly those in-range indices (request order) — unrequested
        # pages cost no layout work. Out-of-range values are excluded with a
        # selection diagnostic, never an error.
        if request.page_range is None:
            indices: list[int] = list(range(page_count))
            out_of_range: list[int] = []
        else:
            indices = [index for index in request.page_range if index < page_count]
            out_of_range = [index for index in request.page_range if index >= page_count]
        # Shared layout pass (R5.5 tail): when the hit-map page is among the
        # requested pages, render it through render_score_model_page_with_layout so its
        # single layout pass feeds BOTH the SVG bytes and the hit-map builder
        # below — a visible request with a hit map costs ONE layout total
        # instead of three. The spliced bytes are identical to the plain path
        # (same layout_page + _render_page calls; indices carry no duplicates,
        # de-duplicated at parse time).
        shared_layout: LayoutPage | None = None
        if request.hitmap_kinds and request.page_index in indices:
            hitmap_svg, shared_layout = render_score_model_page_with_layout(
                model,
                request.page_index,
                serialization_profile=request.serialization_profile,
            )
            others = [index for index in indices if index != request.page_index]
            # One page per requested index — strict keeps the pairing honest.
            other_pages = dict(
                zip(
                    others,
                    render_score_model_pages(
                        model, others, serialization_profile=request.serialization_profile
                    ),
                    strict=True,
                )
            )
            pages = tuple(
                hitmap_svg if index == request.page_index else other_pages[index]
                for index in indices
            )
        else:
            pages = tuple(
                render_score_model_pages(
                    model, indices, serialization_profile=request.serialization_profile
                )
            )
    except Exception as exc:  # noqa: BLE001 - the sidecar must survive bad input
        return RenderResponse(
            id=request.id,
            status=STATUS_RENDER_ERROR,
            error=_describe(exc),
            version=__version__,
        )
    warnings: list[str] = []
    if out_of_range:
        warnings.append(
            "selection: page index(es) "
            + ", ".join(str(index) for index in out_of_range)
            + f" out of range (page_count={page_count})"
        )
    try:
        hitmap = (
            build_hitmap(
                model, request.page_index, request.hitmap_kinds, layout=shared_layout
            )
            if pages and request.hitmap_kinds
            else ()
        )
    except Exception as exc:  # noqa: BLE001 - a hit-map bug must be visible, not silent
        # The SVG pages are valid and must be retained (UI Phase 2 R1): the
        # metadata failure is reported as a warning, not an error that
        # discards the render.
        warnings.append(f"hitmap: {_describe(exc)}")
        hitmap = ()
    return RenderResponse(
        id=request.id,
        status=STATUS_OK,
        pages=pages,
        # 1.7.0 (R6b): self-describing response — the hitmap belongs to
        # this request's page_index, so a client never guesses which of its
        # in-flight requests produced a delivered result.
        page_index=request.page_index,
        page_count=page_count,
        returned_pages=tuple(indices),
        # 1.8.0 (R13): the full per-page line index rides on every render
        # response, so a single-page request still lets the client resolve
        # which page any cursor line belongs to.
        page_line_spans=model_page_line_spans(model),
        diagnostics=_diagnostic_items(model),
        hitmap=hitmap,
        warnings=tuple(warnings),
        version=__version__,
        encoding_repaired=source.encoding_repaired,
    )


def _source_document(request: RenderRequest) -> JpsDocument:
    """Build the same ``JpsDocument`` ``load_jps`` would build for this record.

    Mirrors ``octopus.corpus.load_jps`` field for field (mojibake repair on
    the code, page_config already normalized by the protocol layer, key via
    core ``jps_key()``) so the engine's output is byte-identical to the CLI's
    for the same content. The path is synthesized from the record name; only
    its basename reaches the pipeline (key derivation and ``source_path``),
    and neither affects rendered SVG bytes.

    Key-decision (2026-09-09, R2a 2026-09-09): the request ``name`` is the
    **file identity** — the filename stem, exactly what ``load_jps`` keys on
    via ``path.name``. The ``.jps`` JSON wrapper's own ``name`` field is
    display metadata (56 of 65 corpus files carry a Chinese display name
    differing from the English filename), and the nine remaining silent-audio
    compatibility entries in ``render/compatibility.py`` use this source key.
    R2a makes the identities explicit:
    an optional ``source_key`` overrides derivation from ``name`` (stable
    rendering across renames/Save As), and an optional ``display_name`` is
    routed into the document record for title/export naming only — it never
    reaches SVG bytes (``record`` feeds just the HTML wrapper's title).
    """
    filename = request.name if request.name.lower().endswith(".jps") else f"{request.name}.jps"
    path = Path(filename)
    original_code = request.code
    code, repaired = repair_mojibake(original_code)
    key = request.source_key if request.source_key is not None else jps_key(path.name)
    record_name = request.display_name if request.display_name is not None else request.name
    return JpsDocument(
        path=path,
        key=key,
        code=code,
        original_code=original_code,
        custom_code=request.custom_code,
        page_config=dict(request.page_config),
        record={"name": record_name},
        json_wrapped=True,
        encoding_repaired=repaired,
    )


def _handle_doc(
    request:
    FilesListRequest
    | FileReadRequest
    | FileSaveRequest
    | FileNewRequest
    | FileImportRequest
    | FileSaveAsRequest
    | RecoveryGetRequest
    | RecoverySetRequest
    | RecoveryClearRequest,
) -> DocResponse:
    """Handle one 1.2.0 document operation (PROTOCOL.md §5).

    Every transport reaches the same ``documents`` functions, so the dev HTTP
    server and the stdio sidecar (packaged app) cannot drift: working-copy
    materialization, corpus-exact serialization, atomic writes, conflict via
    ``expected_sha256``, and whole-document recovery snapshots all live in
    one place. Documented failures (unknown file, conflict, invalid name)
    map to a readable ``error`` envelope; anything else falls through to
    dispatch's ``internal`` safety net.
    """
    try:
        if isinstance(request, FilesListRequest):
            # Corpus ∪ working copies (documents.list_documents): user-created
            # documents must be reopenable after a restart.
            return DocResponse(
                id=request.id, status=STATUS_OK, files=docs.list_documents(), version=__version__
            )
        if isinstance(request, FileReadRequest):
            target, digest = docs.ensure_working_copy(
                docs.corpus_dir() / request.name, request.name
            )
            record = json.loads(target.read_text(encoding="utf-8-sig"))
            repaired_code: str | None = None
            fired = False
            code = record.get("code")
            if isinstance(code, str):
                repaired_code, fired = repair_mojibake(code)
            return DocResponse(
                id=request.id,
                status=STATUS_OK,
                sha256=digest,
                record=record,
                encoding_repaired=fired,
                repaired_code=repaired_code if fired else None,
                version=__version__,
            )
        if isinstance(request, FileSaveRequest):
            sha = docs.save_working_copy(
                request.name,
                request.record,
                expected_sha256=request.expected_sha256,
                path=request.path,  # 1.9.0: optional user-chosen destination
                path_expected_sha256=request.path_expected_sha256,
            )
            return DocResponse(id=request.id, status=STATUS_OK, sha256=sha, version=__version__)
        if isinstance(request, FileNewRequest):
            sha = docs.new_working_copy(
                request.name,
                corpus_dir=docs.corpus_dir(),
                code=request.code,  # 1.10.0: optional website-style header
            )
            return DocResponse(id=request.id, status=STATUS_OK, sha256=sha, version=__version__)
        if isinstance(request, FileImportRequest):
            # 1.10.0: external .jps → working copy (same envelope as file.read).
            record, digest = docs.import_external_file(request.path)
            import_repaired_code: str | None = None
            import_fired = False
            code = record.get("code")
            if isinstance(code, str):
                import_repaired_code, import_fired = repair_mojibake(code)
            return DocResponse(
                id=request.id,
                status=STATUS_OK,
                sha256=digest,
                record=record,
                encoding_repaired=import_fired,
                repaired_code=import_repaired_code if import_fired else None,
                version=__version__,
            )
        if isinstance(request, FileSaveAsRequest):
            sha = docs.save_as(
                request.old_name,
                request.new_name,
                corpus_dir=docs.corpus_dir(),
                expected_sha256=request.expected_sha256,
                path=request.path,  # 1.9.0: optional user-chosen destination
            )
            return DocResponse(id=request.id, status=STATUS_OK, sha256=sha, version=__version__)
        if isinstance(request, RecoveryGetRequest):
            payload = docs.load_recovery(request.name)
            if payload is None:
                raise docs.UnknownFileError(f"no recovery snapshot for {request.name!r}")
            return DocResponse(
                id=request.id, status=STATUS_OK, payload=payload, version=__version__
            )
        if isinstance(request, RecoverySetRequest):
            docs.save_recovery(request.name, request.document)
            return DocResponse(id=request.id, status=STATUS_OK, version=__version__)
        # recovery.clear
        removed = docs.clear_recovery(request.name)
        return DocResponse(id=request.id, status=STATUS_OK, removed=removed, version=__version__)
    except (docs.UnknownFileError, docs.ConflictError, ValueError) as exc:
        return DocResponse(id=request.id, status=STATUS_ERROR, error=str(exc), version=__version__)


def _safe_export_stem(name: str) -> str:
    """Basename-sanitize a document name for the engine-picked temp filename
    (a name with path separators must not escape the exports dir). Runs of
    non-word characters collapse to a single hyphen."""
    stem = Path(name).name if name else "untitled"
    cleaned = re.sub(r'[^\w]+', "-", stem, flags=re.UNICODE).strip(".-")
    return cleaned or "untitled"


def _handle_export_pdf(request: ExportPdfRequest) -> DocResponse:
    """1.13.0 ``export.pdf`` (PROTOCOL.md §5): render the revision to a PDF.

    Destination: an explicit ``path`` follows file.save's mirror contract
    (non-empty + absolute via ``validate_save_path``, parents created, atomic
    temp + rename write); no ``path`` means the engine picks one under its UI
    home (``<ui_home>/exports/<name>-<ts>.pdf``) — the dev-browser flow, which
    has no OS save dialog. The ok payload always echoes the final location.
    Every failure is a readable ``error`` envelope — parse/render problems
    included — so an export can never crash the sidecar; only engine bugs
    escape to dispatch's ``internal`` net.
    """
    if request.path is None:
        exports_dir = docs.ui_home() / "exports"
        target = exports_dir / f"{_safe_export_stem(request.name)}-{time.time_ns()}.pdf"
    else:
        try:
            target = docs.validate_save_path(request.path)
        except ValueError as exc:
            return DocResponse(
                id=request.id, status=STATUS_ERROR, error=str(exc), version=__version__
            )
    try:
        data, page_count = pdf_export.build_pdf(
            code=request.code,
            custom_code=request.custom_code,
            page_config=request.page_config,
            name=request.name,
            source_key=request.source_key,
            display_name=request.display_name,
        )
    except Exception as exc:  # noqa: BLE001 - descriptive export failure
        return DocResponse(
            id=request.id,
            status=STATUS_ERROR,
            error=f"PDF export failed: {_describe(exc)}",
            version=__version__,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    docs._write_atomic(target, data)
    return DocResponse(
        id=request.id,
        status=STATUS_OK,
        payload={"pages": page_count, "bytes": len(data), "path": str(target)},
        version=__version__,
    )


def _jpg_page_names(base: str, page_count: int) -> list[str]:
    """Mirror the frontend's ``pageFileName`` convention for JPEG exports:
    single page → ``<base>.jpg``; multiple → ``<base>_page_<N>.jpg`` (1-based).
    The base is sanitized like the TS side (``[\\/:*?"<>|]`` → ``_``)."""
    safe = re.sub(r'[\\/:*?"<>|]', "_", base)
    if page_count <= 1:
        return [f"{safe}.jpg"]
    return [f"{safe}_page_{index + 1}.jpg" for index in range(page_count)]


def _handle_export_jpg(request: ExportJpgRequest) -> DocResponse:
    """1.14.0 ``export.jpg`` (PROTOCOL.md §5): render the revision to JPEGs.

    Destination semantics mirror both file.save's path contract and the
    frontend's SVG-export sibling naming: an explicit ``path`` is the PAGE-1
    destination (absolute; siblings land beside it named from the chosen
    page-1 base — a standard ``_page_1`` suffix is stripped first, so the
    default case keeps canonical ``<stem>_page_<N>.jpg`` names); no path →
    the engine writes a directory under its UI home (the dev-browser flow).
    Every file is written atomically; every failure is a readable ``error``
    envelope — an export can never crash the sidecar.
    """
    try:
        jpegs = jpg_export.build_jpgs(
            code=request.code,
            custom_code=request.custom_code,
            page_config=request.page_config,
            name=request.name,
            source_key=request.source_key,
            display_name=request.display_name,
        )
    except Exception as exc:  # noqa: BLE001 - descriptive export failure
        return DocResponse(
            id=request.id,
            status=STATUS_ERROR,
            error=f"JPG export failed: {_describe(exc)}",
            version=__version__,
        )
    page_count = len(jpegs)
    if request.path is None:
        stem_dir = f"{_safe_export_stem(request.name)}-{time.time_ns()}"
        base_dir = docs.ui_home() / "exports" / stem_dir
        names = _jpg_page_names(_safe_export_stem(request.name), page_count)
        targets = [base_dir / n for n in names]
    else:
        try:
            first = docs.validate_save_path(request.path)
        except ValueError as exc:
            return DocResponse(
                id=request.id, status=STATUS_ERROR, error=str(exc), version=__version__
            )
        # Sibling base: the chosen page-1 name minus .jpg and a standard
        # _page_1 suffix (mirrors svgExport.chosenBaseName in TS).
        stem = first.name[:-4] if first.name.lower().endswith(".jpg") else first.name
        stem = re.sub(r"_page_1$", "", stem, flags=re.IGNORECASE)
        names = _jpg_page_names(stem, page_count)
        targets = [first] + [first.parent / n for n in names[1:]]
    try:
        for target, data in zip(targets, jpegs, strict=True):
            target.parent.mkdir(parents=True, exist_ok=True)
            docs._write_atomic(target, data)
    except OSError as exc:
        return DocResponse(
            id=request.id,
            status=STATUS_ERROR,
            error=f"JPG export failed to write: {_describe(exc)}",
            version=__version__,
        )
    files = [str(t) for t in targets]
    return DocResponse(
        id=request.id,
        status=STATUS_OK,
        payload={"pages": page_count, "files": files, "bytes": sum(len(j) for j in jpegs)},
        version=__version__,
    )


def build_hitmap(
    model: ScoreModel,
    page_index: int,
    kinds: tuple[str, ...] = ("event",),
    layout: LayoutPage | None = None,
) -> tuple[HitEntry, ...]:
    """Build click-to-cursor hit entries for one rendered page.

    ``kinds`` selects which entry families are built (protocol 1.6.0):
    ``"event"`` pairs each rendered event-stream element (from
    ``render_page_elements``) with the source span of its owning
    ``MusicEvent``; ``"lyric"`` pairs each non-synthetic ``LayoutLyric``
    with its owning lyric token's span (the token-consumption replay that
    was recorded follow-up 1b — the layout now records the owner token at
    placement time, so no replay is needed).

    For events, ``source_event_index`` is an index into the owning voice's
    per-system event stream, so it restarts in every system/voice and is
    resolved by matching the element's geometry against the page's layout
    events; elements without a unique geometric match (e.g. bz placeholder
    uses drawn 40 px below their host barline) are omitted.

    ``layout`` optionally reuses the caller's pre-computed ``LayoutPage``
    (the shared-layout path, R5.5 tail): when provided, this function pays
    for NO layout passes of its own — the dispatch renders the hit-map page
    through ``render_score_model_page_with_layout`` and hands the same layout over, so a
    visible request with a hit map performs exactly ONE layout pass in total.
    Without it (standalone callers/tests) the historical behavior holds: one
    pass here plus the one inside ``render_page_elements``. The event path is
    skipped entirely when only lyric entries are requested.
    """
    if layout is None:
        layout = layout_page(model, page_index)
    entries: list[HitEntry] = []
    if "event" in kinds:
        elements = render_page_elements(model, page_index, layout=layout)
        candidates_by_index: dict[int, list[LayoutEvent]] = {}
        for item in [*layout.events, *layout.hidden_events]:
            if item.event.index >= 0:
                candidates_by_index.setdefault(item.event.index, []).append(item)
        for element in elements:
            index = element.source_event_index
            if index is None:
                continue
            host = _match_layout_event(
                candidates_by_index.get(index, []), element.x, element.y
            )
            if host is None:
                continue
            span = host.event.span
            entries.append(
                HitEntry(
                    kind="event",
                    x=element.x,
                    y=element.y,
                    line=span.start.line,
                    column=span.start.column,
                    end_line=span.end.line,
                    end_column=span.end.column,
                    text=host.event.raw or None,
                    # 1.4.0 owner identity (R5.5 metadata API): which voice
                    # of the hosting system, its source Q-number, and the
                    # event's index in that voice's per-system stream.
                    voice=host.voice,
                    source_voice=host.source_voice,
                    event_index=host.event.index,
                    # 1.5.0: the hosting visual system (1-based); zero means
                    # the stamp could not resolve a line, which is null on
                    # the wire.
                    system=host.system_index if host.system_index > 0 else None,
                )
            )
    if "lyric" in kinds:
        for lyric in layout.lyrics:
            # Synthetic entries (skips, empty placeholders) have no source
            # token and nothing to place a cursor on.
            if not lyric.source_spans or not lyric.text.strip():
                continue
            for lyric_span in lyric.source_spans:
                entries.append(
                    HitEntry(
                        kind="lyric",
                        x=lyric.x,
                        y=lyric.y,
                        line=lyric_span.start.line,
                        column=lyric_span.start.column,
                        end_line=lyric_span.end.line,
                        end_column=lyric_span.end.column,
                        text=model.code[lyric_span.start.offset : lyric_span.end.offset],
                        # Owner identity: the hosting event's voice; lyrics have
                        # no per-voice event stream index (null on the wire).
                        voice=lyric.voice,
                        source_voice=None,
                        event_index=None,
                        system=lyric.system_index if lyric.system_index > 0 else None,
                    )
                )
    return tuple(entries)


def _match_layout_event(
    candidates: list[LayoutEvent], x: float, y: float
) -> LayoutEvent | None:
    """Pick the layout event a rendered element was drawn from.

    The true host is always within ``_GEOMETRY_MATCH_TOLERANCE`` (y is
    int-truncated on serialization); distinct rows are tens of pixels apart,
    so a match is unique in practice. Ties fall back to stream order, keeping
    the result deterministic either way.
    """
    best: LayoutEvent | None = None
    best_distance = _GEOMETRY_MATCH_TOLERANCE
    for item in candidates:
        distance = max(abs(item.x - x), abs(item.y - y))
        if distance <= best_distance:
            best, best_distance = item, distance
    return best


def _diagnostic_items(model: ScoreModel) -> tuple[DiagnosticItem, ...]:
    return tuple(
        DiagnosticItem(
            code=item.code,
            message=item.message,
            severity=item.severity.value,
            line=item.span.start.line,
            column=item.span.start.column,
            end_line=item.span.end.line,
            end_column=item.span.end.column,
            raw=item.raw,
            recovery=item.recovery,
        )
        for item in model.diagnostics
    )


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"
