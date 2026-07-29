r"""World-map treasures — the finder: "is there anything to dig right now?" (task #1116)

`tools/dig_treasure.py` can march onto a treasure and claim it, and
`actions/dev/work_treasure.md` works a queue of them — but nothing filled that queue.
This is that missing step: it asks the server for the alliance's detect-treasure list,
reads `DataCenter.ActDetectTreasureDataManager` back, and (with `--queue`) parks the
targets on `DataCenter.__lw_treasure_queue` for the recipe.

Why a request first: the manager is a pure reply cache. Verified live by dumping its
functions — `GetArrData` only reads `self.dataDict[activityId]`, and the only writer is
`OnGetArrDataMsg`. Nothing polls on its own, so a session that never received a list
reply shows an empty dict whether or not a treasure exists. The request is
`activity.detect.list` and it needs an activity id (sent bare it dies in the serializer);
the ids asked for are the manager's own `dailyGot` keys, i.e. the treasure groups this
account tracks a daily count for.

Usage (Windows Python, so it reaches the warm Lua daemon)::

    C:\Python312\python.exe tools\find_treasures.py            # look and report
    C:\Python312\python.exe tools\find_treasures.py --queue    # ... and park the targets
    C:\Python312\python.exe tools\find_treasures.py --queue --ids 25194,25196

Exit code 0 when at least one treasure was found, 1 when there is nothing to dig — so a
scheduler can gate `work_treasure.md` on it.

CAVEAT, and it is the whole story of this feature: no treasure has been on the map during
any session that looked (the #1107 RE and this check both saw `treasures_num == 0`,
`dataDict` empty). The reading path here is confirmed; the *record field names* it maps
into queue entries are not, so `--queue` probes several spellings and the report prints
every record raw. The first live treasure confirms the shape — until then treat a
non-empty run as needing a look at the raw lines.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "tools/lib")
import lua_actions as A  # noqa: E402
from lua_client import get_evaluator  # noqa: E402
from tool_config import default_server  # noqa: E402

DEFAULT_SERVER = default_server()


def _lines(out, needle):
    return [x for x in out if needle in x]


def _value(out, needle, default=""):
    for x in _lines(out, needle):
        return x.split(needle, 1)[1].split()[0]
    return default


def _read_state(ev):
    """Run the state read; return (raw lines, treasures_num, dailyGot ids)."""
    out = ev.run(A.treasure_state(), marker="ACT", settle=1.5)
    num = _value(out, "treasures_num=", "?")
    ids = []
    for line in _lines(out, "treasure_daily "):
        key = line.split("treasure_daily ", 1)[1].split("=", 1)[0].strip()
        if key.isdigit():
            ids.append(int(key))
    return out, num, ids


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    queue = "--queue" in argv
    forced_ids = None
    if "--ids" in argv:
        raw = argv[argv.index("--ids") + 1]
        forced_ids = [int(x) for x in raw.replace(" ", "").split(",") if x]

    ev = get_evaluator()
    try:
        out, num, daily_ids = _read_state(ev)
        ids = forced_ids if forced_ids is not None else daily_ids
        print("before refresh: treasures_num=%s, tracked activity ids=%s"
              % (num, ids or "(none)"), flush=True)

        if ids:
            for line in ev.run(A.treasure_refresh_request(ids), marker="ACT", settle=1.5):
                if "treasure_ask" in line:
                    print(" ", line.split("ACT ", 1)[-1], flush=True)
            time.sleep(2.5)
        else:
            print("no activity ids to ask for - reading whatever the client already has",
                  flush=True)

        out, num, _ = _read_state(ev)
        records = _lines(out, "treasure_rec ")
        print("after refresh: treasures_num=%s, dataDict entries=%s, record lines=%d"
              % (num, _value(out, "treasure_dict_count=", "?"), len(records)), flush=True)
        for line in records:
            print("  ", line.split("ACT ", 1)[-1], flush=True)
        for line in _lines(out, "treasure_daily "):
            print("  ", line.split("ACT ", 1)[-1], "(taken today)", flush=True)

        found = bool(records) or (num.isdigit() and int(num) > 0)
        if not found:
            print("NO TREASURE - nothing to dig or collect "
                  "(no detect event running, or its treasures are gone/expired)", flush=True)
            return 1

        if queue:
            parked = ev.run(A.park_treasures(int(DEFAULT_SERVER or 0)),
                            marker="ACT", settle=1.5)
            for line in _lines(parked, "treasure_target "):
                print("  ", line.split("ACT ", 1)[-1], flush=True)
            n = _value(parked, "treasure_parked ", "0")
            print("parked %s target(s) on DataCenter.__lw_treasure_queue - "
                  "run actions/dev/work_treasure.md to dig/collect them" % n, flush=True)
        else:
            print("TREASURE FOUND - re-run with --queue to park it for work_treasure.md",
                  flush=True)
        return 0
    finally:
        ev.close()


if __name__ == "__main__":
    sys.exit(main())
