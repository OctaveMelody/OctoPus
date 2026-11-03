import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { shouldRegisterBundledFontFaces, uiFontPlatformForTarget } from "./scripts/font-policy.mjs";

export default defineConfig(({ mode }) => ({
  define: {
    __OCTOPUS_BUNDLE_FONTS__: JSON.stringify(shouldRegisterBundledFontFaces({
      mode,
      targetTriple: process.env.TAURI_ENV_TARGET_TRIPLE,
      hostPlatform: process.platform,
    })),
    __OCTOPUS_UI_PLATFORM__: JSON.stringify(uiFontPlatformForTarget({
      mode,
      targetTriple: process.env.TAURI_ENV_TARGET_TRIPLE,
      hostPlatform: process.platform,
    })),
  },
  publicDir: "../../build/pdfjs-assets",
  build: {
    outDir: "../../build/frontend",
    emptyOutDir: true,
    // shortcut: 501 kB accommodates the PDF.js core; recheck after PDF.js upgrades.
    chunkSizeWarningLimit: 501,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const path = id.replace(/\\/g, "/");
          if (path.includes("/node_modules/pdfjs-dist/")) return "pdfjs";
          if (path.includes("/node_modules/react/") || path.includes("/node_modules/react-dom/")) {
            return "react-vendor";
          }
          if (path.includes("/node_modules/@codemirror/")
            || path.includes("/node_modules/@lezer/")
            || path.includes("/node_modules/codemirror/")) {
            return "editor-vendor";
          }
        },
      },
    },
  },
  plugins: [react()],
  clearScreen: false,
}));
