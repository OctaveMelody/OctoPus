/** @typedef {{value: string, label: string}} SettingOption */
/** @typedef {{key: string, label: string, kind: "number" | "select" | "text", defaultValue: string | number | boolean, min?: number, max?: number, options?: SettingOption[]}} PageSetting */
/** @typedef {{key: string, fields: PageSetting[]}} PageSettingGroup */

/** @param {number[]} sizes @returns {SettingOption[]} */
function sizeOptions(sizes) {
  return sizes.map((size) => ({ value: String(size), label: String(size) }));
}

export const MAX_FOOTNOTE_LENGTH = 24;

/** @param {string} value */
export function limitFootnoteText(value) {
  return Array.from(value).slice(0, MAX_FOOTNOTE_LENGTH).join("");
}

const pageNumberStyles = [
  { value: "number", label: "pageNumberOnly" },
  { value: "total", label: "pageNumberWithTotal" },
  { value: "roman", label: "pageNumberRoman" },
  { value: "roman_total", label: "pageNumberRomanWithTotal" },
];

const footerPositions = [
  { value: "null", label: "footerPositionNull" },
  { value: "left", label: "footerPositionLeft" },
  { value: "center", label: "pageNumberCenter" },
  { value: "right", label: "pageNumberRight" },
];

/** @param {string} position */
function freeFootnoteEdge(position) {
  return position === "left" ? "right" : "left";
}

/** @param {Record<string, unknown>} config */
function readPageNumberPosition(config) {
  if (!pageNumberStyles.some(({ value }) => value === config.footer_page_number)) return "null";
  const position = config.footer_page_number_position;
  return position === "left" || position === "center" || position === "null" ? position : "right";
}

/** @param {Record<string, unknown>} config */
function readFootnotePosition(config) {
  if (config.footer_credit !== true) return "null";
  const stored = config.footer_credit_position;
  const position = stored === "center" || stored === "right" ? stored : "left";
  return position === readPageNumberPosition(config) ? freeFootnoteEdge(position) : position;
}

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
      { key: "body_margin_top", label: "pageSettingsBodyTop", kind: "number", defaultValue: 40, min: 0, max: 300 },
    ],
  },
  {
    key: "pageSettingsTypographyGroup",
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
      { key: "biaoti_size", label: "pageSettingsTitleSize", kind: "number", defaultValue: 36, min: 8, max: 120, options: sizeOptions([24, 28, 32, 36, 42, 48]) },
      {
        key: "fubiaoti_font",
        label: "pageSettingsSubtitleFont",
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
      { key: "fubiaoti_size", label: "pageSettingsSubtitleSize", kind: "number", defaultValue: 20, min: 8, max: 120, options: sizeOptions([16, 18, 20, 22, 24, 28]) },
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
      { key: "shuzi_size", label: "pageSettingsNoteSize", kind: "number", defaultValue: "", min: 8, max: 24,
        options: [{ value: "", label: "pageSettingsDefault" }, ...sizeOptions([12, 14, 16, 18, 20, 22, 24])] },
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
      { key: "geci_size", label: "pageSettingsLyricSize", kind: "number", defaultValue: 16, min: 14, max: 32, options: sizeOptions([14, 16, 18, 20, 22, 24, 26, 28, 30, 32]) },
    ],
  },
  {
    key: "pageSettingsSpacingGroup",
    fields: [
      { key: "height_quci", label: "pageSettingsMusicLyricsSpacing", kind: "number", defaultValue: 12, min: 0, max: 100 },
      { key: "height_cici", label: "pageSettingsLyricLineSpacing", kind: "number", defaultValue: 10, min: 0, max: 100 },
      { key: "height_ciqu", label: "pageSettingsLyricsMusicSpacing", kind: "number", defaultValue: 20, min: 0, max: 100 },
      { key: "height_shengbu", label: "pageSettingsVoiceSpacing", kind: "number", defaultValue: 10, min: 0, max: 100 },
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
  {
    key: "pageSettingsFooterGroup",
    fields: [
      {
        key: "footer_page_number_position",
        label: "pageSettingsPageNumberPosition",
        kind: "select",
        defaultValue: "right",
        options: footerPositions,
      },
      {
        key: "footer_page_number",
        label: "pageSettingsPageNumber",
        kind: "select",
        defaultValue: "number",
        options: pageNumberStyles,
      },
      {
        key: "footer_credit_position",
        label: "pageSettingsFooterPosition",
        kind: "select",
        defaultValue: "null",
        options: footerPositions,
      },
      {
        key: "footer_credit_text",
        label: "pageSettingsFooterText",
        kind: "text",
        defaultValue: "编辑排版: 章鱼简谱",
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

/** @param {Record<string, unknown>} config @returns {Record<string, string | number | boolean>} */
export function createPageSettingsDraft(config) {
  const decoded = decodePageConfig(config);
  return Object.fromEntries(pageSettingFields.map((field) => [field.key, readValue(decoded, field)]));
}

/** @param {Record<string, unknown>} config @param {Record<string, string | number | boolean>} draft */
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
    if (field.key === "footer_credit_position") {
      next.footer_credit = normalized !== "null";
      if (next.footer_credit) next.footer_credit_position = normalized;
    } else {
      const editingPageNumber = field.key === "footer_page_number_position"
        || field.key === "footer_page_number";
      if (field.key === "footer_page_number_position" && next.footer_credit === true) {
        next.footer_credit_position = readFootnotePosition(decoded);
      }
      if (editingPageNumber && !pageNumberStyles.some(({ value }) => value === next.footer_page_number)) {
        if (field.key === "footer_page_number") next.footer_page_number_position = "null";
        else if (normalized !== "null") next.footer_page_number = "number";
      }
      next[field.key] = normalized;
    }
    changed = true;
  }
  const numberPosition = readPageNumberPosition(next);
  if ((next.footer_credit_position !== decoded.footer_credit_position
      || next.footer_credit !== decoded.footer_credit
      || numberPosition !== readPageNumberPosition(decoded))
      && next.footer_credit === true && next.footer_credit_position === numberPosition) {
    next.footer_credit_position = freeFootnoteEdge(numberPosition);
  }
  return { config: next, changed };
}

/** @param {Record<string, unknown>} config @param {Record<string, string | number | boolean>} draft */
export function pageSettingsDraftChanged(config, draft) {
  const values = createPageSettingsDraft(config);
  return pageSettingFields.some((field) => String(values[field.key]) !== String(draft[field.key] ?? values[field.key]));
}

/** @param {Record<string, unknown>} config @param {import("./page-settings.js").PageSetting} field */
function readValue(config, field) {
  const stored = config[field.key] ?? (field.key === "fubiaoti_font" ? config.biaoti_font : undefined);
  if (field.key === "footer_page_number_position") return readPageNumberPosition(config);
  if (field.key === "footer_page_number"
      && !pageNumberStyles.some(({ value }) => value === stored)) return field.defaultValue;
  if (field.key === "footer_credit_position") return readFootnotePosition(config);
  if (field.kind === "number") {
    if (typeof stored === "number" && Number.isInteger(stored)) return stored;
    if (typeof stored === "string" && /^[-+]?\d+$/.test(stored.trim())) return Number(stored);
    return field.defaultValue;
  }
  if (typeof stored !== "string") return field.defaultValue;
  if (field.key === "shuzi_font") return ({ a: "Regular", c: "Italic", b: "Bold" })[stored] ?? stored;
  if (field.key === "biaoti_font" || field.key === "fubiaoti_font" || field.key === "geci_font") {
    return ({ "Microsoft YaHei": "HeiTi-1", "微软雅黑": "HeiTi-1",
      HeiTi: "HeiTi-2", SimHei: "HeiTi-2", "黑体": "HeiTi-2", "仿宋": "FangSong",
      SimSun: "SongTi", NSimSun: "SongTi", "宋体": "SongTi", "楷体": "KaiTi" })[stored] ?? stored;
  }
  return stored;
}

/** @param {import("./page-settings.js").PageSetting} field @param {string | number | boolean} value @param {string | number | boolean} original */
function normalizeValue(field, value, original) {
  if (field.kind === "text") return limitFootnoteText(String(value).trim());
  if (field.key === "shuzi_size" && value === "") return "";
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
