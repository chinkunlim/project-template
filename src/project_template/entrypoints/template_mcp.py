"""MCP server for the project template, so AI agents can create, migrate and maintain projects.

Purpose:
    Exposes the template's actions (`services/template_service.py`) as MCP tools. Two ways to reach it:
      - stdio: `python3 scripts/template_mcp.py` — Claude Code (`.mcp.json`), Claude Desktop,
        Antigravity (`.agents/mcp_config.json`), OpenCode (`opencode.json`), Cursor, VS Code;
      - Streamable HTTP: `http://127.0.0.1:8766/mcp` while `python3 scripts/web_ui.py` runs
        (Open WebUI → Admin → Integrations → External Tool Servers → MCP (Streamable HTTP)).

    Least privilege: read-only tools answer directly; tools that change something (create, migrate,
    `doctor-fix`, `setup`, update) only describe the commands they would run unless `confirm=True`,
    so an agent must ask the user first.

Dependencies:
    The launcher needs no `.venv`. When `fastapi` / `mcp` are missing, `config.runtime.ensure_dependencies()`
    re-runs it through `uv run --with ...` (a cached environment managed by uv, nothing installed on
    the host). uv's progress goes to stderr, so the stdio channel stays clean.

Usage:
    python3 scripts/template_mcp.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from project_template.config.framework import FRAMEWORK_VERSION
from project_template.services import template_service as ts

WRITE_COMMANDS = {"doctor-fix", "setup"}


def _pending(title: str, steps: list[Any]) -> str:
    """Describe a change that needs the user's approval.

    Args:
        title: What the action does.
        steps: `(argv, cwd)` pairs that would run.

    Returns:
        Text listing the commands, asking for confirmation.
    """
    import shlex

    commands = "\n".join(f"(cd {shlex.quote(str(cwd))} && {shlex.join(argv)})" for argv, cwd in steps)
    return f"Not run yet — {title}. Show the user these commands; call again with confirm=True only after they agree:\n{commands}"


def _run(title: str, steps: list[Any], after: Any = None) -> str:
    """Run a job to the end and summarise it.

    Args:
        title: Job title.
        steps: `(argv, cwd)` pairs.
        after: Optional callback that fills the job result.

    Returns:
        State and the last output lines.
    """
    job = ts.wait_for(ts.RUNNER.start(title, steps, after=after))
    return f"{job.title}: {job.state}\n" + "\n".join(job.log[-30:])


def describe_options() -> dict[str, Any]:
    """List the template's choices: stacks, add-ons (api/db/ollama need python), optional skills, default folder.

    Returns:
        Framework version, projects folder and the option lists.
    """
    return ts.info()


def list_projects(folder: str = "") -> list[dict[str, Any]]:
    """List projects created from the template with version, uncommitted files and last commit.

    Args:
        folder: Absolute folder to scan; empty = the folder that contains the template.

    Returns:
        One entry per project.
    """
    return ts.list_projects(ts.resolve_root(folder))


def project_overview(folder: str = "") -> list[dict[str, Any]]:
    """Track every project made with the template: framework version, uncommitted files, commits not yet pushed
    to GitHub, open template suggestions, whether AI tools (MCP) are configured. Read only.

    Args:
        folder: Folder to scan; empty = the folder that contains the template (registered projects are added).

    Returns:
        One status per project.
    """
    return ts.overview(ts.resolve_root(folder))


def push_project(project: str, folder: str = "", confirm: bool = False) -> str:
    """Push a project's local commits to its GitHub upstream (never force).

    Args:
        project: Project name (from project_overview) or absolute path.
        folder: Folder to look the name up in; empty = default projects folder.
        confirm: Must be True: show the user the unpushed commits first and push only after they agree.

    Returns:
        The command (without confirm) or the push output.
    """
    path = project if project.startswith("/") else next(
        (p["path"] for p in ts.overview(ts.resolve_root(folder)) if p["name"] == project and p.get("exists")), "")
    title, steps = ts.push_steps({"path": path})
    return _run(title, steps) if confirm else _pending(title, steps)


def preview_data_folder(name: str, folder: str = "", data_dir: str = "") -> dict[str, Any]:
    """Show where a new project's data folder (DATA_DIR) will be and how it is stored.

    Args:
        name: Project name.
        folder: Absolute folder for the project; empty = default projects folder.
        data_dir: Absolute data folder; empty = projects-data/<name> next to the projects folder.

    Returns:
        Absolute path, stored value and where it is written.
    """
    return ts.data_preview({"name": name, "parent": folder or str(ts.projects_root()), "data_dir": data_dir})


def create_project(name: str, stack: str = "python", addons: list[str] | None = None, folder: str = "",
                   data_dir: str = "", description: str = "", skills: list[str] | None = None,
                   install: bool = False, confirm: bool = False) -> str:
    """Create a new project (folders, docs, agent rules, git with a first commit), then repair its environment.

    Args:
        name: Project and folder name.
        stack: python, node, gas, go, rust, generic, both, all or mobile.
        addons: Add-ons such as web, gas, mobile, api, db, ollama, evals (a web page means api).
        folder: Absolute folder to create it in; empty = default projects folder.
        data_dir: Absolute data folder; empty = projects-data/<name>.
        description: One-line description.
        skills: Optional extra skills, e.g. legacy-migration.
        install: Also install dependencies inside the project (needs internet).
        confirm: Must be True to actually create it (after the user agreed).

    Returns:
        The commands (without confirm) or the job result.
    """
    body = {"name": name, "parent": folder or str(ts.projects_root()), "data_dir": data_dir, "stack": stack,
            "addons": addons or [], "skills": skills or [], "description": description, "doctor": True,
            "setup": install, "check": True}
    title, steps = ts.create_steps(body)
    return _run(title, steps) if confirm else _pending(title, steps)


def migrate_project(source: str, name: str = "", folder: str = "", mode: str = "maintain", data_dir: str = "",
                    confirm: bool = False) -> str:
    """Move an old project into a new folder that follows the template (the old project is never changed).

    Args:
        source: Absolute folder of the old project (it must be committed).
        name: New project name; empty = the old folder name.
        folder: Absolute folder for the new project; empty = default projects folder.
        mode: maintain (finished project, keep Flask) or develop (continue, rewrite Flask as FastAPI).
        data_dir: Absolute data folder; empty = projects-data/<name>.
        confirm: Must be True to actually migrate (after the user agreed).

    Returns:
        The commands (without confirm) or the job result.
    """
    body = {"source": source, "name": name or Path(source.rstrip("/")).name, "mode": mode, "data_dir": data_dir,
            "parent": folder or str(ts.projects_root())}
    title, steps = ts.migrate_steps(body)
    return _run(title, steps) if confirm else _pending(title, steps)


def run_project_command(project: str, command: str = "status", folder: str = "", confirm: bool = False) -> str:
    """Run a framework command inside one project.

    Args:
        project: Project name (from list_projects) or absolute path.
        command: status, doctor, check (read only) or doctor-fix, setup (change files: need confirm).
        folder: Folder to look the name up in; empty = default projects folder.
        confirm: Must be True for doctor-fix and setup.

    Returns:
        The command output.
    """
    path = project if project.startswith("/") else next(
        (p["path"] for p in ts.list_projects(ts.resolve_root(folder)) if p["name"] == project), "")
    title, steps = ts.project_command_steps({"path": path, "command": command})
    if command in WRITE_COMMANDS and not confirm:
        return _pending(title, steps)
    return _run(title, steps)


def collect_feedback(include_decided: bool = False, folder: str = "") -> dict[str, Any]:
    """List template-improvement suggestions from every project's docs/TEMPLATE_FEEDBACK.md (read only).

    Args:
        include_decided: Also list adopted / rejected suggestions.
        folder: Folder to scan; empty = default projects folder.

    Returns:
        Number of projects scanned and the suggestions.
    """
    return ts.feedback(ts.resolve_root(folder), include_decided)


def preview_framework_update(folder: str = "") -> list[dict[str, Any]]:
    """Preview the framework update of every project (nothing changes).

    Args:
        folder: Folder to scan; empty = default projects folder.

    Returns:
        Per project: versions, files to update / add, conflicts, removed files and status.
    """
    return ts.update_preview(ts.resolve_root(folder))


def apply_framework_update(folder: str = "", commit: bool = True, confirm: bool = False) -> str:
    """Update every updatable project (project edits are kept as *.template, dirty projects are skipped).

    Args:
        folder: Folder to scan; empty = default projects folder.
        commit: Commit each cleanly updated project locally (never pushes).
        confirm: Must be True to apply (after the user agreed to the preview).

    Returns:
        The commands (without confirm) or the job result.
    """
    title, steps = ts.update_apply_steps(ts.resolve_root(folder), commit)
    return _run(title, steps) if confirm else _pending(title, steps)


def get_job_status() -> dict[str, Any] | None:
    """Show the current or last job started from the web page or the API.

    Returns:
        Title, state and recent output, or None when nothing has run.
    """
    return ts.job_view(ts.RUNNER.current)


# Every tool the server offers (the function name is the MCP tool name).
TOOLS = (
    describe_options,
    list_projects,
    project_overview,
    push_project,
    preview_data_folder,
    create_project,
    migrate_project,
    run_project_command,
    collect_feedback,
    preview_framework_update,
    apply_framework_update,
    get_job_status,
)


def build_template_mcp() -> Any:
    """Create the MCP server with the template's tools.

    Returns:
        An `MCPServer` (run it over stdio, or mount its HTTP routes into the web app).
    """
    from mcp.server import MCPServer

    server = MCPServer(
        "project-template",
        instructions=("Create, migrate and maintain projects with the user's project template. Read-only tools can be "
                      "called freely. Tools with `confirm` change files: call them first without confirm, show the "
                      "user what will run, and call again with confirm=True only after the user agrees."),
        version=FRAMEWORK_VERSION,
    )
    for tool in TOOLS:
        server.tool()(tool)
    return server


def main() -> None:
    """Run the template MCP server over stdio (dependencies are ensured by the launcher)."""
    build_template_mcp().run("stdio")
