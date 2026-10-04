/** @typedef {{text: string, positions: number[]}} FormattedJpsText */

const AUTO_FORMAT_TRIGGERS = "0123456789|:.-";
// Mirror parser/grammar.py: split at the first colon, then match the trimmed prefix.
const MUSIC_PREFIX = /^Q\d*(?:\[[^\]]*\]|"[^"]*")?$/i;

/** @param {string} line @param {{position: number, index: number}[]} positions */
function formatMusicLine(line, positions) {
  const colon = line.indexOf(":");
  if (colon < 0 || !MUSIC_PREFIX.test(line.slice(0, colon).trim())) {
    return { text: line, positions: positions.map(({ position }) => position) };
  }
  const prefixEnd = colon + 1;

  let sourceCursor = 0;
  let quoted = false;
  let escaped = false;
  let bracketDepth = 0;
  let lastNote = "";
  let compact = "";
  const compactPositions = [];
  /** @param {number} end */
  const appendThrough = (end) => {
    while (sourceCursor < end) {
      const character = line.charAt(sourceCursor);
      if (sourceCursor < prefixEnd) {
        compact += character;
        sourceCursor++;
        continue;
      }
      const wasQuoted = quoted;
      const wasBracketed = bracketDepth > 0;
      if (character === '"' && !escaped) quoted = !quoted;
      if (!wasQuoted && !quoted) {
        // A bracket after a bar opens a repeat ending; only grace groups protect spaces.
        if (character === "[" && (wasBracketed || !lastNote.includes("|"))) bracketDepth++;
        else if (character === "]" && bracketDepth > 0) bracketDepth--;
        if (!wasBracketed && "0123456789-|".includes(character)) lastNote = character;
      }
      const protectedText = wasQuoted || quoted || wasBracketed || character === "[" || character === "]";
      if (character !== " " || protectedText) compact += character;
      escaped = character === "\\" && !escaped;
      sourceCursor++;
    }
  };
  for (const { position } of positions) {
    appendThrough(position);
    compactPositions.push(compact.length);
  }
  appendThrough(line.length);
  if (colon >= 0) {
    compact = `${compact.slice(0, colon + 1)} ${compact.slice(colon + 1)}`;
    for (let index = 0; index < compactPositions.length; index++) {
      if (compactPositions[index] >= colon + 1) compactPositions[index]++;
    }
  }

  let output = "";
  quoted = false;
  escaped = false;
  bracketDepth = 0;
  lastNote = "";
  let positionIndex = 0;
  const mappedPositions = new Array(positions.length);
  for (let index = 0; index <= compact.length; index++) {
    while (compactPositions[positionIndex] === index) {
      mappedPositions[positionIndex] = output.length;
      positionIndex++;
    }
    if (index === compact.length) break;

    const character = compact.charAt(index);
    if (index < prefixEnd) {
      output += character;
      continue;
    }
    const previous = compact.charAt(index - 1);
    const next = compact.charAt(index + 1);
    if (character === '"' && !escaped) quoted = !quoted;
    if (quoted) {
      output += character;
      escaped = character === "\\" && !escaped;
      continue;
    }
    if (!lastNote.includes("|")) {
      if (character === "[") bracketDepth++;
      else if (character === "]" && bracketDepth > 0) bracketDepth--;
      if (bracketDepth > 0) {
        output += character;
        escaped = character === "\\" && !escaped;
        continue;
      }
    }

    const spaceBefore = (
      "0123456789-".includes(character)
      && !["Q", "C", " ", "(", "y"].includes(previous)
    ) || (character === "(" && previous !== "(")
      || (character === "|" && previous !== "|" && previous !== ":")
      || (character === ":" && next === "|")
      || character === "{"
      || character === "}";
    if (spaceBefore && !output.endsWith(" ")) output += " ";
    output += character;
    if ("0123456789-|".includes(character)) lastNote = character;
    escaped = character === "\\" && !escaped;
  }

  return { text: output, positions: mappedPositions };
}

/**
 * Format Q-lines while leaving headers, lyrics and line endings untouched.
 * Positions are CodeMirror's UTF-16 offsets and are mapped through the same
 * spacing changes so selections survive both auto-format and explicit format.
 * @param {string} source
 * @param {number[]} [requestedPositions]
 * @returns {FormattedJpsText}
 */
export function formatJpsSource(source, requestedPositions = []) {
  const positions = requestedPositions.map((position, index) => ({
    position: Number.isFinite(position)
      ? Math.max(0, Math.min(source.length, Math.trunc(position)))
      : 0,
    index,
  })).sort((left, right) => left.position - right.position);
  const mappedPositions = new Array(requestedPositions.length);
  let output = "";
  let inputStart = 0;
  let outputLength = 0;
  let positionIndex = 0;

  while (true) {
    let lineEnd = inputStart;
    while (lineEnd < source.length && source.charAt(lineEnd) !== "\n" && source.charAt(lineEnd) !== "\r") {
      lineEnd++;
    }
    const line = source.slice(inputStart, lineEnd);
    const linePositions = [];
    while (positionIndex < positions.length && positions[positionIndex].position <= lineEnd) {
      linePositions.push({
        position: positions[positionIndex].position - inputStart,
        index: positions[positionIndex].index,
      });
      positionIndex++;
    }
    const formatted = formatMusicLine(line, linePositions);
    output += formatted.text;
    for (let index = 0; index < linePositions.length; index++) {
      mappedPositions[linePositions[index].index] = outputLength + formatted.positions[index];
    }
    outputLength += formatted.text.length;

    if (lineEnd === source.length) break;
    const lineBreakLength = source.charAt(lineEnd) === "\r" && source.charAt(lineEnd + 1) === "\n"
      ? 2
      : 1;
    while (
      positionIndex < positions.length
      && positions[positionIndex].position <= lineEnd + lineBreakLength
    ) {
      mappedPositions[positions[positionIndex].index] = outputLength
        + positions[positionIndex].position - lineEnd;
      positionIndex++;
    }
    output += source.slice(lineEnd, lineEnd + lineBreakLength);
    outputLength += lineBreakLength;
    inputStart = lineEnd + lineBreakLength;
  }

  return { text: output, positions: mappedPositions };
}

/** @param {string} source @param {number} cursor @param {number[]} [selection] */
export function formatAfterInput(source, cursor, selection = [cursor]) {
  if (!AUTO_FORMAT_TRIGGERS.includes(source.charAt(cursor - 1))) {
    return { text: source, positions: selection, changed: false };
  }
  const result = formatJpsSource(source, selection);
  return {
    ...result,
    changed: result.text !== source,
  };
}
