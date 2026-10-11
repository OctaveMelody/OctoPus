import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => ({
  publicDir: "../../build/pdfjs-assets",
  build: { outDir: "../../build/frontend", emptyOutDir: true },
  plugins: [react()],
  clearScreen: false,
}));
