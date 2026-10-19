#!/usr/bin/env python3
"""Local LLM add-on (`--with ollama`): Ollama client, hardware guard, prompt registry, quarantine.

Purpose:
    Brings the patterns proven in the books project to every Python project that calls a
    local model:
      - `adapters/llm/ollama_client.py`  : stdlib HTTP client for http://127.0.0.1:11434 with
        timeouts; every failure becomes `LLMError`.
      - `adapters/llm/hardware.py`       : checks free RAM, battery / AC power and free disk
        before heavy model calls, so the Mac never swaps to death or drains the battery.
      - `services/prompts.py`            : `PromptRegistry`, the single place for prompt text.
      - `adapters/storage/quarantine.py` : failed or low-confidence items go to
        `<DATA_DIR>/needs_review/` and the batch continues.
      - `services/llm_review.py`         : example flow tying them together.
      - `tests/test_llm.py`              : fake model client, no Ollama needed.
"""

from __future__ import annotations

from pathlib import Path

from packs.common import write_file as _write

CLIENT_PY = '''"""Ollama HTTP client (standard library only); talks to 127.0.0.1, never localhost."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(Exception):
    """Raised for any model failure: unreachable server, timeout, bad response."""


@dataclass(frozen=True)
class OllamaClient:
    """Minimal client for Ollama's `/api/generate`.

    Attributes:
        base_url: Server URL, e.g. `http://127.0.0.1:11434`.
        model: Model name, e.g. `qwen2.5`.
        timeout_seconds: Request timeout.
    """

    base_url: str
    model: str
    timeout_seconds: int = 120

    def generate(self, prompt: str) -> str:
        """Run one prompt and return the model's text.

        Args:
            prompt: Full prompt text (build it with `PromptRegistry`).

        Returns:
            The generated text.

        Raises:
            LLMError: When the server is unreachable, times out, or returns invalid JSON.
        """
        body = json.dumps({{"model": self.model, "prompt": prompt, "stream": False}}).encode("utf-8")
        request = urllib.request.Request(
            f"{{self.base_url}}/api/generate", data=body, headers={{"Content-Type": "application/json"}}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise LLMError(f"Ollama request failed: {{exc}}") from exc
        return str(data.get("response", ""))
'''

HARDWARE_PY = '''"""Hardware guard: decide whether it is safe to run a heavy local-model call right now.

Thresholds come from the books project (ADR-0001): with AC power at least 2 GB free RAM,
on battery at least 4 GB and 40% charge, and at least 10 GB free disk. When a check fails
the caller degrades gracefully (skip the model, quarantine the item) instead of risking swap
storms or draining the battery.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MIN_RAM_GB_AC = 2.0
MIN_RAM_GB_BATTERY = 4.0
MIN_BATTERY_PERCENT = 40
MIN_DISK_GB = 10.0


@dataclass(frozen=True)
class GuardResult:
    """Outcome of a hardware check.

    Attributes:
        ok: Whether the heavy call may run.
        reason: Human-readable explanation (shown in logs and quarantine notes).
    """

    ok: bool
    reason: str


def available_ram_gb() -> float:
    """Estimate available RAM (macOS counts free + inactive + purgeable pages).

    Returns:
        Gigabytes available, or a large number when it cannot be measured.
    """
    if platform.system() != "Darwin":
        return 1e9
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, check=False).stdout
    page = int(m.group(1)) if (m := re.search(r"page size of (\\d+)", out)) else 16384
    pages = sum(int(n) for n in re.findall(r"Pages (?:free|inactive|purgeable):\\s+(\\d+)", out))
    return pages * page / 1024**3 if pages else 1e9


def power_status() -> tuple[bool, int]:
    """Read AC power and battery level (macOS `pmset`).

    Returns:
        Tuple of (on AC power, battery percent); desktops report (True, 100).
    """
    if platform.system() != "Darwin":
        return True, 100
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, check=False).stdout
    percent = int(m.group(1)) if (m := re.search(r"(\\d+)%", out)) else 100
    return "AC Power" in out or "%" not in out, percent


def check_resources(
    path: Path, ram_gb: float | None = None, power: tuple[bool, int] | None = None
) -> GuardResult:
    """Decide whether a heavy model call is safe.

    Args:
        path: Folder whose disk must have enough free space (usually DATA_DIR).
        ram_gb: Available RAM override (for tests); measured when None.
        power: (on AC, battery percent) override (for tests); measured when None.

    Returns:
        The guard result with a reason.
    """
    on_ac, percent = power or power_status()
    ram = available_ram_gb() if ram_gb is None else ram_gb
    need_ram = MIN_RAM_GB_AC if on_ac else MIN_RAM_GB_BATTERY
    disk_gb = shutil.disk_usage(path if path.exists() else Path.home()).free / 1024**3
    if ram < need_ram:
        return GuardResult(False, f"RAM {{ram:.1f}} GB < {{need_ram}} GB")
    if not on_ac and percent < MIN_BATTERY_PERCENT:
        return GuardResult(False, f"battery {{percent}}% < {{MIN_BATTERY_PERCENT}}% (plug in AC power)")
    if disk_gb < MIN_DISK_GB:
        return GuardResult(False, f"free disk {{disk_gb:.1f}} GB < {{MIN_DISK_GB}} GB")
    return GuardResult(True, "ok")
'''

QUARANTINE_PY = '''"""Quarantine: park items that failed or are low-confidence so a batch never stops for them."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def quarantine(needs_review_dir: Path, item_id: str, content: str, reason: str) -> Path:
    """Write one item to `<DATA_DIR>/needs_review/` with the reason next to it.

    Args:
        needs_review_dir: Quarantine folder (`AppConfig.needs_review_dir`).
        item_id: Identifier of the item, e.g. the input file name.
        content: Content to keep for manual review.
        reason: Why the item was quarantined.

    Returns:
        Path of the written content file (a `.reason.json` file sits beside it).
    """
    needs_review_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = needs_review_dir / f"{{stamp}}-{{re.sub(r'[^A-Za-z0-9_.-]', '_', item_id)}}.md"
    target.write_text(content, encoding="utf-8")
    meta = {{"item": item_id, "reason": reason, "time": stamp}}
    target.with_suffix(".reason.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target
'''

PROMPTS_PY = '''"""Prompt registry: every prompt sent to a model lives here (listed in docs/PROMPT_TEMPLATES.md)."""

from __future__ import annotations

PROMPTS: dict[str, str] = {{
    "review_text": (
        "You are a careful reviewer. Fix obvious typos in the text below and answer with the "
        "corrected text only.\\n\\nTEXT:\\n{{text}}"
    ),
}}


class PromptRegistry:
    """Look up and fill prompt templates by name."""

    @staticmethod
    def render(name: str, **values: str) -> str:
        """Fill a prompt template.

        Args:
            name: Key in `PROMPTS`.
            **values: Placeholder values, e.g. `text=...`.

        Returns:
            The prompt text.

        Raises:
            KeyError: When the prompt name or a placeholder is unknown.
        """
        return PROMPTS[name].format(**values)
'''

REVIEW_PY = '''"""Example LLM flow: guard → prompt → model → quarantine on failure (batch keeps going)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from {pkg}.services.prompts import PromptRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewOutcome:
    """Result of reviewing one text.

    Attributes:
        text: Reviewed text (the original when the model was skipped or failed).
        reviewed: Whether the model actually ran.
        note: Why the model was skipped or failed ("" when it ran).
    """

    text: str
    reviewed: bool
    note: str = ""


def review_text(text: str, generate: Callable[[str], str], guard_ok: tuple[bool, str]) -> ReviewOutcome:
    """Ask the model to proofread text, degrading gracefully when unsafe or failing.

    Args:
        text: Text to review.
        generate: Model call, e.g. `OllamaClient(...).generate` (a fake in tests).
        guard_ok: `(ok, reason)` from the hardware guard.

    Returns:
        The outcome; callers quarantine items whose `reviewed` is False.
    """
    ok, reason = guard_ok
    if not ok:
        logger.warning("model skipped: %s", reason)
        return ReviewOutcome(text=text, reviewed=False, note=f"skipped: {{reason}}")
    try:
        answer = generate(PromptRegistry.render("review_text", text=text)).strip()
    except Exception as exc:  # the batch must continue; the item is quarantined by the caller
        logger.error("model failed: %s", exc)
        return ReviewOutcome(text=text, reviewed=False, note=f"failed: {{exc}}")
    if not answer:
        return ReviewOutcome(text=text, reviewed=False, note="failed: empty answer")
    return ReviewOutcome(text=answer, reviewed=True)
'''

LLM_TEST = '''"""Tests for the LLM add-on (fake model; no Ollama server or network needed)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from {pkg}.adapters.llm.hardware import check_resources
from {pkg}.adapters.storage.quarantine import quarantine
from {pkg}.services.llm_review import review_text


def fake_model(prompt: str) -> str:
    """Pretend to be the model: return the text after `TEXT:` in upper case.

    Args:
        prompt: Prompt built by the registry.

    Returns:
        The "corrected" text.
    """
    return prompt.split("TEXT:\\n", 1)[1].upper()


def broken_model(prompt: str) -> str:
    """Pretend the model server is down.

    Args:
        prompt: Ignored.

    Returns:
        Never returns.

    Raises:
        ConnectionError: Always.
    """
    raise ConnectionError("connection refused")


class LlmTest(unittest.TestCase):
    """Guard, review flow and quarantine."""

    def test_review_runs_when_safe(self) -> None:
        """The model result is used when the guard allows it."""
        outcome = review_text("hello", fake_model, (True, "ok"))
        self.assertEqual((outcome.text, outcome.reviewed), ("HELLO", True))

    def test_guard_failure_skips_model(self) -> None:
        """Low RAM on battery skips the model and keeps the original text."""
        guard = check_resources(Path.home(), ram_gb=1.0, power=(False, 90))
        self.assertFalse(guard.ok)
        outcome = review_text("hello", fake_model, (guard.ok, guard.reason))
        self.assertEqual((outcome.text, outcome.reviewed), ("hello", False))

    def test_model_failure_goes_to_quarantine(self) -> None:
        """A failing model does not raise; the item is quarantined with its reason."""
        outcome = review_text("hello", broken_model, (True, "ok"))
        self.assertFalse(outcome.reviewed)
        with tempfile.TemporaryDirectory() as tmp:
            path = quarantine(Path(tmp), "doc-1", outcome.text, outcome.note)
            self.assertTrue(path.exists())
            self.assertIn("connection refused", path.with_suffix(".reason.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
'''

PROMPT_DOC = """# Prompt 範本 (PROMPT_TEMPLATES)

所有送給模型的 prompt 都集中在 `src/{pkg}/services/prompts.py` 的 `PROMPTS`，用 `PromptRegistry.render(name, ...)` 產生。
新增或修改 prompt 時同步更新下表，並說明輸入、預期輸出與失敗時的處理（隔離到 `<DATA_DIR>/needs_review/`）。

| 名稱 | 用途 | 參數 | 預期輸出 |
|---|---|---|---|
| `review_text` | 校對文字 | `text` | 修正後的全文 |
"""


def scaffold_ollama_pack(target_dir: Path, pkg: str) -> None:
    """Create the Ollama client, hardware guard, prompt registry, quarantine and tests.

    Args:
        target_dir: Project root directory.
        pkg: Python package name under `src/`.
    """
    base = target_dir / "src" / pkg
    _write(base / "adapters" / "llm" / "__init__.py", '"""Local model adapters (Ollama) and the hardware guard."""\n')
    _write(base / "adapters" / "llm" / "ollama_client.py", CLIENT_PY.format())
    _write(base / "adapters" / "llm" / "hardware.py", HARDWARE_PY.format())
    _write(base / "adapters" / "storage" / "__init__.py", '"""File storage adapters (quarantine, outputs)."""\n')
    _write(base / "adapters" / "storage" / "quarantine.py", QUARANTINE_PY.format())
    _write(base / "services" / "prompts.py", PROMPTS_PY.format())
    _write(base / "services" / "llm_review.py", REVIEW_PY.format(pkg=pkg))
    _write(target_dir / "tests" / "test_llm.py", LLM_TEST.format(pkg=pkg))
    _write(target_dir / "docs" / "PROMPT_TEMPLATES.md", PROMPT_DOC.format(pkg=pkg))
