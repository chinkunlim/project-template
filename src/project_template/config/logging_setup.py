"""Logging for the template's own commands (CLIs, web page, MCP server), traced by run id.

Purpose:
    The same logging a generated Python project gets (`packs/python_pack.py`, `PY_LOGGING`), adapted
    to the template. Every file line looks like
        2026-10-22 09:15:02,481 INFO    [3f9a1c2e] project_template.services.migration:migrate:120 - git clone ...
    so one run can be traced with `grep 3f9a1c2e app.log`.

    - Files (outside the template, `<DATA_DIR>/logs/`, DATA_DIR from the template's `.env`):
        `app.log`    : everything at `LOG_LEVEL` and above (5 MB x 5 rotated files)
        `errors.log` : WARNING and above only
    - Console: stderr only (never stdout, so the MCP stdio channel and a CLI's printed output stay
      clean), WARNING and above, message text only, the same as before logging went to files.
      A warning the command already prints for the user passes `extra=FILE_ONLY` so it is not shown twice.
    - Uncaught exceptions and Python warnings are written to the log with their traceback.

Main items:
    - `setup_logging()` : configure the root logger and start a run id.
    - `start_logging()` : read the template settings, call `setup_logging()` and log the command start.
    - `run_command()` : wrap an entrypoint's `main()`: start logging, log the end with its exit code and any crash.
    - `new_run_id()` / `set_run_id()` / `reset_run_id()` : run / request ids.
"""
from __future__ import annotations

import contextvars
import logging
import os
import sys
import uuid
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from project_template.config.settings import log_settings

logger = logging.getLogger(__name__)
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
CONSOLE_FORMAT = "%(message)s"
_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")
FILE_ONLY = {"console": False}  # `logger.warning(..., extra=FILE_ONLY)`: log files only, not the console


def new_run_id() -> str:
    """Create a short random id for a run or a request.

    Returns:
        Eight hexadecimal characters.
    """
    return uuid.uuid4().hex[:8]


def set_run_id(value: str) -> contextvars.Token[str]:
    """Use `value` as the id on every log line of the current context (e.g. one HTTP request).

    Args:
        value: Run or request id.

    Returns:
        Token for `reset_run_id()`.
    """
    return _RUN_ID.set(value)


def reset_run_id(token: contextvars.Token[str]) -> None:
    """Restore the id that was active before `set_run_id()`.

    Args:
        token: Token returned by `set_run_id()`.
    """
    _RUN_ID.reset(token)


def _show_on_console(record: logging.LogRecord) -> bool:
    """Keep records marked `extra=FILE_ONLY` off the console.

    Args:
        record: Log record being emitted.

    Returns:
        False for file-only records.
    """
    return getattr(record, "console", True) is not False


class RunIdFilter(logging.Filter):
    """Attach the current run / request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add `record.run_id`.

        Args:
            record: Log record being emitted.

        Returns:
            Always True (nothing is filtered out).
        """
        record.run_id = _RUN_ID.get()
        return True


def _log_uncaught(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    """Write an uncaught exception with its traceback to the log (Ctrl-C is left alone).

    Args:
        exc_type: Exception class.
        exc: Exception instance.
        tb: Traceback.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("uncaught").critical("uncaught exception", exc_info=(exc_type, exc, tb))


def _rotating(path: Path, max_mb: int, backups: int) -> RotatingFileHandler:
    """Create a size-limited UTF-8 log file handler.

    Args:
        path: Log file path.
        max_mb: Size in MB before the file is rotated.
        backups: Number of old files to keep (`app.log.1` ...).

    Returns:
        The file handler.
    """
    return RotatingFileHandler(path, maxBytes=max_mb * 1_000_000, backupCount=backups, encoding="utf-8")


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> str:
    """Configure the root logger once per process and start a new run id.

    Args:
        level: Logging level name such as `DEBUG`, `INFO` or `WARNING`; unknown names fall back to `INFO`.
        log_dir: When given, also write `app.log` and `errors.log` there (outside the template).

    Returns:
        The run id written on every file line of this run.
    """
    console = logging.StreamHandler(sys.stderr)  # never stdout: the MCP stdio server talks over stdout
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    console.addFilter(_show_on_console)
    handlers: list[logging.Handler] = [console]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        errors = _rotating(log_dir / "errors.log", max_mb=2, backups=3)
        errors.setLevel(logging.WARNING)
        for file_handler in (_rotating(log_dir / "app.log", max_mb=5, backups=5), errors):
            file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
            handlers.append(file_handler)
    for handler in handlers:
        handler.addFilter(RunIdFilter())
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=handlers, force=True)
    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught
    run_id = new_run_id()
    _RUN_ID.set(run_id)
    python = sys.version.split()[0]
    logger.info("run started pid=%s python=%s log_dir=%s", os.getpid(), python, log_dir)
    return run_id


def start_logging(command: str, argv: list[str] | None = None) -> str:
    """Set up logging from the template's settings and record which command started.

    Args:
        command: Command name, e.g. `init_project`.
        argv: Its arguments (logged as given; the template's commands take no secrets).

    Returns:
        The run id.
    """
    level, log_dir = log_settings()
    run_id = setup_logging(level, log_dir)
    logger.info("command start %s argv=%s", command, sys.argv[1:] if argv is None else argv)
    return run_id


def run_command(command: str, body: Callable[[list[str] | None], int], argv: list[str] | None = None) -> int:
    """Run one command with logging: start line, end line with the exit code, crashes with traceback.

    Args:
        command: Command name, e.g. `init_project`.
        body: The command's real work; takes `argv` and returns the exit code.
        argv: Command-line arguments (None = `sys.argv[1:]`).

    Returns:
        The exit code returned by `body`.
    """
    start_logging(command, argv)
    try:
        code = body(argv)
    except SystemExit as exc:  # argparse errors and `sys.exit(...)` still end the run in the log
        logger.info("command end %s exit=%s", command, exc.code)
        raise
    except Exception:
        logger.exception("command failed %s", command)
        raise
    logger.info("command end %s exit=%s", command, code)
    return code
