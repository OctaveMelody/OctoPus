import {
  copyFileSync, cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../../..", import.meta.url));
const docsRoot = path.join(repositoryRoot, "docs");
const frontendAssets = path.join(repositoryRoot, "build", "pdfjs-assets", "docs");

rmSync(frontendAssets, { recursive: true, force: true });
mkdirSync(frontendAssets, { recursive: true });
cpSync(path.join(docsRoot, "user-manual"), path.join(frontendAssets, "user-manual"), {
  recursive: true,
});
cpSync(path.join(docsRoot, "PDF"), path.join(frontendAssets, "PDF"), {
  recursive: true,
});

const quickStartSource = path.join(docsRoot, "QUICKSTART.md");
const quickStartChineseSource = path.join(docsRoot, "QUICKSTART.zh-CN.md");
const quickStartSources = [quickStartSource, quickStartChineseSource];
const quickStartOutput = path.join(frontendAssets, "quick-start");
mkdirSync(quickStartOutput, { recursive: true });
const quickStartScreenshots = path.join(frontendAssets, "screenshots");
mkdirSync(quickStartScreenshots, { recursive: true });
const screenshotNames = new Set(quickStartSources.flatMap((source) =>
  [...readFileSync(source, "utf8").matchAll(/!\[[^\]]*\]\(screenshots\/([^\s)]+)/g)]
    .map((match) => match[1]),
));
for (const screenshot of screenshotNames) {
  copyFileSync(path.join(docsRoot, "screenshots", screenshot),
    path.join(quickStartScreenshots, screenshot));
}
writeFileSync(path.join(quickStartOutput, "quickstart.css"), readFileSync(
  path.join(docsRoot, "quick-start.css"), "utf8",
));
copyFileSync(path.join(docsRoot, "quick-start.js"),
  path.join(quickStartOutput, "quickstart.js"));

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function rewriteDocLink(target) {
  if (target.startsWith("screenshots/")) return `../${target}`;
  if (target.startsWith("docs/user-manual/")) return `../user-manual/${target.slice("docs/user-manual/".length)}`;
  if (target.startsWith("user-manual/")) return `../${target}`;
  if (target === "../ENVIRONMENT.md") {
    return "https://github.com/OctaveMelody/OctoPus/blob/main/ENVIRONMENT.md";
  }
  return target;
}

function inlineMarkdown(source) {
  const tokens = [];
  const token = (html) => {
    const id = `\u0000${tokens.length}\u0000`;
    tokens.push(html);
    return id;
  };
  let value = source.replace(/<a\s+id="([^"]+)"\s*><\/a>/g,
    (_match, id) => token(`<a id="${escapeHtml(id)}"></a>`));
  value = value.replace(/`([^`]+)`/g,
    (_match, code) => token(`<code>${escapeHtml(code)}</code>`));
  value = value.replace(/!\[([^\]]*)\]\(([^\s)]+)(?:\s+"([^"]*)")?\)/g,
    (_match, alt, target, title) => token(
      `<figure><img src="${escapeHtml(rewriteDocLink(target))}" alt="${escapeHtml(alt)}"${title ? ` title="${escapeHtml(title)}"` : ""} loading="eager"></figure>`,
    ));
  value = value.replace(/\[([^\]]+)\]\(([^\s)]+)(?:\s+"([^"]*)")?\)/g,
    (_match, label, target, title) => token(
      `<a href="${escapeHtml(rewriteDocLink(target))}"${title ? ` title="${escapeHtml(title)}"` : ""}>${inlineMarkdown(label)}</a>`,
    ));
  value = value.replace(/<(https?:\/\/[^\s>]+)>/g,
    (_match, target) => token(`<a href="${escapeHtml(target)}">${escapeHtml(target)}</a>`));
  value = escapeHtml(value).replaceAll("\\|", "|");
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return value.replace(/\u0000(\d+)\u0000/g, (_match, index) => tokens[Number(index)]);
}

function slugHeading(heading) {
  return heading.toLocaleLowerCase()
    .replace(/<[^>]*>/g, "")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim().replace(/\s+/g, "-");
}

function splitTableRow(line) {
  const cells = [];
  let cell = "";
  let escaped = false;
  for (const character of line.trim().replace(/^\|/, "").replace(/\|$/, "")) {
    if (character === "|" && !escaped) {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
    escaped = character === "\\" && !escaped;
    if (character !== "\\") escaped = false;
  }
  cells.push(cell.trim());
  return cells;
}

function markdownToHtml(markdown) {
  const lines = markdown.replaceAll("\r\n", "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listTag = null;
  let listItems = [];
  const flushParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };
  const closeList = () => {
    if (listTag) html.push(`<${listTag}>${listItems.map((item) => `<li>${item}</li>`).join("")}</${listTag}>`);
    listTag = null;
    listItems = [];
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flushParagraph();
      const language = line.match(/^\s*```([\w-]*)/)[1];
      const code = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      const indents = code.filter((part) => part.trim()).map((part) => part.match(/^\s*/)[0].length);
      const blockIndent = listTag && indents.length ? Math.min(...indents) : 0;
      const block = `<pre><code${language ? ` class="language-${escapeHtml(language)}"` : ""}>${escapeHtml(code.map((part) => part.slice(blockIndent)).join("\n"))}</code></pre>`;
      if (listTag && listItems.length && /^\s{2,}```/.test(line)) listItems[listItems.length - 1] += block;
      else { closeList(); html.push(block); }
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] ?? "")) {
      flushParagraph(); closeList();
      const headers = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(splitTableRow(lines[i++]));
      i -= 1;
      html.push(`<div class="table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_header, index) => `<td>${inlineMarkdown(row[index] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = heading[1].length;
      const label = heading[2].replace(/\*\*/g, "").replace(/`/g, "");
      html.push(`<h${level} id="${escapeHtml(slugHeading(label))}">${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (/^\s*---+\s*$/.test(line)) { flushParagraph(); closeList(); html.push("<hr>"); continue; }
    if (/^\s*>/.test(line)) {
      flushParagraph(); closeList();
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      i -= 1;
      html.push(`<blockquote><p>${inlineMarkdown(quote.join(" "))}</p></blockquote>`);
      continue;
    }
    if (!line.trim()) { flushParagraph(); continue; }
    if (/^\s*!\[[^\]]*\]\([^\s)]+(?:\s+"[^"]*")?\)\s*$/.test(line)) {
      flushParagraph(); closeList(); html.push(inlineMarkdown(line.trim())); continue;
    }
    const item = line.match(/^\s*(?:[-*+]\s+|(\d+)\.\s+)(.*)$/);
    if (item) {
      flushParagraph();
      const tag = item[1] ? "ol" : "ul";
      if (listTag && listTag !== tag) closeList();
      if (!listTag) listTag = tag;
      listItems.push(inlineMarkdown(item[2]));
      continue;
    }
    if (listTag && /^\s{2,}\S/.test(line)) {
      listItems[listItems.length - 1] += ` ${inlineMarkdown(line.trim())}`;
      continue;
    }
    closeList();
    paragraph.push(line.replace(/\\\s*$/, ""));
  }
  flushParagraph(); closeList();
  return html.join("\n");
}

function quickStartNavigation(language) {
  const chinese = language === "zh-CN";
  const labels = chinese
    ? ["快速上手导航", "后退", "前进", "返回快速上手首页", "转到页面顶部", "转到页面底部"]
    : ["Quick Start navigation", "Go back", "Go forward", "Go to Quick Start home", "Go to page top", "Go to page bottom"];
  return `<nav class="history-controls" aria-label="${labels[0]}">\n`
    + `<button type="button" data-history="back" aria-label="${labels[1]}" title="${labels[1]}">←</button>`
    + `<button type="button" data-history="forward" aria-label="${labels[2]}" title="${labels[2]}">→</button>`
    + `<button type="button" data-navigation="home" aria-label="${labels[3]}" title="${labels[3]}">⌂</button>`
    + `<button type="button" data-scroll="top" aria-label="${labels[4]}" title="${labels[4]}">↑</button>`
    + `<button type="button" data-scroll="bottom" aria-label="${labels[5]}" title="${labels[5]}">↓</button>\n</nav>`;
}

function quickStartHeader(language, showTabs = false) {
  const brand = showTabs
    ? `<span data-quick-start-language="en">OctoPus</span><span data-quick-start-language="zh-CN" hidden>章鱼简谱</span>`
    : language === "zh-CN" ? "章鱼简谱" : "OctoPus";
  const languageNav = showTabs
    ? `<nav role="tablist" aria-label="Quick Start language / 快速上手语言">`
      + `<button id="tab-en" role="tab" aria-selected="true" aria-controls="quick-start-en">English</button>`
      + `<button id="tab-zh-CN" role="tab" aria-selected="false" aria-controls="quick-start-zh-CN" tabindex="-1">简体中文</button></nav>`
    : `<nav aria-label="${language === "zh-CN" ? "快速上手语言" : "Quick Start language"}"><a href="index.html#en">English</a> | `
      + `<a href="index.html#zh-CN">简体中文</a></nav>`;
  return `<header class="quick-start-header"><a class="quick-start-brand" href="https://github.com/OctaveMelody/OctoPus">`
    + `${brand}<small>by OctaveMelody</small></a>${languageNav}</header>`;
}

const quickStartPages = [["en", quickStartSource], ["zh-CN", quickStartChineseSource]]
  .map(([language, source]) => ({ language, body: markdownToHtml(readFileSync(source, "utf8")) }));
const quickStartIndex = `<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n`
  + `<meta name="viewport" content="width=device-width,initial-scale=1">\n`
  + `<title>OctoPus Quick Start</title><link rel="stylesheet" href="quickstart.css">\n`
  + `<script src="quickstart.js" defer></script></head><body>${quickStartNavigation("en")}`
  + `${quickStartHeader("en", true)}<main class="quick-start">`
  + `<article id="quick-start-en" data-quick-start-language="en" lang="en" role="tabpanel" aria-labelledby="tab-en">${quickStartPages[0].body}</article>`
  + `<article id="quick-start-zh-CN" data-quick-start-language="zh-CN" lang="zh-CN" role="tabpanel" aria-labelledby="tab-zh-CN" hidden>${quickStartPages[1].body}</article>`
  + `</main></body></html>\n`;
writeFileSync(path.join(quickStartOutput, "index.html"), quickStartIndex);

for (const { language, body } of quickStartPages) {
  const title = language === "zh-CN" ? "章鱼简谱快速上手" : "OctoPus Quick Start";
  const page = `<!doctype html>\n<html lang="${language}"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>${title}</title><link rel="stylesheet" href="quickstart.css">\n<script src="quickstart.js" defer></script></head>\n<body>${quickStartNavigation(language)}${quickStartHeader(language)}<main class="quick-start">${body}</main></body></html>\n`;
  writeFileSync(path.join(quickStartOutput, `${language}.html`), page);
}

const version = readFileSync(path.join(repositoryRoot, "VERSION"), "utf8").trim()
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");
function replaceManualVersions(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      replaceManualVersions(target);
    } else if (entry.isFile() && entry.name.endsWith(".html")) {
      writeFileSync(target, readFileSync(target, "utf8").replaceAll("{{APP_VERSION}}", version));
    }
  }
}
replaceManualVersions(path.join(frontendAssets, "user-manual"));
