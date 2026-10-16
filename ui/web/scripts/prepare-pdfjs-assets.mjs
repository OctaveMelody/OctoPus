import { prepareFontAssets } from "./prepare-font-assets.mjs";

import { cpSync, copyFileSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import { shouldCopyFontAssetsToFrontend } from "./font-policy.mjs";

const packageRoot = fileURLToPath(new URL("../node_modules/pdfjs-dist/", import.meta.url));
const publicRoot = fileURLToPath(new URL("../../../build/pdfjs-assets/pdfjs/", import.meta.url));

mkdirSync(publicRoot, { recursive: true });
for (const directory of ["cmaps", "iccs", "standard_fonts", "wasm"]) {
  cpSync(`${packageRoot}${directory}`, `${publicRoot}${directory}`, { recursive: true });
}
copyFileSync(`${packageRoot}LICENSE`, `${publicRoot}LICENSE-PDFJS`);

const desktop = process.argv.includes("--desktop");
const frontendRoot = dirname(publicRoot.replace(/[\\/]$/, ""));
rmSync(`${frontendRoot}/fonts`, { recursive: true, force: true });
if (shouldCopyFontAssetsToFrontend(desktop)) prepareFontAssets(frontendRoot);
