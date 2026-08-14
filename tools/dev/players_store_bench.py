#!/usr/bin/env python3
r"""What the register cost as a file, and what it costs as a table (#1398).

Run it against a profile's own `players.json` — the biggest one there is, since that is
where the answer matters:

    C:\Python312\python.exe tools\dev\players_store_bench.py profiles\default\players.json

It copies the file into a temporary directory and works there, so the live profile is
never touched and the run can be repeated. Nothing it prints identifies anybody: row
counts, byte counts and seconds.

The three things measured are the three the page actually does:

* **a write** — what one merge cost. The file version rewrote every row on every change;
  the table writes the rows that changed;
* **opening the page** — the first four hundred rows, sorted;
* **a keystroke** — the same, narrowed by the search box, which on the file version meant
  filtering and sorting the whole register again for every character typed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime.players import PlayerBook, SRC_MAP          # noqa: E402
from panel.runtime.store import Store                          # noqa: E402
from panel.tabs.players import registry as reg                 # noqa: E402

#: What the table draws (`panel/tabs/players/tab.py::MAX_SHOWN`).
SHOWN = 400

#: The filters timed, in the order a person makes them.
CASES = (
    ("open the page", {}),
    ("type three letters", {"text": "abc"}),
    ("one alliance", {"alliance": "?"}),
    ("seen today", {"seen": "day"}),
    ("level 30+, sorted by power", {"level_min": 30}),
)


def _deep_size(obj, seen=None) -> int:
    """Roughly what one Python structure costs, following dicts, lists and strings."""
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    total = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for key, value in obj.items():
            total += _deep_size(key, seen) + _deep_size(value, seen)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            total += _deep_size(item, seen)
    return total


def _took(fn, times: int = 3) -> float:
    """The BEST of a few runs — the interesting number is the cost, not the noise."""
    best = None
    for _ in range(times):
        start = time.perf_counter()
        fn()
        took = time.perf_counter() - start
        best = took if best is None else min(best, took)
    return best or 0.0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    if not source.exists():
        print(f"no such file: {source}")
        return 2

    work = Path(tempfile.mkdtemp(prefix="players-bench-"))
    legacy = work / "players.json"
    shutil.copy2(source, legacy)
    size = os.path.getsize(legacy)

    print(f"file: {size:,} bytes")

    # -- as a file -------------------------------------------------------------------
    rows = json.loads(legacy.read_text(encoding="utf-8"))
    print(f"rows: {len(rows):,}\n")
    load = _took(lambda: json.loads(legacy.read_text(encoding="utf-8")))
    save = _took(lambda: json.dumps(rows, ensure_ascii=False, indent=2))
    print("AS A FILE")
    print(f"  read the register        {load * 1000:8.1f} ms")
    print(f"  write it back (a merge)  {save * 1000:8.1f} ms")

    # The file version kept the whole register resident, as one dict of dicts per open
    # profile — which is the cost that never appeared in any timing.
    held = {str(r.get("uid")): r for r in rows}
    print(f"  held in memory           {_deep_size(held) / 1e6:8.1f} MB  per profile")

    # A lap re-lists what it drove over whether or not anything moved. The file version
    # answered that from memory, which is the one thing it was faster at.
    lap_rows = rows[:4000]

    def unchanged_in_memory():
        for row in lap_rows:
            was = held.get(str(row.get("uid")))
            if was is not None and all(was.get(k) == v for k, v in row.items()):
                continue
    print(f"  a lap that changed none  {_took(unchanged_in_memory) * 1000:8.1f} ms"
          f"   (4 000 rows re-listed)")
    print(f"  a lap that moved 4 000   {save * 1000:8.1f} ms   (the whole file, again)")

    tag = next((r.get("alliance_abbr") for r in rows if r.get("alliance_abbr")), "")
    cases = [(name, dict(f, alliance=tag) if f.get("alliance") == "?" else f)
             for name, f in CASES]
    for name, f in cases:
        def do(f=f):
            kept = reg.apply_filter(rows, f)
            reg.sort_rows(kept, reg.DEFAULT_SORT)[:SHOWN]
        print(f"  {name:<24} {_took(do) * 1000:8.1f} ms")

    # -- as a table ------------------------------------------------------------------
    store = Store(str(work / "panel.db"))
    book = PlayerBook(store, str(legacy))
    moved = _took(book.ensure_imported, times=1)
    print("\nAS A TABLE")
    print(f"  the one-off import       {moved * 1000:8.1f} ms   ({len(book):,} rows)")

    # A lap of the map re-lists what it drove over. Half of it is the ordinary case:
    # the rows are unchanged and the merge writes nothing at all.
    lap = [dict(r, seen_at=r.get("last_seen")) for r in rows[:4000]]
    same = _took(lambda: book.sighted(lap, source=SRC_MAP))
    moved_rows = [dict(r, seen_at=int(time.time()) + i) for i, r in enumerate(lap)]
    changed = _took(lambda: book.sighted(moved_rows, source=SRC_MAP), times=1)
    print(f"  a lap that changed none  {same * 1000:8.1f} ms   (4 000 rows re-listed)")
    print(f"  a lap that moved 4 000   {changed * 1000:8.1f} ms")
    for name, f in cases:
        print(f"  {name:<24} "
              f"{_took(lambda f=f: book.search(f, limit=SHOWN)) * 1000:8.1f} ms")
    print(f"  {'count the register':<24} {_took(lambda: len(book)) * 1000:8.1f} ms")

    store.close()
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
