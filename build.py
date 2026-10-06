"""Build a native package from this self-contained production tree."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "ui" / "web"
BUILD = ROOT / "build" / "cargo"
PACKAGE_SUFFIXES = {".appimage", ".deb", ".dmg", ".exe", ".msi"}


def _tauri_build_command(bundles: str | None) -> list[str]:
    command = ["cargo", "tauri", "build", "--ci"]
    if bundles:
        command.extend(("--bundles", bundles))
    else:
        command.append("--no-bundle")
    return command


def publish_portable(destination: Path, release: Path, system: str) -> Path:
    """Stage executable/resources together and preserve the last successful portable build."""
    from build_desktop_engine import (
        _check_font_assets,
        _check_glyph_assets,
        _check_project_license,
        _request,
        _smoke_test,
    )

    config = json.loads((WEB / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    portable = destination / "portable"
    with tempfile.TemporaryDirectory(prefix=".portable-staging-", dir=destination) as work:
        staged = Path(work) / "portable"
        staged.mkdir()
        if system == "Linux":
            executable = staged / "usr/bin/octopus"
            resources = staged / "usr/lib" / config["productName"]
        elif system == "Windows":
            executable = staged / "octopus.exe"
            resources = staged / "lib/OctoPus"
        else:
            raise RuntimeError(f"portable output is unsupported on {system}")
        executable.parent.mkdir(parents=True, exist_ok=True)
        resources.mkdir(parents=True)
        shutil.copy2(release / executable.name, executable)
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE")
        shutil.copytree(ROOT / "build/desktop-engine/octopus-engine", resources / "engine")
        shutil.copytree(ROOT / "samples/jps_files", resources / "examples")
        shutil.copytree(ROOT / "docs", resources / "docs")
        shutil.copytree(ROOT / "src/octopus/assets/fonts", resources / "fonts")
        if not executable.is_file():
            raise RuntimeError("portable output is missing the native executable")
        bundle = resources / "engine"
        _check_font_assets(resources / "fonts")
        _check_glyph_assets(bundle)
        _smoke_test(bundle, _request("portable-render", "render", 1, {
            "name": "portable-check.jps", "code": "B: 简谱你好\nQ: 1 2 3 4 |",
            "custom_code": "", "page_config": {},
        }))
        expected = ROOT / "samples/jps_files"
        examples = resources / "examples"
        for source in expected.rglob("*"):
            if source.is_file():
                copied = examples / source.relative_to(expected)
                if not copied.is_file() or copied.read_bytes() != source.read_bytes():
                    raise RuntimeError(f"portable example missing/corrupt: {source.name}")
        for manual in sorted((ROOT / "docs").rglob("*")):
            if not manual.is_file():
                continue
            copied_manual = resources / "docs" / manual.relative_to(ROOT / "docs")
            if not copied_manual.is_file() or copied_manual.read_bytes() != manual.read_bytes():
                raise RuntimeError(f"portable user manual missing/corrupt: {manual.name}")
        _check_project_license(resources)
        # Retain the predecessor until a later build replaces it with the then-current tree.
        previous = destination / "portable.previous"
        if previous.exists():
            shutil.rmtree(previous)
        if portable.exists():
            portable.rename(previous)
        try:
            staged.rename(portable)
        except OSError:
            if previous.exists():
                previous.rename(portable)
            raise
    return portable / executable.relative_to(staged)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundles",
        help="Tauri bundle type(s); omit to build only the portable executable",
    )
    parser.add_argument("--target", help="installed Rust target triple for this host")
    args = parser.parse_args()
    if platform.system() not in {"Linux", "Windows"}:
        parser.error("portable builds currently support Linux and Windows")

    from build_desktop_engine import _check_font_assets

    _check_font_assets(ROOT / "src")

    if not (WEB / "node_modules").is_dir():
        subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "ci"], cwd=WEB, check=True)

    BUILD.mkdir(parents=True, exist_ok=True)
    command = _tauri_build_command(args.bundles)
    if args.target:
        command.extend(("--target", args.target))
    # A renamed product must not accidentally republish a stale installer.
    bundle_output = BUILD / (args.target or "") / "release/bundle"
    if bundle_output.exists():
        shutil.rmtree(bundle_output)
    subprocess.run(command, cwd=WEB, env={**os.environ, "CARGO_TARGET_DIR": str(BUILD)}, check=True)

    host = next(
        line.split(": ", 1)[1] for line in subprocess.check_output(
            ["rustc", "-vV"], text=True
        ).splitlines() if line.startswith("host: ")
    )
    triple = args.target or host
    bundles = BUILD / (args.target or "") / "release" / "bundle"
    packages = [
        path for kind in bundles.iterdir() if kind.is_dir()
        for path in kind.iterdir()
        if path.is_file() and path.suffix.lower() in PACKAGE_SUFFIXES
    ]
    if args.bundles and not packages:
        raise RuntimeError(f"Tauri created no installation packages under {bundles}")
    destination = ROOT / "dist" / triple
    destination.mkdir(parents=True, exist_ok=True)
    for package in packages:
        copied = destination / package.name
        shutil.copy2(package, copied)
        print(copied)
    print(publish_portable(destination, bundles.parent, platform.system()))


if __name__ == "__main__":
    main()
