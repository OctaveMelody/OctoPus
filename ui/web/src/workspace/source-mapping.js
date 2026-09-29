/** @typedef {{line: number, column: number, offset: number}} SourcePosition */
/** @typedef {{start: SourcePosition, end: SourcePosition}} SourceSpan */
/**
 * @typedef {{
 *   event_index: number,
 *   event_kind: string,
 *   source_span: SourceSpan,
 *   row: number,
 *   x: number,
 *   y: number
 * }} EventAnchor
 */
/** @typedef {{source_spans: SourceSpan[], row: number, x: number, y: number}} LyricAnchor */
/** @typedef {{events: EventAnchor[], lyrics: LyricAnchor[]}} PageAnchors */

/** @param {string} source */
export function createSourceOffsetMap(source) {
  const utf16Offsets = [0];
  const lineStarts = [0];
  let codePointOffset = 0;
  for (const character of source) {
    const utf16Offset = utf16Offsets[utf16Offsets.length - 1] + character.length;
    utf16Offsets.push(utf16Offset);
    codePointOffset += 1;
    if (
      character === "\n"
      || (character === "\r" && source.charCodeAt(utf16Offset) !== 10)
    ) {
      lineStarts.push(codePointOffset);
    }
  }

  return {
    /** @param {number} codePointOffset */
    codePointToUtf16(codePointOffset) {
      return Number.isSafeInteger(codePointOffset)
        && codePointOffset >= 0
        && codePointOffset < utf16Offsets.length
        ? utf16Offsets[codePointOffset]
        : null;
    },
    /** @param {number} utf16Offset */
    utf16ToCodePoint(utf16Offset) {
      if (!Number.isSafeInteger(utf16Offset) || utf16Offset < 0) return null;
      let low = 0;
      let high = utf16Offsets.length - 1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        if (utf16Offsets[middle] === utf16Offset) return middle;
        if (utf16Offsets[middle] < utf16Offset) low = middle + 1;
        else high = middle - 1;
      }
      return null;
    },
    /** @param {number} codePointOffset */
    codePointToPosition(codePointOffset) {
      if (
        !Number.isSafeInteger(codePointOffset)
        || codePointOffset < 0
        || codePointOffset >= utf16Offsets.length
      ) return null;
      let low = 0;
      let high = lineStarts.length;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (lineStarts[middle] <= codePointOffset) low = middle + 1;
        else high = middle;
      }
      const lineIndex = low - 1;
      return { line: lineIndex + 1, column: codePointOffset - lineStarts[lineIndex] + 1 };
    },
  };
}

/**
 * @param {Map<number, PageAnchors>} pages
 * @param {number} codePointOffset
 * @param {{line: number, column: number} | null} [position]
 */
export function findSourceAnchor(pages, codePointOffset, position = null) {
  const exact = findAnchorAt(pages, codePointOffset);
  if (exact) return exact;
  if (codePointOffset > 0) {
    const previous = findAnchorAt(pages, codePointOffset - 1);
    if (previous) return previous;
  }
  if (!position) return null;
  const anchors = sourceAnchors(pages);
  if (anchors.length === 0) return null;

  const first = anchors[0];
  const last = anchors[anchors.length - 1];
  if (comparePosition(position, first.sourceSpans[0].start) < 0) return first;
  if (comparePosition(position, finalSpan(last.sourceSpans).end) > 0) return last;

  let nearest = null;
  let nearestLineDistance = Infinity;
  let nearestColumnDistance = Infinity;
  for (const anchor of anchors) {
    for (const span of anchor.sourceSpans) {
      const [lineDistance, columnDistance] = distanceToSpan(position, span);
      if (
        lineDistance < nearestLineDistance
        || (lineDistance === nearestLineDistance && columnDistance < nearestColumnDistance)
      ) {
        nearest = anchor;
        nearestLineDistance = lineDistance;
        nearestColumnDistance = columnDistance;
      }
    }
  }
  return nearest;
}

/** @param {Map<number, PageAnchors>} pages @param {number} offset */
function findAnchorAt(pages, offset) {
  for (const [pageIndex, page] of pages) {
    for (const event of page.events) {
      if (contains(event.source_span, offset)) {
        return {
          kind: "event",
          pageIndex,
          x: event.x,
          y: event.y,
          row: event.row,
          sourceSpans: [event.source_span],
          eventIndex: event.event_index,
        };
      }
    }
    for (const lyric of page.lyrics) {
      if (lyric.source_spans.some((span) => contains(span, offset))) {
        return {
          kind: "lyric",
          pageIndex,
          x: lyric.x,
          y: lyric.y,
          row: lyric.row,
          sourceSpans: lyric.source_spans,
        };
      }
    }
  }
  return null;
}

/** @param {Map<number, PageAnchors>} pages */
function sourceAnchors(pages) {
  const anchors = [];
  for (const [pageIndex, page] of [...pages].sort(([left], [right]) => left - right)) {
    for (const event of page.events) {
      anchors.push({
        kind: "event",
        pageIndex,
        x: event.x,
        y: event.y,
        row: event.row,
        sourceSpans: [event.source_span],
        eventIndex: event.event_index,
      });
    }
    for (const lyric of page.lyrics) {
      if (lyric.source_spans.length === 0) continue;
      anchors.push({
        kind: "lyric",
        pageIndex,
        x: lyric.x,
        y: lyric.y,
        row: lyric.row,
        sourceSpans: lyric.source_spans,
      });
    }
  }
  return anchors.sort((left, right) => comparePosition(
    left.sourceSpans[0].start,
    right.sourceSpans[0].start,
  ));
}

/** @param {SourceSpan[]} spans */
function finalSpan(spans) {
  return spans.reduce((last, span) => comparePosition(last.end, span.end) < 0 ? span : last);
}

/** @param {{line: number, column: number}} left @param {{line: number, column: number}} right */
function comparePosition(left, right) {
  return left.line - right.line || left.column - right.column;
}

/** @param {{line: number, column: number}} position @param {SourceSpan} span */
function distanceToSpan(position, span) {
  const lineDistance = position.line < span.start.line
    ? span.start.line - position.line
    : position.line > span.end.line
      ? position.line - span.end.line
      : 0;
  if (lineDistance > 0) return [lineDistance, 0];
  if (position.line === span.start.line && position.column < span.start.column) {
    return [0, span.start.column - position.column];
  }
  if (position.line === span.end.line && position.column >= span.end.column) {
    return [0, position.column - span.end.column + 1];
  }
  return [0, 0];
}

/** @param {PageAnchors} page @param {number} x @param {number} y @param {number} [maxDistance] */
export function hitTestSourceAnchor(page, x, y, maxDistance = 36) {
  let nearest = null;
  let nearestDistance = maxDistance * maxDistance;
  const candidates = [
    ...page.events
      .filter((event) => !["barline", "extension"].includes(event.event_kind))
      .map((event) => ({
        kind: "event",
        x: event.x,
        y: event.y,
        row: event.row,
        sourceSpans: [event.source_span],
        eventIndex: event.event_index,
      })),
    ...page.lyrics
      .filter((lyric) => lyric.source_spans.length > 0)
      .map((lyric) => ({
        kind: "lyric",
        x: lyric.x,
        y: lyric.y,
        row: lyric.row,
        sourceSpans: lyric.source_spans,
      })),
  ];
  for (const candidate of candidates) {
    const distance = (candidate.x - x) ** 2 + (candidate.y - y) ** 2;
    if (distance <= nearestDistance) {
      nearest = candidate;
      nearestDistance = distance;
    }
  }
  return nearest;
}

/** @param {DOMRect} rect @param {number} width @param {number} height @param {number} clientX @param {number} clientY */
export function imagePointToSvg(rect, width, height, clientX, clientY) {
  if (!width || !height || !rect.width || !rect.height) return null;
  return {
    x: ((clientX - rect.left) / rect.width) * width,
    y: ((clientY - rect.top) / rect.height) * height,
  };
}

/** @param {SourceSpan} span @param {number} offset */
function contains(span, offset) {
  return span.start.offset <= offset && offset < span.end.offset;
}
