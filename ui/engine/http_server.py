"""Development-only HTTP transport for the JPS editor engine (UI Phase 2, R3a).

Serves the exact wire contract of ``ui.engine.protocol`` over loopback HTTP so
frontend iteration (R3b) is decoupled from Tauri build times. The packaged app
uses stdio exclusively; this server is never part of release startup. It shares
``ops.dispatch`` with every other transport, so the dev path and the packaged
path cannot drift: a request body is one wire record (the same JSON object a
stdio client would write as a line) and the response body is the serialized
response record.

Endpoints:
    POST /request  — body: one wire request record; response: one wire response
                     record (same fields as the stdio line, minus framing).
    GET  /health   — readiness probe: 200 with a small JSON status object.
    GET  /files    — dev file adapter: list corpus wrapper filenames.
    GET  /file?name=X.jps — dev file adapter: one file's working copy as
                     {"sha256": …, "record": …}. First load materializes the
                     working copy from the immutable corpus (ui/engine/
                     documents.py); later loads return the edited copy.
    POST /file     — save {name, code?, custom_code?, page_config?,
                     expected_sha256?} to the working copy: wrapper fields are
                     preserved, replacement is atomic, a hash mismatch is a
                     409 conflict. Native save (Rust) replaces this in R4/R5.
    POST /save-as  — {name, new_name, expected_sha256?}: atomically rename the
                     working copy; identity follows the new stem (policy in
                     DOCUMENT_IDENTITY.md); existing target is a 409.
    POST /file/new — {name}: create a fresh working copy with a corpus-shaped
                     wrapper (documents.new_working_copy); existing target is a
                     409.
    GET  /recovery?name=X.jps — whole-document recovery snapshot or 404.
    POST /recovery — persist the document's recovery snapshot (schema v1).
    DELETE /recovery?name=X.jps — drop it (after a clean save).

Security posture (dev tool, loopback only):
    - binds 127.0.0.1 only; never 0.0.0.0.
    - requests carrying an ``Origin`` header are accepted only from
      localhost/127.0.0.1 origins (any port); anything else is rejected with
      403 before touching the engine. Origin-less requests (curl, subprocess
      tests) are allowed — the loopback bind is the boundary.
    - request bodies above ``MAX_BODY_BYTES`` are rejected without being read
      into memory in full.

Logs go to stderr; stdout stays clean so the process can be piped.

Usage:
    uv run python -m ui.engine.http_server [--port 8790]

With ``--port 0`` an ephemeral port is chosen and the bound address is printed
to stderr as ``listening on http://127.0.0.1:<port>`` (used by the tests).
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from octopus.jps import repair_mojibake
from ui.engine import documents as docs
from ui.engine.ops import dispatch
from ui.engine.protocol import serialize_response

MAX_BODY_BYTES = 10 * 1024 * 1024  # render requests carry full JPS records; 10 MiB is generous
_LOOPBACK_HOST = "127.0.0.1"
# Corpus directory resolution lives in documents.corpus_dir() (shared with the
# 1.2.0 dispatch ops): OCTOPUS_CORPUS_DIR override, repo default otherwise.
# Read at request time so a test can swap it without re-importing.

log = logging.getLogger("ui.engine.http_server")


def _origin_allowed(origin: str | None) -> bool:
    """Accept origin-less requests and localhost origins (any port), else reject."""
    if origin is None:
        return True
    lowered = origin.lower()
    for prefix in ("http://localhost:", "http://127.0.0.1:", "https://localhost:"):
        if lowered.startswith(prefix):
            return True
    return False


class _Handler(BaseHTTPRequestHandler):
    """One request at a time per connection; dispatch is stateless and shared."""

    server_version = "JpsEngine/1.1"
    # Socket-level inactivity bound (StreamRequestHandler.timeout): a client
    # that stalls mid-body-send would otherwise pin its daemon thread forever
    # in rfile.read(length). The timer only fires on socket idleness — a long
    # render never touches the socket, so this cannot kill slow work.
    timeout = 60

    def log_message(self, format: str, *args: object) -> None:
        # Route the stdlib access log to stderr (stdout must stay clean).
        log.debug(format, *args)

    def _send_json(self, status: int, payload: dict[str, Any], cors_origin: str | None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"}, None)
        elif parsed.path == "/files":
            # Same union as the 1.2.0 files.list op (corpus ∪ working copies),
            # so the dev dialog and the packaged dialog list identical names.
            self._send_json(200, {"files": list(docs.list_documents())}, None)
        elif parsed.path == "/file":
            name = (parse_qs(parsed.query).get("name") or [""])[0]
            try:
                target, digest = docs.ensure_working_copy(docs.corpus_dir() / name, name)
            except docs.UnknownFileError as exc:
                self._send_json(404, {"error": str(exc)}, None)
                return
            record = json.loads(target.read_text(encoding="utf-8-sig"))
            file_payload: dict[str, object] = {"sha256": digest, "record": record}
            # R2d policy (DOCUMENT_IDENTITY.md §6): when mojibake repair fires,
            # the repaired text becomes the visible editable document. The
            # file on disk is NOT rewritten here — only an explicit save does.
            code = record.get("code")
            if isinstance(code, str):
                repaired, fired = repair_mojibake(code)
                if fired:
                    file_payload["encoding_repaired"] = True
                    file_payload["repaired_code"] = repaired
            self._send_json(200, file_payload, None)
        elif parsed.path == "/recovery":
            name = (parse_qs(parsed.query).get("name") or [""])[0]
            try:
                payload = docs.load_recovery(name)
            except docs.UnknownFileError as exc:
                self._send_json(404, {"error": str(exc)}, None)
                return
            if payload is None:
                self._send_json(404, {"error": f"no recovery snapshot for {name!r}"}, None)
                return
            self._send_json(200, payload, None)
        else:
            self._send_json(404, {"error": f"unknown path: {self.path}"}, None)

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        if not _origin_allowed(origin):
            self._send_json(403, {"error": f"origin not allowed: {origin}"}, None)
            return
        parsed = urlparse(self.path)
        if parsed.path not in ("/request", "/file", "/recovery", "/save-as", "/file/new"):
            self._send_json(404, {"error": f"unknown path: {self.path}"}, origin)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            # Drain a bounded amount so well-behaved clients finish their send
            # instead of hitting a connection reset; memory stays capped.
            remaining = min(length, MAX_BODY_BYTES * 2)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            self._send_json(413, {"error": f"body too large (max {MAX_BODY_BYTES} bytes)"}, origin)
            return
        raw = self.rfile.read(length) if length else b""
        if self.path == "/request":
            # The wire contract is one record per line; accept the body with or
            # without the trailing newline and feed dispatch exactly what stdio
            # would (a single line, no framing assumptions beyond that).
            response = dispatch(raw.decode("utf-8", errors="replace").rstrip("\n"))
            self._send_json(200, json.loads(serialize_response(response)), origin)
        elif self.path == "/recovery":
            self._handle_recovery_save(raw, origin)
        elif self.path == "/save-as":
            self._handle_save_as(raw, origin)
        elif self.path == "/file/new":
            self._handle_new_file(raw, origin)
        else:
            self._handle_save(raw, origin)

    def do_DELETE(self) -> None:
        origin = self.headers.get("Origin")
        if not _origin_allowed(origin):
            self._send_json(403, {"error": f"origin not allowed: {origin}"}, None)
            return
        parsed = urlparse(self.path)
        if parsed.path != "/recovery":
            self._send_json(404, {"error": f"unknown path: {self.path}"}, origin)
            return
        name = (parse_qs(parsed.query).get("name") or [""])[0]
        try:
            removed = docs.clear_recovery(name)
        except docs.UnknownFileError as exc:
            self._send_json(404, {"error": str(exc)}, origin)
            return
        self._send_json(200, {"removed": removed}, origin)

    def _handle_save(self, raw: bytes, origin: str | None) -> None:
        """POST /file — wrapper-preserving atomic save to the working copy."""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "save body must be a JSON object"}, origin)
            return
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            self._send_json(400, {"error": "save body needs a string 'name'"}, origin)
            return
        name = body["name"]
        try:
            record = json.loads(
                docs.working_copy_path(name).read_text(encoding="utf-8-sig")
            )
        except (docs.UnknownFileError, OSError, json.JSONDecodeError):
            self._send_json(404, {"error": f"unknown file: {name!r} (load it first)"}, origin)
            return
        expected = body.get("expected_sha256")
        if expected is not None and not isinstance(expected, str):
            self._send_json(
                400, {"error": "'expected_sha256' must be a string when present"}, origin
            )
            return
        code = body.get("code")
        custom_code = body.get("custom_code")
        page_config = body.get("page_config")
        for field_name, value in (("code", code), ("custom_code", custom_code)):
            if value is not None and not isinstance(value, str):
                self._send_json(
                    400, {"error": f"'{field_name}' must be a string when present"}, origin
                )
                return
        if page_config is not None and not isinstance(page_config, dict):
            self._send_json(400, {"error": "'page_config' must be an object when present"}, origin)
            return
        updated = docs.apply_editable_fields(
            record,
            code=code if isinstance(code, str) else None,
            custom_code=custom_code if isinstance(custom_code, str) else None,
            page_config=page_config if isinstance(page_config, dict) else None,
        )
        try:
            digest = docs.save_working_copy(name, updated, expected_sha256=expected)
        except docs.ConflictError as exc:
            self._send_json(409, {"error": str(exc)}, origin)
            return
        except docs.UnknownFileError as exc:
            self._send_json(404, {"error": str(exc)}, origin)
            return
        self._send_json(200, {"status": "ok", "sha256": digest}, origin)

    def _handle_save_as(self, raw: bytes, origin: str | None) -> None:
        """POST /save-as — rename the working copy; identity follows the stem."""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "save-as body must be a JSON object"}, origin)
            return
        name = body.get("name") if isinstance(body, dict) else None
        new_name = body.get("new_name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not isinstance(new_name, str):
            self._send_json(
                400, {"error": "save-as body needs string 'name' and 'new_name'"}, origin
            )
            return
        expected = body.get("expected_sha256")
        if expected is not None and not isinstance(expected, str):
            self._send_json(
                400, {"error": "'expected_sha256' must be a string when present"}, origin
            )
            return
        try:
            digest = docs.save_as(
                name, new_name, corpus_dir=docs.corpus_dir(), expected_sha256=expected
            )
        except docs.ConflictError as exc:
            self._send_json(409, {"error": str(exc)}, origin)
            return
        except docs.UnknownFileError as exc:
            self._send_json(404, {"error": str(exc)}, origin)
            return
        self._send_json(200, {"status": "ok", "sha256": digest}, origin)

    def _handle_new_file(self, raw: bytes, origin: str | None) -> None:
        """POST /file/new — create a fresh corpus-shaped working copy."""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "new-file body must be a JSON object"}, origin)
            return
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str):
            self._send_json(400, {"error": "new-file body needs a string 'name'"}, origin)
            return
        try:
            digest = docs.new_working_copy(name, corpus_dir=docs.corpus_dir())
        except docs.ConflictError as exc:
            self._send_json(409, {"error": str(exc)}, origin)
            return
        except docs.UnknownFileError as exc:
            self._send_json(404, {"error": str(exc)}, origin)
            return
        self._send_json(200, {"status": "ok", "sha256": digest}, origin)

    def _handle_recovery_save(self, raw: bytes, origin: str | None) -> None:
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "recovery body must be a JSON object"}, origin)
            return
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            self._send_json(400, {"error": "recovery body needs a string 'name'"}, origin)
            return
        name = body["name"]
        payload = body.get("document")
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "recovery body needs an object 'document'"}, origin)
            return
        try:
            docs.save_recovery(name, payload)
        except docs.UnknownFileError as exc:
            self._send_json(404, {"error": str(exc)}, origin)
            return
        self._send_json(200, {"status": "ok"}, origin)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if not _origin_allowed(origin):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        if origin is not None:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")
        self.end_headers()


class _Server(ThreadingHTTPServer):
    """Daemon handler threads so a stuck request cannot block process exit."""

    daemon_threads = True


def serve(port: int = 8790) -> ThreadingHTTPServer:
    """Start the dev server on loopback; returns the running server instance."""
    return _Server((_LOOPBACK_HOST, port), _Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8790, help="TCP port (0 = ephemeral)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    def _terminate(signum: int, frame: Any) -> None:
        raise SystemExit(0)  # clean exit so supervisors see a normal shutdown

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _terminate)

    httpd = serve(args.port)
    # Plain (unformatted) machine-readable line on stderr: tests and dev tooling
    # parse the bound port from it. Stdout stays clean for piping.
    bound = f"listening on http://{_LOOPBACK_HOST}:{httpd.server_address[1]}"
    print(bound, file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
