r"""Hospital heal — what the primitive reads before it heals, and what it sends.

The healing press is one ``hospital.cure`` (docs/research/hospital-heal.md); the headless
"heal all" first reads how many soldier types are wounded and only sends when that is
positive, so a healthy army never spends a server round trip. Collecting the healed ones
is gated the same way on the heal timer having finished. All of it is checked here
against an evaluator stub — no game and no capture needed. Run it anywhere::

    python3 tests/test_hospital.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hospital  # noqa: E402
import lua_actions  # noqa: E402


class FakeEval:
    """Answers the gate reads from a script, records every send.

    ``wounded`` / ``ready`` are the sequences of answers the two gate reads give (the last
    repeats); ``None`` stands for an unreadable gate. Any chunk that carries a send is
    recorded and answered as a success unless ``send_error`` / ``skip`` is set.
    """

    def __init__(self, wounded=(0,), ready=(0,), send_error=None, skip=None, free=None):
        self.wounded = list(wounded)
        self.ready = list(ready)
        self.send_error = send_error
        self.skip = skip
        self.free = free
        self.reads = 0
        self.ready_reads = 0
        self.heals = 0
        self.collects = 0
        self.last_chunk = None

    def run(self, chunk, marker=None, settle=1.2):
        self.last_chunk = chunk
        if "wounded=" in chunk:
            self.reads += 1
            v = self.wounded[min(self.reads, len(self.wounded)) - 1]
            return ["%s wounded=%s" % (hospital.MARKER, "ERR" if v is None else v)]
        if "ready=" in chunk:
            self.ready_reads += 1
            v = self.ready[min(self.ready_reads, len(self.ready)) - 1]
            return ["%s ready=%s" % (hospital.MARKER, "ERR" if v is None else v)]
        if "heal=" in chunk:
            self.heals += 1
            if self.send_error:
                return ["%s heal=ERR:%s" % (hospital.MARKER, self.send_error)]
            if self.skip:
                return ["ACT hospital_heal_all skip: %s" % self.skip]
            out = ["%s heal=ok" % hospital.MARKER]
            if self.free is not None:
                out.insert(0, "ACT hospital_heal_all types=1 freeq=%d" % self.free)
            return out
        if "hospital_collect" in chunk:
            self.collects += 1
            if self.skip:
                return ["ACT hospital_collect skip: %s" % self.skip]
            return ["ACT hospital_collect pressed"]
        # `cure()` sends an ACT-marked fire-and-forget with no reply to parse.
        self.heals += 1
        return []


def _check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        raise SystemExit(1)


# -- wounded_types -----------------------------------------------------------

def test_wounded_types_reads_the_number():
    ev = FakeEval([3])
    _check("wounded_types returns the count", hospital.wounded_types(ev.run) == 3)


def test_wounded_types_unreadable_is_none_not_zero():
    ev = FakeEval([None])
    _check("unreadable gate is None, not 0", hospital.wounded_types(ev.run) is None)


def test_wounded_count_counts_the_hospital_rows():
    expr = lua_actions.hospital_wounded_count()
    _check("counts HospitalManager rows", "HospitalManager" in expr and "allHospital" in expr)
    _check("...by the wounded field", "h.dead > 0" in expr)
    _check("...not by the window's own suggestion", "curCount" not in expr)


# -- heal_all: the gate ------------------------------------------------------

def test_heal_all_no_wounded_sends_nothing():
    ev = FakeEval([0])
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("healthy army heals nothing", n == 0 and ev.heals == 0)
    _check("...and says so", any("nothing to heal" in m for m in logs))


def test_heal_all_unreachable_sends_nothing():
    ev = FakeEval([None])
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("unreachable VM heals nothing", n == 0 and ev.heals == 0)
    _check("...and says unreachable", any("unreachable" in m for m in logs))


def test_heal_all_wounded_sends_once():
    ev = FakeEval([2])
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("wounded army heals once", n == 2 and ev.heals == 1)
    _check("...and reports the type count", any("healed 2" in m for m in logs))


def test_heal_all_send_error_is_surfaced():
    ev = FakeEval([1], send_error="boom")
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("a failed send returns 0", n == 0)
    _check("...and surfaces the error", any("boom" in m for m in logs))


def test_heal_all_skip_is_surfaced_as_zero():
    ev = FakeEval([1], skip="no wounded soldiers")
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("a skipped send returns 0", n == 0)
    _check("...and surfaces the skip reason", any("skipped" in m for m in logs))


def test_heal_all_never_blames_the_building_queues():
    # A recorded human press went through with all four Default queues working, so a heal
    # does NOT take one. An earlier build warned about that and the warning was false.
    ev = FakeEval([1], free=0)
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("the send happened", n == 1 and ev.heals == 1)
    _check("...and nothing blames the queues", not any("building queue" in m for m in logs))


def test_heal_all_builds_from_the_hospital_rows():
    chunk = lua_actions.hospital_heal_all()
    _check("heal_all reads the hospital", "allHospital" in chunk)
    _check("...takes the whole wounded batch", "count = math.floor(h.dead)" in chunk)
    _check("...and sends hospital.cure", "MsgDefines.HospitalCure" in chunk)


# -- cure: the message shape -------------------------------------------------

def test_cure_builds_the_message():
    chunk = lua_actions.hospital_cure([("3014", 80)])
    _check("cure names hospital.cure", "SFSNetwork.SendMessage(MsgDefines.HospitalCure" in chunk)
    _check("cure carries armyArray", "armyArray=" in chunk)
    _check("armyId is a string", 'armyId="3014"' in chunk)
    _check("the per-entry count is an int", "count=80" in chunk)


def test_cure_carries_gold_and_nothing_else():
    # `gold` is mandatory (the serialiser packs it as an int). The pay-to-finish fields are
    # NOT: sending them takes the client down the branch that omits armyArray entirely and
    # the server answers E000000 — which is what the 20260729_182527 recording showed.
    chunk = lua_actions.hospital_cure([("3014", 1)])
    _check("cure carries gold=0", "gold=0" in chunk)
    for field in ("goldForTime", "goldForResource", "itemIds"):
        _check("cure does NOT carry %s" % field, field not in chunk)


def test_heal_all_carries_gold_and_nothing_else():
    chunk = lua_actions.hospital_heal_all()
    _check("heal_all carries gold = 0", "gold = 0" in chunk)
    for field in ("goldForTime", "goldForResource", "itemIds"):
        _check("heal_all does NOT carry %s" % field, field not in chunk)


def test_cure_multiple_types():
    chunk = lua_actions.hospital_cure([("3014", 80), ("3015", 5)])
    _check("both types present", 'armyId="3014"' in chunk and 'armyId="3015"' in chunk)
    _check("entry count logged", "entries=2" in chunk)


def test_cure_empty_is_noop():
    ev = FakeEval([0])
    _check("empty cure sends nothing", hospital.cure(ev.run, []) is None and ev.heals == 0)


# -- collect: gated on the heal timer ----------------------------------------

def test_collect_waits_for_the_timer():
    ev = FakeEval(ready=[0])
    logs = []
    n = hospital.collect(ev.run, logs.append)
    _check("a running heal collects nothing", n == 0 and ev.collects == 0)
    _check("...and says so", any("no finished heal" in m for m in logs))


def test_collect_unreachable_sends_nothing():
    ev = FakeEval(ready=[None])
    logs = []
    n = hospital.collect(ev.run, logs.append)
    _check("unreachable VM collects nothing", n == 0 and ev.collects == 0)
    _check("...and says unreachable", any("unreachable" in m for m in logs))


def test_collect_finished_heal_presses_once():
    ev = FakeEval(ready=[1])
    logs = []
    n = hospital.collect(ev.run, logs.append)
    _check("a finished heal is collected", n == 1 and ev.collects == 1)
    _check("...and reports it", any("collected" in m for m in logs))


def test_collect_uses_the_games_own_gate():
    chunk = lua_actions.hospital_collect()
    _check("collect presses CheckSendFinish", "CheckSendFinish" in chunk)
    _check("...with the hospital building", "GetCurHospitalBuildUuid" in chunk)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} hospital tests")
    for t in tests:
        print(t.__name__)
        t()
    print("all green")
