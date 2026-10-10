import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./workspace/App";
import "./workspace/app.css";
import fontStyles from "./fonts.css?raw";

function registerBundledFontFallbacks() {
  const style = document.createElement("style");
  style.textContent = fontStyles;
  document.head.append(style);
}

registerBundledFontFallbacks();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
