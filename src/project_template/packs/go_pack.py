#!/usr/bin/env python3
"""Go starter pack: layered `internal/` packages, `cmd/app` and `log/slog` logging.

Purpose:
    Small, fully commented starter that follows the layer rules (config -> domain -> services)
    and the comment rules; every package logs through `log/slog` set up by `config.SetupLogging`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from project_template.packs.common import write_file as _write

logger = logging.getLogger(__name__)

# Go starter files: `str.format(mod=<module path>)` templates (`{{` / `}}` are literal braces).
GO_CONFIG = '''// Package config is the only package allowed to read environment variables.
package config

import (
	"log/slog"
	"os"
	"strings"
)

// AppConfig holds immutable application settings.
type AppConfig struct {{
	AppEnv    string // deployment environment, e.g. "development"
	LogLevel  string // DEBUG, INFO, WARNING or ERROR
	LogToFile bool   // also write <DataDir>/logs/app.log and errors.log
	DataDir   string // data folder outside the project (empty: console only)
}}

// logger returns this package's logger (created on use so it picks up SetupLogging's handler).
func logger() *slog.Logger {{
	return slog.Default().With("module", "config")
}}

// getenv reads one variable with a default.
// Parameters: key is the variable name; fallback is used when it is empty.
func getenv(key string, fallback string) string {{
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {{
		return value
	}}
	return fallback
}}

// isOn interprets an environment flag.
// Parameters: value is the raw text; 1 / true / yes / on (any case) mean true.
func isOn(value string) bool {{
	switch strings.ToLower(value) {{
	case "1", "true", "yes", "on":
		return true
	}}
	return false
}}

// LoadConfig reads settings from environment variables.
// Returns an AppConfig with defaults for missing values.
func LoadConfig() AppConfig {{
	cfg := AppConfig{{
		AppEnv:    getenv("APP_ENV", "development"),
		LogLevel:  strings.ToUpper(getenv("LOG_LEVEL", "INFO")),
		LogToFile: isOn(getenv("LOG_TO_FILE", "true")),
		DataDir:   getenv("DATA_DIR", ""),
	}}
	logger().Debug("config loaded", "env", cfg.AppEnv, "data_dir", cfg.DataDir)
	return cfg
}}
'''

GO_LOGGING = '''// Package config: logging setup shared by every package, built for tracing one run.
//
// Every record carries a run id (`run_id=3f9a1c2e`). Console output goes to stderr; with
// LogToFile the same lines are appended to <DataDir>/logs/app.log and WARN and above to
// errors.log (outside the project). Each package creates its logger with
// `func logger() *slog.Logger {{ return slog.Default().With("module", "<name>") }}`.
package config

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"io"
	"log/slog"
	"os"
	"path/filepath"
)

// fanout sends every record to several handlers (console + app.log + errors.log).
type fanout []slog.Handler

// Enabled reports whether any handler wants the level.
// Parameters: ctx is the logging context; level is the record level.
func (f fanout) Enabled(ctx context.Context, level slog.Level) bool {{
	for _, h := range f {{
		if h.Enabled(ctx, level) {{
			return true
		}}
	}}
	return false
}}

// Handle passes the record to every handler that accepts its level.
// Parameters: ctx is the logging context; record is the log record.
func (f fanout) Handle(ctx context.Context, record slog.Record) error {{
	for _, h := range f {{
		if h.Enabled(ctx, record.Level) {{
			_ = h.Handle(ctx, record.Clone())
		}}
	}}
	return nil
}}

// WithAttrs adds attributes to every handler.
// Parameters: attrs are the attributes to add.
func (f fanout) WithAttrs(attrs []slog.Attr) slog.Handler {{
	out := make(fanout, len(f))
	for i, h := range f {{
		out[i] = h.WithAttrs(attrs)
	}}
	return out
}}

// WithGroup opens a group on every handler.
// Parameters: name is the group name.
func (f fanout) WithGroup(name string) slog.Handler {{
	out := make(fanout, len(f))
	for i, h := range f {{
		out[i] = h.WithGroup(name)
	}}
	return out
}}

// parseLevel turns DEBUG / INFO / WARNING / ERROR into a slog level.
// Parameters: name is the level name; unknown names fall back to INFO.
func parseLevel(name string) slog.Level {{
	switch name {{
	case "DEBUG":
		return slog.LevelDebug
	case "WARNING", "WARN":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	}}
	return slog.LevelInfo
}}

// SetupLogging configures the default slog logger once per process and starts a new run id.
// Parameters: cfg provides LogLevel, LogToFile and DataDir.
// Returns the run id and a function that closes the log files.
func SetupLogging(cfg AppConfig) (string, func()) {{
	buf := make([]byte, 4)
	_, _ = rand.Read(buf)
	runID := hex.EncodeToString(buf)
	level := parseLevel(cfg.LogLevel)
	handlers := fanout{{slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{{Level: level}})}}
	var files []io.Closer
	if cfg.LogToFile && cfg.DataDir != "" {{
		dir := filepath.Join(cfg.DataDir, "logs")
		if err := os.MkdirAll(dir, 0o755); err == nil {{
			for name, minLevel := range map[string]slog.Level{{"app.log": level, "errors.log": slog.LevelWarn}} {{
				if f, err := os.OpenFile(filepath.Join(dir, name), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); err == nil {{
					files = append(files, f)
					handlers = append(handlers, slog.NewTextHandler(f, &slog.HandlerOptions{{Level: minLevel}}))
				}}
			}}
		}}
	}}
	slog.SetDefault(slog.New(handlers).With("run_id", runID))
	slog.Info("run started", "pid", os.Getpid(), "log_files", len(files))
	return runID, func() {{
		for _, f := range files {{
			_ = f.Close()
		}}
	}}
}}
'''

GO_DOMAIN = '''// Package domain contains pure value objects with no I/O.
package domain

import (
	"log/slog"
	"strings"
)

// Greeting is the result of greeting a user.
type Greeting struct {{
	Message     string
	Environment string
}}

// logger returns this package's logger (created on use so it picks up SetupLogging's handler).
func logger() *slog.Logger {{
	return slog.Default().With("module", "domain")
}}

// NewGreeting builds a greeting.
// Parameters: name is the user name (blank falls back to "World"); env is the environment name.
func NewGreeting(name string, env string) Greeting {{
	clean := strings.TrimSpace(name)
	if clean == "" {{
		clean = "World"
	}}
	logger().Debug("greeting built", "env", env)
	return Greeting{{Message: "Hello, " + clean + "!", Environment: env}}
}}
'''

GO_SERVICES = '''// Package services holds business logic built on config and domain.
package services

import (
	"log/slog"

	"{mod}/internal/config"
	"{mod}/internal/domain"
)

// logger returns this package's logger (created on use so it picks up SetupLogging's handler).
func logger() *slog.Logger {{
	return slog.Default().With("module", "services")
}}

// Greet greets a user in the configured environment.
// Parameters: name is the user to greet; cfg provides the environment.
func Greet(name string, cfg config.AppConfig) domain.Greeting {{
	logger().Info("greeting", "env", cfg.AppEnv)
	return domain.NewGreeting(name, cfg.AppEnv)
}}
'''

GO_SERVICES_TEST = '''package services

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
'''

GO_MAIN = '''// Command app is the CLI entrypoint.
package main

import (
	"fmt"
	"log/slog"
	"os"

	"{mod}/internal/config"
	"{mod}/internal/services"
)

// logger returns this package's logger (created on use so it picks up SetupLogging's handler).
func logger() *slog.Logger {{
	return slog.Default().With("module", "main")
}}

// main loads configuration, starts logging and prints a greeting.
func main() {{
	cfg := config.LoadConfig()
	_, closeLogs := config.SetupLogging(cfg)
	defer closeLogs()
	name := "World"
	if len(os.Args) > 1 {{
		name = os.Args[1]
	}}
	logger().Info("cli start")
	fmt.Println(services.Greet(name, cfg).Message)
	logger().Info("cli done", "exit", 0)
}}
'''


def scaffold_go_pack(target_dir: Path, project_name: str) -> None:
    """Create the Go starter (`go.mod`, `internal/{config,domain,services}`, `cmd/app`).

    Args:
        target_dir: Project root directory.
        project_name: Project name (used for the module path).
    """
    logger.debug("scaffold go_pack in %s", target_dir)
    mod = "example.com/" + (re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app")
    files = {
        "VERSION": "0.1.0\n",
        "go.mod": f"module {mod}\n\ngo 1.21\n",
        "internal/config/config.go": GO_CONFIG,
        "internal/config/logging.go": GO_LOGGING,
        "internal/domain/greeting.go": GO_DOMAIN,
        "internal/services/greeter.go": GO_SERVICES,
        "internal/services/greeter_test.go": GO_SERVICES_TEST,
        "cmd/app/main.go": GO_MAIN,
    }
    for rel, template in files.items():
        _write(target_dir / rel, template.format(mod=mod))
