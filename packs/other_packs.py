#!/usr/bin/env python3
"""Starter packs for Node.js, Go, Rust and language-agnostic (generic) projects.

Purpose:
    Small, fully commented starters that follow the layer rules
    (config -> domain -> services) and the comment rules, used by `init_project.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from packs.common import write_package_json, package_json, write_file as _write


# ---------------------------------------------------------------------------
# Node.js
# ---------------------------------------------------------------------------

NODE_FILES = {
    "src/config/index.js": '''/**
 * @file Configuration layer: the ONLY module allowed to read process.env.
 */

/**
 * Read application settings from environment variables.
 * @param {Record<string, string|undefined>} [env=process.env] Environment variables to read.
 * @returns {{appEnv: string, logLevel: string}} Frozen settings object.
 */
export function loadConfig(env = process.env) {
  return Object.freeze({
    appEnv: (env.APP_ENV || "development").trim(),
    logLevel: (env.LOG_LEVEL || "INFO").trim(),
  });
}
''',
    "src/domain/greeting.js": '''/**
 * @file Domain layer: pure value objects with no I/O.
 */

/**
 * Create an immutable greeting value object.
 * @param {string} userName Name typed by the user; blank falls back to "World".
 * @param {string} environment Environment the greeting is produced in.
 * @returns {{message: string, environment: string}} Frozen greeting.
 */
export function makeGreeting(userName, environment) {
  const clean = String(userName || "").trim() || "World";
  return Object.freeze({ message: `Hello, ${clean}!`, environment });
}
''',
    "src/services/greetingService.js": '''/**
 * @file Services layer: business logic using config values and domain objects.
 */
import { makeGreeting } from "../domain/greeting.js";

/**
 * Greet a user in the configured environment.
 * @param {string} userName Name of the user to greet.
 * @param {{appEnv: string}} config Settings from loadConfig().
 * @returns {{message: string, environment: string}} The greeting.
 */
export function greetUser(userName, config) {
  return makeGreeting(userName, config.appEnv);
}
''',
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
    slug = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"
    write_package_json(target_dir, package_json(slug, description, {}, {"module_type": "module", "pnpm": pnpm}))
    for rel, content in NODE_FILES.items():
        _write(target_dir / rel, content)


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


def scaffold_go_pack(target_dir: Path, project_name: str) -> None:
    """Create the Go starter (`go.mod`, `internal/{config,domain,services}`, `cmd/app`).

    Args:
        target_dir: Project root directory.
        project_name: Project name (used for the module path).
    """
    mod = "example.com/" + (re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app")
    files = {
        "VERSION": "0.1.0\n",
        "go.mod": f"module {mod}\n\ngo 1.21\n",
        "internal/config/config.go": '''// Package config is the only package allowed to read environment variables.
package config

import "os"

// AppConfig holds immutable application settings.
type AppConfig struct {
	AppEnv string // deployment environment, e.g. "development"
}

// LoadConfig reads settings from environment variables.
// Returns an AppConfig with defaults for missing values.
func LoadConfig() AppConfig {
	env := os.Getenv("APP_ENV")
	if env == "" {
		env = "development"
	}
	return AppConfig{AppEnv: env}
}
''',
        "internal/domain/greeting.go": '''// Package domain contains pure value objects with no I/O.
package domain

import "strings"

// Greeting is the result of greeting a user.
type Greeting struct {
	Message     string
	Environment string
}

// NewGreeting builds a greeting.
// Parameters: name is the user name (blank falls back to "World"); env is the environment name.
func NewGreeting(name string, env string) Greeting {
	clean := strings.TrimSpace(name)
	if clean == "" {
		clean = "World"
	}
	return Greeting{Message: "Hello, " + clean + "!", Environment: env}
}
''',
        "internal/services/greeter.go": f'''// Package services holds business logic built on config and domain.
package services

import (
	"{mod}/internal/config"
	"{mod}/internal/domain"
)

// Greet greets a user in the configured environment.
// Parameters: name is the user to greet; cfg provides the environment.
func Greet(name string, cfg config.AppConfig) domain.Greeting {{
	return domain.NewGreeting(name, cfg.AppEnv)
}}
''',
        "internal/services/greeter_test.go": f'''package services

import (
	"testing"

	"{mod}/internal/config"
)

// TestGreet checks the greeting text for a normal name.
func TestGreet(t *testing.T) {{
	res := Greet("Gopher", config.AppConfig{{AppEnv: "test"}})
	if res.Message != "Hello, Gopher!" {{
		t.Fatalf("unexpected message: %s", res.Message)
	}}
}}
''',
        "cmd/app/main.go": f'''// Command app is the CLI entrypoint.
package main

import (
	"fmt"

	"{mod}/internal/config"
	"{mod}/internal/services"
)

// main loads configuration and prints a greeting.
func main() {{
	res := services.Greet("World", config.LoadConfig())
	fmt.Println(res.Message)
}}
''',
    }
    for rel, content in files.items():
        _write(target_dir / rel, content)


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def scaffold_rust_pack(target_dir: Path, project_name: str, description: str) -> None:
    """Create the Rust crate starter (`Cargo.toml`, `src/{lib,config,domain,services}.rs`).

    Args:
        target_dir: Project root directory.
        project_name: Project name (used for the crate name).
        description: One-line description for `Cargo.toml`.
    """
    crate = re.sub(r"[^a-z0-9_-]+", "_", project_name.lower()).strip("_") or "app"
    files = {
        "Cargo.toml": f'[package]\nname = {json.dumps(crate)}\nversion = "0.1.0"\nedition = "2021"\n'
        f"description = {json.dumps(description, ensure_ascii=False)}\n\n[dependencies]\n",
        "src/config.rs": '''//! Configuration layer: the only module allowed to read environment variables.
use std::env;

/// Immutable application settings.
#[derive(Debug, Clone)]
pub struct AppConfig {
    /// Deployment environment, e.g. "development".
    pub app_env: String,
}

/// Read settings from environment variables, using defaults for missing values.
pub fn load_config() -> AppConfig {
    let app_env = env::var("APP_ENV").unwrap_or_else(|_| "development".to_string());
    AppConfig { app_env }
}
''',
        "src/domain.rs": '''//! Domain layer: pure value objects with no I/O.

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
    Greeting { message: format!("Hello, {}!", target), environment: env.to_string() }
}
''',
        "src/services.rs": '''//! Services layer: business logic built on config and domain.
use crate::config::AppConfig;
use crate::domain::{build_greeting, Greeting};

/// Greet a user in the configured environment.
/// * `name` - user to greet.
/// * `cfg` - settings providing the environment.
pub fn greet_user(name: &str, cfg: &AppConfig) -> Greeting {
    build_greeting(name, &cfg.app_env)
}
''',
        "src/lib.rs": '''//! Crate root: declares the layer modules and their tests.
pub mod config;
pub mod domain;
pub mod services;

#[cfg(test)]
mod tests {
    use super::config::AppConfig;
    use super::services::greet_user;

    /// A normal name is greeted and the environment is passed through.
    #[test]
    fn test_greet_user() {
        let cfg = AppConfig { app_env: "test".to_string() };
        let res = greet_user("Ferris", &cfg);
        assert_eq!(res.message, "Hello, Ferris!");
        assert_eq!(res.environment, "test");
    }
}
''',
    }
    for rel, content in files.items():
        _write(target_dir / rel, content)


def scaffold_generic_pack(target_dir: Path, project_name: str) -> None:
    """Create a language-agnostic starter with `VERSION` and layered `src/<layer>/LAYER.md` placeholders.

    Args:
        target_dir: Project root directory.
        project_name: Project name for the placeholder READMEs.
    """
    _write(target_dir / "VERSION", "0.1.0\n")
    for layer in ("config", "domain", "services", "adapters"):
        _write(
            target_dir / "src" / layer / "LAYER.md",
            f"# `{layer}` layer ({project_name})\n\nPut `{layer}` modules here, or change `[architecture]` in `.agents/project.toml`.\n",
        )
