import {normalizeRecentFiles} from "./recent-files.js";

/** @typedef {"en" | "zh-CN"} Language */
/** @typedef {"system" | "classic"} UiFont */
/** @typedef {"windows" | "macos" | "linux"} UiFontPlatform */
/** @typedef {"normal" | "transcription"} WorkspaceMode */
/** @typedef {"N1" | "N2" | "T1" | "T2"} LayoutId */
/** @typedef {{x: number, y: number}} Split */
/** @typedef {"N1" | "N2"} NormalLayout */
/** @typedef {"T1" | "T2"} TranscriptionLayout */
/** @typedef {{recentFiles: string[], referenceHintDismissed: boolean, displaySamplesLibrary: boolean, fontNoticeDismissals: string[], language: Language, uiFont: UiFont, mode: WorkspaceMode, normalLayout: NormalLayout, transcriptionLayout: TranscriptionLayout, splits: Record<LayoutId, Split>}} WorkspacePreferences */

export const PREFERENCES_KEY = "octopus.workspace.v1";

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

/** @returns {WorkspacePreferences} */
export function defaultPreferences() {
  return {
    recentFiles: [],
    referenceHintDismissed: false,
    displaySamplesLibrary: true,
    fontNoticeDismissals: [],
    language: "zh-CN",
    uiFont: "system",
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

/** @param {{getItem: (key: string) => string | null}} storage @returns {WorkspacePreferences} */
export function readPreferences(storage) {
  const defaults = defaultPreferences();
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
      displaySamplesLibrary: candidate.displaySamplesLibrary !== false,
      fontNoticeDismissals: Array.isArray(candidate.fontNoticeDismissals)
        ? [...new Set(candidate.fontNoticeDismissals.filter(
          (key) => typeof key === "string" && key.length <= 2048,
        ))].slice(-20)
        : [],
      language: candidate.language === "zh-CN" || candidate.language === "en"
        ? candidate.language
        : defaults.language,
      uiFont: candidate.uiFont === "classic" ? "classic" : "system",
      mode: candidate.mode === "transcription" ? "transcription" : "normal",
      normalLayout: candidate.normalLayout === "N2" ? "N2" : "N1",
      transcriptionLayout: candidate.transcriptionLayout === "T1" ? "T1" : "T2",
      splits: { N1: split("N1"), N2: split("N2"), T1: t1, T2: split("T2") },
    };
  } catch {
    return defaults;
  }
}

/** @param {UiFontPlatform} platform @returns {Array<{id: UiFont, family: string, stack: string}>} */
export function uiFontChoices(platform) {
  if (platform === "windows") return [
    {id: "system", family: "Microsoft YaHei",
      stack: '"Microsoft YaHei", "Microsoft YaHei UI", "Segoe UI", sans-serif'},
    {id: "classic", family: "SimSun",
      stack: '"SimSun", "NSimSun", "Microsoft YaHei", serif'},
  ];
  if (platform === "macos") return [
    {id: "system", family: "PingFang SC",
      stack: '"PingFang SC", system-ui, -apple-system, sans-serif'},
    {id: "classic", family: "Songti SC",
      stack: '"Songti SC", "STSong", "PingFang SC", serif'},
  ];
  return [
    {id: "system", family: "Noto Sans SC",
      stack: '"OctoPus Noto Sans SC", "OctoPus Liberation Sans", sans-serif'},
    {id: "classic", family: "Liberation Sans",
      stack: '"OctoPus Liberation Sans", "OctoPus Noto Sans SC", sans-serif'},
  ];
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
