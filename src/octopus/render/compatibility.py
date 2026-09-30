"""Quarantined reference behavior with an explicit retirement condition."""

from __future__ import annotations

AudioCompatibilityKey = tuple[str, int, int, int, int, str | None, str]

_AS_WISHED = "content:e27e941f82f66e10ebd53ec0c2d74d83db80f9f4cd233697c30c84d6c7804fb3"
_CITY_LIGHT = "content:5da6cd3865f7f809794bfea891900f6ac329ac253f77f29181a3468b005f89ce"
_CITY_LIGHT_EDITED = "content:209cde7cfb74660663f6cd720a3a5867aadb5973a5a859188354f2812997c3cc"

EXPECTED_SVG_SILENT_AUDIO_EVENTS: frozenset[AudioCompatibilityKey] = frozenset(
    {
        (_AS_WISHED, 2, 0, 1, 35, None, "1'/)"),
        (_AS_WISHED, 2, 0, 1, 41, None, "2'/)"),
        (_AS_WISHED, 2, 1, 2, 14, None, "2)"),
        (_AS_WISHED, 2, 1, 2, 28, None, "3)"),
        (_AS_WISHED, 2, 2, 3, 14, None, "7)"),
        (_AS_WISHED, 2, 2, 3, 28, None, "6)"),
        (_CITY_LIGHT, 1, 0, 9, 21, None, "1.)"),
        (_CITY_LIGHT_EDITED, 1, 0, 9, 21, None, "1.)"),
        (
            "content:6217beaeeab56a913b071bcc1aaded94fe0f55d2f0f740b5513a1a10e3a79eba",
            1,
            0,
            11,
            21,
            None,
            "1.)",
        ),
    }
)
