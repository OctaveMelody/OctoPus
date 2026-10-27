"""Resolve one immutable source commit for a desktop package workflow run."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _commit(repository: Path, ref: str) -> str | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{ref}^{{commit}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _published_releases(repository_name: str) -> list[dict[str, Any]]:
    if not repository_name:
        raise RuntimeError("GITHUB_REPOSITORY is required to list published releases")
    result = subprocess.run(
        [
            "gh",
            "release",
            "list",
            "--repo",
            repository_name,
            "--limit",
            "1000",
            "--exclude-drafts",
            "--order",
            "desc",
            "--json",
            "tagName,publishedAt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "gh release list failed")
    releases = json.loads(result.stdout)
    if not isinstance(releases, list):
        raise RuntimeError("gh release list returned an invalid response")
    return releases


def resolve_source(
    repository: Path,
    selected_sha: str,
    *,
    release_event_tag: str = "",
    source_ref: str = "",
    releases: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    selected_head = _git(repository, "rev-parse", "HEAD")
    selected_commit = _commit(repository, selected_sha)
    if not selected_commit or selected_commit != selected_head:
        raise RuntimeError(f"Selected SHA must resolve to the checked-out HEAD {selected_head}.")

    if release_event_tag:
        source_sha = _commit(repository, f"refs/tags/{release_event_tag}")
        if not source_sha:
            raise RuntimeError(f"Release event tag is missing from the checkout: {release_event_tag}")
        if source_sha != selected_head:
            raise RuntimeError(
                f"Release event tag {release_event_tag} does not point to selected HEAD {selected_head}."
            )
        return source_sha, f"published release tag {release_event_tag}"

    if source_ref:
        branch = source_ref.removeprefix("origin/")
        for candidate in (
            f"refs/remotes/origin/{branch}",
            f"refs/tags/{source_ref}",
            source_ref,
        ):
            source_sha = _commit(repository, candidate)
            if source_sha:
                return source_sha, f"requested ref {source_ref}"
        raise RuntimeError(f"Requested source ref does not resolve to a commit: {source_ref}")

    if releases is None:
        releases = _published_releases(os.environ.get("GITHUB_REPOSITORY", ""))

    best: tuple[int, str, str] | None = None
    # Match jq sort_by(... ) | reverse, including reversing equal-date entries.
    for release in reversed(sorted(releases, key=lambda item: item.get("publishedAt") or "")):
        tag = release.get("tagName")
        if not isinstance(tag, str) or not tag:
            continue
        candidate_sha = _commit(repository, f"refs/tags/{tag}")
        if not candidate_sha:
            continue
        if candidate_sha == selected_head:
            return candidate_sha, f"nearest published release tag {tag}"
        ancestor = subprocess.run(
            ["git", "-C", str(repository), "merge-base", "--is-ancestor", candidate_sha, selected_head],
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestor.returncode:
            continue
        distance = int(_git(repository, "rev-list", "--count", f"{candidate_sha}..{selected_head}"))
        if best is None or distance < best[0]:
            best = (distance, tag, candidate_sha)

    if best is None:
        raise RuntimeError(
            f"No published release tag matches {selected_head} or precedes it in its history."
        )
    return best[2], f"nearest published release tag {best[1]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--selected-sha", required=True)
    parser.add_argument("--release-event-tag", default="")
    parser.add_argument("--source-ref", default="")
    args = parser.parse_args(argv)

    try:
        source_sha, description = resolve_source(
            args.repository.resolve(),
            args.selected_sha,
            release_event_tag=args.release_event_tag,
            source_ref=args.source_ref,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"source_sha={source_sha}\n")
    else:
        print(f"source_sha={source_sha}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"### Package source\nUsing {description} at `{source_sha}`.\n")
            if not args.release_event_tag and not args.source_ref and source_sha != args.selected_sha:
                stream.write(
                    "The selected commit was untagged; this run fell back to the nearest earlier "
                    "published release tag.\n"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
