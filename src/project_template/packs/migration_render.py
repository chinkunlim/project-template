#!/usr/bin/env python3
"""Render `docs/migration/MIGRATION.md` from planned legacy-project entries.

Purpose:
    Keeps `packs/migration_plan.py` concise and cleanly separates Markdown rendering
    of the migration plan batches, dependency steps, data moves, and risks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

BATCH_TITLES = {
    "deps": "依賴與設定檔轉換（uv / pnpm / .env.example / Brewfile）",
    "config": "config 層（設定、環境變數讀取）",
    "db": "資料庫（SQLAlchemy 模型 → adapters/db、Alembic 遷移 → alembic/versions、SQLite → DATA_DIR/db/）",
    "domain": "domain 層（資料模型、純邏輯）",
    "adapters": "adapters 層（外部 API、資料庫、檔案 I/O）",
    "services": "services 層（業務流程）",
    "entrypoints": "entrypoints 層（CLI、HTTP、排程入口）",
    "flask": "Flask → FastAPI 改寫（路由、請求驗證、模板 / 靜態檔）",
    "web": "web 前端（HTML / CSS / JS）",
    "gas": "GAS（Apps Script）",
    "tests": "測試",
    "docs": "文件（README、規格、決策、已知問題）",
    "other": "其他（資料、資源、需人工判斷）",
}

DONE_PER_BATCH = """每一批都必須做到（做到才可 `agentctl task done`）：

1. **兩個 commit：先搬、再整理**（保證 `git log --follow` 與 blame 追得到舊歷史）：
   - 第一個 commit 只用 `git mv legacy/舊路徑 新路徑` 搬移，內容一個字都不改：`agentctl commit --bump none -m "refactor(migration): move <檔名> from legacy"`。pre-commit 只對「從 legacy/ 原樣搬入」的檔案暫時放行註解、大小、分層與 print 問題（秘密與禁用套件仍會擋）。
   - 下一個 commit 必須把這批檔案全部整理到符合規範（第 2 點），否則任何 commit 與 `agentctl check` 都過不了，所以一批只搬少量檔案。
2. 依新規範修改：
   - **註解**：檔案開頭用途說明；每個函數/類別的說明、每個參數（`Args:` / `@param`）與回傳值（[`CODING_PRINCIPLES.md`](../standards/CODING_PRINCIPLES.md) §0）。
   - **型別**：Python 參數與回傳值都有型別，`uv run mypy` 通過（strict）。
   - **分層**：放到正確的層；環境變數只在 `config` 層讀取，其他層改收 `AppConfig` 參數（[`ARCHITECTURE_RULES.md`](../standards/ARCHITECTURE_RULES.md)）。
   - **函式大小**：符合 `[quality]` 門檻。
   - **Log**：除了 entrypoints，`print` 一律改成模組 logger；關鍵步驟、外部呼叫與例外都要記 log（[`CODING_PRINCIPLES.md`](../standards/CODING_PRINCIPLES.md) §0.4）。
   - **秘密**：金鑰移到 `.env`，`.env.example` 只留變數名稱。
   - **依賴**：只用 `uv add` / `pnpm add`（[`ENVIRONMENT_AND_DEPENDENCIES.md`](../standards/ENVIRONMENT_AND_DEPENDENCIES.md)）。
   - **本機服務**：綁 `127.0.0.1`，網址不用 `localhost`。
   - **測試**：搬移的程式要有測試（沿用舊測試或補寫，[`TESTING_AND_QUALITY.md`](../standards/TESTING_AND_QUALITY.md)）。
3. `python3 scripts/agentctl.py check` 與專案測試全部通過。
4. 下方「檔案清單」把這批的 ☐ 改成 ☑；過程中的重要決策寫 ADR、發現的舊 bug 寫 known-issue。
5. `python3 scripts/agentctl.py commit --agent <名字> --task TASK-NNN`，再 `agentctl task done TASK-NNN --summary ...`。
"""

DONE_FINAL = """全部完成才算遷移成功（`python3 scripts/agentctl.py migration --verify` 會逐項檢查）：

- [ ] `legacy/` 已刪除（所有檔案都搬到新結構或確認不需要）。
- [ ] 舊資料已依 §4.5 複製到 `DATA_DIR`，程式透過 config 讀取路徑，專案資料夾內沒有資料檔。
- [ ] 沒有 `requirements.txt`、`package-lock.json`、`yarn.lock`、`Pipfile`：依賴只在 `pyproject.toml` + `uv.lock`、`package.json` + `pnpm-lock.yaml`。
- [ ] `python3 scripts/agentctl.py check` 全部通過（註解、分層、秘密、lint、mypy strict、目錄樹）。
- [ ] 專案測試全部通過。
- [ ] 所有遷移任務卡都是 `done`。
- [ ] 模板的範例程式（`greeting` 相關的 services / domain / cli / api / 資料表 `greetings` 與其 Alembic revision、測試）已刪除或換成真正的程式。
- [ ] `README.md` 改寫為這個專案的說明；`docs/architecture/ARCHITECTURE.md` 有系統概覽；主要功能在 `docs/specs/` 有規格。
- [ ] 舊專案已知的問題記在 `docs/known-issues/`；遷移中的重要決策記在 `docs/adr/`。
- [ ] `.env.example` 列出所有需要的變數（只有名稱）。
- [ ] 最後執行 `agentctl closeout`（本機對話紀錄＋交接看板記下遷移完成）。
"""


def _render_header(source: dict[str, str], entries_count: int) -> list[str]:
    """Render title, source metadata and completion checklists for `MIGRATION.md`.

    Args:
        source: Old project summary dictionary.
        entries_count: Total classified legacy files.

    Returns:
        Markdown lines up to section 3 header.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode_text = {
        "maintain": "維護模式：保留 Flask，只整理結構與規範（之後要繼續開發時執行 `python3 scripts/agentctl.py migration --develop`）",
        "develop": "開發模式：Flask 必須全部改寫成 FastAPI（對照表：[`FLASK_TO_FASTAPI.md`](../../.agents/skills/legacy-migration/FLASK_TO_FASTAPI.md)）",
    }[source.get("mode", "maintain")]
    history = (
        "已保留（新 repo 由舊 repo clone；舊檔案以 `git mv` 移到 `legacy/`，`git log --follow` 可追溯）"
        if source["history"] == "kept"
        else "未保留（舊專案不是 git repo）"
    )
    flask_note = "" if source.get("uses_flask") == "yes" else "（舊專案未使用 Flask）"
    return [
        "# 專案遷移計畫 (MIGRATION)", "",
        "> 舊專案的檔案目前在 `legacy/`（原封不動）。依下方批次逐一搬到新結構，**每一批都要符合新專案的所有規範**，全部完成後刪除 `legacy/`。",
        "", "## 1. 來源", "",
        f"- **舊專案位置**：`{source['path']}`",
        f"- **舊專案遠端**：`{source.get('origin') or '-'}`",
        f"- **遷移時的最後 commit**：`{source.get('commit') or '-'}`",
        f"- **git 歷史**：{history}",
        f"- **模式**：{mode_text}{flask_note}",
        f"- **建立時間**：{now}",
        f"- **檔案數**：{entries_count}", "",
        "## 2. 完成標準", "", "### 每一批", "", DONE_PER_BATCH,
        "### 整個遷移", "", DONE_FINAL,
        "## 3. 批次", "", "| 順序 | 任務 | 內容 | 檔案數 |", "|---|---|---|---|",
    ]


def _render_deps_and_data(extras: dict[str, Any]) -> list[str]:
    """Render dependency conversion and DATA_DIR migration sections.

    Args:
        extras: Plan extras dictionary (`deps`, `env_keys`, `data_moves`).

    Returns:
        Markdown lines for sections 4 and 4.5.
    """
    lines = ["", "## 4. 依賴轉換", ""]
    if extras["deps"]:
        for desc, cmd in extras["deps"]:
            lines += [desc + "：", "", "```bash", cmd, "```", ""]
    else:
        lines += ["（舊專案沒有可自動轉換的依賴檔）", ""]
    if extras["env_keys"]:
        keys = "、".join(f"`{k}`" for k in extras["env_keys"])
        lines += [f"舊 `.env.example` 的變數（加到新 `.env.example`，只寫名稱）：{keys}", ""]
    lines += ["## 4.5 資料搬到 DATA_DIR（資料不進新專案）", ""]
    if not extras.get("data_moves"):
        return lines + ["- 舊專案沒有偵測到資料檔。", ""]
    lines += [
        "舊專案的資料**沒有**搬進 `legacy/`，也不在新專案資料夾內；唯一的副本仍在舊專案（未被修改）。確認 `.env` 的 `DATA_DIR` 後，**在新專案資料夾內**依序執行（目標是相對於新專案的路徑）：",
        "",
    ]
    for desc, cmd in extras["data_moves"]:
        lines += [desc + "：", "", "```bash", cmd, "```", ""]
    return lines + ["複製完成並確認新專案能讀到資料後，再決定是否刪除舊專案的資料（請自行確認，工具不會刪除）。", ""]


def render_migration_md(source: dict[str, str], entries: list[Any], extras: dict[str, Any]) -> str:
    """Render `docs/migration/MIGRATION.md`.

    Args:
        source: Old project info: `path`, `origin`, `commit`, `history` (`kept` / `none`).
        entries: Classified legacy files.
        extras: `batches` (list of `(batch, task_id, entries)`), `deps` (dependency steps),
            `env_keys` (old variable names), `risks` (risk lines).

    Returns:
        Markdown text.
    """
    logger.debug("rendering MIGRATION.md entries=%d", len(entries))
    lines = _render_header(source, len(entries))
    for idx, (batch, task_id, items) in enumerate(extras["batches"], start=1):
        lines.append(f"| {idx} | `{task_id}` | {BATCH_TITLES[batch]} | {len(items)} |")
    lines += _render_deps_and_data(extras)
    lines += ["## 5. 風險", ""]
    lines += [f"- {r}" for r in extras["risks"]] or ["- 未發現機密檔或大型檔案。"]
    lines += ["", "## 6. 檔案清單", "", "| 狀態 | 舊檔案 | 建議位置 | 批次 |", "|---|---|---|---|"]
    lines += [f"| ☐ | `{e.path}` | `{e.target}` | {e.batch} |" for e in entries]
    return "\n".join(lines) + "\n"
