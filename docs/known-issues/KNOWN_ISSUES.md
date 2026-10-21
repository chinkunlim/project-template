# 已知問題 (Known Issues)

記錄「踩過的坑」：值得記住的 bug、外部服務的怪行為、環境問題，以及它們的根本原因與修正方式。
除錯時先查這裡：`grep -rn "關鍵字" docs/known-issues .agents/conversations`（後者只在本機）。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-issue <slug> --title "標題" --summary "錯誤訊息" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在修正的程式碼註解加 `Refs: ISSUE-NNN`，並寫防回歸測試。
- 狀態：🔴 未解決 (open) → 🟡 已規避 (mitigated) → 🟢 已根治 (resolved)

> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `NNN-<slug>.md`。整個專案只有根目錄一份 `README.md`。

## 總表

| ISSUE | 狀態 | 標題 | 現象 | 程式與測試 |
|---|---|---|---|---|
| [ISSUE-001](001-preview-desktop-tcc.md) | 🟡 已規避 (Mitigated) | Claude 瀏覽器預覽無法啟動 ~/Desktop 裡的網頁伺服器 | preview_start 啟動 template-web-ui 失敗：can't open file 'scripts/web_ui.py': [Errno 1] Operation not permitted | 無程式修改（macOS TCC）；規避方式見檔案；`WebUiIntegrationTest` 不受影響 |
| [ISSUE-002](002-unquoted-python-path.md) | 🟢 已根治 (Resolved) | Python 路徑有空格時，migration --verify 的 check 失敗 | /bin/sh: /Users/limchinkun/Desktop/projects/01: No such file or directory | `.agents/skills/legacy-migration/scripts/migration_status.py`；`tests/test_framework.py`（`PY_CMD`、`MigrationTest`） |
| [ISSUE-003](003-template-release-version.md) | 🟡 已規避 (Mitigated) | 母版 finish --tag 只更新 pyproject.toml，不更新 FRAMEWORK_VERSION 與 uv.lock | 發版後 pyproject 與 FRAMEWORK_VERSION 不一致，專案仍記錄舊框架版本，CI uv sync --locked 失敗 | 無程式修改；發版步驟見檔案；`TemplateLayoutTest`、CI `uv sync --locked` |
