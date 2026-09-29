export const MAX_PDF_BYTES = 100 * 1024 * 1024;
export const MAX_PDF_PAGES = 200;
export const MAX_PDF_PAGE_PIXELS = 40_000_000;
export const MAX_PDF_PAGE_DIMENSION = 50_000;
export const MAX_REFERENCE_PAGES = 200;

/**
 * @param {number} byteLength
 * @param {number} pageCount
 * @param {number} [remainingReferencePages]
 */
export function validatePdfLimits(
  byteLength,
  pageCount,
  remainingReferencePages = MAX_REFERENCE_PAGES,
) {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 || byteLength > MAX_PDF_BYTES) {
    throw new RangeError("PDF file size is outside the supported limit");
  }
  if (!Number.isSafeInteger(pageCount) || pageCount < 1 || pageCount > MAX_PDF_PAGES) {
    throw new RangeError("PDF page count is outside the supported limit");
  }
  if (
    !Number.isSafeInteger(remainingReferencePages)
    || remainingReferencePages < 0
    || remainingReferencePages > MAX_REFERENCE_PAGES
  ) throw new RangeError("remaining reference page limit is invalid");
  if (pageCount > remainingReferencePages) {
    throw new RangeError(`reference import exceeds the ${MAX_REFERENCE_PAGES}-page limit`);
  }
}

/** @param {number} width @param {number} height @param {number} deviceScale */
export function boundedPdfRenderScale(width, height, deviceScale) {
  if (
    !Number.isFinite(width)
    || !Number.isFinite(height)
    || width <= 0
    || height <= 0
    || !Number.isFinite(deviceScale)
    || deviceScale <= 0
  ) throw new RangeError("PDF render dimensions are invalid");
  return Math.min(
    2,
    deviceScale,
    MAX_PDF_PAGE_DIMENSION / width,
    MAX_PDF_PAGE_DIMENSION / height,
    Math.sqrt(MAX_PDF_PAGE_PIXELS / (width * height)),
  );
}

/** @param {string} pdfId @param {string} pdfName @param {import("pdfjs-dist").PDFPageProxy} page */
export function createPdfPageMetadata(pdfId, pdfName, page) {
  if (!/^pdf-[A-Za-z0-9]+\.pdf$/.test(pdfId)) throw new TypeError("managed PDF ID is invalid");
  if (!Number.isSafeInteger(page.pageNumber) || page.pageNumber < 1) {
    throw new TypeError("PDF page number is invalid");
  }
  const pageBox = Array.from(page.view);
  const viewport = page.getViewport({ scale: 1 });
  const transform = Array.from(viewport.transform);
  const rotation = ((page.rotate % 360) + 360) % 360;
  const width = Math.ceil(viewport.width);
  const height = Math.ceil(viewport.height);
  if (
    pageBox.length !== 4
    || pageBox.some((coordinate) => !Number.isFinite(coordinate) || Math.abs(coordinate) > 1_000_000)
    || transform.length !== 6
    || transform.some((coordinate) => !Number.isFinite(coordinate))
    || ![0, 90, 180, 270].includes(rotation)
    || !Number.isSafeInteger(width)
    || !Number.isSafeInteger(height)
    || width < 1
    || height < 1
    || width > MAX_PDF_PAGE_DIMENSION
    || height > MAX_PDF_PAGE_DIMENSION
    || width * height > MAX_PDF_PAGE_PIXELS
  ) throw new RangeError("PDF page dimensions are outside the supported limit");

  return {
    id: `pdfpage-${pdfId.slice(4, -4)}-${page.pageNumber}`,
    kind: "pdf-page",
    name: pdfName,
    pdfId,
    pageNumber: page.pageNumber,
    pageBox,
    pageRotation: rotation,
    renderScale: 1,
    transform,
    width,
    height,
    orientation: 1,
  };
}
