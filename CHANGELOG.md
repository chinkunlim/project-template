# Changelog

All notable changes to **project_template** are documented here
(format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/)).
The template's version is the framework version that projects record in `.agents/framework.lock`.

## [Unreleased]

### Added
- feat(standards): implement Progressive Disclosure standards modularization into 10 task-focused sub-modules (by `@Antigravity`)
- feat(agents): rewrite AGENTS.md §4 with task-based progressive routing table to prevent token bloat (by `@Antigravity`)
- feat(graphify): add .graphifyignore to template framework files to eliminate 3rd-party noise (by `@Antigravity`)
- feat(frontend): add Step 0 Prerequisite Mockup Gate with audience psychology and Figma thinking (by `@Antigravity`)
- docs(adr): record ADR-005 on supporting global graphify and superpowers methodology (by `@antigravity`)
- feat(skills): add project-auditor skill to audit conversation records, ADRs and known issues completeness before finish (by `@antigravity`)
- feat(closeout): add document completeness and ADR/Known Issues missing guard in session-closeout (--strict-docs) (by `@antigravity`)
- feat(tracker): add fast record extraction options (--cause, --fix, --decision, etc.) in tracker_cli.py (by `@antigravity`)
- feat(doctor): add global symlink integrity diagnostic in doctor.py (by `@antigravity`)
- docs(adr): record ADR-004 on dual-scope global skills symlinks (by `@antigravity`)
- docs(issues): record ISSUE-004 on closeout symlink root detection and ISSUE-005 on secret regex negative lookbehind (by `@antigravity`)
- feat(skills): add project-auditor skill and enhance finish/closeout documentation guards (by `@antigravity`)
- feat(standards): integrate user habits, empirical verification, data mutation guard and closeout habits extraction (by `@Antigravity`)
- feat(standards): modularize standards into task-based sub-modules and bump framework to v3.5.0 (by `@Antigravity`)
- feat(standards): add iron rule 14 for one-click install and seamless lifecycle updates (by `@antigravity`)

### Fixed
- fix(tests): exclude conversations and graphify-out directories from zsh paste safe doc check (by `@antigravity`)
- fix(framework): backport setup_env import hints check and auto_commit missing file staging (by `@antigravity`)

### Documentation
- docs: add superpowers plugin and methodology skills to local AI environment (by `@antigravity`)
- docs: add graphify environment support and gitignore (by `@antigravity`)
- docs(standards): standardize web app and architecture rules for local AI (by `@antigravity`)
- docs(adr/test): update adr/test documentation (ADR-002, ADR-003, ADR-004, ADR-005) (by `@antigravity`)
- docs(standards): eliminate duplicate entry and generalize layout terms (by `@antigravity`)

### Chore
- chore: sync agent adapters and project tree (by `@antigravity`)
- chore(project): update project tooling and config (by `@antigravity`)

## [3.4.0] - 2026-10-22

### Added
- feat(logging): template commands log to DATA_DIR/logs with a run id (by `@claude-code`)
- Module logger required in every program file (ADR-003): code-review-guard reports a CRITICAL
  `[Logging]` finding when a source file in a layer defines functions but creates no module logger
  (Python `logging.getLogger(__name__)`, JS/TS `createLogger(...)`, Go `slog`, Rust `log`).
  Configured with `[quality] require_logger` and `logger_exempt_layers`; on by default in new
  projects, off when the key is missing (existing projects opt in).
  The template turns it on for itself (`config/runtime.py`, `entrypoints/web_routes.py` and
  `entrypoints/openwebui_tool.py` now log too).
- Every stack's starter code logs: Node `src/config/logger.js` (run id, `DATA_DIR/logs/app.log` and
  `errors.log`, `src/entrypoints/cli.js`), Go `internal/config/logging.go` (log/slog, files in
  `DATA_DIR/logs`), Rust `src/logging.rs` + `src/main.rs` (log crate), web `web/logger.js`, GAS
  `src/Log.js`, mobile loggers in every module with `setLogLevel()`; every generated Python module
  (api, db, ollama, evals, alembic) creates a module logger. The adapter and web skeleton generators too.

### Changed
- Session closeout: the agent first updates every Markdown document; `agentctl closeout` lists the project documents this session did not touch, then commits and pushes to the upstream branch (`--no-push` keeps it local).
- Go and Rust starters moved from `packs/other_packs.py` to `packs/go_pack.py` and `packs/rust_pack.py`;
  AGENTS.md rule 12 and CODING_PRINCIPLES §0.4 describe the module logger per language.

## [3.3.0] - 2026-10-21

### Added
- feat(tools): every action tracks registered projects; add existing project and git fetch (by `@claude-code`)
- feat(tools): Open WebUI tool can add existing projects and git fetch (by `@claude-code`)

### Fixed
- fix(migration): quote the Python path in migration --verify (by `@claude-code`)

### Documentation
- docs: ADR-002 tracked projects and ISSUE-001 preview cannot read Desktop (by `@claude-code`)

## [3.2.0] - 2026-10-21
### Changed
- The template uses the layout of the projects it creates (ADR-001): framework files moved to
  `.agents/{bin,hooks,lib,skills}/`, `docs/standards/` and `scripts/agentctl.py`; the template's own code
  moved to `src/project_template/` (entrypoints → services → packs → adapters → config); commands are now
  `python3 scripts/<command>.py`.
- `scripts/update_all.py` runs the template's own updater with `--project`, so v3.1 projects can update.
- The template has its own AGENTS.md, handoff board, ADRs, `pyproject.toml`/`uv.lock`, and passes
  `agentctl check` (comments, layers, ruff, mypy strict).

## [3.1.0] - 2026-10-21
### Added
- Project overview web page with registry, push and one-click actions; JSON API, MCP and Open WebUI tool.
