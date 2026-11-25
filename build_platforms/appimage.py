from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

RUNTIME_ARCHES = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "i686": "i386",
    "armv7": "armhf",
}

# Published by the packaged launcher so the headless CLI can resolve relative paths against the
# directory the user ran the AppImage from, before the AppImage runtime changes the working
# directory to the (possibly read-only) application directory.
INVOCATION_DIRECTORY_VARIABLE = "OCTOPUS_INVOCATION_CWD"
INVOCATION_DIRECTORY_EXPORT = f'export {INVOCATION_DIRECTORY_VARIABLE}="${{PWD:-$(pwd)}}"'
INVOCATION_APPDIR_EXPORT = 'export OCTOPUS_INVOCATION_APPDIR="$this_dir"'
LINUXDEPLOY_EXEC = 'exec "$this_dir"/AppRun.wrapped "$@"'


def paths(
    target: str | None,
    version: str,
    target_triple: str,
    *,
    build: Path,
    web: Path,
    artifact_filename: Callable[[str, str, str, str | None], str],
) -> tuple[Path, Path, Path, Path]:
    config = json.loads((web / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    product_name = config["productName"]
    bundle_dir = build / (target or "") / "release/bundle/appimage"
    app_dir = bundle_dir / f"{product_name}.AppDir"
    package = bundle_dir / artifact_filename(version, target_triple, "Linux", None)
    identity = bundle_dir / ".octopus-build.json"
    return bundle_dir, app_dir, package, identity


def preserve_invocation_directory(app_dir: Path) -> Path:
    """Teach the deployed launcher to publish the directory it was started from.

    linuxdeploy writes a shell AppRun that execs the AppImage runtime, and that runtime moves the
    working directory into the AppDir before starting the application. The shell AppRun still runs
    in the caller's directory, so the export is inserted immediately before it hands over.
    """
    launcher = app_dir / "AppRun"
    text = launcher.read_text(encoding="utf-8")
    if LINUXDEPLOY_EXEC not in text:
        raise RuntimeError(
            "The staged AppImage launcher does not use the expected linuxdeploy chain; "
            "refusing to package it"
        )
    if INVOCATION_APPDIR_EXPORT not in text or INVOCATION_DIRECTORY_EXPORT not in text:
        text = text.replace(f"{INVOCATION_DIRECTORY_EXPORT}\n", "")
        text = text.replace(f"{INVOCATION_APPDIR_EXPORT}\n", "")
        handoff = f"{INVOCATION_DIRECTORY_EXPORT}\n{INVOCATION_APPDIR_EXPORT}"
        text = text.replace(LINUXDEPLOY_EXEC, f"{handoff}\n{LINUXDEPLOY_EXEC}")
        launcher.write_text(text, encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def prepare_app_dir(app_dir: Path, find_executable: Callable[..., str | None]) -> None:
    from build_desktop_engine import _check_font_assets, check_worker_handshake

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
    preserve_invocation_directory(app_dir)
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

    check_worker_handshake(app_dir / "usr/lib/OctoPus/engine/octopus-engine")


def runtime_download_failed(output: object, app_dir: Path) -> bool:
    if not isinstance(output, str):
        return False
    packaging_started = any(
        "Running command:" in line and "appimagetool" in line and str(app_dir) in line
        for line in output.splitlines()
    )
    return packaging_started and "Failed to download runtime file" in output


def output_plugin(environment: dict[str, str]) -> Path:
    cache_home = Path(environment.get("XDG_CACHE_HOME", ""))
    if not cache_home.is_absolute():
        cache_home = Path.home() / ".cache"
    plugin = cache_home / "tauri/linuxdeploy-plugin-appimage.AppImage"
    if not plugin.is_file():
        raise RuntimeError(f"Tauri's AppImage output plugin is missing: {plugin}. Run a full build.")
    return plugin


def environment(environment: dict[str, str], target_triple: str, *, root: Path) -> dict[str, str]:
    result = dict(environment)
    runtime_arch = RUNTIME_ARCHES.get(target_triple.split("-", 1)[0])
    runtime = root / f"build/cache/tauri/runtime-{runtime_arch}" if runtime_arch else None
    if runtime and runtime.is_file() and not result.get("LDAI_RUNTIME_FILE"):
        result["LDAI_RUNTIME_FILE"] = str(runtime)
    shapely_libraries = root / "build/desktop-engine/octopus-engine/_internal/shapely.libs"
    if shapely_libraries.is_dir():
        paths = [str(shapely_libraries)]
        paths.extend(
            path for path in result.get("LD_LIBRARY_PATH", "").split(os.pathsep)
            if path and path != str(shapely_libraries)
        )
        result["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
    return result
