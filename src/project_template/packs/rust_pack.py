#!/usr/bin/env python3
"""Rust starter pack: layered crate modules, a CLI and `log` crate logging.

Purpose:
    Small, fully commented starter that follows the layer rules (config -> domain -> services)
    and the comment rules; every module logs through the `log` facade set up by `logging::setup_logging`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from project_template.packs.common import write_file as _write

logger = logging.getLogger(__name__)

RUST_CONFIG = """//! Configuration layer: the only module allowed to read environment variables.
use std::env;

use log::debug;

/// Immutable application settings.
#[derive(Debug, Clone, Default)]
pub struct AppConfig {
    /// Deployment environment, e.g. "development".
    pub app_env: String,
    /// DEBUG, INFO, WARNING or ERROR.
    pub log_level: String,
    /// Also write `<data_dir>/logs/app.log` and `errors.log`.
    pub log_to_file: bool,
    /// Data folder outside the project (empty: console only).
    pub data_dir: String,
}

/// Read one variable with a default.
/// * `key` - variable name.
/// * `fallback` - value used when it is missing or blank.
fn var_or(key: &str, fallback: &str) -> String {
    env::var(key).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty()).unwrap_or_else(|| fallback.to_string())
}

/// Read settings from environment variables, using defaults for missing values.
pub fn load_config() -> AppConfig {
    let cfg = AppConfig {
        app_env: var_or("APP_ENV", "development"),
        log_level: var_or("LOG_LEVEL", "INFO").to_uppercase(),
        log_to_file: matches!(var_or("LOG_TO_FILE", "true").to_lowercase().as_str(), "1" | "true" | "yes" | "on"),
        data_dir: var_or("DATA_DIR", ""),
    };
    debug!("config loaded env={} data_dir={}", cfg.app_env, cfg.data_dir);
    cfg
}
"""

RUST_LOGGING = """//! Logging setup shared by every module (`log` crate facade), built for tracing one run.
//!
//! Lines look like `1760951702 INFO    [3f9a1c2e] my_app::services - greeting env=development`
//! (UNIX seconds, run id, module). Console output goes to stderr; with `log_to_file` lines are
//! appended to `<data_dir>/logs/app.log` and WARN and above to `errors.log` (outside the project).
//! Panics are logged too. Modules log with `use log::{info, warn, error};` and `info!(...)`.
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use log::{info, Level, LevelFilter, Log, Metadata, Record};

use crate::config::AppConfig;

/// Logger that writes to stderr and, optionally, to the log files.
struct RunLogger {
    run_id: String,
    level: LevelFilter,
    log_dir: Option<PathBuf>,
    lock: Mutex<()>,
}

/// Append one line to a log file (errors are ignored: logging must never crash the program).
/// * `path` - log file.
/// * `line` - formatted line.
fn append(path: &Path, line: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = file.write_all(line.as_bytes());
    }
}

impl Log for RunLogger {
    /// Accept records at or above the configured level.
    /// * `metadata` - level and target of the record.
    fn enabled(&self, metadata: &Metadata) -> bool {
        metadata.level() <= self.level
    }

    /// Format one record and write it to stderr and the log files.
    /// * `record` - the log record.
    fn log(&self, record: &Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let line = format!("{} {:<7} [{}] {} - {}\\n", secs, record.level(), self.run_id, record.target(), record.args());
        let _guard = self.lock.lock();
        eprint!("{}", line);
        if let Some(dir) = &self.log_dir {
            append(&dir.join("app.log"), &line);
            if record.level() <= Level::Warn {
                append(&dir.join("errors.log"), &line);
            }
        }
    }

    /// Nothing is buffered, so there is nothing to flush.
    fn flush(&self) {}
}

/// Turn DEBUG / INFO / WARNING / ERROR into a level filter (unknown names mean INFO).
/// * `name` - level name.
fn parse_level(name: &str) -> LevelFilter {
    match name {
        "DEBUG" => LevelFilter::Debug,
        "WARNING" | "WARN" => LevelFilter::Warn,
        "ERROR" => LevelFilter::Error,
        _ => LevelFilter::Info,
    }
}

/// Configure the `log` facade once per process and start a new run id.
/// * `cfg` - settings providing the level and the data folder.
///
/// Returns the run id written on every line of this run.
pub fn setup_logging(cfg: &AppConfig) -> String {
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.subsec_nanos()).unwrap_or(0);
    let run_id = format!("{:08x}", nanos ^ std::process::id());
    let level = parse_level(&cfg.log_level);
    let log_dir = (cfg.log_to_file && !cfg.data_dir.is_empty()).then(|| PathBuf::from(&cfg.data_dir).join("logs"));
    if let Some(dir) = &log_dir {
        let _ = fs::create_dir_all(dir);
    }
    let logger = RunLogger { run_id: run_id.clone(), level, log_dir, lock: Mutex::new(()) };
    if log::set_boxed_logger(Box::new(logger)).is_ok() {
        log::set_max_level(level);
    }
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |details| {
        log::error!(target: "panic", "{}", details);
        previous(details);
    }));
    info!("run started pid={}", std::process::id());
    run_id
}
"""

RUST_DOMAIN = """//! Domain layer: pure value objects with no I/O.
use log::debug;

/// The result of greeting a user.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Greeting {
    pub message: String,
    pub environment: String,
}

/// Build a greeting.
/// * `name` - user name; blank falls back to "World".
/// * `env` - environment the greeting is produced in.
pub fn build_greeting(name: &str, env: &str) -> Greeting {
    let clean = name.trim();
    let target = if clean.is_empty() { "World" } else { clean };
    debug!("greeting built env={}", env);
    Greeting { message: format!("Hello, {}!", target), environment: env.to_string() }
}
"""

RUST_SERVICES = """//! Services layer: business logic built on config and domain.
use log::info;

use crate::config::AppConfig;
use crate::domain::{build_greeting, Greeting};

/// Greet a user in the configured environment.
/// * `name` - user to greet.
/// * `cfg` - settings providing the environment.
pub fn greet_user(name: &str, cfg: &AppConfig) -> Greeting {
    info!("greeting env={}", cfg.app_env);
    build_greeting(name, &cfg.app_env)
}
"""

# `{crate}` is replaced by the library crate name
RUST_MAIN = """//! Command-line entrypoint: `cargo run -- Alice`.
//! Loads config, starts logging (run id, files in DATA_DIR/logs) and prints the greeting.
use log::info;

use {crate}::config::load_config;
use {crate}::logging::setup_logging;
use {crate}::services::greet_user;

/// Load configuration, start logging and print a greeting.
fn main() {
    let cfg = load_config();
    setup_logging(&cfg);
    let name = std::env::args().nth(1).unwrap_or_else(|| "World".to_string());
    info!("cli start");
    println!("{}", greet_user(&name, &cfg).message);
    info!("cli done exit=0");
}
"""

RUST_LIB = """//! Crate root: declares the layer modules and their tests.
pub mod config;
pub mod domain;
pub mod logging;
pub mod services;

#[cfg(test)]
mod tests {
    use super::config::AppConfig;
    use super::services::greet_user;

    /// A normal name is greeted and the environment is passed through.
    #[test]
    fn test_greet_user() {
        let cfg = AppConfig { app_env: "test".to_string(), ..AppConfig::default() };
        let res = greet_user("Ferris", &cfg);
        assert_eq!(res.message, "Hello, Ferris!");
        assert_eq!(res.environment, "test");
    }
}
"""


def scaffold_rust_pack(target_dir: Path, project_name: str, description: str) -> None:
    """Create the Rust crate starter (`Cargo.toml`, `src/{lib,config,logging,domain,services,main}.rs`).

    Args:
        target_dir: Project root directory.
        project_name: Project name (used for the crate name).
        description: One-line description for `Cargo.toml`.
    """
    logger.debug("scaffold rust_pack in %s", target_dir)
    crate = re.sub(r"[^a-z0-9_-]+", "_", project_name.lower()).strip("_") or "app"
    files = {
        "Cargo.toml": f'[package]\nname = {json.dumps(crate)}\nversion = "0.1.0"\nedition = "2021"\n'
        f"description = {json.dumps(description, ensure_ascii=False)}\n\n[dependencies]\n"
        'log = { version = "0.4", features = ["std"] }\n',
        "src/config.rs": RUST_CONFIG,
        "src/logging.rs": RUST_LOGGING,
        "src/domain.rs": RUST_DOMAIN,
        "src/services.rs": RUST_SERVICES,
        "src/main.rs": RUST_MAIN.replace("{crate}", crate.replace("-", "_")),
        "src/lib.rs": RUST_LIB,
    }
    for rel, content in files.items():
        _write(target_dir / rel, content)
