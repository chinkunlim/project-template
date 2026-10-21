# ADR-002：所有動作作用在同一組追蹤的專案（資料夾＋登記清單）

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-21
- **Agent**：`claude-code`
- **任務**：`-`

## 1. 背景與問題

母版用兩種方式追蹤專案：掃描母版所在的資料夾（深度 3），以及登記清單 `.local/projects.json`（`init` / `migrate` 會寫入）。原本只有總覽（`overview()`）合併兩者；專案清單、改進建議、框架更新預覽與套用、`scripts/update_all.py`、`scripts/collect_feedback.py` 都只掃描資料夾。結果是：放在別處的專案會出現在總覽，但框架更新和改進建議都漏掉它。另外，用別的方式取得的專案（例如 clone 下來的）無法加入登記清單；「未推送 / 落後」也只反映上次 fetch 的結果，網頁上沒辦法更新。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 各動作各自決定要不要讀登記清單 | 改動少 | 同樣的問題會再發生；每個入口的行為可能不同 |
| B. services 提供一個 `tracked_projects()`（資料夾掃描＋登記清單中仍存在、且有 `.agents/framework.lock` + `scripts/agentctl.py` 的資料夾），所有動作都用它 | 網頁、API、MCP、指令列看到同一組專案；判斷「是不是專案」只有一處（`is_project()`） | 指令列工具的預設行為改變（見第 3 節） |
| C. 把登記清單當唯一來源，不再掃描資料夾 | 只有一個來源 | 手動複製進資料夾、還沒登記的專案會消失；與 v3.2 以前的行為不相容 |

## 3. 決策與理由

採用 B。

- `services/update_all.py`：`is_project()`、`registered_projects()`、`tracked_projects(roots, depth, registered=True)`；`template_service.tracked()`、`overview()`、`list_projects()`、`feedback()`、`update_preview()` 都用它，`update_apply_steps()` 執行 `update_all.py <root> --registered`。
- **指令列的預設**：`scripts/update_all.py`、`scripts/collect_feedback.py` 不加資料夾時，包含登記的專案（「所有專案」的直覺意思）；指定資料夾時只掃描那些資料夾，要包含登記的專案再加 `--registered`。這樣指定資料夾的舊用法（和測試）結果不變。
- **加入既有專案**（`add_existing()`、`POST /api/registry/add`、MCP `register_project`）：只接受 `is_project()` 為真的資料夾，母版本身與其他資料夾一律拒絕（舊專案請用遷移）；只寫登記清單、不改專案，需要 `confirm`，登記方式記成 `how = existing`。
- **git fetch 不需要 `confirm`**（`fetch_steps()`、`POST /api/fetch`、MCP `refresh_remote_status`）：它只更新 remote-tracking refs，不改檔案、不 commit、不推送，效果和「重新整理」一樣是讀取遠端狀態。用 `GIT_TERMINAL_PROMPT=0` 避免等待輸入密碼；不加 `--prune`（不刪除任何 ref）；工作以 `keep_going` 執行，一個專案失敗（例如離線）不會中斷其他專案。

## 4. 影響與代價

- 指令列工具不加資料夾時，結果可能比以前多（多了登記的專案）。README §5 已說明。
- 登記清單的位置可以用 `TEMPLATE_REGISTRY_FILE` 改（`config.settings.registry_file()`）；測試一律指向暫存檔，不會讀寫使用者真正的 `.local/projects.json`。
- 新增會改變狀態的動作時，要用 `tracked()` / `tracked_projects()` 取得專案，並同時接到三個入口（`web_routes.py`、`template_mcp.py`、網頁），Open WebUI 工具檔（`openwebui_tool.py`）也要跟著加。
- 測試：`TrackedProjectsTest`（登記在資料夾外的專案會被預覽與更新；不合格的資料夾被拒絕）、`WebUiIntegrationTest`（API 的 400 / 428 與 MCP 工具清單）。
