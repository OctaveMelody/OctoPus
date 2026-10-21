"""Pinned offline OCR models and selectable profile configuration."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, cast

OcrMode = Literal["default", "accuracy"]
OCR_MODES: tuple[OcrMode, ...] = ("default", "accuracy")
_PACKAGE_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "ocr_models"
_PROJECT_MODEL_CACHE = Path(__file__).resolve().parents[3] / "build" / "ocr-model-cache"
_configured_model_dir = os.environ.get("OCTOPUS_OCR_MODEL_DIR")
if _configured_model_dir:
    ASSET_DIR = Path(_configured_model_dir).expanduser()
elif any(_PACKAGE_ASSET_DIR.glob("*.onnx")) or not _PROJECT_MODEL_CACHE.is_dir():
    ASSET_DIR = _PACKAGE_ASSET_DIR
else:
    ASSET_DIR = _PROJECT_MODEL_CACHE

_OCR_MODE: ContextVar[OcrMode] = ContextVar("octopus_ocr_mode", default="default")


def normalize_ocr_mode(value: object) -> OcrMode:
    if not isinstance(value, str) or value not in OCR_MODES:
        raise ValueError("OCR mode must be 'default' or 'accuracy'")
    return cast(OcrMode, value)


@contextmanager
def ocr_mode_scope(mode: object) -> Iterator[OcrMode]:
    """Bind an OCR profile for this job and restore the caller's mode afterwards."""
    selected = normalize_ocr_mode(mode)
    token = _OCR_MODE.set(selected)
    try:
        yield selected
    finally:
        _OCR_MODE.reset(token)


def current_ocr_mode() -> OcrMode:
    return _OCR_MODE.get()


def _model_dir(model_dir: Path | None = None) -> Path:
    return Path(model_dir) if model_dir is not None else ASSET_DIR


def _manifest(model_dir: Path | None = None) -> dict[str, Any]:
    path = _model_dir(model_dir) / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"OCR model manifest is unavailable: {path}") from error
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise RuntimeError("OCR model manifest has an unsupported schema")
    return value


def _asset_record(filename: str, model_dir: Path | None = None) -> dict[str, Any]:
    assets = _manifest(model_dir).get("models")
    if not isinstance(assets, dict) or not isinstance(assets.get(filename), dict):
        raise RuntimeError(f"OCR model is not recorded in the manifest: {filename}")
    return cast(dict[str, Any], assets[filename])


def _verified_asset(filename: str, model_dir: Path | None = None) -> dict[str, Any]:
    directory = _model_dir(model_dir)
    record = _asset_record(filename, directory)
    path = directory / filename
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"OCR model is missing or not a regular file: {path}")
    expected_size, expected_digest = record.get("size_bytes"), record.get("sha256")
    if type(expected_size) is not int or not isinstance(expected_digest, str):
        raise RuntimeError(f"OCR model metadata is invalid: {filename}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.stat().st_size != expected_size or digest != expected_digest:
        raise RuntimeError(f"OCR model failed size or checksum verification: {filename}")
    return {"file": filename, "size_bytes": expected_size, "sha256": digest}


def _profile_files(mode: OcrMode, model_dir: Path | None = None) -> dict[str, str]:
    profiles = _manifest(model_dir).get("profiles")
    profile = profiles.get(mode) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict) or set(profile) != {"det", "rec", "cls"}:
        raise RuntimeError(f"OCR model profile is invalid: {mode}")
    result = {}
    for role in ("det", "rec", "cls"):
        filename = profile[role]
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeError(f"OCR model filename is invalid for {mode}/{role}")
        result[role] = filename
    return result


def ocr_model_paths(mode: object, model_dir: Path | None = None) -> dict[str, Path]:
    selected = normalize_ocr_mode(mode)
    directory = _model_dir(model_dir)
    return {
        role: directory / _verified_asset(filename, directory)["file"]
        for role, filename in _profile_files(selected, directory).items()
    }


def verify_ocr_assets(
    model_dir: Path | None = None,
    *,
    profiles: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Require the exact selected ONNX files and verify their pinned metadata."""
    directory = _model_dir(model_dir)
    manifest = _manifest(directory)
    models = manifest.get("models")
    if not isinstance(models, dict):
        raise RuntimeError("OCR model manifest has no model inventory")
    selected_modes: tuple[OcrMode, ...] = OCR_MODES if profiles is None else tuple(
        normalize_ocr_mode(mode) for mode in profiles
    )
    expected = {
        filename
        for mode in selected_modes
        for filename in _profile_files(mode, directory).values()
    }
    found = {path.name for path in directory.glob("*.onnx")}
    if found != expected:
        missing, extra = sorted(expected - found), sorted(found - expected)
        raise RuntimeError(f"OCR model inventory differs (missing={missing}, extra={extra})")
    return {filename: _verified_asset(filename, directory) for filename in sorted(expected)}


def _rapidocr_config_sha256() -> str:
    try:
        config = importlib.metadata.distribution("rapidocr").locate_file("rapidocr/config.yaml")
        return hashlib.sha256(Path(str(config)).read_bytes()).hexdigest()
    except (importlib.metadata.PackageNotFoundError, OSError) as error:
        raise RuntimeError("RapidOCR's installed config.yaml is unavailable") from error


def _runtime_versions() -> dict[str, str]:
    packages = (
        "rapidocr", "onnxruntime", "opencv-python-headless", "numpy", "shapely", "pyclipper",
    )
    try:
        return {package: importlib.metadata.version(package) for package in packages}
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(f"required OCR runtime package is unavailable: {error.name}") from error


def _identity_config(mode: OcrMode) -> dict[str, Any]:
    profile = _profile_files(mode)
    model_type = "small" if mode == "default" else "medium"
    return {
        "mode": mode,
        "models": profile,
        "rapidocr_config_sha256": _rapidocr_config_sha256(),
        "rapidocr_parameters": {
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.use_cuda": False,
            "EngineConfig.onnxruntime.use_dml": False,
            "EngineConfig.onnxruntime.use_cann": False,
            "EngineConfig.onnxruntime.use_coreml": False,
            "Global.log_level": "critical",
            "Det.engine_type": "onnxruntime",
            "Det.lang_type": "multi",
            "Det.model_type": model_type,
            "Det.ocr_version": "PP-OCRv6",
            "Det.model_path": profile["det"],
            "Rec.engine_type": "onnxruntime",
            "Rec.lang_type": "multi",
            "Rec.model_type": model_type,
            "Rec.ocr_version": "PP-OCRv6",
            "Rec.model_path": profile["rec"],
            "Cls.engine_type": "onnxruntime",
            "Cls.lang_type": "ch",
            "Cls.model_type": "mobile",
            "Cls.ocr_version": "PP-OCRv4",
            "Cls.model_path": profile["cls"],
        },
        "execution_provider": "CPUExecutionProvider",
    }


def ocr_identity(mode: object) -> dict[str, Any]:
    selected = normalize_ocr_mode(mode)
    paths = ocr_model_paths(selected)
    model_identity = {
        role: _verified_asset(path.name) for role, path in paths.items()
    }
    config = _identity_config(selected)
    config_sha256 = hashlib.sha256(json.dumps(
        config, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {
        "schema": "octopus-ocr-identity-v1",
        "mode": selected,
        "runtime": _runtime_versions(),
        "models": model_identity,
        "config": config,
        "config_sha256": config_sha256,
    }


def rapidocr_params(mode: object, model_dir: Path | None = None) -> dict[str, Any]:
    """Return RapidOCR's explicit local paths and pinned CPU thread settings."""
    selected = normalize_ocr_mode(mode)
    paths = ocr_model_paths(selected, model_dir)
    from rapidocr import EngineType, LangCls, LangDet, ModelType, OCRVersion

    model_type = ModelType.SMALL if selected == "default" else ModelType.MEDIUM
    return {
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
        "EngineConfig.onnxruntime.use_cann": False,
        "EngineConfig.onnxruntime.use_coreml": False,
        "Global.log_level": "critical",
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Det.lang_type": LangDet.MULTI,
        "Det.model_type": model_type,
        "Det.ocr_version": OCRVersion.PPOCRV6,
        "Det.model_path": str(paths["det"]),
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.lang_type": "multi",
        "Rec.model_type": model_type,
        "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Rec.model_path": str(paths["rec"]),
        "Cls.engine_type": EngineType.ONNXRUNTIME,
        "Cls.lang_type": LangCls.CH,
        "Cls.model_type": ModelType.MOBILE,
        "Cls.ocr_version": OCRVersion.PPOCRV4,
        "Cls.model_path": str(paths["cls"]),
    }


def ocr_execution_providers(engine: object) -> dict[str, tuple[str, ...]]:
    """Return the actual ONNX Runtime providers for initialized model sessions."""
    result = {}
    for role, component_name in (
        ("det", "text_det"), ("cls", "text_cls"), ("rec", "text_rec"),
    ):
        component = getattr(engine, component_name, None)
        session = getattr(getattr(component, "session", None), "session", None)
        getter = getattr(session, "get_providers", None)
        if callable(getter):
            providers = tuple(str(provider) for provider in getter())
            if providers:
                result[role] = providers
    return result
