"""Build a native package from this self-contained production tree."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

from build_support import (
    environment_with_tools,
    find_executable,
    publish_directory,
    remove_tree,
    retry_filesystem,
)

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "ui" / "web"
BUILD = ROOT / "build" / "cargo"
PACKAGE_SUFFIXES = {".appimage", ".dmg", ".exe"}
ARTIFACT_ARCHES = {"x86_64": "x64", "aarch64": "arm64"}
APPIMAGE_RUNTIME_ARCHES = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "i686": "i386",
    "armv7": "armhf",
}
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


def _artifact_filename(
    version: str, target_triple: str, system: str, purpose: str | None
) -> str:
    try:
        arch = ARTIFACT_ARCHES[target_triple.split("-", 1)[0]]
    except KeyError as error:
        raise RuntimeError(f"artifact naming does not support {target_triple}") from error
    if system == "Windows" and purpose == "portable":
        os_name, extension = "win64", ".zip"
    elif system == "Windows" and purpose == "setup":
        os_name, extension = "win64", ".exe"
    elif system == "Linux" and purpose is None:
        os_name, extension = "linux", ".AppImage"
    elif system == "Darwin" and purpose is None:
        os_name, extension = "macos", ".dmg"
    else:
        raise RuntimeError(f"unsupported artifact type for {system}: {purpose!r}")
    purpose_suffix = f"_{purpose}" if purpose else ""
    return f"OctoPus_{version}_{arch}_{os_name}{purpose_suffix}{extension}"


def _validate_macos_dmg(package: Path, product_name: str, identifier: str) -> None:
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


def _create_portable_zip(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"portable archive was not created: {destination}")
    return destination


def _appimage_paths(
    target: str | None, version: str, target_triple: str
) -> tuple[Path, Path, Path, Path]:
    config = json.loads((WEB / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    product_name = config["productName"]
    bundle_dir = BUILD / (target or "") / "release/bundle/appimage"
    app_dir = bundle_dir / f"{product_name}.AppDir"
    package = bundle_dir / _artifact_filename(version, target_triple, "Linux", None)
    identity = bundle_dir / ".octopus-build.json"
    return bundle_dir, app_dir, package, identity


def _prepare_appimage_app_dir(app_dir: Path) -> None:
    from build_desktop_engine import _check_font_assets

    required = (
        app_dir / "AppRun",
        app_dir / "AppRun.wrapped",
        app_dir / "apprun-hooks/linuxdeploy-plugin-gtk.sh",
        app_dir / "OctoPus.desktop",
        app_dir / ".DirIcon",
        app_dir / "usr/bin/octopus",
        app_dir / "usr/share/applications/OctoPus.desktop",
        app_dir / "usr/share/icons/hicolor/512x512/apps/octopus.png",
        app_dir / "usr/lib/OctoPus/LICENSE",
        app_dir / "usr/lib/OctoPus/engine/octopus-engine",
        app_dir / "usr/lib/OctoPus/examples",
        app_dir / "usr/lib/OctoPus/docs",
        app_dir / "usr/lib/OctoPus/fonts",
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "The staged AppImage directory is incomplete: "
            + ", ".join(path.relative_to(app_dir).as_posix() for path in missing)
        )
    _check_font_assets(app_dir / "usr/lib/OctoPus/fonts")
    for helper in (
        "WebKitNetworkProcess",
        "WebKitWebProcess",
        "injected-bundle/libwebkit2gtkinjectedbundle.so",
    ):
        if not any(path.is_file() for path in app_dir.glob(f"usr/**/webkit2gtk-4.1/{helper}")):
            raise RuntimeError(f"The staged AppImage is missing WebKit runtime file: {helper}")
    ldd = find_executable("ldd")
    if ldd:
        dependencies = subprocess.run(
            [ldd, str(app_dir / "usr/bin/octopus")],
            capture_output=True,
            text=True,
            check=False,
        )
        missing_dependencies = [
            line.strip() for line in dependencies.stdout.splitlines() if "not found" in line
        ]
        if dependencies.returncode or missing_dependencies:
            raise RuntimeError(
                "The staged AppImage has unresolved native dependencies: "
                + "; ".join(missing_dependencies or [dependencies.stderr.strip()])
            )

    icon_alias = app_dir / "octopus.png"
    icon_target = "usr/share/icons/hicolor/512x512/apps/octopus.png"
    if icon_alias.is_symlink():
        if os.readlink(icon_alias) != icon_target:
            raise RuntimeError(f"unexpected AppImage icon alias: {icon_alias}")
    elif not icon_alias.exists():
        icon_alias.symlink_to(icon_target)
    elif not icon_alias.is_file():
        raise RuntimeError(f"unexpected AppImage icon entry: {icon_alias}")


def _run_appimage_build(command: list[str], environment: dict[str, str]) -> None:
    """Retain linuxdeploy's diagnostics so failure recovery can verify its deployment phase."""
    log_path = BUILD / "appimage-build.log"
    print(f"AppImage deployment diagnostics: {log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            command, cwd=WEB, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                progress = line.lstrip().startswith((
                    "Info ", "Bundling ", "Compiling ", "Finished ", "Built application",
                    "Error ", "error:", "warning:",
                ))
                if progress or "ERROR:" in line or "Failed to download runtime" in line:
                    print(line, end="", flush=True)
            returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(
            returncode, command, output=log_path.read_text(encoding="utf-8")
        )


def _appimage_runtime_download_failed(output: object, app_dir: Path) -> bool:
    if not isinstance(output, str):
        return False
    packaging_started = any(
        "Running command:" in line and "appimagetool" in line and str(app_dir) in line
        for line in output.splitlines()
    )
    return packaging_started and "Failed to download runtime file" in output


def _cached_appimage_tooling(target_triple: str) -> tuple[Path, Path]:
    try:
        runtime_arch = APPIMAGE_RUNTIME_ARCHES[target_triple.split("-", 1)[0]]
    except KeyError as error:
        raise RuntimeError(f"AppImage fallback does not support {target_triple}") from error
    appimagetool = ROOT / "build/cache/squashfs-root/usr/bin/appimagetool"
    runtime = ROOT / f"build/cache/tauri/runtime-{runtime_arch}"
    missing = [path for path in (appimagetool, runtime) if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Cached AppImage fallback tools are missing: "
            + ", ".join(str(path) for path in missing)
        )
    return appimagetool, runtime


def _package_appimage(app_dir: Path, package: Path, target_triple: str) -> Path:
    _prepare_appimage_app_dir(app_dir)
    appimagetool, runtime = _cached_appimage_tooling(target_triple)
    package.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".appimage-package-", dir=package.parent) as work:
        staged = Path(work) / package.name
        subprocess.run(
            [
                str(appimagetool),
                "--no-appstream",
                "--runtime-file",
                str(runtime),
                str(app_dir),
                str(staged),
            ],
            check=True,
        )
        if not staged.is_file() or staged.stat().st_size == 0:
            raise RuntimeError(f"appimagetool did not create {staged}")
        os.replace(staged, package)
    return package


def _write_appimage_identity(
    identity_path: Path, version: str, build_number: str, target_triple: str
) -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    identity_path.write_text(
        json.dumps(
            {
                "version": version,
                "build": build_number,
                "commit": commit,
                "target": target_triple,
                "deployment_complete": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _package_staged_appimage(target: str | None) -> Path:
    if platform.system() != "Linux":
        raise RuntimeError("staged AppImage packaging is supported on Linux only")
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("the cached AppImage runtime is available for Linux x86_64 only")
    version, _, _ = build_metadata()
    bundle_dir = BUILD / (target or "") / "release/bundle/appimage"
    identity_path = bundle_dir / ".octopus-build.json"
    if not identity_path.is_file():
        raise RuntimeError(
            f"No failed AppImage build is staged at {bundle_dir}; run "
            "build.py --bundles appimage first"
        )
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if not isinstance(identity, dict):
        raise RuntimeError(f"Invalid staged AppImage identity: {identity_path}")
    if identity.get("deployment_complete") is not True:
        raise RuntimeError("No verified complete AppImage deployment is staged; run a full build")
    current_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if (
        identity.get("version") != version
        or identity.get("commit") != current_commit
        or (target and identity.get("target") != target)
        or identity.get("target") != "x86_64-unknown-linux-gnu"
    ):
        raise RuntimeError("The staged AppImage belongs to a different production revision")
    _, app_dir, package, _ = _appimage_paths(target, version, identity["target"])
    destination = ROOT / "dist" / identity["target"] / package.name
    return _package_appimage(app_dir, destination, identity["target"])


def _linux_appimage_environment(
    environment: dict[str, str], target_triple: str
) -> dict[str, str]:
    result = dict(environment)
    runtime_arch = APPIMAGE_RUNTIME_ARCHES.get(target_triple.split("-", 1)[0])
    runtime = ROOT / f"build/cache/tauri/runtime-{runtime_arch}" if runtime_arch else None
    if runtime and runtime.is_file() and not result.get("LDAI_RUNTIME_FILE"):
        result["LDAI_RUNTIME_FILE"] = str(runtime)
    shapely_libraries = (
        ROOT / "build/desktop-engine/octopus-engine/_internal/shapely.libs"
    )
    if shapely_libraries.is_dir():
        paths = [str(shapely_libraries)]
        paths.extend(
            path for path in result.get("LD_LIBRARY_PATH", "").split(os.pathsep)
            if path and path != str(shapely_libraries)
        )
        result["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
    return result


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


def publish_portable(
    destination: Path,
    release: Path,
    system: str,
    portable_archive_name: str | None = None,
) -> Path:
    """Stage executable/resources together and preserve the last successful portable build."""
    from build_desktop_engine import (
        _check_font_assets,
        _check_glyph_assets,
        _check_no_application_font_assets,
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
        if not executable.is_file():
            raise RuntimeError("portable output is missing the native executable")
        bundle = resources / "engine"
        if system == "Linux":
            shutil.copytree(ROOT / "src/octopus/assets/fonts", resources / "fonts")
            _check_font_assets(resources / "fonts")
        else:
            _check_no_application_font_assets(staged)
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
        staged_archive = None
        if portable_archive_name:
            staged_archive = _create_portable_zip(
                staged, Path(work) / portable_archive_name
            )
        # Retain the predecessor until a later build replaces it with the then-current tree.
        previous = destination / "portable.previous"
        had_portable = portable.exists()
        publish_directory(staged, portable, previous, retain_backup=True)
        if staged_archive:
            archive = destination / staged_archive.name
            try:
                retry_filesystem(
                    lambda: os.replace(staged_archive, archive), f"publish portable ZIP {archive}"
                )
            except OSError as archive_error:
                try:
                    if had_portable:
                        publish_directory(
                            previous, portable, Path(work) / "failed-portable", retain_backup=False
                        )
                    else:
                        remove_tree(portable)
                except (OSError, RuntimeError) as rollback_error:
                    recovery = (
                        f"The previous directory is preserved at {previous}."
                        if had_portable else "There was no previous portable directory."
                    )
                    raise RuntimeError(
                        f"Portable ZIP publication failed and directory rollback failed: "
                        f"{rollback_error}. {recovery}"
                    ) from archive_error
                raise RuntimeError(
                    f"Could not publish portable ZIP {archive}; previous portable output restored."
                ) from archive_error
    return portable / executable.relative_to(staged)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundles",
        help="Tauri bundle type(s); omit to build only the portable executable",
    )
    parser.add_argument("--target", help="installed Rust target triple for this host")
    parser.add_argument(
        "--package-appimage-only",
        action="store_true",
        help="finalize an AppDir left by a failed AppImage build without recompiling",
    )
    parser.add_argument(
        "--no-portable-zip",
        action="store_true",
        help="validate the portable tree without creating the Windows portable ZIP",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="enable Cargo incremental compilation for faster local rebuilds",
    )
    args = parser.parse_args()
    requested_bundles = {
        bundle.strip() for bundle in (args.bundles or "").split(",") if bundle.strip()
    }
    allowed_bundles = (
        {"appimage"} if platform.system() == "Linux"
        else {"nsis"} if platform.system() == "Windows"
        else {"dmg"} if platform.system() == "Darwin"
        else set()
    )
    unsupported_bundles = requested_bundles - allowed_bundles
    if unsupported_bundles:
        parser.error(
            "supported package types are Linux appimage, Windows nsis, and macOS dmg; "
            f"unsupported: {', '.join(sorted(unsupported_bundles))}"
        )
    if args.package_appimage_only:
        if args.bundles or args.incremental or args.no_portable_zip:
            parser.error("--package-appimage-only cannot be combined with build options")
        try:
            print(_package_staged_appimage(args.target))
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
            parser.error(str(error))
        return
    if platform.system() not in {"Linux", "Windows", "Darwin"}:
        parser.error("desktop builds currently support Linux, Windows, and macOS")

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

    frontend_command = [tools["npm"], "run", "build:desktop:frontend"]
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
    from build_desktop_engine import _check_no_application_font_assets

    _check_no_application_font_assets(BUILD / "frontend")

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
    version_configuration: dict[str, object] = {
        "version": version,
        "build": {"beforeBuildCommand": ""},
    }
    if platform.system() == "Darwin":
        icon_output = BUILD / "macos-icons"
        if icon_output.exists():
            shutil.rmtree(icon_output)
        icon_output.mkdir(parents=True)
        subprocess.run(
            [
                tools["cargo"], "tauri", "icon", str(WEB / "src-tauri/icons/icon.png"),
                "--output", str(icon_output),
            ],
            cwd=WEB,
            env=environment,
            check=True,
        )
        if not (icon_output / "icon.icns").is_file():
            raise RuntimeError("Tauri did not generate the required macOS icon.icns")
    version_config.write_text(json.dumps(version_configuration), encoding="utf-8")
    command = _tauri_build_command_for(tools["cargo"], args.bundles)
    command.extend(("--config", str(version_config)))
    if args.target:
        command.extend(("--target", args.target))
    # A renamed product must not accidentally republish a stale installer.
    bundle_output = BUILD / (args.target or "") / "release/bundle"
    if bundle_output.exists():
        shutil.rmtree(bundle_output)
    print("==> Compiling the native desktop application", flush=True)
    native_environment = {
        **environment,
        "CARGO_TARGET_DIR": str(BUILD),
        "VITE_APP_VERSION": version,
        "VITE_BUILD_NUMBER": f"{build_number} ({build_commit})",
    }
    if args.incremental:
        native_environment["CARGO_INCREMENTAL"] = "1"
    appimage_fallback = platform.system() == "Linux" and requested_bundles == {"appimage"}
    if appimage_fallback:
        native_environment = _linux_appimage_environment(native_environment, target_triple)
        # Two verbose flags make Tauri retain linuxdeploy stderr, including the finalizer phase.
        command.extend(("--verbose", "--verbose"))
    try:
        if appimage_fallback:
            _run_appimage_build(command, native_environment)
        else:
            subprocess.run(command, cwd=WEB, env=native_environment, check=True)
    except subprocess.CalledProcessError as error:
        if not appimage_fallback:
            raise
        _, app_dir, package, identity_path = _appimage_paths(
            args.target, version, target_triple
        )
        if not app_dir.is_dir() or not _appimage_runtime_download_failed(error.output, app_dir):
            raise
        _prepare_appimage_app_dir(app_dir)
        _write_appimage_identity(identity_path, version, build_number, target_triple)
        print(
            "Tauri AppImage finalization failed; using cached appimagetool and runtime.",
            flush=True,
        )
        _package_appimage(app_dir, package, target_triple)

    triple = target_triple
    bundles = BUILD / (args.target or "") / "release" / "bundle"
    tauri_configuration = json.loads(
        (WEB / "src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
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
        suffix = package.suffix.lower()
        if suffix == ".appimage":
            purpose = None
        elif suffix == ".exe":
            purpose = "setup"
        elif suffix == ".dmg":
            purpose = None
        else:
            raise RuntimeError(f"Tauri created an unsupported package artifact: {package.name}")
        if suffix == ".dmg":
            _validate_macos_dmg(
                package,
                tauri_configuration["productName"],
                tauri_configuration["identifier"],
            )
        canonical_name = _artifact_filename(
            version, target_triple, platform.system(), purpose
        )
        canonical_package = package.with_name(canonical_name)
        if canonical_package != package:
            os.replace(package, canonical_package)
        copied = destination / canonical_name
        shutil.copy2(canonical_package, copied)
        print(copied)
    print(f"Version: {version}, Build: {build_number}, Commit: {build_commit}")
    portable_archive_name = (
        _artifact_filename(version, target_triple, "Windows", "portable")
        if platform.system() == "Windows" and not args.no_portable_zip
        else None
    )
    if platform.system() != "Darwin":
        print(
            publish_portable(
                destination,
                bundles.parent,
                platform.system(),
                portable_archive_name,
            )
        )
    if portable_archive_name:
        print(destination / portable_archive_name)


if __name__ == "__main__":
    main()
