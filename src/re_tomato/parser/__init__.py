"""Recovery-oriented parser for Tomato/Jianpu JPS source."""

from .ast import ScoreDocument, document_to_dict
from .grammar import parse_code, parse_document, parse_jps

__all__ = ["ScoreDocument", "document_to_dict", "parse_code", "parse_document", "parse_jps"]
