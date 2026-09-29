import { MAX_PDF_PAGES, MAX_REFERENCE_PAGES } from "../reference/pdf-policy.js";

const MAX_IMAGE_BYTES = 100 * 1024 * 1024;
const MAX_IMAGE_PIXELS = 40_000_000;
const MAX_IMAGE_DIMENSION = 50_000;
const MAX_REFERENCE_SET_BYTES = 500 * 1024 * 1024;
const PDF_ASSET_ID = /^pdf-[A-Za-z0-9]+\.pdf$/;
const PDF_HASH = /^[a-f0-9]{64}$/;
const SAFE_ASSET_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** @typedef {{kind: "image", id: string, name: string, mimeType: "image/png" | "image/jpeg", byteLength: number, width: number, height: number, orientation: number}} ReferenceImage */
/** @typedef {{id: string, name: string, byteLength: number, sha256: string, pageCount: number}} ReferencePdf */
/** @typedef {{id: string, kind: "pdf-page", name: string, pdfId: string, pageNumber: number, pageBox: number[], pageRotation: number, renderScale: 1, transform: number[], width: number, height: number, orientation: 1}} ReferencePdfPage */
/** @typedef {ReferenceImage | ReferencePdfPage} ReferencePage */
/** @typedef {{fit: "page" | "width" | "custom", zoom: number, rotation: number, panX: number, panY: number}} ReferenceView */
/** @typedef {{images: ReferencePage[], pdfs: ReferencePdf[], selectedId: string | null, views: Record<string, ReferenceView>}} ReferenceSet */

/** @returns {ReferenceSet} */
export function createReferenceSet() {
  return { images: [], pdfs: [], selectedId: null, views: {} };
}

/** @returns {ReferenceView} */
function defaultView() {
  return { fit: "width", zoom: 1, rotation: 0, panX: 0, panY: 0 };
}

/** @param {unknown} value @returns {ReferenceImage} */
function validateImage(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("reference image is invalid");
  }
  const image = /** @type {Record<string, unknown>} */ (value);
  if (
    typeof image.id !== "string"
    || !SAFE_ASSET_ID.test(image.id)
    || image.id.includes("..")
    || ["__proto__", "constructor", "prototype"].includes(image.id)
    || typeof image.name !== "string"
    || (image.kind !== undefined && image.kind !== "image")
    || !image.name.trim()
    || image.name.length > 255
    || /[\\/\0]/.test(image.name)
    || (image.mimeType !== "image/png" && image.mimeType !== "image/jpeg")
  ) throw new TypeError("reference image metadata is invalid");

  const { byteLength, width, height, orientation } = image;
  if (
    typeof byteLength !== "number"
    || !Number.isSafeInteger(byteLength)
    || byteLength < 1
    || byteLength > MAX_IMAGE_BYTES
    || typeof width !== "number"
    || !Number.isSafeInteger(width)
    || width < 1
    || typeof height !== "number"
    || !Number.isSafeInteger(height)
    || height < 1
    || width * height > MAX_IMAGE_PIXELS
    || typeof orientation !== "number"
    || !Number.isInteger(orientation)
    || orientation < 1
    || orientation > 8
  ) throw new TypeError("reference image dimensions or limits are invalid");

  return {
    kind: "image",
    id: image.id,
    name: image.name,
    mimeType: image.mimeType,
    byteLength,
    width,
    height,
    orientation,
  };
}

/** @param {unknown} value @returns {ReferencePdf} */
function validatePdf(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("reference PDF is invalid");
  }
  const pdf = /** @type {Record<string, unknown>} */ (value);
  if (
    typeof pdf.id !== "string"
    || !PDF_ASSET_ID.test(pdf.id)
    || typeof pdf.name !== "string"
    || !pdf.name.trim()
    || pdf.name.length > 255
    || /[\\/\0]/.test(pdf.name)
    || typeof pdf.sha256 !== "string"
    || !PDF_HASH.test(pdf.sha256)
    || typeof pdf.byteLength !== "number"
    || !Number.isSafeInteger(pdf.byteLength)
    || pdf.byteLength < 1
    || pdf.byteLength > MAX_IMAGE_BYTES
    || typeof pdf.pageCount !== "number"
    || !Number.isSafeInteger(pdf.pageCount)
    || pdf.pageCount < 1
    || pdf.pageCount > MAX_PDF_PAGES
  ) throw new TypeError("reference PDF metadata is invalid");

  return {
    id: pdf.id,
    name: pdf.name,
    byteLength: pdf.byteLength,
    sha256: pdf.sha256,
    pageCount: pdf.pageCount,
  };
}

/** @param {unknown} value @returns {ReferencePdfPage} */
function validatePdfPage(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("reference PDF page is invalid");
  }
  const page = /** @type {Record<string, unknown>} */ (value);
  const pageBox = page.pageBox;
  const transform = page.transform;
  if (
    page.kind !== "pdf-page"
    || typeof page.id !== "string"
    || !/^pdfpage-[A-Za-z0-9]+-[1-9][0-9]*$/.test(page.id)
    || typeof page.name !== "string"
    || !page.name.trim()
    || page.name.length > 255
    || /[\\/\0]/.test(page.name)
    || typeof page.pdfId !== "string"
    || !PDF_ASSET_ID.test(page.pdfId)
    || typeof page.pageNumber !== "number"
    || !Number.isSafeInteger(page.pageNumber)
    || page.pageNumber < 1
    || page.id !== `pdfpage-${page.pdfId.slice(4, -4)}-${page.pageNumber}`
    || !Array.isArray(pageBox)
    || pageBox.length !== 4
    || pageBox.some((value) => typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) > 1_000_000)
    || ![0, 90, 180, 270].includes(/** @type {number} */ (page.pageRotation))
    || page.renderScale !== 1
    || !Array.isArray(transform)
    || transform.length !== 6
    || transform.some((value) => typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) > 1_000_000)
    || typeof page.width !== "number"
    || !Number.isSafeInteger(page.width)
    || page.width < 1
    || page.width > MAX_IMAGE_DIMENSION
    || typeof page.height !== "number"
    || !Number.isSafeInteger(page.height)
    || page.height < 1
    || page.height > MAX_IMAGE_DIMENSION
    || page.width * page.height > MAX_IMAGE_PIXELS
    || page.orientation !== 1
  ) throw new TypeError("reference PDF page metadata or limits are invalid");

  return {
    id: page.id,
    kind: "pdf-page",
    name: page.name,
    pdfId: page.pdfId,
    pageNumber: page.pageNumber,
    pageBox: /** @type {number[]} */ ([...pageBox]),
    pageRotation: /** @type {number} */ (page.pageRotation),
    renderScale: 1,
    transform: /** @type {number[]} */ ([...transform]),
    width: page.width,
    height: page.height,
    orientation: 1,
  };
}

/** @param {unknown} value @returns {ReferencePage} */
function validatePage(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    && /** @type {Record<string, unknown>} */ (value).kind === "pdf-page"
    ? validatePdfPage(value)
    : validateImage(value);
}

/** @param {unknown} value @param {string} id @returns {ReferenceView} */
function validateView(value, id) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`reference view ${id} is invalid`);
  }
  const view = /** @type {Record<string, unknown>} */ (value);
  if (
    !["page", "width", "custom"].includes(String(view.fit))
    || typeof view.zoom !== "number"
    || !Number.isFinite(view.zoom)
    || view.zoom < 0.25
    || view.zoom > 4
    || typeof view.rotation !== "number"
    || ![0, 90, 180, 270].includes(view.rotation)
    || typeof view.panX !== "number"
    || !Number.isFinite(view.panX)
    || Math.abs(view.panX) > 100_000
    || typeof view.panY !== "number"
    || !Number.isFinite(view.panY)
    || Math.abs(view.panY) > 100_000
  ) throw new TypeError(`reference view ${id} is invalid`);
  return {
    fit: /** @type {ReferenceView["fit"]} */ (view.fit),
    zoom: view.zoom,
    rotation: view.rotation,
    panX: view.panX,
    panY: view.panY,
  };
}

/** @param {unknown} value @returns {ReferenceSet} */
export function validateReferenceSet(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("reference set is invalid");
  }
  const set = /** @type {Record<string, unknown>} */ (value);
  if (
    !Array.isArray(set.images)
    || !Array.isArray(set.pdfs)
    || !set.views
    || typeof set.views !== "object"
    || Array.isArray(set.views)
  ) {
    throw new TypeError("reference set is invalid");
  }
  const images = set.images.map(validatePage);
  const pdfs = set.pdfs.map(validatePdf);
  if (images.length > MAX_REFERENCE_PAGES || pdfs.length > MAX_REFERENCE_PAGES) {
    throw new TypeError("reference page or PDF count exceeds the limit");
  }
  const pdfById = new Map(pdfs.map((pdf) => [pdf.id, pdf]));
  if (pdfById.size !== pdfs.length) throw new TypeError("reference PDF IDs must be unique");
  const imageBytes = images.reduce((total, image) => total + (image.kind === "pdf-page" ? 0 : image.byteLength), 0);
  const pdfBytes = pdfs.reduce((total, pdf) => total + pdf.byteLength, 0);
  if (imageBytes + pdfBytes > MAX_REFERENCE_SET_BYTES) {
    throw new TypeError("reference set exceeds the byte limit");
  }
  const ids = new Set(images.map(({ id }) => id));
  if (ids.size !== images.length) throw new TypeError("reference image IDs must be unique");
  const referencedPdfIds = new Set();
  for (const page of images) {
    if (page.kind !== "pdf-page") continue;
    const pdf = pdfById.get(page.pdfId);
    if (!pdf || page.pageNumber > pdf.pageCount) {
      throw new TypeError("reference PDF page has no matching source");
    }
    referencedPdfIds.add(page.pdfId);
  }
  if (referencedPdfIds.size !== pdfs.length) {
    throw new TypeError("reference PDF source has no pages");
  }
  if (
    (set.selectedId !== null && (typeof set.selectedId !== "string" || !ids.has(set.selectedId)))
    || (images.length === 0 && set.selectedId !== null)
    || (images.length > 0 && set.selectedId === null)
  ) throw new TypeError("selected reference image is invalid");

  const rawViews = /** @type {Record<string, unknown>} */ (set.views);
  if (Object.keys(rawViews).some((id) => !ids.has(id))) {
    throw new TypeError("reference view has no image");
  }
  const views = Object.fromEntries(images.map(({ id }) => [
    id,
    rawViews[id]
      ? validateView(rawViews[id], id)
      : defaultView(),
  ]));
  return { images, pdfs, selectedId: /** @type {string | null} */ (set.selectedId), views };
}

/**
 * @param {string[]} order
 * @param {Array<Record<string, unknown>>} images
 * @param {Array<{id: string, pages: unknown[]}>} parsedPdfs
 */
export function orderStagedReferencePages(order, images, parsedPdfs) {
  const pagesByAssetId = new Map();
  for (const image of images) {
    if (
      !image
      || typeof image !== "object"
      || typeof image.id !== "string"
      || pagesByAssetId.has(image.id)
    ) {
      throw new TypeError("staged reference asset IDs must be unique");
    }
    pagesByAssetId.set(image.id, [{ ...image, kind: "image" }]);
  }
  const pdfs = parsedPdfs.map((pdf) => {
    if (
      !pdf
      || typeof pdf.id !== "string"
      || !Array.isArray(pdf.pages)
      || pagesByAssetId.has(pdf.id)
    ) throw new TypeError("staged PDF metadata or ID is invalid");
    pagesByAssetId.set(pdf.id, pdf.pages);
    const { pages, ...manifest } = pdf;
    return manifest;
  });
  if (
    !Array.isArray(order)
    || order.length !== pagesByAssetId.size
    || new Set(order).size !== order.length
    || order.some((id) => !pagesByAssetId.has(id))
  ) throw new TypeError("staged reference order is incomplete or invalid");
  return {
    pages: order.flatMap((id) => pagesByAssetId.get(id)),
    pdfs,
  };
}

/** @param {ReferenceSet} current @param {unknown[]} staged @param {"add" | "replace" | "cancel"} choice @param {unknown[]} [stagedPdfs] */
export function applyReferenceImport(current, staged, choice, stagedPdfs = []) {
  const referenceSet = validateReferenceSet(current);
  const incoming = staged.map(validatePage);
  const incomingPdfs = stagedPdfs.map(validatePdf);
  if (!["add", "replace", "cancel"].includes(choice)) {
    throw new TypeError("reference import choice is invalid");
  }
  if (choice === "cancel") return current;
  if (incoming.length === 0) throw new TypeError("no reference images were selected");
  if (new Set(incoming.map(({ id }) => id)).size !== incoming.length) {
    throw new TypeError("staged reference image IDs must be unique");
  }
  if (
    choice === "add"
    && incoming.some(({ id }) => referenceSet.images.some((image) => image.id === id))
  ) {
    throw new TypeError("reference image is already in this set");
  }
  const images = choice === "add" ? [...referenceSet.images, ...incoming] : incoming;
  const pdfs = choice === "add" ? [...referenceSet.pdfs, ...incomingPdfs] : incomingPdfs;
  const views = choice === "add" ? { ...referenceSet.views } : {};
  for (const image of incoming) {
    if (!views[image.id]) views[image.id] = defaultView();
  }
  return validateReferenceSet({
    images,
    pdfs,
    selectedId: choice === "add" && referenceSet.selectedId
      ? referenceSet.selectedId
      : incoming[0].id,
    views,
  });
}

/** @param {ReferenceSet} current @param {string} id */
export function selectReferenceImage(current, id) {
  const set = validateReferenceSet(current);
  return set.images.some((image) => image.id === id) && set.selectedId !== id
    ? { ...set, selectedId: id }
    : current;
}

/** @param {ReferenceSet} current @param {string} id @param {number} targetIndex */
export function moveReferenceImage(current, id, targetIndex) {
  const set = validateReferenceSet(current);
  const sourceIndex = set.images.findIndex((image) => image.id === id);
  if (sourceIndex < 0 || !Number.isInteger(targetIndex)) return current;
  const images = [...set.images];
  const [image] = images.splice(sourceIndex, 1);
  images.splice(Math.max(0, Math.min(images.length, targetIndex)), 0, image);
  return images.every((item, index) => item.id === set.images[index].id)
    ? current
    : { ...set, images };
}

/** @param {ReferenceSet} current @param {string} id */
export function removeReferenceImage(current, id) {
  const set = validateReferenceSet(current);
  const index = set.images.findIndex((image) => image.id === id);
  if (index < 0) return { referenceSet: current, removedId: null };
  const images = set.images.filter((image) => image.id !== id);
  const retainedPdfIds = new Set(
    images.flatMap((image) => image.kind === "pdf-page" ? [image.pdfId] : []),
  );
  const views = { ...set.views };
  delete views[id];
  return {
    referenceSet: {
      images,
      pdfs: set.pdfs.filter((pdf) => retainedPdfIds.has(pdf.id)),
      selectedId: set.selectedId === id
        ? images[Math.min(index, images.length - 1)]?.id ?? null
        : set.selectedId,
      views,
    },
    removedId: id,
  };
}

/** @param {ReferenceSet} current @returns {string[]} */
export function referenceAssetIds(current) {
  const set = validateReferenceSet(current);
  return [...new Set(set.images.map((page) => page.kind === "pdf-page" ? page.pdfId : page.id))];
}

/** @param {ReferenceSet} current @param {string} id @param {Partial<ReferenceView>} patch */
export function updateReferenceView(current, id, patch) {
  const set = validateReferenceSet(current);
  if (!set.images.some((image) => image.id === id)) return current;
  const view = set.views[id] ?? defaultView();
  return validateReferenceSet({
    ...set,
    views: { ...set.views, [id]: { ...view, ...patch } },
  });
}
