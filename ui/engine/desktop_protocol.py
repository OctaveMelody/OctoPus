"""Validate a small desktop protocol and adapt snapshots to the existing core."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from octopus.export.svg import (
    normalize_source,
    render_score_pages,
    sanitize_export_pages,
    sanitize_export_svg_xml,
)
from octopus.font_profile import apply_svg_fonts, system_font_availability
from octopus.jps import JpsDocument, jps_key, load_jps_text, serialize_jps
from octopus.normalization.types import ScoreModel
from octopus.parser.grammar import parse_document
from octopus.render.svg import (
    render_score_model_page_with_layout,
)
from octopus.render.svg_preview import add_safe_custom_page_markup
from octopus.transcription import transcribe
from octopus.transcription.text import OcrBackend

from .validation import (
    MAX_SAFE_INTEGER,
    WireValidationError,
    decode_json,
    envelope,
    is_identifier,
    is_integer,
)

PROTOCOL_VERSION = "1.6.0"
MAX_REQUEST_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_REVISION = MAX_SAFE_INTEGER
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_INTERNAL = "internal"
STATUS_PARSE_ERROR = "parse_error"
STATUS_RENDER_ERROR = "render_error"


class ProtocolError(ValueError):
    """A rejected wire request, rather than a renderer failure."""


class PageOutOfRangeError(ProtocolError):
    def __init__(self, page_count: int) -> None:
        super().__init__("page_index is outside the document")
        self.page_count = page_count


def _validate_request(request: object) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ProtocolError("request must be a JSON object")
    required = {
        "protocol_version",
        "request_id",
        "document_id",
        "document_revision",
        "operation",
        "payload",
    }
    if request.keys() != required:
        raise ProtocolError(f"request fields do not match protocol {PROTOCOL_VERSION}")
    if request["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    if not is_identifier(request["request_id"]) or not is_identifier(request["document_id"]):
        raise ProtocolError(
            "request_id and document_id must be nonempty strings of <=128 characters"
        )
    revision = request["document_revision"]
    if not is_integer(revision, minimum=0, maximum=MAX_REVISION):
        raise ProtocolError("document_revision must be a nonnegative safe integer")
    if request["operation"] not in (
        "handshake",
        "render",
        "parse",
        "export_svg",
        "render_page",
        "load_document",
        "serialize_document",
        "transcribe",
    ):
        raise ProtocolError("unsupported operation")
    if not isinstance(request["payload"], dict):
        raise ProtocolError("payload must be a JSON object")
    return request


def _render(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"name", "code", "custom_code", "page_config"} or "code" not in payload:
        raise ProtocolError("render requires code; allowed options: name, custom_code, page_config")
    model = _score_model(payload)
    pages, custom_markup_omitted = render_score_pages(model, payload.get("page_config", {}))
    return {
        "pages": pages,
        "page_count": len(pages),
        "diagnostics": [asdict(item) for item in model.diagnostics],
        "custom_markup_omitted": custom_markup_omitted,
    }


def _export_svg(payload: dict[str, Any]) -> dict[str, Any]:
    result = _render(payload)
    try:
        result["pages"] = list(sanitize_export_pages(tuple(result["pages"])))
    except ValueError as exc:
        raise ProtocolError(str(exc)) from exc
    return result


def _sanitize_export_svg_xml(svg: str) -> str:
    """Compatibility entry point for the core XML sanitizer."""
    return sanitize_export_svg_xml(svg)


def _transcribe(
    payload: dict[str, Any],
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    if (set(payload) not in ({"path"}, {"path", "ocr_backend"})
            or not isinstance(payload.get("path"), str)):
        raise ProtocolError("transcribe requires a managed reference path and optional OCR backend")
    ocr_backend = payload.get("ocr_backend", "rapidocr-onnxruntime")
    if (not isinstance(ocr_backend, str)
            or ocr_backend not in {"rapidocr-onnxruntime", "rapidocr-onnx"}):
        raise ProtocolError("unsupported OCR backend")
    selected_backend = cast(OcrBackend, ocr_backend)
    path = Path(payload["path"])
    if not path.is_absolute() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"}:
        raise ProtocolError("transcribe requires an absolute PNG, JPEG, or PDF path")
    if ocr_backend == "rapidocr-onnxruntime":
        draft = transcribe(path, progress=progress) if progress else transcribe(path)
    elif progress:
        draft = transcribe(path, progress=progress, ocr_backend=selected_backend)
    else:
        draft = transcribe(path, ocr_backend=selected_backend)
    return {
        "jps": draft.jps,
        "issues": [asdict(issue) for issue in draft.issues],
        "page_count": len(draft.pages),
        "page_dimensions": [{"width": page.width, "height": page.height} for page in draft.pages],
    }


def _render_page(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "code", "custom_code", "page_config", "page_index"}
    if set(payload) - allowed or "code" not in payload or "page_index" not in payload:
        raise ProtocolError(
            "render_page requires code and page_index; allowed options: "
            "name, custom_code, page_config, page_index"
        )
    page_index = payload["page_index"]
    if type(page_index) is not int or page_index < 0:
        raise ProtocolError("page_index must be a nonnegative integer")
    model = _score_model(payload)
    if page_index >= len(model.pages):
        raise PageOutOfRangeError(len(model.pages))
    svg, layout = render_score_model_page_with_layout(model, page_index)
    svg, custom_markup_omitted = add_safe_custom_page_markup(model, page_index, svg)
    svg = apply_svg_fonts(svg, payload.get("page_config", {}).get("_font_sources"))
    events = [
        {
            "event_index": item.event.index,
            "event_kind": item.event.kind.value,
            "source_span": asdict(item.event.span),
            "voice": item.voice,
            "row": item.line,
            "slot": item.slot,
            "x": item.x,
            "y": item.y,
        }
        for item in layout.events
    ]
    lyrics = [
        {
            "source_spans": [asdict(span) for span in item.source_spans],
            "x": item.x,
            "y": item.y,
            "voice": item.voice,
            "row": item.line,
            "slot": item.slot,
            "verse": item.verse,
            "annotation": item.annotation,
        }
        for item in layout.lyrics
        if item.source_spans
    ]
    return {
        "page_index": page_index,
        "page_count": len(model.pages),
        "page_width": layout.metrics.width,
        "page_height": layout.metrics.height,
        "svg": svg,
        "source_offset_unit": "codepoint",
        "events": events,
        "lyrics": lyrics,
        "diagnostics": [asdict(item) for item in model.diagnostics],
        "custom_markup_omitted": custom_markup_omitted,
    }


def _snapshot(payload: dict[str, Any]) -> JpsDocument:
    code = payload["code"]
    custom_code = payload.get("custom_code", "")
    name = _filename(payload.get("name", "Untitled.jps"))
    config = payload.get("page_config", {})
    if not isinstance(code, str) or not isinstance(custom_code, str):
        raise ProtocolError("code and custom_code must be strings")
    if not isinstance(config, dict):
        raise ProtocolError("page_config must be an object")
    # The path is identity metadata only: the adapter never reads or writes score files.
    source = JpsDocument(
        path=Path(name),
        key=jps_key(name),
        code=code,
        original_code=code,
        custom_code=custom_code,
        page_config=config,
        record={},
        json_wrapped=False,
        encoding_repaired=False,
    )
    return source


def _score_model(payload: dict[str, Any]) -> ScoreModel:
    source = _snapshot(payload)
    return normalize_source(source)


def _parse(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"name", "code", "custom_code", "page_config"} or "code" not in payload:
        raise ProtocolError("parse requires code; allowed options: name, custom_code, page_config")
    source = _snapshot(payload)
    document = parse_document(source)
    return {
        "diagnostics": [asdict(item) for item in document.diagnostics],
        "source_offset_unit": "codepoint",
        "encoding_repaired": source.encoding_repaired,
    }


def _filename(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
        or any(char in value for char in ("/", "\\", "\x00"))
        or value in (".", "..")
    ):
        raise ProtocolError("name must be a nonempty filename, not a path")
    return value


def _load_document(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"name", "text"}:
        raise ProtocolError("load_document requires only name and text")
    name = _filename(payload["name"])
    text = payload["text"]
    if not isinstance(text, str):
        raise ProtocolError("text must be a string")
    document = load_jps_text(text, Path(name))
    wrapper_fields = dict(document.record)
    wrapper_fields.pop("code", None)
    return {
        "document": {
            "name": name,
            "code": document.code,
            "custom_code": document.custom_code,
            "page_config": document.page_config,
            "wrapper_fields": wrapper_fields,
            "json_wrapped": document.json_wrapped,
            "encoding_repaired": document.encoding_repaired,
        }
    }


def _serialize_document(payload: dict[str, Any]) -> dict[str, str]:
    required = {
        "name",
        "code",
        "wrapper_fields",
        "json_wrapped",
        "page_config",
        "page_config_changed",
    }
    if set(payload) != required:
        raise ProtocolError(
            "serialize_document requires name, code, wrapper_fields, json_wrapped, "
            "page_config and page_config_changed"
        )
    name = _filename(payload["name"])
    code = payload["code"]
    wrapper_fields = payload["wrapper_fields"]
    json_wrapped = payload["json_wrapped"]
    page_config = payload["page_config"]
    page_config_changed = payload["page_config_changed"]
    if (
        not isinstance(code, str)
        or not isinstance(wrapper_fields, dict)
        or not isinstance(page_config, dict)
    ):
        raise ProtocolError("code must be a string and wrapper_fields/page_config objects")
    if (
        type(json_wrapped) is not bool
        or type(page_config_changed) is not bool
        or "code" in wrapper_fields
    ):
        raise ProtocolError(
            "json_wrapped and page_config_changed must be booleans; "
            "wrapper_fields cannot contain code"
        )
    path = Path(name)
    if json_wrapped or page_config_changed:
        record = {**wrapper_fields, "code": code}
        if page_config_changed:
            record["page_config"] = page_config
        source = json.dumps(record, ensure_ascii=False, allow_nan=False)
        document = load_jps_text(source, path)
    else:
        document = JpsDocument(
            path=path,
            key=jps_key(name),
            code=code,
            original_code=code,
            custom_code="",
            page_config={},
            record={},
            json_wrapped=False,
            encoding_repaired=False,
        )
    return {"text": serialize_jps(document, code=code)}


def error_response(generation: str, code: str, message: str) -> dict[str, Any]:
    return envelope(
        status="error",
        protocol_version=PROTOCOL_VERSION,
        engine_generation=generation,
        request_id=None,
        document_id=None,
        document_revision=None,
        error={"code": code, "message": message},
    )


def dispatch(
    line: bytes,
    generation: str,
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """One full snapshot per request; no retained document state or filesystem operations."""
    response = error_response(generation, "invalid_request", "invalid request")
    try:
        if len(line) > MAX_REQUEST_BYTES:
            raise ProtocolError("request exceeds byte limit")
        request = decode_json(line)
        # Echo only bounded, independently valid identity fields, including on rejected requests.
        if isinstance(request, dict):
            for key in ("request_id", "document_id"):
                if is_identifier(request.get(key)):
                    response[key] = request[key]
            revision = request.get("document_revision")
            if is_integer(revision, minimum=0, maximum=MAX_REVISION):
                response["document_revision"] = revision
        request = _validate_request(request)
        result: dict[str, Any]
        if request["operation"] == "handshake":
            if request["payload"]:
                raise ProtocolError("handshake payload must be empty")
            result = {
                "operations": [
                    "handshake",
                    "load_document",
                    "render",
                    "parse",
                    "export_svg",
                    "render_page",
                    "serialize_document",
                    "transcribe",
                ],
                "max_request_bytes": MAX_REQUEST_BYTES,
                "max_response_bytes": MAX_RESPONSE_BYTES,
                "custom_svg_display": True,
                "ocr_backends": {
                    "rapidocr-onnxruntime": importlib.util.find_spec(
                        "rapidocr_onnxruntime"
                    ) is not None,
                    "rapidocr-onnx": importlib.util.find_spec("rapidocr") is not None
                    and importlib.util.find_spec("onnxruntime") is not None,
                },
                "ocr": (
                    importlib.util.find_spec("rapidocr_onnxruntime") is not None
                    or importlib.util.find_spec("rapidocr") is not None
                    and importlib.util.find_spec("onnxruntime") is not None
                ),
                "png_export": True,
                "fonts": system_font_availability(),
            }
        else:
            operation = request["operation"]
            if operation == "render":
                result = _render(request["payload"])
            elif operation == "parse":
                result = _parse(request["payload"])
            elif operation == "export_svg":
                result = _export_svg(request["payload"])
            elif operation == "render_page":
                result = _render_page(request["payload"])
            elif operation == "load_document":
                result = _load_document(request["payload"])
            elif operation == "transcribe":

                def report(completed: int, total: int, stage: str) -> None:
                    if progress:
                        frame = {
                            **response,
                            "status": "progress",
                            "result": {
                                "completed": completed,
                                "total": total,
                                "stage": stage,
                            },
                        }
                        frame.pop("error", None)
                        progress(frame)

                result = _transcribe(request["payload"], report if progress else None)
            else:
                result = _serialize_document(request["payload"])
    except (
        ProtocolError,
        WireValidationError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        if isinstance(exc, PageOutOfRangeError):
            response["error"] = {
                "code": "page_out_of_range",
                "message": str(exc),
                "page_count": exc.page_count,
            }
        else:
            response["error"]["message"] = str(exc)
    except Exception as exc:
        # Recovery-oriented parsing can still fail during layout. Keep the process usable.
        response["error"] = {"code": "render_failed", "message": str(exc)}
    else:
        response.pop("error")
        response.update(status="ok", result=result)
    return response
