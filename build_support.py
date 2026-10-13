"""Shared cross-platform helpers for production build scripts."""

from __future__ import annotations

import errno
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

_RETRYABLE_ERRNOS = {errno.EBUSY}
_RETRYABLE_WINERRORS = {32, 33}


def find_executable(name: str, *, path: str | None = None) -> str | None:
    """Find a host command by name, including Windows command shims."""
    candidates = (name, f"{name}.cmd", f"{name}.exe") if os.name == "nt" else (name,)
    for candidate in candidates:
        resolved = shutil.which(candidate, path=path)
        if resolved:
            return os.path.abspath(resolved)
    return None


def environment_with_tools(
    environment: dict[str, str], executables: list[str | None]
) -> dict[str, str]:
    """Return an environment whose PATH includes the folders of resolved tools."""
    paths: list[str] = []
    known = {
        os.path.normcase(os.path.abspath(entry))
        for entry in environment.get("PATH", "").split(os.pathsep)
        if entry
    }
    for executable in executables:
        if not executable:
            continue
        directory = os.path.dirname(executable)
        key = os.path.normcase(os.path.abspath(directory))
        if key not in known:
            known.add(key)
            paths.append(directory)
    result = dict(environment)
    if paths:
        current_path = result.get("PATH", "")
        result["PATH"] = os.pathsep.join(paths + ([current_path] if current_path else []))
    return result


def retry_filesystem(action: Callable[[], T], description: str, *, attempts: int = 4) -> T:
    """Retry busy and sharing-lock failures; let permanent permission errors fall back."""
    for attempt in range(attempts):
        try:
            return action()
        except OSError as error:
            winerror = getattr(error, "winerror", None)
            if winerror is not None:
                retryable = winerror in _RETRYABLE_WINERRORS
            else:
                retryable = error.errno in _RETRYABLE_ERRNOS
            if not retryable or attempt + 1 == attempts:
                raise
            delay = 0.25 * (2**attempt)
            print(
                f"Retrying {description} after a retryable filesystem access error "
                f"({attempt + 1}/{attempts - 1}): {error}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
    raise AssertionError("filesystem retry loop ended unexpectedly")


def remove_tree(path: Path) -> None:
    """Remove an existing tree, retrying transient file locks and access errors."""
    if path.exists():
        retry_filesystem(lambda: shutil.rmtree(path), f"remove {path}")


def publish_directory(
    staged: Path,
    destination: Path,
    backup: Path,
    *,
    retain_backup: bool,
) -> None:
    """Publish a verified staged tree, with retries, copy fallback, and rollback."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if staged.is_symlink() or destination.is_symlink() or backup.is_symlink():
        raise RuntimeError("refusing to publish through a symlinked build directory")

    remove_tree(backup)
    had_destination = destination.exists()
    if had_destination:
        retry_filesystem(
            lambda: destination.replace(backup),
            f"preserve the previous build at {destination}",
        )

    try:
        try:
            retry_filesystem(
                lambda: staged.replace(destination),
                f"publish the staged build to {destination}",
            )
        except OSError as rename_error:
            if destination.exists():
                remove_tree(destination)

            def copy_staged() -> None:
                try:
                    shutil.copytree(staged, destination, symlinks=True)
                except OSError:
                    if destination.exists():
                        remove_tree(destination)
                    raise

            try:
                retry_filesystem(copy_staged, f"copy the staged build to {destination}")
            except OSError as copy_error:
                raise RuntimeError(
                    f"Could not publish build output to {destination}. Directory rename failed: "
                    f"{rename_error}; copy fallback failed: {copy_error}. Check that the output "
                    "directory is writable and that no running app is holding its files open."
                ) from copy_error
    except BaseException as publish_error:
        try:
            if destination.exists():
                remove_tree(destination)
        except OSError as cleanup_error:
            raise RuntimeError(
                f"Could not remove incomplete build output at {destination}; the previous build "
                f"is preserved at {backup} but could not be restored: {cleanup_error}"
            ) from publish_error
        if had_destination and backup.exists():
            try:
                retry_filesystem(
                    lambda: backup.replace(destination),
                    f"restore the previous build to {destination}",
                )
            except OSError as restore_error:
                raise RuntimeError(
                    f"Build publication failed and the previous output could not be restored; "
                    f"the previous build is preserved at {backup}: {restore_error}"
                ) from publish_error
        raise

    if had_destination and not retain_backup:
        try:
            remove_tree(backup)
        except OSError as cleanup_error:
            print(
                f"The new build is published; previous build cleanup was deferred at "
                f"{backup}: {cleanup_error}",
                file=sys.stderr,
                flush=True,
            )
