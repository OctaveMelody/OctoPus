"""Persistent stdio sidecar for the packaged app (UI Phase 2, R4).

Reads JSON-lines requests from stdin and writes exactly one serialized
response per request to stdout — the contract in ``PROTOCOL.md`` §1. Shares
``ops.dispatch`` with the dev HTTP transport; correctness never depends on
retained session state (requests are self-contained).

Discipline:

- **stdout carries only complete response records**, flushed after each line.
  Every log, warning, and traceback goes to stderr. A client must be able to
  parse every stdout line as one JSON object at all times.
- Lines longer than ``MAX_LINE_BYTES`` are drained (bounded memory) and
  answered with a ``parse_error`` envelope — one oversized request cannot OOM
  or wedge the sidecar, and the stream continues with the next line.
- EOF on stdin exits cleanly (0); SIGTERM exits cleanly (0). The Rust
  supervisor (R4) owns restart/backoff/orphan policy around this process.

Run: ``python -m ui.engine.stdio_server``
"""

from __future__ import annotations

import signal
import sys
from collections.abc import Iterator
from typing import Any, Protocol

from octopus import __version__
from ui.engine.ops import dispatch
from ui.engine.protocol import (
    STATUS_PARSE_ERROR,
    DocResponse,
    PingResponse,
    RenderResponse,
    serialize_response,
)

#: Same bound as the dev HTTP transport (PROTOCOL.md §1): render requests carry
#: full JPS records; 10 MiB is generous for any real score.
MAX_LINE_BYTES = 10 * 1024 * 1024
_CHUNK_SIZE = 65536

# Sentinel yielded when a line exceeded MAX_LINE_BYTES and was drained.
_OVERSIZED = object()


class _LineReader(Protocol):
    """What the sidecar needs from stdin: non-blocking-ish chunked reads."""

    def read1(self, size: int) -> bytes: ...


def _iter_lines(stream: _LineReader) -> Iterator[Any]:
    """Yield newline-terminated lines from a binary stream, memory-bounded.

    A line already over the cap before its newline arrives is drained chunk by
    chunk (without accumulation) and replaced by the ``_OVERSIZED`` sentinel,
    so worst-case memory is one capped line plus one chunk.

    Uses ``read1`` (not ``read``): ``read(n)`` on a buffered reader blocks until
    n bytes or EOF, which would wedge the sidecar waiting for a full chunk of
    input that never arrives while the supervisor keeps stdin open.
    """
    buf = b""
    draining = False
    while True:
        chunk = stream.read1(_CHUNK_SIZE)
        if not chunk:
            if draining:
                yield _OVERSIZED  # oversized line cut off by EOF
            elif buf:
                yield buf  # final line without a trailing newline
            return
        if draining:
            nl = chunk.find(b"\n")
            if nl != -1:
                draining = False
                yield _OVERSIZED
                buf = chunk[nl + 1 :]
            continue
        buf += chunk
        while True:
            nl = buf.find(b"\n")
            if nl == -1:
                break
            line, buf = buf[:nl], buf[nl + 1 :]
            # A line that completes over the cap is discarded as a whole (it is
            # already in memory, bounded by cap + one chunk); the stream moves
            # on with whatever follows the newline.
            yield _OVERSIZED if len(line) > MAX_LINE_BYTES else line
        if len(buf) > MAX_LINE_BYTES:
            # No newline yet and already over the cap: stop accumulating so
            # memory stays bounded even for a multi-megabyte "line".
            draining = True
            buf = b""


def _oversized_response() -> RenderResponse:
    return RenderResponse(
        id=None,
        status=STATUS_PARSE_ERROR,
        error=f"request line exceeds {MAX_LINE_BYTES} bytes and was discarded",
        version=__version__,
    )


def main() -> int:
    def _clean_exit(signum: int, frame: Any) -> None:
        sys.stderr.write("stdio server: terminating\n")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _clean_exit)

    # A BufferedReader in practice (mypy types sys.stdin.buffer as BinaryIO,
    # which lacks read1); the protocol above states what is actually needed.
    stdin: Any = sys.stdin.buffer
    # BINARY stdout: the wire is UTF-8 bytes (PROTOCOL.md §1). Text-mode
    # sys.stdout would encode through the console code page on Windows
    # (cp1252 & co.), and CJK in SVG/response bytes would crash the sidecar
    # mid-session — byte writes are encoding-independent on every platform.
    stdout = sys.stdout.buffer
    for line in _iter_lines(stdin):
        if line is _OVERSIZED:
            response: PingResponse | RenderResponse | DocResponse = _oversized_response()
        else:
            # dispatch never raises (pinned by fuzz tests); decode errors are
            # its business, as with the HTTP transport.
            response = dispatch(line.decode("utf-8", errors="replace"))
        stdout.write(serialize_response(response).encode("utf-8"))
        stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
