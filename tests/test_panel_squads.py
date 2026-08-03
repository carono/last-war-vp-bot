r"""Where the squads are, and how much stamina is left — `panel/runtime/squads.py`.

The reading itself is a scenario (`actions/read_squad_state.md`); what is pinned here is
the panel's side of it, and in the order it quietly breaks:

* **a squad that is out must not read as being at home.** `at_base` is the gate every
  send is judged by, and it is TWO facts — the game's `Free` state and its own idle flag
  — because a half-updated reading satisfies one of them alone.
* **«cannot read» is not «not at home».** A failed reading answers `None`, never
  `False`: a gate that cannot see must let the send go and let the scenario say what
  happened, or a daemon hiccup silently stops every rally the panel would have raised.
* **a rally is recognised however it is spelled** — the march status (`WAIT_RALLY` /
  `IN_TEAM`), the march kind (`ASSEMBLY_MARCH`), or simply belonging to a team.
* **the poll is reference-counted**: the first watcher starts it, the last one stops it,
  so a tab nobody has open costs no game reads.
* **one read serves everybody**: a second caller arriving while a read is in flight
  waits for that one rather than starting a second.

No Tk, no game, no daemon — the scenario is replaced by a stub that returns a line::

    python3 tests/test_panel_squads.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "src", _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# The module is loaded from its file rather than as `panel.runtime.squads`: importing
# the package pulls in the settings binder and with it tkinter, which the WSL python
# does not have — and this module needs neither. It imports nothing but the standard
# library, which is exactly why it can be tested anywhere.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "panel_runtime_squads", _REPO_ROOT / "panel" / "runtime" / "squads.py")
sq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sq)

# What the recipe answers with when every squad is home (taken off a live client).
HOME_LINE = ("stamina=102 max=120 full=1785777706685 | "
             "squad=1 state=0 free=1 soldiers=0 status=- march=- team=0 point=- arrive=0 | "
             "squad=2 state=0 free=1 soldiers=0 status=- march=- team=0 point=- arrive=0 | "
             "squad=3 state=0 free=1 soldiers=0 status=- march=- team=0 point=- arrive=0")

# One out gathering, one standing in a rally, one wiped.
BUSY_LINE = (
    "stamina=44 max=120 full=1785777706685 | "
    "squad=1 state=1 free=0 soldiers=3123 status=COLLECTING march=NORMAL team=0 "
    "point=749650 arrive=1785766040800 | "
    "squad=2 state=1 free=0 soldiers=2565 status=WAIT_RALLY march=ASSEMBLY_MARCH "
    "team=1399660254475822866 point=549550 arrive=1785766133782 | "
    "squad=3 state=3 free=0 soldiers=0 status=- march=- team=0 point=- arrive=0")


# ---------------------------------------------------------------------------
# the parse
# ---------------------------------------------------------------------------
def test_a_home_reading_is_three_squads_at_base():
    state = sq.parse(HOME_LINE)
    assert state.ok, state.error
    assert [s.index for s in state.squads] == [1, 2, 3]
    assert all(s.at_base for s in state.squads)
    assert all(s.kind == sq.HOME for s in state.squads)
    assert (state.stamina, state.stamina_max) == (102, 120)
    assert state.stamina_full_ms == 1785777706685


def test_each_kind_of_busy_is_named():
    state = sq.parse(BUSY_LINE)
    assert state.ok, state.error
    assert state.kind(1) == sq.GATHERING
    assert state.kind(2) == sq.RALLY
    assert state.kind(3) == sq.BROKEN
    assert not any(s.at_base for s in state.squads)
    assert state.stamina == 44


def test_a_rally_is_seen_by_team_kind_or_status():
    by_status = sq.Squad(1, state=1, status="IN_TEAM")
    by_march = sq.Squad(1, state=1, status="MOVING", march="ASSEMBLY_MARCH")
    by_team = sq.Squad(1, state=1, status="MOVING", team="1399660254475822866")
    for squad in (by_status, by_march, by_team):
        assert squad.kind == sq.RALLY, squad
    # …and a plain march is not one.
    assert sq.Squad(1, state=1, status="MOVING").kind == sq.MARCHING


def test_wiped_beats_whatever_it_was_doing():
    # A squad that was wiped may still carry the march it died on; what the operator
    # needs to hear is that it is broken, not where it was going.
    squad = sq.Squad(2, state=3, status="MOVING", march="MONSTER")
    assert squad.kind == sq.BROKEN
    assert not squad.at_base


def test_half_a_reading_is_not_at_base():
    # `state` says Free, the idle flag does not (or the other way round) — the gate
    # must not open on either half alone.
    assert not sq.Squad(1, state=0, free=False).at_base
    assert not sq.Squad(1, state=1, free=True).at_base
    assert sq.Squad(1, state=0, free=True).at_base


def test_junk_is_not_a_reading():
    for raw in ("", "   ", None, "nothing here", "stamina=1 max=2 full=0"):
        state = sq.parse(raw)
        assert not state.ok, raw
        assert state.squads == [] or not state.error


# ---------------------------------------------------------------------------
# the reader
# ---------------------------------------------------------------------------
class _FakeOutcome:
    def __init__(self, line, ok=True, reason=""):
        self.ok, self.reason = ok, reason
        self.ctx = type("Ctx", (), {"vars": {"squads": line}})()


class _FakeActions:
    def __init__(self, line):
        self.line, self.calls, self.delay = line, 0, 0.0

    def play(self, name, args=None, **kw):
        assert name == sq.ACTION, name
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if isinstance(self.line, Exception):
            raise self.line
        return _FakeOutcome(self.line)


class _FakeGame:
    def __init__(self, up=True):
        self._up = up

    def up(self):
        return self._up


class _FakeBus:
    def __init__(self):
        self.published, self.subs = [], []

    def publish(self, topic, payload=None):
        self.published.append((topic, payload))
        for func in list(self.subs):
            func(payload)

    def subscribe(self, topic, func):
        self.subs.append(func)
        return lambda: self.subs.remove(func)


class _FakeTick:
    def __init__(self):
        self.armed = {}

    def arm(self, name, delay_ms, func):
        self.armed[name] = (delay_ms, func)

    def disarm(self, name):
        self.armed.pop(name, None)


class _FakeRuntime:
    def __init__(self, line=HOME_LINE, up=True, root=object()):
        self.actions = _FakeActions(line)
        self.game = _FakeGame(up)
        self.bus = _FakeBus()
        self.tick = _FakeTick()
        self.root = root


def test_a_reading_is_cached_and_published():
    rt = _FakeRuntime()
    reader = sq.SquadReader(rt)
    first = reader.read()
    assert first.ok and rt.actions.calls == 1
    assert reader.read() is first, "a fresh reading is answered from the cache"
    assert rt.actions.calls == 1
    assert rt.bus.published[0][0] == sq.TOPIC
    assert reader.latest() is first


def test_force_re_reads():
    rt = _FakeRuntime()
    reader = sq.SquadReader(rt)
    reader.read()
    reader._state.at -= sq.FRESH_SEC + 1       # pretend it aged past the cache window
    reader.read(force=True)
    assert rt.actions.calls == 2


def test_no_daemon_is_an_unreadable_state_not_a_refusal():
    rt = _FakeRuntime(up=False)
    reader = sq.SquadReader(rt)
    state = reader.read()
    assert not state.ok and state.error == "offline"
    assert rt.actions.calls == 0
    assert reader.at_base(1) is None, "cannot see ≠ not at home"


def test_a_broken_scenario_is_survived():
    rt = _FakeRuntime(line=RuntimeError("daemon went away"))
    reader = sq.SquadReader(rt)
    state = reader.read()
    assert not state.ok and "daemon went away" in state.error
    assert reader.at_base(2) is None


def test_at_base_answers_off_the_reading():
    reader = sq.SquadReader(_FakeRuntime())
    assert reader.at_base(1) is True
    reader = sq.SquadReader(_FakeRuntime(line=BUSY_LINE))
    assert reader.at_base(1) is False
    assert reader.at_base(9) is None, "a slot the game does not list is not a refusal"


def test_one_read_serves_two_callers():
    rt = _FakeRuntime()
    rt.actions.delay = 0.25
    reader = sq.SquadReader(rt)
    out = []
    threads = [threading.Thread(target=lambda: out.append(reader.read(force=True)))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert rt.actions.calls == 1, rt.actions.calls
    assert len({id(state) for state in out}) == 1


def test_the_poll_lives_as_long_as_its_watchers():
    rt = _FakeRuntime()
    reader = sq.SquadReader(rt)
    assert sq.TOPIC not in rt.tick.armed
    off_one = reader.watch(lambda state: None)
    off_two = reader.watch(lambda state: None)
    assert sq.TOPIC in rt.tick.armed, "the first watcher starts the poll"
    off_one()
    assert sq.TOPIC in rt.tick.armed, "…and one leaving does not stop it"
    off_two()
    assert sq.TOPIC not in rt.tick.armed, "the last one out stops it"


def test_a_watcher_hears_every_reading():
    rt = _FakeRuntime()
    reader = sq.SquadReader(rt)
    heard = []
    off = reader.watch(heard.append)
    reader.read(force=True)
    off()
    reader.read(force=True)
    assert len(heard) == 1 and heard[0].ok


def test_no_root_means_no_poll_but_reads_still_work():
    rt = _FakeRuntime(root=None)
    reader = sq.SquadReader(rt)
    reader.start()
    assert sq.TOPIC not in rt.tick.armed
    assert reader.read().ok


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                   # noqa: BLE001 — a crash is a failure
            failed += 1
            print(f"  ERROR {test.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
