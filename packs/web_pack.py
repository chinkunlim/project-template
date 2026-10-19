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

from pathlib import Path

from packs.common import write_file as _write

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
}

.muted { color: var(--color-muted); }
"""

APP_JS = """/**
 * @file Front-end logic: renders the four standard UI states (loading, empty, error, data).
 */

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
 * Load data and render it (replace the sample data with a fetch() call to your API).
 * @returns {Promise<void>}
 */
async function load() {
  render("loading");
  try {
    const items = ["範例資料 A", "範例資料 B"];
    render(items.length ? "data" : "empty", { items });
  } catch (error) {
    console.error(error);
    render("error");
  }
}

document.getElementById("refresh")?.addEventListener("click", load);
load();
"""


WEB_GUIDE = """# Web 前端

純 HTML + CSS + JavaScript，不需要建置工具。檔案開頭都要有用途說明註解（`agentctl check` 會檢查）。

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
    web = target_dir / "web"
    _write(web / "index.html", INDEX_HTML.format(name=project_name))
    _write(web / "styles.css", STYLES_CSS)
    _write(web / "app.js", APP_JS)
    _write(web / "WEB.md", WEB_GUIDE)
