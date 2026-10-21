#!/usr/bin/env python3
"""Output-quality evaluation add-on (`--with evals`): rule-based checks with a score threshold.

Purpose:
    For projects whose product is generated output (conversions, AI answers, reports), unit
    tests are not enough: a change can keep tests green while the output quietly gets worse.
    `evals/` keeps a small benchmark set and scores every output file against rules:
      - `evals/checks.py`    : rule functions (add project-specific ones here)
      - `evals/run_evals.py` : scores `evals/cases/**/*.md` (or `--outputs <dir>`, e.g. DATA_DIR/output)
      - `evals/EVALS.md`     : what is measured, the benchmark set, how to add cases
    `agentctl check --evals` runs it; scores below `--min-score` fail.
"""

from __future__ import annotations

from pathlib import Path

from packs.common import write_file as _write

EVALS_COMMAND = "uv run python evals/run_evals.py"

CHECKS_PY = '''"""Quality rules for generated outputs. Each rule returns (passed, message).

Add project-specific rules to `RULES` (e.g. "abstract present", "no orphan page numbers").
"""

from __future__ import annotations

import re
from collections.abc import Callable

Rule = Callable[[str], tuple[bool, str]]
MIN_BYTES = 200


def not_empty(text: str) -> tuple[bool, str]:
    """The output has real content.

    Args:
        text: Output text.

    Returns:
        (passed, message).
    """
    return len(text.encode("utf-8")) >= MIN_BYTES, f"at least {MIN_BYTES} bytes"


def balanced_brackets(text: str) -> tuple[bool, str]:
    """Brackets and LaTeX `$` delimiters are balanced.

    Args:
        text: Output text.

    Returns:
        (passed, message).
    """
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for ch in re.sub(r"`[^`]*`", "", text):
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in pairs.values() and (not stack or stack.pop() != ch):
            return False, f"unbalanced '{ch}'"
    dollars = len(re.findall(r"(?<!\\\\)\\$", text))
    if stack or dollars % 2:
        return False, "unclosed bracket or `$`"
    return True, "brackets and $ balanced"


def no_error_markers(text: str) -> tuple[bool, str]:
    """No leaked error traces or placeholders.

    Args:
        text: Output text.

    Returns:
        (passed, message).
    """
    markers = ("Traceback (most recent call last)", "TODO", "[object Object]", "\\ufffd")
    found = [m for m in markers if m in text]
    return not found, f"markers found: {found}" if found else "no error markers"


def has_heading(text: str) -> tuple[bool, str]:
    """The document has at least one Markdown heading.

    Args:
        text: Output text.

    Returns:
        (passed, message).
    """
    return bool(re.search(r"^#{1,6} \\S", text, flags=re.M)), "has a heading"


RULES: list[Rule] = [not_empty, balanced_brackets, no_error_markers, has_heading]
'''

RUN_PY = '''"""Score output files against the rules in `checks.py` and fail below a threshold.

Usage:
    uv run python evals/run_evals.py                       # evals/cases/**/*.md
    uv run python evals/run_evals.py --outputs ../../projects-data/app/output --min-score 0.9
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import RULES  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases"


def score_file(path: Path) -> tuple[float, list[str]]:
    """Run every rule on one file.

    Args:
        path: Markdown output file.

    Returns:
        Tuple of (score between 0 and 1, messages of failed rules).
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    results = [rule(text) for rule in RULES]
    failed = [msg for ok, msg in results if not ok]
    return 1 - len(failed) / len(RULES), failed


def main(argv: list[str] | None = None) -> int:
    """Score all outputs and print a report.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        0 when the average score reaches `--min-score`, otherwise 1.
    """
    parser = argparse.ArgumentParser(description="Score generated outputs against quality rules")
    parser.add_argument("--outputs", default=str(CASES), help="folder with *.md outputs")
    parser.add_argument("--min-score", type=float, default=0.9, help="minimum average score (0-1)")
    args = parser.parse_args(argv)
    files = sorted(Path(args.outputs).expanduser().rglob("*.md"))
    if not files:
        print(f"no outputs found in {args.outputs}")
        return 1
    scores = []
    for path in files:
        score, failed = score_file(path)
        scores.append(score)
        print(f"{score:5.0%}  {path.name}" + (f"  ✗ {'; '.join(failed)}" if failed else ""))
    average = sum(scores) / len(scores)
    print(f"average {average:.0%} over {len(files)} files (min {args.min_score:.0%})")
    return 0 if average >= args.min_score else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

SAMPLE_CASE = """# Sample output

This sample shows what a good generated document looks like: it has a heading, real
content, balanced brackets (like these) and inline math such as $a^2 + b^2 = c^2$.
Replace it with real outputs from your pipeline that you have checked by hand.
"""

EVALS_DOC = """# 輸出品質評估 (EVALS)

單元測試確認程式邏輯；evals 確認**產出的品質沒有退步**（轉檔結果、AI 回答、報告）。

- `cases/`：人工確認過的基準輸出（小檔案，可進 git）；大量資料放 `DATA_DIR`，用 `--outputs` 指定。
- `checks.py`：規則（不能是空檔、括號與 `$` 要配對、沒有錯誤殘留、要有標題），依專案再加。
- 分數 = 通過的規則比例；平均低於 `--min-score`（預設 0.9）就失敗。

```bash
uv run python evals/run_evals.py
```

```bash
python3 scripts/agentctl.py check --evals
```

新增案例：把確認過的輸出存到 `cases/<案例名>/output.md`；發現新的品質問題時，先在 `checks.py` 加一條規則，再修程式。
"""


def scaffold_evals_pack(target_dir: Path) -> None:
    """Create `evals/` with rules, runner, a sample case and the guide.

    Args:
        target_dir: Project root directory.
    """
    evals = target_dir / "evals"
    _write(evals / "checks.py", CHECKS_PY)
    _write(evals / "run_evals.py", RUN_PY)
    _write(evals / "cases" / "sample" / "output.md", SAMPLE_CASE)
    _write(evals / "EVALS.md", EVALS_DOC)
