# ISSUE-004：全域軟連結調用時 closeout_runner 專案根目錄誤判

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-01
- **Agent**：`antigravity`
- **任務**：`TASK-001`

## 1. 現象

在子專案（如 `literature-parser`）或其他非母版目錄，透過全域 Symlink 調用 `session-closeout` 技能時：
- 執行測試時，腳本跑的不是當前子專案的測試，而是跑母版 `01 project_template` 的測試。
- 收集修改檔案與 git diff 時，讀取的也是母版倉庫的狀態。

- **錯誤訊息**：子專案收尾時出現母版 75 個測試執行 log，甚至報告母版的 dirty 狀態。
- **重現步驟**：
  1. 將 `.agents/skills/session-closeout` 建立符號連結至 `~/.gemini/config/skills/session-closeout`。
  2. 在任意獨立專案目錄中，由 Agent 執行收尾腳本。
- **影響範圍**：所有透過全域 Symlink 調用 `session-closeout` 的子專案與獨立專案。

## 2. 根本原因

在 `.agents/skills/session-closeout/scripts/closeout_runner.py` 中，判定專案根目錄的原始寫法為：
```python
SCRIPT_ROOT = Path(__file__).resolve().parents[4]
```
`Path.resolve()` 會自動解開符號連結（symlink resolution），導致當腳本經由 `~/.gemini/config/skills/...` 調用時，解析後的物理路徑直接回到母版 `01 project_template`，忽略了使用者實際下達指令的當前工作目錄。

## 3. 修正或規避方式

修正 `find_root()` 函式，優先以當前工作目錄 `Path.cwd()` 向上搜尋 `.agents/project.toml`：
```python
def find_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agents" / "project.toml").exists():
            return candidate
    return SCRIPT_ROOT
```
程式碼已於 commit `f5a7d9e` 修復，加註 `Refs: ISSUE-004`。

## 4. 防回歸

測試 `tests/test_framework.py` 中的 `WorkflowTest.test_closeout_lists_docs_and_pushes` 與目錄解析測試，確保在不同工作目錄下皆能鎖定當前專案根目錄。
