"""Fetch pinned upstream skill sources into a local, git-ignored cache (optional).

Purpose:
    Some skills were adapted from public GitHub repositories. Their original sources
    are useful as reference but must not be shipped inside every project, must not be
    auto-discovered by agents as active skills, and must be reproducible. So:
      - `skills.lock.json` pins every source to a commit and records its license.
      - `fetch` downloads exactly that commit into `.skills-cache/<name>@<commit>/`
        (git-ignored; never inside `.agents/skills` or `.claude/skills`).
      - `update` looks up each repo's latest commit and rewrites the pin only for
        repos that were reached successfully — review the upstream diff first.

Usage:
    python3 scripts/sync_github_skills.py list
    python3 scripts/sync_github_skills.py fetch [name ...]
    python3 scripts/sync_github_skills.py update [name ...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from project_template.config.settings import SKILLS_CACHE
from project_template.config.settings import TEMPLATE_ROOT as ROOT

LOCK_CANDIDATES = (ROOT / ".agents" / "skills" / "skills.lock.json",)
GIT_TIMEOUT = 300


def find_lock() -> Path:
    """Locate the template's `.agents/skills/skills.lock.json`.

    Returns:
        Path to the lock file.

    Raises:
        FileNotFoundError: When no lock file exists.
    """
    for path in LOCK_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("skills.lock.json not found in .agents/skills/")


def git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run git with a timeout and captured output.

    Args:
        args: Arguments after `git`.
        cwd: Working directory.

    Returns:
        The completed process (check `returncode`).
    """
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)


def cache_dir_for(cache_root: Path, name: str, commit: str) -> Path:
    """Return the cache folder of one pinned source.

    Args:
        cache_root: Root of the cache (`.skills-cache`).
        name: Source name from the lock file.
        commit: Pinned commit.

    Returns:
        Path such as `.skills-cache/graphify@86c57be`.
    """
    return cache_root / f"{name}@{commit}"


def fetch_source(name: str, spec: dict[str, Any], cache_root: Path) -> bool:
    """Download one pinned source into the cache.

    Args:
        name: Source name.
        spec: Lock entry with `repo`, `commit`, `paths`, `license`.
        cache_root: Root of the cache.

    Returns:
        True when the cache folder now contains the pinned revision.
    """
    target = cache_dir_for(cache_root, name, spec["commit"])
    if target.exists():
        print(f"  = {name}: already cached ({target.relative_to(ROOT)})")
        return True
    with tempfile.TemporaryDirectory(prefix="skill_src_") as tmp:
        clone = Path(tmp) / name
        steps = (
            (["clone", "--filter=blob:none", "--no-checkout", "--quiet", spec["repo"], str(clone)], None),
            (["checkout", "--quiet", spec["commit"]], clone),
        )
        for args, cwd in steps:
            res = git(args, cwd)
            if res.returncode != 0:
                print(f"  ! {name}: git {args[0]} failed: {res.stderr.strip()[:200]}")
                return False
        for rel in spec.get("paths", []):
            src, dst = clone / rel, target / rel
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SOURCE.txt").write_text(f"repo: {spec['repo']}\ncommit: {spec['commit']}\nlicense: {spec.get('license', '?')}\n", encoding="utf-8")
    print(f"  + {name}: cached {spec['commit']} -> {target.relative_to(ROOT)}")
    return True


def latest_commit(repo: str) -> str:
    """Look up the short commit of a repository's default branch.

    Args:
        repo: Git URL.

    Returns:
        Seven-character commit SHA, or an empty string when the repo is unreachable.
    """
    res = git(["ls-remote", repo, "HEAD"])
    return res.stdout.split()[0][:7] if res.returncode == 0 and res.stdout.strip() else ""


def select(sources: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """Filter lock entries by name.

    Args:
        sources: All lock entries.
        names: Requested names (empty = all).

    Returns:
        The selected entries.

    Raises:
        SystemExit: When an unknown name is requested.
    """
    unknown = [n for n in names if n not in sources]
    if unknown:
        raise SystemExit(f"Unknown source(s): {', '.join(unknown)}. Known: {', '.join(sources)}")
    return {n: s for n, s in sources.items() if not names or n in names}


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code (1 when any fetch/update failed).
    """
    parser = argparse.ArgumentParser(description="下載 / 更新 skills 上游參考原始碼（釘選 commit，存放於 .skills-cache/）")
    parser.add_argument("action", choices=["list", "fetch", "update"])
    parser.add_argument("names", nargs="*", help="只處理指定的來源")
    parser.add_argument("--cache", default=str(SKILLS_CACHE), help="快取目錄（預設 .skills-cache/）")
    args = parser.parse_args(argv)

    lock_path = find_lock()
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    chosen = select(lock["sources"], args.names)
    cache_root = Path(args.cache).resolve()
    if args.action == "list":
        for name, spec in chosen.items():
            cached = "cached" if cache_dir_for(cache_root, name, spec["commit"]).exists() else "-"
            print(f"{name:<22} {spec['commit']:<9} {cached:<7} {spec.get('license', '?'):<36} {spec['repo']}")
        return 0
    if args.action == "fetch":
        return 0 if all([fetch_source(n, s, cache_root) for n, s in chosen.items()]) else 1
    failed = False
    for name, spec in chosen.items():
        newest = latest_commit(spec["repo"])
        if not newest:
            print(f"  ! {name}: unreachable, pin kept at {spec['commit']}")
            failed = True
        elif newest != spec["commit"]:
            print(f"  ~ {name}: {spec['commit']} -> {newest} (review the upstream diff before fetching)")
            spec["commit"] = newest
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if failed else 0

