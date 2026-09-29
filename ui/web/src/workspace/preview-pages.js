/** @typedef {{line: number, column: number, offset: number}} SourcePosition */
/** @typedef {{start: SourcePosition, end: SourcePosition}} SourceSpan */
/** @typedef {{event_index: number, event_kind: string, source_span: SourceSpan, voice: number, row: number, slot: number, x: number, y: number}} PageEvent */
/** @typedef {{source_spans: SourceSpan[], voice: number, row: number, slot: number, verse: number, annotation: boolean, x: number, y: number}} PageLyric */
/** @typedef {{page_index: number, page_count: number, page_width: number, page_height: number, svg: string, source_offset_unit: "codepoint", events: PageEvent[], lyrics: PageLyric[], diagnostics: {code: string, message: string, severity: string}[], custom_markup_omitted: boolean}} RenderedPage */
/** @typedef {{status: "ok" | "error", result?: RenderedPage, error?: {code: string, message: string, page_count?: number}}} PageResponse */
/** @typedef {{documentId: string, revision: number, pageCount: number, pages: Map<number, RenderedPage>}} PageCache */

export class PageOutOfRangeError extends Error {
  /** @param {number} pageCount */
  constructor(pageCount) {
    super("page_index is outside the document");
    this.name = "PageOutOfRangeError";
    this.pageCount = pageCount;
  }
}

/** @param {string} svg */
export function svgPreviewDataUrl(svg) {
  // WebKitGTK needs explicit image dimensions and valid XML entities for data URLs.
  // This repair affects display only; saved SVG bytes stay unchanged.
  const escaped = svg.replace(/&(?!(?:amp|lt|gt|quot|apos|#\d+|#[xX][0-9a-fA-F]+);)/g, "&amp;");
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(escaped)}`;
}

/** @param {{width: number, height: number}} viewport @param {RenderedPage} page */
export function pageFitScale(viewport, page) {
  return Math.min(
    1,
    viewport.height * page.page_width / page.page_height / viewport.width,
  );
}

/** @param {PageCache | null} cache @param {{id: string, revision: number}} document @param {RenderedPage} page */
export function cacheRenderedPage(cache, document, page) {
  const matches = cache?.documentId === document.id && cache.revision === document.revision;
  if (matches && cache.pageCount !== page.page_count) {
    throw new Error("Page count changed during one document revision.");
  }
  const pages = matches ? new Map(cache.pages) : new Map();
  pages.set(page.page_index, page);
  return {
    documentId: document.id,
    revision: document.revision,
    pageCount: page.page_count,
    pages,
  };
}

/**
 * Render the visible page first, then cache the remaining pages until superseded.
 * @template Document
 * @param {{document: Document, pageIndex: number}} request
 * @param {(document: Document, pageIndex: number) => Promise<PageResponse>} renderPage
 * @param {(page: RenderedPage) => void} onPage
 * @param {() => boolean} isLatest
 * @returns {Promise<RenderedPage>}
 */
export async function renderPagesProgressively(request, renderPage, onPage, isLatest) {
  const first = unwrapPage(await renderPage(request.document, request.pageIndex), request.pageIndex);
  if (!isLatest()) return first;
  onPage(first);

  for (let pageIndex = 0; pageIndex < first.page_count; pageIndex += 1) {
    if (pageIndex === request.pageIndex) continue;
    if (!isLatest()) break;
    const page = unwrapPage(await renderPage(request.document, pageIndex), pageIndex);
    if (page.page_count !== first.page_count) {
      throw new Error("Page count changed during one document revision.");
    }
    if (!isLatest()) break;
    onPage(page);
  }
  return first;
}

/** @param {PageResponse} response @param {number} pageIndex @returns {RenderedPage} */
function unwrapPage(response, pageIndex) {
  if (response.status === "error") {
    const error = response.error;
    if (
      error?.code === "page_out_of_range"
      && typeof error.page_count === "number"
      && Number.isSafeInteger(error.page_count)
      && error.page_count >= 0
    ) {
      throw new PageOutOfRangeError(error.page_count);
    }
    throw new Error(`${error?.code ?? "render_failed"}: ${error?.message ?? "Render failed"}`);
  }
  const page = response.result;
  if (
    response.status !== "ok"
    || !page
    || page.page_index !== pageIndex
    || !Number.isSafeInteger(page.page_count)
    || page.page_count < 1
    || !Number.isSafeInteger(page.page_width)
    || page.page_width < 1
    || !Number.isSafeInteger(page.page_height)
    || page.page_height < 1
    || pageIndex < 0
    || pageIndex >= page.page_count
    || typeof page.svg !== "string"
    || !page.svg
    || page.source_offset_unit !== "codepoint"
    || !Array.isArray(page.events)
    || !page.events.every(isEventAnchor)
    || !Array.isArray(page.lyrics)
    || !page.lyrics.every(isLyricAnchor)
    || !Array.isArray(page.diagnostics)
    || !page.diagnostics.every(isDiagnostic)
    || typeof page.custom_markup_omitted !== "boolean"
  ) {
    throw new Error("The renderer returned an invalid page result.");
  }
  return page;
}

/** @param {any} diagnostic */
function isDiagnostic(diagnostic) {
  return typeof diagnostic?.code === "string"
    && typeof diagnostic.message === "string"
    && typeof diagnostic.severity === "string"
    && (diagnostic.span === undefined || isSourceSpan(diagnostic.span))
    && (diagnostic.recovery === undefined || typeof diagnostic.recovery === "string");
}

/** @param {any} event */
function isEventAnchor(event) {
  return Number.isSafeInteger(event?.event_index)
    && typeof event.event_kind === "string"
    && isSourceSpan(event.source_span)
    && Number.isFinite(event.x)
    && Number.isFinite(event.y)
    && Number.isSafeInteger(event.voice)
    && Number.isSafeInteger(event.row)
    && Number.isSafeInteger(event.slot);
}

/** @param {any} lyric */
function isLyricAnchor(lyric) {
  return Array.isArray(lyric?.source_spans)
    && lyric.source_spans.length > 0
    && lyric.source_spans.every(isSourceSpan)
    && Number.isFinite(lyric.x)
    && Number.isFinite(lyric.y)
    && Number.isSafeInteger(lyric.voice)
    && Number.isSafeInteger(lyric.row)
    && Number.isSafeInteger(lyric.slot)
    && Number.isSafeInteger(lyric.verse)
    && typeof lyric.annotation === "boolean";
}

/** @param {any} span */
function isSourceSpan(span) {
  return Number.isSafeInteger(span?.start?.line)
    && span.start.line >= 1
    && Number.isSafeInteger(span.start.column)
    && span.start.column >= 1
    && Number.isSafeInteger(span?.start?.offset)
    && Number.isSafeInteger(span?.end?.offset)
    && Number.isSafeInteger(span?.end?.line)
    && span.end.line >= span.start.line
    && Number.isSafeInteger(span.end.column)
    && span.end.column >= 1
    && span.start.offset >= 0
    && span.start.offset <= span.end.offset;
}
