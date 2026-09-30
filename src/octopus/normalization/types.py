"""Immutable normalized score model types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from octopus.parser.ast import LyricTokenKind, MusicTokenKind
from octopus.parser.diagnostics import Diagnostic
from octopus.parser.source import SourceSpan


@dataclass(frozen=True, slots=True)
class DurationValue:
    numerator: int
    denominator: int
    text: str


@dataclass(frozen=True, slots=True)
class ScoreHeader:
    prefix: str
    value: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class MusicEvent:
    index: int
    kind: MusicTokenKind
    raw: str
    span: SourceSpan
    code: str
    source_code: str | None = None
    render_code: str | None = None
    value: str | None = None
    pitch: int | None = None
    accidental: str | None = None
    octave: int = 0
    duration_slashes: int = 0
    duration_dots: int = 0
    dotted: bool = False
    decorations: tuple[str, ...] = ()
    attached_to_previous: bool = False
    duration: DurationValue | None = None
    time: str | None = None
    audio: str | None = None
    children: tuple[MusicEvent, ...] = ()
    construct_ids: tuple[str, ...] = ()
    construct_roles: tuple[str, ...] = ()
    # Total stretched-space width reserved by unquoted grace markers attached
    # to this event (seven units per marker digit).  The shared duration grid
    # places it in front of the note and takes it out of the available width
    # when solving the compression scale; zero for every other event.
    grace_reservation: int = 0


@dataclass(frozen=True, slots=True)
class SingletonParenthesisProvenance:
    """Source topology for a singleton span retained by an enclosing span."""

    source_span: SourceSpan
    source_text: str
    start_event_index: int
    end_event_index: int
    preceding_event_index: int | None = None


@dataclass(frozen=True, slots=True)
class UnresolvedSpanState:
    """A source-owned span opener that remained unmatched through the document."""

    source_voice: int
    source_span: SourceSpan
    page_index: int
    prior_span_count: int = 0
    family: str = "span"


@dataclass(frozen=True, slots=True)
class SemanticConstruct:
    construct_id: str
    kind: str
    source_span: SourceSpan
    start_event_index: int | None = None
    end_event_index: int | None = None
    event_indices: tuple[int, ...] = ()
    host_event_index: int | None = None
    value: str | None = None
    source_text: str = ""
    role_by_event_index: tuple[tuple[int, str], ...] = ()
    visual_only: bool = False
    # Logical endpoints describe the complete semantic construct.  These
    # optional endpoints describe the segment that should be drawn when a
    # nested tie chain partitions a larger logical span.  Keeping them
    # separate prevents layout concerns from changing event roles, identity,
    # or the construct's source topology.
    visual_start_event_index: int | None = None
    visual_end_event_index: int | None = None
    # The nearest enclosing semantic span.  This is topology, not rendering
    # order, and lets page layout distinguish a true nested parent from two
    # unrelated spans that happen to overlap in X.
    semantic_parent_id: str | None = None
    # Inert source topology for singleton parenthesis spans that were
    # intentionally not promoted to semantic constructs. Keep this on the
    # nearest enclosing span so construct IDs and event roles remain stable.
    singleton_parenthesis_provenance: tuple[SingletonParenthesisProvenance, ...] = ()
    # Number of leading ``+`` modifiers attached to a repeat-ending opener.
    # This is semantic metadata used to select the bracket's vertical lane;
    # other construct families leave it at zero.
    ending_plus_count: int = 0
    ending_is_first_segment: bool = True
    ending_is_last_segment: bool = True
    # A closer written as ``|]/`` (bracket close followed by a slash) omits
    # the right corner of the bracket frame; every other explicit close
    # (``|]``, ``:|]``, ``||]``) draws it.  Oracle- and corpus-verified on
    # Flower-In-Water, I-Like, Edelweiss p3, and Half-Pot segments.
    ending_explicit_close: bool = True
    # Recovered cross-system brackets must not retroactively change the row
    # spacing that was already exact before their visual topology was known.
    ending_reserves_clearance: bool = True
    # A middle member of a shared-endpoint chain that the reference engraver
    # does not draw when an EOL-dangling outer span takes its lane. The
    # construct stays in the model so event roles and signatures are
    # undisturbed; only the layout projection skips it.
    render_suppressed: bool = False
    # A closed span whose proper ancestor ``(`` was left unclosed at end of
    # line and discarded without being drawn.  The reference engraver emits
    # such a span right after its first child's subtree instead of before it
    # (oracle-verified 2026-08-31, probe shapes I/R1b/R3/S1/Q; corpus instance
    # Edelweiss p3 x4).  Childless spans carry the flag inertly.
    inside_dangling_span: bool = False


@dataclass(frozen=True, slots=True)
class LyricEvent:
    kind: LyricTokenKind
    raw: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LyricLineModel:
    voice: int
    raw: str
    span: SourceSpan
    tokens: tuple[LyricEvent, ...]


@dataclass(frozen=True, slots=True)
class IgnoredTextModel:
    identifier: str | None
    voice: int
    line: int
    raw: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class VoiceModel:
    voice: int
    name: str | None
    declared_names: tuple[str, ...]
    source_span: SourceSpan | None
    music_line_numbers: tuple[int, ...]
    lyric_line_numbers: tuple[int, ...]
    events: tuple[MusicEvent, ...]
    lyrics: tuple[LyricLineModel, ...]
    constructs: tuple[SemanticConstruct, ...] = ()
    # (line number, declared name) pairs in source order, e.g. Q1"SA" lines.
    line_names: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MusicRowAddress:
    """Stable identity for one physical ``Q`` music row.

    ``source_line`` is the source-of-truth identity used by the renderer and
    evidence tools.  ``row_index`` is only the deterministic source order
    within a normalized system; it is deliberately not a visual SVG row.
    """

    page_index: int
    system_index: int
    row_index: int
    voice: int
    source_line: int
    continuation: bool = False

    @property
    def key(self) -> tuple[int, int, int, int, int]:
        return (
            self.page_index,
            self.system_index,
            self.row_index,
            self.voice,
            self.source_line,
        )


@dataclass(frozen=True, slots=True)
class VoiceGroupModel:
    """A source-declared group of rows sharing a horizontal music grid."""

    index: int
    rows: tuple[MusicRowAddress, ...]
    source_span: SourceSpan | None = None

    @property
    def voices(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(row.voice for row in self.rows))

    @property
    def source_lines(self) -> tuple[int, ...]:
        return tuple(row.source_line for row in self.rows)

    @property
    def is_multi_voice(self) -> bool:
        return len(self.voices) > 1


@dataclass(frozen=True, slots=True)
class SystemModel:
    index: int
    source_span: SourceSpan | None
    music_line_numbers: tuple[int, ...]
    lyric_line_numbers: tuple[int, ...]
    voices: tuple[VoiceModel, ...]
    voice_groups: tuple[VoiceGroupModel, ...] = ()


@dataclass(frozen=True, slots=True)
class PageModel:
    index: int
    source_span: SourceSpan | None
    systems: tuple[SystemModel, ...]


@dataclass(frozen=True, slots=True)
class ScoreModel:
    source_path: str | None
    source_key: str | None
    code: str
    original_code: str
    custom_code: str
    page_config: dict[str, Any]
    record: dict[str, Any]
    json_wrapped: bool
    encoding_repaired: bool
    headers: tuple[ScoreHeader, ...]
    ignored_text: tuple[IgnoredTextModel, ...]
    pages: tuple[PageModel, ...]
    diagnostics: tuple[Diagnostic, ...]
    source_voice_by_line: tuple[tuple[int, int], ...] = ()
    unresolved_span_states: tuple[UnresolvedSpanState, ...] = ()
