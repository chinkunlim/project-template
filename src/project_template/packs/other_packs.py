#!/usr/bin/env python3
"""Starter packs for Node.js and language-agnostic (generic) projects (Go: `go_pack.py`, Rust: `rust_pack.py`).

Purpose:
    Small, fully commented starters that follow the layer rules
    (config -> domain -> services) and the comment rules, used by `services/scaffold.py`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from project_template.packs.common import package_json, write_package_json
from project_template.packs.common import write_file as _write

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node.js
# ---------------------------------------------------------------------------

NODE_FILES = {
    "src/config/index.js": """/**
 * @file Configuration layer: the ONLY module allowed to read process.env.
 * The project's `.env` is loaded when present; variables already set win.
 */
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createLogger } from "./logger.js";

const logger = createLogger("config");
export const PROJECT_ROOT = fileURLToPath(new URL("../..", import.meta.url));

/**
 * Read application settings from environment variables.
 * @param {Record<string, string|undefined>} [env=process.env] Environment variables to read.
 * @returns {{appEnv: string, logLevel: string, logToFile: boolean, dataDir: string}} Frozen settings object.
 */
export function loadConfig(env = process.env) {
  const envFile = path.join(PROJECT_ROOT, ".env");
  if (env === process.env && existsSync(envFile) && typeof process.loadEnvFile === "function") {
    process.loadEnvFile(envFile);
  }
  const dataDir = (env.DATA_DIR || "").trim();
  const config = Object.freeze({
    appEnv: (env.APP_ENV || "development").trim(),
    logLevel: (env.LOG_LEVEL || "INFO").trim().toUpperCase(),
    logToFile: /^(1|true|yes|on)$/i.test((env.LOG_TO_FILE || "true").trim()),
    dataDir: dataDir ? path.resolve(PROJECT_ROOT, dataDir) : "",
  });
  logger.debug(`config loaded env=${config.appEnv} dataDir=${config.dataDir}`);
  return config;
}
""",
    "src/config/logger.js": """/**
 * @file Logging shared by every module, built for tracing one run.
 *
 * Every line looks like
 *   2026-10-20T09:15:02.481Z INFO    [3f9a1c2e] services/greeting - greeting user=Ann
 * Console output goes to stderr (stdout stays for the program's real output). After
 * `setupLogging(config)` with `logToFile`, lines are also appended to `<DATA_DIR>/logs/app.log`
 * and WARNING and above to `errors.log` (outside the project). Uncaught errors are logged too.
 * Each module creates its own logger: `const logger = createLogger("services/greeting");`
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";

const LEVELS = Object.freeze({ DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 });
const state = { runId: "-", level: LEVELS.INFO, logDir: "" };

/**
 * Write one log line to stderr and, when configured, to the log files.
 * @param {string} level Level name, e.g. "INFO".
 * @param {string} name Logger (module) name.
 * @param {string} message Message text (never secrets or personal data).
 * @returns {void}
 */
function write(level, name, message) {
  if (LEVELS[level] < state.level) {
    return;
  }
  const line = `${new Date().toISOString()} ${level.padEnd(7)} [${state.runId}] ${name} - ${message}`;
  console.error(line);
  if (state.logDir) {
    appendFileSync(path.join(state.logDir, "app.log"), line + "\\n");
    if (LEVELS[level] >= LEVELS.WARNING) {
      appendFileSync(path.join(state.logDir, "errors.log"), line + "\\n");
    }
  }
}

/**
 * Create a module logger.
 * @param {string} name Module name shown on every line, e.g. "services/greeting".
 * @returns {{debug: Function, info: Function, warn: Function, error: Function}} Frozen logger.
 */
export function createLogger(name) {
  return Object.freeze({
    debug: (message) => write("DEBUG", name, message),
    info: (message) => write("INFO", name, message),
    warn: (message) => write("WARNING", name, message),
    error: (message) => write("ERROR", name, message),
  });
}

/**
 * Configure logging once per process and start a new run id.
 * @param {{logLevel: string, logToFile: boolean, dataDir: string}} config Settings from loadConfig().
 * @returns {string} The run id written on every line of this run.
 */
export function setupLogging(config) {
  state.runId = randomUUID().slice(0, 8);
  state.level = LEVELS[config.logLevel] ?? LEVELS.INFO;
  state.logDir = config.logToFile && config.dataDir ? path.join(config.dataDir, "logs") : "";
  if (state.logDir) {
    mkdirSync(state.logDir, { recursive: true });
  }
  process.on("uncaughtExceptionMonitor", (err) => write("CRITICAL", "uncaught", err.stack || String(err)));
  write("INFO", "logger", `run started pid=${process.pid} node=${process.version} logDir=${state.logDir}`);
  return state.runId;
}
""",
    "src/domain/greeting.js": """/**
 * @file Domain layer: pure value objects with no I/O.
 */
import { createLogger } from "../config/logger.js";

const logger = createLogger("domain/greeting");

/**
 * Create an immutable greeting value object.
 * @param {string} userName Name typed by the user; blank falls back to "World".
 * @param {string} environment Environment the greeting is produced in.
 * @returns {{message: string, environment: string}} Frozen greeting.
 */
export function makeGreeting(userName, environment) {
  const clean = String(userName || "").trim() || "World";
  logger.debug(`greeting built for ${clean.length} characters`);
  return Object.freeze({ message: `Hello, ${clean}!`, environment });
}
""",
    "src/services/greetingService.js": """/**
 * @file Services layer: business logic using config values and domain objects.
 */
import { createLogger } from "../config/logger.js";
import { makeGreeting } from "../domain/greeting.js";

const logger = createLogger("services/greetingService");

/**
 * Greet a user in the configured environment.
 * @param {string} userName Name of the user to greet.
 * @param {{appEnv: string}} config Settings from loadConfig().
 * @returns {{message: string, environment: string}} The greeting.
 */
export function greetUser(userName, config) {
  logger.info(`greeting env=${config.appEnv}`);
  return makeGreeting(userName, config.appEnv);
}
""",
    "src/entrypoints/cli.js": """/**
 * @file Command-line entrypoint: `node src/entrypoints/cli.js Alice`.
 * Loads config, starts logging (run id, files in DATA_DIR/logs) and prints the greeting.
 */
import { pathToFileURL } from "node:url";
import { loadConfig } from "../config/index.js";
import { createLogger, setupLogging } from "../config/logger.js";
import { greetUser } from "../services/greetingService.js";

const logger = createLogger("entrypoints/cli");

/**
 * Run the CLI.
 * @param {string[]} [argv=process.argv.slice(2)] Command-line arguments (first one is the name).
 * @returns {number} Exit code.
 */
export function main(argv = process.argv.slice(2)) {
  const config = loadConfig();
  setupLogging(config);
  logger.info(`cli start args=${argv.length}`);
  console.log(greetUser(argv[0] || "World", config).message);
  logger.info("cli done exit=0");
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = main();
}
""",
    "test/greeting.test.js": '''/**
 * @file Unit tests for the starter greeting service (node --test).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { loadConfig } from "../src/config/index.js";
import { greetUser } from "../src/services/greetingService.js";

test("greetUser formats the greeting with the configured environment", () => {
  const res = greetUser("Bob", loadConfig({ APP_ENV: "test" }));
  assert.equal(res.message, "Hello, Bob!");
  assert.equal(res.environment, "test");
});
''',
}


def scaffold_node_pack(target_dir: Path, project_name: str, description: str, pnpm: str = "") -> None:
    """Create the Node.js (ESM) starter.

    Args:
        target_dir: Project root directory.
        project_name: Project name (used for the npm package name).
        description: One-line description.
        pnpm: pnpm version for the `packageManager` field (empty to omit).
    """
    logger.debug("scaffold node_pack in %s", target_dir)
    slug = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"
    scripts = {"start": "node src/entrypoints/cli.js"}
    write_package_json(target_dir, package_json(slug, description, scripts, {"module_type": "module", "pnpm": pnpm}))
    for rel, content in NODE_FILES.items():
        _write(target_dir / rel, content)


def scaffold_generic_pack(target_dir: Path, project_name: str) -> None:
    """Create a language-agnostic starter with `VERSION` and layered `src/<layer>/LAYER.md` placeholders.

    Args:
        target_dir: Project root directory.
        project_name: Project name for the placeholder READMEs.
    """
    logger.debug("scaffold generic_pack in %s", target_dir)
    _write(target_dir / "VERSION", "0.1.0\n")
    for layer in ("config", "domain", "services", "adapters"):
        _write(
            target_dir / "src" / layer / "LAYER.md",
            f"# `{layer}` layer ({project_name})\n\nPut `{layer}` modules here, or change `[architecture]` in `.agents/project.toml`.\n"
            "Every program file that defines functions creates a module logger (docs/standards/CODING_PRINCIPLES.md §0.4).\n",
        )
