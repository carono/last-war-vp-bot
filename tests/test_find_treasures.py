r"""World-map treasure finder — what it asks the server, and how it calls "nothing to dig".

The finder (`tools/find_treasures.py`, task #1116) exists because
`ActDetectTreasureDataManager` is a pure reply cache: an empty `dataDict` means "no
treasure OR nobody asked", so the tool has to send `activity.detect.list` — with an
activity id, which it takes from the manager's own `dailyGot` keys — before it can call
the map empty. That request-then-read order and the verdict it draws are what is checked
here, against an evaluator stub: no game, no capture. Run it anywhere::

    python3 tests/test_find_treasures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import find_treasures as F  # noqa: E402
import lua_actions  # noqa: E402


class FakeEval:
    """Replays a manager state and records every chunk the finder runs.

    ``daily`` are the `dailyGot` cfg ids the state read reports; ``records`` are raw
    record lines (empty = nothing on the map); ``num`` is `treasures_num`.
    """

    def __init__(self, daily=(25194, 25196), records=(), num=0, parked=0):
        self.daily, self.records, self.num, self.parked = daily, list(records), num, parked
        self.asked = []          # activity ids the finder requested
        self.chunks = []
        self.closed = False

    def run(self, chunk, marker=None, settle=1.2):
        self.chunks.append(chunk)
        if "treasure_ask" in chunk:
            # the request chunk carries the ids as a Lua list literal
            ids = chunk.split("ipairs({", 1)[1].split("}", 1)[0]
            self.asked = [int(x) for x in ids.split(",") if x.strip()]
            return ["ACT treasure_ask id=%d ok=true err=nil" % i for i in self.asked]
        if "treasure_parked" in chunk:
            return (["ACT treasure_target pid=500553 uuid=1 srv=935 dug=false"] * self.parked
                    + ["ACT treasure_parked %d" % self.parked])
        # the state read
        out = ["ACT treasures_num=%d" % self.num]
        out += ["ACT treasure_daily %d=0" % i for i in self.daily]
        out += ["ACT treasure_rec %s" % r for r in self.records]
        out += ["ACT treasure_dict_count=%d" % len(self.records)]
        return out

    def close(self):
        self.closed = True


def _check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        raise SystemExit(1)


def _run(ev, argv):
    """Drive main() with a stubbed evaluator and no sleeping."""
    old_get, old_argv, old_sleep = F.get_evaluator, sys.argv, F.time.sleep
    F.get_evaluator = lambda: ev
    F.time.sleep = lambda _s: None
    sys.argv = ["find_treasures.py"] + argv
    try:
        return F.main()
    finally:
        F.get_evaluator, sys.argv, F.time.sleep = old_get, old_argv, old_sleep


# -- the request ------------------------------------------------------------

def test_asks_for_the_ids_the_manager_tracks():
    ev = FakeEval(daily=(25194, 25196))
    _run(ev, [])
    _check("asks activity.detect.list for both tracked ids", ev.asked == [25194, 25196])


def test_ids_can_be_forced():
    ev = FakeEval(daily=(25194,))
    _run(ev, ["--ids", "25193,25196"])
    _check("--ids overrides the tracked ones", ev.asked == [25193, 25196])


def test_no_ids_asks_nothing_but_still_reads():
    ev = FakeEval(daily=())
    code = _run(ev, [])
    _check("nothing to ask for -> no request sent", ev.asked == [])
    _check("...but the state is still read and reported empty", code == 1)


def test_reads_after_asking_not_before():
    ev = FakeEval()
    _run(ev, [])
    kinds = ["ask" if "treasure_ask" in c else "read" for c in ev.chunks]
    _check("order is read, ask, read", kinds[:3] == ["read", "ask", "read"])


# -- the verdict ------------------------------------------------------------

def test_empty_map_is_exit_1():
    ev = FakeEval(records=(), num=0)
    _check("nothing to dig exits 1", _run(ev, []) == 1)


def test_a_record_is_exit_0():
    ev = FakeEval(records=("25194 pointId=500553 uuid=1397117530950313784",), num=1)
    _check("a treasure exits 0", _run(ev, []) == 0)


def test_count_alone_is_enough_to_report_a_treasure():
    # treasures_num > 0 with an unparsed record shape must not read as "nothing"
    ev = FakeEval(records=(), num=2)
    _check("a positive count alone exits 0", _run(ev, []) == 0)


def test_queue_only_parks_when_something_was_found():
    ev = FakeEval(records=(), num=0)
    _run(ev, ["--queue"])
    _check("empty map parks nothing", not any("treasure_parked" in c for c in ev.chunks))

    ev2 = FakeEval(records=("25194 pointId=500553 uuid=1",), num=1, parked=1)
    _run(ev2, ["--queue"])
    _check("a found treasure gets parked", any("treasure_parked" in c for c in ev2.chunks))


def test_evaluator_is_closed_even_on_the_empty_path():
    ev = FakeEval(records=(), num=0)
    _run(ev, [])
    _check("the evaluator is released", ev.closed)


# -- the chunks -------------------------------------------------------------

def test_refresh_names_the_list_message_and_carries_ids():
    chunk = lua_actions.treasure_refresh_request([25194, 25196])
    _check("uses MsgDefines.ActivityDetectList",
           "MsgDefines.ActivityDetectList" in chunk)
    _check("passes an activity id (bare it dies in the serializer)",
           "25194" in chunk and "25196" in chunk)


def test_state_read_reports_count_dict_and_daily():
    chunk = lua_actions.treasure_state()
    for needle in ("treasures_num=", "treasure_daily ", "treasure_rec ", "treasure_dict_count="):
        _check("state read emits %s" % needle.strip(), needle in chunk)


def test_park_probes_several_field_spellings():
    chunk = lua_actions.park_treasures(935)
    for needle in ("'pointId','point_id','pid'", "'uuid','treasureUuid'",
                   "'targetServer','serverId','srcServer'", "'operatorUid','operator'"):
        _check("park probes %s" % needle, needle in chunk)
    _check("park writes the recipe's queue", "DataCenter.__lw_treasure_queue=q" in chunk)
    _check("cross is home-server relative", "tonumber(srv)~=935" in chunk)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} treasure-finder tests")
    for t in tests:
        print(t.__name__)
        t()
    print("all green")
