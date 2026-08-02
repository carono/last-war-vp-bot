"""``python -m panel.tabs`` — what tabs exist, and how to run one.

The registry is the answer to "which tabs are there", so it is also the answer to
"what can I launch". Nothing here imports a tab: the listing is the spec table, which
is the whole point of the specs holding an import path rather than a class.
"""
from __future__ import annotations

import sys

from . import TABS


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] not in ("--list", "-l"):
        print(f"usage: python -m panel.tabs [--list]\n"
              f"       python -m panel.tabs.<id> [--profile NAME] [--help]",
              file=sys.stderr)
        return 2
    width = max(len(s.id) for s in TABS)
    print(f"{'id'.ljust(width)}  order  default  module")
    for spec in sorted(TABS, key=lambda s: s.order):
        mark = "on " if spec.default_enabled else "off"
        print(f"{spec.id.ljust(width)}  {spec.order:>5}  {mark:>7}  {spec.module}")
    print(f"\nRun one on its own:  python -m panel.tabs.<id> --profile <name>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
