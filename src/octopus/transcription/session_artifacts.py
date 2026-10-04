"""Remove newly created diagnostic session debris on normal process exit.

The exact producer of :memory:.ses is not established. Never glob CWD or
remove an existing file, a symlink, or a file that was replaced after creation.
"""

from __future__ import annotations

import atexit
import hashlib
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _identity(path: Path) -> tuple[int, int, int, int, bytes] | None:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            return None
        digest = hashlib.sha256(path.read_bytes()).digest()
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, digest
    except OSError:
        return None


def _delete_owned(path: Path, identity: tuple[int, int, int, int, bytes]) -> None:
    if _identity(path) == identity:
        try:
            path.unlink()
        except OSError:
            pass


@contextmanager
def track_session_artifact() -> Iterator[None]:
    """Watch one creation boundary; cleanup belongs only to a file first made here."""
    path = Path.cwd() / ":memory:.ses"
    absent = not path.exists() and not path.is_symlink()
    try:
        yield
    finally:
        identity = _identity(path) if absent else None
        if identity is not None:
            atexit.register(_delete_owned, path, identity)
