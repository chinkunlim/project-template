#!/usr/bin/env python3
"""New-project bootstrapper: one command creates the standard structure for any project.

Purpose:
    Every new project starts with the same folders, documents, agent rules and tools,
    so you (and every AI agent) always know where things are:
      - `AGENTS.md` + `.agents/project.toml`  : rules and per-project settings (single source of truth)
      - Agent entry files                     : CLAUDE.md, GEMINI.md, Cursor/Windsurf/Copilot rules
      - `.agents/handoff/` + `.agents/tasks/`  : handoff board and task cards between agents
      - `docs/` skeleton                      : sessions, adr, known-issues, specs, architecture, standards
      - `.agents/bin/` + `.agents/hooks/`     : framework scripts (commit, closeout, doctor, ...) and git hooks
      - `scripts/agentctl.py`                 : the single entry point (the rest of `scripts/` is the project's)
      - `.agents/skills/`                     : core + stack-specific skills (optional ones on request)
      - `.github/workflows/ci.yml`            : CI running the same checks and tests on every push / PR
      - Language starter code                 : python / node / gas / go / rust / generic / mobile (Expo)
      - git repo with a version-controlled pre-commit hook (`core.hooksPath .agents/hooks`)

Usage:
    python3 init_project.py --target ~/projects/my_app --stack python
    python3 init_project.py --target ~/projects/app --stack python --with web gas
    python3 init_project.py --target ~/projects/web --stack node --skills legacy-migration
    python3 init_project.py --list-skills
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent
for _path in (TEMPLATE_ROOT, TEMPLATE_ROOT / "lib"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from framework_install import (  # noqa: E402
    framework_file_map,
    install_files,
    load_catalog,
    select_skills,
    write_lock,
)
from packs.docs_templates import docs_skeleton  # noqa: E402
from packs.language_packs import (  # noqa: E402
    ADDON_CHOICES,
    STACK_CHOICES,
    build_ci_workflow,
    build_env_example,
    build_gitignore,
    build_project_toml,
    generate_stack_files,
    project_settings,
)
from project_config import FRAMEWORK_VERSION  # noqa: E402

DEFAULT_DESCRIPTION = "AI-assisted software project with standard structure and agent handoff."


def _write_file(path: Path, content: str) -> None:
    """Write a UTF-8 text file, creating parent folders.

    Args:
        path: Destination file.
        content: Text to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _utc_now() -> str:
    """Return the current UTC time for document headers.

    Returns:
        Timestamp such as `2026-10-19 08:30 UTC`.
    """
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_agents_md(project_name: str, description: str) -> str:
    """Render the root `AGENTS.md` (rules every agent reads first).

    Args:
        project_name: Project name shown in the title.
        description: One-line project description.

    Returns:
        Markdown text. The SKILLS and TREE blocks are filled later by
        `sync_agent_adapters.py` and `update_tree.py`.
    """
    return f"""# AGENTS.md — {project_name}

> {description}
>
> 本檔與 [`.agents/project.toml`](.agents/project.toml) 是所有 AI Agent（Claude Code、Gemini/Antigravity、Cursor、Windsurf、Copilot、Codex）的**唯一規則來源**。`CLAUDE.md`、`GEMINI.md` 等入口檔由 `python3 scripts/agentctl.py sync` 自動產生，請勿直接修改。

<!-- RULES_START -->
## 1. 使用者說什麼 → 執行什麼

能用指令完成的事，Agent **直接執行並貼出結果**，不要只叫使用者自己去跑。

| 使用者說 | 執行 |
|---|---|
| 「開工」「接手」「繼續上次的」（每次對話開始也要先跑） | `python3 scripts/agentctl.py status` |
| 「新工作 / 新功能」 | `python3 scripts/agentctl.py task create "標題" --agent <你的名字>` |
| 「接手 TASK-NNN」 | `python3 scripts/agentctl.py task claim TASK-NNN --agent <你的名字>` |
| 「檢查一下」「跑測試」 | `python3 scripts/agentctl.py check`，再跑 `[commands] test` |
| 「存檔」「commit」 | `python3 scripts/agentctl.py commit --agent <名字> --model <模型>`（訊息用英文） |
| 「去上課」「先暫停」「等一下回來」 | `python3 scripts/agentctl.py pause "<English reason>"` |
| 「換人做」「交給 Cursor」 | `python3 scripts/agentctl.py task handoff TASK-NNN --to <agent> --done-items ... --todo-items ...` |
| 「結束對話」「收工」「今天先這樣」 | `python3 scripts/agentctl.py closeout --agent <名字> --goal ... --decisions ... --issues ... --next ...` |
| 「推上去」 | 先列出未推送的 commit 並**確認**，同意後才 `agentctl commit --push` |
| 「出版本」「專案完成了」 | `python3 scripts/agentctl.py finish`（驗收清單）；要發布再加 `--tag`（Unreleased → 新版本 + 本機 tag） |
| 「環境怪怪的」「換電腦了」 | `python3 scripts/agentctl.py doctor --fix` |

## 2. 核心規則（必須遵守）

1. **完整註解**：每個程式檔開頭寫用途；每個函數/類別寫功能、每個參數（`Args:` / `@param`）與回傳值（格式見 [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) §0，pre-commit 會擋缺漏）。
2. **出示執行證據**：不能只說「已修復 / 完成」，要貼出測試或指令的實際輸出。
3. **決策衝突要停下來問**：動手前先看 `docs/adr/` 中狀態為 Accepted 的決策；使用者的指令或你的做法和它衝突時，暫停並詢問，不要自行改掉。
4. **即時記錄，不要等到最後**：遇到錯誤並找到根因 → 立刻寫 known-issue；做了架構取捨 → 立刻寫 ADR（用 `adr-issue-tracker`）。同樣的錯不能犯第二次。
5. **秘密不進程式碼**：API key / token 只放 `.env`，只在 `config` 層讀取；憑證檔放 `~/.config/<專案>/`（權限 600）。
6. **資料和程式分開**：輸入、輸出、資料庫、log 都在 `.env` 的 `DATA_DIR`（專案資料夾之外）；程式透過 config 取得路徑，專案內只放程式、文件和小型測試樣本。
7. **單向分層**：依 `.agents/project.toml` 的 `[architecture] layers`，上層可依賴下層，反之禁止。
8. **環境隔離（不污染主機）**：Python 只用 `uv add` / `uv run`，Node 只用 `pnpm add` / `pnpm exec`；禁止 `pip install`、`npm`、`npx`、全域安裝與 `sudo`（見 [`ENVIRONMENT_AND_DEPENDENCIES.md`](docs/standards/ENVIRONMENT_AND_DEPENDENCIES.md)）。
9. **本機服務只綁 `127.0.0.1`**：網址寫 `http://127.0.0.1:<port>`，不寫 `localhost`、不綁 `0.0.0.0`。手機 App 預設在 iOS 模擬器 / Android 模擬器測試（`adb reverse` 轉接後端 port）；用真的手機時只用 `expo start --tunnel`，後端不開放到網路（見 `mobile/MOBILE.md`）。
10. **Git**：完成一個可通過測試的修改就用 `agentctl commit`；訊息一律英文；未經使用者明確同意不得 push（見 [`GIT_AND_VERSIONING.md`](docs/standards/GIT_AND_VERSIONING.md)）。
11. **通用規則回寫母版**：使用者提出「以後每個專案都要這樣」的規則時，寫進 [`docs/TEMPLATE_FEEDBACK.md`](docs/TEMPLATE_FEEDBACK.md)，由使用者決定是否更新專案模板；只適用本專案的規則寫進 [`PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md)。
12. **Log 追蹤**：每個模組用 `logger = logging.getLogger(__name__)`，只有 entrypoints 可 `print`；執行的開始與結束、外部呼叫、跳過與重試、例外（`logger.exception`）都要記 log，不記秘密與個資。log 在 `DATA_DIR/logs/`，用 run id 追蹤一次執行（見 [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) §0.4）。
<!-- RULES_END -->

## 2.5 Agent 分工（選填，由使用者維護）

| Agent / 工具 | 負責 | 不負責 |
|---|---|---|
| （例）Claude Code | 後端、測試、重構 | UI 視覺設計 |
| （例）Antigravity | 前端、文件 | 資料庫結構變更 |

## 3. 文件放哪裡（Docs Map）

| 內容 | 位置 | 產生方式 |
|---|---|---|
| 交接看板、任務卡 | `.agents/handoff/LATEST.md`、`.agents/tasks/TASK-NNN-*.json` | `agentctl task` / `closeout` |
| 每次對話的逐字稿＋摘要（目標、決策、錯誤根因、下一步） | `.agents/conversations/YYYY-MM-DD-HHMM-<agent>-{{transcript,summary}}.md`（本機，不進 git） | `agentctl closeout` 產生，Agent 補完摘要 |
| 架構決策 | `docs/adr/NNN-*.md`（總表 `DECISIONS.md`） | `adr-issue-tracker` |
| 已知問題與根因 | `docs/known-issues/NNN-*.md`（總表 `KNOWN_ISSUES.md`） | `adr-issue-tracker` |
| 需求與規格 | `docs/specs/NNN-*.md`（清單 `SPECS.md`） | 手動，照 `_TEMPLATE.md` |
| 系統架構總覽、目錄樹 | `docs/architecture/ARCHITECTURE.md`、`PROJECT_TREE.md` | 手動 / 自動 |
| 版本變更 | `CHANGELOG.md` | commit 寫入 Unreleased；`finish --tag` 發布 |
| 設定 / 環境變數範本 | `.agents/project.toml` / `.env.example` | 手動 |
| 資料（輸入、輸出、資料庫、log） | `.env` 的 `DATA_DIR`（專案資料夾之外） | 程式執行時產生 |
| 給專案模板的改進建議 | `docs/TEMPLATE_FEEDBACK.md` | Agent 記錄，使用者決定 |

**命名規則**：整個專案只有根目錄一份 `README.md`；每個 `docs/` 子資料夾用全大寫的說明/總表檔（如 `KNOWN_ISSUES.md`），新增紀錄時照同資料夾的 `_TEMPLATE.md` 格式寫。

## 4. 規範文件（需要時再讀）

| 文件 | 何時讀 |
|---|---|
| [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) | 寫或重構程式前（含註解規範） |
| [`ARCHITECTURE_RULES.md`](docs/standards/ARCHITECTURE_RULES.md) | 新增模組、調整 import 或分層時 |
| [`MULTI_AGENT_COLLABORATION.md`](docs/standards/MULTI_AGENT_COLLABORATION.md) | 接手、交接、收尾時 |
| [`TESTING_AND_QUALITY.md`](docs/standards/TESTING_AND_QUALITY.md) | 寫測試、錯誤處理時 |
| [`GIT_AND_VERSIONING.md`](docs/standards/GIT_AND_VERSIONING.md) | commit、發版時 |
| [`ENVIRONMENT_AND_DEPENDENCIES.md`](docs/standards/ENVIRONMENT_AND_DEPENDENCIES.md) | 安裝/移除套件、執行工具、設定本機服務前（uv、pnpm、Brewfile、DATA_DIR、127.0.0.1） |
| [`PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md) | **每次開工都讀**：本專案特有的規則（領域知識、例外、禁忌） |

## 5. 可用 Skills

<!-- SKILLS_START -->
(執行 `python3 scripts/agentctl.py sync` 產生)
<!-- SKILLS_END -->

## 6. 目錄結構摘要

> 只列資料夾；含檔案的完整樹在 [`docs/architecture/PROJECT_TREE.md`](docs/architecture/PROJECT_TREE.md)。框架腳本在 `.agents/bin/`，`scripts/` 留給本專案自己的腳本。

<!-- TREE_START -->
```text
{project_name}/
```
<!-- TREE_END -->
"""


def build_readme_md(project_name: str, description: str) -> str:
    """Render the starter `README.md` for humans.

    Args:
        project_name: Project name.
        description: One-line project description.

    Returns:
        Markdown text.
    """
    return f"""# {project_name}

{description}

## 在新電腦上開始

```bash
git clone <repo-url> && cd {project_name}
```

啟用 git hook、重建 skills 連結、檢查 uv / node

```bash
python3 scripts/agentctl.py doctor --fix
```

uv sync（專案內 .venv）+ pnpm install（專案內 node_modules）

```bash
python3 scripts/agentctl.py setup --install
```

填入自己的金鑰（不會被 commit）

```bash
cp .env.example .env
```

所有依賴都裝在專案資料夾內（`.venv/`、`node_modules/`），Python 版本由 uv 依 `.python-version` 自動下載，不會動到主機的 Python / pip。
新增套件：`uv add <套件>`（開發工具 `uv add --dev <套件>`）；執行程式：`uv run ...`。

測試（或 python3 scripts/agentctl.py check）

```bash
uv run python -m unittest discover -s tests -v
```

## 常用指令

交接看板、任務、最近的對話摘要

```bash
python3 scripts/agentctl.py status
```

```bash
python3 scripts/agentctl.py task create "標題" --agent <名字>
```

署名 + CHANGELOG Unreleased + 秘密掃描

```bash
python3 scripts/agentctl.py commit --agent <名字>
```

測試、對話紀錄（逐字稿＋摘要）、交接、Commit

```bash
python3 scripts/agentctl.py closeout --agent <名字>
```

重新產生入口檔與目錄樹

```bash
python3 scripts/agentctl.py sync
```

## 文件索引

- [`AGENTS.md`](AGENTS.md) — Agent 規則與「文件放哪裡」對照表
- [`.agents/handoff/LATEST.md`](.agents/handoff/LATEST.md) — 交接看板
- `.agents/conversations/` — 每次對話的逐字稿與摘要（本機，不進 git）
- [`docs/adr/DECISIONS.md`](docs/adr/DECISIONS.md) — 架構決策
- [`docs/known-issues/KNOWN_ISSUES.md`](docs/known-issues/KNOWN_ISSUES.md) — 已知問題
- [`docs/specs/SPECS.md`](docs/specs/SPECS.md) — 需求規格
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) — 系統架構與目錄樹（依賴圖、審計報告需要時用 `agentctl graph` / `agentctl audit` 產生）
- [`CHANGELOG.md`](CHANGELOG.md) — 版本變更
"""


def build_changelog_md(project_name: str) -> str:
    """Render the initial `CHANGELOG.md`.

    Args:
        project_name: Project name.

    Returns:
        Markdown text with the `0.1.0` entry.
    """
    return f"""# Changelog

All notable changes to **{project_name}** are documented here
(format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/)).

## [Unreleased]

## [0.1.0] - {dt.date.today().isoformat()}
### Added
- Initial project scaffold (framework v{FRAMEWORK_VERSION}).
"""


def build_handoff_md() -> str:
    """Render the initial `.agents/handoff/LATEST.md`.

    Returns:
        Markdown text in the format maintained by `agent_task.py`.
    """
    now = _utc_now()
    return f"""# 🤝 Agent 狀態看板與交接紀錄 (`LATEST.md`)

> **AI Agent 開工必讀**：進入對話時請先閱讀下方「即時狀態看板」，確認上一位 Agent 的完成進度、待接手任務 (`handed_off`) 與注意事項；詳細過程請看本機的 `.agents/conversations/`。

<!-- LIVE_STATE_START -->
## 📊 即時狀態看板 (Live Snapshot)

- **最後更新時間**: `{now}`
- **最近操作 Agent**: `init_project`

### 🎯 進行中 / 待接手任務 (Active & Handed-Off Tasks)

> 目前無進行中或待接手任務。可執行 `python3 scripts/agentctl.py task create "任務名稱" --agent <name>` 建立任務。

<!-- LIVE_STATE_END -->

## 📜 交接與活動時間軸 (Handoff & Activity Timeline)

### [{now}] Initial Bootstrap (by `init_project`)
- **狀態**: 專案已初始化（框架 v{FRAMEWORK_VERSION}）。
- **下一步**: 檢視 `.agents/project.toml`，再用 `agentctl task create` 建立第一個任務。
"""


def ensure_target_is_safe(target_dir: Path, force: bool) -> bool:
    """Refuse to scaffold into a non-empty directory unless `force` is set.

    Args:
        target_dir: Directory that will receive the project.
        force: Allow writing into a non-empty directory (existing files may be overwritten).

    Returns:
        True when the directory already contained files (so no automatic initial commit).

    Raises:
        FileExistsError: When the directory is not empty and `force` is False.
    """
    existing = [p for p in target_dir.iterdir() if p.name not in (".DS_Store",)] if target_dir.exists() else []
    if existing and not force:
        names = ", ".join(p.name for p in existing[:5])
        raise FileExistsError(f"Target directory is not empty ({names}...). Use --force to write into it anyway.")
    return bool(existing)


def write_project_documents(target_dir: Path, project_name: str, settings: dict, extras: dict) -> None:
    """Write configuration, rule documents, CI, the handoff board and the docs skeleton.

    Args:
        target_dir: Project root directory.
        project_name: Project name.
        settings: Output of `project_settings()`.
        extras: Dict with `description` and `skills` (installed skill names).
    """
    langs = settings["languages"]
    files = {
        ".agents/project.toml": build_project_toml(project_name, settings, extras["description"], extras["skills"]),
        ".agents/handoff/LATEST.md": build_handoff_md(),
        "AGENTS.md": build_agents_md(project_name, extras["description"]),
        "README.md": build_readme_md(project_name, extras["description"]),
        "CHANGELOG.md": build_changelog_md(project_name),
        ".gitignore": build_gitignore(langs),
        ".env.example": build_env_example(project_name, langs),
        ".github/workflows/ci.yml": build_ci_workflow(settings),
        **docs_skeleton(),
    }
    for rel, content in files.items():
        _write_file(target_dir / rel, content)


def detect_timezone() -> str:
    """Return this computer's IANA time zone (used for GAS `appsscript.json`).

    Returns:
        A name such as `Asia/Taipei`; `UTC` when it cannot be determined.
    """
    env_tz = os.environ.get("TZ", "").strip()
    if "/" in env_tz:
        return env_tz
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return "UTC"
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else "UTC"


def lock_python_dependencies(target_dir: Path) -> None:
    """Create `uv.lock` so every computer installs exactly the same versions.

    Skipped (with a hint) when uv is missing or offline; set `TEMPLATE_SKIP_UV_LOCK=1`
    to skip on purpose (used by the template's own tests).

    Args:
        target_dir: Project root directory.
    """
    if not (target_dir / "pyproject.toml").exists() or os.environ.get("TEMPLATE_SKIP_UV_LOCK"):
        return
    uv = shutil.which("uv")
    if not uv:
        print("⚠️ 找不到 uv：請安裝 uv（https://docs.astral.sh/uv/）後執行 `uv lock`。")
        return
    res = subprocess.run([uv, "lock"], cwd=target_dir, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        print(f"⚠️ `uv lock` 未完成（可能離線），之後在專案內執行 `uv lock`：{res.stderr.strip()[:200]}")


def run_generators(target_dir: Path) -> None:
    """Run the initial generators: agent entry files and the directory tree.

    Args:
        target_dir: Project root directory.

    Raises:
        subprocess.CalledProcessError: When a generator fails.
    """
    for script in ("sync_agent_adapters.py", "update_tree.py"):
        subprocess.run([sys.executable, str(target_dir / ".agents" / "bin" / script)], cwd=target_dir, check=True, capture_output=True)


def init_git(target_dir: Path, initial_commit: bool) -> None:
    """Create the git repository, activate the versioned hooks, and make the first commit.

    Args:
        target_dir: Project root directory.
        initial_commit: Create the `chore(init)` commit (skipped for pre-existing folders).
    """
    if not (target_dir / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=target_dir, check=False, capture_output=True)
    subprocess.run(["git", "config", "core.hooksPath", ".agents/hooks"], cwd=target_dir, check=False, capture_output=True)
    if not initial_commit:
        return
    subprocess.run(["git", "add", "-A"], cwd=target_dir, check=False, capture_output=True)
    message = (
        f"chore(init): scaffold project v0.1.0 (framework v{FRAMEWORK_VERSION}) [agent:init_project]\n\n"
        "Agent: init_project\nVersion: v0.1.0\nCo-Authored-By: init_project <agent+init_project@local>"
    )
    res = subprocess.run(["git", "commit", "-m", message], cwd=target_dir, check=False, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"⚠️ 初始 commit 未完成（請檢查 git user.name / user.email）：{res.stderr.strip()[:200]}")


def scaffold_project(
    target_dir: Path,
    project_name: str,
    *,
    stack: str = "python",
    addons: list[str] | None = None,
    description: str = DEFAULT_DESCRIPTION,
    extra_skills: list[str] | None = None,
    timezone: str | None = None,
    license_kind: str = "none",
    init_git_repo: bool = True,
    force: bool = False,
) -> list[str]:
    """Create a complete project in `target_dir`.

    Args:
        target_dir: Destination folder (created when missing; must be empty unless `force`).
        project_name: Project name used in documents and package names.
        stack: One of `STACK_CHOICES` (`both` / `all` are aliases for python + add-ons).
        addons: Add-ons from `ADDON_CHOICES` (`web`, `gas`).
        description: One-line project description.
        extra_skills: Optional skills to add on top of core and stack skills.
        timezone: IANA time zone for GAS; detected from this computer when omitted.
        license_kind: `MIT` writes a LICENSE file; `none` (default) grants no license.
        init_git_repo: Initialise git, set `core.hooksPath` and make the first commit.
        force: Allow scaffolding into a non-empty folder (no automatic commit then).

    Returns:
        Installed skill names.

    Raises:
        FileExistsError: When `target_dir` is not empty and `force` is False.
        ValueError: When an unknown skill is requested.
    """
    target_dir = target_dir.resolve()
    pre_existing = ensure_target_is_safe(target_dir, force)
    settings = project_settings(project_name, stack, addons)
    skills = select_skills(load_catalog(TEMPLATE_ROOT), settings["languages"], extra_skills or [])
    target_dir.mkdir(parents=True, exist_ok=True)

    write_project_documents(target_dir, project_name, settings, {"description": description, "skills": skills})
    installed = install_files(target_dir, framework_file_map(TEMPLATE_ROOT, skills))
    options = {"description": description, "timezone": timezone or detect_timezone(), "license": license_kind}
    generate_stack_files(target_dir, project_name, settings, options)
    write_lock(target_dir, TEMPLATE_ROOT, FRAMEWORK_VERSION, skills, installed)
    lock_python_dependencies(target_dir)
    run_generators(target_dir)
    if init_git_repo:
        init_git(target_dir, initial_commit=not pre_existing)
    return skills


def print_skill_list() -> None:
    """Print the skill catalog grouped by tier."""
    for name, meta in sorted(load_catalog(TEMPLATE_ROOT).items(), key=lambda kv: (kv[1].get("tier", ""), kv[0])):
        stacks = f" [{', '.join(meta.get('stacks', []))}]" if meta.get("stacks") else ""
        print(f"{meta.get('tier', '?'):<9} {name:<22}{stacks} — {meta.get('trigger', '')}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="建立標準結構的新專案（文件、資料夾、Agent 規則與工具）")
    parser.add_argument("--target", help="新專案資料夾路徑")
    parser.add_argument("--name", default=None, help="專案名稱（預設為資料夾名稱）")
    parser.add_argument("--stack", choices=STACK_CHOICES, default="python", help="主要語言（預設 python；both = python+web，all = python+web+gas，mobile = 只有手機 App）")
    parser.add_argument("--with", dest="addons", nargs="*", choices=ADDON_CHOICES, default=[],
                        help="附加：web、gas、mobile（Expo 手機 App，Android+iOS）、api（FastAPI）、db（SQLAlchemy+Alembic+SQLite）、ollama（本機模型＋硬體檢查）、evals（輸出品質評估）")
    parser.add_argument("--timezone", default=None, help="GAS 時區（預設讀取這台電腦，例如 Asia/Taipei）")
    parser.add_argument("--license", default="none", choices=["none", "MIT"], help="授權：MIT 會產生 LICENSE（預設不授權）")
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION, help="一句話專案描述")
    parser.add_argument("--skills", nargs="*", default=[], help="額外安裝的 optional skills（例如 legacy-migration）")
    parser.add_argument("--list-skills", action="store_true", help="列出可用 skills 後結束")
    parser.add_argument("--no-git", action="store_true", help="不建立 git repo 與初始 commit")
    parser.add_argument("--force", action="store_true", help="允許寫入非空資料夾（可能覆蓋同名檔案）")
    args = parser.parse_args(argv)
    if not args.list_skills and not args.target:
        parser.error("--target is required")
    return args


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    if args.list_skills:
        print_skill_list()
        return 0
    target_dir = Path(args.target).expanduser().resolve()
    project_name = args.name or target_dir.name
    try:
        skills = scaffold_project(
            target_dir, project_name, stack=args.stack, addons=args.addons, description=args.description,
            extra_skills=args.skills, timezone=args.timezone, license_kind=args.license,
            init_git_repo=not args.no_git, force=args.force,
        )
    except (FileExistsError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    extras = f" + {', '.join(args.addons)}" if args.addons else ""
    print(f"✅ 已建立 '{project_name}' (stack={args.stack}{extras}, skills={', '.join(skills)})：{target_dir}")
    print("   下一步：cd 進去後執行 `python3 scripts/agentctl.py status`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
