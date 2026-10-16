import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./workspace/App";
import "./workspace/app.css";
import fontStyles from "./fonts.css?raw";

declare const __OCTOPUS_BUNDLE_FONTS__: boolean;

async function registerBundledFontFaces() {
  if (!__OCTOPUS_BUNDLE_FONTS__) return;
  let css = fontStyles;
  const native = window.__TAURI__?.core;
  if (native) {
    const directory = await native.invoke<string>("font_directory");
    const root = directory.replace(/[\\/]+$/, "");
    css = fontStyles.replace(/url\("(\/fonts\/[^\"]+)"\)/g, (_match, asset: string) => {
      const relative = asset.slice("/fonts/".length);
      return `url("${native.convertFileSrc(`${root}/${relative}`)}")`;
    });
  }
  const style = document.createElement("style");
  style.textContent = css;
  document.head.append(style);
}

async function startApplication() {
  try {
    await registerBundledFontFaces();
  } catch (error) {
    // Keep the editor usable if optional webview font registration fails.
    console.error("Could not register bundled application fonts", error);
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

void startApplication();
