r"""Count the ✅/🟡/❌ items in docs/farming*.md and render the progress bar.

The bar lives between the `<!-- progress:start -->` / `<!-- progress:end -->`
markers at the top of both files. Only the top-level feature bullets are counted
(lines that begin with `- ✅ `, `- 🟡 ` or `- ❌ `) — the daily-routine tables at
the bottom are a second view of the same abilities, so counting them too would
double-count.

    python3 tools/farming_progress.py            # print the current numbers
    python3 tools/farming_progress.py --write    # rewrite the bar in both files

THE COUNTING ITSELF IS NOT HERE (#2399). It is `tools/lib/farming_doc.py`, which
the panel's «Что умеет бот» page reads as well — so the bar in the documents and
the percentage on the page are the same number arrived at once, rather than two
numbers that happen to agree today. This file is the command line around it.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import farming_doc  # noqa: E402

DOCS = Path(farming_doc.DOCS_DIR)
START, END = farming_doc.START, farming_doc.END


def main():
    write = "--write" in sys.argv[1:]
    failed = False
    for name in farming_doc.TEXT:
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        new_block, (done, partial, todo, total, pct) = farming_doc.block(name, text)
        print(f"{name}: {pct}% — ✅ {done} · 🟡 {partial} · ❌ {todo} of {total}")
        if START not in text or END not in text:
            print(f"  ! no {START} … {END} markers in {name}", file=sys.stderr)
            failed = True
            continue
        updated = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: new_block, text, flags=re.S)
        if updated == text:
            continue
        if write:
            path.write_text(updated, encoding="utf-8")
            print(f"  updated {name}")
        else:
            print(f"  ! {name} is out of date — rerun with --write", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
