import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";

import {
  createPdfPageMetadata,
  boundedPdfRenderScale,
  MAX_PDF_PAGES,
  MAX_REFERENCE_PAGES,
  validatePdfLimits,
} from "./pdf-policy.js";

const MAX_OPEN_PDF_DOCUMENTS = 2;
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

type CachedDocument = {
  task: PDFDocumentLoadingTask;
  promise: Promise<PDFDocumentProxy>;
  lastUsed: number;
  activeUsers: number;
};

type PdfDocumentLease = {
  document: PDFDocumentProxy;
  release(): void;
};

let accessCounter = 0;
const documents = new Map<string, CachedDocument>();

export class UnsupportedPdfError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedPdfError";
  }
}

/** @param {string} assetUrl */
async function acquirePdfDocument(assetUrl: string): Promise<PdfDocumentLease> {
  let cached = documents.get(assetUrl);
  if (!cached) {
    const baseUrl = import.meta.env.BASE_URL;
    const task = pdfjs.getDocument({
      url: assetUrl,
      cMapUrl: `${baseUrl}pdfjs/cmaps/`,
      cMapPacked: true,
      iccUrl: `${baseUrl}pdfjs/iccs/`,
      standardFontDataUrl: `${baseUrl}pdfjs/standard_fonts/`,
      wasmUrl: `${baseUrl}pdfjs/wasm/`,
      isEvalSupported: false,
      enableXfa: false,
      maxImageSize: 40_000_000,
      stopAtErrors: true,
      useWorkerFetch: true,
      disableAutoFetch: true,
      disableStream: true,
      verbosity: pdfjs.VerbosityLevel.ERRORS,
    });
    cached = { task, promise: task.promise, lastUsed: ++accessCounter, activeUsers: 0 };
    documents.set(assetUrl, cached);
    cached.promise = cached.promise.catch(async (error: unknown) => {
      if (documents.get(assetUrl) === cached) documents.delete(assetUrl);
      try {
        await task.destroy();
      } catch {
        // Preserve the parse/password error if teardown also fails.
      }
      if (isPasswordRequired(error)) {
        throw new UnsupportedPdfError("password-protected PDFs are not supported");
      }
      throw error;
    });
  }
  const entry = cached;
  entry.activeUsers += 1;
  cached.lastUsed = ++accessCounter;
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    entry.activeUsers -= 1;
    evictOldDocuments();
  };
  try {
    const document = await entry.promise;
    if (documents.get(assetUrl) !== entry) throw new Error("PDF document was closed during use");
    if (document.numPages > MAX_PDF_PAGES) {
      release();
      await closePdfDocument(assetUrl);
      throw new RangeError(`PDF exceeds the ${MAX_PDF_PAGES}-page limit`);
    }
    entry.lastUsed = ++accessCounter;
    evictOldDocuments();
    return { document, release };
  } catch (error) {
    release();
    throw error;
  }
}

/** @param {string} assetUrl @param {{id: string, name: string, byteLength: number, sha256: string}} pdf */
export async function inspectPdfDocument(
  assetUrl: string,
  pdf: { id: string; name: string; byteLength: number; sha256: string },
  remainingPageLimit = MAX_REFERENCE_PAGES,
) {
  const lease = await acquirePdfDocument(assetUrl);
  try {
    const { document } = lease;
    validatePdfLimits(pdf.byteLength, document.numPages, remainingPageLimit);
    const pages = [];
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      pages.push(createPdfPageMetadata(pdf.id, pdf.name, page));
    }
    return {
      ...pdf,
      pageCount: document.numPages,
      pages,
    };
  } finally {
    lease.release();
  }
}

/** @param {string} assetUrl @param {number} pageNumber @param {number} scale @param {HTMLCanvasElement} canvas @param {AbortSignal} signal */
export async function renderPdfPage(
  assetUrl: string,
  pageNumber: number,
  scale: number,
  canvas: HTMLCanvasElement,
  signal: AbortSignal,
) {
  if (!Number.isFinite(scale) || scale <= 0) throw new RangeError("PDF render scale is invalid");
  const lease = await acquirePdfDocument(assetUrl);
  let page: PDFPageProxy | undefined;
  try {
    throwIfAborted(signal);
    page = await lease.document.getPage(pageNumber);
    throwIfAborted(signal);
    const cssViewport = page.getViewport({ scale });
    const outputScale = boundedPdfRenderScale(
      cssViewport.width,
      cssViewport.height,
      window.devicePixelRatio || 1,
    );
    const renderViewport = page.getViewport({ scale: scale * outputScale });
    canvas.width = Math.max(1, Math.floor(renderViewport.width));
    canvas.height = Math.max(1, Math.floor(renderViewport.height));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("PDF canvas is unavailable");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    const renderTask = page.render({
      canvas,
      canvasContext: context,
      viewport: renderViewport,
      annotationMode: pdfjs.AnnotationMode.DISABLE,
      background: "#fff",
    });
    const cancel = () => renderTask.cancel();
    signal.addEventListener("abort", cancel, { once: true });
    try {
      throwIfAborted(signal);
      await renderTask.promise;
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  } finally {
    try {
      page?.cleanup();
    } finally {
      lease.release();
    }
  }
}

/** @param {string} assetUrl */
export async function closePdfDocument(assetUrl: string) {
  const cached = documents.get(assetUrl);
  if (!cached) return;
  documents.delete(assetUrl);
  await cached.task.destroy();
}

export async function closeAllPdfDocuments() {
  await Promise.all([...documents.keys()].map(closePdfDocument));
}

function evictOldDocuments() {
  while (documents.size > MAX_OPEN_PDF_DOCUMENTS) {
    const leastRecentlyUsed = [...documents.entries()]
      .filter(([, cached]) => cached.activeUsers === 0)
      .sort((left, right) => left[1].lastUsed - right[1].lastUsed)[0];
    if (!leastRecentlyUsed) return;
    const [url, cached] = leastRecentlyUsed;
    documents.delete(url);
    void cached.task.destroy().catch(() => {});
  }
}

function isPasswordRequired(error: unknown) {
  return Boolean(
    error
    && typeof error === "object"
    && "name" in error
    && error.name === "PasswordException",
  );
}

function throwIfAborted(signal: AbortSignal) {
  if (signal.aborted) throw new DOMException("PDF rendering was canceled", "AbortError");
}
