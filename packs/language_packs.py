#!/usr/bin/env python3
"""Starter-file generation entry point used by `init_project.py`.

Purpose:
    Dispatches a base stack plus add-ons to the individual packs and re-exports the
    config builders, so callers only import from this module.

Packs:
    python_pack.py : Python 3.11 via uv (src/<pkg>/..., tests/, CLI, logging, ruff)
    web_pack.py    : `web/` plain HTML + CSS + JS (add-on)
    gas_pack.py    : Google Apps Script with Node tests and project-local clasp (stack or `gas/` add-on)
    mobile_pack.py : Expo (React Native + TypeScript) app for Android and iOS (`mobile/` add-on)
    other_packs.py : Node.js, Go, Rust, generic
    stack_config.py: stacks/add-ons -> project.toml, .gitignore, .env.example, CI workflow
"""

from __future__ import annotations

import re
from pathlib import Path

from packs.common import detect_node_toolchain, slugify_package_name, write_file
from packs.dx_pack import scaffold_dx_files
from packs.gas_pack import scaffold_gas_pack
from packs.mobile_pack import scaffold_mobile_pack
from packs.other_packs import scaffold_generic_pack, scaffold_go_pack, scaffold_node_pack, scaffold_rust_pack
from packs.python_pack import scaffold_python_pack
from packs.stack_config import (  # noqa: F401 - re-exported for init_project.py
    ADDON_CHOICES,
    STACK_CHOICES,
    build_ci_workflow,
    build_env_example,
    build_gitignore,
    build_project_toml,
    project_settings,
    resolve_languages,
    resolve_stack,
)
from packs.evals_pack import scaffold_evals_pack
from packs.web_pack import scaffold_web_pack


def generate_stack_files(target_dir: Path, project_name: str, settings: dict, options: dict[str, str]) -> None:
    """Generate the starter files for the base stack and every add-on.

    Args:
        target_dir: Project root directory.
        project_name: Project name.
        settings: Output of `project_settings()` (uses `base` and `addons`).
        options: Extra values: `description`, `timezone` (IANA name for GAS), `license`
            (`MIT` / `none`), and optional `node` / `pnpm` versions (detected when omitted).
    """
    base, description = settings["base"], options.get("description", "")
    uses_node = base in ("node", "gas") or bool({"gas", "mobile"} & set(settings["addons"]))
    toolchain = {**detect_node_toolchain(), **{k: v for k, v in options.items() if k in ("node", "pnpm") and v}} if uses_node else {}
    gas_options = {"timezone": options.get("timezone", "UTC"), "pnpm": toolchain.get("pnpm", "")}
    if uses_node:
        write_file(target_dir / ".nvmrc", toolchain["node"] + "\n")
    if base == "python":
        scaffold_python_pack(target_dir, project_name, description, settings["addons"])
    elif base == "node":
        scaffold_node_pack(target_dir, project_name, description, toolchain.get("pnpm", ""))
    elif base == "gas":
        scaffold_gas_pack(target_dir, project_name, description, gas_options)
    elif base == "go":
        scaffold_go_pack(target_dir, project_name)
    elif base == "rust":
        scaffold_rust_pack(target_dir, project_name, description)
    elif "mobile" in settings["addons"]:
        write_file(target_dir / "VERSION", "0.1.0\n")  # app-only project: the code lives in mobile/
    else:
        scaffold_generic_pack(target_dir, project_name)
    if "web" in settings["addons"]:
        scaffold_web_pack(target_dir, project_name)
    if "gas" in settings["addons"]:
        scaffold_gas_pack(target_dir / "gas", project_name, description, gas_options)
    if "mobile" in settings["addons"]:
        scaffold_mobile_pack(target_dir, project_name, toolchain.get("pnpm", ""))
    if "evals" in settings["addons"]:
        scaffold_evals_pack(target_dir)
    dist = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"
    names = {"pkg": slugify_package_name(project_name), "dist": dist, "license": options.get("license", "none")}
    scaffold_dx_files(target_dir, settings["languages"], names)
