"""Command line for creating a new project (`python3 scripts/init_project.py`).

Purpose:
    Parses the options, calls `services.scaffold.scaffold_project()`, records the project in
    the local registry and prints the next step.

Usage:
    python3 scripts/init_project.py --target ~/Desktop/projects/my_app --stack python
    python3 scripts/init_project.py --target ~/Desktop/projects/app --stack python --with web gas
    python3 scripts/init_project.py --target ~/Desktop/projects/web --stack node --skills legacy-migration
    python3 scripts/init_project.py --list-skills
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from project_template.adapters.project_registry import register as register_project
from project_template.packs.stack_config import ADDON_CHOICES, STACK_CHOICES
from project_template.services.scaffold import DEFAULT_DESCRIPTION, scaffold_project, skill_catalog


def print_skill_list() -> None:
    """Print the skill catalog grouped by tier."""
    for name, meta in skill_catalog():
        stacks = f" [{', '.join(meta.get('stacks', []))}]" if meta.get("stacks") else ""
        print(f"{meta.get('tier', '?'):<9} {name:<22}{stacks} — {meta.get('trigger', '')}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="建立標準結構的新專案（文件、資料夾、Agent 規則與工具）")
    parser.add_argument("--target", help="新專案資料夾路徑")
    parser.add_argument("--name", default=None, help="專案名稱（預設為資料夾名稱）")
    parser.add_argument("--stack", choices=STACK_CHOICES, default="python",
                        help="主要語言（預設 python；both = python+web，all = python+web+gas，mobile = 只有手機 App）")
    parser.add_argument("--with", dest="addons", nargs="*", choices=ADDON_CHOICES, default=[],
                        help="附加：web、gas、mobile（Expo 手機 App，Android+iOS）、api（FastAPI）、db（SQLAlchemy+Alembic+SQLite）、"
                             "ollama（本機模型＋硬體檢查）、evals（輸出品質評估）")
    parser.add_argument("--timezone", default=None, help="GAS 時區（預設讀取這台電腦，例如 Asia/Taipei）")
    parser.add_argument("--license", default="none", choices=["none", "MIT"], help="授權：MIT 會產生 LICENSE（預設不授權）")
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION, help="一句話專案描述")
    parser.add_argument("--skills", nargs="*", default=[], help="額外安裝的 optional skills（例如 legacy-migration）")
    parser.add_argument("--list-skills", action="store_true", help="列出可用 skills 後結束")
    parser.add_argument("--no-git", action="store_true", help="不建立 git repo 與初始 commit")
    parser.add_argument("--data-dir", default=None,
                        help="資料資料夾（預設 ../../projects-data/<名稱>）；同一顆硬碟會存成相對路徑，外接硬碟只寫進 .env")
    parser.add_argument("--force", action="store_true", help="允許寫入非空資料夾（可能覆蓋同名檔案）")
    args = parser.parse_args(argv)
    if not args.list_skills and not args.target:
        parser.error("--target is required")
    return args


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    if args.list_skills:
        print_skill_list()
        return 0
    target_dir = Path(args.target).expanduser().resolve()
    project_name = args.name or target_dir.name
    try:
        skills = scaffold_project(
            target_dir, project_name, stack=args.stack, addons=args.addons, description=args.description,
            extra_skills=args.skills, timezone=args.timezone, license_kind=args.license,
            init_git_repo=not args.no_git, force=args.force,
            data_dir=Path(args.data_dir) if args.data_dir else None,
        )
    except (FileExistsError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    extras = f" + {', '.join(args.addons)}" if args.addons else ""
    print(f"✅ 已建立 '{project_name}' (stack={args.stack}{extras}, skills={', '.join(skills)})：{target_dir}")
    register_project(target_dir, "init")
    print("   下一步：cd 進去後執行 `python3 scripts/agentctl.py status`")
    return 0
