import {normalizeRecentFiles} from "./recent-files.js";

/** @typedef {"en" | "zh-CN"} Language */
/** @typedef {"normal" | "transcription"} WorkspaceMode */
/** @typedef {"N1" | "N2" | "T1" | "T2"} LayoutId */
/** @typedef {{x: number, y: number}} Split */
/** @typedef {"N1" | "N2"} NormalLayout */
/** @typedef {"T1" | "T2"} TranscriptionLayout */
/** @typedef {Record<string, "system" | "fallback">} FontSources */
/** @typedef {"rapidocr-onnxruntime" | "rapidocr-onnx" | "rapidocr-openvino"} OcrBackend */
/** @typedef {{recentFiles: string[], referenceHintDismissed: boolean, fontSources: FontSources, ocrBackend: OcrBackend, language: Language, mode: WorkspaceMode, normalLayout: NormalLayout, transcriptionLayout: TranscriptionLayout, splits: Record<LayoutId, Split>}} WorkspacePreferences */

export const PREFERENCES_KEY = "octopus.workspace.v1";

/** @param {string} backend @param {Record<string, boolean> | undefined} capabilities */
export function ocrBackendAvailable(backend, capabilities) {
  if (backend === "rapidocr-pytorch") return false;
  if (backend === "rapidocr-openvino") return capabilities?.[backend] === true;
  return capabilities?.[backend] !== false;
}

/** @type {Record<LayoutId, Split>} */
const DEFAULT_SPLITS = {
  N1: { x: 50, y: 50 },
  N2: { x: 50, y: 66 },
  T1: { x: 33, y: 33 },
  T2: { x: 50, y: 65 },
};

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** @param {unknown} value @param {number} fallback @param {number} minimum @param {number} maximum */
function bounded(value, fallback, minimum, maximum) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(maximum, Math.max(minimum, value))
    : fallback;
}

/** @param {string} [osLanguage] @returns {WorkspacePreferences} */
export function defaultPreferences(osLanguage = "en") {
  return {
    recentFiles: [],
    referenceHintDismissed: false,
    fontSources: Object.fromEntries(["heiti-1", "heiti-2", "songti", "kaiti", "fangsong"].map(role => [role, "system"])),
    ocrBackend: "rapidocr-onnxruntime",
    language: osLanguage.toLowerCase().startsWith("zh") ? "zh-CN" : "en",
    mode: "normal",
    normalLayout: "N1",
    transcriptionLayout: "T2",
    splits: {
      N1: { ...DEFAULT_SPLITS.N1 },
      N2: { ...DEFAULT_SPLITS.N2 },
      T1: { ...DEFAULT_SPLITS.T1 },
      T2: { ...DEFAULT_SPLITS.T2 },
    },
  };
}

/** @param {{getItem: (key: string) => string | null}} storage @param {string} [osLanguage] @returns {WorkspacePreferences} */
export function readPreferences(storage, osLanguage = "en") {
  const defaults = defaultPreferences(osLanguage);
  try {
    const candidate = JSON.parse(storage.getItem(PREFERENCES_KEY) ?? "null");
    if (!isRecord(candidate)) return defaults;
    const rawSplits = isRecord(candidate.splits) ? candidate.splits : {};
    /** @param {LayoutId} layout */
    const split = (layout) => {
      const raw = isRecord(rawSplits[layout]) ? rawSplits[layout] : {};
      const xMaximum = layout === "T1" ? 60 : 80;
      const yMaximum = layout === "T1" ? 60 : 80;
      return {
        x: bounded(raw.x, DEFAULT_SPLITS[layout].x, 20, xMaximum),
        y: bounded(raw.y, DEFAULT_SPLITS[layout].y, 20, yMaximum),
      };
    };
    const t1 = split("T1");
    if (t1.x + t1.y > 80) {
      t1.x = Math.max(20, Math.floor((t1.x * 80) / (t1.x + t1.y)));
      t1.y = 80 - t1.x;
    }
    return {
      recentFiles: normalizeRecentFiles(candidate.recentFiles),
      referenceHintDismissed: candidate.referenceHintDismissed === true,
      fontSources: Object.fromEntries(Object.keys(defaults.fontSources).map(role =>
        [role, isRecord(candidate.fontSources) && candidate.fontSources[role] === "fallback" ? "fallback" : "system"])),
      ocrBackend: candidate.ocrBackend === "rapidocr-onnx"
        || candidate.ocrBackend === "rapidocr-openvino"
        ? candidate.ocrBackend
        : "rapidocr-onnxruntime",
      language: candidate.language === "zh-CN" || candidate.language === "en"
        ? candidate.language
        : defaults.language,
      mode: candidate.mode === "transcription" ? "transcription" : "normal",
      normalLayout: candidate.normalLayout === "N2" ? "N2" : "N1",
      transcriptionLayout: candidate.transcriptionLayout === "T1" ? "T1" : "T2",
      splits: { N1: split("N1"), N2: split("N2"), T1: t1, T2: split("T2") },
    };
  } catch {
    return defaults;
  }
}

/** @param {{setItem: (key: string, value: string) => void}} storage @param {WorkspacePreferences} preferences */
export function writePreferences(storage, preferences) {
  try {
    storage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
    return true;
  } catch {
    return false;
  }
}
