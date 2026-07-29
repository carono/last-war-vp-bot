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
    C:\Python312\python.exe tools\find_treasures.py --watch --for 120m --every 3m --queue

Exit code 0 when at least one treasure was found, 1 when there is nothing to dig — so a
scheduler can gate `work_treasure.md` on it.

`--watch` turns the one-shot look into a wait: it repeats the ask-and-read until a
treasure shows up (exit 0, parked if `--queue`) or the window runs out (exit 1). That is
the practical mode here, because a treasure is not a standing feature of the map — it
exists only while the alliance's detect event has one out, and it is dug away fast. One
look answers "right now"; the watch answers "the next one that appears".

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

# The activity ids to ask `activity.detect.list` for, when the client cannot say.
# Normally they come from the manager's own `dailyGot` keys — but that table is filled
# by a reply too, so right after a client restart it is EMPTY and the finder would ask
# for nothing and report "no treasure" without ever having looked (seen live on
# 2026-07-29, a fresh session read `tracked activity ids=(none)`). These are the keys
# this account has been seen tracking; `--ids` overrides them.
KNOWN_ACTIVITY_IDS = (25193, 25194, 25196)


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


def _look(ev, forced_ids, quiet=False):
    """One ask-and-read round; returns True when the client knows of a treasure.

    `quiet` keeps the repeat rounds of a watch from repeating the same empty report —
    but a round that FINDS something prints in full either way, raw record lines
    included: that dump is how the never-yet-seen record shape gets confirmed.
    """
    held = []

    def say(*a):
        if quiet:
            held.append(a)
        else:
            print(*a, flush=True)

    out, num, daily_ids = _read_state(ev)
    if forced_ids is not None:
        ids, source = forced_ids, "--ids"
    elif daily_ids:
        ids, source = daily_ids, "tracked by the client"
    else:
        ids, source = list(KNOWN_ACTIVITY_IDS), "known ids (the client tracks none yet)"
    say("before refresh: treasures_num=%s, activity ids=%s [%s]" % (num, ids, source))

    for line in ev.run(A.treasure_refresh_request(ids), marker="ACT", settle=1.5):
        if "treasure_ask" in line:
            say(" ", line.split("ACT ", 1)[-1])
    time.sleep(2.5)

    out, num, _ = _read_state(ev)
    records = _lines(out, "treasure_rec ")
    say("after refresh: treasures_num=%s, dataDict entries=%s, record lines=%d"
        % (num, _value(out, "treasure_dict_count=", "?"), len(records)))
    for line in records:
        say("  ", line.split("ACT ", 1)[-1])
    for line in _lines(out, "treasure_daily "):
        say("  ", line.split("ACT ", 1)[-1], "(taken today)")

    found = bool(records) or (num.isdigit() and int(num) > 0)
    if found and held:
        for a in held:
            print(*a, flush=True)
    return found


def _park(ev):
    """Park what was found on the recipe's queue; prints one line per target."""
    parked = ev.run(A.park_treasures(int(DEFAULT_SERVER or 0)), marker="ACT", settle=1.5)
    for line in _lines(parked, "treasure_target "):
        print("  ", line.split("ACT ", 1)[-1], flush=True)
    n = _value(parked, "treasure_parked ", "0")
    print("parked %s target(s) on DataCenter.__lw_treasure_queue - "
          "run actions/dev/work_treasure.md to dig/collect them" % n, flush=True)


def _duration(raw, unit_default=1):
    """`90` / `90s` / `3m` / `2h` -> seconds. Bare numbers use `unit_default`."""
    raw = str(raw).strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600}.get(raw[-1:], None)
    if mult is None:
        return int(float(raw) * unit_default)
    return int(float(raw[:-1]) * mult)


def _opt(argv, name, default, unit_default=1):
    return _duration(argv[argv.index(name) + 1], unit_default) if name in argv else default


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    queue = "--queue" in argv
    watch = "--watch" in argv
    every = _opt(argv, "--every", 120, unit_default=1)     # bare number = seconds
    window = _opt(argv, "--for", 3600, unit_default=60)    # bare number = minutes
    forced_ids = None
    if "--ids" in argv:
        raw = argv[argv.index("--ids") + 1]
        forced_ids = [int(x) for x in raw.replace(" ", "").split(",") if x]

    ev = get_evaluator()
    try:
        if not watch:
            if not _look(ev, forced_ids):
                print("NO TREASURE - nothing to dig or collect "
                      "(no detect event running, or its treasures are gone/expired)",
                      flush=True)
                return 1
            if queue:
                _park(ev)
            else:
                print("TREASURE FOUND - re-run with --queue to park it for work_treasure.md",
                      flush=True)
            return 0

        deadline = time.time() + window
        print("watching for a treasure: every %ds, giving up in %dm"
              % (every, window // 60), flush=True)
        rounds = 0
        while True:
            rounds += 1
            found = _look(ev, forced_ids, quiet=rounds > 1)
            if found:
                print("round %d: TREASURE FOUND" % rounds, flush=True)
                if queue:
                    _park(ev)
                return 0
            left = int(deadline - time.time())
            if left <= 0:
                print("gave up after %d round(s): no treasure appeared in the window "
                      "(the alliance's detect event has to put one on the map first)"
                      % rounds, flush=True)
                return 1
            print("round %d: still nothing, %dm%02ds left" % (rounds, left // 60, left % 60),
                  flush=True)
            time.sleep(min(every, left))
    finally:
        ev.close()


if __name__ == "__main__":
    sys.exit(main())
