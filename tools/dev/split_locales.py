r"""Move one tab's keys out of the eleven flat locale files and into their own (#1282).

## Why

A key lands in every shipped locale in the same commit — that rule is why the tables are
complete, and it stays. What it costs is the FILE LAYOUT: measured over the last 200
commits, each of `panel/locales/{de,en,es,fr,id,it,pl,pt,ru,tr,vi}.json` was touched by
**37 different tasks**, and **85 of the 200 commits (43 %) touched all eleven**. With one
working tree and one index, two agents adding a key collide every single time — even when
they are working on two unrelated tabs.

Split by TAB and they never meet: `panel/locales/ru/secret_tasks.json` and
`panel/locales/ru/rally.json` are two files. `panel/i18n.load_locale` reads the flat file
and every per-tab file into one table, so the split can happen one prefix at a time and
nothing has to change in the same breath.

## Using it

    python3 tools/dev/split_locales.py --list                 # prefixes, by size
    python3 tools/dev/split_locales.py secret_tasks --dry-run # what would move
    python3 tools/dev/split_locales.py secret_tasks           # move it, all 11 files

A prefix is the part of a key before the first dot (`secret_tasks.title` →
`secret_tasks`), which is how the panel's keys are already named. The keys move out of
every flat locale into `panel/locales/<lang>/<prefix>.json`, in the same run, or none of
them do — a prefix that is present in ten languages and missing from the eleventh is
refused rather than half-moved, because a half-move is the exact failure the rule about
eleven locales exists to prevent.

**Run it when the tree is quiet.** It rewrites all eleven files at once, so it is the
worst possible thing to do while somebody else has locale edits in flight — which is
also the whole reason the split is worth doing.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCALES = REPO / "panel" / "locales"


def flat_files() -> list[Path]:
    return sorted(p for p in LOCALES.glob("*.json") if p.is_file())


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data: dict) -> None:
    """Same shape as the files already committed: 2-space indent, real UTF-8, one
    trailing newline — so a diff shows the keys that moved and nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def prefixes() -> Counter:
    counts: Counter = Counter()
    for key in read(LOCALES / "en.json"):
        counts[key.split(".", 1)[0]] += 1
    return counts


def split(prefix: str, dry_run: bool = False) -> int:
    langs = [p.stem for p in flat_files()]
    picked: dict[str, dict] = {}
    for path in flat_files():
        data = read(path)
        mine = {k: v for k, v in data.items() if k.split(".", 1)[0] == prefix}
        if not mine:
            print(f"  {path.name}: nothing under {prefix!r}")
        picked[path.stem] = mine

    sizes = {lang: len(keys) for lang, keys in picked.items()}
    if len(set(sizes.values())) != 1:
        print(f"refusing to split {prefix!r}: the locales do not agree on how many keys "
              f"it has — {sizes}. Fill the gap first (tests/test_panel_i18n.py finds "
              f"them); a half-move is worse than none.")
        return 1
    if not any(sizes.values()):
        print(f"no key starts with {prefix!r}")
        return 1

    for lang in langs:
        src = LOCALES / f"{lang}.json"
        dest = LOCALES / lang / f"{prefix}.json"
        print(f"  {len(picked[lang]):4d} keys  {src.name} -> {dest.relative_to(LOCALES)}")
        if dry_run:
            continue
        rest = {k: v for k, v in read(src).items() if k not in picked[lang]}
        write(dest, picked[lang])
        write(src, rest)
    if dry_run:
        print("(dry run — nothing written)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("prefix", nargs="?", help="the key prefix to move out, e.g. rally")
    ap.add_argument("--list", action="store_true", help="print the prefixes by size")
    ap.add_argument("--dry-run", action="store_true", help="say what would move")
    args = ap.parse_args(argv)

    if args.list or not args.prefix:
        for prefix, count in prefixes().most_common():
            print(f"  {count:4d}  {prefix}")
        return 0
    return split(args.prefix, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
