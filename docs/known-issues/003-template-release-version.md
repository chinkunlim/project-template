# ISSUE-003：母版 finish --tag 只更新 pyproject.toml，不更新 FRAMEWORK_VERSION 與 uv.lock

- **狀態**：🟡 已規避 (Mitigated)
- **發現日期**：2026-10-21
- **Agent**：`claude-code`
- **任務**：`-`

## 1. 現象

母版的版本同時存在三個地方：`pyproject.toml` 的 `version`、`.agents/lib/project_config.py` 的 `FRAMEWORK_VERSION`（專案的 `.agents/framework.lock` 記錄的就是它），以及 `uv.lock` 中 `project-template` 的版本。`agentctl finish --tag` 只更新 `.agents/project.toml` `[release] version_files` 列出的 `pyproject.toml`。

- **錯誤訊息**：若直接 `finish --tag`，`TemplateLayoutTest.test_template_version_is_the_framework_version` 失敗；CI 的 `uv sync --locked` 因 lock 檔過期失敗；`update_all.py` 更新後專案仍記錄舊框架版本。
- **重現步驟**：在母版執行 `python3 scripts/agentctl.py finish --tag`。
- **影響範圍**：只有母版發版（一般專案只有 `pyproject.toml` 一個版本來源）。

## 2. 根本原因

`finish --tag` 是給一般專案用的框架工具，只認得 `pyproject.toml` / `package.json` / `Cargo.toml` / `VERSION`。母版另外把框架版本寫死在 `project_config.py`（每個專案都會拿到這個檔案），而 `_write_version_to()` 遇到 `.py` 會把整個檔案改成版本號，所以也不能把它加進 `version_files`。

## 3. 修正或規避方式

母版發版時照 `finish --tag` 的步驟手動做，三個版本一起改、一個 commit：

1. `python3 scripts/agentctl.py finish`（不加 `--tag`）確認全部 ✅；
2. 用 `project_config.release_unreleased()` 把 CHANGELOG 的 Unreleased 改成 `[X.Y.Z] - 日期`；
3. 改 `pyproject.toml` 與 `.agents/lib/project_config.py` 的 `FRAMEWORK_VERSION`，執行 `uv lock` 更新 `uv.lock`；
4. `git commit -m "chore(release): vX.Y.Z [agent:<名字>]"`，再 `git tag -a vX.Y.Z -m "Release vX.Y.Z"`。

之後若要根治，可讓 `finish.py` 在母版（有 `src/project_template/`）時一併更新 `FRAMEWORK_VERSION` 並執行 `uv lock`。

## 4. 防回歸

`TemplateLayoutTest.test_template_version_is_the_framework_version` 檢查 `pyproject.toml` 版本等於 `FRAMEWORK_VERSION`；CI 的 `uv sync --locked` 檢查 `uv.lock`。
