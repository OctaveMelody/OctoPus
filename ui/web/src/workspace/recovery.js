import { createReferenceSet, validateReferenceSet } from "./reference-set.js";

const MAX_RECOVERY_BYTES = 40 * 1024 * 1024;
const MAX_JPS_BYTES = 8 * 1024 * 1024;
const NEW_SCORE_FIELDS = [
  "title",
  "subtitle",
  "lyricist",
  "composer",
  "otherAuthors",
  "keyNote",
  "keyAccidental",
  "beatNumerator",
  "beatDenominator",
  "tempo",
];

/** @typedef {{title: string, subtitle: string, lyricist: string, composer: string, otherAuthors: string, keyNote: string, keyAccidental: "" | "#" | "$", beatNumerator: number, beatDenominator: number, tempo: string}} NewScoreFields */
/** @typedef {{kind: "new", name: string, fields: NewScoreFields}} RecoveryDraft */
/** @typedef {{name: string, source: string, savedSource: string, savedFileText: string | null, suggestedPath: string | null, wrapperFields: Record<string, unknown>, customCode: string, pageConfig: Record<string, unknown>, savedPageConfig: Record<string, unknown>, jsonWrapped: boolean, revision: number}} RecoveryDocument */
/** @typedef {{document: RecoveryDocument, draft: RecoveryDraft | null, references: import("./reference-set.js").ReferenceSet}} RecoveryState */

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** @param {Record<string, unknown>} value @param {string[]} expected @param {string} label */
function requireKeys(value, expected, label) {
  const keys = Object.keys(value).sort();
  const expectedKeys = [...expected].sort();
  if (keys.length !== expectedKeys.length || keys.some((key, index) => key !== expectedKeys[index])) {
    throw new TypeError(`${label} has unsupported fields`);
  }
}

/** @param {unknown} value @param {string} label @param {number} maximum */
function requireText(value, label, maximum = MAX_JPS_BYTES) {
  if (typeof value !== "string" || new TextEncoder().encode(value).length > maximum) {
    throw new TypeError(`${label} is missing or too large`);
  }
  return value;
}

/** @param {unknown} value @returns {RecoveryDraft} */
function validateNewScoreDraft(value) {
  if (!isRecord(value)) throw new TypeError("new-score recovery draft is invalid");
  requireKeys(value, ["kind", "name", "fields"], "new-score recovery draft");
  if (value.kind !== "new") throw new TypeError("recovery draft kind is unsupported");
  const name = requireText(value.name, "draft filename", 255);
  if (name.includes("/") || name.includes("\\") || name.includes("\0")) {
    throw new TypeError("draft filename is invalid");
  }
  if (!isRecord(value.fields)) throw new TypeError("new-score fields are invalid");
  requireKeys(value.fields, NEW_SCORE_FIELDS, "new-score fields");
  for (const key of ["title", "subtitle", "lyricist", "composer", "otherAuthors", "tempo"]) {
    requireText(value.fields[key], `draft ${key}`, 1024 * 1024);
  }
  if (
    typeof value.fields.keyNote !== "string"
    || value.fields.keyNote.length !== 1
    || !"CDEFGAB".includes(value.fields.keyNote)
    || typeof value.fields.keyAccidental !== "string"
    || !["", "#", "$"].includes(value.fields.keyAccidental)
  ) {
    throw new TypeError("draft key signature is invalid");
  }
  for (const key of ["beatNumerator", "beatDenominator"]) {
    const beat = value.fields[key];
    if (typeof beat !== "number" || !Number.isSafeInteger(beat) || beat < 1) {
      throw new TypeError("draft time signature is invalid");
    }
  }
  return {
    kind: "new",
    name,
    fields: /** @type {NewScoreFields} */ ({ ...value.fields }),
  };
}

/** @param {RecoveryDocument & {path?: string | null}} document @param {RecoveryDraft | null} [draft] @param {import("./reference-set.js").ReferenceSet} [references] @returns {string | null} */
export function createRecoverySnapshot(document, draft = null, references = createReferenceSet()) {
  const referenceSet = validateReferenceSet(references);
  if (
    document.source === document.savedSource
    && JSON.stringify(document.pageConfig) === JSON.stringify(document.savedPageConfig)
    && !draft
    && referenceSet.images.length === 0
    && referenceSet.pdfs.length === 0
  ) return null;
  const snapshot = {
    version: 4,
    document: {
      name: document.name,
      source: document.source,
      savedSource: document.savedSource,
      savedFileText: document.savedFileText,
      suggestedPath: document.suggestedPath ?? document.path,
      wrapperFields: document.wrapperFields,
      customCode: document.customCode,
      pageConfig: document.pageConfig,
      savedPageConfig: document.savedPageConfig,
      jsonWrapped: document.jsonWrapped,
      revision: document.revision,
    },
    draft: draft ? validateNewScoreDraft(draft) : null,
    references: referenceSet,
  };
  const text = JSON.stringify(snapshot);
  if (new TextEncoder().encode(text).length > MAX_RECOVERY_BYTES) {
    throw new TypeError("recovery snapshot exceeds the size limit");
  }
  return text;
}

/** @param {string} text @returns {RecoveryState} */
export function parseRecoverySnapshot(text) {
  requireText(text, "recovery snapshot", MAX_RECOVERY_BYTES);
  let snapshot;
  try {
    snapshot = JSON.parse(text);
  } catch {
    throw new TypeError("recovery snapshot is not valid JSON");
  }
  if (!isRecord(snapshot)) throw new TypeError("recovery snapshot is invalid");
  const snapshotVersion = snapshot.version;
  if (snapshotVersion !== 1 && snapshotVersion !== 2 && snapshotVersion !== 3 && snapshotVersion !== 4) {
    throw new TypeError("recovery snapshot version is unsupported");
  }
  requireKeys(
    snapshot,
    snapshotVersion >= 3
      ? ["version", "document", "draft", "references"]
      : ["version", "document", "draft"],
    "recovery snapshot",
  );
  if (!isRecord(snapshot.document)) throw new TypeError("recovery document is invalid");
  const documentFields = [
    "name",
    "source",
    "savedSource",
    "savedFileText",
    "suggestedPath",
    "wrapperFields",
    "customCode",
    "pageConfig",
    "jsonWrapped",
    "revision",
  ];
  if (snapshotVersion >= 2) documentFields.push("savedPageConfig");
  requireKeys(snapshot.document, documentFields, "recovery document");
  const document = snapshot.document;
  const savedPageConfig = snapshotVersion >= 2
    ? document.savedPageConfig
    : document.pageConfig;
  const name = requireText(document.name, "recovery filename", 255);
  if (!name.trim() || name.includes("/") || name.includes("\\") || name.includes("\0")) {
    throw new TypeError("recovery filename is invalid");
  }
  const source = requireText(document.source, "recovery source", MAX_RECOVERY_BYTES);
  const savedSource = requireText(document.savedSource, "saved recovery source", MAX_RECOVERY_BYTES);
  const savedFileText = document.savedFileText === null
    ? null
    : requireText(document.savedFileText, "saved file snapshot", MAX_RECOVERY_BYTES);
  const suggestedPath = document.suggestedPath === null
    ? null
    : requireText(document.suggestedPath, "suggested path", 32 * 1024);
  if (suggestedPath?.includes("\0")) throw new TypeError("suggested path is invalid");
  if (
    !isRecord(document.wrapperFields)
    || Object.prototype.hasOwnProperty.call(document.wrapperFields, "code")
  ) {
    throw new TypeError("recovery wrapper fields are invalid");
  }
  if (
    !isRecord(document.pageConfig)
    || !isRecord(savedPageConfig)
    || typeof document.customCode !== "string"
    || new TextEncoder().encode(document.customCode).length > MAX_RECOVERY_BYTES
  ) {
    throw new TypeError("recovery render metadata is invalid");
  }
  if (typeof document.jsonWrapped !== "boolean") {
    throw new TypeError("recovery wrapper flag is invalid");
  }
  if (
    typeof document.revision !== "number"
    || !Number.isSafeInteger(document.revision)
    || document.revision < 0
  ) {
    throw new TypeError("recovery revision is invalid");
  }
  const draft = snapshot.draft === null ? null : validateNewScoreDraft(snapshot.draft);
  let references = createReferenceSet();
  if (snapshotVersion >= 3) {
    if (!isRecord(snapshot.references)) throw new TypeError("recovery references are invalid");
    references = validateReferenceSet(snapshotVersion === 3
      ? { ...snapshot.references, pdfs: [] }
      : snapshot.references);
  }
  return {
    document: {
      name,
      source,
      savedSource,
      savedFileText,
      suggestedPath,
      wrapperFields: document.wrapperFields,
      customCode: document.customCode,
      pageConfig: document.pageConfig,
      savedPageConfig,
      jsonWrapped: document.jsonWrapped,
      revision: document.revision,
    },
    draft,
    references,
  };
}
