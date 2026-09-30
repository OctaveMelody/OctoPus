"""Stable semantic identity for temporary reference-compatibility rules.

The compatibility tables describe measured reference behavior that has not yet
been generalized into a semantic rule. Their lookup key must identify only the
rendering inputs, not provenance or the name of the file that happened to
contain them, so metadata edits and renamed sources cannot silently change
rendering behavior.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .._json import json_value


def compatibility_profile_key(
    *,
    code: str,
    custom_code: str,
    page_config: Mapping[str, Any],
) -> str:
    """Return a stable identifier for source/configuration data that affects rendering.

    File paths, corpus keys, wrapped record metadata, original spelling, and
    loader provenance are intentionally excluded. ``code`` is the normalized
    source accepted by the parser; ``custom_code`` and ``page_config`` are the
    remaining renderer inputs. The canonical JSON payload keeps the identifier
    stable across dictionary ordering and renamed/rewrapped source tests.
    """

    payload = {
        "code": code,
        "custom_code": custom_code,
        "page_config": json_value(dict(page_config)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"content:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["compatibility_profile_key"]
