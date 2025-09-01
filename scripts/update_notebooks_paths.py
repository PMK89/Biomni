#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

REPLACEMENTS = [
    # Order matters: more specific first
    (re.compile(r"/home/[^\s\"]*/Biomni/biomni/data/?"), "./local_data/"),
    (re.compile(r"/dfs/project/bioagentos/biomni_data/?"), "./local_data/"),
    (re.compile(r"\./data/"), "./local_data/"),
]


def update_sources(sources: List[str]) -> tuple[List[str], bool]:
    changed = False
    new_sources = []
    for s in sources:
        original = s
        for pat, repl in REPLACEMENTS:
            s = pat.sub(repl, s)
        if s != original:
            changed = True
        new_sources.append(s)
    return new_sources, changed


def process_notebook(path: Path, apply: bool = False, verbose: bool = True) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            nb = json.load(f)
    except Exception as e:
        if verbose:
            print(f"[WARN] Skipping {path}: cannot parse JSON ({e})")
        return False

    changed_any = False

    for cell in nb.get("cells", []):
        if not isinstance(cell, dict):
            continue
        if "source" not in cell:
            continue
        src = cell["source"]
        if isinstance(src, list):
            new_src, changed = update_sources(src)
            if changed:
                cell["source"] = new_src
                changed_any = True
        elif isinstance(src, str):
            new_src, changed = update_sources([src])
            if changed:
                cell["source"] = new_src[0]
                changed_any = True

    if changed_any and apply:
        # Backup
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_suffix(path.suffix + f".{ts}.bak")
        shutil.copy2(path, backup)
        with path.open("w", encoding="utf-8") as f:
            json.dump(nb, f, ensure_ascii=False, indent=1)
            f.write("\n")
        if verbose:
            print(f"[APPLY] Updated {path} (backup: {backup.name})")
    else:
        if verbose:
            print(f"[DRY-RUN] {path}: {'changes detected' if changed_any else 'no changes'}")

    return changed_any


def main():
    parser = argparse.ArgumentParser(description="Update notebooks to use ./local_data paths")
    parser.add_argument("--root", default=".", help="Project root to scan (default: .)")
    parser.add_argument("--apply", action="store_true", help="Write changes and create backups")
    parser.add_argument("--files", nargs="*", help="Specific .ipynb files to update")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    targets: List[Path] = []
    if args.files:
        targets = [root / Path(p) for p in args.files]
    else:
        for dirpath, _, filenames in os.walk(root / "tutorials"):
            for fn in filenames:
                if fn.endswith(".ipynb"):
                    targets.append(Path(dirpath) / fn)

    if not targets:
        print("No notebooks found to process.")
        return

    total = 0
    changed = 0
    for nb_path in targets:
        total += 1
        if process_notebook(nb_path, apply=args.apply):
            changed += 1

    print(f"Done. {changed}/{total} notebooks had changes. {'Applied' if args.apply else 'Dry-run only.'}")


if __name__ == "__main__":
    main()
