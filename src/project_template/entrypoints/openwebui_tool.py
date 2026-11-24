"""
title: 專案母版（Project template）
author: limchinkun
version: 0.3.0
description: Create projects, migrate old projects, add existing projects, list projects, manage web
  servers, refresh Graphify graphs, inspect/edit feedback, and preview/apply framework updates through
  the template's local web app (python3 scripts/web_ui.py). Paste into Open WebUI -> Workspace -> Tools.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CreateOptions(BaseModel):
    """Optional fields for creating a project from Open WebUI."""

    stack: str = Field(default="python", description="python, node, gas, go, rust, generic, both, all, mobile")
    addons: str = Field(default="", description="Comma-separated add-ons: web, gas, mobile, api, db, ollama, evals")
    folder: str = Field(default="", description="Absolute folder; empty = default projects folder")
    data_dir: str = Field(default="", description="Absolute DATA_DIR; empty = projects-data/<name>")
    description: str = Field(default="", description="One-line project description")
    install: bool = Field(default=False, description="Also run setup --install (needs internet)")


class MigrateOptions(BaseModel):
    """Optional fields for migrating an old project from Open WebUI."""

    name: str = Field(default="", description="New project name; empty = old folder name")
    folder: str = Field(default="", description="Absolute folder for new project; empty = default")
    mode: str = Field(default="maintain", description="maintain (keep Flask) or develop (rewrite as FastAPI)")


class Tools:
    """Tools the model can call."""

    class Valves(BaseModel):
        """Settings shown in Open WebUI."""

        base_url: str = Field(
            default="http://127.0.0.1:8766",
            description="Address of the template web app (Open WebUI in Docker: http://host.docker.internal:8766)",
        )
        projects_folder: str = Field(
            default="",
            description="Folder that holds the projects; empty = the folder that contains the template",
        )

    def __init__(self) -> None:
        """Create the tools with default settings."""
        self.valves = self.Valves()

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """Call the web app's API.

        Args:
            method: HTTP method.
            path: API path such as /api/projects.
            body: JSON body for POST requests.

        Returns:
            Decoded JSON, or an error message.
        """
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.valves.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        logger.info("template app call %s %s", method, path)
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            logger.warning("template app %s %s -> HTTP %s", method, path, exc.code)
            return f"Error {exc.code}: {str(detail)[:300]}"
        except OSError as exc:
            logger.warning("template app unreachable at %s: %s", self.valves.base_url, exc)
            return f"Cannot reach the template app at {self.valves.base_url} ({exc}). Is `python3 scripts/web_ui.py` running?"

    def _root_query(self) -> str:
        """Build the `root=` query for the configured projects folder.

        Returns:
            Query string (may be empty).
        """
        return f"root={urllib.parse.quote(self.valves.projects_folder)}" if self.valves.projects_folder else ""

    def _wait(self, seconds: int = 90) -> dict[str, Any] | str:
        """Wait for the current job to finish.

        Args:
            seconds: Longest time to wait.

        Returns:
            The finished (or still running) job, or an error message.
        """
        job: dict[str, Any] | str = {}
        for _ in range(seconds):
            job = self._call("GET", "/api/job")
            if isinstance(job, str) or not job or job.get("state") != "running":
                return job
            time.sleep(1)
        return job

    def list_projects(self) -> str:
        """
        List the tracked projects: name, framework version, uncommitted files and last commit.
        :return: One line per project.
        """
        rows = self._call("GET", "/api/projects?" + self._root_query())
        if isinstance(rows, str):
            return rows
        lines = [
            f"- {r['name']} (v{r['version']}, {'clean' if not r['dirty'] else str(r['dirty']) + ' uncommitted'}) "
            f"— {r['last_commit']} — {r['path']}"
            for r in rows
        ]
        return "\n".join(lines) or "No projects found."

    def create_project(self, name: str, options: CreateOptions | None = None, confirm: bool = False) -> str:
        """
        Create a new project from the template (folders, docs, agent rules, git first commit). Runs in background.
        :param name: Project and folder name (letters, digits, Chinese, space, - _ .).
        :param options: Optional stack, comma-separated addons, folder, data_dir, description, install flag.
        :param confirm: Must be True; first ask the user and call with confirm=True after they agree.
        :return: Whether the job started, with the commands it runs.
        """
        opts = options or CreateOptions()
        if not confirm:
            return (
                f"Not created yet. Tell the user: project '{name}' (stack {opts.stack}, add-ons {opts.addons or 'none'}) "
                "will be created with git, docs and agent rules. Call again with confirm=True after they agree."
            )
        info = self._call("GET", "/api/info")
        if isinstance(info, str):
            return info
        body = {
            "name": name, "parent": opts.folder or self.valves.projects_folder or info["projects_root"],
            "data_dir": opts.data_dir, "stack": opts.stack,
            "addons": [a.strip() for a in opts.addons.split(",") if a.strip()],
            "description": opts.description, "doctor": True, "setup": opts.install, "check": True, "confirm": True,
        }
        result = self._call("POST", "/api/create", body)
        if isinstance(result, str):
            return result
        return f"Started: {result['title']}.\nCommands:\n" + "\n".join(result["commands"]) + "\nAsk for job status to follow."

    def migrate_project(self, source: str, options: MigrateOptions | None = None, confirm: bool = False) -> str:
        """
        Migrate an old project into a new folder that follows the template (the old project is untouched).
        :param source: Absolute folder of the old project (it must be committed).
        :param options: Optional name, target folder, and mode (maintain or develop).
        :param confirm: Must be True; first tell the user what will happen and call with confirm=True after approval.
        :return: Whether the job started.
        """
        opts = options or MigrateOptions()
        if not confirm:
            return (
                f"Not migrated yet. Tell the user {source} will be copied into a new project "
                "(the old one is not changed); call again with confirm=True after they agree."
            )
        info = self._call("GET", "/api/info")
        if isinstance(info, str):
            return info
        body = {
            "source": source, "name": opts.name or source.rstrip("/").split("/")[-1],
            "parent": opts.folder or self.valves.projects_folder or info["projects_root"],
            "mode": opts.mode, "confirm": True,
        }
        result = self._call("POST", "/api/migrate", body)
        return result if isinstance(result, str) else f"Started: {result['title']}. Ask for the job status to follow it."

    def register_project(self, path: str, confirm: bool = False) -> str:
        """
        Add an existing template project folder outside the workspace to the project registry.
        :param path: Absolute project folder.
        :param confirm: Must be True; first tell the user which folder will be added and call again after approval.
        :return: Whether it was added.
        """
        result = self._call("POST", "/api/registry/add", {"path": path, "confirm": confirm})
        if isinstance(result, str):
            if result.startswith("Error 428"):
                return f"Not added yet. Tell the user {path} will be added to the project registry; call again with confirm=True."
            return result
        return f"Added {result['path']}." if result["added"] else f"{result['path']} was already registered."

    def refresh_remote_status(self, project: str = "") -> str:
        """
        Run git fetch in one project or every tracked project with a git remote.
        :param project: Absolute project folder; empty = every tracked project.
        :return: The job output.
        """
        body = {"path": project, **({"root": self.valves.projects_folder} if self.valves.projects_folder else {})}
        started = self._call("POST", "/api/fetch", body)
        if isinstance(started, str):
            return started
        self._wait(120)
        return self.get_job_status()

    def get_job_status(self) -> str:
        """
        Get the state and the last output lines of the current or last job.
        :return: Title, state and recent output.
        """
        job = self._call("GET", "/api/job")
        if isinstance(job, str):
            return job
        if not job:
            return "No job has run yet."
        return f"{job['title']}: {job['state']}\n" + "\n".join(job["log"][-25:])

    def run_project_command(self, project: str, command: str = "doctor") -> str:
        """
        Run a framework command in one project and return its output.
        :param project: Project name (from list_projects) or absolute path.
        :param command: status, scan, graph, doctor, check (read only) or doctor-fix, setup, sync (write).
        :return: The command output.
        """
        if command in ("doctor-fix", "setup", "sync"):
            return f"`{command}` changes files; ask the user and run it from the template web page (or MCP with confirm)."
        path = project
        if not project.startswith("/"):
            rows = self._call("GET", "/api/projects?" + self._root_query())
            if isinstance(rows, str):
                return rows
            match = [r["path"] for r in rows if r["name"] == project]
            if not match:
                return f"No project named {project}. Known: {', '.join(r['name'] for r in rows)}"
            path = match[0]
        result = self._call("POST", "/api/project-command", {"path": path, "command": command})
        if isinstance(result, str):
            return result
        return self.get_job_status() if not isinstance(self._wait(), str) else "The command is still running."

    def collect_feedback(self, include_decided: bool = False) -> str:
        """
        List the template-improvement suggestions recorded in every project's docs/TEMPLATE_FEEDBACK.md.
        :param include_decided: Also list suggestions already adopted or rejected.
        :return: One line per suggestion.
        """
        query = "&".join(q for q in (self._root_query(), "all=1" if include_decided else "") if q)
        data = self._call("GET", "/api/feedback?" + query)
        if isinstance(data, str):
            return data
        lines = [f"- {i['date']} [{i['project']}] {i['text']} ({i['status']})" for i in data["items"]]
        return f"Scanned {data['scanned']} projects.\n" + ("\n".join(lines) or "No open suggestions.")

    def preview_framework_update(self) -> str:
        """
        Preview the framework update for every project (nothing changes): versions, files to update or add, conflicts.
        :return: One line per project.
        """
        body = {"root": self.valves.projects_folder} if self.valves.projects_folder else {}
        started = self._call("POST", "/api/update/preview", body)
        if isinstance(started, str):
            return started
        job = self._wait()
        if isinstance(job, str) or not job.get("result"):
            return job if isinstance(job, str) else "Preview did not finish; ask for the job status."
        return "\n".join(
            f"- {r['name']}: v{r['current']} → v{r['target']}, update {r['update']}, add {r['add']}, "
            f"conflicts {r['conflict']}, removed {r['removed']} — {r['status']}"
            for r in job["result"]
        )

    def apply_framework_update(self, confirm: bool = False, commit: bool = True) -> str:
        """
        Update the framework of every updatable project. Call with confirm=True only after user approval.
        :param confirm: Must be True; otherwise only the preview is returned.
        :param commit: Commit each cleanly updated project locally.
        :return: The result per project.
        """
        if not confirm:
            return "Not applied. Show the user this preview and ask before calling again with confirm=True:\n" + self.preview_framework_update()
        body = {"commit": commit, "confirm": True, **({"root": self.valves.projects_folder} if self.valves.projects_folder else {})}
        started = self._call("POST", "/api/update/apply", body)
        if isinstance(started, str):
            return started
        self._wait(300)
        return self.get_job_status()

    def list_web_services(self) -> str:
        """
        List every tracked project with a FastAPI web service, its local URL and whether it is running.
        :return: One line per project web service.
        """
        rows = self._call("GET", "/api/web/services?" + self._root_query())
        if isinstance(rows, str):
            return rows
        lines = [f"- {r['name']}: {'RUNNING' if r['running'] else 'stopped'} ({r['url']})" for r in rows]
        return "\n".join(lines) or "No projects with a web service found."

    def start_project_web(self, project: str, confirm: bool = False) -> str:
        """
        Start a project's FastAPI web server in the background and return its local URL.
        :param project: Project name or absolute path.
        :param confirm: Must be True; first ask the user before starting the server.
        :return: Start result with URL, or confirmation prompt.
        """
        if not confirm:
            return f"Not started yet. Tell the user `{project}` web server will be started; call again with confirm=True."
        body = {"project": project, "confirm": True, **({"root": self.valves.projects_folder} if self.valves.projects_folder else {})}
        res = self._call("POST", "/api/web/start", body)
        if isinstance(res, str):
            return res
        return f"{res['name']} ready at {res['url']} (already_running={res.get('already_running', False)})."

    def stop_project_web(self, project: str, confirm: bool = False) -> str:
        """
        Stop a Hub-managed project web server to free host memory.
        :param project: Project name or absolute path.
        :param confirm: Must be True; first ask the user before stopping the server.
        :return: Stop result message.
        """
        if not confirm:
            return f"Not stopped yet. Tell the user `{project}` web server will be stopped; call again with confirm=True."
        body = {"project": project, "confirm": True, **({"root": self.valves.projects_folder} if self.valves.projects_folder else {})}
        res = self._call("POST", "/api/web/stop", body)
        return res if isinstance(res, str) else f"{res['name']}: {res['message']} ({res['url']})"

    def stop_all_project_webs(self, confirm: bool = False) -> str:
        """
        Stop all Hub-managed child project web servers.
        :param confirm: Must be True; first ask the user before stopping running servers.
        :return: Summary of stopped and skipped services.
        """
        if not confirm:
            return "Not stopped yet. Ask the user and call again with confirm=True to stop all managed web servers."
        body = {"confirm": True, **({"root": self.valves.projects_folder} if self.valves.projects_folder else {})}
        res = self._call("POST", "/api/web/stop-all", body)
        if isinstance(res, str):
            return res
        return f"Stopped {len(res['stopped'])}, skipped {len(res['skipped'])}."

    def refresh_project_graphify(self, project: str = "") -> str:
        """
        Update dependency graphs (agentctl graph) and Graphify knowledge graph in one or all tracked projects.
        :param project: Project name, `master`, or absolute path; empty = all tracked projects.
        :return: Job state and trailing output lines.
        """
        body = {"project": project, **({"root": self.valves.projects_folder} if self.valves.projects_folder else {})}
        started = self._call("POST", "/api/projects/graphify", body)
        if isinstance(started, str):
            return started
        self._wait(300)
        return self.get_job_status()

    def add_template_feedback(self, project: str, text: str, confirm: bool = False) -> str:
        """
        Append a template improvement suggestion into a project's docs/TEMPLATE_FEEDBACK.md.
        :param project: Tracked project name, `master`, or absolute project path.
        :param text: Suggestion text to add.
        :param confirm: Must be True after asking the user to approve.
        :return: Confirmation message or added row summary.
        """
        if not confirm:
            return f"Not added yet. Ask the user to confirm adding feedback to `{project}`: {text}"
        body = {"project": project, "text": text, "source": "openwebui", "confirm": True}
        if self.valves.projects_folder:
            body["root"] = self.valves.projects_folder
        res = self._call("POST", "/api/feedback/add", body)
        return res if isinstance(res, str) else f"Added to {res['project']}: {res['text']} ({res['status']})"

    def update_feedback_status(self, file: str, text: str, status: str, confirm: bool = False) -> str:
        """
        Update the status cell of a suggestion inside `<project>/docs/TEMPLATE_FEEDBACK.md`.
        :param file: Path to docs/TEMPLATE_FEEDBACK.md.
        :param text: Exact suggestion text of the row.
        :param status: New status (待決定, 已採用, or 不採用).
        :param confirm: Must be True after asking the user to approve.
        :return: Confirmation message or updated row summary.
        """
        if not confirm:
            return f"Not updated yet. Ask the user to confirm changing `{text}` in `{file}` to `{status}`."
        res = self._call("POST", "/api/feedback/status", {"file": file, "text": text, "status": status, "confirm": True})
        return res if isinstance(res, str) else f"Updated {res['project']}: {res['text']} -> {res['status']}"
