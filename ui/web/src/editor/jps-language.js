import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

const noteSuffix = new Set(["'", ",", ".", "/", "#", "$", "=", "<", ">", "+", "!", "~", "^", "\\"]);

/** @param {string} line @param {number} position */
function noteToken(line, position) {
  let end = position;
  if ("#$=".includes(line.charAt(end)) && /[0-9]/.test(line.charAt(end + 1))) end++;
  if (!/[0-9]/.test(line.charAt(end))) return null;
  end++;
  while (end < line.length && noteSuffix.has(line.charAt(end))) end++;
  return end;
}

const language = StreamLanguage.define({
  name: "jps",
  token(stream) {
    if (stream.sol()) {
      const prefix = stream.string.slice(stream.pos);
      if (/^\s*#/.test(prefix)) {
        stream.skipToEnd();
        return "comment";
      }
      if (/^[A-Z]:/.test(prefix)) {
        stream.next();
        stream.next();
        return "keyword";
      }
    }
    if (stream.peek() === '"') {
      stream.next();
      let escaped = false;
      while (!stream.eol()) {
        const character = stream.next();
        if (character === '"' && !escaped) break;
        escaped = character === "\\" && !escaped;
      }
      return "string";
    }
    const end = noteToken(stream.string, stream.pos);
    if (end !== null) {
      while (stream.pos < end) stream.next();
      return "number";
    }
    if (stream.match(/[|:{}\[\]()]/)) return "punctuation";
    stream.next();
    return null;
  },
});

const highlighting = HighlightStyle.define([
  { tag: t.comment, color: "#77808c", fontStyle: "italic" },
  { tag: t.keyword, color: "#7656a4", fontWeight: "650" },
  { tag: t.number, color: "#1b5b9e", fontWeight: "600" },
  { tag: t.string, color: "#8b5417" },
  { tag: t.punctuation, color: "#7a8491" },
]);

export const jpsLanguage = [language, syntaxHighlighting(highlighting)];
