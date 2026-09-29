"""Build a native package from this self-contained production tree."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "ui" / "web"
BUILD = ROOT / "build" / "cargo"
PACKAGE_SUFFIXES = {".appimage", ".deb", ".dmg", ".exe", ".msi"}


def main() -> None:
    default_bundle = {"Linux": "deb", "Windows": "nsis"}.get(platform.system())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundles", default=default_bundle, help="Tauri bundle type(s)")
    parser.add_argument("--target", help="installed Rust target triple for this host")
    args = parser.parse_args()
    if not args.bundles:
        parser.error("native packaging currently supports Linux and Windows")

    if not (WEB / "node_modules").is_dir():
        subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "ci"], cwd=WEB, check=True)

    BUILD.mkdir(parents=True, exist_ok=True)
    command = ["cargo", "tauri", "build", "--ci", "--bundles", args.bundles]
    if args.target:
        command.extend(("--target", args.target))
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
    if not packages:
        raise RuntimeError(f"Tauri created no installation packages under {bundles}")
    destination = ROOT / "dist" / triple
    destination.mkdir(parents=True, exist_ok=True)
    for package in packages:
        copied = destination / package.name
        shutil.copy2(package, copied)
        print(copied)


if __name__ == "__main__":
    main()
