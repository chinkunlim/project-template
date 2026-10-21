"""
title: 專案母版（Project template）
author: limchinkun
version: 0.1.0
description: Create projects, migrate old projects, list projects and run doctor / check on them, collect
  template feedback and preview / apply the framework update, through the template's local web app
  (python3 scripts/web_ui.py). Paste this file into Open WebUI → Workspace → Tools.
"""

# Open WebUI tool for the project template (same pattern as literature-fetch ADR-008).
# It calls the JSON API of scripts/web_ui.py; nothing else is needed inside Open WebUI (standard library only).
# Alternatives without pasting code: add http://127.0.0.1:8766 as an OpenAPI tool server, or (admin)
# http://127.0.0.1:8766/mcp as an MCP (Streamable HTTP) connection.
# Native Open WebUI (uv tool install, 127.0.0.1:8080): base_url http://127.0.0.1:8766 (default).
# Open WebUI in Docker: base_url http://host.docker.internal:8766 and start the app with
#   python3 scripts/web_ui.py --allow-host host.docker.internal

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field


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
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            return f"Error {exc.code}: {str(detail)[:300]}"
        except OSError as exc:
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
        List the projects created from the template: name, framework version, uncommitted files and last commit.
        :return: One line per project.
        """
        rows = self._call("GET", "/api/projects?" + self._root_query())
        if isinstance(rows, str):
            return rows
        lines = [f"- {r['name']} (v{r['version']}, {'clean' if not r['dirty'] else str(r['dirty']) + ' uncommitted files'}) — "
                 f"{r['last_commit']} — {r['path']}" for r in rows]
        return "\n".join(lines) or "No projects found."

    def create_project(self, name: str, stack: str = "python", addons: str = "", folder: str = "", data_dir: str = "",
                       description: str = "", install: bool = False, confirm: bool = False) -> str:
        """
        Create a new project from the template (folders, docs, agent rules, git with a first commit), then repair its
        environment. Runs in the background; ask for the job status afterwards.
        :param name: Project and folder name (letters, digits, Chinese, space, - _ .).
        :param stack: python (default), node, gas, go, rust, generic, both (python+web), all (python+web+gas) or mobile.
        :param addons: Comma-separated add-ons: web, gas, mobile, api, db, ollama, evals (api/db/ollama need python).
        :param folder: Absolute folder to create the project in; empty = the projects folder.
        :param data_dir: Absolute data folder; empty = projects-data/<name> next to the projects folder.
        :param description: One-line description of the project.
        :param install: Also install the dependencies inside the project (needs internet).
        :param confirm: Must be True; first describe the project to the user and call with confirm=True after they agree.
        :return: Whether the job started, with the commands it runs.
        """
        if not confirm:
            return (f"Not created yet. Tell the user: project '{name}' (stack {stack}, add-ons {addons or 'none'}) will be "
                    "created with git, docs and agent rules. Call again with confirm=True after they agree.")
        info = self._call("GET", "/api/info")
        if isinstance(info, str):
            return info
        body = {
            "name": name, "parent": folder or self.valves.projects_folder or info["projects_root"], "data_dir": data_dir,
            "stack": stack, "addons": [a.strip() for a in addons.split(",") if a.strip()], "description": description,
            "doctor": True, "setup": install, "check": True, "confirm": True,
        }
        result = self._call("POST", "/api/create", body)
        if isinstance(result, str):
            return result
        return f"Started: {result['title']}.\nCommands:\n" + "\n".join(result["commands"]) + "\nAsk for the job status to follow it."

    def migrate_project(self, source: str, name: str = "", folder: str = "", mode: str = "maintain",
                        confirm: bool = False) -> str:
        """
        Migrate an old project into a new folder that follows the template. The old project is never changed; git history
        is kept, old files go to legacy/ and docs/migration/MIGRATION.md lists the batches. Runs in the background.
        :param source: Absolute folder of the old project (it must be committed).
        :param name: New project name; empty = the old folder name.
        :param folder: Absolute folder to create the new project in; empty = the projects folder.
        :param mode: maintain (finished project, keep Flask) or develop (continue development, rewrite Flask as FastAPI).
        :param confirm: Must be True; first tell the user what will happen and call with confirm=True after they agree.
        :return: Whether the job started.
        """
        if not confirm:
            return (f"Not migrated yet. Tell the user {source} will be copied into a new project (the old one is not changed); "
                    "call again with confirm=True after they agree.")
        info = self._call("GET", "/api/info")
        if isinstance(info, str):
            return info
        body = {"source": source, "name": name or source.rstrip("/").split("/")[-1],
                "parent": folder or self.valves.projects_folder or info["projects_root"], "mode": mode, "confirm": True}
        result = self._call("POST", "/api/migrate", body)
        return result if isinstance(result, str) else f"Started: {result['title']}. Ask for the job status to follow it."

    def get_job_status(self) -> str:
        """
        Get the state and the last output lines of the current or last job (create, migrate, project command, update).
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
        :param command: status, doctor, check (read only), doctor-fix (repair) or setup (install dependencies).
        :return: The command output.
        """
        if command in ("doctor-fix", "setup"):
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
        List the template-improvement suggestions recorded in every project's docs/TEMPLATE_FEEDBACK.md (read only).
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
        return "\n".join(f"- {r['name']}: v{r['current']} → v{r['target']}, update {r['update']}, add {r['add']}, "
                         f"conflicts {r['conflict']}, removed {r['removed']} — {r['status']}" for r in job["result"])

    def apply_framework_update(self, confirm: bool = False, commit: bool = True) -> str:
        """
        Update the framework of every project that can be updated. Project edits are never overwritten, projects with
        uncommitted work are skipped, nothing is pushed. Only call with confirm=True after the user agreed to the preview.
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
