"""Command line for moving an old project into the template structure (`python3 scripts/migrate_project.py`).

Purpose:
    Parses the options, calls `services.migration.migrate()`, records the new project in the
    local registry and prints the next step. The old project is never modified.

Usage:
    python3 scripts/migrate_project.py --from ~/Desktop/projects/old_app --target ~/Desktop/projects/old_app_v2
    python3 scripts/migrate_project.py --from ~/Desktop/projects/old_bot --target ~/Desktop/projects/bot --stack python --with gas
    python3 scripts/migrate_project.py --from ~/Desktop/projects/old_api --target ~/Desktop/projects/api_v2 --mode develop
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from project_template.adapters.project_registry import register as register_project
from project_template.packs.stack_config import ADDON_CHOICES, STACK_CHOICES
from project_template.services.migration import migrate


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="把舊專案搬進用模板建立的新資料夾（保留 git 歷史，產生遷移計畫）")
    parser.add_argument("--from", dest="old", required=True, help="舊專案資料夾")
    parser.add_argument("--target", required=True, help="新專案資料夾（不可已存在）")
    parser.add_argument("--name", default=None, help="專案名稱（預設為新資料夾名稱）")
    parser.add_argument("--stack", choices=STACK_CHOICES, default=None, help="主要語言（預設自動偵測）")
    parser.add_argument("--with", dest="addons", nargs="*", choices=ADDON_CHOICES, default=None, help="附加：web / gas（預設自動偵測）")
    parser.add_argument("--skills", nargs="*", default=[], help="額外安裝的 optional skills")
    parser.add_argument("--mode", choices=["maintain", "develop"], default="maintain",
                        help="maintain：舊專案已完工，保留 Flask；develop：要繼續開發，Flask 全部改成 FastAPI")
    parser.add_argument("--data-dir", default=None, help="資料資料夾（預設 ../../projects-data/<名稱>）")
    args = parser.parse_args(argv)
    old = Path(args.old).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    if not old.is_dir():
        print(f"❌ 找不到舊專案：{old}", file=sys.stderr)
        return 1
    try:
        options = {"stack": args.stack, "addons": args.addons, "name": args.name, "skills": args.skills, "mode": args.mode,
                   "data_dir": Path(args.data_dir) if args.data_dir else None}
        count = migrate(old, target, options)
    except (FileExistsError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✅ 已建立 {target}（{count} 個舊檔案在 legacy/，舊專案未被修改）")
    register_project(target, "migrate")
    print("   下一步：cd 進新資料夾，閱讀 docs/migration/MIGRATION.md，再請 Agent 依 legacy-migration skill 逐批搬移。")
    return 0
