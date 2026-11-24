# 需求與規格 (Specs)

一個功能一份規格，先寫規格再實作；實作時在任務卡與 commit 中引用規格檔名。

- 新增：複製 [`_TEMPLATE.md`](_TEMPLATE.md) 為 `NNN-<slug>.md`（例如 `001-login-api.md`），並在下表加一列。

> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `NNN-<slug>.md`。整個專案只有根目錄一份 `README.md`。

## 規格清單

| 規格 | 狀態 | 說明 |
|---|---|---|
| [`001-project-web-launcher.md`](001-project-web-launcher.md) | Implemented | 總控台網頁整合各專案 FastAPI 啟動器、MCP/OpenAPI 三入口與 `scripts/hub.py` 單一指令集 |
| [`002-master-child-linkage.md`](002-master-child-linkage.md) | Implemented | 清除母版全部 Code Review Guard 警告，並實作母版⇄子專案自動發現 Web、更新 Graphify、狀態掃描與回饋雙向連動 |
