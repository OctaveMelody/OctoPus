import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./workspace/App";
import "./workspace/app.css";
import fontStyles from "./fonts.css?raw";

const scoreFonts = [
  'normal 400 16px "MiSans"', 'normal 400 16px "Zhuque Fangsong (technical preview)"',
  'normal 400 16px "LXGW WenKai"', 'normal 400 16px "SimZhiSong"',
  'normal 400 16px "LXGW Neo XiHei"',
  'normal 400 16px "Noto Sans SC"', 'normal 700 16px "Noto Sans SC"',
  'normal 400 16px "Noto Serif SC"', 'normal 700 16px "Noto Serif SC"',
  'normal 400 16px "Liberation Sans"', 'normal 700 16px "Liberation Sans"',
  'italic 400 16px "Liberation Sans"', 'italic 700 16px "Liberation Sans"',
];

async function loadFonts() {
  const core = window.__TAURI__?.core;
  const directory = core ? await core.invoke<string>("font_directory") : undefined;
  const prefix = directory && core ? core.convertFileSrc(directory).replace(/\/$/, "") + "/" : "/fonts/";
  const style = document.createElement("style");
  style.textContent = fontStyles.replaceAll("/fonts/", prefix);
  document.head.append(style);
  await Promise.all(scoreFonts.map((font) => document.fonts.load(font, "简谱你好 ABC")));
}

loadFonts()
  .then(() => {
    ReactDOM.createRoot(document.getElementById("root")!).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    );
  })
  .catch((error: unknown) => {
    document.getElementById("root")!.textContent = "Could not load the application fonts.";
    console.error(error);
  });
