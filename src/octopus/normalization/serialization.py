"""Serialize normalized models while excluding internal construct metadata."""

from __future__ import annotations

from typing import Any, cast

from octopus._json import json_value
from octopus.normalization.topology import (
    strip_internal_construct_metadata as _strip_internal_construct_metadata,
)
from octopus.normalization.topology import (
    topology_to_dict,
)
from octopus.normalization.types import ScoreModel


def model_to_dict(
    model: ScoreModel, *, include_diagnostics: bool = False
) -> dict[str, Any]:
    """Serialize a portable model, or include provenance for explicit diagnostics."""
    result = cast(dict[str, Any], _strip_internal_construct_metadata(json_value(model)))
    if not include_diagnostics:
        for key in ("source_path", "source_key", "record"):
            result.pop(key, None)
    return result


def model_topology_to_dict(
    model: ScoreModel, *, include_diagnostics: bool = False
) -> dict[str, Any]:
    """Serialize topology, omitting its source key unless diagnostics are requested."""
    return topology_to_dict(model, include_diagnostics=include_diagnostics)
