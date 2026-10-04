"""Bounded UTF-8 JSON-lines over stdin/stdout; logs belong on stderr."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, BinaryIO

from octopus.transcription.session_artifacts import track_session_artifact

from .desktop_protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, dispatch, error_response


def serve(source: BinaryIO, destination: BinaryIO, *, generation: str | None = None) -> None:
    generation = generation or uuid.uuid4().hex

    def report(response: dict[str, Any]) -> None:
        frame = dict(response)
        frame.pop("error", None)
        encoded = json.dumps(frame, ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise ValueError("progress exceeds byte limit")
        destination.write(encoded)
        destination.flush()

    while line := source.readline(MAX_REQUEST_BYTES + 1):
        if len(line) > MAX_REQUEST_BYTES:
            # Drain only the rejected frame, with bounded allocations, then accept the next one.
            while not line.endswith(b"\n"):
                line = source.readline(MAX_REQUEST_BYTES + 1)
                if not line:
                    break
            response = error_response(generation, "request_too_large", "request exceeds byte limit")
        else:
            response = dispatch(line, generation, progress=report)
        encoded = json.dumps(response, ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE_BYTES:
            response = {
                **response,
                "status": "error",
                "error": {"code": "response_too_large", "message": "render exceeds byte limit"},
            }
            response.pop("result", None)
            encoded = json.dumps(response).encode("utf-8") + b"\n"
        destination.write(encoded)
        destination.flush()


def main() -> None:
    try:
        with track_session_artifact():
            serve(sys.stdin.buffer, sys.stdout.buffer)
    except BrokenPipeError:
        # A closed parent is normal shutdown, not a protocol message.
        pass


if __name__ == "__main__":
    main()
