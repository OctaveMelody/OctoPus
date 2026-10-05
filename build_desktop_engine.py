"""Build and verify the offline Python worker resource for Tauri."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
TARGET_DIR = ROOT / "build"
OUTPUT_DIR = TARGET_DIR / "desktop-engine" / "octopus-engine"
ENTRY_POINT = ROOT / "ui" / "engine" / "desktop_entry.py"
GLYPH_DIR = ROOT / "src" / "octopus" / "assets" / "glyphs"
PYINSTALLER_VERSION = "6.22.3"

sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from octopus.jps import load_jps  # noqa: E402
from ui.engine.desktop_protocol import PROTOCOL_VERSION, dispatch  # noqa: E402


def _normalized_architecture(value: str) -> str:
    return {"amd64": "x86_64", "arm64": "aarch64", "win32": "i686"}.get(
        value.lower(), value.lower()
    )


def _validate_target_triple(
    target_triple: str | None,
    *,
    host_system: str | None = None,
    python_platform: str | None = None,
) -> None:
    if target_triple is None:
        return
    parts = target_triple.split("-")
    if len(parts) < 3:
        raise RuntimeError(f"invalid Tauri target triple: {target_triple}")
    target_arch, target_os = parts[0], parts[2]
    expected_system = {"linux": "Linux", "windows": "Windows"}.get(target_os)
    if expected_system is None:
        raise RuntimeError(f"desktop engine packaging does not support {target_triple}")
    if (host_system or platform.system()) != expected_system:
        raise RuntimeError(
            f"PyInstaller cannot cross-build {target_triple}; run the build on {expected_system}"
        )
    build_platform = python_platform or sysconfig.get_platform()
    python_arch = _normalized_architecture(build_platform.split("-")[-1])
    if _normalized_architecture(target_arch) != python_arch:
        raise RuntimeError(
            f"Python architecture {python_arch} does not match Tauri target {target_triple}"
        )


def _request(
    request_id: str, operation: str, revision: int, payload: dict[str, object]
) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "document_id": "desktop-build-smoke",
        "document_revision": revision,
        "operation": operation,
        "payload": payload,
    }


def _check_glyph_assets(bundle: Path, glyph_dir: Path = GLYPH_DIR) -> None:
    expected = {path.name for path in glyph_dir.glob("*.svg")} | {"registry.json"}
    found = {path.name for path in bundle.rglob("*") if path.is_file()}
    missing = sorted(expected - found)
    if missing:
        raise RuntimeError(f"frozen engine is missing glyph assets: {', '.join(missing[:8])}")
    if any(path.name == "playwright" for path in bundle.rglob("playwright")):
        raise RuntimeError("frozen engine unexpectedly contains audit-only Playwright")


def _check_font_assets(bundle: Path) -> None:
    source = ROOT / "src/octopus/assets/fonts"
    manifests = ([bundle / "manifest.json"] if (bundle / "manifest.json").is_file()
                 else list(bundle.rglob("octopus/assets/fonts/manifest.json")))
    if len(manifests) != 1:
        raise RuntimeError("release font directory is missing its manifest")
    root = manifests[0].parent
    if manifests[0].read_bytes() != (source / "manifest.json").read_bytes():
        raise RuntimeError("release font manifest differs from source")
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    for entry in [*manifest["faces"], *manifest["licenses"]]:
        path = root / entry["file"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(
                f"missing/corrupt release font asset: {entry['file']}"
            )


def _check_project_license(bundle: Path, source: Path = ROOT / "LICENSE") -> None:
    copied = bundle / "LICENSE"
    if not copied.is_file() or copied.read_bytes() != source.read_bytes():
        raise RuntimeError("project license missing/corrupt")


def _index_smoke_responses(
    responses: Sequence[object], requests: Sequence[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Correlate final protocol replies while allowing transcription progress frames."""
    expected: dict[str, dict[str, object]] = {}
    for request in requests:
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise RuntimeError("frozen engine smoke request is missing its ID")
        if request_id in expected:
            raise RuntimeError("frozen engine smoke requests contain duplicate IDs")
        expected[request_id] = request
    final: dict[str, dict[str, object]] = {}
    generation: object | None = None
    for response in responses:
        if not isinstance(response, dict):
            raise RuntimeError("frozen engine emitted a non-object response")
        request_id = response.get("request_id")
        if not isinstance(request_id, str) or request_id not in expected:
            raise RuntimeError("frozen engine emitted a response for an unknown request")
        request = expected[request_id]
        if any(
            response.get(key) != request.get(key)
            for key in ("protocol_version", "document_id", "document_revision")
        ):
            raise RuntimeError(f"frozen engine response identity mismatch for {request_id}")
        response_generation = response.get("engine_generation")
        if not isinstance(response_generation, str) or not response_generation:
            raise RuntimeError("frozen engine response is missing its generation")
        if generation is None:
            generation = response_generation
        elif response_generation != generation:
            raise RuntimeError("frozen engine response generation changed during smoke test")

        if response.get("status") == "progress":
            if request_id in final:
                raise RuntimeError(
                    "frozen engine emitted progress after final response for "
                    f"{request_id}"
                )
            progress = response.get("result")
            if request.get("operation") != "transcribe" or not isinstance(progress, dict):
                raise RuntimeError("frozen engine emitted an invalid progress response")
            completed = progress.get("completed")
            total = progress.get("total")
            stage = progress.get("stage")
            if (
                type(completed) is not int
                or type(total) is not int
                or total < 1
                or completed < 0
                or completed > total
                or not isinstance(stage, str)
                or not stage
            ):
                raise RuntimeError("frozen engine emitted malformed transcription progress")
            continue
        if request_id in final:
            raise RuntimeError(f"frozen engine emitted duplicate final response for {request_id}")
        final[request_id] = response

    missing = sorted(set(expected) - set(final))
    if missing:
        raise RuntimeError("frozen engine omitted final response(s): " + ", ".join(missing))
    return final


def _smoke_test(bundle: Path, render_request: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory(prefix="octopus-ocr-smoke-") as temporary:
        _smoke_test_with_image(bundle, render_request, Path(temporary))


def _smoke_test_with_image(
    bundle: Path, render_request: dict[str, object], temporary: Path,
) -> None:
    executable_name = "octopus-engine"
    if platform.system() == "Windows":
        executable_name += ".exe"
    executable = bundle / executable_name
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller output is missing its worker executable: {executable}")

    smoke_image = temporary / "ocr-smoke.png"
    image = Image.new("RGB", (480, 120), "white")
    ImageDraw.Draw(image).text((24, 42), "Q: 1 2 3 4 |", fill="black")
    image.save(smoke_image)
    backends_to_check = ("rapidocr-onnxruntime", "rapidocr-onnx")
    transcription_requests = [
        _request(
            f"desktop-build-transcribe-{backend}", "transcribe", index + 2,
            {"path": str(smoke_image), "ocr_backend": backend},
        )
        for index, backend in enumerate(backends_to_check)
    ]
    handshake = _request("desktop-build-handshake", "handshake", 0, {})
    previous_profile = os.environ.get("OCTOPUS_FONT_PROFILE")
    os.environ["OCTOPUS_FONT_PROFILE"] = "release"
    try:
        expected_handshake = dispatch(
            json.dumps(handshake, ensure_ascii=True, allow_nan=False).encode("utf-8"),
            generation="desktop-build-reference",
        )
        expected = dispatch(
            json.dumps(render_request, ensure_ascii=True, allow_nan=False).encode("utf-8"),
            generation="desktop-build-reference",
        )
    finally:
        if previous_profile is None:
            os.environ.pop("OCTOPUS_FONT_PROFILE", None)
        else:
            os.environ["OCTOPUS_FONT_PROFILE"] = previous_profile
    input_text = (
        "\n".join(
            json.dumps(item, ensure_ascii=True, allow_nan=False)
            for item in (handshake, render_request, *transcription_requests)
        )
        + "\n"
    )
    completed = subprocess.run(
        [str(executable)],
        cwd=bundle,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"frozen engine exited {completed.returncode}: {completed.stderr[-4000:]}"
        )
    try:
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
    except json.JSONDecodeError as error:
        raise RuntimeError(f"frozen engine emitted invalid JSON: {error}") from error
    expected_requests = [handshake, render_request, *transcription_requests]
    responses_by_id = _index_smoke_responses(responses, expected_requests)
    handshake_id = handshake["request_id"]
    render_id = render_request["request_id"]
    if not isinstance(handshake_id, str) or not isinstance(render_id, str):
        raise RuntimeError("frozen engine smoke request is missing its ID")
    handshake_response = responses_by_id[handshake_id]
    if handshake_response.get("status") != "ok":
        raise RuntimeError("frozen engine handshake failed or emitted an unexpected response")
    if (
        handshake_response.get("protocol_version") != PROTOCOL_VERSION
        or handshake_response.get("request_id") != handshake["request_id"]
        or handshake_response.get("document_id") != handshake["document_id"]
        or handshake_response.get("result") != expected_handshake.get("result")
    ):
        raise RuntimeError("frozen engine handshake identity or capabilities did not match")
    response = responses_by_id[render_id]
    if (
        response.get("status") != "ok"
        or response.get("protocol_version") != PROTOCOL_VERSION
        or response.get("request_id") != render_request["request_id"]
        or response.get("document_id") != render_request["document_id"]
        or response.get("document_revision") != render_request["document_revision"]
        or response.get("result") != expected.get("result")
    ):
        raise RuntimeError(
            "frozen engine render did not exactly match the source adapter: "
            + json.dumps(response.get("error"), ensure_ascii=True)[:1000]
        )
    handshake_result = handshake_response.get("result")
    available_backends = (
        handshake_result.get("ocr_backends", {})
        if isinstance(handshake_result, dict)
        else {}
    )
    for request, backend in zip(transcription_requests, backends_to_check, strict=True):
        request_id = request["request_id"]
        if not isinstance(request_id, str):
            raise RuntimeError("frozen engine transcription request is missing its ID")
        result = responses_by_id[request_id]
        if available_backends.get(backend) is not True:
            raise RuntimeError(f"frozen engine did not advertise OCR backend {backend}")
        transcription_result = result.get("result")
        if (
            result.get("status") != "ok"
            or not isinstance(transcription_result, dict)
            or transcription_result.get("page_count") != 1
            or not isinstance(transcription_result.get("jps"), str)
        ):
            raise RuntimeError(
                f"frozen engine transcription failed for {backend}: "
                + json.dumps(result.get("error"), ensure_ascii=True)[:1000]
            )


def _publish_bundle(bundle: Path, output_dir: Path) -> None:
    """Stage a checked worker, restoring the previous bundle if replacement fails."""
    if output_dir.is_symlink() or output_dir.parent.is_symlink():
        raise RuntimeError("refusing to replace a symlinked desktop engine output")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".worker-publish-", dir=output_dir.parent))
    staged = staging_root / "new"
    previous = staging_root / "previous"
    try:
        shutil.copytree(bundle, staged, symlinks=True)
        if output_dir.exists():
            output_dir.replace(previous)
        try:
            staged.replace(output_dir)
        except BaseException:
            if previous.exists():
                previous.replace(output_dir)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        # A failed rollback must leave its backup available for recovery.
        if not previous.exists():
            shutil.rmtree(staging_root)


def build(*, repository_root: Path = ROOT, target_dir: Path = TARGET_DIR) -> Path:
    _validate_target_triple(os.environ.get("TAURI_ENV_TARGET_TRIPLE"))
    entry_point = repository_root / "ui" / "engine" / "desktop_entry.py"
    glyph_dir = repository_root / "src" / "octopus" / "assets" / "glyphs"
    output_dir = target_dir / "desktop-engine" / "octopus-engine"
    if target_dir.is_symlink():
        raise RuntimeError("refusing to write desktop engine through a symlinked Cargo target")
    if output_dir.is_symlink() or output_dir.parent.is_symlink():
        raise RuntimeError("refusing to replace a symlinked desktop engine output")

    if platform.system() not in {"Windows", "Linux"}:
        raise RuntimeError("desktop engine packaging currently supports Windows and Linux only")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("desktop engine packaging requires Python 3.12")
    installed_version = importlib.metadata.version("pyinstaller")
    if installed_version != PYINSTALLER_VERSION:
        raise RuntimeError(
            f"PyInstaller {PYINSTALLER_VERSION} is required; found {installed_version}"
        )
    if importlib.metadata.version("rapidocr-onnxruntime") != "1.4.4":
        raise RuntimeError("desktop transcription requires rapidocr-onnxruntime 1.4.4")
    if importlib.metadata.version("rapidocr") != "3.9.2":
        raise RuntimeError("desktop transcription requires rapidocr 3.9.2")
    if importlib.metadata.version("onnxruntime") != "1.30.0":
        raise RuntimeError("desktop transcription requires ONNX Runtime 1.30.0")
    if not entry_point.is_file():
        raise RuntimeError(f"desktop engine entry point is missing: {entry_point}")

    sample = load_jps(repository_root / "samples" / "jps_files" / "Symbols.jps")
    render_request = _request(
        "desktop-build-render",
        "render",
        1,
        {
            "name": sample.path.name,
            "code": sample.code,
            "custom_code": sample.custom_code,
            "page_config": sample.page_config,
        },
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".desktop-engine-build-", dir=target_dir) as work:
        work_dir = Path(work)
        dist_dir = work_dir / "dist"
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "octopus-engine",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir / "work"),
            "--specpath",
            str(work_dir),
            "--paths",
            str(repository_root),
            "--paths",
            str(repository_root / "src"),
            "--collect-data",
            "octopus.assets.glyphs",
            "--collect-all",
            "fontTools",
            "--collect-all",
            "rapidocr_onnxruntime",
            "--collect-all",
            "rapidocr",
            "--collect-all",
            "onnxruntime",
            "--exclude-module",
            "playwright",
            str(entry_point),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(
                "PyInstaller failed:\n" + (completed.stderr or completed.stdout)[-8000:]
            )
        bundle = dist_dir / "octopus-engine"
        _check_glyph_assets(bundle, glyph_dir)
        shutil.copy2(repository_root / "LICENSE", bundle / "LICENSE")
        _check_project_license(bundle, repository_root / "LICENSE")
        font_dir = dist_dir / "fonts"
        shutil.copytree(repository_root / "src/octopus/assets/fonts", font_dir)
        _check_font_assets(font_dir)
        _smoke_test(bundle, render_request)
        _publish_bundle(dist_dir, output_dir.parent)

    return output_dir


if __name__ == "__main__":
    if sys.argv[1:] == ["--verify-fonts"]:
        _check_font_assets(ROOT / "src")
        print("Verified production font assets and notices")
    else:
        print(build())
