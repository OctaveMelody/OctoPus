"""Document persistence for the dev editor loop (UI Phase 2, R2b minimum).

The dev file adapter never writes to ``samples/`` (the sha-guarded immutable
corpus): the first load of a corpus file materializes a **working copy** under
the UI workspace (system temp by default), and all subsequent reads, saves,
and recovery snapshots operate on that copy. Native save through Rust file
commands replaces this in R4/R5; the semantics here are what that
implementation must match:

- **Wrapper preservation:** the original JSON wrapper record is the base for
  every save; only ``code`` / ``custom_code`` / ``page_config`` are updated,
  unknown fields survive verbatim. A render projection is not the document
  saved to disk (DOCUMENT_IDENTITY.md).
- **Format stability:** wrappers serialize exactly like the corpus —
  ``json.dumps(record, ensure_ascii=False, indent=2)``, no trailing newline,
  UTF-8 without BOM, LF newlines inside strings.
- **Atomic replacement:** a temp file in the same directory plus
  ``os.replace`` — a crash mid-save leaves either the old or the new file,
  never a torn one.
- **External-change conflict:** the client sends the sha256 it last read; a
  mismatch is a :class:`ConflictError` (HTTP 409 / ``error`` envelope), not a
  silent overwrite.

Recovery snapshots persist the *whole* document (settings and custom SVG
included, not just CodeMirror text) per DOCUMENT_IDENTITY.md schema v1, so an
app restart can offer to restore unsaved work.

Both transports share these functions: the dev HTTP server exposes them as
REST endpoints, and protocol 1.2.0 routes the same operations through
``ops.dispatch`` (``files.list`` / ``file.read`` / ``file.save`` / ``file.new``
/ ``file.save_as`` / ``recovery.*``) so the stdio sidecar — and therefore the
packaged app — owns document persistence without duplicating this policy in
Rust.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

#: Override the UI workspace location (tests use this for isolation).
UI_HOME_ENV = "OCTOPUS_UI_HOME"

#: Override the corpus directory (packaged app ships its own copy beside the
#: binary; tests may point it at a fixture tree). Read at call time so a
#: test can swap it without re-importing.
CORPUS_DIR_ENV = "OCTOPUS_CORPUS_DIR"


def corpus_dir() -> Path:
    """The read-only corpus directory (``*.jps`` wrappers), never written to."""
    override = os.environ.get(CORPUS_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "samples" / "jps_files"


def _jps_names(directory: Path) -> set[str]:
    """Bare ``.jps`` filenames in a directory, case-insensitive on the suffix.

    ``new_working_copy``/``save_as`` accept uppercase extensions (``MySong.JPS``)
    via ``lower().endswith``, so the listing must too — a case-sensitive
    ``glob("*.jps")`` would hide such files from the open dialog on Linux.
    Unreadable directories degrade to an empty set rather than failing the list.
    """
    names: set[str] = set()
    try:
        entries = list(directory.iterdir())
    except OSError:
        return names
    for path in entries:
        if path.name.lower().endswith(".jps") and path.is_file():
            names.add(
                path.name[:-len(".jps")]
                if path.name.lower().endswith(".jps.jps")
                else path.name
            )
    return names


def list_documents() -> tuple[str, ...]:
    """Every openable document name: corpus ∪ working copies, sorted, unique.

    A workspace file may shadow a corpus name (the working copy is the
    editable version of it) or exist only in the workspace (a user-created
    document) — without the union, newly created files would be unopenable
    after an app restart because the open dialog lists ``files.list``.
    """
    names = _jps_names(corpus_dir())
    names.update(_jps_names(ui_home() / "workspace"))
    return tuple(sorted(names))


class UnknownFileError(Exception):
    """The requested corpus file does not exist."""


class ConflictError(Exception):
    """The file changed on disk since the client last read it."""


def ui_home() -> Path:
    root = Path(os.environ.get(UI_HOME_ENV) or (Path(tempfile.gettempdir()) / "octopus-ui"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_dir() -> Path:
    path = ui_home() / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recovery_dir() -> Path:
    path = ui_home() / "recovery"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_filename(name: str) -> str:
    """Only bare filenames inside the corpus dir — no traversal, no empties."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise UnknownFileError(f"invalid file name: {name!r}")
    return name


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def working_copy_path(name: str) -> Path:
    return workspace_dir() / validate_filename(name)


def _corpus_path(directory: Path, name: str) -> Path:
    path = directory / name
    if path.is_file() or not name.lower().endswith(".jps"):
        return path
    doubled_suffix = directory / f"{name}.jps"
    return doubled_suffix if doubled_suffix.is_file() else path


def ensure_working_copy(corpus_path: Path, name: str) -> tuple[Path, str]:
    """Materialize the working copy for ``name`` (idempotent).

    Returns ``(path, sha256)`` of the current working copy. The copy is made
    only on first load; later loads return the existing (possibly edited)
    copy so an unsaved dev session survives a browser reload.
    """
    target = working_copy_path(name)
    if not target.exists():
        corpus_path = _corpus_path(corpus_path.parent, corpus_path.name)
        if not corpus_path.is_file():
            raise UnknownFileError(f"unknown file: {name!r}")
        target.write_bytes(corpus_path.read_bytes())
    return target, sha256_of(target)


def _write_atomic(path: Path, data: bytes) -> None:
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)  # atomic on POSIX and Windows
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def serialize_wrapper(record: dict[str, Any]) -> bytes:
    """Corpus-exact wrapper serialization (verified over all 65 files)."""
    return json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")


def apply_editable_fields(
    record: dict[str, Any],
    *,
    code: str | None = None,
    custom_code: str | None = None,
    page_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of ``record`` with the editable fields updated in place.

    Only provided (non-None) fields change; every other field — including
    unknown ones — survives verbatim. ``page_config`` keeps its on-disk form:
    a string-encoded value is re-encoded as a compact JSON string (the corpus
    style), an object stays an object.
    """
    updated = dict(record)
    if code is not None:
        updated["code"] = code
    if custom_code is not None:
        updated["custom_code"] = custom_code
    if page_config is not None:
        existing = record.get("page_config")
        if isinstance(existing, str):
            updated["page_config"] = json.dumps(page_config, ensure_ascii=False)
        else:
            updated["page_config"] = page_config
    return updated


def validate_save_path(path: str) -> Path:
    """1.9.0: the user-chosen save destination must be a non-empty absolute
    path (it comes from the OS save dialog; anything else is a client bug).
    Raises ValueError with a readable message otherwise.
    """
    candidate = Path(path)
    if not path or not candidate.is_absolute():
        raise ValueError(f"save path must be absolute: {path!r}")
    return candidate


def import_external_file(path: str) -> tuple[dict[str, Any], str]:
    """1.10.0: materialize a working copy from an EXTERNAL .jps file.

    ``path`` is the absolute path chosen in the OS open dialog (the packaged
    app's 打开 for files outside the sample library). The file's basename
    becomes the working-copy name. Refuses — instead of clobbering — when a
    working copy of that name already exists (it may hold unsaved edits);
    the source file is never modified. Returns ``(record, sha256)`` of the
    materialized working copy, shaped exactly like ``file.read``'s result.
    """
    source = validate_save_path(path)
    if not source.is_file():
        raise UnknownFileError(f"no such file: {source}")
    name = source.name
    if not name.lower().endswith(".jps"):
        raise UnknownFileError(f"not a .jps file: {name!r}")
    validate_filename(name)
    target = working_copy_path(name)
    if target.exists():
        raise ConflictError(
            f"{name!r} is already loaded as a working copy (possibly with "
            "unsaved changes) — close it first, then import again"
        )
    data = source.read_bytes()
    try:
        record = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UnknownFileError(f"{name!r} is not a valid JPS file: {e}") from e
    if not isinstance(record, dict) or not isinstance(record.get("code"), str):
        raise UnknownFileError(
            f"{name!r} is not a valid JPS file (missing the 'code' field)"
        )
    _write_atomic(target, data)
    return record, sha256_of(target)


def save_working_copy(
    name: str,
    record: dict[str, Any],
    *,
    expected_sha256: str | None = None,
    path: str | None = None,
    path_expected_sha256: str | None = None,
) -> str:
    """Atomically save a wrapper record to the working copy.

    ``expected_sha256`` is the hash the client last read (open or previous
    save); a mismatch means someone else changed the file and the save is
    refused as a conflict. Returns the new sha256.

    1.9.0: with ``path`` set, the identical bytes are ALSO written to that
    absolute destination (parent directories created) — the user's file from
    the OS save dialog and the working copy stay in lockstep. The mirror is
    written BEFORE the working copy, so a failed mirror leaves the session's
    on-disk state untouched.

    1.9.0: ``path_expected_sha256`` guards the mirror destination the same
    way ``expected_sha256`` guards the working copy — after every
    save-to-path both files are byte-identical, so a differing destination
    means the user's file changed on disk since (external edit) and is
    refused instead of clobbered. Absent = the destination was just picked
    in the dialog = explicit overwrite authorization.
    """
    mirror = validate_save_path(path) if path is not None else None
    target = working_copy_path(name)
    if not target.is_file():
        raise UnknownFileError(f"unknown file: {name!r} (load it first)")
    current = sha256_of(target)
    if expected_sha256 is not None and expected_sha256 != current:
        raise ConflictError(
            f"{name!r} changed on disk since it was last read "
            f"(expected {expected_sha256[:12]}…, found {current[:12]}…)"
        )
    if mirror is not None and path_expected_sha256 is not None and mirror.is_file():
        actual = sha256_of(mirror)
        if actual != path_expected_sha256:
            raise ConflictError(
                f"destination {mirror} changed on disk since the last save "
                f"(expected {path_expected_sha256[:12]}…, found {actual[:12]}…) — "
                "re-pick the location to overwrite it"
            )
    data = serialize_wrapper(record)
    if mirror is not None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(mirror, data)
    _write_atomic(target, data)
    return sha256_of(target)


#: Default page settings for new documents — the common A4/40-margin corpus
#: style (string-encoded, compact, like every corpus wrapper).
DEFAULT_PAGE_CONFIG_JSON = (
    '{"page":"A4","margin_top":"40","margin_bottom":"40","margin_left":"60",'
    '"margin_right":"60","biaoti_font":"Microsoft YaHei","shuzi_font":"b",'
    '"geci_font":"Microsoft YaHei","height_quci":"13","height_cici":"10",'
    '"height_ciqu":"40","height_shengbu":"0","biaoti_size":"36",'
    '"fubiaoti_size":"20","geci_size":"18","body_margin_top":"40",'
    '"lianyinxian_type":"0"}'
)

#: Minimal valid score body for a new document — a real `Q:` music line with
#: an empty body. JPS has no measure numbers: the old default `1 2 3` parsed
#: as an unrecognized line (JPS001) that renders to nothing, so notes typed
#: into it produced byte-identical pages and the preview never updated.
DEFAULT_NEW_CODE = "Q: \n"


def new_working_copy(name: str, *, corpus_dir: Path, code: str | None = None) -> str:
    """Create a fresh working copy with a corpus-shaped wrapper record.

    The wrapper mirrors the corpus field set (id/uid/fid/name/code/
    custom_code/page_config/create_time/last_time) so a new file is
    indistinguishable in shape from an upstream one; only the identity fields
    are synthesized. Like save-as, the target must not exist as a working
    copy or a corpus file. Returns the sha256 of the created file.

    1.10.0: optional ``code`` — the initial score text (the website-style
    description header built by the New dialog); absent = DEFAULT_NEW_CODE,
    exactly as before.
    """
    validate_filename(name)
    if not name.lower().endswith(".jps"):
        raise UnknownFileError(f"new name must end in .jps: {name!r}")
    target = working_copy_path(name)
    if target.exists() or _corpus_path(corpus_dir, name).is_file():
        raise ConflictError(f"{name!r} already exists — new never overwrites")
    now_ms = int(time.time() * 1000)
    record = {
        "id": str(now_ms),
        "uid": "0",
        "fid": "0",
        "name": name[: -len(".jps")] if name.lower().endswith(".jps") else name,
        "code": code if code is not None else DEFAULT_NEW_CODE,
        "custom_code": "",
        "page_config": DEFAULT_PAGE_CONFIG_JSON,
        "create_time": str(now_ms // 1000),
        "last_time": str(now_ms // 1000),
    }
    _write_atomic(target, serialize_wrapper(record))
    return sha256_of(target)


def save_as(
    old_name: str,
    new_name: str,
    *,
    corpus_dir: Path,
    expected_sha256: str | None = None,
    path: str | None = None,
) -> str:
    """Atomically rename a working copy (Save As).

    Identity policy (DOCUMENT_IDENTITY.md, Save As section): the source key
    follows the new filename stem exactly as ``load_jps``/the CLI derive it —
    nothing is persisted in the wrapper that the CLI would ignore. The target
    must not exist as a working copy *or* a corpus file: save-as never
    overwrites, and every compatibility-mechanism key is a corpus stem, so
    collisions structurally prevent accidental mechanism activation.
    The old name's recovery snapshot is cleared (a save-as is a clean save).
    Returns the sha256 of the renamed file.

    1.9.0: with ``path`` set, the renamed bytes are ALSO written to that
    absolute destination (see ``save_working_copy``). The mirror is written
    BEFORE the rename — the same ordering policy as ``save_working_copy`` —
    so a failed mirror leaves the working copy unrenamed and the caller sees
    no state it did not get.
    """
    mirror = validate_save_path(path) if path is not None else None
    validate_filename(new_name)
    if not new_name.lower().endswith(".jps"):
        raise UnknownFileError(f"new name must end in .jps: {new_name!r}")
    old_path = working_copy_path(old_name)
    if not old_path.is_file():
        raise UnknownFileError(f"unknown file: {old_name!r} (load it first)")
    new_path = working_copy_path(new_name)
    if new_path.exists() or _corpus_path(corpus_dir, new_name).is_file():
        raise ConflictError(f"{new_name!r} already exists — save-as never overwrites")
    current = sha256_of(old_path)
    if expected_sha256 is not None and expected_sha256 != current:
        raise ConflictError(
            f"{old_name!r} changed on disk since it was last read "
            f"(expected {expected_sha256[:12]}…, found {current[:12]}…)"
        )
    data = old_path.read_bytes()
    if mirror is not None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(mirror, data)
    os.replace(old_path, new_path)  # same directory: atomic rename
    clear_recovery(old_name)
    return sha256_of(new_path)


def save_recovery(name: str, payload: dict[str, Any]) -> None:
    """Persist a whole-document recovery snapshot (schema v1, see the doc)."""
    path = recovery_dir() / f"{validate_filename(name)}.json"
    _write_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def load_recovery(name: str) -> dict[str, Any] | None:
    path = recovery_dir() / f"{validate_filename(name)}.json"
    if not path.is_file():
        return None
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def clear_recovery(name: str) -> bool:
    """Drop the recovery snapshot (e.g. after a clean save); True if removed."""
    path = recovery_dir() / f"{validate_filename(name)}.json"
    if path.is_file():
        path.unlink()
        return True
    return False
