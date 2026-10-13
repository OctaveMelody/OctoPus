"""Build the production portable from any current working directory."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_support import environment_with_tools, find_executable  # noqa: E402


def main() -> int:
    if os.name == "nt":
        python = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        python = ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        setup = ROOT / "scripts" / "setup.py"
        python_command = "py" if os.name == "nt" else "python3"
        raise SystemExit(
            f"Production build environment is missing: {python}\n"
            f"Create the locked environment first with: {python_command} {setup}"
        )
    environment = dict(os.environ)
    tool_paths = [
        find_executable(name, path=environment.get("PATH"))
        for name in ("node", "npm", "cargo", "rustc", "uv")
    ]
    environment = environment_with_tools(environment, tool_paths)
    result = subprocess.run(
        [str(python), str(ROOT / "build.py"), *sys.argv[1:]],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
