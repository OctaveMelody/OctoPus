#!/usr/bin/env python3
"""Exercise the worker from a built Windows or Linux package on a CI runner."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def extract_portable(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in item.filename:
                raise RuntimeError(f"unsafe portable ZIP entry: {item.filename}")
        zipped.extractall(destination)


def smoke(package: Path, kind: str, work: Path, source_root: Path = ROOT) -> None:
    if not package.is_file() or not package.stat().st_size:
        raise RuntimeError(f"package is missing or empty: {package}")
    work.mkdir(parents=True, exist_ok=True)
    package = package.resolve()
    if kind == "linux-appimage":
        subprocess.run([str(package), "--appimage-extract"], cwd=work, check=True,
                       stdout=subprocess.DEVNULL, timeout=180)
        root = work / "squashfs-root"
        executable = root / "usr/bin/octopus"
        engine = root / "usr/lib/OctoPus/engine"
    elif kind == "windows-portable":
        root = work / "portable"
        extract_portable(package, root)
        executable = root / "octopus.exe"
        engine = root / "lib/OctoPus/engine"
    elif kind == "windows-installer":
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("installer smoke checks require an isolated GitHub Actions runner")
        root = (work / "installed").resolve()
        # NSIS requires /D to be last and unquoted, even when its path contains spaces.
        command = f'"{package}" /S /NS /D={root}'
        subprocess.run(command, check=True, timeout=180)
        executable = root / "octopus.exe"
        engine = root / "lib/OctoPus/engine"
    else:
        raise ValueError(f"unsupported package type: {kind}")

    if not executable.is_file():
        raise RuntimeError(f"package is missing its desktop executable: {executable}")
    worker_name = "octopus-engine" if kind == "linux-appimage" else "octopus-engine.exe"
    if not (engine / worker_name).is_file():
        raise RuntimeError(f"package is missing its worker executable: {engine / worker_name}")
    sys.path.insert(0, str(source_root.resolve()))
    from build_desktop_engine import _request, _smoke_test

    _smoke_test(engine, _request("packaged-render", "render", 1, {
        "name": "package-check.jps", "code": "B: 简谱你好\nQ: 1 2 3 4 |",
        "custom_code": "", "page_config": {},
    }))
    print(f"Packaged worker smoke check passed: {package}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("linux-appimage", "windows-installer", "windows-portable"))
    parser.add_argument("package", type=Path)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    expected = "Linux" if args.kind == "linux-appimage" else "Windows"
    if platform.system() != expected:
        parser.error(f"{args.kind} smoke checks require {expected}")
    with tempfile.TemporaryDirectory(prefix="octopus-package-smoke-") as temporary:
        smoke(args.package, args.kind, Path(temporary), args.source_root)


if __name__ == "__main__":
    main()
