"""Download and verify the pinned OCR models into the ignored production build cache."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from octopus.transcription.ocr_profiles import verify_ocr_assets  # noqa: E402

MANIFEST = ROOT / "src" / "octopus" / "assets" / "ocr_models" / "manifest.json"
MODEL_NOTICES = ("LICENSE", "NOTICE.md")
DEFAULT_OUTPUT = ROOT / "build" / "ocr-model-cache"
MODEL_HOST = "www.modelscope.cn"


def _load_manifest(path: Path = MANIFEST) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"OCR model manifest is unavailable: {path}") from error
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise RuntimeError("OCR model manifest has an unsupported schema")
    models, profiles = value.get("models"), value.get("profiles")
    if not isinstance(models, dict) or not isinstance(profiles, dict):
        raise RuntimeError("OCR model manifest is missing models or profiles")
    if set(profiles) != {"default"}:
        raise RuntimeError("OCR model manifest must contain only the Default profile")
    expected = {
        filename
        for profile in profiles.values()
        if isinstance(profile, dict)
        for filename in profile.values()
        if isinstance(filename, str)
    }
    if expected != set(models):
        raise RuntimeError("OCR model manifest inventory does not match its profiles")
    if len(expected) != 3:
        raise RuntimeError("Default OCR profile must inventory exactly three models")
    for filename, record in models.items():
        if (not isinstance(filename, str) or Path(filename).name != filename
                or not filename.endswith(".onnx") or not isinstance(record, dict)):
            raise RuntimeError("OCR model manifest contains an invalid model record")
        url = record.get("source_url")
        if (not isinstance(url, str) or urlsplit(url).scheme != "https"
                or urlsplit(url).hostname != MODEL_HOST):
            raise RuntimeError(f"OCR model source is not an official ModelScope URL: {filename}")
        if (type(record.get("size_bytes")) is not int
                or not isinstance(record.get("sha256"), str)):
            raise RuntimeError(f"OCR model metadata is invalid: {filename}")
    return value


def _matches(path: Path, record: dict[str, object]) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.stat().st_size == record["size_bytes"] and digest == record["sha256"]


def _rapidocr_wheel_model(filename: str, record: dict[str, object]) -> Path | None:
    try:
        distribution = importlib.metadata.distribution("rapidocr")
    except importlib.metadata.PackageNotFoundError:
        return None
    path = Path(distribution.locate_file(Path("rapidocr") / "models" / filename))
    return path if _matches(path, record) else None


def _copy_model(source: Path, target: Path, record: dict[str, object]) -> None:
    if target.is_symlink():
        raise RuntimeError(f"refusing to replace a symlinked OCR model: {target}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".part", dir=target.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        shutil.copyfile(source, temporary_path)
        if not _matches(temporary_path, record):
            raise RuntimeError(f"RapidOCR wheel model failed verification: {source}")
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _download(filename: str, record: dict[str, object], output_dir: Path) -> None:
    target = output_dir / filename
    if target.is_symlink():
        raise RuntimeError(f"refusing to replace a symlinked OCR model: {target}")
    temporary_path: Path | None = None
    try:
        request = Request(
            str(record["source_url"]),
            headers={"User-Agent": "OctoPus pinned OCR model preparation"},
        )
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(
            prefix=f".{filename}.", suffix=".part", dir=output_dir, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            with urlopen(request, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > record["size_bytes"]:
                        raise RuntimeError(
                            f"OCR model download exceeded its pinned size: {filename}"
                        )
                    digest.update(chunk)
                    temporary.write(chunk)
        if size != record["size_bytes"] or digest.hexdigest() != record["sha256"]:
            raise RuntimeError(
                f"OCR model download failed size or checksum verification: {filename}"
            )
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def prepare(output_dir: Path = DEFAULT_OUTPUT) -> Path:
    """Ensure the build cache contains exactly the three Default model assets."""
    manifest = _load_manifest()
    models = manifest["models"]
    profiles = manifest["profiles"]
    assert isinstance(models, dict)
    assert isinstance(profiles, dict)
    default_profile = profiles.get("default")
    assert isinstance(default_profile, dict)
    wheel_models = set(default_profile.values())
    if output_dir.is_symlink():
        raise RuntimeError(f"refusing to write OCR models through a symlink: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = set(models)
    found = {path.name for path in output_dir.glob("*.onnx")}
    extra = found - expected
    if extra:
        raise RuntimeError(f"unexpected OCR model files in build cache: {sorted(extra)}")

    manifest_target = output_dir / "manifest.json"
    if manifest_target.is_symlink():
        raise RuntimeError(f"refusing to replace a symlinked OCR manifest: {manifest_target}")
    shutil.copy2(MANIFEST, manifest_target)
    for filename in MODEL_NOTICES:
        source = MANIFEST.parent / filename
        target = output_dir / filename
        if target.is_symlink():
            raise RuntimeError(f"refusing to replace a symlinked OCR notice: {target}")
        shutil.copy2(source, target)
    for filename, record in models.items():
        assert isinstance(record, dict)
        path = output_dir / filename
        if path.is_symlink():
            raise RuntimeError(f"refusing to replace a symlinked OCR model: {path}")
        if not _matches(path, record):
            wheel_model = (
                _rapidocr_wheel_model(filename, record) if filename in wheel_models else None
            )
            if wheel_model is not None:
                print(f"Copying verified RapidOCR wheel model {filename}", flush=True)
                _copy_model(wheel_model, path, record)
            else:
                print(f"Preparing {filename}", flush=True)
                _download(filename, record, output_dir)

    verify_ocr_assets(output_dir)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(prepare(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
