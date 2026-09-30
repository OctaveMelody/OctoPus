import { prepareFontAssets } from "./prepare-font-assets.mjs";

import { cpSync, copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const packageRoot = fileURLToPath(new URL("../node_modules/pdfjs-dist/", import.meta.url));
const publicRoot = fileURLToPath(new URL("../../../build/pdfjs-assets/pdfjs/", import.meta.url));

mkdirSync(publicRoot, { recursive: true });
for (const directory of ["cmaps", "iccs", "standard_fonts", "wasm"]) {
  cpSync(`${packageRoot}${directory}`, `${publicRoot}${directory}`, { recursive: true });
}
copyFileSync(`${packageRoot}LICENSE`, `${publicRoot}LICENSE-PDFJS`);

prepareFontAssets(dirname(publicRoot.replace(/[\\/]$/, "")));
