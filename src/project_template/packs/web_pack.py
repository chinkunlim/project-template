#!/usr/bin/env python3
"""Plain web add-on (`--with web`): HTML + CSS + JavaScript without a build step.

Purpose:
    For Python projects that also need a small front end (a static page, a dashboard
    served by the Python app, or a GAS HtmlService page prototype). Creates `web/` with:
      - `index.html` : semantic layout, viewport meta, accessible structure
      - `styles.css` : design tokens (CSS custom properties) and responsive layout
      - `app.js`     : ES module with JSDoc comments, Loading / Empty / Error / Data states
    Every file starts with a header comment, matching the project's comment rules.
    Preview locally without installing anything (bound to 127.0.0.1 only, never the LAN):
    `uv run python -m http.server 8000 --bind 127.0.0.1 -d web`, then open http://127.0.0.1:8000.
"""

from __future__ import annotations

import logging
from pathlib import Path

from project_template.packs.common import write_file as _write

logger = logging.getLogger(__name__)

INDEX_HTML = """<!DOCTYPE html>
<!--
  {name} — web front end entry page.
  Loads styles.css and app.js; the #app section shows loading / empty / error / data states.
-->
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header class="site-header">
    <h1>{name}</h1>
  </header>
  <main>
    <section id="app" aria-live="polite"></section>
    <button type="button" id="refresh">重新載入</button>
  </main>
  <script type="module" src="app.js"></script>
</body>
</html>
"""

STYLES_CSS = """/*
 * Styles for the web front end: design tokens first, then layout and components.
 * Change colours and spacing through the custom properties in :root only.
 */
:root {
  --color-bg: #faf8f5;
  --color-text: #1f2328;
  --color-muted: #59636e;
  --color-accent: #0f6cbd;
  --space: 1rem;
  --radius: 10px;
  --font: system-ui, -apple-system, "Noto Sans TC", sans-serif;
  --dur-hover: 140ms;
  --dur-slide: 240ms;
  --ease: cubic-bezier(0.2, 0.8, 0.2, 1);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: var(--font);
  color: var(--color-text);
  background: var(--color-bg);
  line-height: 1.6;
}

.site-header, main {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space);
}

#app {
  min-height: 6rem;
  padding: var(--space);
  border: 1px solid #d0d7de;
  border-radius: var(--radius);
}

button {
  margin-top: var(--space);
  padding: 0.5rem 1rem;
  border: 0;
  border-radius: var(--radius);
  color: #fff;
  background: var(--color-accent);
  cursor: pointer;
  transition: opacity var(--dur-hover) var(--ease);
}

button:hover { opacity: 0.9; }

.offline-banner {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 100;
  display: flex;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem 1rem;
  border-radius: var(--radius);
  background: #8c1d18;
  color: #fff;
}

.muted { color: var(--color-muted); }

@media (pointer: coarse) {
  button, input, select, textarea, a {
    min-height: 44px;
    min-width: 44px;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
"""

LOGGER_JS = """/**
 * @file Browser logger shared by every front-end module: one run id per page load, level, module name.
 *
 * Browsers cannot write to DATA_DIR, so lines go to the developer console; send errors that the
 * team must see to the API (which logs them to DATA_DIR/logs). Debug lines appear after
 * `localStorage.setItem("LOG_LEVEL", "DEBUG")`. Each module creates one:
 * `const logger = createLogger("app");`
 */

const LEVELS = Object.freeze({ DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 });
const RUN_ID = Math.random().toString(16).slice(2, 10);

/**
 * Read the minimum level (INFO unless LOG_LEVEL is set in localStorage).
 * @returns {number} Numeric level.
 */
function currentLevel() {
  try {
    return LEVELS[(localStorage.getItem("LOG_LEVEL") || "INFO").toUpperCase()] ?? LEVELS.INFO;
  } catch {
    return LEVELS.INFO;
  }
}

/**
 * Write one line to the browser console.
 * @param {string} level Level name, e.g. "INFO".
 * @param {string} name Logger (module) name.
 * @param {unknown[]} args Message and extra values (never secrets or personal data).
 * @returns {void}
 */
function write(level, name, args) {
  if (LEVELS[level] < currentLevel()) return;
  const prefix = `${new Date().toISOString()} ${level} [${RUN_ID}] ${name} -`;
  const sink = level === "ERROR" ? console.error : level === "WARNING" ? console.warn : console.log;
  sink(prefix, ...args);
}

/**
 * Create a module logger.
 * @param {string} name Module name shown on every line.
 * @returns {{debug: Function, info: Function, warn: Function, error: Function}} Frozen logger.
 */
export function createLogger(name) {
  return Object.freeze({
    debug: (...args) => write("DEBUG", name, args),
    info: (...args) => write("INFO", name, args),
    warn: (...args) => write("WARNING", name, args),
    error: (...args) => write("ERROR", name, args),
  });
}
"""

APP_JS = """/**
 * @file Front-end logic: renders the four standard UI states (loading, empty, error, data).
 */
import { createEventBus } from "./api_client.js";
import { createLogger } from "./logger.js";

const logger = createLogger("app");
const bus = createEventBus();
const container = document.getElementById("app");

/**
 * Render one UI state into the #app section.
 * @param {"loading"|"empty"|"error"|"data"} state State to show.
 * @param {{items?: string[]}} [payload={}] Data for the "data" state.
 * @returns {void}
 */
function render(state, payload = {}) {
  if (!container) return;
  const views = {
    loading: '<p class="muted">載入中…</p>',
    empty: '<p class="muted">目前沒有資料。</p>',
    error: '<p role="alert">載入失敗，請重試。</p>',
    data: `<ul>${(payload.items || []).map((item) => `<li>${item}</li>`).join("")}</ul>`,
  };
  container.innerHTML = views[state] || views.empty;
}

/**
 * Load data and render it (replace the sample data with apiFetch() to your API).
 * @returns {Promise<void>}
 */
async function load() {
  render("loading");
  try {
    const items = ["範例資料 A", "範例資料 B"];
    render(items.length ? "data" : "empty", { items });
    bus.emit("items:loaded", { count: items.length });
    logger.info(`loaded items=${items.length}`);
  } catch (error) {
    logger.error("load failed", error);
    render("error");
  }
}

document.getElementById("refresh")?.addEventListener("click", load);
load();
"""

API_CLIENT_JS = """/**
 * @file Zero-build Vanilla JS helpers: read-only retrying fetch, EventBus and StateStore.
 */
import { createLogger } from "./logger.js";

const logger = createLogger("api_client");

/**
 * Show or hide the offline banner when the local server stops responding.
 * @param {boolean} show True to display `#offlineBanner`.
 * @returns {void}
 */
export function setOfflineBanner(show) {
  let bar = document.getElementById("offlineBanner");
  if (!bar && show) {
    bar = document.createElement("div");
    bar.id = "offlineBanner";
    bar.className = "offline-banner";
    bar.setAttribute("role", "alert");
    bar.textContent = "本機伺服器沒有回應，請確認服務是否啟動後重新整理。";
    document.body.appendChild(bar);
  }
  if (bar) bar.style.display = show ? "flex" : "none";
}

/**
 * Fetch wrapper that retries GET once after 800ms on network failure, while never retrying writes.
 * @param {RequestInfo|URL} input Request URL or object.
 * @param {RequestInit} [init={}] Fetch init options.
 * @returns {Promise<Response>} HTTP response.
 */
export async function apiFetch(input, init = {}) {
  const method = String(init.method || "GET").toUpperCase();
  try {
    const res = await fetch(input, init);
    setOfflineBanner(false);
    return res;
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    if (method === "GET") {
      await new Promise((resolve) => setTimeout(resolve, 800));
      try {
        const retry = await fetch(input, init);
        setOfflineBanner(false);
        return retry;
      } catch (retryErr) {
        logger.warn("GET retry failed", retryErr);
      }
    }
    setOfflineBanner(true);
    throw err;
  }
}

/**
 * Create a lightweight publish/subscribe EventBus to decouple modular UI scripts.
 * @returns {{on: Function, off: Function, emit: Function}} Frozen bus interface.
 */
export function createEventBus() {
  const listeners = new Map();
  return Object.freeze({
    on(event, fn) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(fn);
    },
    off(event, fn) {
      listeners.get(event)?.delete(fn);
    },
    emit(event, payload) {
      for (const fn of listeners.get(event) || []) {
        try { fn(payload); } catch (err) { logger.error("bus handler error", err); }
      }
    },
  });
}

/**
 * Create a shallow UI state store backed by an EventBus.
 * @param {Record<string, unknown>} [initialState={}] Initial shallow state fields.
 * @param {{emit: Function}} [bus=createEventBus()] Event bus emitting `store:changed`.
 * @returns {{state: Record<string, unknown>, patch: Function}} Store object.
 */
export function createStateStore(initialState = {}, bus = createEventBus()) {
  const state = { ...initialState };
  return {
    state,
    patch(next) {
      Object.assign(state, next || {});
      bus.emit("store:changed", state);
    },
  };
}
"""


WEB_GUIDE = """# Web 前端

純 HTML + CSS + JavaScript，不需要建置工具。檔案開頭都要有用途說明註解（`agentctl check` 會檢查）。

- `api_client.js`：提供 `apiFetch`（GET 斷線重試 1 次、寫入絕不重試、離線橫幅）、`createEventBus` 與 `createStateStore`。
- `styles.css`：內建 `--dur-hover` / `--dur-slide` / `--ease` Motion Tokens 與 `@media (pointer: coarse)` 觸控熱區。
- 離線第三方資源：用 `pnpm` 鎖版安裝後透過腳本複製到 `web/vendor/`（預設已由 `code-review-guard` 與 `.graphifyignore` 排除）。

本機預覽（只綁 `127.0.0.1`，區網看不到；不需要安裝任何東西）：

```bash
uv run python -m http.server 8000 --bind 127.0.0.1 -d web
```

然後打開 http://127.0.0.1:8000 （不要用 localhost）。
"""


def scaffold_web_pack(target_dir: Path, project_name: str) -> None:
    """Create the `web/` front end.

    Args:
        target_dir: Project root directory.
        project_name: Project name shown as the page title.
    """
    logger.debug("scaffold web_pack in %s", target_dir)
    web = target_dir / "web"
    _write(web / "index.html", INDEX_HTML.format(name=project_name))
    _write(web / "styles.css", STYLES_CSS)
    _write(web / "api_client.js", API_CLIENT_JS)
    _write(web / "app.js", APP_JS)
    _write(web / "logger.js", LOGGER_JS)
    _write(web / "WEB.md", WEB_GUIDE)
