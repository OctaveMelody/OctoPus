/** @typedef {"D" | "P" | "J"} HeaderField */
/** @typedef {{offset: number, line: number, column: number}} SourcePosition */
/** @typedef {{start: SourcePosition, end: SourcePosition}} SourceSpan */
/** @typedef {{prefix: string, value: string, span: SourceSpan}} HeaderLine */
/** @typedef {{line: number, token: number, nested_token_path?: number[]}} MusicPosition */
/** @typedef {{value: string, span: SourceSpan, music_position: MusicPosition}} MusicAnnotation */
/** @typedef {{source_offset_unit: "codepoint", music_start_offset: number | null, header_lines: HeaderLine[], music_annotations: MusicAnnotation[]}} ParsedScore */

const HEADER_FIELDS = /** @type {const} */ (["D", "P", "J"]);
const INLINE_HEADER = /(?:^|[^A-Za-z])[DPJ]\s*:/i;

/** Return a localized-error key when headers would be lost or cannot be compared. */
/** @param {string} destinationSource @param {unknown} destination @param {unknown} draft */
export function transcriptionAppendIssue(destinationSource, destination, draft) {
  if (!destinationSource.trim()) return null;
  if (!isParsedScore(destination) || !isParsedScore(draft)) return "cannot-verify";
  // Keep the existing no-music error in App.adoptTranscription as the first diagnosis.
  if (draft.music_start_offset === null) return null;
  if (hasInlineHeader(destination) || hasInlineHeader(draft)) return "cannot-verify";

  const destinationFields = headerValues(destination);
  const draftFields = headerValues(draft);
  if (!destinationFields || !draftFields) return "cannot-verify";
  for (const field of HEADER_FIELDS) {
    const value = draftFields[field];
    if (!value) continue;
    const destinationValue = destinationFields[field];
    if (!destinationValue) return "cannot-verify";
    if (destinationValue !== value) return "conflict";
  }
  return null;
}

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** @param {unknown} value @returns {value is ParsedScore} */
function isParsedScore(value) {
  if (!isRecord(value) || value.source_offset_unit !== "codepoint") return false;
  return (value.music_start_offset === null || isNonnegativeSafeInteger(value.music_start_offset))
    && Array.isArray(value.header_lines)
    && value.header_lines.every(isHeaderLine)
    && Array.isArray(value.music_annotations)
    && value.music_annotations.every(isMusicAnnotation);
}

/** @param {unknown} value @returns {value is HeaderLine} */
function isHeaderLine(value) {
  return isRecord(value) && typeof value.prefix === "string"
    && typeof value.value === "string" && isSourceSpan(value.span);
}

/** @param {unknown} value @returns {value is MusicAnnotation} */
function isMusicAnnotation(value) {
  return isRecord(value) && typeof value.value === "string"
    && isSourceSpan(value.span) && isMusicPosition(value.music_position);
}

/** @param {unknown} value @returns {value is MusicPosition} */
function isMusicPosition(value) {
  if (!isRecord(value) || !isNonnegativeSafeInteger(value.line)
    || !isNonnegativeSafeInteger(value.token)) return false;
  return value.nested_token_path === undefined
    || (Array.isArray(value.nested_token_path) && value.nested_token_path.every(isNonnegativeSafeInteger));
}

/** @param {unknown} value @returns {value is number} */
function isNonnegativeSafeInteger(value) {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

/** @param {unknown} value @returns {value is SourcePosition} */
function isSourcePosition(value) {
  return isRecord(value) && isNonnegativeSafeInteger(value.offset)
    && isNonnegativeSafeInteger(value.line) && value.line >= 1
    && isNonnegativeSafeInteger(value.column) && value.column >= 1;
}

/** @param {unknown} span @returns {span is SourceSpan} */
function isSourceSpan(span) {
  return isRecord(span) && isSourcePosition(span.start) && isSourcePosition(span.end)
    && span.end.offset >= span.start.offset && span.end.line >= span.start.line;
}

/** @param {ParsedScore} score */
function hasInlineHeader(score) {
  return score.music_annotations.some(annotation => INLINE_HEADER.test(annotation.value));
}

/** @param {ParsedScore} score @returns {Partial<Record<HeaderField, string>> | null} */
function headerValues(score) {
  /** @type {Partial<Record<HeaderField, string>>} */
  const values = {};
  for (const header of score.header_lines) {
    if (!isHeaderField(header.prefix)) continue;
    if (score.music_start_offset === null
      || header.span.start.offset > score.music_start_offset) return null;
    const value = header.value.trim().replace(/\s+/gu, " ");
    if (Object.hasOwn(values, header.prefix) && values[header.prefix] !== value) return null;
    values[header.prefix] = value;
  }
  return values;
}

/** @param {string} prefix @returns {prefix is HeaderField} */
function isHeaderField(prefix) {
  return HEADER_FIELDS.some(field => field === prefix);
}
