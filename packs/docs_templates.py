#!/usr/bin/env python3
"""Standard `docs/` skeleton: one index file and one template per folder.

Purpose:
    Gives every project the same documentation layout with names that explain
    themselves, so nobody has to guess which file is which:
      - `README.md` exists only at the project root.
      - `<TOPIC>.md` (upper case) is the folder's guide and index table,
        e.g. `DECISIONS.md`, `KNOWN_ISSUES.md`, `SPECS.md`, `ARCHITECTURE.md`.
      - `_TEMPLATE.md` is the format to copy when adding a record. The leading `_`
        sorts it first and keeps it out of record numbering and listings.
      - Records are `NNN-<slug>.md` (ADR / issues / specs). Conversation records live locally in
        `.agents/conversations/` (not in git).

    `{{NUM}}`, `{{TITLE}}`, `{{DATE}}`, `{{AGENT}}`, `{{TASK}}`, `{{SUMMARY}}`, `{{STATUS}}`
    placeholders are filled in by `adr-issue-tracker` (`tracker_cli.py`); replace them by
    hand when copying a template manually.
"""

from __future__ import annotations

NAMING_NOTE = (
    "> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `{pattern}`。"
    "整個專案只有根目錄一份 `README.md`。\n"
)

ADR_INDEX = """# 架構決策 (Architecture Decision Records)

記錄「為什麼這樣設計」：每個重要的架構取捨一個檔案，之後的人（或 Agent）不用再猜。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr <slug> --title "標題" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在相關程式碼註解加 `Refs: ADR-NNN`。
- 決策被推翻時不要刪檔，把狀態改成 `Superseded by ADR-NNN`。

{note}
## 總表

| ADR | 標題 | 狀態 | 日期 | 相關程式 |
|---|---|---|---|---|
"""

ADR_TEMPLATE = """# ADR-{{NUM}}：{{TITLE}}

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：{{DATE}}
- **Agent**：`{{AGENT}}`
- **任務**：`{{TASK}}`

## 1. 背景與問題

{{SUMMARY}}

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A | TODO | TODO |
| B | TODO | TODO |

## 3. 決策與理由

TODO: 選了哪個方案、為什麼。

## 4. 影響與代價

TODO: 正面影響、代價、之後要注意的事、要同步修改的地方。
"""

ISSUE_INDEX = """# 已知問題 (Known Issues)

記錄「踩過的坑」：值得記住的 bug、外部服務的怪行為、環境問題，以及它們的根本原因與修正方式。
除錯時先查這裡：`grep -rn "關鍵字" docs/known-issues .agents/conversations`（後者只在本機）。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-issue <slug> --title "標題" --summary "錯誤訊息" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在修正的程式碼註解加 `Refs: ISSUE-NNN`，並寫防回歸測試。
- 狀態：🔴 未解決 (open) → 🟡 已規避 (mitigated) → 🟢 已根治 (resolved)

{note}
## 總表

| ISSUE | 狀態 | 標題 | 現象 | 程式與測試 |
|---|---|---|---|---|
"""

ISSUE_TEMPLATE = """# ISSUE-{{NUM}}：{{TITLE}}

- **狀態**：{{STATUS}}
- **發現日期**：{{DATE}}
- **Agent**：`{{AGENT}}`
- **任務**：`{{TASK}}`

## 1. 現象

{{SUMMARY}}

- **錯誤訊息**：TODO（貼上完整訊息或 log 片段）
- **重現步驟**：TODO
- **影響範圍**：TODO

## 2. 根本原因

TODO: 為什麼會發生（不是「怎麼修」）。

## 3. 修正或規避方式

TODO: 改了什麼；相關程式碼註解加 `Refs: ISSUE-{{NUM}}`。

## 4. 防回歸

TODO: 對應的測試檔與測試名稱，確保不會再發生。
"""

SPECS_INDEX = """# 需求與規格 (Specs)

一個功能一份規格，先寫規格再實作；實作時在任務卡與 commit 中引用規格檔名。

- 新增：複製 [`_TEMPLATE.md`](_TEMPLATE.md) 為 `NNN-<slug>.md`（例如 `001-login-api.md`），並在下表加一列。

{note}
## 規格清單

| 規格 | 狀態 | 說明 |
|---|---|---|
"""

SPEC_TEMPLATE = """# SPEC-NNN：<功能名稱>

- **狀態**：Draft <!-- Draft | Approved | Implemented | Deprecated -->
- **日期**：YYYY-MM-DD
- **相關任務 / ADR**：TASK-NNN / ADR-NNN

## 1. 目標

這個功能要解決什麼問題？成功的樣子是什麼？

## 2. 使用情境

誰、在什麼情況下、做什麼。

## 3. 需求

- **必須 (Must)**：
- **可選 (Nice to have)**：
- **不做 (Out of scope)**：

## 4. 介面 / API

輸入、輸出、錯誤情況（必要時附範例 JSON）。

## 5. 驗收標準

- [ ] 可以用測試驗證的條件

## 6. 未決問題

- 尚待確認的事項
"""

ARCHITECTURE_DOC = """# 系統架構 (Architecture)

> 手動維護本檔的「系統概覽」；以下報告由工具自動產生，請勿手動修改。

| 文件 | 內容 | 產生方式 |
|---|---|---|
| [`PROJECT_TREE.md`](PROJECT_TREE.md) | 完整目錄樹 | `agentctl sync` / 每次 commit |
| `GRAPH_REPORT.md` | 模組依賴圖、分層檢查、函式大小 | 需要時 `agentctl graph`（不進 git） |
| `AGENT_AUDIT_REPORT.md` | 各 Agent 的 commit 與任務 | 需要時 `agentctl audit`（不進 git） |

## 系統概覽

TODO: 用幾句話或一張圖說明主要元件、資料流與外部服務。

## 分層

見 `.agents/project.toml` 的 `[architecture] layers` 與 [`ARCHITECTURE_RULES.md`](../standards/ARCHITECTURE_RULES.md)。
"""


PROJECT_RULES = """# 本專案專屬規則 (PROJECT_RULES)

> 規則分兩層：`docs/standards/` 的其他文件是**所有專案通用**的規範（由專案模板提供，`agentctl update` 會更新）；
> 本檔是**只適用這個專案**的規則，由這個專案自己維護，模板更新時不會被覆蓋。每次開工都要讀。

## 1. 領域知識與術語

- （例）「文獻」指學術論文 PDF；「書籍」指教科書 PDF / EPUB。

## 2. 本專案特有的規則

- （例）所有呼叫本機 Ollama 的程式，都要先通過硬體檢查（RAM / 電池）。

## 3. 和通用規範不同的例外（要寫理由）

- （例）`legacy_parser.py` 暫時允許 900 行：正在依 TASK-012 拆分。

## 4. 禁止事項

- （例）不要修改 `data/input/` 的原始檔（只讀）。
"""

TEMPLATE_FEEDBACK = """# 給專案模板的改進建議 (TEMPLATE_FEEDBACK)

> 使用者提出「以後每個專案都要這樣」的規則或習慣時，Agent 記在這裡（不直接改模板）。
> 使用者之後決定是否把它更新到專案模板（`01 project_template`），讓所有新專案都有。

| 日期 | 建議 | 來源（對話 / 任務） | 狀態 |
|---|---|---|---|
"""


def docs_skeleton() -> dict[str, str]:
    """Return every documentation file a new project starts with.

    Returns:
        Mapping of repo-relative path -> file content.
    """
    return {
        ".agents/tasks/.gitkeep": "",
        "docs/adr/DECISIONS.md": ADR_INDEX.format(note=NAMING_NOTE.format(pattern="NNN-<slug>.md")),
        "docs/adr/_TEMPLATE.md": ADR_TEMPLATE,
        "docs/known-issues/KNOWN_ISSUES.md": ISSUE_INDEX.format(note=NAMING_NOTE.format(pattern="NNN-<slug>.md")),
        "docs/known-issues/_TEMPLATE.md": ISSUE_TEMPLATE,
        "docs/specs/SPECS.md": SPECS_INDEX.format(note=NAMING_NOTE.format(pattern="NNN-<slug>.md")),
        "docs/specs/_TEMPLATE.md": SPEC_TEMPLATE,
        "docs/architecture/ARCHITECTURE.md": ARCHITECTURE_DOC,
        "docs/standards/PROJECT_RULES.md": PROJECT_RULES,
        "docs/TEMPLATE_FEEDBACK.md": TEMPLATE_FEEDBACK,
    }
