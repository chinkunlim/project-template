#!/usr/bin/env python3
"""Starter Python configuration, logging and `pyproject.toml` text templates.

Purpose:
    Keeps `packs/python_pack.py` concise while storing the full starter source
    templates for `config/settings.py`, `config/logging_setup.py`, and `pyproject.toml`.
"""

from __future__ import annotations

PYTHON_VERSION = "3.11"

PY_SETTINGS = '''"""Configuration layer: the ONLY layer allowed to read environment variables.

Loads settings once at startup into an immutable `AppConfig` so every other layer
receives plain values instead of touching `os.environ`.

Data lives OUTSIDE the project folder: `DATA_DIR` (default `../../projects-data/{dist}`) holds
input/, output/, needs_review/, state/, db/ and logs/. The project folder only holds code,
docs and small test fixtures. A relative `DATA_DIR` is resolved from the project folder (never
from the current working directory), so the project and its data can be moved together.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = "../../projects-data/{dist}"


def resolve_data_dir(raw: str) -> Path:
    """Turn a `DATA_DIR` value into an absolute path.

    Args:
        raw: Value from `.env`; relative paths are relative to the project folder, `~` is expanded.

    Returns:
        The absolute data folder.
    """
    path = Path(raw.strip()).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


# Keys whose project `.env` value beats an inherited environment variable. `DATA_DIR` is a common
# name (e.g. Open WebUI's `export DATA_DIR=...` in ~/.zshrc) and must never point a project elsewhere.
PROJECT_FILE_WINS = ("DATA_DIR",)


def load_dotenv_file(path: Path) -> None:
    """Load `KEY=value` lines from a `.env` file.

    Variables that are already set win (so `LOG_LEVEL=DEBUG uv run ...` works), except the keys in
    `PROJECT_FILE_WINS`, where the project's own `.env` always wins.

    Args:
        path: The `.env` file (missing files are ignored).
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("\\"'")
            if key in PROJECT_FILE_WINS and value:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


@dataclass(frozen=True)
class AppConfig:
    """Immutable application settings.

    Attributes:
        app_env: Deployment environment name, e.g. `development` or `production`.
        log_level: Logging level name, e.g. `INFO` or `DEBUG`.
        log_to_file: Also write `<data_dir>/logs/app.log` and `errors.log` (default on; tests turn it off).
        timeout_seconds: Timeout for outgoing API calls.
        ollama_base_url: Local Ollama endpoint (always 127.0.0.1, never localhost / 0.0.0.0).
        data_dir: Root folder for all data, outside the project folder.{extra_attr_docs}
    """

    app_env: str = "development"
    log_level: str = "INFO"
    log_to_file: bool = True
    timeout_seconds: int = 15
    ollama_base_url: str = "http://127.0.0.1:11434"
    data_dir: Path = resolve_data_dir(DEFAULT_DATA_DIR){extra_fields}

    @property
    def input_dir(self) -> Path:
        """Folder with files waiting to be processed.

        Returns:
            `<data_dir>/input`.
        """
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """Folder for produced results.

        Returns:
            `<data_dir>/output`.
        """
        return self.data_dir / "output"

    @property
    def needs_review_dir(self) -> Path:
        """Quarantine for failed or low-confidence items (batches never stop for them).

        Returns:
            `<data_dir>/needs_review`.
        """
        return self.data_dir / "needs_review"

    @property
    def state_dir(self) -> Path:
        """Folder for progress / resume state.

        Returns:
            `<data_dir>/state`.
        """
        return self.data_dir / "state"

    @property
    def logs_dir(self) -> Path:
        """Folder for log files.

        Returns:
            `<data_dir>/logs`.
        """
        return self.data_dir / "logs"


def _csv(value: str) -> tuple[str, ...]:
    """Split a comma-separated setting.

    Args:
        value: Raw text such as `a, b`.

    Returns:
        The non-empty, stripped items.
    """
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _flag(value: str) -> bool:
    """Interpret an environment flag.

    Args:
        value: Raw text such as `1`, `true`, `yes`.

    Returns:
        True for 1 / true / yes / on (case-insensitive).
    """
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> AppConfig:
    """Read and validate configuration from `.env` and environment variables.

    Returns:
        A populated `AppConfig`.

    Raises:
        ValueError: When a numeric setting is not an integer.
    """
    load_dotenv_file(PROJECT_ROOT / ".env")
    data_dir = resolve_data_dir(os.environ.get("DATA_DIR", DEFAULT_DATA_DIR))
    logger.debug("config loaded data_dir=%s", data_dir)
    return AppConfig(
        app_env=os.environ.get("APP_ENV", "development").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        log_to_file=_flag(os.environ.get("LOG_TO_FILE", "true")),
        timeout_seconds=int(os.environ.get("API_TIMEOUT_SECONDS", "15")),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/"),
        data_dir=data_dir,{extra_loads}
    )
'''

PY_LOGGING = '''\"\"\"Logging setup shared by every entrypoint, built for tracing one run or one request.

Every line looks like
    2026-10-20 09:15:02,481 INFO    [3f9a1c2e] app.services.greeting:create_greeting:24 - greeting user='Ann'
so you can see when, how serious, which run / request, and exactly which function and line.

- Run id: one short id per process run (`setup_logging()` creates it); inside an HTTP request
  the request id (`X-Request-ID`) replaces it. Trace one run: `grep 3f9a1c2e app.log`.
- Files (with `LOG_TO_FILE=true`, outside the project in `<DATA_DIR>/logs/`):
    `app.log`    : everything at `LOG_LEVEL` and above (5 MB x 5 rotated files)
    `errors.log` : WARNING and above only, for a quick look at what went wrong
- Console output goes to stderr, so a CLI's real output on stdout stays clean.
- Uncaught exceptions and Python warnings are written to the log with their traceback.
\"\"\"

from __future__ import annotations

import contextvars
import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


def new_run_id() -> str:
    \"\"\"Create a short random id for a run or a request.

    Returns:
        Eight hexadecimal characters.
    \"\"\"
    return uuid.uuid4().hex[:8]


def set_run_id(value: str) -> contextvars.Token[str]:
    \"\"\"Use `value` as the id on every log line of the current context (e.g. one HTTP request).

    Args:
        value: Run or request id.

    Returns:
        Token for `reset_run_id()`.
    \"\"\"
    return _RUN_ID.set(value)


def reset_run_id(token: contextvars.Token[str]) -> None:
    \"\"\"Restore the id that was active before `set_run_id()`.

    Args:
        token: Token returned by `set_run_id()`.
    \"\"\"
    _RUN_ID.reset(token)


class RunIdFilter(logging.Filter):
    \"\"\"Attach the current run / request id to every log record.\"\"\"

    def filter(self, record: logging.LogRecord) -> bool:
        \"\"\"Add `record.run_id`.

        Args:
            record: Log record being emitted.

        Returns:
            Always True (nothing is filtered out).
        \"\"\"
        record.run_id = _RUN_ID.get()
        return True


def _log_uncaught(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    \"\"\"Write an uncaught exception with its traceback to the log (Ctrl-C is left alone).

    Args:
        exc_type: Exception class.
        exc: Exception instance.
        tb: Traceback.
    \"\"\"
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("uncaught").critical("uncaught exception", exc_info=(exc_type, exc, tb))


def _rotating(path: Path, max_mb: int, backups: int) -> RotatingFileHandler:
    \"\"\"Create a size-limited UTF-8 log file handler.

    Args:
        path: Log file path.
        max_mb: Size in MB before the file is rotated.
        backups: Number of old files to keep (`app.log.1` ...).

    Returns:
        The file handler.
    \"\"\"
    return RotatingFileHandler(path, maxBytes=max_mb * 1_000_000, backupCount=backups, encoding="utf-8")


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> str:
    \"\"\"Configure the root logger once per process and start a new run id.

    Args:
        level: Logging level name such as `DEBUG`, `INFO` or `WARNING`; unknown names fall back to `INFO`.
        log_dir: When given, also write `app.log` and `errors.log` there (outside the project).

    Returns:
        The run id written on every line of this run.
    \"\"\"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        errors = _rotating(log_dir / "errors.log", max_mb=2, backups=3)
        errors.setLevel(logging.WARNING)
        handlers += [_rotating(log_dir / "app.log", max_mb=5, backups=5), errors]
    formatter = logging.Formatter(LOG_FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RunIdFilter())
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=handlers, force=True)
    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught
    run_id = new_run_id()
    _RUN_ID.set(run_id)
    python = sys.version.split()[0]
    logger.info("run started pid=%s python=%s log_dir=%s", os.getpid(), python, log_dir)
    return run_id
'''

EXTRA_SETTINGS = {
    "api": (
        "\n        http_host: Address the HTTP server binds to (127.0.0.1 only; never 0.0.0.0).\n        http_port: HTTP server port."
        "\n        http_allowed_hosts: Extra accepted Host names, e.g. host.docker.internal (Docker)."
        "\n        http_allowed_origins: Web pages that may call the API (Open WebUI: http://127.0.0.1:8080).",
        '\n    http_host: str = "127.0.0.1"\n    http_port: int = {http_port}'
        '\n    http_allowed_hosts: tuple[str, ...] = ()\n    http_allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8080",)',
        '\n        http_host=os.environ.get("HTTP_HOST", "127.0.0.1").strip(),\n        http_port=int(os.environ.get("HTTP_PORT", "{http_port}")),'
        '\n        http_allowed_hosts=_csv(os.environ.get("HTTP_ALLOWED_HOSTS", "")),'
        '\n        http_allowed_origins=_csv(os.environ.get("HTTP_ALLOWED_ORIGINS", "http://127.0.0.1:8080")),',
    ),
    "ollama": (
        "\n        ollama_model: Local model name, e.g. `qwen2.5`.\n        ollama_timeout_seconds: Timeout for one model call.",
        '\n    ollama_model: str = "qwen2.5"\n    ollama_timeout_seconds: int = 120',
        '\n        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5").strip(),'
        '\n        ollama_timeout_seconds=int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120")),',
    ),
    "db": (
        "\n        database_url: SQLAlchemy URL; SQLite file `<data_dir>/db/app.db` by default.",
        '\n    database_url: str = "sqlite://"',
        '\n        database_url=os.environ.get("DATABASE_URL", "").strip() or f"sqlite:///{data_dir / \'db\' / \'app.db\'}",',
    ),
}

PYPROJECT_TEMPLATE = '''[project]
name = {dist_json}
version = "0.1.0"
description = {description_json}
readme = "README.md"
requires-python = ">={python_version}"
dependencies = {deps_toml}  # add with `uv add <package>` (never `pip install`)

[project.scripts]
{dist} = "{pkg}.entrypoints.cli:main"{server}

[dependency-groups]
dev = {dev_toml}  # add with `uv add --dev <package>`

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.uv]
# Use uv's own downloaded Python (see .python-version), never the system / Homebrew one
python-preference = "only-managed"

[tool.ruff]
line-length = 110
target-version = "py311"
src = ["src", "tests"]
# Framework-managed files (updated by `agentctl update`) and non-Python folders are not linted here
extend-exclude = ["scripts", ".agents", "gas", "web", "legacy", "data"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B"]

[tool.mypy]
python_version = "{python_version}"
files = ["src"]
mypy_path = "src"
strict = true
'''
