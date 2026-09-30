import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

export function prepareFontAssets(publicRoot) {
  const source = fileURLToPath(new URL("../../../src/octopus/assets/fonts/", import.meta.url));
  const manifest = JSON.parse(readFileSync(`${source}manifest.json`, "utf8"));
  for (const entry of [...manifest.faces, ...manifest.licenses]) {
    const bytes = readFileSync(`${source}${entry.file}`);
    if (createHash("sha256").update(bytes).digest("hex") !== entry.sha256) {
      throw new Error(`release font checksum mismatch: ${entry.file}`);
    }
    const target = `${publicRoot}/fonts/${entry.file}`;
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(`${source}${entry.file}`, target);
  }
  copyFileSync(`${source}manifest.json`, `${publicRoot}/fonts/manifest.json`);
}
