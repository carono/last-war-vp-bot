r"""«Вторжение зомби»: the hunt does not run outside the event's window (#2647).

The report was «карточка с золотыми зомби работает и без события вторжение зомби, нужно
учитывать и не гонять в пустую». What is pinned here:

  * the recipe holds the gate — every golden-zombie chain reads the invasion BEFORE it
    switches scenes, refills a squad, claims the day's energy or buys one for diamonds,
    and stops on a closed reading;
  * the schedule holds the SECOND one: while the panel already knows the event is shut,
    the errand is not started at all — no claim, no context, not one reading;
  * ignorance is never a refusal. No reading, a stale one, or one whose own «next
    window» has come round lets the run go and look;
  * and the ear has no clock in it — the client entering the game, the invasion's own
    record, and the bounded first look #2636 wrote, and nothing else.

Needs no display, no game and no database:

    python3 tests/test_invasion_live.py
"""
from __future__ import annotations

TIER = "unit"

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tools" / "lib", ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from panel.runtime import bus as busmod           # noqa: E402 — path wired up above
from panel.runtime import claims as claimsmod     # noqa: E402
from panel.runtime import invasion_live as inv    # noqa: E402

OPEN = ("open=1 inv=5 act=80024 starts=1788832800 ends=1788919199 season=6 day=57 "
        "next_day=57 next_at=0 seen=135 asked=0")
SHUT = ("open=0 inv=0 act=0 starts=0 ends=0 season=6 day=16 next_day=57 "
        "next_at=1792375200 seen=0 asked=1")

#: The three recipes that spend energy on golden zombies. Every one of them is gated.
HUNTS = ("attack_golden_zombies", "attack_golden_zombies2", "attack_golden_zombies_pair")


class _Store:
    def __init__(self) -> None:
        self.blobs: dict = {}

    def blob_get(self, name: str):
        return self.blobs.get(name)

    def blob_set(self, name: str, value) -> None:
        self.blobs[name] = value


class _Bus:
    def __init__(self) -> None:
        self.subs: dict = {}

    def subscribe(self, topic, func):
        self.subs.setdefault(topic, []).append(func)
        return lambda: self.subs[topic].remove(func)

    def publish(self, topic, payload=None):
        for func in list(self.subs.get(topic, ())):
            func(payload)


class _Wire(_Bus):
    pass


class _Gate:
    def __init__(self, shut: bool) -> None:
        self.shut = shut

    def held(self) -> bool:
        return self.shut


class _Tick:
    def __init__(self) -> None:
        self.armed: list = []

    def arm(self, name, delay_ms, func) -> None:
        self.armed.append((name, delay_ms, func))

    def fire(self) -> None:
        booked, self.armed = self.armed, []
        for _name, _delay, func in booked:
            func()


class _Schedule:
    def __init__(self) -> None:
        self.before: dict = {}
        self.reports: dict = {}

    def register_precondition(self, name, check) -> None:
        self.before[name] = check

    def register_report(self, name, hook) -> None:
        self.reports[name] = hook


class _Runtime:
    def __init__(self, refuse: bool = False, gate_held: bool = False) -> None:
        self.store = _Store()
        self.bus = _Bus()
        self.wire = _Wire()
        self.tick = _Tick()
        self.schedule = _Schedule()
        self.plays: list = []
        self.refuse = refuse
        self.gate = _Gate(gate_held)

    def dbg(self, _tag):
        class _Log:
            def error(self, *_a, **_k):
                pass
        return _Log()

    def play_async(self, name, args=None, **kw):
        self.plays.append((name, kw.get("tag"), kw.get("priority")))
        if self.refuse:
            return False
        on_result = kw.get("on_result")
        if on_result is not None:
            on_result(_Outcome(SHUT))
        return True


class _Outcome:
    def __init__(self, line: str) -> None:
        self.ok = True
        self.ctx = type("Ctx", (), {"vars": {inv.VARIABLE: line}})()


# -- the recipe's own gate ----------------------------------------------------------
def test_every_hunt_reads_the_invasion_before_it_spends_anything():
    for name in HUNTS:
        text = (ROOT / "src" / "lastwar_bot" / "actions" / f"{name}.md").read_text(
            encoding="utf-8")
        lines = [ln.strip() for ln in text.split("\n")]
        gate = lines.index("CALL read_zombie_invasion")
        for costly in ("GAME WORLD", "CALL fill_empty_squads",
                       "CALL claim_free_stamina", "CALL buy_stamina_refill"):
            if costly in lines:
                assert gate < lines.index(costly), (name, costly)
        assert "IF inv_open == 0" in lines, name
        assert any(ln.startswith("STOP ") and "Invasion" in ln for ln in lines), name


def test_the_reading_recipe_asks_the_game_and_never_a_calendar():
    text = (ROOT / "src" / "lastwar_bot" / "actions"
            / "read_zombie_invasion.md").read_text(encoding="utf-8")
    for wanted in ("ActivityMonsterInvasionDataManager", "invasionId",
                   "GetInvasionActivityId", "advanced_monster_invasion",
                   "GetNowSeasonAndSeasonDay"):
        assert wanted in text, wanted
    for var in ("INTO inv_open", "INTO inv_ends", "INTO inv_next_at", "INTO inv_seen"):
        assert var in text, var
    # A DATE IS NEVER WRITTEN DOWN. The window is a season day the client's own config
    # names, judged against the day the game says the season is on — so no year, no
    # timestamp and no epoch is spelled out in what actually RUNS.
    import re                                     # noqa: PLC0415 — one check, here
    for line in text.split("\n"):
        if line.startswith("#") or not line.strip():
            continue
        assert not re.search(r"\b\d{10,}\b", line), line       # no epoch stamp
        assert not re.search(r"\d{4}-\d{2}-\d{2}", line), line   # and no date


# -- the schedule's gate ------------------------------------------------------------
def test_a_shut_event_holds_the_errand_back_without_a_single_reading():
    rt = _Runtime()
    inv.record(rt, SHUT)
    inv.wire(rt)
    check = rt.schedule.before[inv.ERRAND]
    assert check() == inv.SKIP_KEY
    assert rt.plays == [], "holding an errand back must cost nothing at all"


def test_a_running_event_does_not_hold_anything_back():
    rt = _Runtime()
    inv.record(rt, OPEN)
    assert inv.precondition(rt) is None


def test_ignorance_is_never_a_refusal():
    rt = _Runtime()
    assert inv.precondition(rt) is None, "no reading — the run goes and looks"
    inv.record(rt, SHUT)
    rt.store.blobs[inv.BLOB]["at"] = time.time() - inv.STALE_SEC - 1
    assert inv.precondition(rt) is None, "a stale reading is no reading"


def test_the_window_the_reading_named_reopens_the_errand():
    rt = _Runtime()
    inv.record(rt, SHUT)
    fields, _age = inv.state(rt)
    assert inv.precondition(rt, now=fields["next_at"] - 1) == inv.SKIP_KEY
    assert inv.precondition(rt, now=fields["next_at"] + 1) is None


def test_a_finished_hunt_refreshes_the_reading():
    rt = _Runtime()
    inv.wire(rt)
    ctx = type("Ctx", (), {"vars": {inv.VARIABLE: OPEN}})()
    rt.schedule.reports[inv.ERRAND](ctx)
    assert inv.state(rt)[0]["open"] == 1


# -- the ear -------------------------------------------------------------------------
def test_the_client_entering_the_game_takes_the_first_reading():
    rt = _Runtime()
    inv.InvasionWatch(rt).start()
    assert not rt.plays, "nothing may be read before the client is up"
    rt.bus.publish(busmod.GAME_READY)
    assert [p[0] for p in rt.plays] == [inv.ACTION], rt.plays
    assert rt.plays[0][2] == claimsmod.BACKGROUND, rt.plays


def test_a_burst_of_records_costs_one_reading():
    rt = _Runtime()
    inv.InvasionWatch(rt).start()
    for _ in range(5):
        rt.wire.publish(inv.PUSH)
    assert len(rt.plays) == 1, rt.plays


def test_there_is_no_clock_anywhere_in_the_ear():
    source = (ROOT / "panel" / "runtime" / "invasion_live.py").read_text(encoding="utf-8")
    for banned in ("after(", "threading.Timer", "Thread(", "while True"):
        assert banned not in source, banned
    assert source.count("tick.arm") == 1, "one booking, and it is the first look"


def test_a_shut_gate_is_waited_out_and_never_played_into():
    rt = _Runtime(gate_held=True)
    inv.InvasionWatch(rt).start()
    for _ in range(10):
        rt.tick.fire()
    assert rt.plays == [], "a shut gate must cost no play and no log line"
    assert len(rt.tick.armed) == 1, "…but the look must still be waiting"
    rt.gate.shut = False
    rt.tick.fire()
    assert [p[0] for p in rt.plays] == [inv.ACTION], rt.plays
    assert rt.tick.armed == [], "and it stops the moment it has read"


def test_a_gate_that_never_opens_does_not_wait_for_ever():
    rt = _Runtime(gate_held=True)
    inv.InvasionWatch(rt).start()
    for _ in range(inv.GATE_WAIT_TRIES + 5):
        rt.tick.fire()
    assert rt.plays == [], rt.plays
    assert rt.tick.armed == [], "a client that never comes back leaves no booking"


# -- the words -----------------------------------------------------------------------
def test_every_locale_has_the_words_for_it():
    keys = ("events.golden.invasion", "events.golden.invasion.next",
            "events.golden.invasion.on", "events.golden.invasion.off",
            "events.golden.invasion.running", "events.golden.invasion.in",
            inv.SKIP_KEY, "timers.stat.golden.closed", "timers.stat.golden.off")
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in words and words[key].strip(), (path.name, key)
        assert "{day}" in words["events.golden.invasion.in"], path.name
        assert "{left}" in words["events.golden.invasion.in"], path.name


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok  ", t.__name__)
        except Exception as exc:                  # noqa: BLE001 — a test runner
            bad += 1
            print("  FAIL", t.__name__, "->", exc)
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
