r"""Donate to the alliance's PRIORITY (server-recommended) tech — no pixel clicks.

Reproduces exactly what a player does in Alliance -> Alliance Tech: pick the tech
the alliance recommends, then hammer the "Donate 1000" button until the daily
attempts run out. Everything runs inside the game's own Lua VM through the warm
daemon (tools/lua_daemon.py); there is no screen reading and no foreground input.

The donation logic lives in `tools/lib/alliance_science.py`; the DSL does the same
job through `TAP` and the button catalogue (src/lastwar_bot/actions/donate_alliance_tech.md).
The confirmed API and the reverse-engineering are written up in
docs/research/alliance-tech-donate.md.

Usage:
    /mnt/c/Python312/python.exe tools/alliance_donate.py          # donate all attempts
    /mnt/c/Python312/python.exe tools/alliance_donate.py --status # read-only report
    /mnt/c/Python312/python.exe tools/alliance_donate.py --max 5  # cap the presses
    /mnt/c/Python312/python.exe tools/alliance_donate.py --gold   # spend diamonds (!)
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "tools/lib")
import alliance_science  # noqa: E402
import lua_client  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Donate to the alliance priority tech.")
    ap.add_argument("--status", action="store_true", help="report only, do not donate")
    ap.add_argument("--gold", action="store_true", help="use diamond donations (spends gems!)")
    ap.add_argument("--max", type=int, default=None, help="cap the number of presses")
    args = ap.parse_args()

    ev = lua_client.get_evaluator()

    def run(chunk, marker=None, settle=1.4):
        return ev.run(chunk, marker, settle)

    def log(msg):
        print(msg, flush=True)

    if args.status:
        st = alliance_science.read_status(run)
        log("PRIORITY tech: scienceId=%s  level=%s  progress=%s"
            % (st.get("recId"), st.get("curLevel"), st.get("progress")))
        log("ATTEMPTS: resource=%s  gold=%s  canDonate=%s"
            % (st.get("resRest"), st.get("goldRest"), st.get("canDonate")))
        return 0

    alliance_science.donate_priority(run, use_gold=args.gold, cap=args.max, log=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
