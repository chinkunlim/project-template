# ISSUE-002：Python 路徑有空格時，migration --verify 的 check 失敗

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-10-21
- **Agent**：`claude-code`
- **任務**：`-`

## 1. 現象

在母版用 `uv run python -m unittest discover -s tests`（也就是 `agentctl finish` 的測試指令）執行時，兩個測試失敗；用系統的 `python3 tests/test_framework.py` 則通過。

- **錯誤訊息**：`/bin/sh: /Users/limchinkun/Desktop/projects/01: No such file or directory`；`agentctl migration --verify` 顯示「❌ agentctl check 通過」。
- **重現步驟**：Python 位於含空格的路徑（例如母版 `~/Desktop/projects/01 project_template/.venv/bin/python`），在遷移完成的專案執行 `agentctl migration --verify`。
- **影響範圍**：任何專案只要資料夾或 `.venv` 路徑有空格，`migration --verify` 一定判定 check 失敗；母版的 `agentctl finish` 因此無法通過。

## 2. 根本原因

`.agents/skills/legacy-migration/scripts/migration_status.py` 用 `shell=True` 執行 `f"{sys.executable} scripts/agentctl.py check"`，Python 路徑沒有加引號，shell 在空格處切開。測試 `tests/test_framework.py` 也有同樣的問題：把 `sys.executable` 直接寫進 `[commands] test`。以前多用系統的 `python3`（路徑沒有空格）跑測試，所以沒發現。

## 3. 修正或規避方式

- `migration_status.py`：改成 `shlex.quote(sys.executable)`（註解 `Refs: ISSUE-002`）。此檔是框架檔案，專案透過 `update_all.py` / `agentctl update` 拿到修正。
- `tests/test_framework.py`：新增 `PY_CMD = shlex.quote(sys.executable)`，寫入 shell 指令字串時一律用它。
- 規則：把路徑放進 `shell=True` 的指令字串時一律 `shlex.quote()`；能用 list 參數時就不要用 shell 字串。

## 4. 防回歸

在母版用 `uv run python -m unittest discover -s tests`（母版路徑本身有空格）執行 `MigrationTest.test_verify_requires_full_compliance` 與 `WorkflowTest.test_closeout_writes_local_transcript_and_summary`；`agentctl finish` 也會跑這個指令。
