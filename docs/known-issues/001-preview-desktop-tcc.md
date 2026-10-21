# ISSUE-001：Claude 瀏覽器預覽無法啟動 ~/Desktop 裡的網頁伺服器

- **狀態**：🟡 已規避 (Mitigated)
- **發現日期**：2026-10-21
- **Agent**：`claude-code`
- **任務**：`-`

## 1. 現象

在 Claude Code 桌面版用瀏覽器預覽（`preview_start`）啟動 `.claude/launch.json` 的 `template-web-ui` 時，伺服器一啟動就結束。

- **錯誤訊息**：`/Library/Developer/CommandLineTools/usr/bin/python3: can't open file 'scripts/web_ui.py': [Errno 1] Operation not permitted`（結束碼 2）；改用 `python3 -c ...` 啟動則在 import 時出現 `PermissionError: [Errno 1] Operation not permitted`。
- **重現步驟**：母版放在 `~/Desktop/projects/01 project_template`，在桌面版的 Code 分頁讓 Agent 執行 `preview_start {name: "template-web-ui"}`。
- **影響範圍**：只影響 Agent 用預覽工具驗證網頁。使用者自己在終端機執行 `python3 scripts/web_ui.py` 正常；Agent 用 Bash 執行指令與測試也正常。

## 2. 根本原因

macOS 的隱私保護（TCC）限制 App 存取 `~/Desktop`、`~/Documents`、`~/Downloads`。預覽工具啟動伺服器的程序沒有取得「桌面」資料夾的存取權限，所以連工作目錄都無法讀取（`Operation not permitted` 是 TCC 拒絕，不是一般的檔案權限 `Permission denied`）。程式本身沒有問題。

## 3. 修正或規避方式

不改程式。Agent 要在預覽中驗證網頁時：

1. 把目前的程式複製到 Agent 的暫存資料夾（排除 `.git`、`.local`、`.venv`、`.skills-cache`），例如 `rsync -a --exclude .git --exclude .local --exclude .venv --exclude .skills-cache ./ <暫存>/projects/tpl/`；
2. 在 `.claude/launch.json` 暫時加一組設定：`python3 -I <暫存>/projects/tpl/scripts/web_ui.py --no-browser --port <埠號>`（`-I` 讓 Python 不讀取無法存取的工作目錄）；
3. 複本沒有 `.local/`，登記清單是空的，因此測試「加入既有專案」不會改到使用者真正的 `.local/projects.json`；
4. 驗證完停止伺服器，並移除暫時加的設定。

另一種做法是在「系統設定 → 隱私權與安全性 → 檔案和資料夾 / 完整磁碟取用權限」允許 Claude 存取桌面，或把專案資料夾移出 `~/Desktop`；這由使用者決定。

## 4. 防回歸

這是電腦環境的限制，沒有自動化測試。網頁與 API 的行為由 `WebUiIntegrationTest`（`TEMPLATE_UV_TESTS=1`）以子程序啟動伺服器驗證，不受這個限制影響。
