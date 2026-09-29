"""Reference-derived style selection for slurs and ties."""

from __future__ import annotations

from ...parser.ast import MusicTokenKind
from ..core.layout_types import LayoutConstruct

STYLE0_ENDPOINT_MIN_SPAN = 100.0


def slur_uses_path(construct: LayoutConstruct) -> bool:
    """Return whether a slur or tie uses the reference path form.

    The classification uses finalized visible event coordinates. ``style_x``
    is an intermediate layout aid and is intentionally ignored here.
    """

    if construct.lianyinxian_type == "2":
        return False
    if construct.lianyinxian_type == "1":
        return True
    if construct.start.line != construct.end.line:
        return False
    # Ties that open or close on a barline keep the endpoint form: a
    # barline-closing tie drops its right glyph and runs to the barline,
    # so the path band would have no right anchor to bend from.
    if construct.start.event.kind == MusicTokenKind.BARLINE:
        return False
    if construct.end.event.kind == MusicTokenKind.BARLINE:
        return False
    return abs(construct.end.x - construct.start.x) < STYLE0_ENDPOINT_MIN_SPAN


__all__ = ["STYLE0_ENDPOINT_MIN_SPAN", "slur_uses_path"]
