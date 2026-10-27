from __future__ import annotations

import plistlib
import subprocess
import tempfile
from pathlib import Path


def validate_dmg(package: Path, product_name: str, identifier: str) -> None:
    """Verify a DMG and the app/resources it contains before publishing it."""
    if not package.is_file() or package.stat().st_size == 0:
        raise RuntimeError(f"macOS disk image is missing or empty: {package}")
    verified = subprocess.run(
        ["hdiutil", "verify", str(package)], capture_output=True, text=True, check=False
    )
    if verified.returncode:
        raise RuntimeError(
            f"hdiutil could not verify {package}: {verified.stderr or verified.stdout}"
        )

    with tempfile.TemporaryDirectory(prefix="octopus-dmg-check-") as temporary:
        mountpoint = Path(temporary) / "mounted"
        mountpoint.mkdir()
        attached = subprocess.run(
            [
                "hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint",
                str(mountpoint), str(package),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if attached.returncode:
            raise RuntimeError(
                f"hdiutil could not mount {package}: {attached.stderr or attached.stdout}"
            )
        try:
            app = mountpoint / f"{product_name}.app"
            info_path = app / "Contents" / "Info.plist"
            executable_directory = app / "Contents" / "MacOS"
            resources = app / "Contents" / "Resources" / "lib" / "OctoPus"
            if not info_path.is_file():
                missing_info = info_path.relative_to(mountpoint)
                raise RuntimeError(f"macOS app bundle is missing {missing_info}")
            with info_path.open("rb") as source:
                info = plistlib.load(source)
            executable = info.get("CFBundleExecutable")
            if (
                info.get("CFBundleIdentifier") != identifier
                or info.get("CFBundlePackageType") != "APPL"
            ):
                raise RuntimeError("macOS app bundle has unexpected bundle metadata")
            if not isinstance(executable, str):
                raise RuntimeError("macOS app bundle is missing its native executable")
            if not (executable_directory / executable).is_file():
                raise RuntimeError("macOS app bundle is missing its native executable")
            required_resources = (
                resources / "engine" / "octopus-engine",
                resources / "LICENSE",
                resources / "examples",
                resources / "docs",
            )
            missing = [str(path.relative_to(mountpoint)) for path in required_resources
                       if not path.exists()]
            if missing:
                raise RuntimeError(
                    "macOS app bundle is missing packaged resources: " + ", ".join(missing)
                )
            if not any((resources / "examples").rglob("*.jps")):
                raise RuntimeError("macOS app bundle has no packaged JPS examples")
            if not any(path.is_file() for path in (resources / "docs").rglob("*")):
                raise RuntimeError("macOS app bundle has no packaged manual files")
        finally:
            detached = subprocess.run(
                ["hdiutil", "detach", "-quiet", str(mountpoint)],
                capture_output=True,
                text=True,
                check=False,
            )
            if detached.returncode:
                raise RuntimeError(
                    f"hdiutil could not detach {mountpoint}: "
                    f"{detached.stderr or detached.stdout}"
                )
