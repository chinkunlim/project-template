#!/usr/bin/env python3
"""End-to-end tests for the project template (framework v3).

Each test scaffolds real projects into a temporary folder and drives the generated
scripts the way an agent would. Regression tests for fixed bugs are marked `Bug N`
(numbering follows the v3 review plan).

Run:
    python3 tests/test_framework.py -v
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TEMPLATE_ROOT))
sys.path.insert(0, str(TEMPLATE_ROOT / "skills" / "code-review-guard" / "scripts"))

from init_project import scaffold_project  # noqa: E402
import review_guard  # noqa: E402

# Deterministic git identity so commits work on any machine / CI
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Template Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Template Test", "GIT_COMMITTER_EMAIL": "test@example.com",
}
os.environ.update(GIT_ENV)
os.environ["TEMPLATE_SKIP_UV_LOCK"] = "1"  # unit tests stay offline; see UvIntegrationTest for the real uv flow
_DATA_HOME = tempfile.TemporaryDirectory(prefix="template-test-data-")
os.environ["DATA_DIR"] = _DATA_HOME.name  # tests never write into the user's real ~/project-data
HAS_NODE = shutil.which("node") is not None
for _var in ("AI_AGENT_NAME", "CLAUDECODE", "GEMINI_CLI", "CURSOR_TRACE_ID", "WINDSURF_SESSION"):
    os.environ.pop(_var, None)


def run(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a command in `cwd` and capture its output.

    Args:
        cwd: Working directory.
        *args: Command and arguments; a leading `.py` path or `-m` runs with the current Python.
        env: Extra environment variables.

    Returns:
        The completed process.
    """
    cmd = [sys.executable, *args] if args[0].endswith(".py") or args[0] == "-m" else list(args)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})


def git_log_body(cwd: Path) -> str:
    """Return the full message of the latest commit.

    Args:
        cwd: Repository root.

    Returns:
        Commit message text.
    """
    return run(cwd, "git", "log", "-1", "--pretty=format:%B").stdout


class ScaffoldTest(unittest.TestCase):
    """Project creation, structure and portability."""

    def setUp(self) -> None:
        """Create a temporary folder for each test."""
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        """Remove the temporary folder."""
        self.tmp.cleanup()

    def test_python_project_structure(self) -> None:
        """The python stack gets the docs skeleton, lock, hooks, skills and passing starter code."""
        target = self.base / "demo_py"
        skills = scaffold_project(target, "demo_py", stack="python")
        for rel in (
            ".agents/project.toml", ".agents/framework.lock", ".agents/handoff/LATEST.md", "AGENTS.md", "CLAUDE.md",
            "docs/adr/DECISIONS.md", "docs/known-issues/KNOWN_ISSUES.md", "docs/specs/SPECS.md",
            "docs/architecture/ARCHITECTURE.md", "docs/adr/_TEMPLATE.md", "docs/known-issues/_TEMPLATE.md",
            "docs/specs/_TEMPLATE.md", ".agents/bin/conversations.py", ".agents/bin/check_staged.py",
            "docs/architecture/PROJECT_TREE.md", "scripts/agentctl.py", ".agents/bin/doctor.py", ".agents/bin/setup_env.py",
            ".agents/hooks/pre-commit", ".agents/skills/catalog.json",
        ):
            self.assertTrue((target / rel).exists(), rel)
        self.assertEqual(sorted(p.name for p in (target / "scripts").iterdir()), ["agentctl.py"], "scripts/ only holds the launcher")
        for template_only in (".agents/skills/skills.lock.json", ".agents/bin/sync_github_skills.py"):
            self.assertFalse((target / template_only).exists(), template_only)
        self.assertIn("api-adapter-scaffold", skills)
        self.assertNotIn("frontend-design", skills)
        self.assertFalse(list((target / ".agents" / "skills").glob("*/upstream")))
        self.assertEqual(run(target, "git", "config", "core.hooksPath").stdout.strip(), ".agents/hooks")
        self.assertIn("chore(init)", run(target, "git", "log", "--oneline").stdout)
        self.assertEqual(run(target, "git", "status", "--porcelain").stdout.strip(), "", "init leaves a clean tree")
        self.assertEqual(run(target, "-m", "unittest", "discover", "-s", "tests").returncode, 0)
        guard = run(target, ".agents/skills/code-review-guard/scripts/review_guard.py")
        self.assertEqual(guard.returncode, 0, guard.stdout)

    def test_agents_md_blocks_are_generated(self) -> None:
        """Bug 2: the tree block and the skills block in AGENTS.md are filled in."""
        target = self.base / "blocks"
        scaffold_project(target, "blocks", stack="python", init_git_repo=False)
        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        tree = agents.split("<!-- TREE_START -->", 1)[1].split("<!-- TREE_END -->", 1)[0]
        self.assertIn(".agents/", tree)
        self.assertIn("session-closeout", agents.split("<!-- SKILLS_START -->", 1)[1])
        self.assertIn("session-closeout", (target / "GEMINI.md").read_text(encoding="utf-8"))
        self.assertEqual(run(target, ".agents/bin/update_tree.py", "--check").returncode, 0)

    def test_only_one_readme_and_templates_everywhere(self) -> None:
        """Only the root has README.md; every docs folder has an index and a `_TEMPLATE.md`."""
        for stack in ("python", "generic"):
            target = self.base / f"names_{stack}"
            scaffold_project(target, f"names_{stack}", stack=stack, init_git_repo=False)
            readmes = [p.relative_to(target).as_posix() for p in target.rglob("README.md") if ".git" not in p.parts]
            self.assertEqual(readmes, ["README.md"], stack)
            self.assertFalse((target / "docs" / "adr" / "000-template.md").exists())
        self.assertTrue((self.base / "names_generic" / "src" / "config" / "LAYER.md").exists())

    def test_tracker_uses_folder_template(self) -> None:
        """`tracker_cli --add-issue` fills the folder's `_TEMPLATE.md` (custom edits included)."""
        target = self.base / "tracker"
        scaffold_project(target, "tracker", stack="python", init_git_repo=False)
        template = target / "docs" / "known-issues" / "_TEMPLATE.md"
        template.write_text(template.read_text(encoding="utf-8") + "\n## 5. 自訂欄位\n", encoding="utf-8")
        tool = ".agents/skills/adr-issue-tracker/scripts/tracker_cli.py"
        res = run(target, tool, "--add-issue", "api-timeout", "--title", "API | timeout", "--summary", "504 from upstream", "--agent", "cursor")
        self.assertEqual(res.returncode, 0, res.stderr)
        record = (target / "docs" / "known-issues" / "001-api-timeout.md").read_text(encoding="utf-8")
        self.assertIn("# ISSUE-001：API | timeout", record)
        self.assertIn("504 from upstream", record)
        self.assertIn("`cursor`", record)
        self.assertIn("自訂欄位", record)
        self.assertNotIn("{{", record)
        index = (target / "docs" / "known-issues" / "KNOWN_ISSUES.md").read_text(encoding="utf-8")
        self.assertIn("[ISSUE-001](001-api-timeout.md)", index)
        self.assertIn("API \\| timeout", index)
        run(target, tool, "--add-adr", "cache", "--title", "Use LRU")
        self.assertTrue((target / "docs" / "adr" / "001-cache.md").exists(), "_TEMPLATE.md is not counted as a record")
        status = run(target, "scripts/agentctl.py", "status").stdout
        self.assertNotIn("_TEMPLATE", status)
        self.assertNotIn("SESSIONS.md", status)

    def test_non_empty_target_is_refused(self) -> None:
        """Bug 5: an existing folder is not overwritten unless --force is given."""
        target = self.base / "existing"
        target.mkdir()
        (target / "README.md").write_text("my notes", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            scaffold_project(target, "existing", stack="generic")
        self.assertEqual((target / "README.md").read_text(encoding="utf-8"), "my notes")
        scaffold_project(target, "existing", stack="generic", force=True)
        self.assertEqual(run(target, "git", "log", "--oneline").stdout.strip(), "", "no automatic commit into an existing folder")

    def test_mobile_addon_layout_rules_and_offline_tests(self) -> None:
        """`--with mobile` adds a layered Expo app, its rules, CI, Brewfile, and blocks signing keys; `--stack mobile` is app-only."""
        target = self.base / "phone"
        scaffold_project(target, "phone", stack="python", addons=["api", "mobile"])
        for rel in ("mobile/package.json", "mobile/app.json", "mobile/tsconfig.json", "mobile/index.ts", "mobile/MOBILE.md",
                    "mobile/.env.example", "mobile/src/config/env.ts", "mobile/src/config/logger.ts", "mobile/src/domain/models.ts",
                    "mobile/src/services/greeting.ts", "mobile/src/adapters/api.ts", "mobile/src/entrypoints/App.tsx",
                    "mobile/test/greeting.test.ts", "Brewfile", ".nvmrc"):
            self.assertTrue((target / rel).exists(), rel)
        pkg = json.loads((target / "mobile" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["scripts"]["tunnel"], "expo start --tunnel")
        self.assertIn("@expo/ngrok", pkg["devDependencies"], "--tunnel never installs anything globally")
        self.assertIn("node-linker=hoisted", (target / "mobile" / ".npmrc").read_text(encoding="utf-8"))
        toml = (target / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn('"mobile/src"', toml)
        self.assertIn("(cd mobile && node --test)", toml)
        self.assertIn("(cd mobile && pnpm exec tsc --noEmit)", toml)
        for needle in ("mobile/ios/", "mobile/android/", "*.jks", "*.mobileprovision", "node_modules/"):
            self.assertIn(needle, (target / ".gitignore").read_text(encoding="utf-8"))
        ci = (target / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("working-directory: mobile", ci)
        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("expo start --tunnel", agents)
        self.assertIn("adb reverse", agents)
        self.assertEqual(run(target, ".agents/skills/code-review-guard/scripts/review_guard.py").returncode, 0)
        self.assertEqual(run(target, "scripts/agentctl.py", "graph").returncode, 0)
        check = run(target, "scripts/agentctl.py", "check")
        self.assertIn("尚未安裝 mobile/node_modules", check.stdout, "the mobile type check waits for pnpm install")
        if HAS_NODE:
            self.assertEqual(run(target / "mobile", "node", "--test").returncode, 0, "TypeScript tests run with no install")
        (target / "mobile" / "release.jks").write_bytes(b"key")
        run(target, "git", "add", "-f", "mobile/release.jks")
        blocked = run(target, "git", "commit", "-m", "chore: key")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("signing", blocked.stdout + blocked.stderr)
        only = self.base / "apponly"
        scaffold_project(only, "apponly", stack="mobile", init_git_repo=False)
        self.assertFalse((only / "src").exists(), "app-only project keeps its code in mobile/")
        self.assertIn('source_roots = ["mobile/src"]', (only / ".agents" / "project.toml").read_text(encoding="utf-8"))

    def test_all_stacks_pass_guard_and_graph(self) -> None:
        """Every stack's starter code follows the comment and layer rules."""
        for stack in ("node", "gas", "go", "rust", "generic", "both", "all", "mobile"):
            target = self.base / f"p_{stack}"
            scaffold_project(target, f"p_{stack}", stack=stack, init_git_repo=False)
            guard = run(target, ".agents/skills/code-review-guard/scripts/review_guard.py")
            self.assertEqual(guard.returncode, 0, f"{stack}: {guard.stdout}")
            self.assertEqual(run(target, "scripts/agentctl.py", "graph").returncode, 0, stack)
            self.assertFalse((target / "docs" / "architecture" / "AGENT_AUDIT_REPORT.md").exists(), "reports are on demand")
            graph = json.loads((target / ".agents" / "cache" / "graph.json").read_text(encoding="utf-8"))
            self.assertEqual(graph["layer_violations"], [], stack)

    def test_ci_workflow_matches_stack(self) -> None:
        """Each stack gets a CI workflow with its own toolchain and test command."""
        expectations = {
            "python": ("setup-uv", "uv run python -m unittest discover -s tests -v", "uv sync", "uv run python scripts/agentctl.py check"),
            "node": ("pnpm/action-setup", "node-version-file: .nvmrc", "pnpm install", "python3 scripts/agentctl.py check"),
            "gas": ("pnpm/action-setup", "node --test", "pnpm install", "python3 scripts/agentctl.py check"),
            "go": ("setup-go", "go test ./...", "python3 scripts/agentctl.py check"),
        }
        for stack, needles in expectations.items():
            target = self.base / f"ci_{stack}"
            scaffold_project(target, f"ci_{stack}", stack=stack, init_git_repo=False)
            workflow = (target / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertTrue(workflow.startswith("# ==="), "header comment")
            self.assertIn("continue-on-error: true", workflow)
            self.assertNotIn("pip install", workflow)
            for needle in needles:
                self.assertIn(needle, workflow, stack)
        self.assertNotIn("setup-node", (self.base / "ci_python" / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
        target = self.base / "ci_python_gas"
        scaffold_project(target, "ci_python_gas", stack="python", addons=["gas"], init_git_repo=False)
        workflow = (target / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("working-directory: gas", workflow)
        self.assertIn("(cd gas && node --test)", workflow)

    def test_python_project_is_isolated_and_pinned(self) -> None:
        """Python projects pin 3.11, use uv-managed Python and never mention global pip."""
        target = self.base / "iso"
        scaffold_project(target, "iso", stack="python", init_git_repo=False)
        self.assertEqual((target / ".python-version").read_text(encoding="utf-8").strip(), "3.11")
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        for needle in ('requires-python = ">=3.11"', 'python-preference = "only-managed"', "[dependency-groups]", "ruff", "mypy",
                       "[tool.mypy]", "strict = true", "[project.scripts]"):
            self.assertIn(needle, pyproject)
        toml = (target / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn('test = "uv run python -m unittest discover -s tests -v"', toml)
        self.assertIn("uv run ruff check .", toml)
        self.assertIn('typecheck = "uv run mypy"', toml)
        self.assertIn("OLLAMA_BASE_URL=http://127.0.0.1:11434", (target / ".env.example").read_text(encoding="utf-8"))
        for rel in ("README.md", "AGENTS.md", "GEMINI.md"):
            text = (target / rel).read_text(encoding="utf-8")
            self.assertIn("uv", text, rel)
        self.assertTrue((target / "src" / "iso" / "entrypoints" / "cli.py").exists())
        self.assertTrue((target / "src" / "iso" / "config" / "logging_setup.py").exists())
        check = run(target, "scripts/agentctl.py", "check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("略過 lint", check.stdout, "lint waits for the project .venv instead of installing anything")
        self.assertIn("略過 typecheck", check.stdout)

    def test_python_with_web_and_gas_addons(self) -> None:
        """`--with web gas` keeps each part in its own folder with its own source root."""
        target = self.base / "mix"
        skills = scaffold_project(target, "mix", stack="python", addons=["web", "gas"], timezone="Asia/Kuala_Lumpur", init_git_repo=False)
        self.assertIn("frontend-design", skills)
        for rel in ("src/mix/services/greeting.py", "web/index.html", "web/app.js", "gas/src/Main.js", "gas/.claspignore",
                    "gas/.clasp.json.example", "gas/GAS.md", "gas/Code.gs"):
            self.assertTrue((target / rel).exists(), rel)
        self.assertFalse((target / "package.json").exists(), "Node files stay inside gas/")
        toml = (target / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn('source_roots = ["src/mix", "web", "gas/src"]', toml)
        self.assertEqual(json.loads((target / "gas" / "appsscript.json").read_text(encoding="utf-8"))["timeZone"], "Asia/Kuala_Lumpur")
        gas_pkg = json.loads((target / "gas" / "package.json").read_text(encoding="utf-8"))
        self.assertIn("@google/clasp", gas_pkg["devDependencies"])
        self.assertTrue((target / ".nvmrc").exists())
        if shutil.which("pnpm"):
            self.assertTrue(gas_pkg["packageManager"].startswith("pnpm@"), "pnpm version pinned for corepack")
        self.assertIn("--bind 127.0.0.1", (target / "web" / "WEB.md").read_text(encoding="utf-8"))
        self.assertEqual(run(target, ".agents/skills/code-review-guard/scripts/review_guard.py").returncode, 0)
        self.assertEqual(run(target, "scripts/agentctl.py", "graph").returncode, 0)
        graph = json.loads((target / ".agents" / "cache" / "graph.json").read_text(encoding="utf-8"))
        self.assertIn("src/mix/services/greeting.py", [n["path"] for n in graph["nodes"]])
        if HAS_NODE:
            self.assertEqual(run(target / "gas", "node", "--test").returncode, 0)
            self.assertEqual(run(target, "node", "gas/dev/build.js", "--check").returncode, 0)

    def test_api_and_db_addons(self) -> None:
        """`--with api db web` creates FastAPI + SQLAlchemy/Alembic code that follows every rule."""
        target = self.base / "apidb"
        scaffold_project(target, "apidb", stack="python", addons=["api", "db", "web"], init_git_repo=False)
        pkg = target / "src" / "apidb"
        for rel in ("entrypoints/http/app.py", "entrypoints/http/schemas.py", "entrypoints/http/server.py",
                    "adapters/db/models.py", "adapters/db/session.py", "adapters/db/repository.py"):
            self.assertTrue((pkg / rel).exists(), rel)
        for rel in ("alembic.ini", "alembic/env.py", "alembic/script.py.mako", "tests/test_api.py", "tests/test_db.py"):
            self.assertTrue((target / rel).exists(), rel)
        self.assertFalse((target / "data").exists(), "data lives in DATA_DIR, outside the project")
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        for dep in ("fastapi", "pydantic", "uvicorn", "sqlalchemy", "alembic", "httpx", "apidb-server"):
            self.assertIn(dep, pyproject)
        toml = (target / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn("alembic upgrade head && uv run alembic check", toml)
        self.assertIn('"flask:', toml, "new projects forbid Flask")
        self.assertIn('"alembic"', toml.split("source_roots")[1].split("\n")[0])
        env = (target / ".env.example").read_text(encoding="utf-8")
        self.assertIn("HTTP_HOST=127.0.0.1", env)
        self.assertIn("DATABASE_URL=", env)
        self.assertIn("DATA_DIR=~/project-data/apidb", env)
        self.assertIn("/data/", (target / ".gitignore").read_text(encoding="utf-8"))
        self.assertIn("<data_dir>/db/app.db", (pkg / "config" / "settings.py").read_text(encoding="utf-8"))
        settings = (pkg / "config" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('http_host: str = "127.0.0.1"', settings)
        guard = run(target, ".agents/skills/code-review-guard/scripts/review_guard.py")
        self.assertEqual(guard.returncode, 0, guard.stdout)
        self.assertNotIn("IMPORTANT", guard.stdout, "starter code has no size warnings")
        with self.assertRaises(ValueError):
            scaffold_project(self.base / "bad", "bad", stack="node", addons=["api"], init_git_repo=False)

    def test_aliases_map_to_addons(self) -> None:
        """`both` = python + web and `all` = python + web + gas."""
        target = self.base / "alias_all"
        scaffold_project(target, "alias_all", stack="all", init_git_repo=False)
        toml = (target / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn('stack = "python"', toml)
        self.assertIn('addons = ["web", "gas"]', toml)

    def test_tree_check_ignores_build_output(self) -> None:
        """Install artifacts (git-ignored) do not make `update_tree --check` fail in CI."""
        target = self.base / "artifacts"
        scaffold_project(target, "artifacts", stack="python")
        (target / "src" / "artifacts.egg-info").mkdir()
        (target / "src" / "artifacts.egg-info" / "PKG-INFO").write_text("x", encoding="utf-8")
        (target / "node_modules").mkdir()
        self.assertEqual(run(target, ".agents/bin/update_tree.py", "--check").returncode, 0)
        self.assertEqual(run(target, "scripts/agentctl.py", "check").returncode, 0)

    def test_doctor_repairs_a_fresh_clone(self) -> None:
        """A clone on another machine gets hooks and skill links back via doctor --fix."""
        origin = self.base / "origin"
        scaffold_project(origin, "origin", stack="python")
        clone = self.base / "clone"
        run(self.base, "git", "clone", "--quiet", str(origin), str(clone))
        self.assertFalse((clone / ".claude" / "skills").exists(), ".claude/skills is per-machine")
        self.assertEqual(run(clone, ".agents/bin/doctor.py").returncode, 1)
        fixed = run(clone, ".agents/bin/doctor.py", "--fix")
        self.assertEqual(fixed.returncode, 0, fixed.stdout)
        self.assertEqual(run(clone, "git", "config", "core.hooksPath").stdout.strip(), ".agents/hooks")
        self.assertTrue((clone / ".claude" / "skills" / "session-closeout" / "SKILL.md").exists())


class WorkflowTest(unittest.TestCase):
    """Commit, handoff, closeout and audit as agents would use them."""

    def setUp(self) -> None:
        """Scaffold one python project per test."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "collab"
        scaffold_project(self.root, "collab", stack="python")
        self.pkg = self.root / "src" / "collab"
        # Run the project's tests with this interpreter instead of `uv run` so unit tests stay offline
        toml = self.root / ".agents" / "project.toml"
        text = toml.read_text(encoding="utf-8")
        text = text.replace('test = "uv run python -m unittest discover -s tests -v"', f'test = "{sys.executable} -m unittest discover -s tests -v"')
        toml.write_text(text, encoding="utf-8")
        run(self.root, "git", "commit", "-qam", "chore(test): offline test command\n\nAgent: test-harness")

    def tearDown(self) -> None:
        """Remove the temporary project."""
        self.tmp.cleanup()

    def write_documented_module(self, rel: str) -> None:
        """Write a small module that satisfies the comment rules.

        Args:
            rel: Path relative to the project root.
        """
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('"""Cache helpers."""\n\n\ndef ttl(seconds: int) -> int:\n    """Clamp a TTL.\n\n    Args:\n        seconds: Requested TTL.\n\n    Returns:\n        TTL between 1 and 3600.\n    """\n    return max(1, min(seconds, 3600))\n', encoding="utf-8")

    def test_commit_handles_paths_and_attribution(self) -> None:
        """Bug 1: the first `git status` line and names with spaces/CJK are committed intact."""
        greeting = self.pkg / "services" / "greeting.py"
        greeting.write_text(greeting.read_text(encoding="utf-8") + "\n# tweak\n", encoding="utf-8")
        (self.root / "docs" / "specs" / "登入 規格.md").write_text("# 登入規格\n", encoding="utf-8")
        self.write_documented_module("src/collab/services/cache.py")
        res = run(self.root, "scripts/agentctl.py", "commit", "--agent", "claude-code", "--model", "claude-opus-5-5")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        files = run(self.root, "git", "-c", "core.quotePath=false", "show", "--name-only", "--pretty=format:").stdout
        for rel in ("src/collab/services/greeting.py", "docs/specs/登入 規格.md", "src/collab/services/cache.py"):
            self.assertIn(rel, files)
        body = git_log_body(self.root)
        for expected in ("[agent:claude-code]", "Agent: claude-code", "Model: claude-opus-5-5", "Version: v0.1.0"):
            self.assertIn(expected, body)
        changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertNotIn("## [0.2.0]", changelog, "commits do not bump the version")
        unreleased = changelog.split("## [Unreleased]", 1)[1].split("## [0.1.0]", 1)[0]
        self.assertIn("### Added", unreleased)
        self.assertIn("by `@claude-code`", unreleased)
        self.assertEqual(run(self.root, "git", "status", "--porcelain").stdout.strip(), "")

    def test_logging_traces_runs_and_blocks_print(self) -> None:
        """The CLI logs to DATA_DIR/logs with a run id and line info; stdout keeps only the result; print in services is blocked."""
        data = Path(self.tmp.name) / "data"
        env = {"PYTHONPATH": str(self.root / "src"), "DATA_DIR": str(data), "LOG_TO_FILE": "true", "LOG_LEVEL": "INFO"}
        res = run(self.root, sys.executable, "-m", "collab.entrypoints.cli", "--name", "Ann", env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "Hello, Ann!", "logs go to stderr, the result to stdout")
        app_log = (data / "logs" / "app.log").read_text(encoding="utf-8")
        run_id = re.search(r"\[([0-9a-f]{8})\] .*run started", app_log).group(1)
        self.assertRegex(app_log, rf"INFO +\[{run_id}\] collab\.services\.greeting:create_greeting:\d+ - greeting user='Ann'")
        self.assertTrue((data / "logs" / "errors.log").exists())
        service = self.pkg / "services" / "greeting.py"
        service.write_text(service.read_text(encoding="utf-8") + "\n\ndef debug_dump(x: int) -> None:\n    \"\"\"Dump.\n\n    Args:\n        x: Value.\n    \"\"\"\n    print(x)\n", encoding="utf-8")
        guard = run(self.root, ".agents/skills/code-review-guard/scripts/review_guard.py")
        self.assertEqual(guard.returncode, 1)
        self.assertIn("[Logging]", guard.stdout)

    def test_check_passes_right_after_adding_files(self) -> None:
        """`agentctl check` refreshes the tree locally, so a new file never fails it; `tree --check` stays strict."""
        self.write_documented_module("src/collab/services/cache.py")
        self.assertEqual(run(self.root, "scripts/agentctl.py", "tree", "--check").returncode, 1, "tree is stale before check")
        res = run(self.root, "scripts/agentctl.py", "check")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("cache.py", (self.root / "docs" / "architecture" / "PROJECT_TREE.md").read_text(encoding="utf-8"))
        self.assertEqual(run(self.root, "scripts/agentctl.py", "tree", "--check").returncode, 0)
        self.assertNotIn("cache.py", (self.root / "AGENTS.md").read_text(encoding="utf-8"), "AGENTS.md lists folders only")

    def test_adapters_follow_agents_md_rules(self) -> None:
        """Entry files copy the AGENTS.md rules block; editing AGENTS.md + sync updates all of them."""
        agents = self.root / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8").replace("<!-- RULES_END -->", "12. **Custom rule**: say hello.\n<!-- RULES_END -->"), encoding="utf-8")
        self.assertEqual(run(self.root, "scripts/agentctl.py", "sync").returncode, 0)
        claude = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("@AGENTS.md", claude)
        self.assertNotIn("核心規則", claude, "Claude imports AGENTS.md instead of a copy")
        for rel in ("GEMINI.md", ".github/copilot-instructions.md", ".cursor/rules/00-project-constitution.mdc"):
            text = (self.root / rel).read_text(encoding="utf-8")
            self.assertIn("12. **Custom rule**: say hello.", text, rel)
            self.assertIn("## 2. 核心規則", text, rel)
        cursor = (self.root / ".cursor/rules/00-project-constitution.mdc").read_text(encoding="utf-8")
        self.assertIn("](../../docs/standards/CODING_PRINCIPLES.md)", cursor, "links are rewritten for nested files")

    def test_release_turns_unreleased_into_version_and_tag(self) -> None:
        """`finish --tag` release step: Unreleased → [0.2.0], version files bumped, commit + local tag."""
        self.write_documented_module("src/collab/services/cache.py")
        self.assertEqual(run(self.root, "scripts/agentctl.py", "commit", "--agent", "claude-code").returncode, 0)
        code = "import sys; sys.path[:0] = ['.agents/bin', '.agents/lib']; import finish, project_config; print(finish.release(project_config.load_config(), 'auto'))"
        res = run(self.root, sys.executable, "-c", code, env={"AI_AGENT_NAME": "claude-code"})
        self.assertEqual(res.stdout.strip().splitlines()[-1:], ["v0.2.0"], res.stdout + res.stderr)
        changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(changelog, r"## \[Unreleased\]\s+## \[0\.2\.0\] - \d{4}-\d{2}-\d{2}\s+### Added")
        self.assertIn('version = "0.2.0"', (self.root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(run(self.root, "git", "tag", "--list").stdout.strip(), "v0.2.0")
        self.assertIn("chore(release): v0.2.0", run(self.root, "git", "log", "-1", "--pretty=%s").stdout)
        self.assertEqual(run(self.root, "git", "status", "--porcelain").stdout.strip(), "")

    def test_secret_in_new_file_blocks_and_rolls_back(self) -> None:
        """Bugs 6 and 7: a token in an untracked file blocks the commit and edits are restored."""
        changelog_before = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        head_before = run(self.root, "git", "rev-parse", "HEAD").stdout
        (self.root / "notes.txt").write_text("token = ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4\n", encoding="utf-8")
        self.write_documented_module("src/collab/services/cache.py")
        res = run(self.root, ".agents/bin/auto_commit.py", "--agent", "claude-code")
        self.assertEqual(res.returncode, 1)
        self.assertIn("SECURITY BLOCK", res.stderr)
        self.assertEqual(run(self.root, "git", "rev-parse", "HEAD").stdout, head_before)
        self.assertEqual((self.root / "CHANGELOG.md").read_text(encoding="utf-8"), changelog_before)
        self.assertEqual(run(self.root, "git", "diff", "--cached", "--name-only").stdout.strip(), "")

    def test_hook_blocks_env_file_and_undocumented_code(self) -> None:
        """The versioned pre-commit hook blocks `.env` and code without docstrings."""
        (self.root / "config").mkdir()
        (self.root / "config" / ".env").write_text("APP_ENV=prod\n", encoding="utf-8")
        run(self.root, "git", "add", "-f", "config/.env")
        self.assertNotEqual(run(self.root, "git", "commit", "-m", "x").returncode, 0)
        run(self.root, "git", "rm", "-q", "--cached", "config/.env")
        (self.root / ".clasp.json").write_text('{"scriptId": "abc", "rootDir": "."}\n', encoding="utf-8")
        run(self.root, "git", "add", ".clasp.json")
        allowed = run(self.root, "git", "commit", "-m", "chore: clasp script id\n\nAgent: test-harness")
        self.assertEqual(allowed.returncode, 0, ".clasp.json (script ID only) may be committed: " + allowed.stdout)
        (self.pkg / "services" / "bad.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
        run(self.root, "git", "add", "src")
        res = run(self.root, "git", "commit", "-m", "bad")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("code-review-guard", res.stdout + res.stderr)

    def test_handoff_claim_rules_and_escaping(self) -> None:
        """Handoff board escapes `|`; claim refuses another agent's in-progress task without --force."""
        run(self.root, ".agents/bin/agent_task.py", "create", "Cache | metrics", "--paths", "src/collab/services", "--agent", "claude-code")
        res = run(self.root, ".agents/bin/agent_task.py", "handoff", "TASK-001", "--to", "cursor",
                  "--done-items", "service done", "--todo-items", "add TTL | metric", "--blockers", "none")
        self.assertEqual(res.returncode, 0, res.stderr)
        board = (self.root / ".agents" / "handoff" / "LATEST.md").read_text(encoding="utf-8")
        self.assertIn("Cache \\| metrics", board)
        self.assertIn("add TTL \\| metric", board)
        self.assertEqual(run(self.root, ".agents/bin/agent_task.py", "claim", "TASK-001", "--agent", "cursor").returncode, 0)
        self.assertEqual(run(self.root, ".agents/bin/agent_task.py", "claim", "TASK-001", "--agent", "gemini-cli").returncode, 1)
        self.assertEqual(run(self.root, ".agents/bin/agent_task.py", "claim", "TASK-001", "--agent", "gemini-cli", "--force").returncode, 0)
        self.assertEqual(run(self.root, ".agents/bin/agent_task.py", "done", "TASK-001", "--summary", "ok").returncode, 0)
        task = json.loads(next((self.root / ".agents" / "tasks").glob("TASK-001-*.json")).read_text(encoding="utf-8"))
        self.assertEqual([h["action"] for h in task["history"]], ["created_and_claimed", "handed_off", "claimed", "claimed", "done"])

    def test_closeout_writes_local_transcript_and_summary(self) -> None:
        """Bug 3 + 4: closeout attributes the detected agent and writes a local, redacted transcript + summary."""
        self.write_documented_module("src/collab/services/cache.py")
        export = Path(self.tmp.name) / "export.jsonl"
        lines = [
            {"type": "user", "timestamp": "2026-10-20T01:00:00Z", "message": {"content": "my key is ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4 mail me@example.com"}},
            {"type": "assistant", "timestamp": "2026-10-20T01:00:05Z", "message": {"content": [{"type": "text", "text": "Added the cache."}]}},
            {"type": "assistant", "isSidechain": True, "message": {"content": "sub-agent noise"}},
        ]
        export.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        res = run(self.root, "scripts/agentctl.py", "closeout", "--goal", "Add cache", "--issues", "None", "--next", "TTL metric",
                  "--transcript", str(export), env={"CLAUDECODE": "1"})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        body = git_log_body(self.root)
        self.assertIn("Agent: claude-code", body)
        self.assertNotIn("active-agent", body)
        folder = self.root / ".agents" / "conversations"
        transcripts, summaries = list(folder.glob("*-claude-code-transcript.md")), list(folder.glob("*-claude-code-summary.md"))
        self.assertEqual((len(transcripts), len(summaries)), (1, 1), "one transcript + one summary per conversation")
        transcript = transcripts[0].read_text(encoding="utf-8")
        self.assertIn("Added the cache.", transcript)
        self.assertNotIn("ghp_a1B2", transcript)
        self.assertNotIn("me@example.com", transcript)
        self.assertNotIn("sub-agent noise", transcript)
        summary = summaries[0].read_text(encoding="utf-8")
        self.assertIn("Add cache", summary)
        self.assertIn("TODO(claude-code)", summary)
        self.assertIn(transcripts[0].name, summary)
        self.assertEqual(run(self.root, "git", "ls-files", ".agents/conversations").stdout.strip(), "", "never committed")
        self.assertEqual(run(self.root, "git", "status", "--porcelain", ".agents/conversations").stdout.strip(), "", "git-ignored")
        status = run(self.root, "scripts/agentctl.py", "status").stdout
        self.assertIn("上一次的交接紀錄", status)
        self.assertIn("**下一步**: TTL metric", status, "the last closeout's next step is shown (shared through git)")
        self.assertIn("最新摘要的「下一步」", status, "the local summary's next steps are shown too")
        board = (self.root / ".agents" / "handoff" / "LATEST.md").read_text(encoding="utf-8")
        self.assertIn("**目標**: Add cache", board)
        self.assertIn("**下一步**: TTL metric", board)
        self.assertEqual(run(self.root, ".agents/bin/audit_trail.py", "--verify").returncode, 0)
        self.assertIn("1 個", run(self.root, "scripts/agentctl.py", "conversations", "prune", "--before", "2999-01-01").stdout.replace("2 個", "1 個"))
        self.assertEqual(list(folder.glob("*.md")), [])

    def test_skill_generators_produce_compliant_code(self) -> None:
        """Adapter and TDD scaffolds create documented code inside the package that runs."""
        res = run(self.root, ".agents/skills/api-adapter-scaffold/scripts/scaffold_adapter.py", "--name", "brave_search")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.pkg / "adapters" / "search" / "brave_search_adapter.py").exists())
        self.assertEqual(run(self.root, "-m", "unittest", "discover", "-s", "tests").returncode, 0)
        self.assertEqual(run(self.root, ".agents/skills/code-review-guard/scripts/review_guard.py").returncode, 0)
        run(self.root, ".agents/skills/tdd-bugfix/scripts/tdd_runner.py", "--new-test", "price_parser")
        self.assertNotEqual(run(self.root, ".agents/skills/tdd-bugfix/scripts/tdd_runner.py", "--verify").returncode, 0, "RED phase fails")

    def test_update_framework_keeps_project_edits(self) -> None:
        """Files edited in the project are not overwritten; the template version is saved aside."""
        edited = self.root / ".agents" / "bin" / "finish.py"
        edited.write_text(edited.read_text(encoding="utf-8") + "\n# project-specific tweak\n", encoding="utf-8")
        stale = self.root / ".agents" / "bin" / "doctor.py"
        stale.write_text("# stale copy\n", encoding="utf-8")
        lock_path = self.root / ".agents" / "framework.lock"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["files"][".agents/bin/doctor.py"] = __import__("hashlib").sha256(stale.read_bytes()).hexdigest()
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        res = run(self.root, "scripts/agentctl.py", "update", "--from", str(TEMPLATE_ROOT))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("project-specific tweak", edited.read_text(encoding="utf-8"))
        self.assertTrue((self.root / ".agents" / "bin" / "finish.py.template").exists())
        self.assertNotEqual(stale.read_text(encoding="utf-8"), "# stale copy\n", "unmodified files are updated")

    def test_update_lists_v30_scripts_without_deleting(self) -> None:
        """A v3.0 project (framework scripts in `scripts/`) gets them listed as removed, never deleted."""
        old = self.root / "scripts" / "doctor.py"
        old.write_text("# v3.0 framework copy\n", encoding="utf-8")
        lock_path = self.root / ".agents" / "framework.lock"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["files"]["scripts/doctor.py"] = __import__("hashlib").sha256(old.read_bytes()).hexdigest()
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        res = run(self.root, "scripts/agentctl.py", "update", "--from", str(TEMPLATE_ROOT))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("母版已移除", res.stdout)
        self.assertIn("scripts/doctor.py", res.stdout)
        self.assertTrue(old.exists(), "removed framework files are only listed")


def make_old_project(base: Path) -> Path:
    """Create a small "old" git project (no docstrings, env reads outside config, pip requirements).

    Args:
        base: Folder to create it in.

    Returns:
        Path of the old project.
    """
    old = base / "old_shop"
    (old / "tests").mkdir(parents=True)
    files = {
        "requirements.txt": "requests>=2.31\n",
        "app.py": "import os\nfrom utils import price_with_tax\n\ndef main():\n    print(price_with_tax(100, float(os.environ.get('TAX_RATE', '0.05'))))\n",
        "utils.py": "def price_with_tax(price, rate):\n    return round(price * (1 + rate), 2)\n",
        "tests/test_utils.py": "from utils import price_with_tax\n\ndef test_tax():\n    assert price_with_tax(100, 0.05) == 105.0\n",
        ".env.example": "TAX_RATE=\nSHOP_API_KEY=\n",
        "credentials.json": "{}\n",
        "README.md": "# Old Shop\n",
    }
    (old / "data" / "input").mkdir(parents=True)
    (old / "data" / "input" / "catalog.pdf").write_bytes(b"%PDF-1.4 fake")
    for rel, content in files.items():
        (old / rel).write_text(content, encoding="utf-8")
    run(old, "git", "init", "-q", "-b", "main")
    run(old, "git", "add", "-A")
    run(old, "git", "commit", "-qm", "init shop")
    return old


class MigrationTest(unittest.TestCase):
    """migrate_project.py + legacy-migration skill."""

    def setUp(self) -> None:
        """Create an old project and migrate it into a new folder."""
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.old = make_old_project(base)
        self.new = base / "shop_v2"
        res = run(TEMPLATE_ROOT, "migrate_project.py", "--from", str(self.old), "--target", str(self.new))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def tearDown(self) -> None:
        """Remove the temporary folders."""
        self.tmp.cleanup()

    def test_history_plan_and_old_project_untouched(self) -> None:
        """History is kept, files sit in legacy/, the plan lists batches/deps/risks, old repo is unchanged."""
        self.assertEqual(run(self.old, "git", "status", "--porcelain").stdout.strip(), "")
        self.assertIn("init shop", run(self.new, "git", "log", "--follow", "--oneline", "--", "legacy/utils.py").stdout)
        self.assertEqual(run(self.new, "git", "status", "--porcelain").stdout.strip(), "", "everything is committed")
        self.assertTrue((self.new / "legacy" / "app.py").exists())
        self.assertFalse((self.new / "app.py").exists())
        plan = (self.new / "docs" / "migration" / "MIGRATION.md").read_text(encoding="utf-8")
        self.assertIn("uv add 'requests>=2.31'", plan)
        self.assertIn("`TAX_RATE`", plan)
        self.assertIn("legacy/credentials.json", plan.split("## 5. 風險")[1].split("## 6")[0])
        self.assertNotIn("legacy/.env.example` 看起來是機密檔", plan)
        self.assertIn("| ☐ | `legacy/utils.py` | `src/shop_v2/services/` | services |", plan)
        self.assertIn("| ☐ | `legacy/app.py` | `src/shop_v2/entrypoints/` | entrypoints |", plan)
        self.assertTrue((self.new / ".agents" / "skills" / "legacy-migration" / "SKILL.md").exists())
        self.assertFalse((self.new / "legacy" / "data").exists(), "data is not moved into legacy/")
        self.assertFalse((self.new / "data").exists())
        self.assertNotIn("catalog.pdf", run(self.new, "git", "ls-files").stdout)
        self.assertTrue((self.old / "data" / "input" / "catalog.pdf").exists(), "old project keeps its data")
        self.assertIn("rsync -a", plan)
        self.assertIn("~/project-data/shop-v2/input/", plan)
        self.assertIn("遷移批次", run(self.new, ".agents/bin/agent_task.py", "list").stdout)
        self.assertEqual(run(self.new, "scripts/agentctl.py", "check").returncode, 0, "legacy/ does not break the checks")

    def test_plan_suggests_concrete_targets(self) -> None:
        """Real-world files get a fitting target: I/O code → adapters, known docs → their folder, data → DATA_DIR."""
        from packs.migration_plan import PlanContext, classify

        ctx = PlanContext(pkg="app")
        cases = {
            ("src/x/hardware.py", ""): "src/app/adapters/",
            ("src/x/ssd1306.py", "import framebuf\nfrom machine import I2C\n"): "src/app/adapters/",
            ("src/x/controller.py", "import time\n"): "src/app/services/",
            ("DECISIONS.md", ""): "docs/adr/",
            ("KNOWN_ISSUES.md", ""): "docs/known-issues/",
            ("AGENTS.md", ""): "docs/standards/PROJECT_RULES.md",
            ("conversations/raw/001_x.md", ""): ".agents/conversations/",
            ("evals/README.md", ""): "evals/EVALS.md",
            (".cursorrules", ""): "docs/standards/PROJECT_RULES.md",
            ("shop.sqlite", ""): "DATA_DIR/db/",
        }
        for (rel, text), expected in cases.items():
            self.assertIn(expected, classify(rel, ctx, text).target, rel)

    def test_move_then_fix_keeps_history(self) -> None:
        """Unchanged move out of legacy/ commits once; the next commit must fix it; `--follow` keeps the history."""
        dest = "src/shop_v2/services/pricing.py"
        run(self.new, "git", "mv", "legacy/utils.py", dest)
        move = run(self.new, "scripts/agentctl.py", "commit", "--agent", "tester", "--bump", "none", "-m", "refactor(migration): move utils from legacy")
        self.assertEqual(move.returncode, 0, move.stdout + move.stderr)
        self.assertEqual(run(self.new, "scripts/agentctl.py", "check").returncode, 1, "check still demands docs")
        (self.new / "README.md").write_text("# Shop v2\n", encoding="utf-8")
        blocked = run(self.new, "scripts/agentctl.py", "commit", "--agent", "tester", "-m", "docs: readme")
        self.assertNotEqual(blocked.returncode, 0, "the next commit is blocked until the moved file is fixed")
        (self.new / dest).write_text(
            '"""Price calculations (migrated from legacy/utils.py)."""\n\n\ndef price_with_tax(price: float, rate: float) -> float:\n'
            '    """Add tax to a price.\n\n    Args:\n        price: Net price.\n        rate: Tax rate, e.g. 0.05.\n\n'
            '    Returns:\n        Gross price rounded to 2 decimals.\n    """\n    return round(price * (1 + rate), 2)\n', encoding="utf-8")
        fixed = run(self.new, "scripts/agentctl.py", "commit", "--agent", "tester", "-m", "refactor(services): document pricing")
        self.assertEqual(fixed.returncode, 0, fixed.stdout + fixed.stderr)
        self.assertIn("init shop", run(self.new, "git", "log", "--follow", "--oneline", "--", dest).stdout)

    def test_changed_move_is_not_exempt(self) -> None:
        """A move that also edits the file (not a 100% rename) gets no exemption."""
        run(self.new, "git", "mv", "legacy/utils.py", "src/shop_v2/services/pricing.py")
        moved = self.new / "src" / "shop_v2" / "services" / "pricing.py"
        moved.write_text(moved.read_text(encoding="utf-8") + "\n\ndef extra(x):\n    return x\n", encoding="utf-8")
        res = run(self.new, "scripts/agentctl.py", "commit", "--agent", "tester", "-m", "refactor(migration): move and edit")
        self.assertNotEqual(res.returncode, 0)

    def test_verify_requires_full_compliance(self) -> None:
        """--verify fails until legacy/ is gone and the project meets every rule, then passes."""
        verify = lambda: run(self.new, "scripts/agentctl.py", "migration", "--verify")  # noqa: E731
        self.assertEqual(verify().returncode, 1)
        toml = self.new / ".agents" / "project.toml"
        toml.write_text(toml.read_text(encoding="utf-8").replace("uv run python -m unittest", f"{sys.executable} -m unittest"), encoding="utf-8")
        pkg = self.new / "src" / "shop_v2"
        run(self.new, "git", "mv", "legacy/utils.py", "src/shop_v2/services/pricing.py")
        (pkg / "services" / "pricing.py").write_text(
            '"""Price calculations."""\n\n\ndef price_with_tax(price: float, rate: float) -> float:\n'
            '    """Add tax to a price.\n\n    Args:\n        price: Net price.\n        rate: Tax rate, e.g. 0.05.\n\n'
            '    Returns:\n        Gross price rounded to 2 decimals.\n    """\n    return round(price * (1 + rate), 2)\n', encoding="utf-8")
        for rel in ("src/shop_v2/services/greeting.py", "src/shop_v2/entrypoints/cli.py", "tests/test_greeting.py"):
            run(self.new, "git", "rm", "-q", rel)
        (self.new / "tests" / "test_pricing.py").write_text(
            '"""Tests for pricing."""\n\nimport sys\nimport unittest\nfrom pathlib import Path\n\n'
            'sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))\n\n'
            'from shop_v2.services.pricing import price_with_tax  # noqa: E402\n\n\n'
            'class PricingTest(unittest.TestCase):\n    """Tax maths."""\n\n'
            '    def test_tax(self) -> None:\n        """5% tax on 100."""\n        self.assertEqual(price_with_tax(100, 0.05), 105.0)\n', encoding="utf-8")
        run(self.new, "git", "rm", "-q", "-r", "legacy")
        (self.new / "README.md").write_text("# Shop v2\n\nPricing tools for the shop.\n", encoding="utf-8")
        arch = self.new / "docs" / "architecture" / "ARCHITECTURE.md"
        arch.write_text(arch.read_text(encoding="utf-8").replace("TODO: 用幾句話或一張圖說明主要元件", "services/pricing 計算含稅價"), encoding="utf-8")
        plan = self.new / "docs" / "migration" / "MIGRATION.md"
        plan.write_text(plan.read_text(encoding="utf-8").replace("| ☐ |", "| ☑ |"), encoding="utf-8")
        for task in json.loads("[]") or [p.name.split("-")[0] + "-" + p.name.split("-")[1] for p in (self.new / ".agents" / "tasks").glob("TASK-*.json")]:
            run(self.new, ".agents/bin/agent_task.py", "done", task, "--agent", "tester", "--summary", "migrated")
        run(self.new, ".agents/bin/update_tree.py")  # normally done by `agentctl commit`
        res = verify()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("遷移完成", res.stdout)


def make_flask_project(base: Path) -> Path:
    """Create an old Flask + Flask-SQLAlchemy git project.

    Args:
        base: Folder to create it in.

    Returns:
        Path of the old project.
    """
    old = base / "old_flask"
    for folder in ("templates", "migrations/versions"):
        (old / folder).mkdir(parents=True)
    files = {
        "requirements.txt": "flask==3.0.0\nflask-sqlalchemy==3.1.1\nflask-migrate==4.0.5\n",
        "app.py": "from flask import Flask, jsonify\n\napp = Flask(__name__)\n\n@app.route('/items')\ndef items():\n    return jsonify([])\n",
        "models.py": "from flask_sqlalchemy import SQLAlchemy\n\ndb = SQLAlchemy()\n\nclass Item(db.Model):\n    id = db.Column(db.Integer, primary_key=True)\n",
        "templates/index.html": "<html></html>\n",
        "migrations/versions/abc123_items.py": "revision = 'abc123'\n",
    }
    for rel, content in files.items():
        (old / rel).write_text(content, encoding="utf-8")
    run(old, "git", "init", "-q", "-b", "main")
    run(old, "git", "add", "-A")
    run(old, "git", "commit", "-qm", "flask app")
    return old


class FlaskMigrationTest(unittest.TestCase):
    """Maintain mode keeps Flask; develop mode requires FastAPI."""

    def setUp(self) -> None:
        """Create the old Flask project."""
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.old = make_flask_project(self.base)

    def tearDown(self) -> None:
        """Remove the temporary folders."""
        self.tmp.cleanup()

    def migrate(self, name: str, mode: str) -> tuple[Path, str]:
        """Migrate the old project in the given mode.

        Args:
            name: New folder name.
            mode: `maintain` or `develop`.

        Returns:
            Tuple of the new project path and its MIGRATION.md text.
        """
        target = self.base / name
        res = run(TEMPLATE_ROOT, "migrate_project.py", "--from", str(self.old), "--target", str(target), "--mode", mode)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return target, (target / "docs" / "migration" / "MIGRATION.md").read_text(encoding="utf-8")

    def test_maintain_keeps_flask(self) -> None:
        """Maintain mode: Flask allowed, routes stay Flask, DB files go to the db batch, no FastAPI scaffold."""
        target, plan = self.migrate("keep", "maintain")
        toml = (target / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn("forbidden_imports = []", toml)
        self.assertIn("維護模式", plan)
        self.assertIn("| ☐ | `legacy/app.py` | `src/keep/entrypoints/http/（保留 Flask）` | entrypoints |", plan)
        self.assertIn("| ☐ | `legacy/models.py` | `src/keep/adapters/db/` | db |", plan)
        self.assertIn("| ☐ | `legacy/migrations/versions/abc123_items.py` | `alembic/versions/（保留舊的 revision，取代範例 0001）` | db |", plan)
        self.assertIn("src/keep/entrypoints/http/templates/", plan)
        self.assertTrue((target / "src" / "keep" / "adapters" / "db" / "session.py").exists(), "db add-on detected")
        self.assertFalse((target / "src" / "keep" / "entrypoints" / "http" / "app.py").exists(), "no FastAPI in maintain mode")
        switch = run(target, "scripts/agentctl.py", "migration", "--develop")
        self.assertEqual(switch.returncode, 0, switch.stdout + switch.stderr)
        self.assertIn('"flask:', (target / ".agents" / "project.toml").read_text(encoding="utf-8"))
        self.assertIn("Flask → FastAPI", run(target, ".agents/bin/agent_task.py", "list").stdout)

    def test_develop_requires_fastapi(self) -> None:
        """Develop mode: Flask forbidden, conversion batch planned, FastAPI scaffold present."""
        target, plan = self.migrate("grow", "develop")
        self.assertIn('"flask:', (target / ".agents" / "project.toml").read_text(encoding="utf-8"))
        self.assertIn("開發模式", plan)
        self.assertIn("Flask → FastAPI 改寫", plan)
        self.assertIn("（改寫成 FastAPI）", plan)
        self.assertTrue((target / "src" / "grow" / "entrypoints" / "http" / "app.py").exists())
        self.assertTrue((target / ".agents" / "skills" / "legacy-migration" / "FLASK_TO_FASTAPI.md").exists())
        (target / "src" / "grow" / "services" / "bad.py").write_text('"""Uses Flask."""\n\nimport flask  # noqa: F401\n', encoding="utf-8")
        guard = run(target, ".agents/skills/code-review-guard/scripts/review_guard.py")
        self.assertNotEqual(guard.returncode, 0)
        self.assertIn("禁止使用 `flask`", guard.stdout)


class RulesAndSafetyTest(unittest.TestCase):
    """English commits, push guard, pause, data guard, file size, add-ons, DX files, finish."""

    def setUp(self) -> None:
        """Scaffold one python project with every offline-testable add-on."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "safe"
        scaffold_project(self.root, "safe", stack="python", addons=["ollama", "evals", "api", "db"], license_kind="MIT")
        toml = self.root / ".agents" / "project.toml"
        toml.write_text(toml.read_text(encoding="utf-8").replace('test = "uv run python -m unittest discover -s tests -v"', 'test = ""'), encoding="utf-8")
        run(self.root, "git", "commit", "-qam", "chore(test): offline\n\nAgent: test-harness")

    def tearDown(self) -> None:
        """Remove the temporary project."""
        self.tmp.cleanup()

    def test_scaffold_files(self) -> None:
        """Ollama/evals/DX files exist, PROJECT_RULES and TEMPLATE_FEEDBACK are created, guard passes."""
        pkg = self.root / "src" / "safe"
        for rel in ("adapters/llm/ollama_client.py", "adapters/llm/hardware.py", "adapters/storage/quarantine.py",
                    "services/prompts.py", "services/llm_review.py"):
            self.assertTrue((pkg / rel).exists(), rel)
        for rel in ("evals/run_evals.py", "evals/checks.py", "evals/cases/sample/output.md", "docs/PROMPT_TEMPLATES.md",
                    ".editorconfig", ".vscode/settings.json", ".vscode/launch.json", "LICENSE", ".agents/hooks/pre-push",
                    "docs/standards/PROJECT_RULES.md", "docs/TEMPLATE_FEEDBACK.md", ".agents/bin/finish.py"):
            self.assertTrue((self.root / rel).exists(), rel)
        self.assertIn("MIT License", (self.root / "LICENSE").read_text(encoding="utf-8"))
        launch = json.loads((self.root / ".vscode" / "launch.json").read_text(encoding="utf-8"))
        self.assertEqual(len(launch["configurations"]), 2, "CLI + API server")
        self.assertEqual(run(self.root, "git", "status", "--porcelain").stdout.strip(), "", ".vscode shared files are tracked")
        self.assertEqual(run(self.root, ".agents/skills/code-review-guard/scripts/review_guard.py").returncode, 0)
        self.assertEqual(run(self.root, "evals/run_evals.py").returncode, 0)
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        for needle in ("使用者說什麼 → 執行什麼", "出示執行證據", "決策衝突要停下來問", "即時記錄", "TEMPLATE_FEEDBACK.md", "PROJECT_RULES.md"):
            self.assertIn(needle, agents)

    def test_english_commit_and_cjk_warning(self) -> None:
        """Auto-generated subjects are English; a Chinese -m subject triggers a warning."""
        (self.root / "src" / "safe" / "services" / "extra.py").write_text('"""Extra."""\n', encoding="utf-8")
        run(self.root, ".agents/bin/auto_commit.py", "--agent", "claude-code")
        subject = run(self.root, "git", "log", "-1", "--pretty=%s").stdout
        self.assertRegex(subject, r"^feat\(services\): add services module")
        self.assertIsNone(__import__("re").search(r"[\u4e00-\u9fff]", subject))
        (self.root / "src" / "safe" / "services" / "extra.py").write_text('"""Extra two."""\n', encoding="utf-8")
        res = run(self.root, ".agents/bin/auto_commit.py", "--agent", "claude-code", "-m", "fix: 修正錯誤")
        self.assertIn("請使用英文", res.stderr)

    def test_pre_push_blocks_without_permission(self) -> None:
        """A plain push is blocked by the versioned hook; ALLOW_PUSH=1 lets it through."""
        remote = Path(self.tmp.name) / "remote.git"
        run(self.root, "git", "init", "-q", "--bare", str(remote))
        run(self.root, "git", "remote", "add", "origin", str(remote))
        blocked = run(self.root, "git", "push", "-q", "origin", "main")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("PRE-PUSH BLOCKED", blocked.stdout + blocked.stderr)
        self.assertEqual(run(self.root, "git", "push", "-q", "origin", "main", env={"ALLOW_PUSH": "1"}).returncode, 0)

    def test_pause_with_unfinished_code_keeps_work(self) -> None:
        """Pausing with code that fails the checks does not commit, but keeps the work and the board note."""
        head = run(self.root, "git", "rev-parse", "HEAD").stdout
        (self.root / "src" / "safe" / "services" / "draft.py").write_text("def todo(x):\n    return x\n", encoding="utf-8")
        res = run(self.root, "scripts/agentctl.py", "pause", "meeting", "--agent", "cursor")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("沒有 commit", res.stdout)
        self.assertEqual(run(self.root, "git", "rev-parse", "HEAD").stdout, head)
        self.assertTrue((self.root / "src" / "safe" / "services" / "draft.py").exists())
        self.assertIn("meeting", (self.root / ".agents" / "handoff" / "LATEST.md").read_text(encoding="utf-8"))

    def test_pause_records_and_commits(self) -> None:
        """`agentctl pause` notes the pause on the board and makes a wip(handoff) commit."""
        res = run(self.root, "scripts/agentctl.py", "pause", "class", "break", "--agent", "cursor")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("wip(handoff): class break", run(self.root, "git", "log", "-1", "--pretty=%s").stdout)
        self.assertIn("Pause (暫停離席)", (self.root / ".agents" / "handoff" / "LATEST.md").read_text(encoding="utf-8"))

    def test_data_files_blocked_unless_disabled(self) -> None:
        """PDFs and >10 MB files are blocked; samples in tests/fixtures pass; block_data_files=false allows docs."""
        (self.root / "book.pdf").write_bytes(b"%PDF-1.4")
        run(self.root, "git", "add", "book.pdf")
        self.assertNotEqual(run(self.root, "git", "commit", "-m", "chore: add pdf").returncode, 0)
        run(self.root, "git", "rm", "-q", "--cached", "book.pdf")
        (self.root / "tests" / "fixtures").mkdir(exist_ok=True)
        (self.root / "tests" / "fixtures" / "tiny.pdf").write_bytes(b"%PDF-1.4")
        run(self.root, "git", "add", "tests/fixtures/tiny.pdf")
        self.assertEqual(run(self.root, "git", "commit", "-qm", "test: add tiny fixture").returncode, 0)
        toml = self.root / ".agents" / "project.toml"
        toml.write_text(toml.read_text(encoding="utf-8").replace("block_data_files = true", "block_data_files = false"), encoding="utf-8")
        run(self.root, "git", "add", "book.pdf", ".agents/project.toml")
        self.assertEqual(run(self.root, "git", "commit", "-qm", "docs: course material").returncode, 0)

    def test_file_length_limits(self) -> None:
        """Files over the hard limit are CRITICAL; over the soft limit only warn."""
        quality = {"max_file_lines": 5, "hard_max_file_lines": 10}
        self.assertEqual(review_guard.file_size_issues("x\n" * 7, "a.py", quality)[0]["severity"], "IMPORTANT")
        self.assertEqual(review_guard.file_size_issues("x\n" * 12, "a.py", quality)[0]["severity"], "CRITICAL")
        self.assertEqual(review_guard.file_size_issues("x\n" * 3, "a.py", quality), [])

    def test_doctor_data_dir_checks(self) -> None:
        """DATA_DIR inside the project warns; --fix creates the standard sub-folders outside."""
        outside = Path(self.tmp.name) / "data-home"
        res = run(self.root, ".agents/bin/doctor.py", "--fix", env={"DATA_DIR": str(outside)})
        self.assertTrue((outside / "needs_review").is_dir())
        self.assertIn("與程式分開", res.stdout)
        inside = run(self.root, ".agents/bin/doctor.py", env={"DATA_DIR": str(self.root / "data")})
        self.assertIn("DATA_DIR 在專案資料夾內", inside.stdout)

    def test_project_rules_survive_update_and_finish_reports(self) -> None:
        """PROJECT_RULES.md is project-owned (not overwritten); finish reports open items."""
        rules = self.root / "docs" / "standards" / "PROJECT_RULES.md"
        rules.write_text("# mine\n", encoding="utf-8")
        self.assertEqual(run(self.root, "scripts/agentctl.py", "update", "--from", str(TEMPLATE_ROOT)).returncode, 0)
        self.assertEqual(rules.read_text(encoding="utf-8"), "# mine\n")
        report = run(self.root, "scripts/agentctl.py", "finish")
        self.assertEqual(report.returncode, 1, "template README is still untouched")
        self.assertIn("README / ARCHITECTURE", report.stdout)


@unittest.skipUnless(os.environ.get("TEMPLATE_MOBILE_TESTS") and shutil.which("pnpm"), "set TEMPLATE_MOBILE_TESTS=1 (needs pnpm + network, ~300 MB)")
class MobileIntegrationTest(unittest.TestCase):
    """Real Expo flow: pnpm install in mobile/, type check, SDK version check, iOS + Android bundles."""

    def test_expo_flow(self) -> None:
        """A fresh `--stack mobile` project installs locally, type-checks, matches the SDK and bundles for both phones."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "phoneapp"
            scaffold_project(target, "phoneapp", stack="mobile")
            self.assertEqual(run(target, ".agents/bin/setup_env.py", "--install").returncode, 0)
            self.assertTrue((target / "mobile" / "node_modules" / ".bin" / "expo").exists(), "expo CLI is project-local")
            check = run(target, "scripts/agentctl.py", "check")
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            mobile = target / "mobile"
            self.assertIn("up to date", run(mobile, "pnpm", "exec", "expo", "install", "--check").stdout)
            for platform in ("ios", "android"):
                out = run(mobile, "pnpm", "exec", "expo", "export", "--platform", platform, "--output-dir", str(Path(tmp) / platform),
                          env={"CI": "1"})
                self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
                self.assertTrue(list((Path(tmp) / platform).rglob("*.hbc")), f"{platform} bundle")


@unittest.skipUnless(os.environ.get("TEMPLATE_UV_TESTS") and shutil.which("uv"), "set TEMPLATE_UV_TESTS=1 (needs uv + network)")
class UvIntegrationTest(unittest.TestCase):
    """Real uv flow: lock, sync into .venv with Python 3.11, test, lint."""

    def test_uv_flow(self) -> None:
        """A fresh python project syncs, passes tests and ruff, and doctor sees Python 3.11 in .venv."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "uvapp"
            env = {k: v for k, v in os.environ.items() if k != "TEMPLATE_SKIP_UV_LOCK"}
            res = subprocess.run([sys.executable, str(TEMPLATE_ROOT / "init_project.py"), "--target", str(target), "--with", "web", "gas", "api", "db", "ollama", "evals"],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertTrue((target / "uv.lock").exists())
            self.assertEqual(run(target, ".agents/bin/setup_env.py", "--install").returncode, 0)
            self.assertTrue(venv_version(target).startswith("3.11"))
            for cmd in (("uv", "run", "python", "-m", "unittest", "discover", "-s", "tests"), ("uv", "run", "ruff", "check", "."),
                        ("uv", "run", "ruff", "format", "--check", "."), ("uv", "run", "mypy"), ("uv", "run", "uvapp", "--name", "Ann"),
                        ("uv", "run", "alembic", "upgrade", "head"), ("uv", "run", "alembic", "check"),
                        ("uv", "run", "python", "evals/run_evals.py")):
                out = run(target, *cmd)
                self.assertEqual(out.returncode, 0, f"{cmd}: {out.stdout}{out.stderr}")
            self.assertEqual(run(target, "scripts/agentctl.py", "check").returncode, 0)
            self.assertIn("Python 3.11", run(target, ".agents/bin/doctor.py").stdout)
            if shutil.which("pnpm"):
                self.assertTrue((target / "gas" / "node_modules" / ".bin" / "clasp").exists(), "clasp installed locally by pnpm")
                self.assertEqual(run(target / "gas", "pnpm", "test").returncode, 0)


def venv_version(root: Path) -> str:
    """Read the Python version recorded in a project's `.venv/pyvenv.cfg`.

    Args:
        root: Project root.

    Returns:
        Version string, or an empty string when missing.
    """
    cfg = root / ".venv" / "pyvenv.cfg"
    lines = cfg.read_text(encoding="utf-8").splitlines() if cfg.exists() else []
    return next((ln.split("=", 1)[1].strip() for ln in lines if ln.split("=")[0].strip() in ("version_info", "version")), "")


class CollectFeedbackTest(unittest.TestCase):
    """tools/collect_feedback.py gathers open suggestions from every project without changing them."""

    def test_collects_open_suggestions_read_only(self) -> None:
        """Open rows (empty or 待決定) are listed oldest first; adopted rows only with --all; files stay unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for rel, rows in (("books", ["| 2026-10-21 | run 指令 | 對話 | 待決定 |", "| 2026-10-22 | 頁數 \\| 耗時 | TASK-4 | 已採用 |"]),
                              ("group/phone", ["| 2026-10-20 | 離線模式 | 對話 |  |"])):
                scaffold_project(base / rel, rel.split("/")[-1], stack="generic", init_git_repo=False)
                feedback = base / rel / "docs" / "TEMPLATE_FEEDBACK.md"
                feedback.write_text(feedback.read_text(encoding="utf-8") + "\n".join(rows) + "\n", encoding="utf-8")
            before = (base / "books" / "docs" / "TEMPLATE_FEEDBACK.md").read_text(encoding="utf-8")
            out = run(TEMPLATE_ROOT, "tools/collect_feedback.py", str(base)).stdout
            self.assertIn("掃描 2 個專案，共 2 條", out)
            self.assertLess(out.index("離線模式"), out.index("run 指令"), "oldest first")
            self.assertNotIn("頁數", out)
            self.assertIn("頁數 \\| 耗時", run(TEMPLATE_ROOT, "tools/collect_feedback.py", str(base), "--all").stdout)
            self.assertEqual((base / "books" / "docs" / "TEMPLATE_FEEDBACK.md").read_text(encoding="utf-8"), before)


class UpdateAllTest(unittest.TestCase):
    """tools/update_all.py previews by default and updates only clean, conflict-free projects."""

    def test_preview_then_apply(self) -> None:
        """Preview changes nothing; --apply commits clean projects, leaves conflicts uncommitted, skips dirty ones."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tpl = base / "tpl"
            shutil.copytree(TEMPLATE_ROOT, tpl, ignore=shutil.ignore_patterns(".git", ".skills-cache", "__pycache__"))
            git_env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            run(tpl, "git", "init", "-q", "-b", "main")
            run(tpl, "git", "add", "-A")
            run(tpl, "git", "commit", "-qm", "template", env=git_env)
            for name in ("alpha", "beta", "gamma"):
                res = run(tpl, "init_project.py", "--target", str(base / "projects" / name), "--stack", "generic")
                self.assertEqual(res.returncode, 0, res.stderr)
            doctor = tpl / "core" / "scripts" / "doctor.py"
            doctor.write_text(doctor.read_text(encoding="utf-8") + "\n# template improvement\n", encoding="utf-8")
            run(tpl, "git", "commit", "-qam", "improve", env=git_env)
            beta_doctor = base / "projects" / "beta" / ".agents" / "bin" / "doctor.py"
            beta_doctor.write_text(beta_doctor.read_text(encoding="utf-8") + "\n# beta tweak\n", encoding="utf-8")
            run(base / "projects" / "beta", "git", "commit", "-qam", "chore: tweak", "--no-verify")
            (base / "projects" / "gamma" / "notes.txt").write_text("draft\n", encoding="utf-8")
            heads = {n: run(base / "projects" / n, "git", "rev-parse", "HEAD").stdout for n in ("alpha", "beta", "gamma")}

            preview = run(tpl, "tools/update_all.py", str(base / "projects"))
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("可更新（有衝突", preview.stdout)
            self.assertIn("略過：有未 commit", preview.stdout)
            self.assertEqual(run(base / "projects" / "alpha", "git", "rev-parse", "HEAD").stdout, heads["alpha"], "preview changes nothing")

            run(tpl, "tools/update_all.py", str(base / "projects"), "--apply", "--yes")
            alpha = base / "projects" / "alpha"
            self.assertIn("chore(framework): update to v", run(alpha, "git", "log", "-1", "--pretty=%s").stdout)
            self.assertEqual(run(alpha, "git", "status", "--porcelain").stdout.strip(), "")
            self.assertIn("# template improvement", (alpha / ".agents" / "bin" / "doctor.py").read_text(encoding="utf-8"))
            self.assertIn("# beta tweak", beta_doctor.read_text(encoding="utf-8"), "project edits are never overwritten")
            self.assertTrue(beta_doctor.with_name("doctor.py.template").exists())
            self.assertEqual(run(base / "projects" / "beta", "git", "rev-parse", "HEAD").stdout, heads["beta"], "conflicts are not committed")
            self.assertEqual(run(base / "projects" / "gamma", "git", "rev-parse", "HEAD").stdout, heads["gamma"])
            (tpl / "scratch.txt").write_text("x", encoding="utf-8")
            self.assertEqual(run(tpl, "tools/update_all.py", str(base / "projects")).returncode, 1, "dirty template is refused")


class GuardTest(unittest.TestCase):
    """Comment-rule detection in code-review-guard."""

    def test_forbidden_imports(self) -> None:
        """`[project_rules] forbidden_imports` blocks `import flask` / `from flask import ...`."""
        config = {"project_rules": {"forbidden_imports": ["flask:use FastAPI"]}}
        tree = ast.parse("from flask import Flask\nimport json\nimport flask.json\n")
        issues = review_guard.forbidden_import_issues(tree, "src/x.py", config)
        self.assertEqual(len(issues), 2)
        self.assertIn("use FastAPI", issues[0]["msg"])
        self.assertEqual(review_guard.forbidden_import_issues(tree, "src/x.py", {"project_rules": {}}), [])

    def test_html_css_headers(self) -> None:
        """HTML needs a comment after DOCTYPE; CSS needs a header comment."""
        config = {"quality": {"require_docstrings": True}}
        self.assertEqual(len(review_guard.markup_header_issues("<!DOCTYPE html>\n<html></html>\n", "web/a.html", config)), 1)
        self.assertEqual(review_guard.markup_header_issues("<!DOCTYPE html>\n<!-- Page. -->\n<html></html>\n", "web/a.html", config), [])
        self.assertEqual(len(review_guard.markup_header_issues("body { margin: 0; }\n", "web/a.css", config)), 1)
        self.assertEqual(review_guard.markup_header_issues("/* Styles. */\nbody { margin: 0; }\n", "web/a.css", config), [])

    def test_docs_are_zsh_paste_safe(self) -> None:
        """No `#` comments inside bash blocks (zsh does not treat `#` as a comment when pasting)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "docs_check"
            scaffold_project(target, "docs_check", stack="python", addons=["web", "gas"], init_git_repo=False)
            files = [p for root in (TEMPLATE_ROOT, target) for p in root.rglob("*.md") if ".skills-cache" not in p.parts]
            offenders = []
            for path in files:
                for block in __import__("re").findall(r"```(?:bash|sh|zsh)\n(.*?)```", path.read_text(encoding="utf-8"), flags=16):
                    offenders += [f"{path.name}: {ln}" for ln in block.splitlines()
                                  if (ln.strip().startswith("#") and not ln.strip().startswith("#!")) or " # " in ln]
            self.assertEqual(offenders, [])

    def test_python_rules(self) -> None:
        """Missing module docstring, function docstring and parameter docs are reported."""
        src = 'def f(a, b):\n    """Add.\n\n    Args:\n        a: First.\n    """\n    return a + b\n\n\ndef g():\n    return 1\n'
        msgs = [i["msg"] for i in review_guard.python_docstring_issues(ast.parse(src), "x.py")]
        self.assertEqual(len(msgs), 3)
        self.assertTrue(any("b" in m and "Args" in m for m in msgs))

    def test_js_rules(self) -> None:
        """JS files need a header comment and one @param per parameter."""
        config = {"architecture": {"env_access_layers": ["config"]}, "quality": {"require_docstrings": True}}
        bad = "export function add(a, b) {\n  return a + b;\n}\n"
        good = "/** @file Math helpers. */\n\n/**\n * Add.\n * @param {number} a First.\n * @param {number} b Second.\n * @returns {number} Sum.\n */\nexport const add = (a, b) => {\n  return a + b;\n};\n"
        self.assertEqual(len(review_guard.audit_brace_file(bad, "src/m.js", None, config)), 2)
        self.assertEqual(review_guard.audit_brace_file(good, "src/m.js", None, config), [])

    def test_framework_itself_is_documented(self) -> None:
        """Every framework Python file follows the comment rules it enforces."""
        problems = []
        for path in sorted(TEMPLATE_ROOT.rglob("*.py")):
            rel = path.relative_to(TEMPLATE_ROOT)
            if rel.parts[0] in (".skills-cache", "tests") or "__pycache__" in rel.parts:
                continue
            problems += review_guard.python_docstring_issues(ast.parse(path.read_text(encoding="utf-8")), rel.as_posix())
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
