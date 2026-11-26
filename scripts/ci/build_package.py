#!/usr/bin/env python3
"""Run the native desktop package checks used by GitHub Actions."""

from __future__ import annotations

import argparse
import os
import platform
import stat
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

TOOL_ROOT = Path(__file__).resolve().parents[2]


class PackageSpec(TypedDict):
    system: str
    machines: set[str]
    build_args: tuple[str, ...]
    filename: str


PACKAGES: dict[str, PackageSpec] = {
    "linux-appimage": {
        "system": "Linux",
        "machines": {"x86_64", "amd64"},
        "build_args": ("--bundles", "appimage"),
        "filename": "OctoPus_{version}_x64_linux.AppImage",
    },
    "windows-installer": {
        "system": "Windows",
        "machines": {"amd64", "x86_64"},
        "build_args": ("--bundles", "nsis", "--no-portable-zip"),
        "filename": "OctoPus_{version}_x64_win64_setup.exe",
    },
    "windows-portable": {
        "system": "Windows",
        "machines": {"amd64", "x86_64"},
        "build_args": (),
        "filename": "OctoPus_{version}_x64_win64_portable.zip",
    },
    "macos-dmg": {
        "system": "Darwin",
        "machines": {"arm64", "aarch64"},
        "build_args": ("--bundles", "dmg"),
        "filename": "OctoPus_{version}_arm64_macos.dmg",
    },
}


def _build_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.setdefault("UV_PROJECT_ENVIRONMENT", str(root / ".venv"))
    environment["VIRTUAL_ENV"] = ""
    environment.setdefault("UV_PYTHON", "3.12")
    environment.setdefault("RUSTUP_TOOLCHAIN", "1.98.1")
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    environment.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    environment.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")
    environment.setdefault("CARGO_INCREMENTAL", "0")
    return environment


def _run(command: list[str], cwd: Path, environment: dict[str, str]) -> None:
    print(f"Running: {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def _uv_command(root: Path, *arguments: str) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        str(root),
        "--locked",
        "--extra",
        "desktop-build",
        "--extra",
        "transcription",
        *arguments,
    ]


def _validate_host(package: str) -> None:
    specification = PACKAGES[package]
    system = platform.system()
    machine = platform.machine().lower()
    if system != specification["system"] or machine not in specification["machines"]:
        expected = specification["system"]
        expected_machine = " or ".join(sorted(specification["machines"]))
        raise RuntimeError(
            f"{package} requires {expected} on {expected_machine}; found {system} on {machine}"
        )


def _find_artifact(root: Path, package: str) -> Path:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    filename = PACKAGES[package]["filename"].format(version=version)
    matches = sorted(path for path in (root / "dist").glob(f"*/{filename}") if path.is_file())
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {package} artifact named {filename}, found {len(matches)}"
        )
    return matches[0]


def _write_github_outputs(root: Path, artifact: Path) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    relative_path = artifact.relative_to(root).as_posix()
    with Path(output).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"path={relative_path}\n")
        stream.write(f"name={artifact.stem}\n")


def _remove_readonly(func, path, exc_info_or_exc):  # pragma: no cover - Windows only
    """Git marks pack/idx files read-only; clear the bit so rmtree can delete them."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_remove_readonly)
    else:  # pragma: no cover - Python < 3.12
        shutil.rmtree(path, onerror=_remove_readonly)


def _stage_workflow_tools(root: Path, package: str) -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("--stage-workflow-tools is reserved for GitHub Actions")
    helper_root = Path(__file__).resolve().parents[2]
    if helper_root.name != "workflow-source" or helper_root.parent.resolve() != root:
        raise RuntimeError(
            "--stage-workflow-tools requires a workflow-source checkout beside package source"
        )
    smoke_source = helper_root / "scripts" / "smoke_package.py"
    if not smoke_source.is_file():
        raise RuntimeError(f"workflow smoke checker is missing: {smoke_source}")
    runner_temp = os.environ.get("RUNNER_TEMP")
    if not runner_temp:
        raise RuntimeError("RUNNER_TEMP is required to stage workflow tools")

    tools_root = Path(runner_temp) / "octopus-ci"
    staged_driver = tools_root / "scripts" / "ci" / "build_package.py"
    staged_smoke = tools_root / "scripts" / "smoke_package.py"
    staged_driver.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), staged_driver)
    shutil.copy2(smoke_source, staged_smoke)

    # The source digest must not see this nested Git checkout as a build input.
    _rmtree(helper_root)
    command = [
        sys.executable,
        str(staged_driver),
        "--package",
        package,
        "--source-root",
        str(root),
        "--tools-root",
        str(tools_root),
    ]
    return subprocess.run(command, cwd=root, check=False).returncode


def build_package(package: str, root: Path, tools_root: Path) -> None:
    _validate_host(package)
    environment = _build_environment(root)
    format_command = ["cargo", "fmt", "--all"]
    if environment.get("GITHUB_ACTIONS") == "true":
        format_command.append("--check")
    _run(
        format_command,
        root / "ui",
        environment,
    )
    _run(
        [
            "uv",
            "sync",
            "--project",
            str(root),
            "--locked",
            "--extra",
            "desktop-build",
            "--extra",
            "transcription",
        ],
        root,
        environment,
    )
    _run(
        _uv_command(root, "python", "scripts/prepare_ocr_models.py"),
        root,
        environment,
    )
    _run(
        _uv_command(root, "python", "build.py", *PACKAGES[package]["build_args"]),
        root,
        environment,
    )
    _run(
        ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"],
        root / "ui",
        environment,
    )
    _run(["cargo", "test", "--workspace"], root / "ui", environment)

    artifact = _find_artifact(root, package)
    if package == "macos-dmg":
        print(
            "The macOS DMG build performs bundle validation; no package smoke step is configured."
        )
    elif package == "windows-installer" and environment.get("GITHUB_ACTIONS") != "true":
        print(
            "Skipping installer-install smoke locally; it is restricted to an isolated "
            "GitHub Actions runner. The installer build and Rust checks passed."
        )
    else:
        smoke_script = tools_root / "scripts" / "smoke_package.py"
        if not smoke_script.is_file():
            raise RuntimeError(f"package smoke checker is missing: {smoke_script}")
        _run(
            _uv_command(
                root,
                "python",
                str(smoke_script),
                package,
                str(artifact),
                "--source-root",
                str(root),
            ),
            root,
            environment,
        )
    _write_github_outputs(root, artifact)
    print(f"Package checks passed: {artifact}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, choices=tuple(PACKAGES))
    parser.add_argument("--source-root", type=Path, default=TOOL_ROOT)
    parser.add_argument("--tools-root", type=Path, default=TOOL_ROOT)
    parser.add_argument(
        "--stage-workflow-tools",
        action="store_true",
        help="stage CI helpers outside workflow-source before hashing",
    )
    args = parser.parse_args()
    root = args.source_root.resolve()

    try:
        if args.stage_workflow_tools:
            return _stage_workflow_tools(root, args.package)
        build_package(args.package, root, args.tools_root.resolve())
    except (OSError, RuntimeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
