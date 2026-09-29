"""Safe, deterministic helpers for renderer-owned filesystem output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MANIFEST_SCHEMA_VERSION = 2
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_OWNER_FILE_RE = {
    "render_jps": re.compile(r"page_[1-9][0-9]*\.html\Z"),
    "render_all": re.compile(r".+_page[1-9][0-9]*\.svg\Z"),
}


@dataclass(frozen=True, slots=True)
class OwnedManifest:
    """Validated renderer ownership metadata."""

    files: frozenset[str]
    hashes: Mapping[str, str]


def write_utf8_text(path: Path, text: str) -> None:
    """Atomically write UTF-8 text without following a destination symlink."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def read_owned_manifest(manifest_path: Path, *, owner: str) -> OwnedManifest:
    """Read a renderer manifest, returning no deletable files if it is unsafe."""
    if manifest_path.is_symlink():
        return OwnedManifest(frozenset(), {})
    try:
        value: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return OwnedManifest(frozenset(), {})
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != _MANIFEST_SCHEMA_VERSION
        or value.get("owner") != owner
    ):
        return OwnedManifest(frozenset(), {})
    files = value.get("files")
    hashes = value.get("hashes")
    if (
        not isinstance(files, list)
        or not all(isinstance(name, str) for name in files)
        or not isinstance(hashes, dict)
        or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in hashes.items()
        )
    ):
        return OwnedManifest(frozenset(), {})
    owned = frozenset(files)
    if (
        len(owned) != len(files)
        or set(hashes) != owned
        or not all(_is_safe_owned_name(name) for name in owned)
        or owner not in _OWNER_FILE_RE
        or not all(_OWNER_FILE_RE[owner].fullmatch(name) for name in owned)
        or not all(_SHA256_RE.fullmatch(value) for value in hashes.values())
    ):
        return OwnedManifest(frozenset(), {})
    return OwnedManifest(owned, dict(hashes))


def read_owned_files(manifest_path: Path, *, owner: str) -> frozenset[str]:
    """Return the files from a validated renderer manifest."""
    return read_owned_manifest(manifest_path, owner=owner).files


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_owned_files(
    root: Path,
    staged_files: Mapping[str, Path],
    *,
    previous: OwnedManifest,
    current: Iterable[str],
    replaceable_names: Iterable[str] = (),
) -> None:
    """Publish a staged owned-file set with rollback on publication failure.

    The staged files must be single-child names under *root*. Existing targets are replaceable only
    when their bytes match the previous renderer manifest, except for explicitly reserved control
    files in *replaceable_names*. A private sibling backup makes a failed replacement reversible;
    stale regular files are removed only after the same ownership check.
    """
    root = root.resolve()
    staged = dict(staged_files)
    previous_names = set(previous.files)
    current_names = set(current)
    replaceable = set(replaceable_names)
    if not replaceable <= set(staged):
        raise ValueError("Replaceable renderer names must be staged")
    names = set(staged) | previous_names | current_names
    invalid_names = sorted(name for name in names if not _is_safe_owned_name(name))
    if invalid_names:
        raise ValueError(f"Unsafe renderer-owned filenames: {invalid_names!r}")
    for _name, staged_path in staged.items():
        if not staged_path.is_file() or staged_path.is_symlink():
            raise ValueError(f"Staged renderer output is not a regular file: {staged_path}")
    staged_hashes = {name: sha256_file(path) for name, path in staged.items()}

    stale_names = previous_names - current_names
    affected_names = set(staged)
    for name in stale_names:
        path = root / name
        if path.is_file() and not path.is_symlink():
            _assert_previous_file(path, name, previous.hashes.get(name))
            affected_names.add(name)
    for name in affected_names:
        path = root / name
        if path.is_dir() and not path.is_symlink():
            raise IsADirectoryError(path)
        if not (path.exists() or path.is_symlink()):
            continue
        if name not in previous_names and name not in replaceable:
            raise FileExistsError(
                f"Refusing to replace unowned renderer output: {path}. "
                "Render to a fresh output directory, or back up and move existing files aside."
            )
        if name in previous_names:
            _assert_previous_file(path, name, previous.hashes.get(name))

    backup_dir = Path(tempfile.mkdtemp(prefix=f".{root.name}-owned-backup-", dir=root.parent))
    backups: dict[str, Path] = {}
    published: set[str] = set()
    try:
        for name in sorted(affected_names):
            path = root / name
            if path.exists() or path.is_symlink():
                backup = backup_dir / name
                os.replace(path, backup)
                backups[name] = backup
        for name in sorted(staged):
            os.replace(staged[name], root / name)
            published.add(name)
    except BaseException as publication_error:
        rollback_errors: list[OSError] = []
        for name in sorted(published, reverse=True):
            path = root / name
            try:
                if path.exists() or path.is_symlink():
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or sha256_file(path) != staged_hashes[name]
                    ):
                        raise FileExistsError(
                            f"Published renderer output was replaced outside the renderer: {path}"
                        )
                    path.unlink()
            except OSError as error:
                rollback_errors.append(error)
        for name in sorted(backups):
            backup = backups[name]
            try:
                if backup.exists() or backup.is_symlink():
                    # Restore without clobbering a file created after publication failed.
                    if backup.is_symlink():
                        os.symlink(os.readlink(backup), root / name)
                    else:
                        os.link(backup, root / name)
                    backup.unlink()
            except OSError as error:
                rollback_errors.append(error)
        if rollback_errors:
            raise OSError(
                f"Renderer rollback was incomplete; recover original files from {backup_dir}. "
                f"Publication error: {publication_error}; rollback error: {rollback_errors[0]}"
            ) from publication_error
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise
    else:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _assert_previous_file(path: Path, name: str, expected_hash: str | None) -> None:
    if path.is_symlink() or not path.is_file() or expected_hash is None:
        raise FileExistsError(f"Renderer-owned output is not a verified regular file: {name}")
    if sha256_file(path) != expected_hash:
        raise FileExistsError(f"Renderer-owned output was modified outside the renderer: {name}")


def _is_safe_owned_name(name: str) -> bool:
    """Return whether *name* is a single safe child filename."""
    candidate_name = Path(name)
    if (
        not name
        or name in {".", ".."}
        or candidate_name.is_absolute()
        or candidate_name.name != name
    ):
        return False
    return True


__all__ = [
    "OwnedManifest",
    "publish_owned_files",
    "read_owned_manifest",
    "read_owned_files",
    "sha256_file",
    "write_utf8_text",
]
