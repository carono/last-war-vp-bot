r"""Hospital heal — what the primitive reads before it heals, and what it sends.

The healing press is one ``hospital.cure`` whose shape is proven on the wire
(docs/research/hospital-heal.md); the headless "heal all" first reads how many soldier
types are wounded and only sends when that is positive, so a healthy army never spends a
server round trip. Both halves are checked here against an evaluator stub — no game and
no capture needed. Run it anywhere::

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
    """Answers the wounded-count read from a script, records every heal send.

    ``wounded`` is the sequence of answers the count read gives (the last repeats);
    ``None`` stands for an unreadable gate. Any chunk that carries the heal send is
    recorded and answered ``heal=ok`` unless ``send_error`` / ``skip`` is set.
    """

    def __init__(self, wounded, send_error=None, skip=None):
        self.wounded = list(wounded)
        self.send_error = send_error
        self.skip = skip
        self.reads = 0
        self.heals = 0
        self.last_chunk = None

    def run(self, chunk, marker=None, settle=1.2):
        self.last_chunk = chunk
        if "wounded=" in chunk:
            self.reads += 1
            v = self.wounded[min(self.reads, len(self.wounded)) - 1]
            return ["%s wounded=%s" % (hospital.MARKER, "ERR" if v is None else v)]
        if "heal=" in chunk:
            self.heals += 1
            if self.send_error:
                return ["%s heal=ERR:%s" % (hospital.MARKER, self.send_error)]
            if self.skip:
                return ["ACT hospital_heal_all skip: %s" % self.skip]
            return ["%s heal=ok" % hospital.MARKER]
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
    ev = FakeEval([1], skip="no wounded (or T11Util shape differs)")
    logs = []
    n = hospital.heal_all(ev.run, logs.append)
    _check("an unresolved-shape skip returns 0", n == 0)
    _check("...and surfaces the skip reason", any("skipped" in m for m in logs))


# -- cure: the proven message shape ------------------------------------------

def test_cure_builds_the_proven_message():
    chunk = lua_actions.hospital_cure([("3014", 80)])
    _check("cure names hospital.cure", 'SFSNetwork.SendMessage("hospital.cure"' in chunk)
    _check("cure carries armyArray", "armyArray=" in chunk)
    _check("armyId is a string", 'armyId="3014"' in chunk)
    _check("healNum is an int", "healNum=80" in chunk)


def test_cure_multiple_types():
    chunk = lua_actions.hospital_cure([("3014", 80), ("3015", 5)])
    _check("both types present", 'armyId="3014"' in chunk and 'armyId="3015"' in chunk)
    _check("entry count logged", "entries=2" in chunk)


def test_cure_empty_is_noop():
    ev = FakeEval([0])
    _check("empty cure sends nothing", hospital.cure(ev.run, []) is None and ev.heals == 0)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} hospital tests")
    for t in tests:
        print(t.__name__)
        t()
    print("all green")
