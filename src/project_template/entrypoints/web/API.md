# 母版網頁 JSON API 與 MCP（`scripts/web_ui.py`）

網頁、Open WebUI 工具（`src/project_template/entrypoints/openwebui_tool.py`）與其他程式共用同一組 API。

- 位址：`http://127.0.0.1:8766`（`--port` 可改）；只綁 127.0.0.1。互動文件 `/docs`，規格 `/openapi.json`（Open WebUI 可直接加成 OpenAPI 工具伺服器），MCP 在 `/mcp`；stdio MCP：`python3 scripts/template_mcp.py`。
- 會修改檔案的端點（create、migrate、registry/add、push、update/apply、project-command 的 doctor-fix / setup / sync、feedback/add、feedback/status、web/start、web/stop、web/stop-all）需要 `"confirm": true`，否則回 428。
- Host 必須是 `127.0.0.1` / `localhost`（防 DNS rebinding）；Open WebUI 在 Docker 時啟動加 `--allow-host host.docker.internal`。
- POST 若帶其他網站的 `Origin` 一律 403（防惡意網頁 CSRF）；Open WebUI（`http://127.0.0.1:8080`，可用 `--allow-origin` 改）允許並開放 CORS；伺服器端程式不帶 Origin，可以呼叫。
- 一次只執行一個工作；工作執行的是一般指令（`scripts/init_project.py`、`scripts/migrate_project.py`、`agentctl …`、`scripts/update_all.py`），不會推送、不會刪檔。
- 執行指令時會移除環境變數 `DATA_DIR`，讓每個專案都用自己 `.env` 的設定。
- `root`、`parent` 省略時 = 母版所在的資料夾。總覽、專案清單、改進建議、更新預覽 / 套用與 git fetch 都作用在同一組「追蹤的專案」：`root` 底下的專案＋登記清單（`.local/projects.json`）中仍存在的專案。

## 讀取

| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/api/info` | 框架版本、母版位置、預設專案資料夾、可選的 stack / 附加功能 / skills |
| GET | `/api/overview?root=` | 總覽：資料夾裡的專案＋登記過的專案；框架版本、未 commit、未推送 / 落後（以上次 fetch 為準）、待辦任務卡數（`tasks`）、Graphify 圖譜狀態（`graphify`）、待決定建議、是否有 MCP、Web 狀態、找不到的專案 |
| GET | `/api/projects?root=` | 追蹤的專案（資料夾＋登記清單）：名稱、路徑、框架版本、未 commit 檔案數、最後 commit |
| GET | `/api/feedback?root=&all=1` | 各專案 `docs/TEMPLATE_FEEDBACK.md` 的建議（`all=1` 含已決定的） |
| GET | `/api/job` | 目前或上一個工作：`title`、`state`（running / done / failed）、`log`、`result` |
| GET | `/api/dirs?path=` | 子資料夾清單（網頁內建的資料夾瀏覽器用） |
| GET | `/api/web/services?root=` | 列出具 FastAPI 網頁的追蹤專案與即時運行狀態（`port`、`url`、`running`、`managed`、`pid`） |
| GET | `/api/web/logs?project=&lines=80` | 讀取由母版啟動之專案網頁最近日誌 |

## 動作（POST，JSON）

| 路徑 | 內容 | 說明 |
|---|---|---|
| `/api/data-preview` | `name`、`parent`、`data_dir`（選填） | 資料資料夾的實際位置與會寫入的設定值（相對路徑寫 `.env.example`；外接硬碟只寫 `.env`） |
| `/api/create` | `name`、`parent`、`data_dir`、`stack`、`addons[]`、`skills[]`、`description`、`license`（`MIT`）、`timezone`、`doctor`、`setup`、`check`、`http_port` | 建立專案；`--with api` 未填埠號時自動避開已用埠號並寫入 `[web]`（202 + 執行的指令） |
| `/api/migrate` | `source`、`name`、`parent`、`data_dir`、`mode`（`maintain` / `develop`）、`stack`、`addons[]` | 遷移舊專案（舊專案不會被修改），再執行 `doctor --fix` |
| `/api/project-command` | `path`、`command`（`status` / `scan` / `graph` / `doctor` / `doctor-fix` / `setup` / `sync` / `check`） | 在專案內執行 `agentctl` 指令（`doctor-fix` / `setup` / `sync` 需 `confirm=true`） |
| `/api/projects/graphify` | `project` / `path`、`root`、`include_master` | 對單一或全部追蹤專案執行 `agentctl graph` ＋ `graphify update .`（202 + 背景工作，完成後結果於 `/api/job`） |
| `/api/feedback/add` | `project` / `path`、`root`、`text`、`source`、`status`、`confirm` | 直接新增一列建議至目標專案（或 `master`）的 `docs/TEMPLATE_FEEDBACK.md`（需 `confirm=true`） |
| `/api/feedback/status` | `file`、`text`、`date`、`status`、`confirm` | 原地更新 `docs/TEMPLATE_FEEDBACK.md` 某列建議之狀態（`待決定` / `已採用` / `不採用`，需 `confirm=true`） |
| `/api/update/preview` | `root` | 預覽所有專案的框架更新（不修改）；結果在 `/api/job` 的 `result` |
| `/api/update/apply` | `root`、`commit`（預設 true） | 更新可更新的專案（母版要先 commit；有衝突或 check 失敗不 commit） |
| `/api/push` | `path`、`confirm` | 把專案的 commit 推送到它的 GitHub 遠端分支（需要 confirm；沒有 upstream 會回 400） |
| `/api/registry/add` | `path`、`confirm` | 加入既有專案（要有 `.agents/framework.lock` 和 `scripts/agentctl.py`，否則 400；需要 confirm；不動資料夾） |
| `/api/fetch` | `path`（選填）、`root` | 在一個或所有有遠端的追蹤專案執行 `git fetch --all`，更新「未推送 / 落後」；不改檔案，不需 confirm；結果（新的總覽）在 `/api/job` |
| `/api/registry/forget` | `path` | 從總覽移除登記（不動資料夾） |
| `/api/pick-folder` | `prompt`、`start` | 開啟 macOS 資料夾選擇視窗，回傳 `path`（取消時為空） |
| `/api/reveal` | `path` | 在 Finder 打開資料夾 |
| `/api/web/start` | `project` / `path`、`root`、`confirm` | 在背景啟動該專案 FastAPI 並等埠號就緒（需 `confirm=true`） |
| `/api/web/stop` | `project` / `path`、`root`、`confirm` | 停止由母版啟動的該專案網頁（需 `confirm=true`） |
| `/api/web/stop-all` | `root`、`confirm` | 停止所有由母版啟動的子專案網頁釋放記憶體（需 `confirm=true`） |

錯誤：400（欄位錯誤，`detail` 說明原因）、403（不是本機請求）、409（已有工作在執行）、428（需要 confirm）。
