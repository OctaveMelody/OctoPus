"""Load raw or JSON-wrapped JPS text and repair evidenced encoding damage."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_JPS_SUFFIX_RE = re.compile(r"(?:\.jps)+$", re.IGNORECASE)


JPS_EXTENSION = ".jps"


_MOJIBAKE_MARKERS = frozenset("ÃÂäåæçèéïð")


@dataclass(frozen=True, slots=True)
class JpsDocument:
    path: Path
    key: str
    code: str
    original_code: str
    custom_code: str
    page_config: dict[str, Any]
    record: dict[str, Any]
    json_wrapped: bool
    encoding_repaired: bool


def _mojibake_score(value: str) -> int:
    marker_count = sum(value.count(char) for char in _MOJIBAKE_MARKERS)
    control_count = sum(0x80 <= ord(char) <= 0x9F for char in value)
    return marker_count + control_count * 2 + value.count("\ufffd") * 10


def repair_mojibake(value: str) -> tuple[str, bool]:
    """Repair UTF-8 decoded as a single-byte encoding when evidence is strong."""
    baseline = _mojibake_score(value)
    if baseline == 0:
        return value, False
    candidates: list[str] = []
    for encoding in ("latin-1", "cp1252"):
        try:
            candidates.append(value.encode(encoding).decode("utf-8"))
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    if not candidates:
        return value, False
    best = min(candidates, key=_mojibake_score)
    if _mojibake_score(best) < baseline:
        return best, True
    return value, False


def load_jps(path: Path) -> JpsDocument:
    return load_jps_text(path.read_text(encoding="utf-8-sig"), path)


def _finite_json_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number in JPS document")
    return number


def decode_page_config(value: Any) -> dict[str, Any]:
    """Normalize dict or JSON-string page settings while retaining invalid input."""
    if isinstance(value, str):
        try:
            decoded = json.loads(
                value, parse_float=_finite_json_number, parse_constant=_finite_json_number,
            )
        except json.JSONDecodeError:
            return {"_raw": value}
        return decoded if isinstance(decoded, dict) else {"_raw": value}
    return value if isinstance(value, dict) else {"_raw": value}


def load_jps_text(text: str, path: Path) -> JpsDocument:
    """Parse JPS text without accessing the filesystem; `path` supplies identity only."""
    text = text.removeprefix("\ufeff")
    record: dict[str, Any] = {}
    json_wrapped = False
    try:
        parsed = json.loads(
            text, parse_float=_finite_json_number, parse_constant=_finite_json_number,
        )
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("code"), str):
        record = parsed
        original_code = parsed["code"]
        custom_code = parsed.get("custom_code", "")
        page_config_value = parsed.get("page_config", {})
        json_wrapped = True
    else:
        original_code = text
        custom_code = ""
        page_config_value = {}

    code, repaired = repair_mojibake(original_code)
    page_config = decode_page_config(page_config_value)

    return JpsDocument(
        path=path,
        key=jps_key(path.name),
        code=code,
        original_code=original_code,
        custom_code=custom_code if isinstance(custom_code, str) else str(custom_code),
        page_config=page_config,
        record=record,
        json_wrapped=json_wrapped,
        encoding_repaired=repaired,
    )


def serialize_jps(
    document: JpsDocument,
    *,
    code: str | None = None,
    page_config: Mapping[str, Any] | None = None,
) -> str:
    """Serialize source while retaining wrapper fields and optional page settings."""
    source_code = document.code if code is None else code
    if not document.json_wrapped and page_config is None:
        return source_code
    record = dict(document.record)
    record["code"] = source_code
    if page_config is not None:
        record["page_config"] = dict(page_config)
    return json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def jps_key(filename: str) -> str:
    return _JPS_SUFFIX_RE.sub("", filename).strip()
