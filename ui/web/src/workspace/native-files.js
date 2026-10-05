/** @typedef {{name: string, path: string, suggestedPath: string, text: string}} OpenedJpsDocument */
/** @typedef {{name: string, kind: "example" | "working-copy"}} JpsCatalogDocument */
/** @typedef {{path: string | null, suggestedPath?: string | null, suggestedName?: string | null, recentSavedPath?: string | null, expectedText?: string | null, text: string, saveAs?: boolean}} SaveJpsDocumentOptions */
/** @typedef {{documentId: string, revision: number, pageCount: number, filenames: string[], customMarkupOmitted: boolean}} SvgExportReceipt */
/** @typedef {"pdf" | "jpg" | "png"} ScoreExportFormat */
/** @typedef {{documentId: string, revision: number, format: ScoreExportFormat, dpi: number | null, pageCount: number, filenames: string[], customMarkupOmitted: boolean}} ScoreExportReceipt */
/** @typedef {{ocr: boolean, ocr_backends?: Record<"rapidocr-onnxruntime" | "rapidocr-onnx" | "rapidocr-openvino", boolean>, png_export: boolean, fonts?: Record<string, {family: string, fallback: string, available: boolean}>}} EngineCapabilities */
/** @typedef {{id: string, path: string, name: string, mimeType: "image/png" | "image/jpeg", byteLength: number, width: number, height: number, orientation: number}} StagedReferenceImage */
/** @typedef {{id: string, path: string, name: string, byteLength: number, sha256: string}} StagedReferencePdf */
/** @typedef {{images: StagedReferenceImage[], pdfs: StagedReferencePdf[], order: string[]}} StagedReferenceAssets */
/** @typedef {{jps: string, page_count: number, page_dimensions?: Array<{width:number, height:number}>, issues: Array<{code: string, page: number, detail: string, regions: number[][], confidence?:number|null, source_start?:number|null, source_end?:number|null}>}} TranscriptionDraft */
/** @typedef {{status: "ok" | "error", result?: TranscriptionDraft, error?: {message: string}}} TranscriptionResponse */

/** @template T @param {string} command @param {Record<string, unknown>} args @returns {Promise<T>} */
function invokeNative(command, args) {
  const invoke = window.__TAURI__?.core.invoke;
  if (!invoke) throw new Error("Native file access is available only in the desktop app.");
  return invoke(command, args);
}

/** @param {string | null} initialPath @returns {Promise<OpenedJpsDocument | null>} */
export function openJpsDocument(initialPath = null) {
  return invokeNative("open_jps_file", initialPath ? { initialPath } : {});
}

/** @param {string[] | null} paths @param {string | null} suggestedPath @returns {Promise<StagedReferenceAssets | null>} */
export function stageReferenceAssets(paths = null, suggestedPath = null) {
  return invokeNative("stage_reference_assets", { paths, suggestedPath });
}

/** @param {string[]} ids @returns {Promise<void>} */
export function discardReferenceImages(ids) {
  return invokeNative("discard_reference_images", { ids });
}

/** @param {string[]} retainedIds @returns {Promise<void>} */
export function pruneReferenceImages(retainedIds) {
  return invokeNative("prune_reference_images", { retainedIds });
}

/** @param {string[]} ids @returns {Promise<{id: string, path: string}[]>} */
export function resolveReferenceImages(ids) {
  return invokeNative("resolve_reference_images", { ids });
}

/** @param {string} assetId @param {string} documentId @param {number} documentRevision @param {string} jobId
 * @param {"rapidocr-onnxruntime" | "rapidocr-onnx" | "rapidocr-openvino"} [ocrBackend]
 * @returns {Promise<TranscriptionResponse>} */
export async function transcribeReference(
  assetId, documentId, documentRevision, jobId, ocrBackend = "rapidocr-onnxruntime",
) {
  /** @type {TranscriptionResponse} */
  const response = await invokeNative("transcribe_reference", {
    assetId, documentId, documentRevision, jobId, ocrBackend,
  });
  const draft = response?.result;
  if (response?.status === "error" && typeof response.error?.message === "string") return response;
  if (response?.status !== "ok"
    || typeof draft?.jps !== "string"
    || !Number.isSafeInteger(draft.page_count) || draft.page_count < 1
    || (draft.page_dimensions !== undefined && (!Array.isArray(draft.page_dimensions)
      || draft.page_dimensions.length !== draft.page_count
      || !draft.page_dimensions.every(page => Number.isSafeInteger(page.width) && page.width > 0
        && Number.isSafeInteger(page.height) && page.height > 0)))
    || !Array.isArray(draft.issues) || !draft.issues.every(isTranscriptionIssue)) {
    throw new Error("The transcription worker returned an invalid draft.");
  }
  return response;
}

/** @param {string} jobId @param {string} documentId @param {number} documentRevision */
export function cancelTranscription(jobId, documentId, documentRevision) {
  return invokeNative("cancel_transcription", {jobId, documentId, documentRevision});
}

/** @param {(payload: any) => void} handler */
export async function onTranscriptionProgress(handler) {
  const events = window.__TAURI__?.event;
  if (!events) return () => {};
  return events.listen("octopus-transcription-progress", event => handler(event.payload));
}

/** @param {string} path @returns {Promise<OpenedJpsDocument>} */
export function openRecentJpsDocument(path) {
  return invokeNative("open_recent_jps_file", {path});
}

/** @param {any} issue */
function isTranscriptionIssue(issue) {
  return typeof issue?.code === "string"
    && Number.isSafeInteger(issue.page) && issue.page >= 1
    && typeof issue.detail === "string"
    && (issue.confidence == null || (Number.isFinite(issue.confidence) && issue.confidence >= 0 && issue.confidence <= 1))
    && (issue.source_start == null || (Number.isSafeInteger(issue.source_start) && issue.source_start >= 0))
    && (issue.source_end == null || (Number.isSafeInteger(issue.source_end) && issue.source_end >= issue.source_start))
    && Array.isArray(issue.regions)
    && issue.regions.every((/** @type {any} */ region) => (
      Array.isArray(region) && region.length === 4 && region.every(Number.isFinite)
    ));
}

/** @param {string} path */
export function referenceImageUrl(path) {
  const convertFileSrc = window.__TAURI__?.core.convertFileSrc;
  if (!convertFileSrc) throw new Error("Image display is available only in the desktop app.");
  return convertFileSrc(path);
}

/** @param {(paths: string[]) => void} handler
 * @param {(position: {x: number, y: number} | null) => void} [hover]
 * @returns {Promise<() => void>} */
export function onNativeReferenceDrop(handler, hover = () => {}) {
  const tauriWindow = window.__TAURI__?.window?.getCurrentWindow();
  if (!tauriWindow) return Promise.resolve(() => {});
  return tauriWindow.onDragDropEvent(({ payload }) => {
    hover(payload.type === "enter" || payload.type === "over" ? payload.position ?? null : null);
    if (payload.type === "drop") handler(payload.paths ?? []);
  });
}

/** @returns {Promise<JpsCatalogDocument[]>} */
export function listJpsDocuments() {
  return invokeNative("list_jps_documents", {});
}

/** @param {JpsCatalogDocument["kind"]} kind @param {string} name @returns {Promise<{name: string, path: string | null, suggestedPath: string | null, text: string}>} */
export function openJpsCatalogDocument(kind, name) {
  return invokeNative("open_jps_catalog_document", { kind, name });
}

/** @returns {Promise<string | null>} */
export function readRecoverySnapshot() {
  return invokeNative("read_recovery_snapshot", {});
}

/** @param {number} sequence @param {string | null} text @returns {Promise<boolean>} */
export function writeRecoverySnapshot(sequence, text) {
  return invokeNative("write_recovery_snapshot", { sequence, text });
}

/** @param {(event: {preventDefault(): void}) => void} handler */
export function onNativeCloseRequested(handler) {
  const tauriWindow = window.__TAURI__?.window?.getCurrentWindow();
  if (!tauriWindow) return Promise.resolve(() => {});
  return tauriWindow.onCloseRequested(handler);
}

/** @param {boolean} recoveryReady @param {boolean} recoveryDialog @returns {"defer" | "preserve" | "prompt"} */
export function nativeCloseDisposition(recoveryReady, recoveryDialog) {
  if (!recoveryReady) return "defer";
  return recoveryDialog ? "preserve" : "prompt";
}

export function closeNativeWindow() {
  const tauriWindow = window.__TAURI__?.window?.getCurrentWindow();
  if (!tauriWindow) return Promise.resolve();
  return tauriWindow.close();
}

export function destroyNativeWindow() {
  const tauriWindow = window.__TAURI__?.window?.getCurrentWindow();
  if (!tauriWindow) return Promise.resolve();
  return tauriWindow.destroy();
}

/** @returns {Promise<EngineCapabilities>} */
export function getEngineCapabilities() {
  return invokeNative("get_engine_capabilities", {});
}

/** @param {SaveJpsDocumentOptions} options @returns {Promise<string | null>} */
export function saveJpsDocument({
  path,
  suggestedPath,
  suggestedName,
  recentSavedPath,
  expectedText,
  text,
  saveAs = false,
}) {
  return invokeNative("save_jps_file", {
    path: saveAs ? null : path,
    suggestedPath: suggestedPath ?? path,
    suggestedName: suggestedName ?? null,
    ...(recentSavedPath ? { recentSavedPath } : {}),
    expectedText: expectedText ?? null,
    text,
    saveAs,
  });
}

/** @param {Record<string, unknown>} args @param {string | null} suggestedPath @param {string} suggestedName @returns {Promise<SvgExportReceipt | null>} */
export function exportSvgDocument(args, suggestedPath, suggestedName) {
  return invokeNative("export_svg", { args, suggestedPath, suggestedName });
}

/** @param {Record<string, unknown>} args @param {string | null} suggestedPath @param {string} suggestedName @param {ScoreExportFormat} format @param {96 | 300 | null} dpi @returns {Promise<ScoreExportReceipt | null>} */
export function exportScoreDocument(args, suggestedPath, suggestedName, format, dpi) {
  return invokeNative("export_score", { args, suggestedPath, suggestedName, format, dpi });
}
