"""project_template: create, migrate and maintain projects that share one standard structure.

Purpose:
    The template's own code, laid out in the same layers as the projects it creates:
    `entrypoints` (command line, web page, MCP) -> `services` (create, migrate, update,
    collect feedback) -> `packs` (starter files per language) -> `adapters` (local project
    registry) -> `config` (paths and environment). The framework files that every project
    receives live in `.agents/`, `docs/standards/` and `scripts/agentctl.py`, exactly where
    a generated project has them.
"""
