/** @typedef {{id: string, name: string, path: string | null, suggestedPath: string | null, source: string, savedSource: string, savedFileText: string | null, wrapperFields: Record<string, unknown>, customCode: string, pageConfig: Record<string, unknown>, savedPageConfig: Record<string, unknown>, jsonWrapped: boolean, revision: number, saveSequence: number}} DocumentSession */
/** @typedef {{documentId: string, revision: number, saveSequence: number, name: string, path: string | null, suggestedPath: string | null, source: string, wrapperFields: Record<string, unknown>, pageConfig: Record<string, unknown>, pageConfigChanged: boolean, jsonWrapped: boolean}} SaveSnapshot */

/** @param {{id: string, name: string, source: string, path?: string | null, suggestedPath?: string | null, savedSource?: string, savedFileText?: string | null, wrapperFields?: Record<string, unknown>, customCode?: string, pageConfig?: Record<string, unknown>, savedPageConfig?: Record<string, unknown>, jsonWrapped?: boolean, revision?: number}} input @returns {DocumentSession} */
export function createDocumentSession({
  id,
  name,
  source,
  path = null,
  suggestedPath = path,
  savedSource = source,
  savedFileText = null,
  wrapperFields = {},
  customCode = "",
  pageConfig = {},
  savedPageConfig = pageConfig,
  jsonWrapped = false,
  revision = 0,
}) {
  if (
    !id
    || !name.trim()
    || typeof source !== "string"
    || !Number.isSafeInteger(revision)
    || revision < 0
  ) {
    throw new TypeError("document identity, name and source are required");
  }
  return {
    id,
    name,
    path,
    suggestedPath,
    source,
    savedSource,
    savedFileText,
    wrapperFields,
    customCode,
    pageConfig,
    savedPageConfig,
    jsonWrapped,
    revision,
    saveSequence: 0,
  };
}

/** @param {DocumentSession} document @param {string} source @returns {DocumentSession} */
export function updateDocumentSource(document, source) {
  if (source === document.source) return document;
  return { ...document, source, revision: document.revision + 1 };
}

/** @param {DocumentSession} document @param {Record<string, unknown>} pageConfig @returns {DocumentSession} */
export function updateDocumentPageConfig(document, pageConfig) {
  if (samePageConfig(pageConfig, document.pageConfig)) return document;
  return { ...document, pageConfig, revision: document.revision + 1 };
}

/** @param {DocumentSession} document @param {{documentId: string, revision: number}} snapshot */
export function isCurrentDocumentRevision(document, snapshot) {
  return document.id === snapshot.documentId && document.revision === snapshot.revision;
}

/** @param {DocumentSession} document @returns {boolean} */
export function isPageConfigDirty(document) {
  return !samePageConfig(document.pageConfig, document.savedPageConfig);
}

/** @param {DocumentSession} document @returns {boolean} */
export function isDocumentDirty(document) {
  return document.source !== document.savedSource
    || isPageConfigDirty(document);
}

/** @param {DocumentSession} document @param {{name: string, path: string | null}} target */
export function beginDocumentSave(document, target) {
  if (!target.name.trim() || (target.path !== null && !target.path.trim())) {
    throw new TypeError("save target name is required and path must be valid when present");
  }
  const nextDocument = { ...document, saveSequence: document.saveSequence + 1 };
  const pageConfigChanged = !samePageConfig(document.pageConfig, document.savedPageConfig);
  const snapshot = {
    documentId: document.id,
    revision: document.revision,
    saveSequence: nextDocument.saveSequence,
    name: target.name,
    path: target.path,
    suggestedPath: document.suggestedPath,
    source: document.source,
    wrapperFields: document.wrapperFields,
    pageConfig: document.pageConfig,
    pageConfigChanged,
    jsonWrapped: document.jsonWrapped || pageConfigChanged,
  };
  return { document: nextDocument, snapshot };
}

/** @param {DocumentSession} document @param {SaveSnapshot} snapshot @param {string | null} [savedFileText] @returns {DocumentSession} */
export function finishDocumentSave(document, snapshot, savedFileText = document.savedFileText) {
  if (document.id !== snapshot.documentId || document.saveSequence !== snapshot.saveSequence) {
    return document;
  }
  return {
    ...document,
    name: snapshot.name,
    path: snapshot.path,
    suggestedPath: snapshot.suggestedPath,
    savedSource: snapshot.source,
    savedPageConfig: snapshot.pageConfig,
    wrapperFields: snapshot.pageConfigChanged
      ? { ...snapshot.wrapperFields, page_config: snapshot.pageConfig }
      : snapshot.wrapperFields,
    jsonWrapped: snapshot.jsonWrapped,
    savedFileText,
  };
}

/** @param {Record<string, unknown>} left @param {Record<string, unknown>} right */
function samePageConfig(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}
