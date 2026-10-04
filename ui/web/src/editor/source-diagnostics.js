import { createSourceOffsetMap } from "../workspace/source-mapping.js";

/**
 * Convert parser codepoint spans to CodeMirror UTF-16 positions. CodeMirror stores every
 * configured line separator as one internal character, even when sliceDoc returns CRLF.
 * @param {string} source
 * @param {import('../workspace/types').RenderDiagnostic[]} diagnostics
 */
export function sourceDiagnosticRanges(source, diagnostics) {
  const offsets = createSourceOffsetMap(source);
  const separator = source.match(/\r\n|\r|\n/)?.[0] ?? "\n";
  const normalized = source.split(separator).join("\n");
  /** @param {number} serializedOffset */
  const editorOffset = (serializedOffset) => source.slice(0, serializedOffset).split(separator).join("\n").length;
  return diagnostics.flatMap((diagnostic) => {
    if (!diagnostic.span || typeof diagnostic.message !== "string") return [];
    const serializedFrom = offsets.codePointToUtf16(diagnostic.span.start.offset);
    const serializedTo = offsets.codePointToUtf16(diagnostic.span.end.offset);
    if (serializedFrom === null || serializedTo === null || serializedFrom > serializedTo) return [];
    const from = editorOffset(serializedFrom);
    const to = editorOffset(serializedTo);
    // Use offsets, not a potentially mismatched line number, as the single positioning authority.
    const lineFrom = from === 0 ? 0 : normalized.lastIndexOf("\n", from - 1) + 1;
    return [{ from, to, lineFrom,
      severity: diagnostic.severity === "error" || diagnostic.severity === "warning"
        ? diagnostic.severity : "info",
      message: diagnostic.code ? `${diagnostic.code}: ${diagnostic.message}` : diagnostic.message }];
  });
}

/**
 * Debounce cheap parse requests and discard responses from superseded documents/revisions.
 * @template T
 * @template R
 * @param {(request: T) => Promise<R>} check
 * @param {(request: T, result: R) => void} accept
 * @param {(error: unknown) => void} onError
 * @param {{delay?: number, setTimer?: typeof setTimeout, clearTimer?: typeof clearTimeout}} [options]
 */
export function createSourceDiagnosticsQueue(check, accept, onError, options = {}) {
  const setTimer = options.setTimer ?? setTimeout;
  const clearTimer = options.clearTimer ?? clearTimeout;
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let timer;
  let generation = 0;
  return {
    /** @param {T} request */
    request(request) {
      const ownGeneration = ++generation;
      if (timer !== undefined) clearTimer(timer);
      timer = setTimer(() => {
        timer = undefined;
        void Promise.resolve().then(() => check(request)).then((result) => {
          if (ownGeneration === generation) accept(request, result);
        }).catch((error) => {
          if (ownGeneration === generation) onError(error);
        });
      }, options.delay ?? 300);
    },
    cancel() {
      generation++;
      if (timer !== undefined) clearTimer(timer);
      timer = undefined;
    },
  };
}

/** @param {number} blockHeight @param {number} lineHeight */
export function wrappedContinuationCount(blockHeight, lineHeight) {
  if (!Number.isFinite(blockHeight) || !Number.isFinite(lineHeight) || lineHeight <= 0) return 0;
  return Math.max(0, Math.round(blockHeight / lineHeight) - 1);
}
