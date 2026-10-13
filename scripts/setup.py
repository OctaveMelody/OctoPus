"""Create this repository's locked runtime or native-build environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_support import environment_with_tools, find_executable  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-only", action="store_true", help="skip native build tools")
    args = parser.parse_args()

    uv = find_executable("uv")
    if not uv:
        raise RuntimeError("uv was not found on PATH; install uv and rerun this setup script.")
    tools = [uv]
    npm = node = cargo = None
    if not args.runtime_only:
        node = find_executable("node")
        npm = find_executable("npm")
        cargo = find_executable("cargo")
        missing = [
            name for name, value in (("node", node), ("npm", npm), ("cargo", cargo))
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Native setup requires these tools on PATH: " + ", ".join(missing)
                + ". Install the pinned host tools listed in ENVIRONMENT.md first."
            )
        tools.extend((node, npm, cargo))
    environment = environment_with_tools(dict(os.environ), tools)
    if not args.runtime_only:
        expected_node = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
        actual_node = subprocess.check_output(
            [node, "--version"], text=True, env=environment
        ).strip().removeprefix("v")
        if actual_node != expected_node:
            raise RuntimeError(
                f"Node.js {expected_node} is pinned for this environment; found {actual_node}."
            )
        expected_npm = (ROOT / ".npm-version").read_text(encoding="utf-8").strip()
        actual_npm = subprocess.check_output(
            [npm, "--version"], text=True, env=environment
        ).strip()
        if actual_npm != expected_npm:
            raise RuntimeError(
                f"npm {expected_npm} is pinned for this environment; found {actual_npm}."
            )

    command = [uv, "sync", "--locked", "--extra", "transcription"]
    if not args.runtime_only:
        command.extend(("--extra", "desktop-build"))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    if not args.runtime_only:
        subprocess.run(
            [npm, "ci", "--no-audit", "--no-fund"],
            cwd=ROOT / "ui" / "web",
            env=environment,
            check=True,
        )
        subprocess.run([cargo, "--version"], cwd=ROOT, env=environment, check=True)
    print(f"Locked Python environment ready: {ROOT / '.venv'}")


if __name__ == "__main__":
    main()
