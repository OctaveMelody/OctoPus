"""Stable parsing and normalization entry points."""

from octopus._json import json_value
from octopus.jps import JpsDocument, load_jps
from octopus.normalization import brackets as model_brackets
from octopus.normalization.grace import attach_grace_reservations
from octopus.normalization.pipeline import normalize_code, normalize_document, normalize_jps
from octopus.normalization.serialization import model_to_dict, model_topology_to_dict
from octopus.normalization.topology import topology_to_dict
from octopus.normalization.types import (
    DurationValue,
    LyricEvent,
    LyricLineModel,
    MusicEvent,
    PageModel,
    ScoreHeader,
    ScoreModel,
    SemanticConstruct,
    SingletonParenthesisProvenance,
    SystemModel,
    VoiceGroupModel,
    VoiceModel,
)
from octopus.normalization.visual_chains import resolve_visual_chain_endpoints
from octopus.parser.ast import (
    BlankLine,
    HeaderLine,
    LyricLine,
    MusicLine,
    MusicToken,
    MusicTokenKind,
    PageBreakLine,
    ScoreDocument,
)
from octopus.parser.grammar import parse_code, parse_document
from octopus.parser.source import SourceSpan

__all__ = [
    "BlankLine",
    "DurationValue",
    "HeaderLine",
    "JpsDocument",
    "LyricEvent",
    "LyricLine",
    "LyricLineModel",
    "MusicEvent",
    "MusicLine",
    "MusicToken",
    "MusicTokenKind",
    "PageBreakLine",
    "PageModel",
    "ScoreDocument",
    "ScoreHeader",
    "ScoreModel",
    "SemanticConstruct",
    "SingletonParenthesisProvenance",
    "SourceSpan",
    "SystemModel",
    "VoiceGroupModel",
    "VoiceModel",
    "attach_grace_reservations",
    "json_value",
    "load_jps",
    "model_brackets",
    "model_to_dict",
    "model_topology_to_dict",
    "normalize_code",
    "normalize_document",
    "normalize_jps",
    "parse_code",
    "parse_document",
    "resolve_visual_chain_endpoints",
    "topology_to_dict",
]
