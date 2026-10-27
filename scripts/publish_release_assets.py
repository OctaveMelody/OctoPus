"""Upload package files only when their source matches the destination release tag."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def _commit(repository: Path, revision: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{revision}^{{commit}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Git revision does not resolve: {revision}")
    return result.stdout.strip()


def publish(
    repository: Path,
    repository_name: str,
    release_tag: str,
    source_sha: str,
    files_directory: Path,
) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", source_sha):
        raise RuntimeError(f"Package source is not an immutable commit SHA: {source_sha}")

    tag_sha = _commit(repository, f"refs/tags/{release_tag}")
    source_commit = _commit(repository, source_sha)
    if tag_sha != source_commit:
        raise RuntimeError(
            f"Release tag {release_tag} resolves to {tag_sha}, but package source is {source_commit}."
        )

    if not files_directory.is_dir():
        raise RuntimeError(f"Package download directory does not exist: {files_directory}")
    files = sorted(path for path in files_directory.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError("No package files were downloaded")
    empty_files = [path for path in files if path.stat().st_size == 0]
    if empty_files:
        raise RuntimeError("Package files must not be empty: " + ", ".join(map(str, empty_files)))

    if not repository_name:
        raise RuntimeError("GITHUB_REPOSITORY is required to upload release assets")
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            release_tag,
            *(str(path) for path in files),
            "--repo",
            repository_name,
            "--clobber",
        ],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--files-directory", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--repository-name", default=os.environ.get("GITHUB_REPOSITORY", "")
    )
    args = parser.parse_args(argv)

    try:
        publish(
            args.repository.resolve(),
            args.repository_name,
            args.release_tag,
            args.source_sha,
            args.files_directory.resolve(),
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
