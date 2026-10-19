import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { validateEnv } from "./config/env";
import { initSentry } from "./config/sentry";
import "./index.css";

validateEnv();
if ("requestIdleCallback" in window)
  window.requestIdleCallback(
    () => {
      void initSentry().catch(() => {});
    },
    { timeout: 3000 },
  );
else
  setTimeout(() => {
    void initSentry().catch(() => {});
  }, 2000);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
