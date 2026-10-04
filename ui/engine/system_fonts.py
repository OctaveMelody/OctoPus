"""Compatibility path for core SFNT inspection helpers."""

from __future__ import annotations

import sys

from octopus import system_fonts as _implementation

sys.modules[__name__] = _implementation
