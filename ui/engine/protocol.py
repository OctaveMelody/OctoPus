"""Wire protocol for the JPS editor engine (UI Phase 2, Option A).

The engine speaks one JSON object per line on a transport (stdio in the
packaged app, HTTP in dev). Every request carries an ``id`` assigned by the
client and an ``op`` name; every response echoes the ``id``. Requests are
stateless: a render request carries the full JPS record (``name``, ``code``,
``custom_code``, ``page_config``) mirroring the ``.jps`` JSON wrapper, because
page_config drives layout metrics and custom_code emits the per-page custom
block. A caller may also select the SVG serialization profile explicitly.

This module imports only the lightweight core ``corpus`` module (for the
shared ``page_config`` decoder, so the protocol layer and ``load_jps`` cannot
drift) — never the render pipeline — so both transports and the tests share
one validated shape without paying engine import costs. The full wire spec,
versioning rules, and boundary behaviors live in ``ui/engine/PROTOCOL.md``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from octopus.jps import decode_page_config

STATUS_OK = "ok"
STATUS_PARSE_ERROR = "parse_error"
STATUS_RENDER_ERROR = "render_error"
STATUS_INTERNAL = "internal"
#: Document-operation failures (1.2.0): the request was well-formed but the
#: operation could not be performed (unknown file, conflict, bad name).
#: ping/render never return this status.
STATUS_ERROR = "error"

#: Protocol version on the wire (semver; see PROTOCOL.md for the rules).
PROTOCOL_VERSION = "1.14.0"

OPS: frozenset[str] = frozenset(
    {
        "ping",
        "render",
        # 1.2.0 document operations (shared by every transport — the stdio
        # sidecar gains file access so the packaged app owns documents.py).
        "files.list",
        "file.read",
        "file.save",
        "file.new",
        "file.import",  # 1.10.0: materialize a working copy from an external file
        "file.save_as",
        "recovery.get",
        "recovery.set",
        "recovery.clear",
        # 1.13.0: render the revision and write a multi-page PDF to `path`.
        "export.pdf",
        # 1.14.0: render the revision and write one JPEG per page.
        "export.jpg",
    }
)

#: Hit-map entry kinds (1.6.0): music events and lyric tokens.
HITMAP_KINDS: frozenset[str] = frozenset({"event", "lyric"})

#: Wire options still rejected by the parser. ``visible_page_first`` was
#: reserved in 1.0.0 for R5.5 and retired in 1.3.0 (contract v1, PARTIAL_
#: PAGE_LIFECYCLE.md): one-request-one-response framing makes intra-request
#: ordering invisible, so visible-page-first is a client-side scheduling rule.
#: Rejection (rather than silent ignore) stays deliberate: a client sending
#: it expects server-side scheduling that will never happen.
RESERVED_FIELDS: tuple[str, ...] = ("visible_page_first",)


class ProtocolError(ValueError):
    """A request line that is not a valid engine request.

    ``request_id`` carries the best-effort readable id of the offending
    request (when the payload was a JSON object with an integer ``id``) so
    error responses can still be correlated with their request.
    """

    def __init__(self, message: str, request_id: int | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class PingRequest:
    """Liveness/handshake probe; the response carries the engine version."""

    op: str = "ping"
    id: int = 0


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """One stateless render of a full JPS record.

    Identity fields (R2a — see PROTOCOL.md §4 and DOCUMENT_IDENTITY.md):

    - ``name``: the file identity — the filename stem (e.g. ``As-Wished -
      Choir`` for ``As-Wished - Choir.jps``). Required; when no explicit
      ``source_key`` is given it feeds core ``jps_key()`` for source-key
      derivation.
    - ``source_key``: optional explicit renderer source key. When present it
      takes precedence over derivation from ``name`` — this is how a client
      keeps rendering stable across renames/Save As (R2c policy).
    - ``display_name``: optional wrapper display name (often Chinese). It is
      metadata routed into the document record for title/export naming; it
      never affects SVG bytes.
    - ``serialization_profile``: optional SVG formatting selected by the
      caller; defaults to ``"spaced"`` and never follows source identity.

    ``page_index`` selects which page's hit map (click-to-cursor entries) the
    response carries; all pages' SVGs are always returned.
    """

    op: str = "render"
    id: int = 0
    name: str = ""
    source_key: str | None = None
    display_name: str | None = None
    code: str = ""
    custom_code: str = ""
    page_config: dict[str, Any] = field(default_factory=dict)
    page_index: int = 0
    serialization_profile: Literal["spaced", "compact"] = "spaced"
    #: 1.6.0 (R5.5 metadata API): which hit-map entry kinds to build —
    #: any of ``"event"`` / ``"lyric"``. Default ``("event",)`` keeps the
    #: legacy payload; an empty tuple requests no hit map at all.
    hitmap_kinds: tuple[str, ...] = ("event",)
    #: 1.3.0 (R5.5): explicit page indices to render and return, in request
    #: order; ``None`` means all pages (legacy behavior). Duplicates are
    #: de-duplicated keeping the first occurrence; out-of-range values are
    #: excluded with a selection warning (never an error) — see PARTIAL_
    #: PAGE_LIFECYCLE.md §1.
    page_range: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class ExportPdfRequest:
    """1.13.0: render the revision and write a multi-page PDF to ``path``.

    Carries the same R0 content snapshot as ``render`` (the export belongs to
    exactly this revision — name/source_key/display_name identity fields,
    code, custom_code, page_config) plus an optional absolute destination
    path. The engine renders ALL pages of the revision and assembles one
    vector PDF (per-page sizes preserved); the write is atomic (temp +
    rename in the target directory). Response: DocResponse — ok with payload
    ``{pages, bytes, path}`` (path echoes where the file landed), or error
    with a descriptive message (parse/render failures never crash the
    sidecar).

    ``path`` semantics: present → must be absolute (well-formed-request
    failure otherwise, mirroring file.save's contract); absent/null → the
    engine writes under its own UI home (``<ui_home>/exports/<name>-<ts>.pdf``)
    and reports the location in the payload — this is the dev-browser path,
    which has no OS save dialog.
    """

    op: str = "export.pdf"
    id: int = 0
    name: str = ""
    source_key: str | None = None
    display_name: str | None = None
    code: str = ""
    custom_code: str = ""
    page_config: dict[str, Any] = field(default_factory=dict)
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ExportJpgRequest:
    """1.14.0: render the revision and write one JPEG per page.

    Same R0 content snapshot as ``render``/``export.pdf`` plus an optional
    absolute destination path for PAGE 1; siblings land beside it named per
    the frontend convention (``<stem>_page_<N>.jpg``, 1-based; single page =
    ``<stem>.jpg``). Absent/null path → the engine writes a directory under
    its UI home (``<ui_home>/exports/<name>-<ts>/``) — the dev-browser flow.
    Response: DocResponse — ok with payload ``{pages, files, bytes}``
    (files = absolute paths in page order; bytes = total), or error with a
    descriptive message (never a crash).
    """

    op: str = "export.jpg"
    id: int = 0
    name: str = ""
    source_key: str | None = None
    display_name: str | None = None
    code: str = ""
    custom_code: str = ""
    page_config: dict[str, Any] = field(default_factory=dict)
    path: str | None = None


@dataclass(frozen=True, slots=True)
class FilesListRequest:
    """1.2.0: list the corpus ``*.jps`` filenames (sorted)."""

    op: str = "files.list"
    id: int = 0


@dataclass(frozen=True, slots=True)
class FileReadRequest:
    """1.2.0: read one document (materializes the working copy on first load).

    The response carries ``sha256`` + the wrapper ``record``, plus
    ``encoding_repaired``/``repaired_code`` when mojibake repair fires
    (DOCUMENT_IDENTITY.md §6 — same policy as the dev REST endpoint).
    """

    op: str = "file.read"
    id: int = 0
    name: str = ""


@dataclass(frozen=True, slots=True)
class FileSaveRequest:
    """1.2.0: atomically save a wrapper record to the working copy.

    ``expected_sha256`` is the hash the client last read; a mismatch is a
    conflict (response status ``error``). Returns the new sha256.

    1.9.0: optional ``path`` — an absolute destination chosen in the OS save
    dialog. When present, the identical bytes are also written there (parent
    directories are created), so the user's copy and the working copy never
    drift apart. A relative/empty path is a well-formed-request error.

    1.9.0: optional ``path_expected_sha256`` — conflict guard for the mirror
    destination, mirroring ``expected_sha256`` for the working copy. Sent on
    saves to a REMEMBERED location (the hash the last save wrote there); a
    mismatch means the user's file changed on disk since then and the save is
    refused rather than clobbering it. Absent = freshly picked in the dialog
    = explicit overwrite authorization.
    """

    op: str = "file.save"
    id: int = 0
    name: str = ""
    record: dict[str, Any] = field(default_factory=dict)
    expected_sha256: str | None = None
    path: str | None = None
    path_expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class FileNewRequest:
    """1.2.0: create a fresh corpus-shaped working copy (never overwrites).

    1.10.0: optional ``code`` — the initial score text (the website-style
    description header built by the New dialog). Absent = the engine's blank
    default, exactly as before.
    """

    op: str = "file.new"
    id: int = 0
    name: str = ""
    code: str | None = None


@dataclass(frozen=True, slots=True)
class FileImportRequest:
    """1.10.0: materialize a working copy from an EXTERNAL .jps file.

    ``path`` is the absolute path chosen in the OS open dialog (the packaged
    app's 打开 for files outside the sample library). The file's basename
    becomes the working-copy name; an existing working copy of that name is
    refused (it may hold unsaved edits) rather than clobbered. Success returns
    the same envelope as ``file.read`` (record + sha256 + mojibake repair).
    """

    op: str = "file.import"
    id: int = 0
    path: str = ""


@dataclass(frozen=True, slots=True)
class FileSaveAsRequest:
    """1.2.0: atomically rename a working copy (identity follows the new stem).

    1.9.0: optional ``path`` — like ``file.save``, mirrors the renamed bytes
    to an absolute user-chosen destination.
    """

    op: str = "file.save_as"
    id: int = 0
    old_name: str = ""
    new_name: str = ""
    expected_sha256: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryGetRequest:
    """1.2.0: fetch the whole-document recovery snapshot (schema v1)."""

    op: str = "recovery.get"
    id: int = 0
    name: str = ""


@dataclass(frozen=True, slots=True)
class RecoverySetRequest:
    """1.2.0: persist a whole-document recovery snapshot (schema v1)."""

    op: str = "recovery.set"
    id: int = 0
    name: str = ""
    document: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecoveryClearRequest:
    """1.2.0: drop the recovery snapshot (e.g. after a clean save)."""

    op: str = "recovery.clear"
    id: int = 0
    name: str = ""


#: Union of the 1.2.0 document-operation request types.
DocRequest = (
    FilesListRequest
    | FileReadRequest
    | FileSaveRequest
    | FileNewRequest
    | FileImportRequest
    | FileSaveAsRequest
    | RecoveryGetRequest
    | RecoverySetRequest
    | RecoveryClearRequest
)


def _extract_request_id(data: Any) -> int | None:
    """Best-effort extraction of a readable request id from a raw payload."""
    if isinstance(data, dict):
        candidate = data.get("id")
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def parse_request(
    line: str,
) -> PingRequest | RenderRequest | ExportPdfRequest | ExportJpgRequest | DocRequest:
    """Parse one JSON request line into a typed request.

    Raises :class:`ProtocolError` with a human-readable reason (and the
    best-effort readable id, when one was present) when the line is not a
    valid request; transports map that to a ``parse_error`` response.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"request is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("request must be a JSON object")
    readable_id = _extract_request_id(data)
    op = data.get("op")
    if not isinstance(op, str) or op not in OPS:
        # ``not isinstance(op, str)`` guards unhashable ops (lists, dicts):
        # membership testing on the frozenset would raise TypeError.
        raise ProtocolError(
            f"unknown op: {op!r} (expected one of: ping, render, export.pdf, export.jpg, "
            f"files.list, file.read, file.save, file.new, file.import, file.save_as, "
            f"recovery.get, recovery.set, recovery.clear)",
            readable_id,
        )
    request_id = data.get("id", 0)
    if isinstance(request_id, bool) or not isinstance(request_id, int):
        # ``readable_id`` is None here by construction, so the error response
        # correctly reports an unreadable id.
        raise ProtocolError("request id must be an integer")
    if op == "ping":
        return PingRequest(op=op, id=request_id)
    if op == "export.pdf":
        return _parse_export_pdf(data, request_id)
    if op == "export.jpg":
        return _parse_export_jpg(data, request_id)
    if op in _DOC_OPS:
        return _parse_doc_request(op, data, request_id)
    for reserved in RESERVED_FIELDS:
        if reserved in data:
            raise ProtocolError(
                f"'{reserved}' is reserved for a future protocol version and not yet implemented",
                readable_id,
            )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProtocolError("render request needs a non-empty string 'name'", request_id)
    source_key = data.get("source_key")
    if source_key is not None and (not isinstance(source_key, str) or not source_key.strip()):
        raise ProtocolError("'source_key' must be a non-empty string when present", request_id)
    display_name = data.get("display_name")
    if display_name is not None and not isinstance(display_name, str):
        raise ProtocolError("'display_name' must be a string when present", request_id)
    serialization_profile = data.get("serialization_profile", "spaced")
    if serialization_profile not in {"spaced", "compact"}:
        raise ProtocolError(
            "'serialization_profile' must be 'spaced' or 'compact'", request_id
        )
    code = data.get("code")
    if not isinstance(code, str):
        raise ProtocolError("render request needs a string 'code'", request_id)
    custom_code = data.get("custom_code", "")
    if not isinstance(custom_code, str):
        raise ProtocolError("'custom_code' must be a string when present", request_id)
    page_index = data.get("page_index", 0)
    if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
        raise ProtocolError("'page_index' must be a non-negative integer", request_id)
    hitmap_kinds: tuple[str, ...] = ("event",)
    raw_hitmap_kinds = data.get("hitmap_kinds")
    if raw_hitmap_kinds is not None:
        # Well-typed wire (PROTOCOL.md §4): an array of known kind strings.
        # Duplicates are de-duplicated preserving order; an empty array
        # requests no hit map at all.
        if not isinstance(raw_hitmap_kinds, list) or any(
            not isinstance(kind, str) or kind not in HITMAP_KINDS for kind in raw_hitmap_kinds
        ):
            raise ProtocolError(
                "'hitmap_kinds' must be an array of 'event' and/or 'lyric'",
                request_id,
            )
        seen_kinds: set[str] = set()
        deduped_kinds: list[str] = []
        for kind in raw_hitmap_kinds:
            if kind not in seen_kinds:
                seen_kinds.add(kind)
                deduped_kinds.append(kind)
        hitmap_kinds = tuple(deduped_kinds)
    page_range: tuple[int, ...] | None = None
    raw_page_range = data.get("page_range")
    if raw_page_range is not None:
        # Well-typed wire (PARTIAL_PAGE_LIFECYCLE.md §1): an array of
        # non-negative integers. Out-of-range *values* are a selection matter
        # handled at render time, not a parse error.
        if not isinstance(raw_page_range, list) or any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in raw_page_range
        ):
            raise ProtocolError(
                "'page_range' must be an array of non-negative integers",
                request_id,
            )
        seen: set[int] = set()
        deduped: list[int] = []
        for index in raw_page_range:
            if index not in seen:
                seen.add(index)
                deduped.append(index)
        page_range = tuple(deduped)
    return RenderRequest(
        op=op,
        id=request_id,
        name=name,
        source_key=source_key,
        display_name=display_name,
        code=code,
        custom_code=custom_code,
        page_config=decode_page_config(data.get("page_config", {})),
        page_index=page_index,
        serialization_profile=serialization_profile,
        page_range=page_range,
        hitmap_kinds=hitmap_kinds,
    )


def _parse_export_fields(
    op: str, data: dict[str, Any], request_id: int
) -> tuple[str, str | None, str | None, str, str, dict[str, Any], str | None]:
    """Shared R0 snapshot validation for the export ops (1.13.0/1.14.0).

    Field validation mirrors the render branch (same R0 snapshot contract);
    ``path`` is optional — present it must be a non-empty string (absoluteness
    is the op handler's job, STATUS_ERROR, like file.save via
    documents.validate_save_path); absent/null means "engine picks a temp
    location under its UI home". Returns the validated fields in request-dataclass order.
    """
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProtocolError(f"{op} needs a non-empty string 'name'", request_id)
    source_key = data.get("source_key")
    if source_key is not None and (not isinstance(source_key, str) or not source_key.strip()):
        raise ProtocolError("'source_key' must be a non-empty string when present", request_id)
    display_name = data.get("display_name")
    if display_name is not None and not isinstance(display_name, str):
        raise ProtocolError("'display_name' must be a string when present", request_id)
    code = data.get("code")
    if not isinstance(code, str):
        raise ProtocolError(f"{op} needs a string 'code'", request_id)
    custom_code = data.get("custom_code", "")
    if not isinstance(custom_code, str):
        raise ProtocolError("'custom_code' must be a string when present", request_id)
    path = data.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise ProtocolError("'path' must be a non-empty string when present", request_id)
    return (
        name,
        source_key,
        display_name,
        code,
        custom_code,
        decode_page_config(data.get("page_config", {})),
        path,
    )


def _parse_export_pdf(data: dict[str, Any], request_id: int) -> ExportPdfRequest:
    """1.13.0 ``export.pdf`` — see :func:`_parse_export_fields`."""
    name, source_key, display_name, code, custom_code, page_config, path = _parse_export_fields(
        "export.pdf", data, request_id
    )
    return ExportPdfRequest(
        op="export.pdf",
        id=request_id,
        name=name,
        source_key=source_key,
        display_name=display_name,
        code=code,
        custom_code=custom_code,
        page_config=page_config,
        path=path,
    )


def _parse_export_jpg(data: dict[str, Any], request_id: int) -> ExportJpgRequest:
    """1.14.0 ``export.jpg`` — see :func:`_parse_export_fields`."""
    name, source_key, display_name, code, custom_code, page_config, path = _parse_export_fields(
        "export.jpg", data, request_id
    )
    return ExportJpgRequest(
        op="export.jpg",
        id=request_id,
        name=name,
        source_key=source_key,
        display_name=display_name,
        code=code,
        custom_code=custom_code,
        page_config=page_config,
        path=path,
    )


#: 1.2.0 document operations (PROTOCOL.md §5).
_DOC_OPS: frozenset[str] = frozenset(
    {
        "files.list",
        "file.read",
        "file.save",
        "file.new",
        "file.import",
        "file.save_as",
        "recovery.get",
        "recovery.set",
        "recovery.clear",
    }
)


def _require_name(data: dict[str, Any], request_id: int) -> str:
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProtocolError("request needs a non-empty string 'name'", request_id)
    return name


def _optional_sha(data: dict[str, Any], request_id: int) -> str | None:
    sha = data.get("expected_sha256")
    if sha is not None and (not isinstance(sha, str) or not sha.strip()):
        raise ProtocolError("'expected_sha256' must be a non-empty string when present", request_id)
    return sha


def _optional_sha_field(
    data: dict[str, Any], key: str, request_id: int
) -> str | None:
    """Same contract as ``_optional_sha`` for any optional hash field."""
    value = data.get(key)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ProtocolError(f"'{key}' must be a non-empty string when present", request_id)
    return value


def _optional_path(data: dict[str, Any], request_id: int) -> str | None:
    # 1.9.0: user-chosen save destination from the OS dialog. The type is
    # checked here; absoluteness is enforced by documents.validate_save_path
    # (a well-formed-request failure, not a parse error).
    path = data.get("path")
    if path is not None and not isinstance(path, str):
        raise ProtocolError("'path' must be a string when present", request_id)
    return path


def _parse_doc_request(op: str, data: dict[str, Any], request_id: int) -> DocRequest:
    if op == "files.list":
        return FilesListRequest(op=op, id=request_id)
    if op in ("file.read", "recovery.get", "recovery.clear"):
        name = _require_name(data, request_id)
        if op == "file.read":
            return FileReadRequest(op=op, id=request_id, name=name)
        if op == "recovery.get":
            return RecoveryGetRequest(op=op, id=request_id, name=name)
        return RecoveryClearRequest(op=op, id=request_id, name=name)
    if op in ("file.save", "file.new"):
        name = _require_name(data, request_id)
        if op == "file.new":
            # 1.10.0: optional initial code from the New dialog's website-
            # style description header.
            code = data.get("code")
            if code is not None and (not isinstance(code, str) or not code.strip()):
                raise ProtocolError(
                    "'code' must be a non-empty string when present", request_id
                )
            return FileNewRequest(op=op, id=request_id, name=name, code=code)
        record = data.get("record")
        if not isinstance(record, dict):
            raise ProtocolError("file.save needs an object 'record'", request_id)
        return FileSaveRequest(
            op=op,
            id=request_id,
            name=name,
            record=record,
            expected_sha256=_optional_sha(data, request_id),
            path=_optional_path(data, request_id),
            path_expected_sha256=_optional_sha_field(
                data, "path_expected_sha256", request_id
            ),
        )
    if op == "file.import":
        # 1.10.0: the type is checked here; absoluteness is enforced by
        # documents.validate_save_path (well-formed-request failure, not a
        # parse error) — same contract as file.save's path.
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ProtocolError("file.import needs a non-empty string 'path'", request_id)
        return FileImportRequest(op=op, id=request_id, path=path)
    if op == "file.save_as":
        old_name = _require_name(data, request_id)
        new_name = data.get("new_name")
        if not isinstance(new_name, str) or not new_name.strip():
            raise ProtocolError("file.save_as needs a non-empty string 'new_name'", request_id)
        return FileSaveAsRequest(
            op=op,
            id=request_id,
            old_name=old_name,
            new_name=new_name,
            expected_sha256=_optional_sha(data, request_id),
            path=_optional_path(data, request_id),
        )
    # recovery.set
    name = _require_name(data, request_id)
    document = data.get("document")
    if not isinstance(document, dict):
        raise ProtocolError("recovery.set needs an object 'document'", request_id)
    return RecoverySetRequest(op=op, id=request_id, name=name, document=document)


@dataclass(frozen=True, slots=True)
class DiagnosticItem:
    """One parser/normalizer diagnostic, positioned in the JPS source."""

    code: str
    message: str
    severity: str  # "info" | "warning" | "error"
    line: int  # 1-based
    column: int  # 1-based
    end_line: int
    end_column: int
    raw: str
    recovery: str


@dataclass(frozen=True, slots=True)
class HitEntry:
    """Click-to-cursor mapping for one rendered element.

    ``kind`` is ``"event"`` in step 1 (lyric entries are recorded follow-up
    step 1b). Line/column are 1-based positions into the request's ``code``,
    directly usable as a CodeMirror selection.
    """

    kind: str
    x: float
    y: float
    line: int
    column: int
    end_line: int
    end_column: int
    text: str | None = None
    # 1.4.0 (R5.5 metadata API): owner identity for disambiguation — which
    # voice of the hosting system, its source Q-number, and the event's index
    # in that voice's per-system stream. Page is implicit (the hitmap belongs
    # to one page_index request). Lyric entries need token-consumption replay
    # and land later (see PROTOCOL.md §4).
    voice: int | None = None
    source_voice: int | None = None
    event_index: int | None = None
    # 1.5.0 (R5.5 metadata API): the 1-based index of the hosting visual
    # system on the page — repeated material in different systems stays
    # distinguishable. Null when the host could not be resolved to a line.
    system: int | None = None


@dataclass(frozen=True, slots=True)
class PingResponse:
    id: int
    version: str
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class RenderResponse:
    """Result of one render request.

    ``status`` is ``ok`` when pages were produced (diagnostics may still be
    present — the parser is recovery-oriented), ``parse_error`` for invalid
    requests, ``render_error`` when the pipeline raised, and ``internal`` for
    unexpected engine bugs. ``warnings`` carries non-fatal metadata failures
    (e.g. a hit-map bug): the pages stay valid and must be shown.
    ``encoding_repaired`` tells the frontend that mojibake repair rewrote the
    code before rendering, so source positions point into the repaired text.
    """

    id: int | None
    status: str
    pages: tuple[str, ...] = ()
    #: 1.7.0 (R6b hit overlay): echo of the request's ``page_index`` — the
    #: page ``hitmap`` belongs to. Makes the response self-describing so a
    #: client never has to guess which in-flight request produced it.
    page_index: int = 0
    #: 1.3.0 (R5.5): total pages in this document's render (this revision).
    page_count: int = 0
    #: 1.3.0 (R5.5): the ``page_range`` indices actually included in
    #: ``pages``, in the same order; legacy all-pages renders carry
    #: ``[0 .. page_count-1]``.
    returned_pages: tuple[int, ...] = ()
    #: 1.8.0 (R13): per-page source-line coverage — for each of the
    #: ``page_count`` pages, the ``[first_line, last_line]`` span of the
    #: music/lyric lines that page renders, or None when the page renders
    #: none. Derived from the model's page/system assignment (every such
    #: line belongs to exactly one page), so spans are disjoint and ordered.
    #: Present on every render response — even partial ``page_range``
    #: requests carry the FULL index, which is how a client resolves which
    #: page a cursor line belongs to (cross-page preview navigation).
    page_line_spans: tuple[tuple[int, int] | None, ...] = ()
    diagnostics: tuple[DiagnosticItem, ...] = ()
    hitmap: tuple[HitEntry, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
    version: str | None = None
    protocol_version: str | None = PROTOCOL_VERSION
    encoding_repaired: bool = False


@dataclass(frozen=True, slots=True)
class DocResponse:
    """Result of one 1.2.0 document operation.

    ``status`` is ``ok`` on success and ``error`` when the operation could
    not be performed (unknown file, conflict, invalid name — see PROTOCOL.md
    §5); the reason rides in ``error``. Unexpected engine bugs still map to
    ``internal`` via dispatch's safety net. Only the fields relevant to the
    op are serialized (see :func:`doc_response_to_dict`), keeping lines small.
    """

    id: int | None
    status: str
    files: tuple[str, ...] | None = None
    sha256: str | None = None
    record: dict[str, Any] | None = None
    encoding_repaired: bool = False
    repaired_code: str | None = None
    payload: dict[str, Any] | None = None
    removed: bool | None = None
    error: str | None = None
    version: str | None = None
    protocol_version: str | None = PROTOCOL_VERSION


def render_response_to_dict(response: RenderResponse) -> dict[str, Any]:
    return {
        "id": response.id,
        "status": response.status,
        "pages": list(response.pages),
        "page_index": response.page_index,
        "page_count": response.page_count,
        "returned_pages": list(response.returned_pages),
        # 1.8.0: full per-page line index (see RenderResponse.page_line_spans).
        "page_line_spans": [
            list(span) if span is not None else None for span in response.page_line_spans
        ],
        "diagnostics": [asdict(item) for item in response.diagnostics],
        "hitmap": [asdict(entry) for entry in response.hitmap],
        "warnings": list(response.warnings),
        "error": response.error,
        "version": response.version,
        "protocol_version": response.protocol_version,
        "encoding_repaired": response.encoding_repaired,
    }


def ping_response_to_dict(response: PingResponse) -> dict[str, Any]:
    return {
        "id": response.id,
        "status": STATUS_OK,
        "version": response.version,
        "protocol_version": response.protocol_version,
    }


def doc_response_to_dict(response: DocResponse) -> dict[str, Any]:
    """Compact serialization: envelope fields always, op fields when present."""
    payload: dict[str, Any] = {
        "id": response.id,
        "status": response.status,
    }
    if response.files is not None:
        payload["files"] = list(response.files)
    if response.sha256 is not None:
        payload["sha256"] = response.sha256
    if response.record is not None:
        payload["record"] = response.record
    if response.encoding_repaired:
        payload["encoding_repaired"] = True
    if response.repaired_code is not None:
        payload["repaired_code"] = response.repaired_code
    if response.payload is not None:
        payload["payload"] = response.payload
    if response.removed is not None:
        payload["removed"] = response.removed
    if response.error is not None:
        payload["error"] = response.error
    payload["version"] = response.version
    payload["protocol_version"] = response.protocol_version
    return payload


def serialize_response(
    response: PingResponse | RenderResponse | DocResponse,
) -> str:
    """Serialize one response to a single JSON line (the wire format)."""
    if isinstance(response, PingResponse):
        payload = ping_response_to_dict(response)
    elif isinstance(response, DocResponse):
        payload = doc_response_to_dict(response)
    else:
        payload = render_response_to_dict(response)
    return json.dumps(payload, ensure_ascii=False) + "\n"
