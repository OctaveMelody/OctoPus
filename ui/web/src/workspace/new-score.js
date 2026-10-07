import { createPageSettingsDraft } from "./page-settings.js";

/** @typedef {{title: string, subtitle: string, lyricist: string, composer: string, otherAuthors: string, keyNote: string, keyAccidental: "" | "#" | "$", beatNumerator: number, beatDenominator: number, tempo: string}} NewScoreFields */

/** @param {string} value @param {string} field */
function oneLine(value, field) {
  if (typeof value !== "string") throw new TypeError(`${field} must be text`);
  if (/[\r\n]/.test(value)) throw new TypeError(`${field} must be a single line`);
  return value.trim();
}

/** @param {NewScoreFields} fields */
export function createNewScore(fields) {
  const title = oneLine(fields.title, "title");
  if (!title) throw new TypeError("title is required");
  if (
    fields.keyNote.length !== 1
    || !"CDEFGAB".includes(fields.keyNote)
    || !["", "#", "$"].includes(fields.keyAccidental)
  ) {
    throw new TypeError("key signature is invalid");
  }
  for (const value of [fields.beatNumerator, fields.beatDenominator]) {
    if (!Number.isSafeInteger(value) || value < 1) {
      throw new TypeError("time-signature values must be positive safe integers");
    }
  }

  const lines = [
    "#============================以下为描述头定义==========================",
    "V: 1.0",
    `B: ${title}`,
  ];
  const optional = [
    ["subtitle", fields.subtitle],
    ["lyricist", fields.lyricist],
    ["composer", fields.composer],
    ["other authors", fields.otherAuthors],
    ["tempo", fields.tempo],
  ].map(([field, value]) => [field, oneLine(value, field)]);
  const [subtitle, lyricist, composer, otherAuthors, tempo] = optional.map(([, value]) => value);
  if (subtitle) lines.push(`B: ${subtitle}`);
  if (lyricist) lines.push(`Z: ${lyricist} 词`);
  if (composer) lines.push(`Z: ${composer} 曲`);
  if (otherAuthors) lines.push(`Z: ${otherAuthors}`);
  lines.push(`D: ${fields.keyNote}${fields.keyAccidental}`);
  lines.push(`P: ${fields.beatNumerator}/${fields.beatDenominator}`);
  if (tempo) lines.push(`J: ${tempo}`);
  lines.push("#============================以下开始简谱主体==========================");
  lines.push("Q: 1 2 3 4 | ");
  lines.push("C: 这是歌词 ");
  return lines.join("\n");
}

/** @param {string} value */
export function normalizeJpsFileName(value) {
  const name = value.trim();
  if (
    !name
    || name.length > 255
    || /[\\/:*?"<>|\0\r\n]/.test(name)
    || /[. ]$/.test(name)
    || name === "."
    || name === ".."
    || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name)
  ) {
    throw new TypeError("enter a valid JPS filename");
  }
  const normalized = name.toLowerCase().endsWith(".jps") ? name : `${name}.jps`;
  if (new TextEncoder().encode(normalized).length > 255) {
    throw new TypeError("JPS filename exceeds the filesystem name limit");
  }
  return normalized;
}

export function createNewScorePageConfig() {
  const { biaoti_font, geci_font, shuzi_font } = createPageSettingsDraft({});
  return { biaoti_font, geci_font, shuzi_font };
}
