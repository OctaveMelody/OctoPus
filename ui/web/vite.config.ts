import { defineConfig } from "vite";
import { rmSync } from "node:fs";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  publicDir: "../../build/pdfjs-assets",
  build: { outDir: "../../build/frontend", emptyOutDir: true },
  plugins: [react(), {
    name: "external-desktop-fonts",
    closeBundle() {
      if (mode === "desktop") rmSync(new URL("../../build/frontend/fonts", import.meta.url), { recursive: true, force: true });
    },
  }],
  clearScreen: false,
}));
