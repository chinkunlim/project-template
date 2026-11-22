#!/usr/bin/env python3
"""Unit and scaffold tests for v3.6.0 Tier 1 & Tier 2 template upgrades."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TEMPLATE_ROOT / "src"))
sys.path.insert(0, str(TEMPLATE_ROOT / ".agents" / "lib"))
sys.path.insert(0, str(TEMPLATE_ROOT / ".agents" / "bin"))
sys.path.insert(0, str(TEMPLATE_ROOT / ".agents" / "skills" / "code-review-guard" / "scripts"))
sys.path.insert(0, str(TEMPLATE_ROOT / ".agents" / "skills" / "compliance-scanner" / "scripts"))

import framework_install  # noqa: E402
import review_guard  # noqa: E402
import scan_compliance  # noqa: E402
import setup_env  # noqa: E402

from project_template.services.scaffold import scaffold_project  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Template Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Template Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "maintenance.auto",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "gc.auto",
    "GIT_CONFIG_VALUE_1": "0",
    "TEMPLATE_NO_REGISTRY": "1",
    "TEMPLATE_SKIP_UV_LOCK": "1",
}


def _run(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command inside `cwd` with deterministic test env vars."""
    merged_env = {**os.environ, **GIT_ENV, **(env or {})}
    for key in ("AI_AGENT_NAME", "CLAUDECODE", "GEMINI_CLI", "CURSOR_TRACE_ID", "WINDSURF_SESSION"):
        if env is None or key not in env:
            merged_env.pop(key, None)
    cmd = [sys.executable, *args] if args[0].endswith(".py") or args[0] == "-m" else list(args)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=merged_env, check=False)


class Tier1FrameworkFixesTest(unittest.TestCase):
    """Tests for Tier 1 framework bug fixes, drift checks, hooks and multi-agent safety."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "app"
        scaffold_project(self.root, "app", stack="python")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_setup_env_import_hints_and_stdlib(self) -> None:
        """`setup_env` expands PyPI mappings (`PIL`->`Pillow`, `docx`->`python-docx`) and 3.11+ stdlib."""
        self.assertEqual(setup_env.IMPORT_HINTS["PIL"], "Pillow")
        self.assertEqual(setup_env.IMPORT_HINTS["docx"], "python-docx")
        self.assertTrue(setup_env.is_stdlib("tomllib"))
        self.assertTrue(setup_env.is_stdlib("zoneinfo"))

    def test_auto_commit_deleted_file_and_push_on_clean_tree(self) -> None:
        """`auto_commit` stages deleted files cleanly and `--push` pushes prior local commits when clean."""
        remote = Path(self.tmp.name) / "remote.git"
        _run(self.root, "git", "init", "-q", "--bare", str(remote))
        _run(self.root, "git", "remote", "add", "origin", str(remote))
        self.assertEqual(_run(self.root, "git", "push", "-q", "-u", "origin", "main", env={"ALLOW_PUSH": "1"}).returncode, 0)

        target = self.root / "src" / "app" / "services" / "temp.py"
        target.write_text('"""Temp."""\n\nimport logging\n\nlogger = logging.getLogger(__name__)\n', encoding="utf-8")
        self.assertEqual(_run(self.root, "scripts/agentctl.py", "commit", "--agent", "codex", "-m", "feat(services): add temp").returncode, 0)

        target.unlink()
        del_res = _run(self.root, "scripts/agentctl.py", "commit", "--agent", "codex", "-m", "chore(services): remove temp")
        self.assertEqual(del_res.returncode, 0, del_res.stdout + del_res.stderr)

        push_res = _run(self.root, "scripts/agentctl.py", "commit", "--push")
        self.assertEqual(push_res.returncode, 0, push_res.stdout + push_res.stderr)
        self.assertEqual(_run(self.root, "git", "rev-parse", "HEAD").stdout, _run(self.root, "git", "rev-parse", "origin/main").stdout)

    def test_review_guard_excludes_vendor_and_supports_staged_mode(self) -> None:
        """Vendor/minified files are ignored, and `--staged` ignores unstaged undocumented work."""
        vendor_file = self.root / "src" / "app" / "vendor" / "third_party.py"
        vendor_file.parent.mkdir(parents=True, exist_ok=True)
        vendor_file.write_text("def bad_vendor(x):\n    return x\n", encoding="utf-8")

        unstaged_bad = self.root / "src" / "app" / "services" / "wip.py"
        unstaged_bad.write_text("def undocumented_wip(x):\n    return x\n", encoding="utf-8")

        staged_good = self.root / "src" / "app" / "services" / "clean.py"
        staged_good.write_text(
            '"""Clean module."""\n\nimport logging\n\nlogger = logging.getLogger(__name__)\n\n\n'
            'def ok(val: int) -> int:\n    """Double input.\n\n    Args:\n        val: Input integer.\n\n    Returns:\n        Doubled integer.\n    """\n    return val * 2\n',
            encoding="utf-8",
        )
        _run(self.root, "git", "add", str(staged_good.relative_to(self.root)))

        issues_staged, passed_staged = review_guard.run_review(self.root, staged_only=True)
        self.assertTrue(passed_staged, issues_staged)

        issues_all, passed_all = review_guard.run_review(self.root, staged_only=False)
        self.assertFalse(passed_all)
        files = {i["file"] for i in issues_all}
        self.assertIn("src/app/services/wip.py", files)
        self.assertNotIn("src/app/vendor/third_party.py", files)

    def test_build_graph_skips_vendor_and_minified_files(self) -> None:
        """`build_graph.py` excludes `vendor/` directories and `*.min.js` bundles."""
        vendor_py = self.root / "src" / "app" / "vendor" / "lib.py"
        vendor_py.parent.mkdir(parents=True, exist_ok=True)
        vendor_py.write_text("def v():\n    return 1\n", encoding="utf-8")
        res = _run(self.root, "scripts/agentctl.py", "graph")
        self.assertEqual(res.returncode, 0, res.stderr)
        report = (self.root / "docs" / "architecture" / "GRAPH_REPORT.md").read_text(encoding="utf-8")
        self.assertNotIn("vendor/lib.py", report)

    def test_closeout_blocks_foreign_in_progress_task_unless_scoped_or_forced(self) -> None:
        """Closeout protects another agent's active task files unless `--paths` or `--force-all` is used."""
        remote = Path(self.tmp.name) / "remote2.git"
        _run(self.root, "git", "init", "-q", "--bare", str(remote))
        _run(self.root, "git", "remote", "add", "origin", str(remote))
        _run(self.root, "git", "push", "-q", "-u", "origin", "main", env={"ALLOW_PUSH": "1"})

        _run(self.root, "scripts/agentctl.py", "task", "create", "Cursor work", "--paths", "src/app/adapters", "--agent", "cursor")
        foreign_file = self.root / "src" / "app" / "adapters" / "other.py"
        foreign_file.write_text('"""Adapter."""\n\nimport logging\n\nlogger = logging.getLogger(__name__)\n', encoding="utf-8")
        my_file = self.root / "src" / "app" / "services" / "mine.py"
        my_file.write_text('"""Mine."""\n\nimport logging\n\nlogger = logging.getLogger(__name__)\n', encoding="utf-8")

        blocked = _run(
            self.root, "scripts/agentctl.py", "closeout", "--agent", "claude-code", "--goal", "Mine", "--no-push"
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("TASK-001", blocked.stderr)

        scoped = _run(
            self.root,
            "scripts/agentctl.py",
            "closeout",
            "--agent",
            "claude-code",
            "--goal",
            "Scoped work",
            "--paths",
            "src/app/services/mine.py",
            "--no-push",
        )
        self.assertEqual(scoped.returncode, 0, scoped.stdout + scoped.stderr)
        self.assertTrue(foreign_file.exists())
        status = _run(self.root, "git", "status", "--porcelain").stdout
        self.assertIn("adapters/other.py", status)
        self.assertNotIn("services/mine.py", status)

    def test_drift_detection_and_scanner_version(self) -> None:
        """`detect_framework_drift` catches missing rules/skills, and `scan_compliance` reads version dynamically."""
        info = scan_compliance.check_framework_status(self.root)
        self.assertEqual(info["current_version"], "3.6.0")
        self.assertEqual(info["template_version"], "3.6.0")

        agents = self.root / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8").replace("15. **", "15. "), encoding="utf-8")
        toml = self.root / ".agents" / "project.toml"
        toml.write_text(toml.read_text(encoding="utf-8").replace('"compliance-scanner", ', ""), encoding="utf-8")

        drift = framework_install.detect_framework_drift(self.root, TEMPLATE_ROOT)
        self.assertTrue(any("15" in item for item in drift), drift)
        self.assertTrue(any("compliance-scanner" in item for item in drift), drift)

        dry = _run(self.root, "scripts/agentctl.py", "update", "--from", str(TEMPLATE_ROOT), "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("漂移", dry.stdout)

    def test_graphify_hooks_exist_safe_when_missing_and_clear_stale_locks(self) -> None:
        """Graphify hooks exit cleanly when graphify/graphify-out is absent and prune stale locks."""
        hooks_dir = TEMPLATE_ROOT / ".agents" / "hooks"
        for name in ("post-commit", "post-merge", "post-checkout", "graphify-refresh.sh"):
            path = hooks_dir / name
            self.assertTrue(path.is_file(), name)
            self.assertTrue(os.access(path, os.X_OK), name)
            self.assertEqual(subprocess.run(["bash", "-n", str(path)], check=False).returncode, 0)

        no_graph_out = _run(self.root, "bash", str(self.root / ".agents" / "hooks" / "graphify-refresh.sh"), env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(no_graph_out.returncode, 0)
        self.assertEqual(no_graph_out.stderr.strip(), "")

        (self.root / "graphify-out").mkdir()
        warn_res = _run(self.root, "bash", str(self.root / ".agents" / "hooks" / "graphify-refresh.sh"), env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(warn_res.returncode, 0)
        self.assertIn("graphify not installed", warn_res.stderr)

        fake_bin = Path(self.tmp.name) / "bin"
        fake_bin.mkdir()
        fake_graphify = fake_bin / "graphify"
        fake_graphify.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_graphify.chmod(0o755)
        lock = self.root / "graphify-out" / ".hook.lock"
        lock.mkdir()
        os.utime(lock, (1_700_000_000, 1_700_000_000))
        stale_res = _run(
            self.root,
            "bash",
            str(self.root / ".agents" / "hooks" / "graphify-refresh.sh"),
            env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
        )
        self.assertEqual(stale_res.returncode, 0)
        self.assertIn("removed a stale lock", stale_res.stderr)

    def test_task_checklist_generation(self) -> None:
        """`agentctl task create --checklist` and `task checklist` generate cross-session checklists."""
        res = _run(self.root, "scripts/agentctl.py", "task", "create", "Live verify feature", "--agent", "claude-code", "--checklist")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        chk1 = self.root / ".agents" / "tasks" / "TASK-001-checklist.md"
        self.assertTrue(chk1.is_file())
        content = chk1.read_text(encoding="utf-8")
        self.assertIn("已證實", content)
        self.assertIn("不可修改之使用者決定", content)

        _run(self.root, "scripts/agentctl.py", "task", "create", "Second task")
        res2 = _run(self.root, "scripts/agentctl.py", "task", "checklist", "TASK-002")
        self.assertEqual(res2.returncode, 0, res2.stderr)
        self.assertTrue((self.root / ".agents" / "tasks" / "TASK-002-checklist.md").is_file())


class Tier2WebApiDbPacksTest(unittest.TestCase):
    """Tests for Tier 2 `--with api / web / db` starter packs and offline contract suites."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_api_db_web_scaffold_files_guard_and_ruff_format(self) -> None:
        """`--with api db web` generates Tier 2 modules passing guard and ruff lint/format cleanly."""
        target = self.base / "fullweb"
        scaffold_project(target, "fullweb", stack="python", addons=["api", "db", "web"])

        expected_files = (
            "src/fullweb/entrypoints/wiring.py",
            "src/fullweb/domain/protocols.py",
            "src/fullweb/entrypoints/http/port_check.py",
            "web/api_client.js",
            "tests/test_port_check.py",
            "tests/test_web_contracts.py",
        )
        for rel in expected_files:
            self.assertTrue((target / rel).is_file(), f"missing {rel}")

        guard = _run(target, ".agents/skills/code-review-guard/scripts/review_guard.py", str(target))
        self.assertEqual(guard.returncode, 0, guard.stdout)
        self.assertNotIn("IMPORTANT", guard.stdout, guard.stdout)

        ruff = shutil.which("ruff") or str(Path(sys.executable).parent / "ruff")
        if Path(ruff).exists():
            lint_res = subprocess.run([ruff, "check", "."], cwd=target, capture_output=True, text=True, check=False)
            self.assertEqual(lint_res.returncode, 0, lint_res.stdout + lint_res.stderr)
            fmt_res = subprocess.run([ruff, "format", "--check", "."], cwd=target, capture_output=True, text=True, check=False)
            self.assertEqual(fmt_res.returncode, 0, fmt_res.stdout + fmt_res.stderr)

        db_session_src = (target / "src" / "fullweb" / "adapters" / "db" / "session.py").read_text(encoding="utf-8")
        self.assertIn("make_request_scoped_session", db_session_src)
        app_src = (target / "src" / "fullweb" / "entrypoints" / "http" / "app.py").read_text(encoding="utf-8")
        self.assertIn("add_db_session_scope", app_src)
        self.assertIn("NoCacheStaticFiles", app_src)

    def test_api_web_without_db_runs_contracts_nocache_portcheck_and_wiring(self) -> None:
        """`--with api web` runs all starter API, MCP, port-check, path-guard and WebContracts tests live."""
        target = self.base / "apiweb"
        scaffold_project(target, "apiweb", stack="python", addons=["api", "web"])

        res = _run(
            target,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
            env={"PYTHONPATH": str(target / "src"), "LOG_TO_FILE": "false"},
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("test_every_dom_id_in_js_exists_in_html", res.stderr)
        self.assertIn("test_every_fetched_api_path_exists_in_openapi", res.stderr)
        self.assertIn("test_static_files_send_no_cache", res.stderr)
        self.assertIn("test_safe_resolve_under_blocks_traversal", res.stderr)
        self.assertIn("test_unbound_and_bound_ports", res.stderr)

    def test_web_without_api_creates_dom_contract_test_and_passes(self) -> None:
        """`--with web` (without `api`) creates `tests/test_web_contracts.py` and passes all tests."""
        target = self.base / "plainweb"
        scaffold_project(target, "plainweb", stack="python", addons=["web"])
        self.assertTrue((target / "tests" / "test_web_contracts.py").is_file())
        self.assertTrue((target / "web" / "api_client.js").is_file())
        res = _run(
            target,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
            env={"PYTHONPATH": str(target / "src"), "LOG_TO_FILE": "false"},
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(json.loads((target / ".agents" / "framework.lock").read_text(encoding="utf-8"))["framework_version"], "3.6.0")


if __name__ == "__main__":
    unittest.main()
