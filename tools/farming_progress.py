r"""Count the ✅/🟡/❌ items in docs/farming*.md and render the progress bar.

The bar lives between the `<!-- progress:start -->` / `<!-- progress:end -->`
markers at the top of both files. Only the top-level feature bullets are counted
(lines that begin with `- ✅ `, `- 🟡 ` or `- ❌ `) — the daily-routine tables at
the bottom are a second view of the same abilities, so counting them too would
double-count.

    python3 tools/farming_progress.py            # print the current numbers
    python3 tools/farming_progress.py --write    # rewrite the bar in both files
"""
import re
import sys
from pathlib import Path

CELLS = 20
DOCS = Path(__file__).resolve().parent.parent / "docs"
START, END = "<!-- progress:start -->", "<!-- progress:end -->"
ITEM = re.compile(r"^- (✅|🟡|❌) ", re.M)

# per-file wording — the EN copy is canonical, the RU one mirrors it
TEXT = {
    "farming.md": ("{bar}  **{pct}%** — {done} of {total}\n\n"
                   "🟩 {done} done · 🟨 {partial} partly · 🟥 {todo} not automated"),
    "farming.ru.md": ("{bar}  **{pct}%** — {done} из {total}\n\n"
                      "🟩 {done} готово · 🟨 {partial} частично · 🟥 {todo} не реализовано"),
}


def counts(text):
    marks = ITEM.findall(text)
    done = marks.count("✅")
    partial = marks.count("🟡")
    return done, partial, len(marks) - done - partial, len(marks)


def bar(done, partial, total):
    if not total:
        return "🟥" * CELLS
    green = round(done / total * CELLS)
    yellow = round(partial / total * CELLS)
    red = max(0, CELLS - green - yellow)
    return "🟩" * green + "🟨" * yellow + "🟥" * red


def block(name, text):
    done, partial, todo, total = counts(text)
    pct = round(done / total * 100) if total else 0
    body = TEXT[name].format(bar=bar(done, partial, total), pct=pct,
                             done=done, partial=partial, todo=todo, total=total)
    return f"{START}\n{body}\n{END}", (done, partial, todo, total, pct)


def main():
    write = "--write" in sys.argv[1:]
    failed = False
    for name in TEXT:
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        new_block, (done, partial, todo, total, pct) = block(name, text)
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
