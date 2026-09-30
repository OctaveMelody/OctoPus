"""Create this repository's locked runtime or native-build environment."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-only", action="store_true", help="skip native build tools")
    args = parser.parse_args()
    command = ["uv", "sync", "--locked", "--extra", "transcription"]
    if not args.runtime_only:
        command.extend(("--extra", "desktop-build"))
    subprocess.run(command, cwd=ROOT, check=True)
    if not args.runtime_only:
        subprocess.run(
            ["npm.cmd" if os.name == "nt" else "npm", "ci", "--no-audit", "--no-fund"],
            cwd=ROOT / "ui" / "web",
            check=True,
        )
        subprocess.run(["cargo", "--version"], cwd=ROOT, check=True)
    print(f"Locked Python environment ready: {ROOT / '.venv'}")


if __name__ == "__main__":
    main()
