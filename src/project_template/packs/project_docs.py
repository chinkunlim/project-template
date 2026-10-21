"""Project documents every new project starts with: AGENTS.md, README.md, CHANGELOG.md, the handoff board.

Purpose:
    `services/scaffold.py` writes these files when it creates a project. The long texts are
    module-level templates (`AGENTS_TEMPLATE`, `README_TEMPLATE`) filled with `str.format()`, so the
    functions only decide which stack-specific sentences apply. `AGENTS.md`'s SKILLS and TREE blocks
    are filled later by `.agents/bin/sync_agent_adapters.py` and `.agents/bin/update_tree.py`.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from project_template.packs.common import slugify_package_name

AGENTS_TEMPLATE = """# AGENTS.md — {project_name}

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
| 「做一個網頁」「給 Open WebUI / Ollama / Agent 用」 | **先依 [`LOCAL_AI_ENVIRONMENT.md`](docs/standards/LOCAL_AI_ENVIRONMENT.md) §2 確認需求**並請使用者確認摘要，再做 FastAPI + MCP（核心規則 13）；專案沒有 `api` 時先問使用者 |
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
9. **本機服務只綁 `127.0.0.1`**：網址寫 `http://127.0.0.1:<port>`，不寫 `localhost`、不綁 `0.0.0.0`。{mobile_rule}
10. **Git**：完成一個可通過測試的修改就用 `agentctl commit`；訊息一律英文；未經使用者明確同意不得 push（見 [`GIT_AND_VERSIONING.md`](docs/standards/GIT_AND_VERSIONING.md)）。
11. **通用規則回寫母版**：使用者提出「以後每個專案都要這樣」的規則時，寫進 [`docs/TEMPLATE_FEEDBACK.md`](docs/TEMPLATE_FEEDBACK.md)，由使用者決定是否更新專案模板；只適用本專案的規則寫進 [`PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md)。
12. **Log 追蹤**：執行的開始與結束、外部呼叫、跳過與重試、例外都要記 log，不記秘密與個資。{log_how}（見 [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) §0.4）。
13. **網頁一定要能給 AI 工具用**：使用者要網頁、API，或要讓 Open WebUI / Ollama / 其他 Agent 使用時，先依 [`LOCAL_AI_ENVIRONMENT.md`](docs/standards/LOCAL_AI_ENVIRONMENT.md) §2 的清單確認需求（誰用、哪些動作會改資料、接哪些工具、要不要本機模型、資料、介面、啟動方式、埠號、驗收），整理成摘要請使用者確認；再一律用 FastAPI（`--with api`），不要做單純的網頁。同一組 `services` 由三個入口呼叫：HTTP 路由（OpenAPI 給 Open WebUI）、MCP 工具（`entrypoints/mcp_server.py`，給 Claude Code、Antigravity、OpenCode、Cursor、Open WebUI）與網頁。新增功能時三個入口一起接；會修改或刪除資料的 MCP 工具要有 `confirm` 參數{integrations_link}。
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
| 給專案模板的改進建議 | `docs/TEMPLATE_FEEDBACK.md` | Agent 記錄，使用者決定 |{integrations_row}

**命名規則**：整個專案只有根目錄一份 `README.md`；每個 `docs/` 子資料夾用全大寫的說明/總表檔（如 `KNOWN_ISSUES.md`），新增紀錄時照同資料夾的 `_TEMPLATE.md` 格式寫。

## 4. 規範文件（需要時再讀）

| 文件 | 何時讀 |
|---|---|
| [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) | 寫或重構程式前（含註解規範） |
| [`ARCHITECTURE_RULES.md`](docs/standards/ARCHITECTURE_RULES.md) | 新增模組、調整 import 或分層時 |
| [`MULTI_AGENT_COLLABORATION.md`](docs/standards/MULTI_AGENT_COLLABORATION.md) | 接手、交接、收尾時 |
| [`TESTING_AND_QUALITY.md`](docs/standards/TESTING_AND_QUALITY.md) | 寫測試、錯誤處理時 |
| [`GIT_AND_VERSIONING.md`](docs/standards/GIT_AND_VERSIONING.md) | commit、發版時 |
| [`LOCAL_AI_ENVIRONMENT.md`](docs/standards/LOCAL_AI_ENVIRONMENT.md) | 使用者要網頁 / API / 給 AI 工具用、要接 Ollama 或 Open WebUI、排除 AI 工具連線問題時（這台電腦的 AI 工具、埠號、需求確認清單） |
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

README_TEMPLATE = """# {project_name}

{description}

> 請把上面兩行改寫成這個專案的說明（`agentctl finish` 會檢查）。以下是開發環境與日常操作。

## 第一次在這台電腦使用

1. 取得程式（已經在本機就略過）

```bash
git clone <repo-url> && cd {project_name}
```

2. 檢查並修復環境：{doctor_what}

```bash
python3 scripts/agentctl.py doctor --fix
```

3. 打開 `.env` 填入金鑰與設定（`.env` 不會被 commit）{mobile_env_note}。
{install_block}
> 換電腦時：資料不在 git 裡，另外複製整個 `DATA_DIR`（路徑寫在 `.env`）。
> 搬移或改名專案資料夾後：執行一次 `python3 scripts/agentctl.py doctor --fix`（重建記住舊位置的 `.venv`）。
{python_note}
## 確認一切正常

註解、分層、秘密、lint、型別、目錄樹

```bash
python3 scripts/agentctl.py check
```
{test_block}
## 和 AI Agent 一起開發

用 Claude Code、Antigravity、Cursor 等工具打開這個資料夾，Agent 會自動讀 `AGENTS.md`。直接用口語下指令：

| 你說 | Agent 會做 |
|---|---|
| 「開工」「繼續上次的」 | 看交接看板、上次的下一步、未完成的任務 |
| 「新功能：…」 | 建任務卡，寫測試與程式 |
| 「commit」 | 檢查後本機 commit（英文訊息，不會推送） |
| 「去上課」「先暫停」 | 記下進度，下次接著做 |
| 「收工」 | 測試、寫對話紀錄與摘要、更新交接看板、commit |
| 「推上去」 | 列出要推送的 commit，等你同意 |
| 「出版本」「專案完成了」 | 完成驗收；`--tag` 時升版並打 tag |

完整對照表見 [`AGENTS.md`](AGENTS.md) §1。

## 常用指令

```bash
python3 scripts/agentctl.py status
```

```bash
python3 scripts/agentctl.py task create "標題" --agent <名字>
```

```bash
python3 scripts/agentctl.py commit --agent <名字>
```

```bash
python3 scripts/agentctl.py closeout --agent <名字>
```

全部子指令

```bash
python3 scripts/agentctl.py --help
```
{guides_block}
## 文件索引

- [`AGENTS.md`](AGENTS.md) — Agent 規則與「文件放哪裡」對照表
- [`.agents/handoff/LATEST.md`](.agents/handoff/LATEST.md) — 交接看板
- `.agents/conversations/` — 每次對話的逐字稿與摘要（本機，不進 git）
- [`docs/adr/DECISIONS.md`](docs/adr/DECISIONS.md) — 架構決策
- [`docs/known-issues/KNOWN_ISSUES.md`](docs/known-issues/KNOWN_ISSUES.md) — 已知問題
- [`docs/specs/SPECS.md`](docs/specs/SPECS.md) — 需求規格
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) — 系統架構與目錄樹（依賴圖、審計報告需要時用 `agentctl graph` / `agentctl audit` 產生）
- [`docs/standards/PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md) — 本專案特有的規則
- [`CHANGELOG.md`](CHANGELOG.md) — 版本變更
"""


def _utc_now() -> str:
    """Return the current UTC time for document headers.

    Returns:
        Timestamp such as `2026-10-19 08:30 UTC`.
    """
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_agents_md(project_name: str, description: str, languages: list[str] | None = None) -> str:
    """Render the root `AGENTS.md` (rules every agent reads first).

    Args:
        project_name: Project name shown in the title.
        description: One-line project description.
        languages: Base stack plus add-ons; stack-specific sentences are added only when they apply.

    Returns:
        Markdown text. The SKILLS and TREE blocks are filled later by
        `sync_agent_adapters.py` and `update_tree.py`.
    """
    langs = languages or []
    integrations_link = "（各工具怎麼接：[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)）" if "api" in langs else ""
    integrations_row = (
        "\n| 讓 AI 工具使用本專案（Open WebUI、Claude Code、Antigravity、OpenCode…） | `docs/INTEGRATIONS.md`、`.mcp.json` 等設定檔 | 建立專案時產生 |"
    ) if "api" in langs else ""
    mobile_rule = (
        "手機 App 預設在 iOS 模擬器 / Android 模擬器測試（`adb reverse` 轉接後端 port）；用真的手機時只用 `expo start --tunnel`，"
        "後端不開放到網路（見 `mobile/MOBILE.md`）。"
    ) if "mobile" in langs else ""
    log_how = "；".join(part for part in (
        "Python 每個模組用 `logger = logging.getLogger(__name__)`，只有 entrypoints 可 `print`，log 檔在 `DATA_DIR/logs/`，用 run id 追蹤一次執行"
        if "python" in langs else "",
        "手機 App 用 `createLogger(\"<層>/<模組>\")`" if "mobile" in langs else "",
        "JS / GAS 用 `console.info / warn / error`" if {"node", "gas", "web"} & set(langs) else "",
    ) if part) or "依語言使用標準的 logger"
    return AGENTS_TEMPLATE.format(
        project_name=project_name, description=description, mobile_rule=mobile_rule, log_how=log_how,
        integrations_link=integrations_link, integrations_row=integrations_row,
    )


README_GUIDES = (
    ("web", "web/WEB.md", "網頁前端（本機預覽）"),
    ("gas", "gas/GAS.md", "Google Apps Script（測試、打包、clasp 推送）"),
    ("mobile", "mobile/MOBILE.md", "手機 App（Expo：模擬器、實機 tunnel、上架）"),
    ("api", "src/{pkg}/entrypoints/http/API.md", "HTTP API（FastAPI，啟動與 /docs）"),
    ("db", "alembic/DB.md", "資料庫（SQLAlchemy + Alembic：改資料表的流程）"),
    ("ollama", "docs/PROMPT_TEMPLATES.md", "本機模型的 prompt 版本"),
    ("evals", "evals/EVALS.md", "輸出品質評估"),
)


def build_readme_md(project_name: str, description: str, settings: dict[str, Any] | None = None) -> str:
    """Render the starter `README.md` for humans: setup on a new computer, daily use, guides.

    Args:
        project_name: Project name.
        description: One-line project description.
        settings: Output of `project_settings()` (languages and test command); None for a minimal README.

    Returns:
        Markdown text.
    """
    settings = settings or {"languages": [], "test": ""}
    langs = settings["languages"]
    pkg = slugify_package_name(project_name)
    doctor_what = "啟用 git hook、建立 `.env`" + (" 與 `mobile/.env`" if "mobile" in langs else "") + "、建立 DATA_DIR、檢查 " + "、".join(
        t for t, need in (("uv", "python" in langs), ("Node / pnpm", bool({"node", "gas", "mobile"} & set(langs))),
                          ("Xcode / Android SDK", "mobile" in langs)) if need) + "（只修這個專案，不安裝全域工具）"
    install_what = "、".join(t for t, need in (("uv sync（專案內 `.venv/`）", "python" in langs),
                                             ("pnpm install（各資料夾內的 `node_modules/`）", bool({"node", "gas", "mobile"} & set(langs)))) if need)
    guides = [f"- [`{path.format(pkg=pkg)}`]({path.format(pkg=pkg)}) — {desc}" for key, path, desc in README_GUIDES if key in langs[1:]]
    if langs[:1] == ["gas"]:
        guides.insert(0, "- [`GAS.md`](GAS.md) — Google Apps Script（測試、打包、clasp 推送）")  # gas as the base stack lives at the root
    python_note = (
        "\n新增 Python 套件：`uv add <套件>`（開發工具 `uv add --dev <套件>`）；執行程式：`uv run ...`。"
        "Python 版本由 uv 依 `.python-version` 自動下載，不會動到主機的 Python / pip。\n" if "python" in langs else ""
    )
    test_block = f"""
專案測試

```bash
{settings["test"]}
```
""" if settings.get("test") else ""
    install_block = f"""
4. 安裝依賴：{install_what}

```bash
python3 scripts/agentctl.py setup --install
```
""" if install_what else ""
    mobile_env_note = "；App 的設定在 `mobile/.env`（會打包進 App，不放秘密）" if "mobile" in langs else ""
    guides_block = "\n## 各部分說明\n\n" + "\n".join(guides) + "\n" if guides else ""
    return README_TEMPLATE.format(
        project_name=project_name, description=description, doctor_what=doctor_what, mobile_env_note=mobile_env_note,
        install_block=install_block, python_note=python_note, test_block=test_block, guides_block=guides_block,
    )


def build_changelog_md(project_name: str, framework_version: str) -> str:
    """Render the initial `CHANGELOG.md`.

    Args:
        project_name: Project name.
        framework_version: Template framework version the project starts with.

    Returns:
        Markdown text with the `0.1.0` entry.
    """
    return f"""# Changelog

All notable changes to **{project_name}** are documented here
(format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/)).

## [Unreleased]

## [0.1.0] - {dt.date.today().isoformat()}
### Added
- Initial project scaffold (framework v{framework_version}).
"""


def build_handoff_md(framework_version: str) -> str:
    """Render the initial `.agents/handoff/LATEST.md`.

    Args:
        framework_version: Template framework version the project starts with.

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
- **狀態**: 專案已初始化（框架 v{framework_version}）。
- **下一步**: 檢視 `.agents/project.toml`，再用 `agentctl task create` 建立第一個任務。
"""
