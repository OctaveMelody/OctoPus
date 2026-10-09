import {formatJpsSource} from "../editor/jp-format.js";
import {createSourceOffsetMap} from "./source-mapping.js";
/** Regions are pixel edge boxes [left,top,right,bottom], not width/height. */
/** @param {number[][]} boxes @param {{width:number,height:number}|undefined} dimensions */
export function normalizedIssueRegions(boxes, dimensions) {
  if (!dimensions || dimensions.width <= 0 || dimensions.height <= 0) return [];
  return boxes.map(box => [box[0] / dimensions.width, box[1] / dimensions.height,
    box[2] / dimensions.width, box[3] / dimensions.height].map(value => Math.max(0, Math.min(1, value))))
    .filter(box => box.every(Number.isFinite) && box[2] > box[0] && box[3] > box[1]);
}
/** @param {string} source @param {{source_start?:number|null,source_end?:number|null}} issue */
export function issueSourceRange(source, issue) {
  if (issue.source_start == null || issue.source_end == null || issue.source_end <= issue.source_start) return null;
  const map = createSourceOffsetMap(source);
  const from = map.codePointToUtf16(issue.source_start);
  const to = map.codePointToUtf16(issue.source_end);
  return from === null || to === null ? null : {from, to};
}

/** Preserve source ownership if append auto-format changes whitespace. Unknown edits lose spans. */
/** @template {{source_start?:number|null,source_end?:number|null}} T
 * @param {string} raw @param {string} actual @param {T[]} issues @returns {T[]} */
export function mapFormattedIssueSpans(raw, actual, issues) {
  if (raw === actual) return issues;
  const before = createSourceOffsetMap(raw);
  const points = issues.flatMap(issue => [issue.source_start, issue.source_end].map(
    offset => offset == null ? 0 : before.codePointToUtf16(offset) ?? 0,
  ));
  /** @param {string} text */
  const normalizeLines = text => text.replace(/\r\n|\r|\n/g, "\n");
  const normalizedActual = normalizeLines(actual);
  const formatted = normalizeLines(raw) === normalizedActual
    ? {text: raw, positions: points}
    : formatJpsSource(raw, points);
  const formattedText = normalizeLines(formatted.text);
  const after = createSourceOffsetMap(actual);
  return issues.map((issue, index) => {
    let from = sourceOffsetFromNormalizedLines(actual,
      normalizeLines(formatted.text.slice(0, formatted.positions[index*2])).length);
    let to = sourceOffsetFromNormalizedLines(actual,
      normalizeLines(formatted.text.slice(0, formatted.positions[index*2+1])).length);
    const valid = formattedText === normalizedActual && from !== null && to !== null
      && issue.source_start != null && issue.source_end != null
      && issue.source_end > issue.source_start && before.codePointToUtf16(issue.source_start) !== null
      && before.codePointToUtf16(issue.source_end) !== null;
    if (!valid || from === null || to === null) {
      return {...issue, source_start: null, source_end: null};
    }
    while (from < to && /\s/.test(actual[from])) from++;
    while (to > from && /\s/.test(actual[to-1])) to--;
    return {...issue, source_start: to > from ? after.utf16ToCodePoint(from) : null,
      source_end: to > from ? after.utf16ToCodePoint(to) : null};
  });
}

/** Map a normalized UTF-16 offset back to the serialized source without changing line endings.
 * @param {string} source @param {number} offset
 */
function sourceOffsetFromNormalizedLines(source, offset) {
  if (!Number.isSafeInteger(offset) || offset < 0) return null;
  let sourceStart = 0;
  let normalizedStart = 0;
  for (const match of source.matchAll(/\r\n|\r|\n/g)) {
    const sourceBreak = match.index;
    if (sourceBreak === undefined) return null;
    const normalizedBreak = normalizedStart + sourceBreak - sourceStart;
    if (offset <= normalizedBreak) return sourceStart + offset - normalizedStart;
    sourceStart = sourceBreak + match[0].length;
    normalizedStart = normalizedBreak + 1;
    if (offset === normalizedStart) return sourceStart;
  }
  const sourceOffset = sourceStart + offset - normalizedStart;
  return sourceOffset <= source.length ? sourceOffset : null;
}
