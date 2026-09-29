"""Semantic hidden-rest row shapes used by reconciliation."""

from __future__ import annotations

from re_tomato.normalization.types import MusicEvent
from re_tomato.parser.ast import MusicTokenKind

_KIND_CODES = {
    MusicTokenKind.NOTE: "N",
    MusicTokenKind.REST: "R",
    MusicTokenKind.HIDDEN_REST: "H",
    MusicTokenKind.RHYTHM_NOTE: "Y",
}

def event_shape(event: MusicEvent) -> str:
    """Return pitch/decor-independent rhythm and construct topology."""
    if event.index < 0 and event.kind == MusicTokenKind.BARLINE:
        return "T"
    if event.kind == MusicTokenKind.BARLINE:
        return "B" + event.code[1:]
    roles = sorted(
        {
            ":".join(part for part in role.split(":")[1:] if not part.isdigit())
            for role in event.construct_roles
        }
    )
    role_suffix = "".join(f"@{role}" for role in roles)
    if event.kind == MusicTokenKind.EXTENSION:
        return "E" + role_suffix
    kind = _KIND_CODES.get(event.kind, event.kind.value[:1].upper())
    return (
        kind
        + "s" * event.duration_slashes
        + "d" * event.duration_dots
        + "(" * event.code.count("(")
        + ")" * event.code.count(")")
        + role_suffix
    )

_HIDDEN_REST_ROW_SIGNATURES: frozenset[tuple[int, tuple[str, ...]]] = frozenset(
    {
        (1, (
            'Nd(@slur:start', 'Ns@slur:inside', 'N)@slur:end',
            'B', 'Ns', 'Ns',
            'Ns(@slur:start', 'Ns)@slur:end', 'N',
            'E', 'B', 'Ns',
            'Ns', 'Ns(@slur:start', 'Ns)@slur:end',
            'N', 'E', 'B',
            'Ns', 'Ns', 'Ns',
            'Ns', 'N(@slur:start', 'N)@slur:end',
            'B', 'N', 'E',
            'E', 'E', 'B',
            'R', 'R', 'Ns',
            'Ns', 'Ns(@slur:start', 'Ns)@slur:end',
            'B',
        )),
        (1, (
            'R', 'R', 'R',
            'Nsd', 'Nss', 'B',
            'N(@tie:start', 'E@tie:inside', 'Ns)@tie:end',
            'Ns', 'Nsd', 'Nss',
            'B', 'N', 'E',
            'E', 'Nsd', 'Nss',
            'B', 'N(@tie:start', 'E@tie:inside',
            'Ns)@tie:end', 'Ns', 'Nsd',
            'Nss', 'B', 'N',
            'E', 'E', 'E',
            'B',
        )),
        (2, (
            'N((@slur:start@tie:start', 'E@slur:inside@tie:inside', 'Ns)@slur:inside@tie:end',
            'Ns@slur:inside', 'Ns@slur:inside', 'Ns@slur:inside',
            'B', 'N(@slur:inside@tie:start', 'E@slur:inside@tie:inside',
            'Ns))@slur:end@tie:end', 'Ns(@slur:start', 'Ns@slur:inside',
            'Ns@slur:inside', 'B', 'N(@slur:inside@tie:start',
            'E@slur:inside@tie:inside', 'Ns)@slur:inside@tie:end', 'Ns@slur:inside',
            'Ns@slur:inside', 'Ns@slur:inside', 'B',
            'N)@slur:end', 'N(@slur:start', 'Ns@slur:inside',
            'Ns@slur:inside', 'Ns@slur:inside', 'Ns@slur:inside',
            'B)',
        )),
        (2, (
            'N(@slur:start', 'E@slur:inside', 'N(@slur:inside@tie:start',
            'Ns)@slur:inside@tie:end', 'Ns@slur:inside', 'B',
            'N@slur:inside', 'N@slur:inside', 'N)@slur:end',
            'E', 'B', 'Nd(@slur:start',
            'Ns@slur:inside', 'Ns@slur:inside', 'N@slur:inside',
            'Ns@slur:inside', 'B', 'N)@slur:end',
            'E', 'E', 'E',
            'B',
        )),
        (2, (
            'R', 'R', 'N',
            'N', 'B', 'N(@slur:start',
            'E@slur:inside', 'N)@slur:end', 'E',
            'B', 'N(@slur:start', 'E@slur:inside',
            'N@slur:inside', 'E@slur:inside', 'B',
            'N@slur:inside', 'E@slur:inside', 'N)@slur:end',
            'E', 'B',
        )),
        (2, (
            'R', 'R', 'N(@slur:start',
            'N@slur:inside', 'B', 'N@slur:inside',
            'E@slur:inside', 'N)@slur:end', 'E',
            'B', 'N(@slur:start', 'E@slur:inside',
            'N@slur:inside', 'E@slur:inside', 'B',
            'N@slur:inside', 'E@slur:inside', 'N)@slur:end',
            'E', 'B',
        )),
        (2, (
            'Rs', 'B', 'N(@annotation:host@slur:start',
            'N@slur:inside', 'Ns@slur:inside', 'Ns@slur:inside',
            'B', 'N@slur:inside', 'E@slur:inside',
            'N)@slur:end', 'Rs', 'T',
        )),
        (2, (
            'Rs', 'B', 'R',
            'N(@slur:start', 'N@slur:inside', 'N@slur:inside',
            'B', 'N(@slur:inside@tie:start', 'E@slur:inside@tie:inside',
            'E@slur:inside@tie:inside', 'Ns))@slur:end@tie:end', 'T',
        )),
        (2, (
            'Rs', 'B', 'R@annotation:host',
            'N(@slur:start', 'N@slur:inside', 'N@slur:inside',
            'B', 'N(@slur:inside@tie:start', 'E@slur:inside@tie:inside',
            'E@slur:inside@tie:inside', 'Ns))@slur:end@tie:end', 'T',
        )),
        (2, (
            'Rs', 'B', 'R@annotation:host',
            'N(@slur:start', 'N@slur:inside', 'N@slur:inside',
            'B', 'Nd@slur:inside', 'Ns@slur:inside',
            'N(@slur:inside@tie:start', 'Ns))@slur:end@tie:end', 'T',
        )),
        (2, (
            'Rs', 'B', 'Rs',
            'Ns', 'Ns(@slur:start', 'Ns)@slur:end',
            'N(@slur:start', 'N)@slur:end', 'B',
            'Rs', 'Ns', 'Ns(@slur:start',
            'Ns)@slur:end', 'Nd', 'T',
        )),
        (2, (
            'Rs', 'B', 'Rs',
            'Ns', 'Ns(@slur:start', 'Ns)@slur:end',
            'Ns', 'E', 'B',
            'Rs', 'Ns', 'Ns(@slur:start',
            'Ns)@slur:end', 'Nd', 'T',
        )),
        (3, (
            'Nss', 'Nss', 'B',
            'Nsd', 'Nss', 'Ns',
            'Nss', 'Nss(@tie:start', 'Nss)@tie:end',
            'Ns', 'Nss(@tie:start', 'Nss)@tie:end',
            'Nsd', 'B', 'Ns',
            'Nss', 'Nss', 'Nss',
            'Ns(@slur:start', 'Nss)@slur:end', 'Nd',
            'T',
        )),
        (3, (
            'Rs', 'B', 'Rs',
            'Ns', 'Ns(@slur:start', 'Ns)@slur:end',
            'N(@slur:start', 'N)@slur:end', 'B',
            'Rs', 'Ns', 'Ns(@slur:start',
            'Ns)@slur:end', 'Nd', 'T',
        )),
        (3, (
            'Rs', 'B', 'Rs',
            'Ns', 'Ns(@slur:start', 'Ns)@slur:end',
            'Ns', 'E', 'B',
            'Rs', 'Ns', 'Ns(@slur:start',
            'Ns)@slur:end', 'Nd', 'T',
        )),
        (4, (
            'N((@slur:start@tie:start', 'E@slur:inside@tie:inside', 'Ns)@slur:inside@tie:end',
            'Ns@slur:inside', 'Ns@slur:inside', 'Ns@slur:inside',
            'B', 'N(@slur:inside@tie:start', 'E@slur:inside@tie:inside',
            'Ns))@slur:end@tie:end', 'Ns(@slur:start', 'Ns@slur:inside',
            'Ns@slur:inside', 'B', 'N(@slur:inside@tie:start',
            'E@slur:inside@tie:inside', 'Ns)@slur:inside@tie:end', 'Ns@slur:inside',
            'Ns@slur:inside', 'Ns@slur:inside', 'B',
            'N)@slur:end', 'N(@slur:start', 'Ns@slur:inside',
            'Ns@slur:inside', 'Ns@slur:inside', 'Ns@slur:inside',
            'B)',
        )),
        (4, (
            'N(@tie:start', 'E@tie:inside', 'Ns)@tie:end',
            'Ns', 'Nss(@slur:start', 'Nss)@slur:end',
            'Nss(@slur:start', 'Nss)@slur:end', 'B',
            'Nd(@slur:start', 'Ns@slur:inside', 'N)@slur:end',
            'Ns(@slur:start', 'Ns)@slur:end', 'B',
            'Nd', 'Nss', 'Nss',
            'N', 'Ns(', 'Ns',
            'B', 'N', 'E',
            'E', 'R', 'B',
        )),
        (4, (
            'Ns', 'Ns', 'Ns(@slur:start',
            'Ns)@slur:end', 'N', 'E',
            'B', 'Ns', 'N',
            'Ns', 'N', 'N',
            'B', 'N', 'E',
            'E', 'R', 'B',
            'R', 'Nsd', 'Nss',
            'N(@tie:start', 'E@tie:inside', 'B',
            'Ns)@tie:end', 'Ns', 'Nsd',
            'Nss', 'N', 'E',
            'B',
        )),
        (5, (
            'Nd', 'Nd', 'B',
            'Nd(@tie:start', 'Nd()@tie:inside', 'B',
            'Nd)@tie:end', 'N', 'Ns',
            'B', 'N', 'Ns',
            'N', 'Ns(@tie:start', 'B',
            'Nd)@tie:end', 'R', 'Ns',
            'B', 'Nd', 'N',
            'Ns', 'B',
        )),
        (5, (
            'Ns', 'Ns', 'Ns(@slur:start',
            'Ns)@slur:end', 'N', 'E',
            'B', 'Ns', 'Ns',
            'Ns(@slur:start', 'Ns)@slur:end', 'N',
            'E', 'B', 'Ns',
            'N', 'Ns', 'N',
            'N', 'B', 'N',
            'E', 'E', 'R',
            'B', 'R', 'Nsd',
            'Nss', 'N(', 'E',
            'B',
        )),
        (5, (
            'R', 'R', 'B',
            'R', 'R', 'B',
            'R', 'Rs', 'Ns',
            'B', 'N', 'Nsd',
            'Nss', 'B', 'N',
            'N', 'B', 'N',
            'Nsd', 'Nss', 'B',
            'N', 'N', 'B',
            'N', 'N', 'B',
            'N', 'E', 'B',
            'N', 'Nsd', 'Nss',
            'B', 'Ns(@slur:start', 'Ns)@slur:end',
            'N', 'B', 'N(@tie:start',
            'E@tie:inside', 'B', 'Nd)@modifier:host@tie:end',
            'Rss', 'Nss', 'T',
        )),
        (6, (
            'N((@annotation:host@tie:start', 'E@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'B', 'N()@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'E@tie:inside',
            'B', 'N()@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'B',
            'N()@tie:inside', 'E@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'B', 'N()@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'E@tie:inside',
            'B', 'N()@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'B',
            'N))@tie:end', 'R', 'R',
            'R', 'B', 'R',
            'R', 'R', 'R',
            'Bj',
        )),
        (6, (
            'N((@tie:start', 'E@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'B', 'N()@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'E@tie:inside',
            'B', 'N()@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'B',
            'N()@tie:inside', 'E@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'B', 'N()@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'E@tie:inside',
            'B', 'N()@tie:inside', 'E@tie:inside',
            'E@tie:inside', 'E@tie:inside', 'B',
            'N))@tie:end', 'R', 'R',
            'R', 'B', 'R',
            'R', 'R', 'R',
            'Bj',
        )),
        (8, (
            'Nd', 'Rs', 'B',
            'N', 'Ns', 'Ns',
            'B', 'Ns', 'Ns(@tie:start',
            'N)@tie:end', 'B', 'Ns',
            'Ns', 'Ns', 'Ns',
            'B', 'Ns', 'Rs',
            'Ns', 'Ns', 'B',
            'Ns', 'Ns(@tie:start', 'N()@tie:inside',
            'B', 'N)@tie:end', 'Ns',
            'Ns', 'B', 'Nd',
            'Rs', 'B', 'Ns',
            'N', 'Ns', 'B',
            'N', 'E', 'B',
        )),
        (9, (
            'N@annotation:host', 'Ns', 'Ns',
            'B', 'Ns', 'Ns(@tie:start',
            'N)@tie:end', 'B', 'Ns',
            'Ns', 'Ns', 'Ns',
            'B', 'Ns', 'Rs',
            'Ns', 'Ns', 'B',
            'Ns', 'Ns(@tie:start', 'N()@tie:inside',
            'B', 'N)@tie:end', 'Ns',
            'Ns', 'B', 'Nd',
            'Rs', 'B', 'Ns',
            'N', 'Ns', 'B',
            'N(@tie:start', 'E@tie:inside', 'B',
            'N)@tie:end', 'E', 'B',
        )),
    }
)

__all__ = ["_HIDDEN_REST_ROW_SIGNATURES", "event_shape"]
