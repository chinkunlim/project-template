#!/usr/bin/env python3
"""Google Apps Script (GAS) starter: source, Node test harness, bundler and clasp deployment.

Purpose:
    Lets GAS code be written, unit-tested and deployed from a normal repository:
      - `src/*.js`         : GAS source (fully JSDoc-commented); `Log.js` is the shared logger
      - `dev/gasShim.js`   : runs the GAS files in Node with fake Apps Script services
      - `dev/build.js`     : bundles `src/*.js` into `Code.gs` (`--check` verifies it)
      - `test/*.test.js`   : `node --test` unit tests
      - clasp              : dev dependency in this folder (`pnpm exec clasp ...`), never global
      - `.clasp.json`      : script ID (safe to commit); `~/.clasprc.json` holds the login token
                             and must never be committed
      - `.claspignore`     : only `Code.gs` and `appsscript.json` are pushed

    Used standalone (`--stack gas`, files at the project root) or as an add-on to a
    Python project (`--with gas`, files under `gas/`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from project_template.packs.common import npm_slug, package_json, write_package_json
from project_template.packs.common import write_file as _write

logger = logging.getLogger(__name__)

CLASP_VERSION = "^2.4.2"
CLASPIGNORE = """# Push only the bundle and the manifest (clasp reads this file)
**/**
!Code.gs
!appsscript.json
"""
CLASP_EXAMPLE = {"scriptId": "<Apps Script 專案設定 → 指令碼 ID>", "rootDir": "."}
GAS_GUIDE = """# GAS — Google Apps Script

程式寫在 `src/*.js`，用 Node 測試，打包成 `Code.gs` 後用本資料夾的 clasp 推送（不需要全域安裝）。

1. 安裝本資料夾的 clasp（裝在 `node_modules/`，不影響主機）：

```bash
pnpm install
```

2. 在 Node 中執行 GAS 單元測試：

```bash
pnpm test
```

3. 第一次使用時登入 Google（憑證存在 `~/.clasprc.json`，絕不 commit）：

```bash
pnpm exec clasp login
```

4. 建立 `.clasp.json` 並填入指令碼 ID（這個檔案可以 commit）：

```bash
cp .clasp.json.example .clasp.json
```

5. 打包 `Code.gs` 並推送：

```bash
pnpm run push
```
"""


GAS_SOURCES = {
    "Config.js": '''/**
 * @file Configuration reader for Google Apps Script (Script Properties).
 */

/**
 * Read settings from Script Properties.
 * @param {GoogleAppsScript.Properties.Properties} [props] Property store; defaults to Script Properties.
 * @returns {{appEnv: string, logLevel: string}} Settings object.
 */
function getConfig(props) {
  var log = createLogger("Config");
  var store = props || PropertiesService.getScriptProperties();
  var cfg = { appEnv: store.getProperty("APP_ENV") || "production", logLevel: store.getProperty("LOG_LEVEL") || "INFO" };
  log.debug("config loaded env=" + cfg.appEnv);
  return cfg;
}
''',
    "Log.js": '''/**
 * @file Logging for Google Apps Script: one run id per execution, a level filter and the module name.
 *
 * Apps Script cannot write files, so lines go to `console` (Executions log / Cloud Logging);
 * WARNING and above use console.warn / console.error. All files share one global scope, so each
 * function creates its logger where it runs: `var log = createLogger("Main");`.
 */

var LOG_LEVELS_ = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 };
var LOG_STATE_ = { runId: "", level: 20 };

/**
 * Set the minimum level for this execution.
 * @param {string} name DEBUG, INFO, WARNING or ERROR (unknown names mean INFO).
 * @returns {void}
 */
function setLogLevel(name) {
  LOG_STATE_.level = LOG_LEVELS_[String(name).toUpperCase()] || LOG_LEVELS_.INFO;
}

/**
 * Write one log line to the Apps Script console.
 * @param {string} level Level name, e.g. "INFO".
 * @param {string} name Logger (module) name.
 * @param {string} message Message text (never secrets or personal data).
 * @returns {void}
 */
function writeLog_(level, name, message) {
  if (LOG_LEVELS_[level] < LOG_STATE_.level) {
    return;
  }
  if (!LOG_STATE_.runId) {
    LOG_STATE_.runId = Math.random().toString(16).slice(2, 10);
  }
  var line = level + " [" + LOG_STATE_.runId + "] " + name + " - " + message;
  if (LOG_LEVELS_[level] >= LOG_LEVELS_.ERROR) {
    console.error(line);
  } else if (LOG_LEVELS_[level] >= LOG_LEVELS_.WARNING) {
    console.warn(line);
  } else {
    console.log(line);
  }
}

/**
 * Create a module logger.
 * @param {string} name Module name shown on every line, e.g. "Main".
 * @returns {{debug: Function, info: Function, warn: Function, error: Function}} Logger.
 */
function createLogger(name) {
  return {
    debug: function (message) { writeLog_("DEBUG", name, message); },
    info: function (message) { writeLog_("INFO", name, message); },
    warn: function (message) { writeLog_("WARNING", name, message); },
    error: function (message) { writeLog_("ERROR", name, message); },
  };
}
''',
    "Main.js": '''/**
 * @file Web App entrypoint for Google Apps Script.
 */

/**
 * Handle HTTP GET requests to the Web App.
 * @returns {GoogleAppsScript.HTML.HtmlOutput} Plain status page.
 */
function doGet() {
  var log = createLogger("Main");
  var cfg = getConfig();
  setLogLevel(cfg.logLevel);
  log.info("doGet start env=" + cfg.appEnv);
  return HtmlService.createHtmlOutput("OK (" + cfg.appEnv + ")");
}
''',
}

GAS_DEV_FILES = {
    "dev/gasShim.js": '''"use strict";
/**
 * @file Loads src/*.js into a Node VM with fake Apps Script services so GAS code can be unit tested.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

/**
 * Load every src/*.js file into a sandbox that mimics Apps Script globals.
 * @param {Record<string, string>} [propsOverride={}] Script Properties returned by the fake PropertiesService.
 * @returns {object} The sandbox; GAS functions are available as its properties.
 */
function loadGas(propsOverride = {}) {
  const sandbox = {
    console,
    PropertiesService: {
      getScriptProperties: () => ({ getProperty: (k) => (k in propsOverride ? propsOverride[k] : null) }),
    },
    HtmlService: { createHtmlOutput: (html) => ({ getContent: () => String(html) }) },
  };
  vm.createContext(sandbox);
  const srcDir = path.join(__dirname, "..", "src");
  for (const file of fs.readdirSync(srcDir).filter((f) => f.endsWith(".js")).sort()) {
    vm.runInContext(fs.readFileSync(path.join(srcDir, file), "utf8"), sandbox, { filename: file });
  }
  return sandbox;
}

module.exports = { loadGas };
''',
    "dev/build.js": '''#!/usr/bin/env node
"use strict";
/**
 * @file Bundles src/*.js into Code.gs for deployment; `--check` verifies the bundle is up to date.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SRC_DIR = path.join(ROOT, "src");
const OUT_FILE = path.join(ROOT, "Code.gs");

/**
 * Concatenate every src/*.js file (sorted by name) into one bundle.
 * @returns {string} Bundle text written to Code.gs.
 */
function buildBundle() {
  const chunks = ["// AUTO-GENERATED BY dev/build.js — DO NOT EDIT DIRECTLY"];
  for (const file of fs.readdirSync(SRC_DIR).filter((f) => f.endsWith(".js")).sort()) {
    chunks.push(`// --- ${file} ---`);
    chunks.push(fs.readFileSync(path.join(SRC_DIR, file), "utf8").trim());
  }
  return chunks.join("\\n\\n") + "\\n";
}

const expected = buildBundle();
if (process.argv.includes("--check")) {
  const current = fs.existsSync(OUT_FILE) ? fs.readFileSync(OUT_FILE, "utf8") : "";
  if (current !== expected) {
    console.error("Code.gs is out of sync with src/*.js. Run `pnpm run build`.");
    process.exit(1);
  }
  console.log("Code.gs is in sync.");
} else {
  fs.writeFileSync(OUT_FILE, expected, "utf8");
  console.log("Generated Code.gs");
}
''',
    "test/gas.test.js": '''"use strict";
/**
 * @file Unit tests for the GAS Web App, run in Node through dev/gasShim.js.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadGas } = require("../dev/gasShim");

test("doGet returns OK with the configured environment", () => {
  const gas = loadGas({ APP_ENV: "staging" });
  assert.equal(gas.doGet().getContent(), "OK (staging)");
});
''',
}


def build_gas_bundle(sources: dict[str, str]) -> str:
    """Build `Code.gs` exactly like `dev/build.js` so `--check` passes immediately.

    Args:
        sources: Mapping of file name -> content for every `src/*.js` file.

    Returns:
        Bundle text.
    """
    chunks = ["// AUTO-GENERATED BY dev/build.js — DO NOT EDIT DIRECTLY"]
    for name in sorted(sources):
        chunks += [f"// --- {name} ---", sources[name].strip()]
    return "\n\n".join(chunks) + "\n"


def scaffold_gas_pack(target_dir: Path, project_name: str, description: str, options: dict[str, str]) -> None:
    """Create the Google Apps Script starter in `target_dir`.

    Args:
        target_dir: Folder that receives the GAS project (project root, or `gas/` for the add-on).
        project_name: Project name (used for the npm package name).
        description: One-line description.
        options: `timezone` (IANA name for `appsscript.json`, e.g. `Asia/Taipei`) and
            `pnpm` (version for `packageManager`; empty to omit).
    """
    logger.debug("scaffold gas_pack in %s", target_dir)
    scripts = {
        "build": "node dev/build.js",
        "build:check": "node dev/build.js --check",
        "push": "node dev/build.js && clasp push",
        "login": "clasp login",
    }
    pkg_options = {"dev_deps": {"@google/clasp": CLASP_VERSION}, "pnpm": options.get("pnpm", "")}
    write_package_json(target_dir, package_json(npm_slug(project_name) + "-gas", description, scripts, pkg_options))
    appsscript = {"timeZone": options.get("timezone", "UTC"), "dependencies": {}, "exceptionLogging": "STACKDRIVER", "runtimeVersion": "V8"}
    _write(target_dir / "appsscript.json", json.dumps(appsscript, indent=2) + "\n")
    _write(target_dir / ".claspignore", CLASPIGNORE)
    _write(target_dir / ".clasp.json.example", json.dumps(CLASP_EXAMPLE, ensure_ascii=False, indent=2) + "\n")
    _write(target_dir / "GAS.md", GAS_GUIDE)
    for name, content in GAS_SOURCES.items():
        _write(target_dir / "src" / name, content)
    for rel, content in GAS_DEV_FILES.items():
        _write(target_dir / rel, content, executable=rel.endswith("build.js"))
    _write(target_dir / "Code.gs", build_gas_bundle(GAS_SOURCES))
