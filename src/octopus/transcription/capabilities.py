"""Conservative host and runtime capability checks for selectable OCR engines."""

from __future__ import annotations

import importlib.util
import platform
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, cast


def _linux_vendor_ids() -> tuple[str, ...]:
    try:
        contents = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    return _linux_vendor_ids_from_cpuinfo(contents)


def _linux_vendor_ids_from_cpuinfo(contents: str) -> tuple[str, ...]:
    return tuple(
        value.strip()
        for line in contents.splitlines()
        if line.partition(":")[0].strip().casefold() == "vendor_id"
        and (value := line.partition(":")[2])
    )


def _windows_vendor_id() -> str | None:
    try:
        import winreg

        registry = cast(Any, winreg)
        with registry.OpenKey(
            registry.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            value, _ = registry.QueryValueEx(key, "VendorIdentifier")
    except (ImportError, OSError):
        return None
    return str(value).strip()


def _macos_vendor_id() -> str | None:
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "machdep.cpu.vendor"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def intel_cpu_confirmed() -> bool:
    """Return true only when an OS CPU-vendor source reports GenuineIntel."""
    system = platform.system()
    if system == "Linux":
        vendors = _linux_vendor_ids()
        return bool(vendors) and all(vendor == "GenuineIntel" for vendor in vendors)
    if system == "Windows":
        return _windows_vendor_id() == "GenuineIntel"
    if system == "Darwin":
        return _macos_vendor_id() == "GenuineIntel"
    return False


def _has_module(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


@lru_cache(maxsize=1)
def openvino_cpu_available() -> bool:
    """Require an Intel CPU, RapidOCR, OpenVINO and an enumerated OpenVINO CPU plugin."""
    if not intel_cpu_confirmed() or not _has_module("rapidocr") or not _has_module("openvino"):
        return False
    try:
        from openvino import Core  # type: ignore[import-untyped]

        return "CPU" in Core().available_devices
    except Exception:
        return False


def ocr_backend_capabilities() -> dict[str, bool]:
    """Return availability flags used by the desktop handshake and Preferences UI."""
    has_rapidocr = _has_module("rapidocr")
    return {
        "rapidocr-onnxruntime": _has_module("rapidocr_onnxruntime"),
        "rapidocr-onnx": has_rapidocr and _has_module("onnxruntime"),
        "rapidocr-openvino": openvino_cpu_available(),
    }
