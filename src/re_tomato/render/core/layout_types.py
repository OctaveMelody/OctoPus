"""Data types produced by the score layout stage.

This module intentionally contains only layout data structures.  Keeping these
types separate lets the layout algorithms evolve without changing the public
``re_tomato.render.layout`` import surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from re_tomato.normalization.types import (
    LyricLineModel,
    MusicEvent,
    SystemModel,
    UnresolvedSpanState,
    VoiceModel,
)
from re_tomato.parser.source import SourceSpan

# Guard internal geometry arithmetic without tightening corpus acceptance.
GEOMETRY_EPSILON = 1e-9
DEFAULT_NOTE_START_OFFSET = 3.0


@dataclass(frozen=True)
class PageMetrics:
    width: int = 1000
    height: int = 1415
    margin_top: int = 40
    margin_bottom: int = 40
    margin_left: int = 60
    margin_right: int = 60
    body_margin_top: int = 20
    title_font: str = "Microsoft YaHei"
    note_font: str = "b"
    lyric_font: str = "Microsoft YaHei"
    title_size: int = 36
    subtitle_size: int = 20
    lyric_size: int = 16
    height_quci: int = 12
    height_cici: int = 10
    height_ciqu: int = 20
    height_shengbu: int = 10
    lianyinxian_type: str = "0"
    time_sig: str = ""

    def __post_init__(self) -> None:
        positive_fields = ("width", "height", "title_size", "subtitle_size", "lyric_size")
        non_negative_fields = (
            "margin_top",
            "margin_bottom",
            "margin_left",
            "margin_right",
            "body_margin_top",
            "height_quci",
            "height_cici",
            "height_ciqu",
            "height_shengbu",
        )
        for name in (*positive_fields, *non_negative_fields):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
        for name in positive_fields:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in non_negative_fields:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.margin_left + self.margin_right >= self.width:
            raise ValueError("horizontal margins must leave a positive content width")
        if self.margin_top + self.margin_bottom >= self.height:
            raise ValueError("vertical margins must leave a positive content height")

    @property
    def title_y(self) -> int:
        return self.margin_top + 30

    @property
    def header_content_offset_y(self) -> int:
        """Offset header content after the title from the 36px reference profile."""
        return self.title_size - 36

    @property
    def key_y(self) -> int:
        return self.margin_top + 96 + self.header_content_offset_y

    @property
    def tempo_y(self) -> int:
        return self.margin_top + 136 + self.header_content_offset_y

    @property
    def credit_y(self) -> int:
        return self.margin_top + 146 + self.header_content_offset_y

    @property
    def music_start_y(self) -> int:
        return (
            self.margin_top
            + 146
            + self.body_margin_top
            + self.header_content_offset_y
        )

    @property
    def continuation_music_start_y(self) -> int:
        # Continuation pages retain the configured body headroom rather than a
        # fixed offset.  The reference starts music ten pixels below that
        # profile, independent of title/header content on page one.
        return self.margin_top + self.body_margin_top + 10

    @property
    def note_start_x(self) -> float:
        return float(self.margin_left + DEFAULT_NOTE_START_OFFSET)

    @property
    def lyric_offset_y(self) -> float:
        # Reference anchors the first verse to the line's bottom row plus the
        # note-to-lyric gap (height_quci) and a fixed 25 px lyric drop.
        return float(self.height_quci + 25)

    @property
    def lyric_line_spacing(self) -> float:
        return float(self.lyric_size + self.height_cici)


@dataclass(frozen=True, slots=True)
class RowLayoutInput:
    """Typed source context shared by row splitting and spacing decisions."""

    source_group: tuple[MusicEvent, ...]
    voice: VoiceModel
    lyrics: tuple[LyricLineModel, ...]
    meter: str
    hidden_reserve_width: float
    available_width: float


@dataclass
class LayoutAddress:
    page_index: int
    visual_row_index: int
    slot_index: int

    @property
    def notepos(self) -> str:
        return f"{self.page_index}_{self.visual_row_index}_{self.slot_index}"


@dataclass
class LayoutEvent:
    event: MusicEvent
    x: float
    y: float
    page_index: int
    voice: int
    line: int
    slot: int
    # Source Q-voice number of the hosting voice (plain `Q:` lines are 0,
    # ``Q1`` is 1, ...).  The layout ``voice`` field is only the enumerate
    # index within a system, which diverges from the Q numbering whenever a
    # system does not start at Q1.
    source_voice: int = 0
    # 1-based index of the hosting visual system on the page (UI Phase 2 R5.5
    # metadata API). Stamped by the layout engine as each system is placed;
    # zero means "not stamped".
    system_index: int = 0
    block: str | None = None
    block_index: int = 0
    stream_slot: int | None = None
    style_x: float | None = None
    # Exact temporary-DSB onset mapping.  This is intentionally separate from
    # stream_slot, which may be shared by all notes in a beam group.
    onset_slot: int | None = None
    onset_aligned: bool = False
    # Compression scale (stretched px per natural unit) of the row or shared
    # system this event was projected with.  Renderers use it to place
    # scaled-width accessories, such as temporary meter labels, at a
    # natural-unit offset from the host.
    projection_scale: float | None = None
    # Direction (``<`` or ``>``) of a standalone hairpin modifier token that
    # attaches after this event, e.g. ``(3' 2')<`` — the ``<`` is lexed as its
    # own MODIFIER token once the paren group closes on the host note.
    hairpin_opener: str | None = None
    # Which projection produced the final x: "grid" (shared duration grid,
    # where projection_scale is the exact geometric ratio), "shared" (legacy
    # reconciled-width shared system), "syllabic", "ordinary", or "sparse"
    # (per-row legacy justifications, where projection_scale is only the plan
    # scale and not the geometric row ratio).
    projection_kind: str | None = None

    @property
    def address(self) -> LayoutAddress:
        return LayoutAddress(self.page_index, self.line, self.slot)


@dataclass
class LayoutLyric:
    text: str
    x: float
    y: float
    cipos: str | None
    verse: int
    annotation: bool = False
    voice: int = 0
    line: int = 0
    slot: int = 0
    profile_continuation: bool = False
    # Internal anchor for annotation x fixup (not serialized).
    anchor_cipos: str | None = None
    source_spans: tuple[SourceSpan, ...] = ()
    # 1-based visual system owner; zero means the lyric has no source token.
    system_index: int = 0


@dataclass
class LayoutHeader:
    title: str = ""
    subtitle: str = ""
    credits: list[tuple[str, str]] = field(default_factory=list)
    key: str = ""
    time_sig: str = ""
    tempo: str = ""


@dataclass
class LayoutConstruct:
    kind: str
    start: LayoutEvent
    end: LayoutEvent
    lianyinxian_type: str = "0"
    source_kind: str | None = None
    source_text: str = ""
    construct_id: str | None = None
    logical_start: LayoutEvent | None = None
    logical_end: LayoutEvent | None = None
    visual_only: bool = False
    semantic_parent_id: str | None = None
    visual_start_event_index: int | None = None
    visual_end_event_index: int | None = None
    vertical_offset: float = 0.0
    row_vertical_offsets: dict[int, float] = field(default_factory=dict)
    ending_plus_count: int = 0
    ending_is_first_segment: bool = True
    ending_is_last_segment: bool = True
    ending_explicit_close: bool = True
    ending_reserves_clearance: bool = True
    # The span was nested in an EOL-dangling ``(`` that the reference discards
    # without drawing; visible rows emit it after its first child's subtree
    # instead of before it (model.SemanticConstruct.inside_dangling_span).
    inside_dangling_span: bool = False


@dataclass
class LayoutVoiceBrace:
    x: float
    y_top: float
    y_bottom: float
    line_start: int
    line_end: int


@dataclass
class LayoutVoiceCaption:
    """Right-aligned voice label (or empty marker) for a brace-run line."""

    x: float
    y: float
    text: str
    voice: int
    line: int


@dataclass
class LayoutGrace:
    host: LayoutEvent
    raw: str
    children: tuple[MusicEvent, ...]


@dataclass
class LayoutMark:
    host: LayoutEvent
    event: MusicEvent
    placement: str = "above"
    ending_plus_count: int = 0
    # Modifier marks can have a source-level span opener between the host note
    # and the decoration token.  Keep that semantic fact on the layout mark so
    # renderers do not inspect raw source text.
    starts_upper_span: bool = False


@dataclass
class LayoutHairpinMark:
    """A source modifier whose wedge boundary is not a visible note pair."""

    host: LayoutEvent
    direction: str
    boundary: LayoutEvent


@dataclass
class LayoutPage:
    metrics: PageMetrics
    page_index: int = 1
    compatibility_key: str | None = None
    events: list[LayoutEvent] = field(default_factory=list)
    hidden_events: list[LayoutEvent] = field(default_factory=list)
    lyrics: list[LayoutLyric] = field(default_factory=list)
    constructs: list[LayoutConstruct] = field(default_factory=list)
    voice_braces: list[LayoutVoiceBrace] = field(default_factory=list)
    voice_captions: list[LayoutVoiceCaption] = field(default_factory=list)
    graces: list[LayoutGrace] = field(default_factory=list)
    marks: list[LayoutMark] = field(default_factory=list)
    hairpin_marks: list[LayoutHairpinMark] = field(default_factory=list)
    header: LayoutHeader = field(default_factory=LayoutHeader)
    source_voice_by_line: dict[int, int] = field(default_factory=dict)
    unresolved_span_states: tuple[UnresolvedSpanState, ...] = ()
    first_tie_lift_rows: frozenset[int] = frozenset()


@dataclass
class _SyntheticIndexAllocator:
    next_index: int

    def take(self) -> int:
        index = self.next_index
        self.next_index -= 1
        return index


@dataclass
class _SystemLayoutState:
    current_y: float
    max_voice_y: float
    voice_spacing: float
    system_rows: int
    system_line_start: int
    system_event_start: int
    system_tail_height: float
    right: float
    system_note_start_x: float
    available_width: float
    next_system: SystemModel | None
    visible_events_by_voice: dict[int, list[MusicEvent]]
    source_line_offsets: dict[int, int]
    source_line_y_offsets: dict[int, float]
    shared_lyric_text_by_voice: dict[int, dict[tuple[int, int], tuple[str, ...]]]
    shared_lyric_gap_by_voice: dict[int, dict[tuple[int, int], int]]
    shared_grace_raw_by_voice: dict[int, dict[int, str]]
