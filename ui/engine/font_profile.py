"""Compatibility path for the core-owned font profile implementation."""

from __future__ import annotations

import sys

from octopus import font_profile as _implementation

# Preserve module identity for existing callers that patch/cache profile state.
sys.modules[__name__] = _implementation
