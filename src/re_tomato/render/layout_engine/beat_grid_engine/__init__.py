"""Beat-grid-union natural layout for shared voice groups (P2.4, M2 rule).

This module implements the reference (OpenFanqieCore ``layoutVoiceGroup``)
beat-grid-union width rule. It computes the *natural* (uncompressed) barline
x offsets and per-line note x offsets for a group of rendered lines that share
a measure grid. The caller applies the per-system compression scale (see
:func:`compression_scale`).

The rule (confirmed against ``samples/svg_pages/``; see ``docs/project/IMPLEMENTATION_PLAN.md``
"P2.4 multi-voice measure alignment"):

* Per measure, take the max beat count across the lines.
* Per beat, build columns: column 0 = the max ``leading_width`` across lines,
  column i = column i-1 + the max ``within_beat_spacing`` across lines.
* Beat width = last column + ``PLAIN_NOTE_STEP`` + the max ``beat_terminal``
  across lines (a wide lyric on a beat's last note also widens the gap to the
  next beat via ``lyric_overflow``).
* Measure width = sum of beat widths + ``BARLINE_GAP`` + the max barline
  trailing (the last beat's terminal width plus its last note's lyric overflow).

Key details that make it exact on the verified case (Grandmas-Penghu-Bay -
Choir system 0, all four voice lines, <0.5 px):

* ``lyric_overflow(text) = max(0, (125n - 225) / 9)`` where ``n`` counts one
  unit per ASCII letter/space/hyphen/punctuation and two units per wide
  (non-ASCII) char of the syllable's first rendered element (0 for n <= 2).
* A dotted event's trailing space and its lyric overflow never stack: the
  reference pushes by ``max(dot_trail, overflow)`` (oracle-verified).
* A sustain ``-`` (model EXTENSION, ``duration=None``) is a 1-beat grid item
  that does NOT consume a lyric syllable.
* A hidden rest ``8`` (model HIDDEN_REST, ``duration=None``) is a note-like
  rest whose length follows its slashes; it consumes a syllable slot.
* Rests (``0``/``8``) are narrow symbols: they use the underlined step even
  without slashes, so a rest never widens a shared beat column.
* Beat assignment is the natural beat (floor of cumulative quarter-note time),
  overridable by ``~`` (join) / ``^`` (split) beat boundaries, which the model
  folds into the note ``raw``.

The TS is a structural guide that deviates from the reference for complex
cases (hidden rests combined with dotted notes, quoted annotations, repeats,
voltas); the final rule stays pinned to the reference output."""

__all__: list[str] = []
