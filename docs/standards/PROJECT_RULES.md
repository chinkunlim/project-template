# 本專案專屬規則 (PROJECT_RULES)

> 規則分兩層：`docs/standards/` 的其他文件是**所有專案通用**的規範（由專案模板提供，`agentctl update` 會更新）；
> 本檔是**只適用這個專案**的規則，由這個專案自己維護，模板更新時不會被覆蓋。每次開工都要讀。

## 1. 領域知識與術語

- **母版**：這個資料夾（`01 project_template`）。它本身也是一個用自己產生的專案（見 [ADR-001](../adr/001-template-uses-project-layout.md)）。
- **框架檔案**：每個專案都會拿到、由 `agentctl update` 更新的檔案：`.agents/{bin,hooks,lib,skills}/`、`docs/standards/`（本檔除外）、`scripts/agentctl.py`。在母版改它們，就是在改所有專案。
- **母版自己的程式**：`src/project_template/`（產生器、語言範本 `packs/`、網頁、MCP），以及 `scripts/` 裡的啟動器。不會複製到專案。

## 2. 本專案特有的規則

- 改框架檔案時，同時想清楚**已存在的專案**怎麼拿到這個修改（`scripts/update_all.py`）；改了檔案位置或更新流程，要升 `FRAMEWORK_VERSION`（`.agents/lib/project_config.py`）並同步 `pyproject.toml` 的 `version`。
- 框架檔案只用 Python 標準函式庫（專案可能還沒有 `.venv`）。只有網頁與 MCP 用 FastAPI / MCP。
- `scripts/` 的啟動器只負責把 `src/` 加進 import 路徑並呼叫 `entrypoints`，不放邏輯。
- 改了產生的檔案內容（`packs/`），用 `python3 -m unittest discover -s tests -v` 跑完整測試；需要網路的實裝測試見 README §7。
- 網頁、JSON API、MCP 三個入口呼叫同一組 `services/template_service.py`；新增功能時三個一起接。

## 3. 和通用規範不同的例外（要寫理由）

- **不跑 `ruff format`、行長 160**：`packs/` 裡大部分是新專案檔案的文字範本，它們的換行就是產生出來的檔案的換行；`packs/` 與 `tests/`（測試資料）不檢查 E501。
- **`.local/projects.json`**（建立過的專案清單）放在母版內、不進 git，而不是 `DATA_DIR`：它記錄的是這台電腦上的專案位置，跟著母版走。

## 4. 禁止事項

- 不要在 `docs/standards/` 放只適用母版的內容（會被複製到每個專案）；母版專屬的寫在本檔。
- 不要讓 `src/project_template/` 以外的地方 import 母版程式；框架檔案不可依賴 `src/`。
