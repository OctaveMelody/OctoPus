import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./workspace/App";
import "./workspace/app.css";
import "./fonts.css";

const scoreFonts = [
  'normal 400 16px "Noto Sans SC"', 'normal 700 16px "Noto Sans SC"',
  'normal 400 16px "Noto Serif SC"', 'normal 700 16px "Noto Serif SC"',
  'normal 400 16px "Liberation Sans"', 'normal 700 16px "Liberation Sans"',
  'italic 400 16px "Liberation Sans"', 'italic 700 16px "Liberation Sans"',
];

Promise.all(scoreFonts.map((font) => document.fonts.load(font, "简谱你好 ABC")))
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
