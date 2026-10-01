/** @typedef {{value: string, label: string}} SettingOption */
/** @typedef {{key: string, label: string, kind: "number" | "select", defaultValue: string | number, min?: number, max?: number, options?: SettingOption[]}} PageSetting */
/** @typedef {{key: string, fields: PageSetting[]}} PageSettingGroup */

/** @type {PageSettingGroup[]} */
export const pageSettingGroups = [
  {
    key: "pageSettingsPageGroup",
    fields: [
      {
        key: "page",
        label: "pageSettingsPaper",
        kind: "select",
        defaultValue: "A4",
        options: [
          { value: "A4", label: "pageSettingsA4" },
          { value: "A5", label: "pageSettingsA5" },
        ],
      },
      { key: "margin_top", label: "pageSettingsMarginTop", kind: "number", defaultValue: 40, min: 0, max: 300 },
      { key: "margin_bottom", label: "pageSettingsMarginBottom", kind: "number", defaultValue: 40, min: 0, max: 300 },
      { key: "margin_left", label: "pageSettingsMarginLeft", kind: "number", defaultValue: 60, min: 0, max: 300 },
      { key: "margin_right", label: "pageSettingsMarginRight", kind: "number", defaultValue: 60, min: 0, max: 300 },
      { key: "body_margin_top", label: "pageSettingsBodyTop", kind: "number", defaultValue: 20, min: 0, max: 300 },
    ],
  },
  {
    key: "pageSettingsFontsGroup",
    fields: [
      {
        key: "biaoti_font",
        label: "pageSettingsTitleFont",
        kind: "select",
        defaultValue: "HeiTi-1",
        options: [
          { value: "HeiTi-1", label: "fontHeiTi1" },
          { value: "HeiTi-2", label: "fontHeiTi2" },
          { value: "SongTi", label: "fontSongTi" },
          { value: "KaiTi", label: "fontKaiTi" },
          { value: "FangSong", label: "fontFangSong" },
        ],
      },
      {
        key: "shuzi_font",
        label: "pageSettingsNoteFont",
        kind: "select",
        defaultValue: "Bold",
        options: [
          { value: "Regular", label: "noteStyleRegular" },
          { value: "Italic", label: "noteStyleItalic" },
          { value: "Bold", label: "noteStyleBold" },
        ],
      },
      {
        key: "geci_font",
        label: "pageSettingsLyricFont",
        kind: "select",
        defaultValue: "HeiTi-1",
        options: [
          { value: "HeiTi-1", label: "fontHeiTi1" },
          { value: "HeiTi-2", label: "fontHeiTi2" },
          { value: "SongTi", label: "fontSongTi" },
          { value: "KaiTi", label: "fontKaiTi" },
          { value: "FangSong", label: "fontFangSong" },
        ],
      },
    ],
  },
  {
    key: "pageSettingsSizesGroup",
    fields: [
      { key: "biaoti_size", label: "pageSettingsTitleSize", kind: "number", defaultValue: 36, min: 8, max: 120 },
      { key: "fubiaoti_size", label: "pageSettingsSubtitleSize", kind: "number", defaultValue: 20, min: 8, max: 120 },
      { key: "geci_size", label: "pageSettingsLyricSize", kind: "number", defaultValue: 16, min: 8, max: 120 },
    ],
  },
  {
    key: "pageSettingsSpacingGroup",
    fields: [
      { key: "height_quci", label: "pageSettingsMusicLyricsSpacing", kind: "number", defaultValue: 12, min: 0, max: 100 },
      { key: "height_cici", label: "pageSettingsLyricLineSpacing", kind: "number", defaultValue: 10, min: 0, max: 100 },
      { key: "height_ciqu", label: "pageSettingsLyricsMusicSpacing", kind: "number", defaultValue: 20, min: 0, max: 100 },
      { key: "height_shengbu", label: "pageSettingsVoiceSpacing", kind: "number", defaultValue: 10, min: 0, max: 100 },
    ],
  },
  {
    key: "pageSettingsOtherGroup",
    fields: [
      {
        key: "lianyinxian_type",
        label: "pageSettingsSlurStyle",
        kind: "select",
        defaultValue: "0",
        options: [
          { value: "0", label: "slurAutomatic" },
          { value: "1", label: "slurArc" },
          { value: "2", label: "slurFlatTop" },
        ],
      },
    ],
  },
];

export const pageSettingFields = pageSettingGroups.flatMap((group) => group.fields);

/** @param {unknown} value @returns {Record<string, unknown>} */
export function decodePageConfig(value) {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return isRecord(parsed) ? parsed : { _raw: value };
    } catch {
      return { _raw: value };
    }
  }
  return isRecord(value) ? value : { _raw: value };
}

/** @param {Record<string, unknown>} config @returns {Record<string, string | number>} */
export function createPageSettingsDraft(config) {
  const decoded = decodePageConfig(config);
  return Object.fromEntries(pageSettingFields.map((field) => [field.key, readValue(decoded, field)]));
}

/** @param {Record<string, unknown>} config @param {Record<string, string | number>} draft */
export function applyPageSettings(config, draft) {
  const decoded = decodePageConfig(config);
  const next = { ...decoded };
  let changed = false;
  for (const field of pageSettingFields) {
    const original = readValue(decoded, field);
    const proposed = draft[field.key] ?? original;
    if (String(proposed) === String(original)) continue;
    const normalized = normalizeValue(field, proposed, original);
    if (normalized === original) continue;
    next[field.key] = normalized;
    changed = true;
  }
  return { config: next, changed };
}

/** @param {Record<string, unknown>} config @param {Record<string, string | number>} draft */
export function pageSettingsDraftChanged(config, draft) {
  const values = createPageSettingsDraft(config);
  return pageSettingFields.some((field) => String(values[field.key]) !== String(draft[field.key] ?? values[field.key]));
}

/** @param {Record<string, unknown>} config @param {import("./page-settings.js").PageSetting} field */
function readValue(config, field) {
  const stored = config[field.key];
  if (field.kind === "number") {
    if (typeof stored === "number" && Number.isInteger(stored)) return stored;
    if (typeof stored === "string" && /^[-+]?\d+$/.test(stored.trim())) return Number(stored);
    return field.defaultValue;
  }
  if (typeof stored !== "string") return field.defaultValue;
  if (field.key === "shuzi_font") return ({ a: "Regular", c: "Italic", b: "Bold" })[stored] ?? stored;
  if (field.key === "biaoti_font" || field.key === "geci_font") {
    return ({ "Microsoft YaHei": "HeiTi-1", "微软雅黑": "HeiTi-1",
      HeiTi: "HeiTi-2", SimHei: "HeiTi-2", "黑体": "HeiTi-2", "仿宋": "FangSong",
      SimSun: "SongTi", NSimSun: "SongTi", "宋体": "SongTi", "楷体": "KaiTi" })[stored] ?? stored;
  }
  return stored;
}

/** @param {import("./page-settings.js").PageSetting} field @param {string | number} value @param {string | number} original */
function normalizeValue(field, value, original) {
  if (field.kind === "select") {
    const text = String(value);
    if (field.options?.some((option) => option.value === text)) return text;
    return text === String(original) ? original : field.defaultValue;
  }
  let parsed = Number(value);
  if (!Number.isFinite(parsed)) parsed = Number(field.defaultValue);
  parsed = Math.round(parsed);
  return Math.min(field.max ?? Number.MAX_SAFE_INTEGER, Math.max(field.min ?? 0, parsed));
}

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
