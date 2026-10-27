from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path


def developer_environment(
    environment: dict[str, str], find_executable: Callable[..., str | None]
) -> dict[str, str]:
    """Load an installed Visual Studio x64 toolchain when this shell lacks one."""
    if (
        find_executable("cl", path=environment.get("PATH"))
        and find_executable("link", path=environment.get("PATH"))
        and environment.get("INCLUDE")
        and environment.get("LIB")
        and environment.get("VSCMD_ARG_TGT_ARCH", "").lower() == "x64"
    ):
        return environment

    program_files = (
        environment.get("PROGRAMFILES(X86)") or environment.get("ProgramFiles(x86)")
    )
    vswhere = find_executable("vswhere", path=environment.get("PATH"))
    if not vswhere and program_files:
        candidate = Path(program_files) / "Microsoft Visual Studio/Installer/vswhere.exe"
        if candidate.is_file():
            vswhere = str(candidate)
    if not vswhere:
        raise RuntimeError(
            "MSVC tools are not on PATH and vswhere could not locate Visual Studio. Install "
            "Visual Studio 2022 Build Tools with the Desktop development with C++ workload."
        )

    installation = subprocess.run(
        [
            vswhere,
            "-latest",
            "-products",
            "*",
            "-version",
            "[17.0,18.0)",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    install_path = installation.stdout.strip()
    if installation.returncode != 0 or not install_path:
        raise RuntimeError(
            "Visual Studio 2022 C++ Build Tools were not found. Install the Desktop "
            "development with C++ workload and a Windows SDK."
        )
    developer_prompt = Path(install_path) / "Common7/Tools/VsDevCmd.bat"
    if not developer_prompt.is_file():
        raise RuntimeError(f"Visual Studio developer environment is missing: {developer_prompt}")

    with tempfile.TemporaryDirectory(prefix="octopus-vs-env-") as work:
        environment_script = Path(work) / "load-environment.cmd"
        environment_script.write_text(
            "@echo off\r\n"
            f'call "{developer_prompt}" -arch=x64 -host_arch=x64 >nul\r\n'
            "if errorlevel 1 exit /b %errorlevel%\r\n"
            "set\r\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", environment_script.name],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "Could not initialize the Visual Studio x64 build environment: "
            + (completed.stderr or completed.stdout)[-2000:]
        )
    result = dict(environment)
    for line in completed.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator and name and not name.startswith("="):
            result[name.upper() if os.name == "nt" else name] = value
    if (
        not find_executable("cl", path=result.get("PATH"))
        or not find_executable("link", path=result.get("PATH"))
        or not result.get("INCLUDE")
        or not result.get("LIB")
    ):
        raise RuntimeError("Visual Studio did not expose cl.exe and link.exe for x64 builds")
    print("Initialized Visual Studio 2022 x64 build tools.", flush=True)
    return result
