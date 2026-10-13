"""Build a native package from this self-contained production tree."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from build_support import environment_with_tools, find_executable, publish_directory

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "ui" / "web"
BUILD = ROOT / "build" / "cargo"
PACKAGE_SUFFIXES = {".appimage", ".deb", ".dmg", ".exe", ".msi"}
SEMVER_VERSION = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def build_metadata(root: Path = ROOT) -> tuple[str, str, str]:
    """Return the manually assigned SemVer, product commit count, and short SHA."""
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    if git("rev-parse", "--is-shallow-repository") == "true":
        raise ValueError(
            "commit-based build numbers require full Git history; run git fetch --unshallow"
        )
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER_VERSION.fullmatch(version):
        raise ValueError(
            f"VERSION must contain a SemVer value without a leading 'v'; got {version!r}"
        )
    commit = git("rev-parse", "HEAD")
    sha = git("rev-parse", "--short", "HEAD")
    build_number = git("rev-list", "--count", commit)
    return version, build_number, sha


def _tauri_build_command(bundles: str | None) -> list[str]:
    return _tauri_build_command_for("cargo", bundles)


def _tauri_build_command_for(cargo: str, bundles: str | None) -> list[str]:
    command = [cargo, "tauri", "build", "--ci"]
    if bundles:
        command.extend(("--bundles", bundles))
    else:
        command.append("--no-bundle")
    return command


def _windows_developer_environment(environment: dict[str, str]) -> dict[str, str]:
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


def _toolchain_environment() -> tuple[dict[str, str], dict[str, str]]:
    """Resolve and validate native build tools before running expensive build steps."""
    environment = dict(os.environ)
    compiler_problem = None
    if platform.system() == "Windows":
        try:
            environment = _windows_developer_environment(environment)
        except (OSError, RuntimeError) as error:
            compiler_problem = str(error)

    required = ["node", "npm", "cargo", "rustc"]
    commands: dict[str, str] = {}
    missing = []
    for name in required:
        executable = find_executable(name, path=environment.get("PATH"))
        if executable:
            commands[name] = executable
        else:
            missing.append(name)
    if missing or compiler_problem:
        problems = []
        if missing:
            problems.append("required commands not found on PATH: " + ", ".join(missing))
        if compiler_problem:
            problems.append("Windows compiler environment: " + compiler_problem)
        raise RuntimeError(
            "Build prerequisites are incomplete:\n- " + "\n- ".join(problems)
            + "\nInstall the pinned tools listed in ENVIRONMENT.md, then rerun "
            "scripts/build_portable.py."
        )
    environment = environment_with_tools(environment, list(commands.values()))

    expected_python = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    actual_python = ".".join(map(str, sys.version_info[:2]))
    if actual_python != expected_python:
        raise RuntimeError(
            f"The production build requires Python {expected_python}; this interpreter is "
            f"{actual_python}. Run scripts/build_portable.py to use the repository environment."
        )

    expected_node = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    actual_node = subprocess.check_output(
        [commands["node"], "--version"], text=True, env=environment
    ).strip().removeprefix("v")
    version_problems = []
    if actual_node != expected_node:
        version_problems.append(f"Node.js: expected {expected_node}, found {actual_node}")

    expected_npm = (ROOT / ".npm-version").read_text(encoding="utf-8").strip()
    actual_npm = subprocess.check_output(
        [commands["npm"], "--version"], text=True, env=environment
    ).strip()
    if actual_npm != expected_npm:
        version_problems.append(f"npm: expected {expected_npm}, found {actual_npm}")

    rust_toolchain = tomllib.loads(
        (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
    )["toolchain"]["channel"]
    for name in ("cargo", "rustc"):
        actual = subprocess.check_output(
            [commands[name], "--version"], text=True, env=environment
        ).strip()
        if not re.search(rf"\b{re.escape(rust_toolchain)}\b", actual):
            version_problems.append(f"{name}: expected Rust {rust_toolchain}, found {actual}")

    tauri = subprocess.run(
        [commands["cargo"], "tauri", "--version"],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    tauri_version = "2.11.5"
    tauri_output = tauri.stdout + tauri.stderr
    if tauri.returncode != 0 or not re.search(rf"\b{tauri_version}\b", tauri_output):
        detail = tauri_output.strip()
        version_problems.append(
            f"Tauri CLI: expected {tauri_version}; install it with `cargo install tauri-cli "
            f"--version {tauri_version} --locked`{': ' + detail if detail else ''}"
        )

    if platform.system() == "Linux":
        if not find_executable("cc", path=environment.get("PATH")):
            raise RuntimeError("Linux desktop builds require a C compiler; see ENVIRONMENT.md.")
        pkg_config = find_executable("pkg-config", path=environment.get("PATH"))
        if not pkg_config:
            raise RuntimeError("Linux desktop builds require pkg-config; see ENVIRONMENT.md.")
        modules = ("webkit2gtk-4.1", "gtk+-3.0", "ayatana-appindicator3-0.1", "librsvg-2.0")
        missing_modules = [
            module for module in modules
            if subprocess.run(
                [pkg_config, "--exists", module], env=environment, check=False
            ).returncode
        ]
        if missing_modules:
            raise RuntimeError(
                "Linux desktop development libraries are missing: "
                + ", ".join(missing_modules)
                + ". Install the host packages listed in ENVIRONMENT.md before building."
            )

    if platform.system() == "Windows":
        commands["cl"] = find_executable("cl", path=environment.get("PATH")) or ""
        commands["link"] = find_executable("link", path=environment.get("PATH")) or ""
        environment = environment_with_tools(environment, [commands["cl"], commands["link"]])

    if version_problems:
        details = "\n- ".join(version_problems)
        raise RuntimeError(f"Pinned build tool versions do not match:\n- {details}")

    print(
        f"Build tools ready: Python {actual_python}, Node.js {actual_node}, npm {actual_npm}, "
        f"Rust {rust_toolchain}, Tauri CLI {tauri_version}.",
        flush=True,
    )
    return environment, commands


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
        manual_docs = ROOT / "build" / "pdfjs-assets" / "docs"
        if not manual_docs.is_dir():
            raise RuntimeError("prepared manual resources are missing")
        shutil.copytree(manual_docs, resources / "docs")
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
        for manual in sorted(manual_docs.rglob("*")):
            if not manual.is_file():
                continue
            copied_manual = resources / "docs" / manual.relative_to(manual_docs)
            if not copied_manual.is_file() or copied_manual.read_bytes() != manual.read_bytes():
                raise RuntimeError(f"portable user manual missing/corrupt: {manual.name}")
        _check_project_license(resources)
        # Retain the predecessor until a later build replaces it with the then-current tree.
        previous = destination / "portable.previous"
        publish_directory(staged, portable, previous, retain_backup=True)
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

    try:
        environment, tools = _toolchain_environment()
    except RuntimeError as error:
        parser.error(str(error))
    if platform.system() == "Windows" and platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Portable Windows builds require an x64 host and Python interpreter.")
    rust_host = next(
        line.split(": ", 1)[1]
        for line in subprocess.check_output(
            [tools["rustc"], "-vV"], text=True, env=environment
        ).splitlines()
        if line.startswith("host: ")
    )
    target_triple = args.target or rust_host
    if target_triple != rust_host:
        parser.error(
            f"This build requires the native Rust target {rust_host}; "
            f"cross-target {target_triple} is unsupported for the frozen Python engine."
        )
    environment["TAURI_ENV_TARGET_TRIPLE"] = target_triple

    from build_desktop_engine import _check_font_assets, _validate_target_triple

    _check_font_assets(ROOT / "src")
    try:
        _validate_target_triple(target_triple)
    except RuntimeError as error:
        parser.error(str(error))
    version, build_number, build_commit = build_metadata()

    if not (WEB / "node_modules").is_dir():
        subprocess.run(
            [tools["npm"], "ci", "--no-audit", "--no-fund"],
            cwd=WEB,
            env=environment,
            check=True,
        )

    BUILD.mkdir(parents=True, exist_ok=True)

    frontend_command = [tools["npm"], "run", "build", "--", "--mode", "desktop"]
    print("==> Building the desktop frontend", flush=True)
    subprocess.run(
        frontend_command,
        cwd=WEB,
        env={
            **environment,
            "VITE_APP_VERSION": version,
            "VITE_BUILD_NUMBER": f"{build_number} ({build_commit})",
        },
        check=True,
    )
    frontend_entry = ROOT / "build" / "frontend" / "index.html"
    if not frontend_entry.is_file():
        raise RuntimeError(f"Frontend build did not produce {frontend_entry}")

    engine_environment = {
        **environment,
        "VITE_APP_VERSION": version,
        "VITE_BUILD_NUMBER": f"{build_number} ({build_commit})",
    }
    engine_environment["TAURI_ENV_TARGET_TRIPLE"] = target_triple
    print("==> Building and smoke-checking the offline desktop engine", flush=True)
    subprocess.run(
        [sys.executable, str(ROOT / "build_desktop_engine.py")],
        cwd=ROOT,
        env=engine_environment,
        check=True,
    )

    version_config = BUILD / "tauri-version.json"
    version_config.write_text(
        json.dumps({"version": version, "build": {"beforeBuildCommand": ""}}),
        encoding="utf-8",
    )
    command = _tauri_build_command_for(tools["cargo"], args.bundles)
    command.extend(("--config", str(version_config)))
    if args.target:
        command.extend(("--target", args.target))
    # A renamed product must not accidentally republish a stale installer.
    bundle_output = BUILD / (args.target or "") / "release/bundle"
    if bundle_output.exists():
        shutil.rmtree(bundle_output)
    print("==> Compiling the native desktop application", flush=True)
    subprocess.run(command, cwd=WEB, env={
        **environment,
        "CARGO_TARGET_DIR": str(BUILD),
        "VITE_APP_VERSION": version,
        "VITE_BUILD_NUMBER": f"{build_number} ({build_commit})",
    }, check=True)

    triple = target_triple
    bundles = BUILD / (args.target or "") / "release" / "bundle"
    packages = [
        path for kind in bundles.iterdir() if kind.is_dir()
        for path in kind.iterdir()
        if path.is_file() and path.suffix.lower() in PACKAGE_SUFFIXES
    ] if bundles.is_dir() else []
    if args.bundles and not packages:
        raise RuntimeError(f"Tauri created no installation packages under {bundles}")
    destination = ROOT / "dist" / triple
    destination.mkdir(parents=True, exist_ok=True)
    for package in packages:
        copied = destination / package.name
        shutil.copy2(package, copied)
        print(copied)
    print(f"Version: {version}, Build: {build_number}, Commit: {build_commit}")
    print(publish_portable(destination, bundles.parent, platform.system()))


if __name__ == "__main__":
    main()
