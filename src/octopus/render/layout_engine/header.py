"""Score-header projection into the layout header model."""

from __future__ import annotations

from octopus.normalization.types import ScoreModel
from octopus.render.core.layout_types import LayoutHeader


def compute_header(model: ScoreModel) -> LayoutHeader:
    header = LayoutHeader()
    for item in model.headers:
        if item.prefix == "B":
            if not header.title:
                header.title = item.value
            else:
                header.subtitle = item.value
        elif item.prefix == "Z":
            # Z lines already contain their author/composer role when intended.
            header.credits.append(("", item.value))
        elif item.prefix == "D":
            header.key = item.value
        elif item.prefix == "P":
            header.time_sig = item.value
        elif item.prefix == "J":
            header.tempo = item.value
    return header


__all__ = ["compute_header"]
