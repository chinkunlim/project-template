# Changelog

All notable changes to **project_template** are documented here
(format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/)).
The template's version is the framework version that projects record in `.agents/framework.lock`.

## [Unreleased]

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
