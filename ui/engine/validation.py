"""Shared wire-boundary checks for desktop and DEV-only diagnostic transports.

Transport envelopes and identifier formats remain distinct; JSON validity, safe
integer checks and envelope construction have a single implementation.
"""

from __future__ import annotations

import json
import math
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1


class WireValidationError(ValueError):
    """Malformed JSON or an invalid scalar at a protocol boundary."""


def is_integer(value: object, *, minimum: int | None = None,
               maximum: int | None = None) -> bool:
    return (type(value) is int and (minimum is None or value >= minimum)
            and (maximum is None or value <= maximum))


def is_identifier(value: object, maximum: int = 128) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum


def _reject_constant(value: str) -> None:
    raise WireValidationError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise WireValidationError("non-finite JSON number")
    return number


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WireValidationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _validate_unicode(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise WireValidationError("strings must contain valid Unicode scalar values") from exc
    elif isinstance(value, list):
        for item in value:
            _validate_unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_unicode(key)
            _validate_unicode(item)


def decode_json(line: str | bytes) -> Any:
    try:
        value = json.loads(line, parse_constant=_reject_constant, parse_float=_finite_float,
                           object_pairs_hook=_unique_object)
    except json.JSONDecodeError:
        raise
    except ValueError as exc:
        raise WireValidationError(str(exc)) from exc
    _validate_unicode(value)
    return value


def envelope(*, status: str, protocol_version: str, **identity: Any) -> dict[str, Any]:
    """Keep boundary status/version construction common without blending wire schemas."""
    return {**identity, "status": status, "protocol_version": protocol_version}
