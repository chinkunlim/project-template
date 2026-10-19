#!/usr/bin/env python3
"""Migration planner: inventory an old project in `legacy/` and write `docs/migration/MIGRATION.md`.

Purpose:
    When an old project is moved into a new template folder, every file must end up in
    the new structure and meet every rule of the new project (standards, docs layout,
    comments, types, tests). This module:
      - classifies each `legacy/` file and suggests where it belongs;
      - groups files into ordered batches that can each be migrated, tested and committed;
      - converts dependency files into `uv add` / `pnpm` commands;
      - lists risks (tracked secrets, large files);
      - renders `MIGRATION.md` with per-batch and final completion criteria.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BATCH_ORDER = (
    "deps", "config", "db", "domain", "adapters", "services", "entrypoints", "flask", "web", "gas", "tests", "docs", "other",
)
BATCH_TITLES = {
    "deps": "依賴與設定檔轉換（uv / pnpm / .env.example / Brewfile）",
    "config": "config 層（設定、環境變數讀取）",
    "db": "資料庫（SQLAlchemy 模型 → adapters/db、Alembic 遷移 → alembic/versions、SQLite → data/）",
    "domain": "domain 層（資料模型、純邏輯）",
    "adapters": "adapters 層（外部 API、資料庫、檔案 I/O）",
    "services": "services 層（業務流程）",
    "entrypoints": "entrypoints 層（CLI、HTTP、排程入口）",
    "flask": "Flask → FastAPI 改寫（路由、請求驗證、模板 / 靜態檔）",
    "web": "web 前端（HTML / CSS / JS）",
    "gas": "GAS（Apps Script）",
    "tests": "測試",
    "docs": "文件（README、規格、決策、已知問題）",
    "other": "其他（資料、資源、需人工判斷）",
}
LAYER_KEYWORDS = (
    ("config", ("config", "settings", "setting", "env", "constants", "const")),
    ("domain", ("model", "models", "schema", "schemas", "entity", "entities", "types", "dto", "domain")),
    ("adapters", ("api", "client", "clients", "adapter", "adapters", "db", "database", "repository", "repo",
                  "storage", "store", "http", "gateway", "provider", "crud", "dao")),
    ("entrypoints", ("main", "cli", "app", "server", "routes", "route", "router", "views", "handler", "handlers",
                     "bot", "manage", "run", "wsgi", "asgi", "__main__")),
)
DEP_FILES = {"requirements.txt", "requirements-dev.txt", "requirements_dev.txt", "pyproject.toml", "setup.py", "setup.cfg",
             "Pipfile", "Pipfile.lock", "poetry.lock", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
             ".env.example", "Brewfile", ".python-version", ".nvmrc", ".gitignore", ".clasp.json", "appsscript.json"}
SECRET_NAMES = re.compile(r"(^|/)(\.env(\..+)?|\.clasprc\.json|credentials\.json|service-account.*\.json|.*\.(pem|key|p12))$")
WEB_EXTS = {".html", ".htm", ".css", ".scss"}
LARGE_FILE_BYTES = 5 * 1024 * 1024
ORM_MARKERS = ("db.Model", "DeclarativeBase", "declarative_base(", "Mapped[", "mapped_column(", "sqlalchemy.orm")
FLASK_ROUTE_MARKERS = ("@app.route", "Blueprint(", ".route(", "Flask(__name__")
DB_FILE_EXTS = {".db", ".sqlite", ".sqlite3"}
DATA_DIR_NAMES = {"data", "input", "inputs", "output", "outputs", "inbox", "processed", "dataset", "datasets", "logs"}
DATA_FILE_EXTS = {
    ".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a", ".flac",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".feather", ".h5", ".pkl", ".npy", ".npz",
}


def is_data_path(rel: str) -> bool:
    """Tell whether an old-project path is data (goes to DATA_DIR, not into the new repo).

    Args:
        rel: Path relative to the old project root.

    Returns:
        True for files under data-like top-level folders or with data extensions.
    """
    path = PurePosixPath(rel)
    return path.parts[0].lower() in DATA_DIR_NAMES or path.suffix.lower() in DATA_FILE_EXTS


def data_moves(data_paths: list[str], old_root: str, data_dir: str) -> list[tuple[str, str]]:
    """Plan copy commands that move old data into the new project's DATA_DIR.

    Args:
        data_paths: Old-project paths classified as data.
        old_root: Old project folder (still holds the only copy of the data).
        data_dir: New project's DATA_DIR (e.g. `~/project-data/app`).

    Returns:
        `(description, shell command)` pairs, one per top-level data folder or loose file.
    """
    tops: dict[str, int] = {}
    for rel in data_paths:
        top = PurePosixPath(rel).parts[0]
        tops[top] = tops.get(top, 0) + 1
    steps = []
    for top, count in sorted(tops.items()):
        is_dir = count > 1 or (Path(old_root) / top).is_dir()
        dest = {"output": "output", "outputs": "output", "processed": "output", "logs": "logs"}.get(top.lower(), "input")
        src = f'"{old_root}/{top}/"' if is_dir else f'"{old_root}/{top}"'
        target = f"{data_dir}/{dest}/{top}/" if is_dir and dest == "input" and top.lower() not in ("input", "inputs", "inbox") else f"{data_dir}/{dest}/"
        steps.append((f"`{top}`（{count} 個檔案）→ `{target}`", f'mkdir -p {target} && rsync -a {src} {target}'))
    return steps


@dataclass
class PlanContext:
    """Facts about the old project that change how files are classified.

    Attributes:
        pkg: Python package name of the new project.
        is_gas: Whether the old project contains `appsscript.json`.
        uses_flask: Whether the old project depends on Flask.
        mode: `maintain` (keep Flask) or `develop` (rewrite Flask to FastAPI).
    """

    pkg: str
    is_gas: bool = False
    uses_flask: bool = False
    mode: str = "maintain"


@dataclass
class Entry:
    """One legacy file and where it should go.

    Attributes:
        path: Path relative to the project root (starts with `legacy/`).
        batch: Batch key from `BATCH_ORDER`.
        target: Suggested destination (folder or file) in the new structure.
    """

    path: str
    batch: str
    target: str


def _layer_for(stem_parts: list[str]) -> str:
    """Guess the architectural layer of a Python module from its path words.

    Args:
        stem_parts: Lower-case words from the file path (folders and file stem).

    Returns:
        Layer name; `services` when nothing matches.
    """
    words = set(stem_parts)
    for layer, keys in LAYER_KEYWORDS:
        if words & set(keys):
            return layer
    return "services"


def _classify_python(rel: str, words: list[str], text: str, ctx: PlanContext) -> Entry:
    """Classify a Python module by content first (ORM models, Flask routes), then by name.

    Args:
        rel: Path relative to `legacy/`.
        words: Lower-case words from the path.
        text: File content (may be empty).
        ctx: Old-project facts.

    Returns:
        The file's batch and suggested target.
    """
    legacy = f"legacy/{rel}"
    if any(m in text for m in ORM_MARKERS):
        return Entry(legacy, "db", f"src/{ctx.pkg}/adapters/db/")
    if ctx.uses_flask and any(m in text for m in FLASK_ROUTE_MARKERS):
        if ctx.mode == "develop":
            return Entry(legacy, "flask", f"src/{ctx.pkg}/entrypoints/http/（改寫成 FastAPI）")
        return Entry(legacy, "entrypoints", f"src/{ctx.pkg}/entrypoints/http/（保留 Flask）")
    layer = _layer_for(words)
    return Entry(legacy, layer, f"src/{ctx.pkg}/{layer}/")


def _classify_frontend(rel: str, path: PurePosixPath, ctx: PlanContext) -> Entry | None:
    """Classify GAS, Flask template/static and plain web files.

    Args:
        rel: Path relative to `legacy/`.
        path: The same path as a `PurePosixPath`.
        ctx: Old-project facts.

    Returns:
        An entry, or None when the file is not a front-end file.
    """
    legacy, suffix = f"legacy/{rel}", path.suffix.lower()
    if suffix == ".gs" or (ctx.is_gas and suffix in (".js", ".html")):
        return Entry(legacy, "gas", "gas/src/")
    in_flask_dir = ctx.uses_flask and ("templates" in path.parts or "static" in path.parts)
    if in_flask_dir and ctx.mode == "maintain":
        sub = "templates" if "templates" in path.parts else "static"
        return Entry(legacy, "entrypoints", f"src/{ctx.pkg}/entrypoints/http/{sub}/（Flask 用）")
    if in_flask_dir:
        return Entry(legacy, "flask", "web/（靜態檔）或 src/<pkg>/entrypoints/http/templates/（Jinja2）")
    if suffix in WEB_EXTS or suffix in (".js", ".mjs", ".ts", ".jsx", ".tsx"):
        return Entry(legacy, "web", "web/")
    return None


def classify(rel: str, ctx: PlanContext, text: str = "") -> Entry:
    """Classify one legacy file.

    Args:
        rel: Path relative to `legacy/`.
        ctx: Old-project facts (package name, GAS, Flask, mode).
        text: File content for Python files (used to spot ORM models and Flask routes).

    Returns:
        The file's batch and suggested target.
    """
    path = PurePosixPath(rel)
    name, suffix = path.name, path.suffix.lower()
    words = [w for part in [*path.parts[:-1], path.stem] for w in re.split(r"[^a-z0-9]+", part.lower()) if w]
    legacy = f"legacy/{rel}"
    if name in DEP_FILES or name.startswith("requirements"):
        return Entry(legacy, "deps", "pyproject.toml / package.json / .env.example（轉換後刪除舊檔）")
    if {"alembic", "migrations"} & set(path.parts) or name == "alembic.ini":
        return Entry(legacy, "db", "alembic/versions/（保留舊的 revision，取代範例 0001）")
    if suffix in DB_FILE_EXTS:
        return Entry(legacy, "db", "data/（資料檔不進 git）")
    if "test" in words or "tests" in words or re.match(r"(test_.*|.*_test)\.py$|.*\.(test|spec)\.[cm]?[jt]sx?$", name):
        return Entry(legacy, "tests", "tests/" if suffix == ".py" else "test/")
    if suffix == ".py":
        return _classify_python(rel, words, text, ctx)
    frontend = _classify_frontend(rel, path, ctx)
    if frontend:
        return frontend
    if suffix in (".md", ".rst", ".txt") and path.parent == PurePosixPath("."):
        return Entry(legacy, "docs", "README.md / docs/specs/ / docs/architecture/ARCHITECTURE.md")
    if suffix in (".md", ".rst"):
        return Entry(legacy, "docs", "docs/specs/ 或 docs/adr/ 或 docs/known-issues/")
    return Entry(legacy, "other", "依用途判斷（資料 → data/，靜態資源 → web/ 或 src/<pkg>/）")


def requirements_specs(text: str) -> list[str]:
    """Extract package specs from a `requirements.txt`.

    Args:
        text: File content.

    Returns:
        Specs such as `requests>=2.31` (options, includes and comments are skipped).
    """
    specs = []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith(("#", "-")):
            specs.append(line)
    return specs


def dependency_commands(legacy_root: Path) -> list[tuple[str, str]]:
    """Build the dependency conversion steps for the old project.

    Args:
        legacy_root: The `legacy/` folder.

    Returns:
        `(description, shell command)` pairs; commands contain no `#` (zsh-paste safe).
    """
    steps = []
    for req_name, dev in (("requirements.txt", False), ("requirements-dev.txt", True), ("requirements_dev.txt", True)):
        req = legacy_root / req_name
        specs = requirements_specs(req.read_text(encoding="utf-8", errors="replace")) if req.exists() else []
        if specs:
            quoted = " ".join(f"'{s}'" for s in specs)
            steps.append((f"從 `{req_name}` 加入{'開發' if dev else ''}依賴（確認版本後執行）", f"uv add {'--dev ' if dev else ''}{quoted}"))
    pkg_json = legacy_root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        for key, flag in (("dependencies", ""), ("devDependencies", "-D ")):
            deps = data.get(key) or {}
            if deps:
                specs = " ".join(f"'{n}@{v}'" for n, v in deps.items())
                steps.append((f"從舊 `package.json` 的 {key} 加入（在 package.json 所在資料夾執行）", f"pnpm add {flag}{specs}"))
    if (legacy_root / "pyproject.toml").exists() or (legacy_root / "setup.py").exists() or (legacy_root / "Pipfile").exists():
        steps.append(("舊專案有 pyproject.toml / setup.py / Pipfile：把其中的依賴逐一用 uv add 加入，再比對版本", "uv tree"))
    return steps


def env_keys(legacy_root: Path) -> list[str]:
    """Read variable names (never values) from the old `.env.example`.

    Args:
        legacy_root: The `legacy/` folder.

    Returns:
        Variable names in file order.
    """
    example = legacy_root / ".env.example"
    if not example.exists():
        return []
    lines = example.read_text(encoding="utf-8", errors="replace").splitlines()
    return [ln.split("=", 1)[0].strip() for ln in lines if "=" in ln and not ln.strip().startswith("#")]


def find_risks(root: Path, entries: list[Entry]) -> list[str]:
    """List migration risks: tracked secret files and large files.

    Args:
        root: Project root.
        entries: Classified legacy files.

    Returns:
        Human-readable risk lines.
    """
    risks = []
    for e in entries:
        if SECRET_NAMES.search(e.path) and not e.path.endswith(".env.example"):
            risks.append(f"🔴 `{e.path}` 看起來是機密檔且被 git 追蹤：從 repo 移除（`git rm --cached`），**並更換其中的金鑰**（舊 commit 歷史仍保有內容）。")
        size = (root / e.path).stat().st_size if (root / e.path).exists() else 0
        if size > LARGE_FILE_BYTES:
            risks.append(f"🟡 `{e.path}` 大小 {size // 1024 // 1024} MB：確認是否該放進 git（資料檔可改放外部儲存）。")
    return risks


def build_entries(root: Path, legacy_files: list[str], ctx: PlanContext) -> list[Entry]:
    """Classify every legacy file.

    Args:
        root: Project root.
        legacy_files: Paths relative to the project root (all start with `legacy/`).
        ctx: Old-project facts; `is_gas` is filled in here.

    Returns:
        Entries sorted by batch order, then path.
    """
    ctx.is_gas = any(PurePosixPath(f).name == "appsscript.json" for f in legacy_files)
    entries = []
    for f in legacy_files:
        path = root / f
        text = path.read_text(encoding="utf-8", errors="replace") if f.endswith(".py") and path.is_file() else ""
        entries.append(classify(f[len("legacy/"):], ctx, text))
    return sorted(entries, key=lambda e: (BATCH_ORDER.index(e.batch), e.path))


def group_batches(entries: list[Entry]) -> list[tuple[str, list[Entry]]]:
    """Group entries into non-empty batches in migration order.

    Args:
        entries: Output of `build_entries()`.

    Returns:
        `(batch key, entries)` pairs.
    """
    return [(b, [e for e in entries if e.batch == b]) for b in BATCH_ORDER if any(e.batch == b for e in entries)]


DONE_PER_BATCH = """每一批都必須做到（做到才可 `agentctl task done`）：

1. **兩個 commit：先搬、再整理**（保證 `git log --follow` 與 blame 追得到舊歷史）：
   - 第一個 commit 只用 `git mv legacy/舊路徑 新路徑` 搬移，內容一個字都不改：`agentctl commit --bump none -m "refactor(migration): move <檔名> from legacy"`。pre-commit 只對「從 legacy/ 原樣搬入」的檔案暫時放行註解、大小與分層問題（秘密與禁用套件仍會擋）。
   - 下一個 commit 必須把這批檔案全部整理到符合規範（第 2 點），否則任何 commit 與 `agentctl check` 都過不了，所以一批只搬少量檔案。
2. 依新規範修改：
   - **註解**：檔案開頭用途說明；每個函數/類別的說明、每個參數（`Args:` / `@param`）與回傳值（[`CODING_PRINCIPLES.md`](../standards/CODING_PRINCIPLES.md) §0）。
   - **型別**：Python 參數與回傳值都有型別，`uv run mypy` 通過（strict）。
   - **分層**：放到正確的層；環境變數只在 `config` 層讀取，其他層改收 `AppConfig` 參數（[`ARCHITECTURE_RULES.md`](../standards/ARCHITECTURE_RULES.md)）。
   - **函式大小**：符合 `[quality]` 門檻；`print` 除錯改用 logging。
   - **秘密**：金鑰移到 `.env`，`.env.example` 只留變數名稱。
   - **依賴**：只用 `uv add` / `pnpm add`（[`ENVIRONMENT_AND_DEPENDENCIES.md`](../standards/ENVIRONMENT_AND_DEPENDENCIES.md)）。
   - **本機服務**：綁 `127.0.0.1`，網址不用 `localhost`。
   - **測試**：搬移的程式要有測試（沿用舊測試或補寫，[`TESTING_AND_QUALITY.md`](../standards/TESTING_AND_QUALITY.md)）。
3. `python3 scripts/agentctl.py check` 與專案測試全部通過。
4. 下方「檔案清單」把這批的 ☐ 改成 ☑；過程中的重要決策寫 ADR、發現的舊 bug 寫 known-issue。
5. `python3 scripts/agentctl.py commit --agent <名字> --task TASK-NNN`，再 `agentctl task done TASK-NNN --summary ...`。
"""

DONE_FINAL = """全部完成才算遷移成功（`python3 scripts/agentctl.py migration --verify` 會逐項檢查）：

- [ ] `legacy/` 已刪除（所有檔案都搬到新結構或確認不需要）。
- [ ] 舊資料已依 §4.5 複製到 `DATA_DIR`，程式透過 config 讀取路徑，專案資料夾內沒有資料檔。
- [ ] 沒有 `requirements.txt`、`package-lock.json`、`yarn.lock`、`Pipfile`：依賴只在 `pyproject.toml` + `uv.lock`、`package.json` + `pnpm-lock.yaml`。
- [ ] `python3 scripts/agentctl.py check` 全部通過（註解、分層、秘密、lint、mypy strict、目錄樹）。
- [ ] 專案測試全部通過。
- [ ] 所有遷移任務卡都是 `done`。
- [ ] 模板的範例程式（`greeting` 相關的 services / domain / cli / api / 資料表 `greetings` 與其 Alembic revision、測試）已刪除或換成真正的程式。
- [ ] `README.md` 改寫為這個專案的說明；`docs/architecture/ARCHITECTURE.md` 有系統概覽；主要功能在 `docs/specs/` 有規格。
- [ ] 舊專案已知的問題記在 `docs/known-issues/`；遷移中的重要決策記在 `docs/adr/`。
- [ ] `.env.example` 列出所有需要的變數（只有名稱）。
- [ ] 最後執行 `agentctl closeout`（本機對話紀錄＋交接看板記下遷移完成）。
"""


def render_migration_md(source: dict[str, str], entries: list[Entry], extras: dict) -> str:
    """Render `docs/migration/MIGRATION.md`.

    Args:
        source: Old project info: `path`, `origin`, `commit`, `history` (`kept` / `none`).
        entries: Classified legacy files.
        extras: `batches` (list of `(batch, task_id, entries)`), `deps` (dependency steps),
            `env_keys` (old variable names), `risks` (risk lines).

    Returns:
        Markdown text.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode_text = {
        "maintain": "維護模式：保留 Flask，只整理結構與規範（之後要繼續開發時執行 `python3 scripts/agentctl.py migration --develop`）",
        "develop": "開發模式：Flask 必須全部改寫成 FastAPI（對照表：[`FLASK_TO_FASTAPI.md`](../../.agents/skills/legacy-migration/FLASK_TO_FASTAPI.md)）",
    }[source.get("mode", "maintain")]
    history = "已保留（新 repo 由舊 repo clone；舊檔案以 `git mv` 移到 `legacy/`，`git log --follow` 可追溯）" if source["history"] == "kept" else "未保留（舊專案不是 git repo）"
    lines = [
        "# 專案遷移計畫 (MIGRATION)",
        "",
        "> 舊專案的檔案目前在 `legacy/`（原封不動）。依下方批次逐一搬到新結構，**每一批都要符合新專案的所有規範**，全部完成後刪除 `legacy/`。",
        "",
        "## 1. 來源",
        "",
        f"- **舊專案位置**：`{source['path']}`",
        f"- **舊專案遠端**：`{source.get('origin') or '-'}`",
        f"- **遷移時的最後 commit**：`{source.get('commit') or '-'}`",
        f"- **git 歷史**：{history}",
        f"- **模式**：{mode_text}" + ("" if source.get("uses_flask") == "yes" else "（舊專案未使用 Flask）"),
        f"- **建立時間**：{now}",
        f"- **檔案數**：{len(entries)}",
        "",
        "## 2. 完成標準",
        "",
        "### 每一批",
        "",
        DONE_PER_BATCH,
        "### 整個遷移",
        "",
        DONE_FINAL,
        "## 3. 批次",
        "",
        "| 順序 | 任務 | 內容 | 檔案數 |",
        "|---|---|---|---|",
    ]
    for idx, (batch, task_id, items) in enumerate(extras["batches"], start=1):
        lines.append(f"| {idx} | `{task_id}` | {BATCH_TITLES[batch]} | {len(items)} |")
    lines += ["", "## 4. 依賴轉換", ""]
    if extras["deps"]:
        for desc, cmd in extras["deps"]:
            lines += [desc + "：", "", "```bash", cmd, "```", ""]
    else:
        lines += ["（舊專案沒有可自動轉換的依賴檔）", ""]
    if extras["env_keys"]:
        lines += ["舊 `.env.example` 的變數（加到新 `.env.example`，只寫名稱）：" + "、".join(f"`{k}`" for k in extras["env_keys"]), ""]
    lines += ["## 4.5 資料搬到 DATA_DIR（資料不進新專案）", ""]
    if extras.get("data_moves"):
        lines += [
            "舊專案的資料**沒有**搬進 `legacy/`，也不在新專案資料夾內；唯一的副本仍在舊專案（未被修改）。確認 `.env` 的 `DATA_DIR` 後，依序複製：",
            "",
        ]
        for desc, cmd in extras["data_moves"]:
            lines += [desc + "：", "", "```bash", cmd, "```", ""]
        lines += ["複製完成並確認新專案能讀到資料後，再決定是否刪除舊專案的資料（請自行確認，工具不會刪除）。", ""]
    else:
        lines += ["- 舊專案沒有偵測到資料檔。", ""]
    lines += ["## 5. 風險", ""]
    lines += [f"- {r}" for r in extras["risks"]] or ["- 未發現機密檔或大型檔案。"]
    lines += ["", "## 6. 檔案清單", "", "| 狀態 | 舊檔案 | 建議位置 | 批次 |", "|---|---|---|---|"]
    lines += [f"| ☐ | `{e.path}` | `{e.target}` | {e.batch} |" for e in entries]
    return "\n".join(lines) + "\n"
