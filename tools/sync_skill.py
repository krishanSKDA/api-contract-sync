"""Copy the library's modules, tests and fixtures into the Claude skill.

The package (src/api_contract_sync) is the source of truth. The skill runs the same
files as standalone scripts from <skill>/scripts, which works because each module
falls back to flat imports when it is not inside a package.

    python tools/sync_skill.py <skill-dir>           # copy
    python tools/sync_skill.py <skill-dir> --check   # exit 1 if the skill is out of date
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ["java_parser.py", "kotlin_parser.py", "ts_parser.py", "extract_spring.py", "extract_openapi.py",
           "generate_ts.py", "check_drift.py"]
TREES = ["tests/fixtures"]
FILES = ["tests/test_pipeline.py"]
IGNORE = shutil.ignore_patterns("__pycache__", "target", "node_modules")


def pairs(skill: Path):
    for m in MODULES:
        yield ROOT / "src" / "api_contract_sync" / m, skill / "scripts" / m
    for f in FILES:
        yield ROOT / f, skill / f


def tree_differs(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    cmp = filecmp.dircmp(src, dst, ignore=["__pycache__", "target", "node_modules"])

    def walk(c) -> bool:
        if c.left_only or c.right_only or c.diff_files or c.funny_files:
            return True
        return any(walk(sub) for sub in c.subdirs.values())
    return walk(cmp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill", type=Path, help="skill directory (contains SKILL.md)")
    ap.add_argument("--check", action="store_true", help="report differences, change nothing")
    a = ap.parse_args(argv)
    if not (a.skill / "SKILL.md").exists():
        ap.error(f"{a.skill} has no SKILL.md")

    stale = [str(d.relative_to(a.skill)) for s, d in pairs(a.skill) if not d.exists() or not filecmp.cmp(s, d, shallow=False)]
    stale += [t for t in TREES if tree_differs(ROOT / t, a.skill / t)]
    if a.check:
        print("skill is up to date" if not stale else "out of date: " + ", ".join(stale))
        return 1 if stale else 0
    for s, d in pairs(a.skill):
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
    for t in TREES:
        if (a.skill / t).exists():
            shutil.rmtree(a.skill / t)
        shutil.copytree(ROOT / t, a.skill / t, ignore=IGNORE)
    print(f"synced {len(stale)} changed item(s) into {a.skill}" if stale else "nothing to sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
