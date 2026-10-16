import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { shouldRegisterBundledFontFaces } from "./scripts/font-policy.mjs";

export default defineConfig(({ mode }) => ({
  define: {
    __OCTOPUS_BUNDLE_FONTS__: JSON.stringify(shouldRegisterBundledFontFaces({
      mode,
      targetTriple: process.env.TAURI_ENV_TARGET_TRIPLE,
      hostPlatform: process.platform,
    })),
  },
  publicDir: "../../build/pdfjs-assets",
  build: { outDir: "../../build/frontend", emptyOutDir: true },
  plugins: [react()],
  clearScreen: false,
}));
