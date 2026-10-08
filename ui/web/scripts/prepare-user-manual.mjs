import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

const version = (process.env.VITE_APP_VERSION || "development")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");
for (const page of ["en.html", "zh-CN.html", "index.html"]) {
  const target = path.join(frontendAssets, "user-manual", page);
  writeFileSync(target, readFileSync(target, "utf8").replaceAll("{{APP_VERSION}}", version));
}
